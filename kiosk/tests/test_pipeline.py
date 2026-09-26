"""Integration-style tests for kiosk/pipeline.py, wiring real MotionGate +
SubjectGate + BestShotBuffer against fake FaceEngine/LivenessChecker so the
whole per-frame orchestration (spec steps 1-6) is exercised without real ML
weights.

NON-NEGOTIABLE #6 (idle cost near-zero) is tested here rather than in
test_motion_gate.py, because the actual claim is about the *detector*: a
static kiosk must never call FaceEngine.detect(), and that's only observable
once the gate is wired into the pipeline that guards the real detector call.
"""
from __future__ import annotations

import numpy as np
import pytest

from kiosk.face_engine import DetectedFace
from kiosk.liveness import LivenessChecker
from kiosk.offline_queue import OfflineQueue
from kiosk.pipeline import PipelineConfig, RecognitionPipeline


def _flat_frame(value: int = 40) -> np.ndarray:
    return np.full((480, 640, 3), value, dtype=np.uint8)


def _visitor_frame(cx: int = 320, cy: int = 240) -> np.ndarray:
    # Textured (not flat) block: a real face has detail, and the quality
    # gate (kiosk/quality.py) rejects featureless/blurry crops.
    frame = _flat_frame()
    texture = np.random.default_rng(7).integers(150, 230, size=(260, 200, 3), dtype=np.uint8)
    texture[130 - 1 : 130 + 1, 100 - 1 : 100 + 1] = 180  # keep the centre pixel deterministic for the fake detector
    frame[cy - 130 : cy + 130, cx - 100 : cx + 100] = texture
    return frame


class _CountingFaceEngine:
    """Wraps a real detection heuristic (bright-block-in-center => one face)
    behind the exact FaceEngine interface the pipeline depends on, while
    counting calls so idle-cost assertions are possible."""

    def __init__(self, embedding: np.ndarray | None = None) -> None:
        self.detect_calls = 0
        self.embed_calls = 0
        self._embedding = embedding if embedding is not None else np.random.default_rng(0).random(512).astype(np.float32)

    def detect(self, frame: np.ndarray) -> list[DetectedFace]:
        self.detect_calls += 1
        cy, cx = frame.shape[0] // 2, frame.shape[1] // 2
        if frame[cy, cx, 0] == 40:  # background value -> no face
            return []
        return [
            DetectedFace(
                box=(float(cx - 100), float(cy - 130), float(cx + 100), float(cy + 130)),
                kps=np.array([[cx - 60, cy - 60], [cx + 60, cy - 60], [cx, cy], [cx - 40, cy + 60], [cx + 40, cy + 60]], dtype=np.float32),
                det_score=0.95,
            )
        ]

    def embed(self, frame: np.ndarray, face: DetectedFace) -> np.ndarray | None:
        self.embed_calls += 1
        return self._embedding


@pytest.fixture
def offline_queue(tmp_path):
    return OfflineQueue(str(tmp_path / "queue.db"))


@pytest.fixture
def passthrough_liveness():
    # A loaded checker that always says "live" (liveness is fail-closed now,
    # so an unloaded checker would reject every face).
    checker = LivenessChecker(model_cache_dir="/tmp/models")
    checker.inject_for_tests(object())
    checker.check = lambda frame, box: 0.99  # type: ignore[method-assign]
    return checker


def _make_pipeline(face_engine, liveness, offline_queue, post_event_fn, **config_overrides):
    config = PipelineConfig(kiosk_id="kiosk-test", bestshot_frames=3, bestshot_window_seconds=0.05, **config_overrides)
    return RecognitionPipeline(config, face_engine, liveness, offline_queue, post_event_fn)


# --- NON-NEGOTIABLE #6: idle cost near-zero ----------------------------------

def test_600_static_frames_never_call_the_detector(offline_queue, passthrough_liveness):
    engine = _CountingFaceEngine()
    pipeline = _make_pipeline(engine, passthrough_liveness, offline_queue, post_event_fn=lambda p: True)

    now = 0.0
    for _ in range(600):
        pipeline.process_frame(_flat_frame(), now=now)
        now += 1.0 / 6

    assert engine.detect_calls == 0


