from fractions import Fraction

from nvs.media import VideoInfo


def test_video_info_serializes_fraction() -> None:
    """Verify rational frame rates serialize as numeric video metadata.

    Returns:
        None: No value is returned.
    """
    info = VideoInfo(1920, 1080, 0, 300, Fraction(30000, 1001),
                     Fraction(1, 30000), 10.01, False, True)
    assert info.to_dict()['fps'] > 29
    assert info.to_dict()['frames'] == 300
