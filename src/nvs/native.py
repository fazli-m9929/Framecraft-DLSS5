from __future__ import annotations

import hashlib
import re
import struct
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import BinaryIO

import numpy as np

from .config import Settings

# Values and byte packing are compatibility constants for perseval-BLR feature-18 worker.
VIDEO_MAGIC = 0x32563544
FRAME_MAGIC = 0x314D5246
OUTPUT_MAGIC = 0x3154554F
VIDEO_HEADER = struct.Struct("<10I4f")
FRAME_HEADER = struct.Struct("<4Iq")
OUTPUT_HEADER = struct.Struct("<5Iq")


class RenderCancelled(RuntimeError):
    """Signal that the user cancelled a render operation."""



def read_exact(stream: BinaryIO, size: int) -> bytes:
    """Read exactly the requested number of bytes or raise EOFError.

    Args:
        stream (BinaryIO): The binary input stream to read.
        size (int): The exact number of bytes required.

    Returns:
        bytes: The complete byte sequence.
    """
    buffer = bytearray()
    while len(buffer) < size:
        part = stream.read(size - len(buffer))
        if not part:
            raise EOFError(f"Worker returned {len(buffer)} of {size} required bytes")
        buffer.extend(part)
    return bytes(buffer)


def hash_file(path: Path) -> str:
    """Compute a file's SHA-256 digest using bounded memory.

    Args:
        path (Path): The filesystem path to resolve or process.

    Returns:
        str: The lowercase hexadecimal SHA-256 digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as src:
        for chunk in iter(lambda: src.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ProcessControl:
    """Track render subprocesses and coordinate thread-safe cancellation."""

    def __init__(self) -> None:
        """Initialize cancellation state and the subprocess registry.

        Returns:
            None: No value is returned.
        """
        self.cancelled = threading.Event()
        self._lock = threading.Lock()
        self._processes: list[subprocess.Popen[bytes]] = []

    def add(self, process: subprocess.Popen[bytes]) -> None:
        """Register a subprocess and terminate it if cancellation was already requested.

        Args:
            process (subprocess.Popen[bytes]): The binary-mode subprocess to track or inspect.

        Returns:
            None: No value is returned.
        """
        with self._lock:
            self._processes.append(process)
            if self.cancelled.is_set():
                self._terminate(process)

    def remove(self, process: subprocess.Popen[bytes]) -> None:
        """Remove a subprocess from the cancellation registry.

        Args:
            process (subprocess.Popen[bytes]): The binary-mode subprocess to track or inspect.

        Returns:
            None: No value is returned.
        """
        with self._lock:
            if process in self._processes:
                self._processes.remove(process)

    @staticmethod
    def _terminate(process: subprocess.Popen[bytes]) -> None:
        """Request termination of a running subprocess, ignoring OS errors.

        Args:
            process (subprocess.Popen[bytes]): The binary-mode subprocess to track or inspect.

        Returns:
            None: No value is returned.
        """
        if process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def stop(self) -> None:
        """Mark the render cancelled and terminate all registered subprocesses.

        Returns:
            None: No value is returned.
        """
        self.cancelled.set()
        with self._lock:
            for process in self._processes:
                self._terminate(process)

    def check(self) -> None:
        """Raise RenderCancelled when cancellation has been requested.

        Returns:
            None: No value is returned.
        """
        if self.cancelled.is_set():
            raise RenderCancelled("Cancelled by the user")


class ProcessLog:
    """Drain a subprocess's stderr and retain a bounded diagnostic history."""
    def __init__(self, process: subprocess.Popen[bytes], max_lines: int = 1500) -> None:
        """Start a background stderr reader for a subprocess.

        Args:
            process (subprocess.Popen[bytes]): The binary-mode subprocess to track or inspect.
            max_lines (int): The maximum number of stderr lines retained.

        Returns:
            None: No value is returned.
        """
        self.lines: deque[str] = deque(maxlen=max_lines)
        self.direct_create_result: str | None = None
        self.thread = threading.Thread(target=self._drain, args=(process,), daemon=True)
        self.thread.start()

    def _drain(self, process: subprocess.Popen[bytes]) -> None:
        """Collect stderr lines and parse native feature-18 initialization results.

        Args:
            process (subprocess.Popen[bytes]): The binary-mode subprocess to track or inspect.

        Returns:
            None: No value is returned.
        """
        if process.stderr:
            for line in iter(process.stderr.readline, b""):
                message = line.decode("utf-8", errors="replace").rstrip()
                self.lines.append(message)
                match = re.search(r"direct feature 18 ready:.*result=0x([0-9A-Fa-f]{8})", message, re.I)
                if match:
                    self.direct_create_result = "0x" + match.group(1).upper()

    def tail(self, lines: int = 50) -> str:
        """Join the most recent diagnostic lines.

        Args:
            lines (int): The maximum number of recent log lines to return.

        Returns:
            str: The requested log tail as newline-separated text.
        """
        return "\n".join(list(self.lines)[-lines:])