def test_a_single_motion_frame_triggers_exactly_one_detector_call(offline_queue, passthrough_liveness):
    engine = _CountingFaceEngine()
    pipeline = _make_pipeline(engine, passthrough_liveness, offline_queue, post_event_fn=lambda p: True)

    now = 0.0
    for _ in range(600):
        pipeline.process_frame(_flat_frame(), now=now)
        now += 1.0 / 6

    assert engine.detect_calls == 0
    pipeline.process_frame(_visitor_frame(), now=now)
    assert engine.detect_calls == 1


# --- full visit flow ----------------------------------------------------------

def test_a_full_visit_buffers_then_sends_exactly_one_event(offline_queue, passthrough_liveness):
    engine = _CountingFaceEngine()
    sent = []
    pipeline = _make_pipeline(engine, passthrough_liveness, offline_queue, post_event_fn=lambda p: sent.append(p) or True)

    now = 0.0
    pipeline.process_frame(_flat_frame(), now=now)  # establish reference, no motion yet
    for _ in range(6):  # visitor appears and holds -- enough frames to fill the bestshot buffer
        now += 0.1
        pipeline.process_frame(_visitor_frame(), now=now)

    assert len(sent) == 1
    assert sent[0]["embedding"] is not None
    assert sent[0]["reject_reason"] is None if "reject_reason" in sent[0] else True
    assert engine.embed_calls == 1  # embedding computed exactly once for the whole visit


def test_repeated_frames_of_the_same_visitor_send_only_one_event(offline_queue, passthrough_liveness):
    """The subject gate must dedupe a person standing still for many frames
    -- the naive per-frame loop must not spam an event per frame."""
    engine = _CountingFaceEngine()
    sent = []
    pipeline = _make_pipeline(engine, passthrough_liveness, offline_queue, post_event_fn=lambda p: sent.append(p) or True)

    now = 0.0
    pipeline.process_frame(_flat_frame(), now=now)  # establish the motion-gate reference frame first
    for _ in range(60):  # 10 seconds at 6fps of the same person standing still
        now += 1.0 / 6
        pipeline.process_frame(_visitor_frame(), now=now)

    assert len(sent) == 1


# --- liveness gate (kiosk-side complement of backend NON-NEGOTIABLE #3) ------

def test_liveness_failure_stops_before_any_embedding_call(offline_queue):
    engine = _CountingFaceEngine()
    liveness = LivenessChecker(model_cache_dir="/tmp/models")
    liveness.inject_for_tests(object())
    liveness.check = lambda frame, box: 0.01  # type: ignore[method-assign]

    sent = []
    pipeline = _make_pipeline(engine, liveness, offline_queue, post_event_fn=lambda p: sent.append(p) or True, liveness_threshold=0.75)

    now = 0.0
    pipeline.process_frame(_flat_frame(), now=now)
    for _ in range(6):
        now += 0.1
        pipeline.process_frame(_visitor_frame(), now=now)

    assert engine.embed_calls == 0  # recognition must never run past a liveness failure
    assert len(sent) == 1
    assert sent[0]["reject_reason"] == "liveness_failed"
    assert sent[0]["embedding"] is None


def test_liveness_disabled_by_config_skips_the_check_entirely(offline_queue, passthrough_liveness):
    engine = _CountingFaceEngine()
    sent = []
    pipeline = _make_pipeline(
        engine, passthrough_liveness, offline_queue, post_event_fn=lambda p: sent.append(p) or True, liveness_enabled=False
    )

    now = 0.0
    pipeline.process_frame(_flat_frame(), now=now)
    for _ in range(6):
        now += 0.1
        pipeline.process_frame(_visitor_frame(), now=now)

    assert len(sent) == 1
    assert sent[0]["liveness_score"] is None


# --- too-small face reject -----------------------------------------------------

def test_a_too_small_face_is_rejected_before_liveness_or_embedding(offline_queue, passthrough_liveness):
    class _TinyFaceEngine(_CountingFaceEngine):
        def detect(self, frame):
            self.detect_calls += 1
            if frame[240, 320, 0] == 40:
                return []
            return [DetectedFace(box=(310.0, 235.0, 330.0, 245.0), kps=np.zeros((5, 2), dtype=np.float32), det_score=0.9)]

    engine = _TinyFaceEngine()
    sent = []
    pipeline = _make_pipeline(engine, passthrough_liveness, offline_queue, post_event_fn=lambda p: sent.append(p) or True, min_face_pixels=80)

    pipeline.process_frame(_flat_frame(), now=0.0)
    pipeline.process_frame(_visitor_frame(), now=0.1)

    assert engine.embed_calls == 0
    assert len(sent) == 1
    assert sent[0]["reject_reason"] == "too_small"


