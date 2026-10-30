from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .export_presets import CUSTOM, LEGACY_CUSTOM, LEGACY_HEVC_CQ20, RECIPES, selected_recipe


class Profile(StrEnum):
    """Name the four supported native rendering characters."""
    FAITHFUL = "Faithful"
    NATURAL = "Natural"
    CINEMATIC = "Strong / Cinematic"
    EXTREME = "Extreme / Overdrive"


# Preserve feature-18 profile mapping and defaults from the upstream worker interface.
PRESETS: dict[Profile, dict[str, float | int]] = {
    Profile.FAITHFUL: dict(
        profile=0, preset=0, style=0, auto_mask=0, ui_correction=0,
        intensity=0.70, local_tone=0.75, local_structure=0.75, skin_structure=-1.0
    ),
    Profile.NATURAL: dict(
        profile=1, preset=0, style=1, auto_mask=0, ui_correction=0,
        intensity=1.00, local_tone=1.00, local_structure=1.00, skin_structure=-1.0
    ),
    Profile.CINEMATIC: dict(
        profile=2, preset=2, style=2, auto_mask=1, ui_correction=0,
        intensity=1.65, local_tone=1.40, local_structure=1.50, skin_structure=1.0
    ),
    Profile.EXTREME: dict(
        profile=2, preset=2, style=2, auto_mask=1, ui_correction=0,
        intensity=2.50, local_tone=2.00, local_structure=2.00, skin_structure=1.5
    ),
}


class Clip(BaseModel):
    """Represent a half-open source interval in seconds, optionally ending at EOF.

    Args:
        start (float): The inclusive source start time in seconds.
        end (float | None): The exclusive source end time, or None for EOF.
    """

    model_config = ConfigDict(extra="forbid")
    start: float = Field(ge=0, le=864000)
    end: float | None = Field(default=None, gt=0, le=864000)

    @model_validator(mode="after")
    def validate_bounds(self) -> Clip:
        """Reject an explicit clip end that does not follow its start.

        Returns:
            Clip: The validated clip instance.
        """
        if self.end is not None and self.end <= self.start:
            raise ValueError("Clip end must be greater than start")
        return self


class RenderOptions(BaseModel):
    """Validate native rendering parameters, export choices, and selected clips.

    Args:
        profile (Profile): The native rendering character.
        codec (Literal['H.264', 'HEVC', 'AV1']): The display codec name.
        container (Literal['MP4', 'MKV']): The output container.
        quality (Literal['High', 'Balanced', 'Small', 'Lossless']): The Custom export quality level.
        export_preset (str): The named export recipe or Custom.
        target_fps (Literal['Source', '60']): Source timing or conversion to 60 FPS.
        clips (list[Clip]): The ordered source intervals to keep; empty means the full video.
        warmup_frames (int): The native warmup count.
        intensity (float | None): The optional overall strength override.
        local_tone (float | None): The optional local-tone override.
        local_structure (float | None): The optional local-detail override.
        skin_structure (float | None): The optional skin-detail override.
    """
    model_config = ConfigDict(extra="forbid")
    profile: Profile = Profile.CINEMATIC
    codec: Literal["H.264", "HEVC", "AV1"] = "H.264"
    container: Literal["MP4", "MKV"] = "MP4"
    quality: Literal["High", "Balanced", "Small", "Lossless"] = "High"
    export_preset: Literal[
        "Custom", "Standard", "HEVC 10-bit / NVENC P7 CQ20",
        "HEVC Main10 - Maximum quality (CQ18)",
        "HEVC Main10 - Balanced (CQ20)",
        "HEVC Main10 - Smaller files (CQ24)",
        "H.264 - Compatible (CQ20)",
        "AV1 - Efficient (CQ20)",
    ] = "HEVC Main10 - Balanced (CQ20)"
    target_fps: Literal["Source", "60"] = "Source"
    clips: list[Clip] = Field(default_factory=list, max_length=100)
    warmup_frames: int = Field(default=120, ge=0, le=1000)
    intensity: float | None = Field(default=None, ge=0, le=3)
    local_tone: float | None = Field(default=None, ge=0, le=3)
    local_structure: float | None = Field(default=None, ge=0, le=3)
    skin_structure: float | None = Field(default=None, ge=-1, le=3)

    @model_validator(mode="after")
    def compatible(self) -> RenderOptions:
        """Reject unsupported export combinations and unordered or overlapping clips.

        Returns:
            RenderOptions: The validated render options instance.
        """
        if self.codec == "AV1" and self.quality == "Lossless":
            raise ValueError("AV1 lossless is not supported by the upstream NVENC pipeline")
        previous_end = 0.0
        for i, clip in enumerate(self.clips):
            if clip.start < previous_end:
                raise ValueError("Clips must be ordered and nonoverlapping")
            if clip.end is None and i < len(self.clips) - 1:
                raise ValueError("An open-ended clip must be last")
            previous_end = clip.end if clip.end is not None else float("inf")
        if selected_recipe(self.export_preset) is not None and self.container != "MP4":
            raise ValueError("An export recipe requires MP4; select Custom for MKV")
        return self

    def native(self) -> dict[str, float | int]:
        """Combine the chosen native profile defaults with explicit slider overrides.

        Returns:
            dict[str, float | int]: The effective native integer and floating-point parameters.
        """
        values = PRESETS[self.profile].copy()
        for key in ("intensity", "local_tone", "local_structure", "skin_structure"):
            value = getattr(self, key)
            if value is not None:
                values[key] = value
        return values


class JobRequest(BaseModel):
    """Describe an uploaded video and the options for a queued render.

    Args:
        upload_id (str): The source upload identifier.
        options (RenderOptions): The validated rendering options.
    """
    upload_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    options: RenderOptions = Field(default_factory=RenderOptions)


class PreviewRequest(BaseModel):
    """Describe an uploaded video, timestamp, and still-image preview options.

    Args:
        upload_id (str): The source upload identifier.
        timestamp (float): The preview time in seconds.
        options (RenderOptions): The validated rendering options.
    """
    upload_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    timestamp: float = Field(default=0, ge=0, le=864000)
    options: RenderOptions = Field(default_factory=RenderOptions)


class Status(StrEnum):
    """Enumerate the lifecycle states of a render job."""
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


def now_utc() -> datetime:
    """Get the current timezone-aware UTC timestamp.

    Returns:
        datetime: The current UTC datetime.
    """
    return datetime.now(timezone.utc)


class JobView(BaseModel):
    """Expose persisted job status, timing, progress, and output filenames.

    Args:
        id (str): The unique record identifier.
        filename (str): The original source filename.
        upload_id (str): The source upload identifier.
        options (RenderOptions): The validated rendering options.
        status (Status): The job lifecycle state.
        progress (float): The completion fraction from zero to one.
        message (str): The current status description.
        created_at (datetime): The job creation timestamp.
        started_at (datetime | None): The render start timestamp, if started.
        finished_at (datetime | None): The completion timestamp, if finished.
        error (str | None): The failure description, if any.
        output_filename (str | None): The verified video filename, if completed.
        report_filename (str | None): The evidence report filename, if completed.
        frames (int | None): The processed native frame count.
        elapsed_seconds (float | None): The measured render duration, if completed.
    """
    id: str
    filename: str
    upload_id: str
    options: RenderOptions
    status: Status = Status.QUEUED
    progress: float = Field(default=0, ge=0, le=1)
    message: str = "Queued"
    created_at: datetime = Field(default_factory=now_utc)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    output_filename: str | None = None
    report_filename: str | None = None
    frames: int | None = None
    elapsed_seconds: float | None = None
