"""Unit tests for kiosk/liveness.py (spec step 5). Uses an injected fake ONNX
session (`inject_for_tests`) so no network access or real MiniFASNet weights
are required."""
from __future__ import annotations

import numpy as np
import pytest

from kiosk.liveness import LivenessChecker, _softmax


class _FakeInput:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeSession:
    def __init__(self, logits: list[float]) -> None:
        self._logits = np.array(logits, dtype=np.float32).reshape(1, -1)
        self.run_calls: list[dict] = []

    def get_inputs(self):
        return [_FakeInput("input")]

    def run(self, output_names, feed):
        self.run_calls.append(feed)
        return [self._logits]


def _frame() -> np.ndarray:
    return np.full((480, 640, 3), 128, dtype=np.uint8)


def test_softmax_sums_to_one():
    probs = _softmax(np.array([1.0, 2.0, 3.0]))
    assert probs.sum() == pytest.approx(1.0)


def test_softmax_is_numerically_stable_for_large_values():
    probs = _softmax(np.array([1000.0, 1001.0, 1002.0]))
    assert np.isfinite(probs).all()
    assert probs.sum() == pytest.approx(1.0)


def test_check_returns_pass_default_when_unavailable():
    checker = LivenessChecker(model_cache_dir="/tmp/models")  # load() never called
    assert checker.available is False
    score = checker.check(_frame(), (100.0, 100.0, 300.0, 340.0))
    assert score == 1.0


def test_check_reports_high_score_when_live_class_dominates():
    # LIVE_CLASS_INDEX = 1 -- make class 1's logit dominate.
    session = _FakeSession([0.0, 10.0, 0.0])
    checker = LivenessChecker(model_cache_dir="/tmp/models")
    checker.inject_for_tests(session)

    score = checker.check(_frame(), (100.0, 100.0, 300.0, 340.0))
    assert score > 0.99
    assert len(session.run_calls) == 1


def test_check_reports_low_score_when_spoof_class_dominates():
    session = _FakeSession([10.0, 0.0, 0.0])  # class 0 (spoof) dominates
    checker = LivenessChecker(model_cache_dir="/tmp/models")
    checker.inject_for_tests(session)

    score = checker.check(_frame(), (100.0, 100.0, 300.0, 340.0))
    assert score < 0.01


def test_preprocess_output_shape_is_nchw_80x80():
    checker = LivenessChecker(model_cache_dir="/tmp/models")
    arr = checker._preprocess(_frame(), (100.0, 100.0, 300.0, 340.0))
    assert arr.shape == (1, 3, 80, 80)
    assert arr.dtype == np.float32
    # raw 0..255 BGR -- MiniFASNet was trained without /255 normalisation
    assert arr.max() == pytest.approx(128.0)


def test_preprocess_handles_a_box_at_the_frame_edge_without_crashing():
    checker = LivenessChecker(model_cache_dir="/tmp/models")
    frame = _frame()
    arr = checker._preprocess(frame, (0.0, 0.0, 20.0, 20.0))
    assert arr.shape == (1, 3, 80, 80)


def test_load_failure_disables_liveness_without_raising(monkeypatch):
    checker = LivenessChecker(model_cache_dir="/tmp/definitely_missing_dir_xyz")

    def _boom() -> None:
        raise RuntimeError("no network")

    monkeypatch.setattr(checker, "_ensure_weights", _boom)
    checker.load(["CPUExecutionProvider"])  # must not raise
    assert checker.available is False
    assert checker.check(_frame(), (0.0, 0.0, 10.0, 10.0)) == 1.0  # safe default


def test_ensemble_averages_every_loaded_model():
    from kiosk.liveness import MODELS

    checker = LivenessChecker(model_cache_dir="/tmp/models")
    checker.inject_for_tests(_FakeSession([0.0, 10.0, 0.0]), MODELS[0])  # ~1.0 live
    checker.inject_for_tests(_FakeSession([10.0, 0.0, 0.0]), MODELS[1])  # ~0.0 live
    assert checker.check(_frame(), (100.0, 100.0, 300.0, 340.0)) == pytest.approx(0.5, abs=0.01)
    assert checker.status() == {"available": True, "models": [m.filename for m in MODELS]}


def test_each_model_gets_its_own_crop_scale():
    from kiosk.liveness import crop_for_model

    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[200:280, 280:360] = 255  # the "face"
    box = (280.0, 200.0, 360.0, 280.0)
    tight = crop_for_model(frame, box, 2.7)
    wide = crop_for_model(frame, box, 4.0)
    # the wider crop shows more dark background around the bright face
    assert wide.mean() < tight.mean()


def test_real_weights_if_present_score_is_a_probability():
    """Runs only where the pinned ONNX weights are cached (CI / a dev box):
    loads both real models and checks the output is a sane probability."""
    import os

    cache = os.environ.get("LIVENESS_TEST_MODEL_DIR")
    if not cache:
        pytest.skip("set LIVENESS_TEST_MODEL_DIR to a folder containing minifasnet/*.onnx")
    pytest.importorskip("onnxruntime")
    checker = LivenessChecker(model_cache_dir=cache)
    checker.load(["CPUExecutionProvider"])
    assert checker.models_loaded == 2
    rng = np.random.default_rng(0)
    frame = rng.integers(0, 255, (480, 640, 3), dtype=np.uint8)
    score = checker.check(frame, (250.0, 150.0, 390.0, 330.0))
    assert 0.0 <= score <= 1.0


def test_calibration_recommends_midpoint_between_real_and_spoof():
    from kiosk.liveness_check import recommend

    assert recommend({"real": [0.9] * 10, "spoof": [0.1] * 10}) == 0.5
    assert recommend({"real": [0.9]}) is None
