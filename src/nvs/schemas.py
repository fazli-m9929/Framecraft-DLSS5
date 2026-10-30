from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .export_presets import CUSTOM, LEGACY_CUSTOM, LEGACY_HEVC_CQ20, RECIPES, selected_recipe


class Profile(StrEnum):
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
    """Half-open source interval [start, end), expressed in seconds."""

    model_config = ConfigDict(extra="forbid")
    start: float = Field(ge=0, le=864000)
    end: float | None = Field(default=None, gt=0, le=864000)

    @model_validator(mode="after")
    def validate_bounds(self):
        if self.end is not None and self.end <= self.start:
            raise ValueError("Clip end must be greater than start")
        return self


class RenderOptions(BaseModel):
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
    def compatible(self):
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
        values = PRESETS[self.profile].copy()
        for key in ("intensity", "local_tone", "local_structure", "skin_structure"):
            value = getattr(self, key)
            if value is not None:
                values[key] = value
        return values


class JobRequest(BaseModel):
    upload_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    options: RenderOptions = Field(default_factory=RenderOptions)


class PreviewRequest(BaseModel):
    upload_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    timestamp: float = Field(default=0, ge=0, le=864000)
    options: RenderOptions = Field(default_factory=RenderOptions)


class Status(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class JobView(BaseModel):
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
