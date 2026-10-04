"""Face QUALITY GATE -- runs on best-shot candidates, before liveness/embedding.

Why this exists (found on a real deployment, 2026-09-25): the same person
kept getting a brand-new UNK- id on almost every visit. Measuring the stored
embeddings showed two sightings of the same person taken seconds apart
scored a median cosine similarity of only ~0.34 (ArcFace normally gives
0.5-0.8 for the same person). The saved crops explained why: head tilted
down at a laptop, a hand over the face, dim light, forehead cut off by the
frame edge. Garbage-in embeddings can't be matched reliably by ANY
threshold, so the fix is to stop embedding bad frames in the first place.

Every check is cheap (landmarks + a few pixel stats -- no extra model), and
every limit is a runtime setting (NON-NEGOTIABLE #1), with `quality_gate_enabled`
as the off switch. A person standing at the camera for ~1-2 s produces
several frames, so rejecting the bad ones just means we wait for a good one.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from kiosk.bestshot import Box, crop_box, frontality_score


@dataclass
class QualityConfig:
    enabled: bool = True
    min_det_score: float = 0.60  # low detector confidence ~ occluded / blurred / odd angle
    min_frontality: float = 0.50  # yaw proxy, 1.0 = looking straight at the camera
    min_pitch_ratio: float = 0.28  # nose position between eyes (0) and mouth (1);
    max_pitch_ratio: float = 0.75  # ~0.5 when level, rises when looking down
    min_brightness: float = 40.0  # mean grey level of the face crop (0-255)
    min_sharpness: float = 20.0  # Laplacian variance on a 112x112 grey crop
    edge_margin: float = 0.01  # face box must not touch the frame edge (fraction of frame)
    # Combined score below this = reject. Added 2026-09-29: a hand over the
    # face passed every single check above (landmarks are still predicted)
    # but scored 0.35-0.41, against 0.73-0.76 for the same person's clear
    # face, and became an "unknown" person.
    min_score: float = 0.50


@dataclass
class QualityResult:
    ok: bool
    reason: str | None
    score: float  # 0..1, only meaningful when ok


def pitch_ratio(kps: np.ndarray) -> float:
    """Vertical position of the nose tip between the eye line (0.0) and the
    mouth line (1.0). ~0.5 for a level head; looking down pushes it up
    towards the mouth, looking up pulls it towards the eyes."""
    left_eye, right_eye, nose, mouth_left, mouth_right = kps[:5]
    eye_y = (left_eye[1] + right_eye[1]) / 2.0
    mouth_y = (mouth_left[1] + mouth_right[1]) / 2.0
    span = mouth_y - eye_y
    if span <= 1e-6:
        return -1.0  # degenerate / upside-down landmarks
    return float((nose[1] - eye_y) / span)


def assess(frame: np.ndarray, box: Box, kps: np.ndarray | None, det_score: float, cfg: QualityConfig) -> QualityResult:
    if not cfg.enabled:
        return QualityResult(ok=True, reason=None, score=1.0)

    if det_score < cfg.min_det_score:
        return QualityResult(ok=False, reason="low_det_score", score=0.0)

    h, w = frame.shape[:2]
    mx, my = cfg.edge_margin * w, cfg.edge_margin * h
    x1, y1, x2, y2 = box
    if x1 < mx or y1 < my or x2 > w - mx or y2 > h - my:
        return QualityResult(ok=False, reason="face_cut_off", score=0.0)

    if kps is None or len(kps) < 5:
        return QualityResult(ok=False, reason="no_landmarks", score=0.0)

    frontal = frontality_score(kps)
    if frontal < cfg.min_frontality:
        return QualityResult(ok=False, reason="turned_sideways", score=0.0)

    pitch = pitch_ratio(kps)
    if not (cfg.min_pitch_ratio <= pitch <= cfg.max_pitch_ratio):
        return QualityResult(ok=False, reason="looking_up_or_down", score=0.0)

    crop = crop_box(frame, box)
    if crop.size == 0:
        return QualityResult(ok=False, reason="empty_crop", score=0.0)
    grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    grey = cv2.resize(grey, (112, 112))
    brightness = float(grey.mean())
    if brightness < cfg.min_brightness:
        return QualityResult(ok=False, reason="too_dark", score=0.0)
    sharpness = float(cv2.Laplacian(grey, cv2.CV_64F).var())
    if sharpness < cfg.min_sharpness:
        return QualityResult(ok=False, reason="blurry", score=0.0)

    # Combined score used to rank passing candidates: pose closeness to level,
    # detector confidence and sharpness (soft-clipped).
    pitch_closeness = max(0.0, 1.0 - abs(pitch - 0.5) * 2.0)
    score = float(min(1.0, det_score * frontal * (0.5 + 0.5 * pitch_closeness) * min(1.0, sharpness / 200.0 + 0.5)))
    if score < cfg.min_score:
        return QualityResult(ok=False, reason="low_quality_score", score=score)  # e.g. hand over the face
    return QualityResult(ok=True, reason=None, score=score)
