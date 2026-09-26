"""Unit tests for kiosk/subject_gate.py (spec step 1b, checks 1-3): track
continuity, bounding-box IoU dedupe, and embedding-similarity dedupe."""
from __future__ import annotations

import numpy as np
import pytest

from kiosk.subject_gate import SubjectGate, SubjectGateConfig, cosine_similarity, iou

BOX_A = (100.0, 100.0, 200.0, 240.0)
BOX_A_SHIFTED = (105.0, 100.0, 205.0, 240.0)  # high IoU with BOX_A
BOX_FAR = (500.0, 500.0, 600.0, 640.0)  # ~zero IoU with BOX_A


def test_iou_identical_boxes_is_one():
    assert iou(BOX_A, BOX_A) == pytest.approx(1.0)


def test_iou_disjoint_boxes_is_zero():
    assert iou(BOX_A, BOX_FAR) == 0.0


def test_iou_partial_overlap_between_zero_and_one():
    score = iou(BOX_A, BOX_A_SHIFTED)
    assert 0.0 < score < 1.0


def test_cosine_similarity_identical_vectors_is_one():
    v = np.array([1.0, 2.0, 3.0])
    assert cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors_is_zero():
    a = np.array([1.0, 0.0])
    b = np.array([0.0, 1.0])
    assert cosine_similarity(a, b) == pytest.approx(0.0)


def test_new_track_at_time_zero_is_processed():
    gate = SubjectGate()
    decision = gate.check_pre_embedding(BOX_A, now=0.0)
    assert decision.process is True
    assert decision.is_new_track is True
    assert decision.track_id is not None


def test_check_1_already_recognized_track_still_present_is_skipped():
    gate = SubjectGate()
    d1 = gate.check_pre_embedding(BOX_A, now=0.0)
    embedding = np.random.default_rng(0).random(512)
    gate.record_processed(BOX_A, embedding=embedding, track_id=d1.track_id, now=0.0)

    # Same track (near-identical box, well within the timeout) reappears a
    # split second later -- check 1 (track continuity) should skip it before
    # check 2 even runs.
    d2 = gate.check_pre_embedding(BOX_A, now=0.05)
    assert d2.process is False
    assert d2.reason == "track_continuity"
    assert d2.track_id == d1.track_id


def test_check_2_iou_dedupe_within_window_blocks_even_a_new_track():
    """A brief occlusion breaks the track (new track_id assigned), but the box
    is still essentially the same spot as the last *processed* face within
    the dedupe window -- check 2 must still catch this."""
    config = SubjectGateConfig(dedupe_window_minutes=5.0)
    gate = SubjectGate(config)
    d1 = gate.check_pre_embedding(BOX_A, now=0.0)
    embedding = np.random.default_rng(0).random(512)
    gate.record_processed(BOX_A, embedding=embedding, track_id=d1.track_id, now=0.0)

    # Force a "new" track by evicting the old one (simulate > TRACK_TIMEOUT_SECONDS
    # gap) but stay well within the dedupe window.
    d2 = gate.check_pre_embedding(BOX_A_SHIFTED, now=3.0)
    assert d2.process is False
    assert d2.reason == "iou_same_subject"


def test_check_2_outside_dedupe_window_allows_reprocessing():
    config = SubjectGateConfig(dedupe_window_minutes=0.01)  # 0.6 seconds
    gate = SubjectGate(config)
    d1 = gate.check_pre_embedding(BOX_A, now=0.0)
    embedding = np.random.default_rng(0).random(512)
    gate.record_processed(BOX_A, embedding=embedding, track_id=d1.track_id, now=0.0)

    d2 = gate.check_pre_embedding(BOX_A, now=10.0)  # long after the window closed
    assert d2.process is True


def test_check_3_embedding_similarity_blocks_same_person_different_box():
    """Same person walks to a different spot in frame (breaks IoU + maybe
    track) -- the embedding ring buffer should still catch it as a dedupe."""
    gate = SubjectGate()
    embedding = np.random.default_rng(0).random(512)
    gate.record_processed(BOX_A, embedding=embedding, track_id="t1", now=0.0)

    decision = gate.check_embedding(embedding, now=1.0)  # identical embedding
    assert decision.process is False
    assert decision.reason == "embedding_similarity"


def test_check_3_dissimilar_embedding_is_a_genuine_new_subject():
    gate = SubjectGate()
    rng = np.random.default_rng(0)
    e1 = rng.random(512)
    e2 = rng.random(512) + 10.0  # very different direction
    gate.record_processed(BOX_A, embedding=e1, track_id="t1", now=0.0)

    decision = gate.check_embedding(e2, now=1.0)
    assert decision.process is True


def test_check_3_ignores_entries_outside_the_dedupe_window():
    config = SubjectGateConfig(dedupe_window_minutes=0.01)  # 0.6s
    gate = SubjectGate(config)
    embedding = np.random.default_rng(0).random(512)
    gate.record_processed(BOX_A, embedding=embedding, track_id="t1", now=0.0)

    decision = gate.check_embedding(embedding, now=100.0)  # long expired
    assert decision.process is True


def test_left_and_reentered_after_timeout_starts_a_new_track():
    gate = SubjectGate()
    d1 = gate.check_pre_embedding(BOX_A, now=0.0)
    embedding = np.random.default_rng(0).random(512)
    gate.record_processed(BOX_A, embedding=embedding, track_id=d1.track_id, now=0.0)

    # Long enough gap to evict the track AND clear the dedupe window.
    d2 = gate.check_pre_embedding(BOX_FAR, now=1000.0)
    assert d2.is_new_track is True
    assert d2.process is True


def test_record_processed_with_no_embedding_does_not_pollute_the_ring_buffer():
    """Regression test: `record_processed(embedding=None, ...)` is the real
    call the pipeline makes for too_small/liveness_failed rejects (see
    kiosk/pipeline.py) -- there is no embedding to compare future visitors
    against. Before this was guarded, a None embedding was coerced with
    `np.asarray(None, dtype=np.float64)` into a 0-d nan array and pushed into
    the ring buffer; the next `check_embedding()` call would then broadcast
    a real 512-d embedding against that 0-d entry inside cosine_similarity()
    and raise TypeError ("only length-1 arrays can be converted to Python
    scalars"), crashing the whole recognition pipeline on the very next
    visitor. This proves a no-embedding reject is now silently skipped
    instead."""
    gate = SubjectGate()
    gate.record_processed(BOX_A, embedding=None, track_id="t1", now=0.0)
    assert len(gate._ring) == 0

    # A real visitor arriving shortly after must still be checkable without
    # crashing, and -- since the ring is empty -- must be treated as new.
    real_embedding = np.random.default_rng(0).random(512)
    decision = gate.check_embedding(real_embedding, now=0.5)
    assert decision.process is True


def test_record_processed_mixes_no_embedding_and_real_embedding_rejects_safely():
    gate = SubjectGate()
    rng = np.random.default_rng(1)
    seen = rng.random(512)
    seen /= np.linalg.norm(seen)

    gate.record_processed(BOX_A, embedding=None, track_id="t1", now=0.0)
    gate.record_processed(BOX_A, embedding=seen, track_id="t1", now=0.1)
    assert len(gate._ring) == 1

    decision = gate.check_embedding(seen, now=0.2)
    assert decision.process is False
    assert decision.reason == "embedding_similarity"
