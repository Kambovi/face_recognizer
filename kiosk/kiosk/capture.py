"""Step 1 -- frame capture.

`CAMERA_SOURCE=synthetic` drives the kiosk from procedurally-drawn PIL faces
so the whole system is demonstrable end-to-end without real camera hardware
(see docs/DECISIONS.md and scripts/seed_demo.py, which draws the same style
of synthetic face for the demo dataset). Any other value is treated as a
`cv2.VideoCapture` source: an integer camera index, or an rtsp:// URL.
"""
from __future__ import annotations

import time
from typing import Protocol

import cv2
import numpy as np
import structlog

logger = structlog.get_logger(__name__)


class FrameSource(Protocol):
    def read(self) -> np.ndarray | None: ...

    def release(self) -> None: ...


class CameraFrameSource:
    def __init__(self, source: str) -> None:
        target: int | str = int(source) if source.isdigit() else source
        self._cap = cv2.VideoCapture(target)
        if not self._cap.isOpened():
            logger.warning("camera_open_failed", source=source)

    def read(self) -> np.ndarray | None:
        ok, frame = self._cap.read()
        return frame if ok else None

    def release(self) -> None:
        self._cap.release()


class SyntheticFrameSource:
    """Cycles: a long stretch of an empty (static) background frame, then a
    procedurally-drawn synthetic face held steady for ~2 seconds (enough to
    satisfy best-shot buffering), then back to empty. Good enough to drive
    the motion gate, subject gate, and best-shot buffer realistically for
    local demo/dev without a camera."""

    def __init__(self, frame_size: tuple[int, int] = (480, 640)) -> None:
        self.frame_size = frame_size
        self._background = np.full((*frame_size, 3), 40, dtype=np.uint8)
        self._visitor_face: np.ndarray | None = None
        self._visitor_until: float = 0.0
        self._rng = np.random.default_rng(42)

    def _draw_face(self) -> np.ndarray:
        from PIL import Image, ImageDraw

        h, w = self.frame_size
        img = Image.new("RGB", (w, h), (40, 40, 40))
        draw = ImageDraw.Draw(img)
        cx, cy = w // 2, h // 2
        skin = tuple(int(v) for v in self._rng.integers(150, 220, size=3))
        draw.ellipse((cx - 100, cy - 130, cx + 100, cy + 130), fill=skin)
        draw.ellipse((cx - 45, cy - 30, cx - 15, cy), fill=(30, 30, 30))
        draw.ellipse((cx + 15, cy - 30, cx + 45, cy), fill=(30, 30, 30))
        draw.line((cx, cy, cx, cy + 40), fill=(100, 70, 70), width=3)
        draw.arc((cx - 40, cy + 30, cx + 40, cy + 70), start=20, end=160, fill=(80, 40, 40), width=4)
        return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

    def read(self) -> np.ndarray | None:
        now = time.monotonic()
        if now < self._visitor_until and self._visitor_face is not None:
            return self._visitor_face.copy()

        # ~6% chance per call a new "visitor" walks up, held for 2 seconds --
        # roughly matches the spec's "kiosk unoccupied ~94% of the day" framing.
        if self._rng.random() < 0.06:
            self._visitor_face = self._draw_face()
            self._visitor_until = now + 2.0
            return self._visitor_face.copy()

        return self._background.copy()

    def release(self) -> None:
        pass


def make_frame_source(camera_source: str) -> FrameSource:
    if camera_source == "synthetic":
        logger.info("camera_source_synthetic")
        return SyntheticFrameSource()
    return CameraFrameSource(camera_source)
