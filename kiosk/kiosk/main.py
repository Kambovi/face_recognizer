"""Kiosk process entrypoint.

Wires frame capture -> `RecognitionPipeline` -> the backend API together into
a single-threaded loop, and drives the three background timers around it:
periodic settings refresh (NON-NEGOTIABLE #1 -- thresholds always come from
the backend's runtime `settings` table, never hardcoded here), device-status
heartbeat, and offline-queue replay (NON-NEGOTIABLE #5).

Run as `python -m kiosk.main` (see kiosk/Dockerfile's CMD). This module is
intentionally thin: every piece of actual logic lives in a unit-tested
module (device.py, capture.py, pipeline.py, ...) and is just assembled here.
"""
from __future__ import annotations

import signal
import time
from types import FrameType
from typing import Any

import structlog

from kiosk import device
from kiosk.api_client import ApiClient
from kiosk.capture import make_frame_source
from kiosk.config import KioskConfig, get_kiosk_config
from kiosk.face_engine import FaceEngine
from kiosk.liveness import LivenessChecker
from kiosk.motion_gate import MotionGateConfig
from kiosk.offline_queue import OfflineQueue
from kiosk.pipeline import PipelineConfig, RecognitionPipeline
from kiosk.quality import QualityConfig
from kiosk.subject_gate import SubjectGateConfig

logger = structlog.get_logger(__name__)

# Fallback values used only until the first successful `GET /kiosk/config`
# call -- mirrors backend/app/services/settings_service.py's DEFAULT_SETTINGS
# for the keys this process actually consumes. If the backend is reachable
# at boot these are immediately overwritten by the real settings row.
_DEFAULT_SETTINGS: dict[str, Any] = {
    "min_face_pixels": 80,
    "liveness_enabled": True,
    "liveness_threshold": 0.5,  # calibrate per camera: python -m kiosk.liveness_check
    "liveness_required": True,
    "bestshot_frames": 5,
    "capture_fps": 6,
    "motion_pixel_threshold": 25,
    "motion_area_threshold": 0.02,
    "idle_frames_before_sleep": 60,
    "idle_fps": 1,
    "reference_refresh_seconds": 30,
    "iou_same_subject": 0.85,
    "dedupe_window_minutes": 5,
    "same_person_threshold": 0.55,
    "recent_embedding_buffer": 5,
    "det_size": "640,640",
    "quality_gate_enabled": True,
    "quality_min_det_score": 0.60,
    "quality_min_frontality": 0.50,
    "quality_min_pitch_ratio": 0.28,
    "quality_max_pitch_ratio": 0.75,
    "quality_min_brightness": 40.0,
    "quality_min_sharpness": 20.0,
    "quality_min_score": 0.50,
}


def _parse_det_size(value: Any) -> tuple[int, int]:
    if isinstance(value, str):
        try:
            w, h = (int(p.strip()) for p in value.split(","))
            return (w, h)
        except (ValueError, TypeError):
            pass
    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            return (int(value[0]), int(value[1]))
        except (ValueError, TypeError):
            pass
    return (640, 640)


def build_pipeline_config(kiosk_id: str, settings: dict[str, Any]) -> PipelineConfig:
    """Merge a `GET /kiosk/config`-shaped settings dict (falling back to
    `_DEFAULT_SETTINGS` for anything missing/unreachable) into the dataclasses
    the pipeline and its gates actually consume. Split out as a standalone
    function so kiosk/tests can exercise the merge logic without booting the
    whole process."""
    merged = dict(_DEFAULT_SETTINGS)
    merged.update({k: v for k, v in settings.items() if k in _DEFAULT_SETTINGS})

    motion_cfg = MotionGateConfig(
        motion_pixel_threshold=int(merged["motion_pixel_threshold"]),
        motion_area_threshold=float(merged["motion_area_threshold"]),
        idle_frames_before_sleep=int(merged["idle_frames_before_sleep"]),
        idle_fps=int(merged["idle_fps"]),
        reference_refresh_seconds=float(merged["reference_refresh_seconds"]),
    )
    subject_cfg = SubjectGateConfig(
        iou_same_subject=float(merged["iou_same_subject"]),
        dedupe_window_minutes=float(merged["dedupe_window_minutes"]),
        same_person_threshold=float(merged["same_person_threshold"]),
        recent_embedding_buffer=int(merged["recent_embedding_buffer"]),
    )
    quality_cfg = QualityConfig(
        enabled=bool(merged["quality_gate_enabled"]),
        min_det_score=float(merged["quality_min_det_score"]),
        min_frontality=float(merged["quality_min_frontality"]),
        min_pitch_ratio=float(merged["quality_min_pitch_ratio"]),
        max_pitch_ratio=float(merged["quality_max_pitch_ratio"]),
        min_brightness=float(merged["quality_min_brightness"]),
        min_sharpness=float(merged["quality_min_sharpness"]),
        min_score=float(merged["quality_min_score"]),
    )
    return PipelineConfig(
        kiosk_id=kiosk_id,
        min_face_pixels=int(merged["min_face_pixels"]),
        liveness_enabled=bool(merged["liveness_enabled"]),
        liveness_threshold=float(merged["liveness_threshold"]),
        liveness_required=bool(merged["liveness_required"]),
        bestshot_frames=int(merged["bestshot_frames"]),
        capture_fps=int(merged["capture_fps"]),
        motion_gate_config=motion_cfg,
        subject_gate_config=subject_cfg,
        quality_config=quality_cfg,
    )