# --- offline queue integration -------------------------------------------------

def test_failed_post_is_queued_offline_not_dropped(offline_queue, passthrough_liveness):
    engine = _CountingFaceEngine()
    pipeline = _make_pipeline(engine, passthrough_liveness, offline_queue, post_event_fn=lambda p: False)

    now = 0.0
    pipeline.process_frame(_flat_frame(), now=now)
    for _ in range(6):
        now += 0.1
        pipeline.process_frame(_visitor_frame(), now=now)

    assert offline_queue.count() == 1


def test_post_transport_exception_is_treated_as_failure_and_queued(offline_queue, passthrough_liveness):
    engine = _CountingFaceEngine()

    def _raises(payload):
        raise ConnectionError("network unreachable")

    pipeline = _make_pipeline(engine, passthrough_liveness, offline_queue, post_event_fn=_raises)

    now = 0.0
    pipeline.process_frame(_flat_frame(), now=now)
    for _ in range(6):
        now += 0.1
        pipeline.process_frame(_visitor_frame(), now=now)

    assert offline_queue.count() == 1


def test_replay_offline_queue_removes_successfully_replayed_events(offline_queue, passthrough_liveness):
    engine = _CountingFaceEngine()
    attempts = {"n": 0}

    def _fails_once_then_succeeds(payload):
        attempts["n"] += 1
        return attempts["n"] > 1

    pipeline = _make_pipeline(engine, passthrough_liveness, offline_queue, post_event_fn=_fails_once_then_succeeds)

    now = 0.0
    pipeline.process_frame(_flat_frame(), now=now)
    for _ in range(6):
        now += 0.1
        pipeline.process_frame(_visitor_frame(), now=now)
    assert offline_queue.count() == 1

    replayed = pipeline.replay_offline_queue()
    assert replayed == 1
    assert offline_queue.count() == 0


def test_replay_offline_queue_leaves_still_failing_events_queued(offline_queue, passthrough_liveness):
    engine = _CountingFaceEngine()
    pipeline = _make_pipeline(engine, passthrough_liveness, offline_queue, post_event_fn=lambda p: False)

    now = 0.0
    pipeline.process_frame(_flat_frame(), now=now)
    for _ in range(6):
        now += 0.1
        pipeline.process_frame(_visitor_frame(), now=now)
    assert offline_queue.count() == 1

    replayed = pipeline.replay_offline_queue()
    assert replayed == 0
    assert offline_queue.count() == 1


def _one_visit(pipeline) -> None:
    now = 0.0
    pipeline.process_frame(_flat_frame(), now=now)
    for _ in range(6):
        now += 0.1
        pipeline.process_frame(_visitor_frame(), now=now)


def test_missing_liveness_model_rejects_faces_when_required(offline_queue):
    """Fail-closed: no anti-spoofing model + liveness_required -> nobody is
    matched (a held-up photo can't mark attendance on a broken install)."""
    engine = _CountingFaceEngine()
    unloaded = LivenessChecker(model_cache_dir="/tmp/models")
    sent: list[dict] = []
    pipeline = _make_pipeline(engine, unloaded, offline_queue, post_event_fn=lambda p: sent.append(p) or True)
    _one_visit(pipeline)
    assert len(sent) == 1
    assert sent[0]["reject_reason"] == "liveness_failed"
    assert sent[0]["liveness_score"] is None
    assert engine.embed_calls == 0


def test_missing_liveness_model_accepts_faces_when_not_required(offline_queue):
    engine = _CountingFaceEngine()
    unloaded = LivenessChecker(model_cache_dir="/tmp/models")
    sent: list[dict] = []
    pipeline = _make_pipeline(
        engine, unloaded, offline_queue, post_event_fn=lambda p: sent.append(p) or True, liveness_required=False
    )
    _one_visit(pipeline)
    assert len(sent) == 1
    assert sent[0].get("reject_reason") is None
    assert sent[0]["embedding"] is not None
