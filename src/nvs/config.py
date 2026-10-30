from __future__ import annotations

import os
import shutil
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root is independent of the working directory when installed editable.
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Load application paths and limits from NVS_ variables and the project .env file.

    Args:
        host (str): The server bind address.
        port (int): The server TCP port.
        runtime_dir (Path): The video worker and model directory.
        preview_dir (Path): The optional image-preview directory.
        data_dir (Path): The persistent application data directory.
        ffmpeg (str | None): An optional FFmpeg path override.
        ffprobe (str | None): An optional ffprobe path override.
        max_upload_gb (float): The upload limit in GiB.
        allow_unverified_gpu (bool): Whether to bypass GPU name filtering on Windows.
    """
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
        """Resolve a configured path relative to the project root.

        Args:
            path (Path): The filesystem path to resolve or process.

        Returns:
            Path: The absolute filesystem path.
        """
        return (path if path.is_absolute() else PROJECT_ROOT / path).resolve()

    @property
    def runtime(self) -> Path:
        """Get the directory containing the native video worker and model.

        Returns:
            Path: The absolute runtime directory.
        """
        return self.absolute(self.runtime_dir)

    @property
    def preview(self) -> Path:
        """Get the directory containing the optional image preview worker.

        Returns:
            Path: The absolute preview directory.
        """
        return self.absolute(self.preview_dir)

    @property
    def data(self) -> Path:
        """Get the directory containing uploads, jobs, outputs, and scratch files.

        Returns:
            Path: The absolute application data directory.
        """
        return self.absolute(self.data_dir)

    @property
    def max_upload_bytes(self) -> int:
        """Convert the configured upload limit from GiB to bytes.

        Returns:
            int: The maximum accepted upload size in bytes.
        """
        return int(self.max_upload_gb * 1024**3)

    @property
    def worker(self) -> Path:
        """Get the path to the native feature-18 video executable.

        Returns:
            Path: The expected runtime/nvngx.dll path.
        """
        return self.runtime / "nvngx.dll"

    @property
    def model(self) -> Path:
        """Get the path to the matching neural model binary.

        Returns:
            Path: The expected runtime/nvngx_dlssnr.dll path.
        """
        return self.runtime / "nvngx_dlssnr.dll"

    @property
    def preview_cli(self) -> Path:
        """Get the path to the optional still-image preview executable.

        Returns:
            Path: The expected dlssnr-image.exe path.
        """
        return self.preview / "dlssnr-image.exe"

    def resolve_command(self, name: str) -> Path | None:
        """Find a media executable using an override, bundled tools, or PATH.

        Args:
            name (str): The command or recipe name to resolve.

        Returns:
            Path | None: The resolved executable path, or None when unavailable.
        """
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
        """Create the upload, job, output, and scratch directories if needed.

        Returns:
            None: No value is returned.
        """
        for name in ("uploads", "jobs", "outputs", "scratch"):
            (self.data / name).mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    """Load a fresh application settings instance.

    Returns:
        Settings: Settings read from defaults, environment variables, and .env.
    """
    return Settings()
