"""Regression tests for precise counting and seek-based clip selection.

Uses a fake PyAV reader to make skipped ranges observable without a GPU.
"""
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
import sys

from nvs.native import ProcessControl
from nvs.pipeline import count_clip_frames, iter_clip_frames


class FakeReader:
    def __init__(self, count: int = 1200, frame_rate: int = 10):
        self.frame_rate = frame_rate
        self.frames = [SimpleNamespace(pts=i) for i in range(count)]
        self.cursor = 0
        self.decoded = 0
        self.seeks = []
        self.stream = SimpleNamespace(time_base=Fraction(1, frame_rate), thread_type=None)
        self.streams = SimpleNamespace(video=[self.stream])

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def seek(self, offset, **kwargs):
        assert kwargs == {"backward": True, "any_frame": False, "stream": self.stream}
        self.seeks.append(offset)
        # Simulate keyframe seeking: every 20 source frames.
        self.cursor = max(0, (offset // 20) * 20)

    def decode(self, stream):
        assert stream is self.stream
        while self.cursor < len(self.frames):
            frame = self.frames[self.cursor]
            self.cursor += 1
            self.decoded += 1
            yield frame


def test_counter_skips_deleted_range_and_matches_render(monkeypatch):
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


def test_counter_can_be_cancelled_before_seeking(monkeypatch):
    import pytest
    from nvs.native import RenderCancelled
    reader = FakeReader()
    monkeypatch.setitem(sys.modules, 'av', SimpleNamespace(open=lambda _: reader))
    control = ProcessControl()
    control.stop()
    with pytest.raises(RenderCancelled):
        count_clip_frames(Path('fake.mp4'), [(0., 3.)], Fraction(1, 10),
                          Fraction(10, 1), control)
