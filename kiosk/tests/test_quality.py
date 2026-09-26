"""kiosk/quality.py -- frames that can't give a trustworthy embedding (looking
down, turned away, occluded, dark, blurry, cut off) are rejected BEFORE
embedding, which is what stops one person turning into many UNK- ids."""
from __future__ import annotations

import numpy as np

from kiosk.quality import QualityConfig, assess, pitch_ratio

CX, CY = 320, 240
BOX = (float(CX - 100), float(CY - 130), float(CX + 100), float(CY + 130))


def _frame(level: int = 180, textured: bool = True) -> np.ndarray:
    frame = np.full((480, 640, 3), 40, dtype=np.uint8)
    if textured:
        block = np.random.default_rng(1).integers(level - 30, level + 30, size=(260, 200, 3)).clip(0, 255).astype(np.uint8)
    else:
        block = np.full((260, 200, 3), level, dtype=np.uint8)
    frame[CY - 130 : CY + 130, CX - 100 : CX + 100] = block
    return frame


def _kps(nose_dy: float = 0.0, nose_dx: float = 0.0) -> np.ndarray:
    # eyes at y-60, mouth at y+60 -> nose at y gives pitch ratio 0.5 (level head)
    return np.array(
        [[CX - 60, CY - 60], [CX + 60, CY - 60], [CX + nose_dx, CY + nose_dy], [CX - 40, CY + 60], [CX + 40, CY + 60]],
        dtype=np.float32,
    )


def test_good_frontal_face_passes() -> None:
    r = assess(_frame(), BOX, _kps(), 0.9, QualityConfig())
    assert r.ok and r.reason is None and 0 < r.score <= 1


def test_looking_down_is_rejected() -> None:
    kps = _kps(nose_dy=40)  # nose nearly on the mouth line
    assert pitch_ratio(kps) > 0.75
    assert assess(_frame(), BOX, kps, 0.9, QualityConfig()).reason == "looking_up_or_down"


def test_turned_sideways_is_rejected() -> None:
    assert assess(_frame(), BOX, _kps(nose_dx=55), 0.9, QualityConfig()).reason == "turned_sideways"


def test_low_detector_confidence_is_rejected() -> None:
    # e.g. a hand over the face
    assert assess(_frame(), BOX, _kps(), 0.45, QualityConfig()).reason == "low_det_score"


def test_dark_and_blurry_faces_are_rejected() -> None:
    assert assess(_frame(level=20), BOX, _kps(), 0.9, QualityConfig()).reason == "too_dark"
    assert assess(_frame(textured=False), BOX, _kps(), 0.9, QualityConfig()).reason == "blurry"


def test_face_cut_off_by_frame_edge_is_rejected() -> None:
    cut = (float(CX - 100), 0.0, float(CX + 100), float(CY + 130))
    assert assess(_frame(), cut, _kps(), 0.9, QualityConfig()).reason == "face_cut_off"


def test_gate_can_be_switched_off_from_settings() -> None:
    assert assess(_frame(level=20), BOX, _kps(nose_dy=40), 0.1, QualityConfig(enabled=False)).ok