class _Shutdown:
    """SIGINT/SIGTERM latch -- lets the main loop drain the current frame and
    exit cleanly (releasing the camera, closing the HTTP client) instead of
    dying mid-iteration."""

    def __init__(self) -> None:
        self.requested = False

    def handle(self, signum: int, _frame: FrameType | None) -> None:
        logger.info("kiosk_shutdown_requested", signum=signum)
        self.requested = True


def run(config: KioskConfig | None = None) -> None:  # pragma: no cover - exercised via integration/manual run, not unit tests
    config = config or get_kiosk_config()
    shutdown = _Shutdown()
    signal.signal(signal.SIGINT, shutdown.handle)
    signal.signal(signal.SIGTERM, shutdown.handle)

    # Resolve the ONNX Runtime provider exactly once for this process (see
    # kiosk/device.py's module docstring) and reuse it for every model
    # session below -- detector, recognizer, and liveness all share it.
    providers, device_info = device.resolve_providers(device_preference=config.device_preference)
    logger.info("kiosk_starting", kiosk_id=config.kiosk_id, device=device_info)

    det_size = _parse_det_size(device_info.get("det_size", "640,640"))
    face_engine = FaceEngine(
        model_cache_dir=config.model_cache_dir,
        model_name=config.insightface_model_name,
        providers=providers,
        det_size=det_size,
    )
    face_engine.load()

    liveness_checker = LivenessChecker(model_cache_dir=config.model_cache_dir)
    liveness_checker.load(providers)

    offline_queue = OfflineQueue(config.offline_queue_path)
    api_client = ApiClient(config.api_base_url, config.kiosk_service_token)

    # `GET /kiosk/config` responds `{"settings": {...}}` (KioskConfigResponse)
    # -- unwrap once here so build_pipeline_config always sees a flat dict.
    initial_settings = (api_client.get_settings() or {}).get("settings", {})
    pipeline_config = build_pipeline_config(config.kiosk_id, initial_settings)

    pipeline = RecognitionPipeline(
        config=pipeline_config,
        face_engine=face_engine,
        liveness_checker=liveness_checker,
        offline_queue=offline_queue,
        post_event_fn=api_client.post_event,
    )

    frame_source = make_frame_source(config.camera_source)

    last_settings_refresh = time.monotonic()
    last_heartbeat = time.monotonic()
    last_replay = time.monotonic()

    logger.info("kiosk_ready", camera_source=config.camera_source, providers=providers)

    try:
        while not shutdown.requested:
            loop_start = time.monotonic()

            frame = frame_source.read()
            if frame is not None:
                pipeline.process_frame(frame)

            now = time.monotonic()

            if now - last_settings_refresh >= config.settings_refresh_seconds:
                remote = api_client.get_settings()
                if remote is not None:
                    new_config = build_pipeline_config(config.kiosk_id, remote.get("settings", {}))
                    pipeline.config = new_config
                    pipeline.bestshot_buffer.max_frames = new_config.bestshot_frames
                    # Update the already-running gates' thresholds in place
                    # rather than replacing them outright, so a settings
                    # change takes effect immediately without losing gate
                    # state (rolling reference frame, active tracks, ring
                    # buffer) -- NON-NEGOTIABLE #1 applies live, not just at
                    # boot.
                    pipeline.motion_gate.config = new_config.motion_gate_config or pipeline.motion_gate.config
                    pipeline.motion_gate.full_fps = new_config.capture_fps
                    pipeline.subject_gate.config = new_config.subject_gate_config or pipeline.subject_gate.config
                last_settings_refresh = now

            if now - last_heartbeat >= config.heartbeat_seconds:
                api_client.post_heartbeat(config.kiosk_id, {**device_info, "liveness": liveness_checker.status()})
                last_heartbeat = now

            if now - last_replay >= config.heartbeat_seconds:
                replayed = pipeline.replay_offline_queue()
                if replayed:
                    logger.info("offline_queue_replayed", count=replayed)
                last_replay = now

            sleep_for = max(0.0, (1.0 / pipeline.motion_gate.effective_fps) - (time.monotonic() - loop_start))
            time.sleep(sleep_for)
    finally:
        frame_source.release()
        api_client.close()
        logger.info("kiosk_stopped")


if __name__ == "__main__":  # pragma: no cover
    run()
