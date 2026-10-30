from __future__ import annotations

import os
import shutil
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root is independent of the working directory when installed editable.
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NVS_", env_file=PROJECT_ROOT / ".env", extra="ignore")

    host: str = "127.0.0.1"
    port: int = Field(default=7860, ge=1, le=65535)
    runtime_dir: Path = Path("runtime")
    preview_dir: Path = Path("preview")
    data_dir: Path = Path("data")
    ffmpeg: str | None = None
    ffprobe: str | None = None
    max_upload_gb: float = Field(default=20, gt=0)
    allow_unverified_gpu: bool = False

    def absolute(self, path: Path) -> Path:
        return (path if path.is_absolute() else PROJECT_ROOT / path).resolve()

    @property
    def runtime(self) -> Path:
        return self.absolute(self.runtime_dir)

    @property
    def preview(self) -> Path:
        return self.absolute(self.preview_dir)

    @property
    def data(self) -> Path:
        return self.absolute(self.data_dir)

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_gb * 1024**3)

    @property
    def worker(self) -> Path:
        return self.runtime / "nvngx.dll"

    @property
    def model(self) -> Path:
        return self.runtime / "nvngx_dlssnr.dll"

    @property
    def preview_cli(self) -> Path:
        return self.preview / "dlssnr-image.exe"

    def resolve_command(self, name: str) -> Path | None:
        override = getattr(self, name)
        if override:
            path = Path(override).expanduser()
            found = shutil.which(str(path))
            candidate = self.absolute(path)
            return Path(found).resolve() if found else (candidate if candidate.is_file() else None)
        exe = f"{name}.exe" if os.name == "nt" else name
        bundled = PROJECT_ROOT / "bin" / "ffmpeg" / "bin" / exe
        if bundled.is_file():
            return bundled.resolve()
        found = shutil.which(exe)
        return Path(found).resolve() if found else None

    def make_directories(self) -> None:
        for name in ("uploads", "jobs", "outputs", "scratch"):
            (self.data / name).mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    return Settings()
