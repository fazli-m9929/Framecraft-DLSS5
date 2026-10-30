from __future__ import annotations

import re
import subprocess
import sys

from .config import Settings


def gpu_inventory() -> list[dict]:
    try:
        proc = subprocess.run(
            [
                "nvidia-smi", "--query-gpu=name,driver_version,memory.total,compute_cap",
                "--format=csv,noheader,nounits"
            ],
            capture_output=True, text=True, timeout=8, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    result = []
    if proc.returncode != 0:
        return []
    for line in proc.stdout.splitlines():
        parts = [x.strip() for x in line.split(",")]
        if len(parts) >= 4:
            name, driver, memory, capability = parts[:4]
            match = re.search(r"\bRTX\s+(30|40|50)\d{2}\b", name.upper())
            result.append({
                "name": name, "driver": driver, "memory_mb": memory,
                "compute_capability": capability,
                "expected_compatible": bool(match)
            })
    return result


def capabilities(settings: Settings) -> dict:
    gpus = gpu_inventory()
    missing = [str(p) for p in (settings.worker, settings.model) if not p.is_file()]
    ffmpeg = settings.resolve_command("ffmpeg")
    ffprobe = settings.resolve_command("ffprobe")
    if not ffmpeg: missing.append("ffmpeg executable (configure NVS_FFMPEG)")
    if not ffprobe: missing.append("ffprobe executable (configure NVS_FFPROBE)")
    windows = sys.platform == "win32"
    gpu_ok = any(g["expected_compatible"] for g in gpus)
    if not windows:
        reason = "The supplied feature-18 worker is a Windows/D3D12 executable; Linux/CPU support is not available."
    elif missing:
        reason = "Required runtime files or media tools are missing."
    elif not gpus:
        reason = "No NVIDIA GPU/driver detected. CPU-only DLSS rendering is not supported."
    elif not (gpu_ok or settings.allow_unverified_gpu):
        reason = "No recognized RTX 30/40/50 GPU. H100/H200 and others are not verified."
    else:
        reason = "Prerequisites passed. Actual compatibility is determined by a real feature-18 frame evaluation."
    return {
        "platform": sys.platform,
        "gpus": gpus,
        "missing": missing,
        "render_available": windows and not missing and bool(gpus) and (gpu_ok or settings.allow_unverified_gpu),
        "reason": reason,
        "preview_available": windows and settings.preview_cli.is_file()
            and (settings.preview / "caller" / "nvngx.dll").is_file()
            and settings.model.is_file(),
        "ffmpeg": str(ffmpeg) if ffmpeg else None,
        "ffprobe": str(ffprobe) if ffprobe else None,
        "experimental_gpu_override": settings.allow_unverified_gpu,
    }
