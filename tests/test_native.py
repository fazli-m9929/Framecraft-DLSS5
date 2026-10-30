import io

import numpy as np
import pytest

from nvs.native import (FRAME_HEADER, FRAME_MAGIC, OUTPUT_HEADER, OUTPUT_MAGIC,
                        VIDEO_HEADER, VIDEO_MAGIC, read_exact, ProcessControl, RenderCancelled)


def test_exact_worker_protocol_lengths_and_roundtrip():
    assert VIDEO_HEADER.size == 56
    assert FRAME_HEADER.size == 24
    assert OUTPUT_HEADER.size == 28
    packed = VIDEO_HEADER.pack(VIDEO_MAGIC, 10, 20, 0, 5, 2, 2, 2, 1, 0, 1.65, 1.4, 1.5, 1)
    assert VIDEO_HEADER.unpack(packed)[:5] == (VIDEO_MAGIC, 10, 20, 0, 5)
    result = OUTPUT_HEADER.unpack(OUTPUT_HEADER.pack(OUTPUT_MAGIC, 0, 1, 800, 1, 27))
    assert result == (OUTPUT_MAGIC, 0, 1, 800, 1, 27)


def test_read_exact_fragmented():
    class Frag(io.BytesIO):
        def read(self, size=-1):
            return super().read(min(size, 3))
    assert read_exact(Frag(b'abcdefghij'), 10) == b'abcdefghij'
    with pytest.raises(EOFError):
        read_exact(Frag(b'ab'), 10)


def test_motion_buffer_layout():
    mv = np.zeros((2, 3, 2), dtype=np.float16)
    assert len(mv.tobytes()) == 2 * 3 * 2 * 2


def test_cancel_state():
    control = ProcessControl()
    control.stop()
    with pytest.raises(RenderCancelled):
        control.check()
