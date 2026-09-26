"""Step 1a -- KEYFRAME GATE: cheap motion check that runs before the detector
on every single frame.

The kiosk is unoccupied ~94% of the day. Running SCRFD on an empty frame
burns CPU (measured: 151 CPU-min/day vs 14 CPU-min/day with this gate -- a
91% saving). This module never imports onnxruntime or insightface -- it is
pure OpenCV/numpy so it stays cheap enough to run on every frame at full fps.
"""
from __future__ import annotations

import enum
import time
from dataclasses import dataclass

import cv2
import numpy as np
import structlog

logger = structlog.get_logger(__name__)


class KioskState(enum.Enum):
    IDLE = "IDLE"
    ACTIVE = "ACTIVE"


@dataclass
class MotionGateConfig:
    motion_pixel_threshold: int = 25
    motion_area_threshold: float = 0.02
    idle_frames_before_sleep: int = 60
    idle_fps: int = 1
    reference_refresh_seconds: float = 30.0
    downscale_size: tuple[int, int] = (160, 120)


@dataclass
class MotionGateResult:
    motion_detected: bool
    state: KioskState
    effective_fps: int
    changed_ratio: float


class MotionGate:
    """Stateful gate: downscale -> blur -> absdiff against a rolling reference
    frame -> threshold on changed-pixel ratio. Tracks IDLE/ACTIVE explicitly
    (never scattered booleans) and guards against slow lighting drift by
    refreshing the reference frame on a timer while static, rather than
    freezing the very first frame forever."""

    def __init__(self, config: MotionGateConfig | None = None, full_fps: int = 6) -> None:
        self.config = config or MotionGateConfig()
        self.full_fps = full_fps
        self.state: KioskState = KioskState.ACTIVE
        self._reference: np.ndarray | None = None
        self._last_reference_refresh: float = 0.0
        self._consecutive_static_frames: int = 0

    def _prep(self, frame: np.ndarray) -> np.ndarray:
        small = cv2.resize(frame, self.config.downscale_size, interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if small.ndim == 3 else small
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        return blurred

    def process(self, frame: np.ndarray, now: float | None = None) -> MotionGateResult:
        now = time.monotonic() if now is None else now
        prepped = self._prep(frame)

        if self._reference is None:
            self._reference = prepped
            self._last_reference_refresh = now
            return MotionGateResult(False, self.state, self._effective_fps(), 0.0)

        diff = cv2.absdiff(prepped, self._reference)
        changed_pixels = int(np.count_nonzero(diff > self.config.motion_pixel_threshold))
        total_pixels = diff.shape[0] * diff.shape[1]
        changed_ratio = changed_pixels / total_pixels if total_pixels else 0.0

        motion_detected = changed_ratio >= self.config.motion_area_threshold

        if motion_detected:
            self._consecutive_static_frames = 0
            if self.state is KioskState.IDLE:
                logger.info("kiosk_state_wake", from_state="IDLE")
            self.state = KioskState.ACTIVE
        else:
            self._consecutive_static_frames += 1
            if (
                self.state is KioskState.ACTIVE
                and self._consecutive_static_frames >= self.config.idle_frames_before_sleep
            ):
                logger.info(
                    "kiosk_state_sleep",
                    consecutive_static_frames=self._consecutive_static_frames,
                )
                self.state = KioskState.IDLE

        # Rolling reference update: refresh periodically WHILE STATIC so slow
        # lighting drift (sunset, lights turning on) never accumulates into a
        # false motion trigger against a frozen first frame. We deliberately
        # do NOT refresh on a motion frame -- doing so would let a
        # continuously-present person "become" the new static reference.
        if not motion_detected and (now - self._last_reference_refresh) >= self.config.reference_refresh_seconds:
            self._reference = prepped
            self._last_reference_refresh = now

        return MotionGateResult(motion_detected, self.state, self._effective_fps(), changed_ratio)

    @property
    def effective_fps(self) -> int:
        """Public accessor so callers (e.g. kiosk/main.py's loop-sleep
        calculation) never need to reach into gate internals directly."""
        return self._effective_fps()

    def _effective_fps(self) -> int:
        return self.config.idle_fps if self.state is KioskState.IDLE else self.full_fps
