import numpy as np

from nvs.guides import MotionGuide


def test_first_frame_has_reset_and_zero_motion():
    g = MotionGuide(32, 24)
    frame = np.zeros((24, 32, 4), dtype=np.uint8)
    frame[..., 3] = 255
    result = g.process(frame)
    assert result.reset is True
    assert result.motion.shape == (24, 32, 2)
    assert result.motion.dtype == np.float16
    assert not result.motion.any()
    second = g.process(frame)
    assert second.reset is False
    assert second.motion.shape == (24, 32, 2)


def test_scene_cut_reset():
    guide = MotionGuide(64, 32)
    dark = np.zeros((32, 64, 4), dtype=np.uint8)
    white = dark.copy()
    white[..., :3] = 255
    guide.process(dark)
    result = guide.process(white)
    assert result.reset
    assert result.scene_score > .24
