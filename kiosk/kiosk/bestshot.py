"""Step 4 -- BEST-SHOT SELECTION.

Buffers up to `bestshot_frames` candidate detections over ~1.5s and scores
each by sharpness (Laplacian variance) x frontality (from 5-point landmark
symmetry) x face_area. Only the single highest-scoring crop proceeds to
liveness + embedding. Pure OpenCV/numpy -- no ML model involved, so this
buffering never pays the ArcFace recognition cost more than once per visit
(see docs/DECISIONS.md on why detection and embedding are split into two
separate model calls).
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import cv2
import numpy as np

Box = tuple[float, float, float, float]


@dataclass
class Candidate:
    frame: np.ndarray
    box: Box
    kps: np.ndarray  # shape (5, 2): left_eye, right_eye, nose, mouth_left, mouth_right
    det_score: float
    track_id: str | None = None
    timestamp: float = 0.0


def crop_box(frame: np.ndarray, box: Box) -> np.ndarray:
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = [int(max(0, v)) for v in box]
    x2, y2 = min(w, x2), min(h, y2)
    if x2 <= x1 or y2 <= y1:
        return frame[0:1, 0:1]
    return frame[y1:y2, x1:x2]


def sharpness_score(crop: np.ndarray) -> float:
    if crop.size == 0:
        return 0.0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def frontality_score(kps: np.ndarray) -> float:
    """1.0 = perfectly frontal, lower = more profile/yaw. Estimated from the
    horizontal symmetry of the two eyes and two mouth corners around the
    nose -- a well-known cheap proxy for yaw that needs no extra model."""
    if kps is None or len(kps) < 5:
        return 0.5
    left_eye, right_eye, nose, mouth_left, mouth_right = kps[:5]

    eye_span = np.linalg.norm(right_eye - left_eye) or 1e-6
    eye_mid = (left_eye + right_eye) / 2.0
    eye_offset = abs(nose[0] - eye_mid[0]) / eye_span

    mouth_span = np.linalg.norm(mouth_right - mouth_left) or 1e-6
    mouth_mid = (mouth_left + mouth_right) / 2.0
    mouth_offset = abs(nose[0] - mouth_mid[0]) / mouth_span

    deviation = (eye_offset + mouth_offset) / 2.0
    return float(max(0.0, 1.0 - min(deviation, 1.0)))


def face_area_score(box: Box, frame_shape: tuple[int, ...]) -> float:
    h, w = frame_shape[:2]
    frame_area = max(1.0, h * w)
    x1, y1, x2, y2 = box
    area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    return float(min(1.0, area / frame_area * 10))  # *10: a face rarely exceeds 10% of frame


def score_candidate(candidate: Candidate) -> float:
    crop = crop_box(candidate.frame, candidate.box)
    sharp = sharpness_score(crop)
    # Normalize sharpness into a comparable 0..1-ish range (Laplacian variance
    # is unbounded above; empirically >500 is already very sharp for a face
    # crop, so we soft-clip there rather than let one super-sharp outlier
    # dominate the product).
    sharp_norm = min(1.0, sharp / 500.0)
    frontal = frontality_score(candidate.kps)
    area = face_area_score(candidate.box, candidate.frame.shape)
    return sharp_norm * frontal * area


class BestShotBuffer:
    def __init__(self, max_frames: int = 5, window_seconds: float = 1.5) -> None:
        self.max_frames = max_frames
        self.window_seconds = window_seconds
        self._candidates: list[Candidate] = []
        self._started_at: float | None = None

    def reset(self) -> None:
        self._candidates = []
        self._started_at = None

    def add(self, candidate: Candidate, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        candidate.timestamp = now
        if self._started_at is None:
            self._started_at = now
        self._candidates.append(candidate)

    def ready(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        if not self._candidates:
            return False
        if len(self._candidates) >= self.max_frames:
            return True
        if self._started_at is not None and (now - self._started_at) >= self.window_seconds:
            return True
        return False

    def best(self) -> Candidate | None:
        if not self._candidates:
            return None
        return max(self._candidates, key=score_candidate)

    def has_pending(self) -> bool:
        return bool(self._candidates)

    def candidates(self) -> list[Candidate]:
        return list(self._candidates)
