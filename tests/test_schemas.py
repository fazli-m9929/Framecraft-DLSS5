import pytest
from pydantic import ValidationError

from nvs.schemas import PRESETS, Profile, RenderOptions


def test_native_presets_and_overrides() -> None:
    """Verify native profile defaults and explicit slider overrides.

    Returns:
        None: No value is returned.
    """
    assert len(PRESETS) == 4
    assert RenderOptions(profile=Profile.FAITHFUL).native()["intensity"] == .7
    payload = RenderOptions(profile=Profile.CINEMATIC, intensity=2.3).native()
    assert payload["intensity"] == 2.3
    assert payload["profile"] == 2
    assert payload["skin_structure"] == 1.0


def test_reject_bad_options() -> None:
    """Reject invalid profiles, unsupported export combinations, and unknown fields.

    Returns:
        None: No value is returned.
    """
    with pytest.raises(ValidationError):
        RenderOptions(profile="notreal")
    with pytest.raises(ValidationError):
        RenderOptions(codec="AV1", quality="Lossless")
    with pytest.raises(ValidationError):
        RenderOptions(intensity=7)
    with pytest.raises(ValidationError):
        RenderOptions(preserve_hdr=True)
