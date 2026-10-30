from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from pathlib import Path

from .config import Settings
from .hardware import capabilities
from .native import ProcessControl, RenderCancelled
from .pipeline import render_video
from .schemas import JobView, RenderOptions, Status, now_utc


class JobManager:
    """Single native GPU worker with queued jobs, status persistence and cancellation."""

    def __init__(self, settings: Settings, hardware_lock: threading.Lock | None = None):
        self.settings = settings
        self.hardware_lock = hardware_lock or threading.Lock()
        self.lock = threading.RLock()
        self.queue: queue.Queue[str | None] = queue.Queue()
        self.jobs: dict[str, JobView] = {}
        self.controls: dict[str, ProcessControl] = {}
        self.persisted: dict[str, float] = {}
        self._active: str | None = None
        self._closed = False
        self._restore()
        self.thread = threading.Thread(target=self._work, name="nvs-render-queue", daemon=True)
        self.thread.start()

    @property
    def active(self) -> bool:
        with self.lock:
            return self._active is not None

    def _record_path(self, job_id: str) -> Path:
        return self.settings.data / "jobs" / f"{job_id}.json"

    def _save(self, job: JobView, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self.persisted.get(job.id, -999) < 1.0:
            return
        path = self._record_path(job.id)
        temp = path.with_suffix(".tmp")
        temp.write_text(job.model_dump_json(indent=2), encoding="utf-8")
        temp.replace(path)
        self.persisted[job.id] = now

    def _restore(self) -> None:
        for path in (self.settings.data / "jobs").glob("*.json"):
            try:
                job = JobView.model_validate_json(path.read_text(encoding="utf-8"))
                if job.status in (Status.QUEUED, Status.RUNNING):
                    job.status, job.message = Status.FAILED, "Interrupted by server restart"
                    job.error, job.finished_at = job.message, now_utc()
                    self._save(job, force=True)
                self.jobs[job.id] = job
            except Exception:
                continue

    def submit(self, upload_id: str, filename: str, options: RenderOptions) -> JobView:
        with self.lock:
            if self._closed:
                raise RuntimeError("Job manager is shutting down")
            job = JobView(
                id=uuid.uuid4().hex, upload_id=upload_id,
                filename=filename, options=options
            )
            self.jobs[job.id] = job
            self._save(job, force=True)
            self.queue.put(job.id)
            return job.model_copy(deep=True)

    def get(self, job_id: str) -> JobView | None:
        with self.lock:
            item = self.jobs.get(job_id)
            return item.model_copy(deep=True) if item else None

    def all(self) -> list[JobView]:
        with self.lock:
            return [job.model_copy(deep=True) for job in sorted(self.jobs.values(),
                    key=lambda x: x.created_at, reverse=True)]

    def cancel(self, job_id: str) -> JobView | None:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return None
            if job.status == Status.QUEUED:
                job.status, job.message, job.finished_at = Status.CANCELLED, "Cancelled", now_utc()
                self._save(job, force=True)
            elif job.status == Status.RUNNING:
                job.message = "Stopping native worker and encoder"
                control = self.controls.get(job_id)
                if control:
                    control.stop()
                self._save(job, force=True)
            return job.model_copy(deep=True)

    def _progress(self, job_id: str, fraction: float, message: str) -> None:
        with self.lock:
            job = self.jobs[job_id]
            job.progress = max(0, min(1, fraction))
            job.message = message
            self._save(job)

    def _work(self) -> None:
        while True:
            job_id = self.queue.get()
            try:
                if job_id is None:
                    return
                with self.lock:
                    job = self.jobs[job_id]
                    if job.status != Status.QUEUED:
                        continue
                    job.status, job.started_at, job.message = Status.RUNNING, now_utc(), "Preparing"
                    control = ProcessControl()
                    self.controls[job_id], self._active = control, job_id
                    self._save(job, force=True)
                try:
                    from .uploads import UploadStore
                    source = UploadStore(self.settings).get(job.upload_id)
                    if source is None:
                        raise FileNotFoundError("Source upload has been removed")
                    caps = capabilities(self.settings)
                    if not caps["render_available"]:
                        raise RuntimeError(caps["reason"] + " Missing: " + ", ".join(caps["missing"]))
                    with self.hardware_lock:
                        control.check()
                        result = render_video(
                            self.settings, source.path, source.name, job_id,
                                job.options, lambda p, m: self._progress(job_id, p, m), control
                            )
                    with self.lock:
                        if control.cancelled.is_set():
                            result.video.unlink(missing_ok=True)
                            result.report.unlink(missing_ok=True)
                            raise RenderCancelled("Cancelled after render completion")
                        job.status = Status.COMPLETED
                        job.message = "Completed and verified"
                        job.progress = 1.0
                        job.output_filename = result.video.name
                        job.report_filename = result.report.name
                        job.frames = result.frames
                        job.elapsed_seconds = result.elapsed
                except RenderCancelled:
                    with self.lock:
                        job.status, job.message = Status.CANCELLED, "Cancelled"
                except Exception as exc:
                    with self.lock:
                        if control.cancelled.is_set():
                            job.status, job.message = Status.CANCELLED, "Cancelled"
                        else:
                            job.status, job.message = Status.FAILED, "Render failed"
                            job.error = f"{type(exc).__name__}: {exc}"
                finally:
                    with self.lock:
                        job.finished_at = now_utc()
                        self._save(job, force=True)
                        self.controls.pop(job_id, None)
                        self._active = None
            finally:
                self.queue.task_done()

    def shutdown(self) -> None:
        with self.lock:
            self._closed = True
            for control in self.controls.values():
                control.stop()
            self.queue.put(None)
        self.thread.join(timeout=5)
