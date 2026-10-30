
import subprocess
from fractions import Fraction

import pytest
from pydantic import ValidationError

from nvs.media import audio_filter, effective_clips
from nvs.pipeline import clip_for_timestamp
from nvs.schemas import Clip, RenderOptions


def test_export_options() -> None:
    """Verify the legacy HEVC recipe accepts 60 FPS and open-ended clips.

    Returns:
        None: No value is returned.
    """
    opts = RenderOptions(export_preset="HEVC 10-bit / NVENC P7 CQ20",
                         codec="HEVC", target_fps="60",
                         clips=[Clip(start=0, end=547), Clip(start=945)])
    assert opts.clips[1].end is None
    assert opts.container == "MP4"
    assert opts.target_fps == "60"


@pytest.mark.parametrize("clips", [
    [{"start": 9, "end": 4}],
    [{"start": 5, "end": 10}, {"start": 9, "end": 12}],
    [{"start": 10}, {"start": 12, "end": 15}],
])
def test_reject_invalid_clip_bounds(clips: list[dict[str, int]]) -> None:
    """Reject reversed, overlapping, and misplaced open-ended clips.

    Args:
        clips (list[dict[str, int]]): The invalid clip configuration supplied by parametrization.

    Returns:
        None: No value is returned.
    """
    with pytest.raises(ValidationError):
        RenderOptions(clips=clips)


def test_reject_mkv_hevc_preset() -> None:
    """Reject MKV when a fixed MP4 export recipe is selected.

    Returns:
        None: No value is returned.
    """
    with pytest.raises(ValidationError):
        RenderOptions(container="MKV", export_preset="HEVC 10-bit / NVENC P7 CQ20")


def test_selected_clips_match_example() -> None:
    """Verify half-open clip membership and the documented retained duration.

    Returns:
        None: No value is returned.
    """
    clips = effective_clips([Clip(start=0, end=547), Clip(start=945)], 1000)
    assert clips == [(0, 547), (945, 1000)]
    assert [clip_for_timestamp(t, clips) for t in [0, 546.999, 547, 944, 945, 1000]] == [0, 0, None, None, 1, None]
    assert sum(end - start for start, end in clips) == 602


def test_trim_audio_ffmpeg_filter() -> None:
    """Verify audio trimming and concatenation use the selected intervals.

    Returns:
        None: No value is returned.
    """
    expression = audio_filter([(0, 547), (945, 1000)])
    assert "atrim=start=0.000000:end=547.000000" in expression
    assert "atrim=start=945.000000:end=1000.000000" in expression
    assert "concat=n=2:v=0:a=1" in expression
    assert expression.endswith("aresample=async=1:first_pts=0,apad[a]")


def test_single_clip_audio_no_concat() -> None:
    """Verify a single audio interval needs no concatenation node.

    Returns:
        None: No value is returned.
    """
    expression = audio_filter([(2, 7)])
    assert "concat=" not in expression
    assert "[a0]aresample" in expression


def test_hevc_main10_encoder_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the legacy HEVC recipe selects the expected Main10 encoder flags.

    Args:
        monkeypatch (pytest.MonkeyPatch): The pytest fixture for replacing dependencies during the test.

    Returns:
        None: No value is returned.
    """
    import nvs.media as media
    monkeypatch.setattr(media, 'encoder_available', lambda *a, **k: True)
    opts = RenderOptions(export_preset='HEVC 10-bit / NVENC P7 CQ20', codec='HEVC')
    args, encoder = media.encoder_args(None, opts)
    assert encoder == 'hevc_nvenc'
    for flag, value in [('-preset', 'p7'), ('-tune', 'hq'), ('-profile:v', 'main10'),
                        ('-rc', 'vbr'), ('-cq', '20'), ('-b:v', '0'),
                        ('-pix_fmt', 'p010le')]:
        assert args[args.index(flag) + 1] == value


@pytest.mark.parametrize("preset,encoder,cq,bit_depth", [
    ("HEVC Main10 - Maximum quality (CQ18)", "hevc_nvenc", "18", "p010le"),
    ("HEVC Main10 - Balanced (CQ20)", "hevc_nvenc", "20", "p010le"),
    ("HEVC Main10 - Smaller files (CQ24)", "hevc_nvenc", "24", "p010le"),
    ("H.264 - Compatible (CQ20)", "h264_nvenc", "20", "yuv420p"),
    ("AV1 - Efficient (CQ20)", "av1_nvenc", "20", "yuv420p"),
])
def test_export_recipes(monkeypatch: pytest.MonkeyPatch, preset: str, encoder: str, cq: str, bit_depth: str) -> None:
    """Verify each export recipe selects its encoder, quality, and pixel format.

    Args:
        monkeypatch (pytest.MonkeyPatch): The pytest fixture for replacing dependencies during the test.
        preset (str): The export recipe name under test.
        encoder (str): The expected FFmpeg encoder name.
        cq (str): The expected constant-quality argument.
        bit_depth (str): The expected pixel format.

    Returns:
        None: No value is returned.
    """
    import nvs.media as media
    monkeypatch.setattr(media, "encoder_available", lambda *args, **kw: True)
    args, name = media.encoder_args(None, RenderOptions(export_preset=preset))
    assert name == encoder
    assert args[args.index("-cq") + 1] == cq
    assert args[args.index("-pix_fmt") + 1] == bit_depth
    assert "-tag:v" not in args  # MP4 tag cannot be applied to intermediate MKV
    assert ("-profile:v" in args) == (bit_depth == "p010le")


def test_encoder_list_check_does_not_try_synthetic_nvenc(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify encoder detection reads the FFmpeg list without encoding a probe.

    Args:
        monkeypatch (pytest.MonkeyPatch): The pytest fixture for replacing dependencies during the test.

    Returns:
        None: No value is returned.
    """
    from pathlib import Path

    import nvs.media as media
    from nvs.config import Settings

    seen = []
    monkeypatch.setattr(Settings, "resolve_command", lambda *a: Path("ffmpeg.exe"))
    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        """Return a synthetic FFmpeg encoder listing and record the command.

        Args:
            cmd (list[str]): The executable and arguments to record.
            kwargs (object): Additional subprocess or seek keyword arguments.

        Returns:
            subprocess.CompletedProcess[str]: A successful completed process with a fake encoder listing.
        """
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, " V....D hevc_nvenc NVIDIA NVENC hevc encoder\n", "")
    monkeypatch.setattr(media, "run_command", fake_run)
    assert media.encoder_available(Settings(), "hevc_nvenc", main10=True)
    assert not media.encoder_available(Settings(), "av1_nvenc")
    assert all(cmd[1:] == ["-hide_banner", "-encoders"] for cmd in seen)


def test_custom_mkv_option_and_legacy_names() -> None:
    """Verify Custom MKV exports and legacy recipe aliases remain supported.

    Returns:
        None: No value is returned.
    """
    from nvs.export_presets import selected_recipe
    assert selected_recipe("Standard") is None
    assert selected_recipe("Custom") is None
    assert selected_recipe("HEVC 10-bit / NVENC P7 CQ20").cq == 20
    assert RenderOptions(container="MKV", export_preset="Custom").container == "MKV"
    with pytest.raises(ValidationError):
        RenderOptions(container="MKV", export_preset="AV1 - Efficient (CQ20)")
