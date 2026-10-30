from __future__ import annotations

from pathlib import Path
import mimetypes

from .media import run_command
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from .hardware import capabilities
from .preview import make_preview
from .schemas import JobRequest, PreviewRequest, PRESETS, Status
from .uploads import UploadStore

router = APIRouter(prefix="/api")


def s(request: Request):
    return request.app.state.settings


def jobs(request: Request):
    return request.app.state.jobs


@router.get("/health")
def health():
    return {"ok": True, "app": "Neural Video Studio", "version": "0.3.2"}


@router.get("/capabilities")
def system_capabilities(request: Request):
    return capabilities(s(request))


@router.get("/presets")
def presets():
    return {k.value: v for k, v in PRESETS.items()}


@router.post("/uploads", status_code=201)
async def upload_video(request: Request, file: Annotated[UploadFile, File()]):
    try:
        return (await UploadStore(s(request)).save(file)).public()
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc


@router.get("/uploads/{upload_id}/source")
def get_source(request: Request, upload_id: str):
    info = UploadStore(s(request)).get(upload_id)
    if not info:
        raise HTTPException(404, detail="Unknown upload")
    return FileResponse(info.path, media_type=mimetypes.guess_type(info.name)[0] or "application/octet-stream",
                        content_disposition_type="inline", filename=info.name)


@router.post("/jobs", status_code=201)
def create_job(request: Request, data: JobRequest):
    source = UploadStore(s(request)).get(data.upload_id)
    if not source:
        raise HTTPException(404, detail="Upload not found")
    try:
        return jobs(request).submit(source.id, source.name, data.options)
    except RuntimeError as exc:
        raise HTTPException(503, detail=str(exc)) from exc


@router.get("/jobs")
def get_jobs(request: Request):
    return jobs(request).all()


@router.get("/jobs/{job_id}")
def get_job(request: Request, job_id: str):
    record = jobs(request).get(job_id)
    if record is None:
        raise HTTPException(404, detail="Job not found")
    return record


@router.post("/jobs/{job_id}/cancel")
def cancel_job(request: Request, job_id: str):
    record = jobs(request).cancel(job_id)
    if record is None:
        raise HTTPException(404, detail="Job not found")
    return record


def result_path(request: Request, job_id: str, report: bool) -> Path:
    record = jobs(request).get(job_id)
    if record is None:
        raise HTTPException(404, detail="Job not found")
    if record.status != Status.COMPLETED:
        raise HTTPException(409, detail="Job is not completed")
    filename = record.report_filename if report else record.output_filename
    if not filename:
        raise HTTPException(404, detail="Result is missing")
    path = s(request).data / "outputs" / filename
    if not path.is_file() or path.parent.resolve() != (s(request).data / "outputs").resolve():
        raise HTTPException(404, detail="Output file not found")
    return path


@router.get("/jobs/{job_id}/download")
def download_result(request: Request, job_id: str):
    return FileResponse(result_path(request, job_id, False), media_type="application/octet-stream",
                        filename=jobs(request).get(job_id).output_filename)


@router.get("/jobs/{job_id}/video")
def watch_full_result(request: Request, job_id: str):
    """Serve verified full result inline; HEVC playback depends on browser support."""
    path = result_path(request, job_id, False)
    media = "video/mp4" if path.suffix.lower() == ".mp4" else "video/x-matroska"
    return FileResponse(path, media_type=media, content_disposition_type="inline")


@router.get("/jobs/{job_id}/sample")
def watch_short_sample(request: Request, job_id: str):
    """Build a cached 12-second H.264/AAC sample for browser inspection.

    Only works for completed/verified jobs. Generated independently of DLSS;
    it re-encodes a small part of the already-neural-rendered output.
    """
    source = result_path(request, job_id, False)
    target_dir = s(request).data / "samples"
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / f"{job_id}.mp4"
    if not dest.is_file() or dest.stat().st_size == 0:
        exe = s(request).resolve_command("ffmpeg")
        if not exe:
            raise HTTPException(503, detail="ffmpeg unavailable; download the full result instead")
        # Single-user app: guard duplicate concurrent sample requests.
        with request.app.state.sample_lock:
            if not dest.is_file() or dest.stat().st_size == 0:
                temp = target_dir / f"{job_id}.partial.mp4"
                command = [str(exe), "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
                           "-t", "12", "-map", "0:v:0", "-map", "0:a:0?",
                           "-vf", "scale='min(1280,iw)':-2", "-c:v", "libx264", "-preset", "veryfast",
                           "-crf", "23", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                           "-movflags", "+faststart", str(temp)]
                try:
                    process = run_command(command, timeout=240)
                    if process.returncode or not temp.is_file() or temp.stat().st_size == 0:
                        raise HTTPException(422, detail="Could not generate browser sample: " + process.stderr[-600:])
                    temp.replace(dest)
                finally:
                    temp.unlink(missing_ok=True)
    return FileResponse(dest, media_type="video/mp4", content_disposition_type="inline")


@router.get("/jobs/{job_id}/report")
def download_report(request: Request, job_id: str):
    return FileResponse(result_path(request, job_id, True), media_type="application/json",
                        filename=jobs(request).get(job_id).report_filename)


@router.post("/preview")
def preview_frame(request: Request, data: PreviewRequest):
    source = UploadStore(s(request)).get(data.upload_id)
    if not source:
        raise HTTPException(404, detail="Upload not found")
    caps = capabilities(s(request))
    if not caps["render_available"]:
        raise HTTPException(409, detail=caps["reason"])
    # The proprietary image worker is not safe to run concurrently with a render.
    if jobs(request).active:
        raise HTTPException(409, detail="Wait for the active render before previewing")
    with request.app.state.preview_lock:
        if jobs(request).active:
            raise HTTPException(409, detail="Wait for the active render before previewing")
        try:
            return make_preview(s(request), source, data)
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(422, detail=str(exc)) from exc
