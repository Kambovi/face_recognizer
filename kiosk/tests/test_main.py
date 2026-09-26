"""Unit tests for kiosk/main.py's settings-merge logic -- the part of the
process entrypoint that can be tested without booting the live capture loop
(NON-NEGOTIABLE #1: thresholds always come from the backend, defaults are
only a boot-time fallback)."""
from __future__ import annotations

from kiosk.main import _DEFAULT_SETTINGS, _parse_det_size, build_pipeline_config


def test_parse_det_size_valid_csv_string():
    assert _parse_det_size("320,320") == (320, 320)


def test_parse_det_size_with_whitespace():
    assert _parse_det_size(" 640 , 480 ") == (640, 480)


def test_parse_det_size_list_input():
    assert _parse_det_size([320, 240]) == (320, 240)


def test_parse_det_size_garbage_falls_back_to_default():
    assert _parse_det_size("not-a-size") == (640, 640)
    assert _parse_det_size(None) == (640, 640)
    assert _parse_det_size(12345) == (640, 640)


def test_build_pipeline_config_uses_defaults_when_settings_empty():
    config = build_pipeline_config("kiosk-01", {})
    assert config.kiosk_id == "kiosk-01"
    assert config.min_face_pixels == _DEFAULT_SETTINGS["min_face_pixels"]
    assert config.liveness_enabled == _DEFAULT_SETTINGS["liveness_enabled"]
    assert config.capture_fps == _DEFAULT_SETTINGS["capture_fps"]
    assert config.motion_gate_config is not None
    assert config.subject_gate_config is not None


def test_build_pipeline_config_overrides_from_remote_settings():
    remote = {
        "min_face_pixels": 120,
        "liveness_enabled": False,
        "liveness_threshold": 0.6,
        "bestshot_frames": 10,
        "capture_fps": 15,
        "motion_pixel_threshold": 40,
        "iou_same_subject": 0.7,
        "same_person_threshold": 0.95,
    }
    config = build_pipeline_config("kiosk-01", remote)

    assert config.min_face_pixels == 120
    assert config.liveness_enabled is False
    assert config.liveness_threshold == 0.6
    assert config.bestshot_frames == 10
    assert config.capture_fps == 15
    assert config.motion_gate_config.motion_pixel_threshold == 40
    assert config.subject_gate_config.iou_same_subject == 0.7
    assert config.subject_gate_config.same_person_threshold == 0.95


def test_build_pipeline_config_ignores_unknown_keys():
    remote = {"some_future_setting_not_yet_known": 123, "capture_fps": 12}
    config = build_pipeline_config("kiosk-01", remote)
    assert config.capture_fps == 12  # known keys still applied
    assert not hasattr(config, "some_future_setting_not_yet_known")


def test_build_pipeline_config_partial_settings_fill_gaps_with_defaults():
    remote = {"capture_fps": 20}
    config = build_pipeline_config("kiosk-01", remote)
    assert config.capture_fps == 20
    assert config.min_face_pixels == _DEFAULT_SETTINGS["min_face_pixels"]
