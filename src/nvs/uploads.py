from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from fastapi import UploadFile

from .config import Settings

ALLOWED_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v"}


@dataclass(frozen=True)
class UploadInfo:
    """Describe an uploaded video and its stored filesystem location.

    Args:
        id (str): The unique record identifier.
        name (str): The original filename or encoder preset name.
        size (int): The stored video size in bytes.
        path (Path): The stored video path.
    """
    id: str
    name: str
    size: int
    path: Path

    def public(self) -> dict[str, str | int]:
        """Serialize upload metadata without exposing the storage path.

        Returns:
            dict[str, str | int]: The upload identifier, original name, and byte size.
        """
        return {"id": self.id, "name": self.name, "size": self.size}


class UploadStore:
    """Persist uploaded videos and their metadata under the data directory."""
    def __init__(self, settings: Settings) -> None:
        """Create the upload storage directory and retain its settings.

        Args:
            settings (Settings): Application paths, limits, and runtime configuration.

        Returns:
            None: No value is returned.
        """
        self.settings = settings
        self.directory = settings.data / "uploads"
        self.directory.mkdir(parents=True, exist_ok=True)

    def get(self, upload_id: str) -> UploadInfo | None:
        """Look up an upload by its validated hexadecimal identifier.

        Args:
            upload_id (str): The stored upload hexadecimal identifier.

        Returns:
            UploadInfo | None: The stored upload, or None if invalid, missing, or unreadable.
        """
        if len(upload_id) != 32 or any(x not in "0123456789abcdef" for x in upload_id):
            return None
        metadata = self.directory / f"{upload_id}.json"
        if not metadata.is_file():
            return None
        try:
            info = json.loads(metadata.read_text(encoding="utf-8"))
            path = self.directory / f"{upload_id}{info['extension']}"
            if path.is_file():
                return UploadInfo(upload_id, info["name"], info["size"], path)
        except (OSError, KeyError, ValueError):
            pass
        return None

    async def save(self, upload: UploadFile) -> UploadInfo:
        """Stream an upload to disk while enforcing extension and size limits.

        Args:
            upload (UploadFile): The multipart video file to store and close.

        Returns:
            UploadInfo: The completed upload record.
        """
        name = PureWindowsPath(upload.filename or "video.mp4").name[:200]
        extension = Path(name).suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise ValueError("Unsupported extension. Use MP4, MKV, WEBM, MOV, AVI or M4V")
        identifier = uuid.uuid4().hex
        path = self.directory / f"{identifier}{extension}"
        temp = self.directory / f"{identifier}.part"
        count = 0
        try:
            with temp.open("wb") as target:
                while data := await upload.read(4 * 1024 * 1024):
                    count += len(data)
                    if count > self.settings.max_upload_bytes:
                        raise ValueError(f"Upload exceeds {self.settings.max_upload_gb:g} GiB limit")
                    target.write(data)
            if not count:
                raise ValueError("Upload is empty")
            temp.replace(path)
            (self.directory / f"{identifier}.json").write_text(
                json.dumps({"name": name, "extension": extension, "size": count}), encoding="utf-8")
            return UploadInfo(identifier, name, count, path)
        except Exception:
            temp.unlink(missing_ok=True)
            path.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()
