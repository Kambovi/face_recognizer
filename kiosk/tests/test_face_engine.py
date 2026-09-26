"""Unit tests for kiosk/face_engine.py. Uses injected fake detection/
recognition models (via `inject_for_tests`) so no network access or real
buffalo_l weights are required. The fakes mirror real insightface semantics:
`Face.normed_embedding` is a read-only property computed from `Face.embedding`
(see insightface.app.common.Face) -- a recognition model's `.get()` sets
`.embedding`, never `.normed_embedding` directly."""
from __future__ import annotations

import numpy as np
import pytest

from kiosk.face_engine import FaceEngine


class _FakeDetectionModel:
    def __init__(self, boxes: np.ndarray, kpss: np.ndarray | None) -> None:
        self._boxes = boxes
        self._kpss = kpss
        self.calls = 0

    def detect(self, img, **kwargs):
        self.calls += 1
        return self._boxes, self._kpss


class _FakeRecognitionModel:
    def __init__(self, embedding: np.ndarray | None) -> None:
        self._embedding = embedding
        self.calls = 0

    def get(self, img, face_obj):
        self.calls += 1
        if self._embedding is not None:
            face_obj.embedding = self._embedding
        return getattr(face_obj, "embedding", None)


# A fixed provider list is fine in test fixtures (deterministic, no real
# inference happens against it since detection/recognition are injected
# fakes) -- only *production* code paths must always go through
# device.resolve_providers() (see NON-NEGOTIABLE #8's source-scan test).
_TEST_PROVIDERS = ["CPUExecutionProvider"]


def _engine() -> FaceEngine:
    return FaceEngine(model_cache_dir="/tmp/models", model_name="buffalo_l", providers=_TEST_PROVIDERS, det_size=(640, 640))


def test_detect_returns_empty_list_when_engine_unavailable():
    engine = _engine()  # load() never called -> available stays False
    result = engine.detect(np.zeros((480, 640, 3), dtype=np.uint8))
    assert result == []


def test_embed_returns_none_when_engine_unavailable():
    engine = _engine()
    from kiosk.face_engine import DetectedFace

    face = DetectedFace(box=(0, 0, 10, 10), kps=np.zeros((5, 2)), det_score=0.9)
    assert engine.embed(np.zeros((480, 640, 3), dtype=np.uint8), face) is None


def test_detect_parses_boxes_and_scores_from_the_detection_model():
    boxes = np.array([[10.0, 20.0, 110.0, 220.0, 0.93]], dtype=np.float32)
    kpss = np.zeros((1, 5, 2), dtype=np.float32)
    detection = _FakeDetectionModel(boxes, kpss)
    engine = _engine()
    engine.inject_for_tests(detection, _FakeRecognitionModel(None))

    faces = engine.detect(np.zeros((480, 640, 3), dtype=np.uint8))
    assert len(faces) == 1
    assert faces[0].box == (10.0, 20.0, 110.0, 220.0)
    assert faces[0].det_score == pytest.approx(0.93)
    assert detection.calls == 1


def test_detect_with_no_faces_returns_empty_list():
    boxes = np.zeros((0, 5), dtype=np.float32)
    detection = _FakeDetectionModel(boxes, None)
    engine = _engine()
    engine.inject_for_tests(detection, _FakeRecognitionModel(None))

    assert engine.detect(np.zeros((480, 640, 3), dtype=np.uint8)) == []


def test_detect_handles_missing_keypoints_gracefully():
    boxes = np.array([[0.0, 0.0, 50.0, 50.0, 0.8]], dtype=np.float32)
    detection = _FakeDetectionModel(boxes, None)  # kpss=None is valid per SCRFD API
    engine = _engine()
    engine.inject_for_tests(detection, _FakeRecognitionModel(None))

    faces = engine.detect(np.zeros((480, 640, 3), dtype=np.uint8))
    assert len(faces) == 1
    assert faces[0].kps.shape == (5, 2)


def test_embed_reads_normed_embedding_after_recognition_sets_raw_embedding():
    from kiosk.face_engine import DetectedFace

    raw = np.array([3.0, 4.0] + [0.0] * 510, dtype=np.float32)  # norm == 5.0
    recognition = _FakeRecognitionModel(raw)
    engine = _engine()
    engine.inject_for_tests(_FakeDetectionModel(np.zeros((0, 5)), None), recognition)

    face = DetectedFace(box=(0.0, 0.0, 100.0, 100.0), kps=np.zeros((5, 2)), det_score=0.9)
    embedding = engine.embed(np.zeros((480, 640, 3), dtype=np.uint8), face)

    assert embedding is not None
    assert embedding.shape == (512,)
    # normed_embedding = embedding / ||embedding||
    np.testing.assert_allclose(embedding[:2], [0.6, 0.8], atol=1e-5)
    assert recognition.calls == 1


def test_embed_returns_none_if_recognition_model_never_sets_embedding():
    from kiosk.face_engine import DetectedFace

    recognition = _FakeRecognitionModel(None)
    engine = _engine()
    engine.inject_for_tests(_FakeDetectionModel(np.zeros((0, 5)), None), recognition)

    face = DetectedFace(box=(0.0, 0.0, 100.0, 100.0), kps=np.zeros((5, 2)), det_score=0.9)
    assert engine.embed(np.zeros((480, 640, 3), dtype=np.uint8), face) is None


def test_load_failure_degrades_gracefully_never_raises(monkeypatch):
    """No network/weights available (or any other load-time failure) must
    leave the engine usable-but-disabled, never crash the kiosk process."""
    engine = _engine()

    monkeypatch.setitem(__import__("sys").modules, "insightface", None)  # ensure a clean failure path
    # Directly exercise the except-branch contract instead of the import
    # machinery: load() must never propagate any exception.
    class _ExplodingFaceAnalysis:
        def __init__(self, *a, **k):
            raise RuntimeError("simulated model download failure")

    import types

    fake_insightface_app = types.SimpleNamespace(FaceAnalysis=_ExplodingFaceAnalysis)
    fake_insightface = types.SimpleNamespace(app=fake_insightface_app)
    monkeypatch.setitem(__import__("sys").modules, "insightface", fake_insightface)
    monkeypatch.setitem(__import__("sys").modules, "insightface.app", fake_insightface_app)

    engine.load()  # must not raise
    assert engine.available is False
    assert engine.detect(np.zeros((10, 10, 3), dtype=np.uint8)) == []
