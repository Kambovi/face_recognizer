"""Unit tests for kiosk/motion_gate.py (spec step 1a: the cheap keyframe
gate). The end-to-end "idle costs zero detector calls" assertion
(NON-NEGOTIABLE #6) lives in test_pipeline.py, where a real detector call
count is observable; these tests cover the gate's own state machine."""
from __future__ import annotations

import numpy as np

from kiosk.motion_gate import KioskState, MotionGate, MotionGateConfig


def _flat_frame(value: int = 40, h: int = 480, w: int = 640) -> np.ndarray:
    return np.full((h, w, 3), value, dtype=np.uint8)


def _frame_with_bright_block(h: int = 480, w: int = 640) -> np.ndarray:
    frame = _flat_frame(h=h, w=w)
    frame[100:300, 100:300] = 220
    return frame


def test_first_frame_establishes_reference_and_reports_no_motion():
    gate = MotionGate()
    result = gate.process(_flat_frame(), now=0.0)
    assert result.motion_detected is False


def test_identical_subsequent_frames_report_no_motion():
    gate = MotionGate()
    gate.process(_flat_frame(), now=0.0)
    result = gate.process(_flat_frame(), now=1.0)
    assert result.motion_detected is False
    assert result.changed_ratio == 0.0


def test_a_large_change_is_detected_as_motion():
    gate = MotionGate()
    gate.process(_flat_frame(), now=0.0)
    result = gate.process(_frame_with_bright_block(), now=1.0)
    assert result.motion_detected is True
    assert result.changed_ratio > 0.0


def test_state_transitions_to_idle_after_enough_static_frames():
    config = MotionGateConfig(idle_frames_before_sleep=3)
    gate = MotionGate(config=config, full_fps=6)
    gate.process(_flat_frame(), now=0.0)  # establishes reference
    assert gate.state is KioskState.ACTIVE

    for i in range(1, 4):
        gate.process(_flat_frame(), now=float(i))
    assert gate.state is KioskState.IDLE
    assert gate.effective_fps == config.idle_fps


def test_motion_wakes_the_gate_back_to_active():
    config = MotionGateConfig(idle_frames_before_sleep=2)
    gate = MotionGate(config=config, full_fps=6)
    gate.process(_flat_frame(), now=0.0)
    gate.process(_flat_frame(), now=1.0)
    gate.process(_flat_frame(), now=2.0)
    assert gate.state is KioskState.IDLE

    result = gate.process(_frame_with_bright_block(), now=3.0)
    assert result.motion_detected is True
    assert gate.state is KioskState.ACTIVE
    assert gate.effective_fps == gate.full_fps


def test_effective_fps_matches_state():
    config = MotionGateConfig(idle_fps=1)
    gate = MotionGate(config=config, full_fps=6)
    assert gate.effective_fps == 6  # starts ACTIVE
    gate.state = KioskState.IDLE
    assert gate.effective_fps == 1


def test_reference_frame_refreshes_on_a_timer_while_static():
    """Slow lighting drift must not accumulate into a false motion trigger
    against a frame frozen forever -- the reference updates periodically
    while nothing is moving."""
    config = MotionGateConfig(reference_refresh_seconds=5.0)
    gate = MotionGate(config=config)
    gate.process(_flat_frame(value=40), now=0.0)

    # Slight, gradual brightening below the motion threshold each step.
    gate.process(_flat_frame(value=45), now=1.0)
    gate.process(_flat_frame(value=50), now=6.0)  # past the refresh timer

    assert gate._reference is not None
    # After refresh, comparing the *same* (value=50) frame again reports no
    # motion, proving the reference actually moved forward.
    result = gate.process(_flat_frame(value=50), now=6.5)
    assert result.motion_detected is False


def test_reference_does_not_refresh_while_motion_is_ongoing():
    """A continuously-present person must never 'become' the new static
    reference -- refresh only happens on frames classified as non-motion."""
    config = MotionGateConfig(reference_refresh_seconds=0.001)
    gate = MotionGate(config=config)
    gate.process(_flat_frame(), now=0.0)

    busy = _frame_with_bright_block()
    gate.process(busy, now=1.0)
    ref_after_motion = gate._reference.copy()

    # If the reference had been replaced with `busy`, comparing `busy` again
    # would now report no motion. It must still report motion.
    result = gate.process(busy, now=2.0)
    assert result.motion_detected is True
    assert np.array_equal(ref_after_motion, gate._reference)