class NeuralWorker:
    """Exchange validated frame packets with the native feature-18 executable."""
    def __init__(
        self, settings: Settings, width: int, height: int, frame_count: int,
        warmup_frames: int, native: dict[str, float | int], control: ProcessControl
    ) -> None:
        """Launch the native video worker and send its startup configuration.

        Args:
            settings (Settings): Application paths, limits, and runtime configuration.
            width (int): The output frame width in pixels.
            height (int): The output frame height in pixels.
            frame_count (int): The exact number of frames expected by the worker.
            warmup_frames (int): The warmup frame count passed to the native worker.
            native (dict[str, float | int]): The effective native profile parameters.
            control (ProcessControl): The shared subprocess cancellation controller.

        Returns:
            None: No value is returned.
        """
        self.settings, self.width, self.height = settings, width, height
        self.control = control
        self.process = subprocess.Popen(
            [str(settings.worker), "--video"], cwd=settings.runtime,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=0, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        control.add(self.process)
        self.log = ProcessLog(self.process)
        self.evaluations = 0
        if self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("Native worker pipes unavailable")
        self.process.stdin.write(VIDEO_HEADER.pack(
            VIDEO_MAGIC, width, height, warmup_frames, frame_count,
            int(native["profile"]), int(native["preset"]), int(native["style"]),
            int(native["auto_mask"]), int(native["ui_correction"]),
            float(native["intensity"]), float(native["local_tone"]),
            float(native["local_structure"]), float(native["skin_structure"]),
        ))
        self.process.stdin.flush()

    def process_frame(
        self, index: int, rgba: np.ndarray, motion: np.ndarray,
        reset: bool, pts: int
    ) -> tuple[np.ndarray, int]:
        """Submit an RGBA frame and motion vectors and validate the native response.

        Args:
            index (int): The zero-based source or worker frame index.
            rgba (np.ndarray): The RGBA8 image with shape (height, width, 4).
            motion (np.ndarray): The FP16 motion vectors with shape (height, width, 2).
            reset (bool): Whether to reset the native temporal history for this frame.
            pts (int): The source presentation timestamp sent to the native worker.

        Returns:
            tuple[np.ndarray, int]: The processed RGBA8 frame and the worker's output timestamp.
        """
        self.control.check()
        assert rgba.dtype == np.uint8 and rgba.shape == (self.height, self.width, 4)
        assert motion.dtype == np.float16 and motion.shape == (self.height, self.width, 2)
        assert self.process.stdin is not None and self.process.stdout is not None
        self.process.stdin.write(FRAME_HEADER.pack(FRAME_MAGIC, index, int(reset), 0, pts))
        self.process.stdin.write(memoryview(np.ascontiguousarray(rgba)))
        self.process.stdin.write(memoryview(np.ascontiguousarray(motion)))
        self.process.stdin.flush()
        raw_header = read_exact(self.process.stdout, OUTPUT_HEADER.size)
        magic, response_index, valid, byte_count, result, out_pts = OUTPUT_HEADER.unpack(raw_header)
        if (magic != OUTPUT_MAGIC or response_index != index or valid != 1
                or byte_count != self.width * self.height * 4):
            raise RuntimeError(f"Invalid feature-18 worker packet at frame {index}: {raw_header.hex()}")
        if result != 1:
            raise RuntimeError(f"Feature-18 evaluation failed at frame {index}: 0x{result:08X}")
        data = read_exact(self.process.stdout, byte_count)
        self.evaluations += 1
        return np.frombuffer(data, dtype=np.uint8).reshape(self.height, self.width, 4), out_pts

    def finish(self) -> None:
        """Wait for clean worker exit and require successful feature-18 initialization.

        Returns:
            None: No value is returned.
        """
        if self.process.stdin and not self.process.stdin.closed:
            self.process.stdin.close()
        try:
            returncode = self.process.wait(timeout=90)
        except subprocess.TimeoutExpired as exc:
            self.control.stop()
            raise RuntimeError("Native worker did not finish in 90 seconds") from exc
        self.log.thread.join(timeout=3)
        self.control.remove(self.process)
        if returncode != 0:
            raise RuntimeError("Native worker failed:\n" + self.log.tail())
        if not self.log.direct_create_result:
            raise RuntimeError("Worker did not log a feature-18 initialization confirmation")
        if self.log.direct_create_result != "0x00000001":
            raise RuntimeError("Feature-18 creation reported failure: " + self.log.direct_create_result)

    def abort(self) -> None:
        """Terminate the worker if necessary and unregister its process.

        Returns:
            None: No value is returned.
        """
        if self.process.poll() is None:
            ProcessControl._terminate(self.process)
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.control.remove(self.process)
