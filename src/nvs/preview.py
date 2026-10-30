from __future__ import annotations

import base64
import shutil
import subprocess
import tempfile
from pathlib import Path

from .config import Settings
from .media import probe_video, run_command
from .schemas import PreviewRequest
from .uploads import UploadInfo


def make_preview(settings: Settings, info: UploadInfo, payload: PreviewRequest) -> dict:
    if not settings.preview_cli.is_file():
        raise RuntimeError("Preview executable missing: preview/dlssnr-image.exe")
    if not (settings.preview / "caller" / "nvngx.dll").is_file():
        raise RuntimeError("Preview caller missing: preview/caller/nvngx.dll")
    if not settings.model.is_file():
        raise RuntimeError("Neural model missing from runtime directory")
    video = probe_video(settings, info.path)
    if video.duration and payload.timestamp > video.duration + .1:
        raise ValueError("Preview timestamp exceeds video duration")
    ffmpeg = settings.resolve_command("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("FFmpeg is not installed")
    with tempfile.TemporaryDirectory(prefix="preview_", dir=settings.data / "scratch") as temp:
        root = Path(temp)
        source_png, processed_png = root / "before.png", root / "after.png"
        command = [
            str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-ss",
            str(payload.timestamp), "-i", str(info.path), "-frames:v", "1", str(source_png)
        ]
        extracted = run_command(command, timeout=120)
        if extracted.returncode or not source_png.is_file():
            raise RuntimeError("Could not extract preview frame: " + extracted.stderr[-500:])
        if video.hdr:
            raise RuntimeError("HDR is not supported by the SDR preview renderer")
        model_in_preview = settings.preview / "nvngx_dlssnr.dll"
        if not model_in_preview.is_file():
            shutil.copy2(settings.model, model_in_preview)
        native = payload.options.native()
        # The image-only executable accepts narrower ranges than the video worker.
        for key in ("intensity", "local_tone", "local_structure"):
            native[key] = min(2.0, max(0.0, float(native[key])))
        native["skin_structure"] = min(2.0, max(-1.0, float(native["skin_structure"])))
        command = [
            str(settings.preview_cli), str(source_png), str(processed_png),
            "--preset", str(native["preset"]), "--style", str(native["style"]),
            "--intensity", str(native["intensity"]), "--tone", str(native["local_tone"]),
            "--structure", str(native["local_structure"]), "--skin", str(native["skin_structure"]),
            "--auto-mask", str(native["auto_mask"]), "--diagnostics", "0"
            ]
        try:
            result = subprocess.run(
                command, cwd=settings.preview, capture_output=True, text=True,
                timeout=180, errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Native preview timed out") from exc
        if result.returncode or not processed_png.is_file():
            raise RuntimeError("Native preview failed: " + (result.stderr or result.stdout)[-800:])
        return {
            "before": "data:image/png;base64," + base64.b64encode(source_png.read_bytes()).decode(),
            "after": "data:image/png;base64," + base64.b64encode(processed_png.read_bytes()).decode(),
            "effective_parameters": native,
            "note": "Preview uses the image worker and clamps controls to its supported ranges.",
        }
