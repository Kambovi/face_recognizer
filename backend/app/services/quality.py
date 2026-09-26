"""Shared image-quality scoring (sharpness x frontality x size x detector
confidence). Used by enrollment (app/services/embedding.py) to accept/reject
uploaded photos. Deliberately simple, pure OpenCV/numpy -- mirrors
kiosk/kiosk/bestshot.py's scoring philosophy but is not the same code path
(enrollment scores a still photo once; the kiosk scores a rolling buffer of
live frames), so it is kept as its own small module rather than shared
across the two isolated Docker build contexts."""
from __future__ import annotations

import cv2
import numpy as np


def sharpness_score(crop: np.ndarray) -> float:
    if crop.size == 0:
        return 0.0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def frontality_score(kps: np.ndarray | None) -> float:
    if kps is None or len(kps) < 5:
        return 0.7
    left_eye, right_eye, nose, mouth_left, mouth_right = kps[:5]
    eye_span = np.linalg.norm(right_eye - left_eye) or 1e-6
    eye_mid = (left_eye + right_eye) / 2.0
    eye_offset = abs(nose[0] - eye_mid[0]) / eye_span
    mouth_span = np.linalg.norm(mouth_right - mouth_left) or 1e-6
    mouth_mid = (mouth_left + mouth_right) / 2.0
    mouth_offset = abs(nose[0] - mouth_mid[0]) / mouth_span
    deviation = (eye_offset + mouth_offset) / 2.0
    return float(max(0.0, 1.0 - min(deviation, 1.0)))


def compute_quality_score(
    image: np.ndarray,
    box: tuple[float, float, float, float],
    kps: np.ndarray | None,
    det_score: float,
) -> float:
    h, w = image.shape[:2]
    x1, y1, x2, y2 = [int(max(0, v)) for v in box]
    x2, y2 = min(w, x2), min(h, y2)
    crop = image[y1:y2, x1:x2] if x2 > x1 and y2 > y1 else image
    sharp_norm = min(1.0, sharpness_score(crop) / 500.0)
    frontal = frontality_score(kps)
    area_ratio = min(1.0, ((x2 - x1) * (y2 - y1)) / max(1.0, h * w) * 10)
    det_conf = max(0.0, min(1.0, det_score))
    # Weighted blend rather than a straight product: a product punishes any
    # single weak factor to near-zero (e.g. a slightly-off-center but sharp,
    # well-lit photo would score ~0), which is too harsh for still-photo
    # enrollment where we want a graded accept/reject line, not a cliff.
    return float(sharp_norm * 0.35 + frontal * 0.25 + area_ratio * 0.2 + det_conf * 0.2)
