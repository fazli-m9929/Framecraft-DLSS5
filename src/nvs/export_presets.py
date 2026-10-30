"""Output recipes. These affect encoding, never DLSS model inference.

The worker emits RGBA8. Main10 packs that source into a 10-bit output
container; it does not restore missing source precision.
"""
from __future__ import annotations

from dataclasses import dataclass

CUSTOM = "Custom"
LEGACY_CUSTOM = "Standard"
LEGACY_HEVC_CQ20 = "HEVC 10-bit / NVENC P7 CQ20"


@dataclass(frozen=True, slots=True)
class ExportRecipe:
    """Describe the encoder, pixel format, quality, and audio settings of an export.

    Args:
        encoder (str): The FFmpeg encoder name.
        codec (str): The display codec name.
        pix_fmt (str): The encoded pixel format.
        preset (str): The FFmpeg encoder speed/quality preset.
        cq (int): The constant-quality target.
        audio_bitrate (str): The AAC audio bitrate.
        audio_rate (int): The audio sample rate in Hz.
        main10 (bool): Whether HEVC Main10 is required.
    """
    encoder: str
    codec: str
    pix_fmt: str
    preset: str
    cq: int
    audio_bitrate: str = "384k"
    audio_rate: int = 48000
    main10: bool = False


RECIPES: dict[str, ExportRecipe] = {
    "HEVC Main10 - Maximum quality (CQ18)": ExportRecipe(
        "hevc_nvenc", "HEVC", "p010le", "p7", 18, main10=True),
    "HEVC Main10 - Balanced (CQ20)": ExportRecipe(
        "hevc_nvenc", "HEVC", "p010le", "p7", 20, main10=True),
    "HEVC Main10 - Smaller files (CQ24)": ExportRecipe(
        "hevc_nvenc", "HEVC", "p010le", "p7", 24, main10=True),
    "H.264 - Compatible (CQ20)": ExportRecipe(
        "h264_nvenc", "H.264", "yuv420p", "p6", 20),
    "AV1 - Efficient (CQ20)": ExportRecipe(
        "av1_nvenc", "AV1", "yuv420p", "p6", 20),
}


def selected_recipe(name: str) -> ExportRecipe | None:
    """Resolve a named or legacy export recipe, leaving Custom unconfigured.

    Args:
        name (str): The command or recipe name to resolve.

    Returns:
        ExportRecipe | None: The selected recipe, or None for Custom and its legacy alias.
    """
    if name in (CUSTOM, LEGACY_CUSTOM):
        return None
    if name == LEGACY_HEVC_CQ20:
        return RECIPES["HEVC Main10 - Balanced (CQ20)"]
    return RECIPES[name]


def recipe_names() -> tuple[str, ...]:
    """List Custom followed by the supported export recipe names.

    Returns:
        tuple[str, ...]: The ordered recipe names.
    """
    return (CUSTOM, *RECIPES)
