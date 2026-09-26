"""Unit tests for kiosk/capture.py."""
from __future__ import annotations

import numpy as np

from kiosk.capture import CameraFrameSource, SyntheticFrameSource, make_frame_source


def test_make_frame_source_synthetic_returns_synthetic_source():
    source = make_frame_source("synthetic")
    assert isinstance(source, SyntheticFrameSource)


def test_make_frame_source_anything_else_returns_camera_source():
    source = make_frame_source("0")
    assert isinstance(source, CameraFrameSource)
    source.release()


def test_synthetic_source_always_returns_a_frame():
    source = SyntheticFrameSource()
    for _ in range(50):
        frame = source.read()
        assert frame is not None
        assert frame.shape == (480, 640, 3)
        assert frame.dtype == np.uint8


def test_synthetic_source_eventually_produces_a_visitor():
    """~6% chance per call -- across enough calls a visitor frame (different
    from the flat background) must appear."""
    source = SyntheticFrameSource()
    background = source._background
    saw_visitor = False
    for _ in range(500):
        frame = source.read()
        if not np.array_equal(frame, background):
            saw_visitor = True
            break
    assert saw_visitor


def test_synthetic_source_holds_the_visitor_steady_across_calls():
    """Best-shot buffering needs several consecutive frames of the *same*
    face, not a new random face every call."""
    import time

    source = SyntheticFrameSource()
    source._visitor_face = source._draw_face()
    source._visitor_until = time.monotonic() + 2.0

    frame1 = source.read()
    frame2 = source.read()
    assert np.array_equal(frame1, frame2)


def test_synthetic_source_release_is_a_noop():
    source = SyntheticFrameSource()
    source.release()  # must not raise
