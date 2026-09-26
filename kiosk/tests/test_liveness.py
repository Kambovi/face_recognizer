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
    assert arr.min() >= 0.0 and arr.max() <= 1.0


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
