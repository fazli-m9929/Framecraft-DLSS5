"""Exercise packet interoperability against an independent fake executable.

This does NOT establish DLSS model compatibility or inference validity.
"""

import os
import sys
from pathlib import Path

import numpy as np
import pytest

from nvs.config import Settings
from nvs.native import NeuralWorker, ProcessControl
from nvs.schemas import RenderOptions


@pytest.mark.skipif(os.name == "nt", reason="Test-only shebang executable used on Unix")
def test_native_worker_pipe_roundtrip(tmp_path: Path) -> None:
    """Exercise binary frame interoperability with a fake worker, without DLSS inference.

    Args:
        tmp_path (Path): The isolated temporary directory supplied by pytest.

    Returns:
        None: No value is returned.
    """
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    worker = runtime / "nvngx.dll"
    worker.write_text(f'''#!{sys.executable}
import sys, struct
r=sys.stdin.buffer; w=sys.stdout.buffer
hdr=r.read(56)
magic,width,height,warmup,nframes,*rest=struct.unpack('<10I4f',hdr)
assert magic == 0x32563544
sys.stderr.write('direct feature 18 ready: result=0x00000001\\n'); sys.stderr.flush()
for _ in range(nframes):
    packet=r.read(24)
    magic, idx, reset, reserved, pts=struct.unpack('<4Iq',packet)
    assert magic == 0x314D5246
    rgba=r.read(width*height*4)
    flow=r.read(width*height*4)
    assert len(flow) == width*height*4
    w.write(struct.pack('<5Iq',0x3154554F,idx,1,len(rgba),1,pts))
    w.write(rgba)
    w.flush()
''')
    worker.chmod(0o755)
    (runtime / "nvngx_dlssnr.dll").write_bytes(b"dummy")
    settings = Settings(runtime_dir=runtime, data_dir=tmp_path / "data")
    control = ProcessControl()
    native = NeuralWorker(settings, 4, 3, 2, 0, RenderOptions().native(), control)
    frame = np.full((3, 4, 4), 100, dtype=np.uint8)
    motion = np.zeros((3, 4, 2), dtype=np.float16)
    try:
        for i in range(2):
            result, pts = native.process_frame(i, frame, motion, i == 0, i * 5)
            assert (result == frame).all()
            assert pts == i * 5
        native.finish()
        assert native.evaluations == 2
    finally:
        native.abort()
