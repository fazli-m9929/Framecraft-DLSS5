import io

import numpy as np
import pytest

from nvs.native import (
    FRAME_HEADER,
    FRAME_MAGIC,
    OUTPUT_HEADER,
    OUTPUT_MAGIC,
    VIDEO_HEADER,
    VIDEO_MAGIC,
    ProcessControl,
    RenderCancelled,
    read_exact,
)


def test_exact_worker_protocol_lengths_and_roundtrip() -> None:
    """Verify native packet sizes and packed field order.

    Returns:
        None: No value is returned.
    """
    assert VIDEO_HEADER.size == 56
    assert FRAME_HEADER.size == 24
    assert OUTPUT_HEADER.size == 28
    packed = VIDEO_HEADER.pack(VIDEO_MAGIC, 10, 20, 0, 5, 2, 2, 2, 1, 0, 1.65, 1.4, 1.5, 1)
    assert VIDEO_HEADER.unpack(packed)[:5] == (VIDEO_MAGIC, 10, 20, 0, 5)
    result = OUTPUT_HEADER.unpack(OUTPUT_HEADER.pack(OUTPUT_MAGIC, 0, 1, 800, 1, 27))
    assert result == (OUTPUT_MAGIC, 0, 1, 800, 1, 27)


def test_read_exact_fragmented() -> None:
    """Verify exact reads combine fragments and reject premature EOF.

    Returns:
        None: No value is returned.
    """
    class Frag(io.BytesIO):
        """Limit read sizes to simulate fragmented worker output."""
        def read(self, size: int=-1) -> bytes:
            """Return at most three bytes to simulate a fragmented binary stream.

            Args:
                size (int): The maximum requested byte count.

            Returns:
                bytes: The next fragment of the byte stream.
            """
            return super().read(min(size, 3))
    assert read_exact(Frag(b'abcdefghij'), 10) == b'abcdefghij'
    with pytest.raises(EOFError):
        read_exact(Frag(b'ab'), 10)


def test_motion_buffer_layout() -> None:
    """Verify the serialized FP16 motion buffer byte count.

    Returns:
        None: No value is returned.
    """
    mv = np.zeros((2, 3, 2), dtype=np.float16)
    assert len(mv.tobytes()) == 2 * 3 * 2 * 2


def test_cancel_state() -> None:
    """Verify cancelled controllers raise RenderCancelled.

    Returns:
        None: No value is returned.
    """
    control = ProcessControl()
    control.stop()
    with pytest.raises(RenderCancelled):
        control.check()
