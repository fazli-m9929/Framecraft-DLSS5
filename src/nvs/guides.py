from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(slots=True)
class Guides:
    """Carry current-to-previous motion vectors and scene-reset information.

    Args:
        motion (np.ndarray): The FP16 current-to-previous motion vectors.
        reset (bool): Whether temporal history must be reset.
        scene_score (float): The normalized change between consecutive frames.
    """
    motion: np.ndarray
    reset: bool
    scene_score: float


class MotionGuide:
    """Estimate current-to-previous motion in output-pixel units."""

    def __init__(self, width: int, height: int, flow_width: int = 640, cut_threshold: float = .24) -> None:
        """Initialize the optical-flow estimator and scene-change threshold.

        Args:
            width (int): The output frame width in pixels.
            height (int): The output frame height in pixels.
            flow_width (int): The target width used for reduced-resolution optical flow.
            cut_threshold (float): The normalized scene-change score that triggers a reset.

        Returns:
            None: No value is returned.
        """
        self.width, self.height = width, height
        self.small_width = max(64, round(min(width, flow_width) / 2) * 2)
        self.small_height = max(64, round(height * self.small_width / width / 2) * 2)
        self.threshold = cut_threshold
        self.previous: np.ndarray | None = None
        self.dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
        self.dis.setUseSpatialPropagation(True)
        self.dis.setFinestScale(1)

    def process(self, rgba: np.ndarray) -> Guides:
        """Estimate motion from an RGBA frame and reset on first frames or scene cuts.

        Args:
            rgba (np.ndarray): The RGBA8 image with shape (height, width, 4).

        Returns:
            Guides: Contiguous FP16 motion vectors, reset status, and scene-change score.
        """
        gray = cv2.cvtColor(rgba, cv2.COLOR_RGBA2GRAY)
        gray = cv2.resize(gray, (self.small_width, self.small_height), interpolation=cv2.INTER_AREA)
        score = 1.0 if self.previous is None else float(np.mean(cv2.absdiff(gray, self.previous))) / 255
        reset = self.previous is None or score > self.threshold
        if reset:
            motion = np.zeros((self.height, self.width, 2), dtype=np.float16)
        else:
            small = self.dis.calc(gray, self.previous, None)
            motion32 = cv2.resize(small, (self.width, self.height), interpolation=cv2.INTER_LINEAR)
            motion32[..., 0] *= self.width / self.small_width
            motion32[..., 1] *= self.height / self.small_height
            motion = motion32.astype(np.float16)
        self.previous = gray
        return Guides(np.ascontiguousarray(motion), reset, score)
