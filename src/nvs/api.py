from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from .config import Settings
from .hardware import capabilities
from .jobs import JobManager
from .media import run_command
from .preview import make_preview
from .schemas import PRESETS, JobRequest, JobView, PreviewRequest, Status
from .uploads import UploadStore

router = APIRouter(prefix="/api")


def s(request: Request) -> Settings:
    """Read the application settings attached to a request.

    Args:
        request (Request): The incoming HTTP request carrying application state.

    Returns:
        Settings: The active application settings.
    """
    return request.app.state.settings


def jobs(request: Request) -> JobManager:
    """Read the render queue attached to a request.

    Args:
        request (Request): The incoming HTTP request carrying application state.

    Returns:
        JobManager: The active job manager.
    """
    return request.app.state.jobs


@router.get("/health")
def health() -> dict[str, str | bool]:
    """Report application liveness and version.

    Returns:
        dict[str, str | bool]: The liveness flag, application name, and version.
    """
    return {"ok": True, "app": "Neural Video Studio", "version": "0.3.2"}


@router.get("/capabilities")
def system_capabilities(request: Request) -> dict[str, Any]:
    """Report hardware, runtime, and media-tool prerequisites.

    Args:
        request (Request): The incoming HTTP request carrying application state.

    Returns:
        dict[str, Any]: Capability flags, detected hardware, and diagnostic reasons.
    """
    return capabilities(s(request))


@router.get("/presets")
def presets() -> dict[str, dict[str, float | int]]:
    """Expose native defaults for each rendering profile.

    Returns:
        dict[str, dict[str, float | int]]: Profile names mapped to native parameter defaults.
    """
    return {k.value: v for k, v in PRESETS.items()}


@router.post("/uploads", status_code=201)
async def upload_video(request: Request, file: Annotated[UploadFile, File()]) -> dict[str, str | int]:
    """Store an uploaded video and translate validation errors into HTTP 400.

    Args:
        request (Request): The incoming HTTP request carrying application state.
        file (Annotated[UploadFile, File()]): The multipart video file to store.

    Returns:
        dict[str, str | int]: The upload identifier, original name, and byte size.
    """
    try:
        return (await UploadStore(s(request)).save(file)).public()
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc


@router.get("/uploads/{upload_id}/source")
def get_source(request: Request, upload_id: str) -> FileResponse:
    """Serve an uploaded source file inline.

    Args:
        request (Request): The incoming HTTP request carrying application state.
        upload_id (str): The stored upload hexadecimal identifier.

    Returns:
        FileResponse: The source video response.
    """
    info = UploadStore(s(request)).get(upload_id)
    if not info:
        raise HTTPException(404, detail="Unknown upload")
    return FileResponse(info.path, media_type=mimetypes.guess_type(info.name)[0] or "application/octet-stream",
                        content_disposition_type="inline", filename=info.name)


@router.post("/jobs", status_code=201)
def create_job(request: Request, data: JobRequest) -> JobView:
    """Queue a render for an existing upload.

    Args:
        request (Request): The incoming HTTP request carrying application state.
        data (JobRequest): The validated request payload.

    Returns:
        JobView: The newly queued job snapshot.
    """
    source = UploadStore(s(request)).get(data.upload_id)
    if not source:
        raise HTTPException(404, detail="Upload not found")
    try:
        return jobs(request).submit(source.id, source.name, data.options)
    except RuntimeError as exc:
        raise HTTPException(503, detail=str(exc)) from exc


@router.get("/jobs")
def get_jobs(request: Request) -> list[JobView]:
    """List known render jobs in newest-first order.

    Args:
        request (Request): The incoming HTTP request carrying application state.

    Returns:
        list[JobView]: Snapshots of all known jobs.
    """
    return jobs(request).all()


@router.get("/jobs/{job_id}")
def get_job(request: Request, job_id: str) -> JobView:
    """Retrieve a render job or return HTTP 404.

    Args:
        request (Request): The incoming HTTP request carrying application state.
        job_id (str): The render job identifier.

    Returns:
        JobView: The requested job snapshot.
    """
    record = jobs(request).get(job_id)
    if record is None:
        raise HTTPException(404, detail="Job not found")
    return record


@router.post("/jobs/{job_id}/cancel")
def cancel_job(request: Request, job_id: str) -> JobView:
    """Cancel a queued job or request cancellation of an active render.

    Args:
        request (Request): The incoming HTTP request carrying application state.
        job_id (str): The render job identifier.

    Returns:
        JobView: The updated job snapshot.
    """
    record = jobs(request).cancel(job_id)
    if record is None:
        raise HTTPException(404, detail="Job not found")
    return record


def result_path(request: Request, job_id: str, report: bool) -> Path:
    """Resolve an existing output or report for a completed job.

    Args:
        request (Request): The incoming HTTP request carrying application state.
        job_id (str): The render job identifier.
        report (bool): Whether to resolve the JSON report instead of the video.

    Returns:
        Path: The validated result file path.
    """
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
def download_result(request: Request, job_id: str) -> FileResponse:
    """Download the verified full video for a completed job.

    Args:
        request (Request): The incoming HTTP request carrying application state.
        job_id (str): The render job identifier.

    Returns:
        FileResponse: The video attachment response.
    """
    return FileResponse(result_path(request, job_id, False), media_type="application/octet-stream",
                        filename=jobs(request).get(job_id).output_filename)


@router.get("/jobs/{job_id}/video")
def watch_full_result(request: Request, job_id: str) -> FileResponse:
    """Serve the verified full result inline using its container media type.

    Args:
        request (Request): The incoming HTTP request carrying application state.
        job_id (str): The render job identifier.

    Returns:
        FileResponse: The full video response; playback depends on browser codec support.
    """
    path = result_path(request, job_id, False)
    media = "video/mp4" if path.suffix.lower() == ".mp4" else "video/x-matroska"
    return FileResponse(path, media_type=media, content_disposition_type="inline")


@router.get("/jobs/{job_id}/sample")
def watch_short_sample(request: Request, job_id: str) -> FileResponse:
    """Cache and serve a 12-second H.264/AAC sample of a verified result.

    Args:
        request (Request): The incoming HTTP request carrying application state.
        job_id (str): The render job identifier.

    Returns:
        FileResponse: The browser-compatible sample response without changing the full export.
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
def download_report(request: Request, job_id: str) -> FileResponse:
    """Download the evidence report for a completed render.

    Args:
        request (Request): The incoming HTTP request carrying application state.
        job_id (str): The render job identifier.

    Returns:
        FileResponse: The JSON report attachment response.
    """
    return FileResponse(result_path(request, job_id, True), media_type="application/json",
                        filename=jobs(request).get(job_id).report_filename)


@router.post("/preview")
def preview_frame(request: Request, data: PreviewRequest) -> dict[str, Any]:
    """Generate a still-image comparison while the shared GPU is idle.

    Args:
        request (Request): The incoming HTTP request carrying application state.
        data (PreviewRequest): The validated request payload.

    Returns:
        dict[str, Any]: Before/after image data, effective parameters, and a preview note.
    """
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
