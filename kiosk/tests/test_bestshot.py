"""Unit tests for kiosk/bestshot.py (spec step 4: best-shot selection)."""
from __future__ import annotations

import numpy as np
import pytest

from kiosk.bestshot import (
    BestShotBuffer,
    Candidate,
    crop_box,
    face_area_score,
    frontality_score,
    score_candidate,
    sharpness_score,
)


def _frame(h: int = 480, w: int = 640) -> np.ndarray:
    return np.full((h, w, 3), 128, dtype=np.uint8)


def _frontal_kps() -> np.ndarray:
    # left_eye, right_eye, nose, mouth_left, mouth_right -- symmetric around
    # the vertical midline (nose x == midpoint of eyes/mouth x).
    return np.array(
        [[260.0, 200.0], [300.0, 200.0], [280.0, 230.0], [265.0, 260.0], [295.0, 260.0]]
    )


def _profile_kps() -> np.ndarray:
    # Heavily skewed to one side -- nose far from both midpoints.
    return np.array(
        [[260.0, 200.0], [300.0, 200.0], [400.0, 230.0], [265.0, 260.0], [295.0, 260.0]]
    )


def test_crop_box_extracts_the_requested_region():
    frame = _frame()
    frame[100:200, 100:200] = 255
    crop = crop_box(frame, (100.0, 100.0, 200.0, 200.0))
    assert crop.shape == (100, 100, 3)
    assert (crop == 255).all()


def test_crop_box_clamps_out_of_bounds_box():
    frame = _frame()
    crop = crop_box(frame, (-50.0, -50.0, 10000.0, 10000.0))
    assert crop.shape[0] <= frame.shape[0]
    assert crop.shape[1] <= frame.shape[1]


def test_crop_box_degenerate_box_returns_tiny_fallback_not_a_crash():
    frame = _frame()
    crop = crop_box(frame, (300.0, 300.0, 300.0, 300.0))  # zero area
    assert crop.size > 0


def test_sharpness_score_of_flat_image_is_zero():
    flat = np.full((100, 100, 3), 128, dtype=np.uint8)
    assert sharpness_score(flat) == pytest.approx(0.0, abs=1e-6)


def test_sharpness_score_of_noisy_image_is_higher_than_flat():
    rng = np.random.default_rng(0)
    noisy = rng.integers(0, 255, size=(100, 100, 3), dtype=np.uint8)
    flat = np.full((100, 100, 3), 128, dtype=np.uint8)
    assert sharpness_score(noisy) > sharpness_score(flat)


def test_sharpness_score_empty_crop_is_zero():
    assert sharpness_score(np.zeros((0, 0, 3), dtype=np.uint8)) == 0.0


def test_frontality_score_frontal_face_near_one():
    assert frontality_score(_frontal_kps()) > 0.9


def test_frontality_score_profile_face_is_lower():
    assert frontality_score(_profile_kps()) < frontality_score(_frontal_kps())


def test_frontality_score_missing_landmarks_returns_neutral_default():
    assert frontality_score(None) == 0.5
    assert frontality_score(np.zeros((2, 2))) == 0.5


def test_face_area_score_larger_face_scores_higher():
    frame_shape = (480, 640)
    small_box = (300.0, 200.0, 340.0, 240.0)
    big_box = (100.0, 100.0, 400.0, 400.0)
    assert face_area_score(big_box, frame_shape) > face_area_score(small_box, frame_shape)


def test_face_area_score_is_capped_at_one():
    frame_shape = (10, 10)
    huge_box = (0.0, 0.0, 10.0, 10.0)
    assert face_area_score(huge_box, frame_shape) <= 1.0


def test_score_candidate_combines_all_three_factors():
    frame = _frame()
    good = Candidate(frame=frame, box=(100.0, 100.0, 300.0, 340.0), kps=_frontal_kps(), det_score=0.99)
    bad = Candidate(frame=frame, box=(300.0, 300.0, 310.0, 310.0), kps=_profile_kps(), det_score=0.5)
    assert score_candidate(good) >= score_candidate(bad)


def test_bestshot_buffer_not_ready_until_max_frames_or_window_elapsed():
    buf = BestShotBuffer(max_frames=3, window_seconds=10.0)
    frame = _frame()
    buf.add(Candidate(frame=frame, box=(0, 0, 10, 10), kps=_frontal_kps(), det_score=0.9), now=0.0)
    assert buf.ready(now=0.1) is False
    buf.add(Candidate(frame=frame, box=(0, 0, 10, 10), kps=_frontal_kps(), det_score=0.9), now=0.2)
    assert buf.ready(now=0.3) is False
    buf.add(Candidate(frame=frame, box=(0, 0, 10, 10), kps=_frontal_kps(), det_score=0.9), now=0.4)
    assert buf.ready(now=0.5) is True  # hit max_frames


def test_bestshot_buffer_ready_once_window_elapses_even_with_few_frames():
    buf = BestShotBuffer(max_frames=100, window_seconds=1.0)
    buf.add(Candidate(frame=_frame(), box=(0, 0, 10, 10), kps=_frontal_kps(), det_score=0.9), now=0.0)
    assert buf.ready(now=0.5) is False
    assert buf.ready(now=1.5) is True


def test_bestshot_buffer_best_returns_highest_scoring_candidate():
    buf = BestShotBuffer(max_frames=10, window_seconds=10.0)
    # Give the "sharp" frame actual texture (a flat frame has zero Laplacian
    # variance, i.e. zero sharpness_score) so it genuinely outscores the
    # flat, small, off-angle candidate rather than tying on sharpness.
    textured = np.random.default_rng(0).integers(0, 255, size=(480, 640, 3), dtype=np.uint8)
    sharp_frontal_big = Candidate(
        frame=textured, box=(50.0, 50.0, 350.0, 400.0), kps=_frontal_kps(), det_score=0.99
    )
    blurry_profile_small = Candidate(
        frame=np.full((480, 640, 3), 128, dtype=np.uint8),
        box=(300.0, 300.0, 320.0, 320.0),
        kps=_profile_kps(),
        det_score=0.9,
    )
    buf.add(blurry_profile_small, now=0.0)
    buf.add(sharp_frontal_big, now=0.1)
    best = buf.best()
    assert best is sharp_frontal_big


def test_bestshot_buffer_reset_clears_state():
    buf = BestShotBuffer(max_frames=3, window_seconds=1.0)
    buf.add(Candidate(frame=_frame(), box=(0, 0, 10, 10), kps=_frontal_kps(), det_score=0.9), now=0.0)
    assert buf.has_pending() is True
    buf.reset()
    assert buf.has_pending() is False
    assert buf.best() is None
    assert buf.ready(now=100.0) is False


def test_bestshot_buffer_best_on_empty_buffer_is_none():
    buf = BestShotBuffer()
    assert buf.best() is None
