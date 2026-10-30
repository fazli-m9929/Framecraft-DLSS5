"""Regression tests for precise counting and seek-based clip selection.

Uses a fake PyAV reader to make skipped ranges observable without a GPU.
"""

import sys
from collections.abc import Iterator
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from typing import Self

import pytest

from nvs.native import ProcessControl
from nvs.pipeline import count_clip_frames, iter_clip_frames


class FakeReader:
    """Simulate PyAV decoding and keyframe seeking for deterministic clip tests."""
    def __init__(self, count: int = 1200, frame_rate: int = 10) -> None:
        """Initialize synthetic frames, counters, and stream metadata.

        Args:
            count (int): The number of synthetic frames.
            frame_rate (int): The synthetic frame rate in frames per second.

        Returns:
            None: No value is returned.
        """
        self.frame_rate = frame_rate
        self.frames = [SimpleNamespace(pts=i) for i in range(count)]
        self.cursor = 0
        self.decoded = 0
        self.seeks = []
        self.stream = SimpleNamespace(time_base=Fraction(1, frame_rate), thread_type=None)
        self.streams = SimpleNamespace(video=[self.stream])

    def __enter__(self) -> Self:
        """Enter the synthetic reader context.

        Returns:
            Self: This reader instance.
        """
        return self

    def __exit__(self, *args: object) -> bool:
        """Leave the reader context without suppressing exceptions.

        Args:
            args (object): The context-manager exception details.

        Returns:
            bool: False so exceptions propagate.
        """
        return False

    def seek(self, offset: int, **kwargs: object) -> None:
        """Simulate backward seeking to the previous twenty-frame keyframe.

        Args:
            offset (int): The seek position in stream timestamp units.
            kwargs (object): Additional subprocess or seek keyword arguments.

        Returns:
            None: No value is returned.
        """
        assert kwargs == {"backward": True, "any_frame": False, "stream": self.stream}
        self.seeks.append(offset)
        # Simulate keyframe seeking: every 20 source frames.
        self.cursor = max(0, (offset // 20) * 20)

    def decode(self, stream: SimpleNamespace) -> Iterator[SimpleNamespace]:
        """Yield synthetic frames while tracking the amount of decoded footage.

        Args:
            stream (SimpleNamespace): The synthetic video stream to decode.

        Returns:
            Iterator[SimpleNamespace]: An iterator over synthetic decoded frames.
        """
        assert stream is self.stream
        while self.cursor < len(self.frames):
            frame = self.frames[self.cursor]
            self.cursor += 1
            self.decoded += 1
            yield frame


def test_counter_skips_deleted_range_and_matches_render(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify counting and rendering select identical frames while seeking over cuts.

    Args:
        monkeypatch (pytest.MonkeyPatch): The pytest fixture for replacing dependencies during the test.

    Returns:
        None: No value is returned.
    """
    clips = [(0., 2.05), (70.05, 75.05)]
    count_reader = FakeReader()
    render_reader = FakeReader()
    monkeypatch.setitem(sys.modules, 'av', SimpleNamespace(open=lambda _: count_reader))
    messages = []
    counted = count_clip_frames(Path('fake.mp4'), clips, Fraction(1, 10), Fraction(10, 1),
                                ProcessControl(), lambda p, m: messages.append((p, m)))
    selected = [frame.pts for _, frame, _ in iter_clip_frames(
        render_reader, render_reader.stream, clips, Fraction(1, 10), Fraction(10, 1), ProcessControl())]
    assert counted == len(selected) == 71
    assert selected[:3] == [0, 1, 2]
    assert selected[-3:] == [748, 749, 750]
    assert count_reader.seeks == [700]
    assert render_reader.seeks == [700]
    assert count_reader.decoded < 120
    assert render_reader.decoded < 120
    assert count_reader.stream.thread_type == 'AUTO'
    assert messages[0][1].startswith('Counting selected frames')
    assert messages[-1][0] == .09
    assert '71' in messages[-1][1]


def test_counter_can_be_cancelled_before_seeking(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify cancellation prevents clip scanning before any seek.

    Args:
        monkeypatch (pytest.MonkeyPatch): The pytest fixture for replacing dependencies during the test.

    Returns:
        None: No value is returned.
    """
    import pytest

    from nvs.native import RenderCancelled
    reader = FakeReader()
    monkeypatch.setitem(sys.modules, 'av', SimpleNamespace(open=lambda _: reader))
    control = ProcessControl()
    control.stop()
    with pytest.raises(RenderCancelled):
        count_clip_frames(Path('fake.mp4'), [(0., 3.)], Fraction(1, 10),
                          Fraction(10, 1), control)
