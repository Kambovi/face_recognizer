"""Orchestrates the kiosk-side half of the recognition pipeline (spec steps
1-6, plus the 1b subject gate that spans them): motion gate -> detect ->
subject gate (pre-embedding) -> size reject -> best-shot buffering ->
liveness -> embed -> subject gate (post-embedding) -> emit an event (posted
to the backend, or queued offline). Steps 7-11 run server-side (see
backend/app/services/recognition.py).
"""
from __future__ import annotations

import base64
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import cv2
import numpy as np
import structlog

from kiosk.bestshot import BestShotBuffer, Candidate, crop_box, score_candidate
from kiosk.face_engine import DetectedFace, FaceEngine
from kiosk.liveness import LivenessChecker
from kiosk.motion_gate import MotionGate, MotionGateConfig
from kiosk.offline_queue import OfflineQueue
from kiosk.quality import QualityConfig, assess
from kiosk.subject_gate import SubjectGate, SubjectGateConfig

logger = structlog.get_logger(__name__)


@dataclass
class PipelineConfig:
    kiosk_id: str
    min_face_pixels: int = 80
    liveness_enabled: bool = True
    liveness_threshold: float = 0.5
    # When liveness is enabled but no anti-spoofing model could be loaded:
    # True -> reject every face (fail-closed; a photo can never mark
    # attendance, and the install problem is loud), False -> accept
    # (fail-open, the pre-2026-09-26 behaviour).
    liveness_required: bool = True
    bestshot_frames: int = 5
    bestshot_window_seconds: float = 1.5
    capture_fps: int = 6
    # Runtime-tunable gate configs (NON-NEGOTIABLE #1: never hardcoded --
    # `main.py` builds these from the backend's `settings` table). Left as
    # None here so existing callers/tests that don't care about gate tuning
    # keep working with MotionGate/SubjectGate's own defaults.
    motion_gate_config: MotionGateConfig | None = None
    subject_gate_config: SubjectGateConfig | None = None
    # Face quality gate (kiosk/quality.py). None -> QualityConfig() defaults.
    quality_config: QualityConfig | None = None


@dataclass
class PipelineResult:
    action: str  # "idle" | "no_face" | "buffering" | "sent" | "queued" | "gated"
    reason: str | None = None


def _encode_crop_base64(frame: np.ndarray, box: tuple[float, float, float, float]) -> str:
    crop = crop_box(frame, box)
    resized = cv2.resize(crop, (224, 224))
    ok, buf = cv2.imencode(".jpg", resized, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        return ""
    return base64.b64encode(buf.tobytes()).decode("ascii")


class RecognitionPipeline:
    def __init__(
        self,
        config: PipelineConfig,
        face_engine: FaceEngine,
        liveness_checker: LivenessChecker,
        offline_queue: OfflineQueue,
        post_event_fn: Any,  # Callable[[dict], bool] -- True on success
    ) -> None:
        self.config = config
        self.face_engine = face_engine
        self.liveness_checker = liveness_checker
        self.offline_queue = offline_queue
        self.post_event_fn = post_event_fn

        self.motion_gate = MotionGate(config=config.motion_gate_config, full_fps=config.capture_fps)
        self.subject_gate = SubjectGate(config=config.subject_gate_config)
        self.bestshot_buffer = BestShotBuffer(
            max_frames=config.bestshot_frames, window_seconds=config.bestshot_window_seconds
        )
        self._active_track_id: str | None = None

    # -- helpers --------------------------------------------------------------

    def _emit(self, payload: dict[str, Any]) -> str:
        client_event_id = payload["client_event_id"]
        ok = False
        try:
            ok = self.post_event_fn(payload)
        except Exception:  # noqa: BLE001 - any transport failure means "queue it"
            ok = False
        if not ok:
            self.offline_queue.enqueue(client_event_id, payload)
            return "queued"
        return "sent"

    def _base_payload(self, occurred_at: datetime) -> dict[str, Any]:
        return {
            "client_event_id": str(uuid.uuid4()),
            "kiosk_id": self.config.kiosk_id,
            "occurred_at": occurred_at.isoformat(),
        }

    # -- main entrypoint -------------------------------------------------------

    def process_frame(self, frame: np.ndarray, now: float | None = None) -> PipelineResult:
        now = time.monotonic() if now is None else now
        occurred_at = datetime.now(timezone.utc)

        motion_result = self.motion_gate.process(frame, now=now)
        if not motion_result.motion_detected and not self.bestshot_buffer.has_pending():
            # No motion and nothing already buffered from a prior active
            # frame -- the cheap gate wins, the detector is never called.
            return PipelineResult(action="idle")

        faces = self.face_engine.detect(frame)
        if not faces:
            self.bestshot_buffer.reset()
            return PipelineResult(action="no_face")

        # Kiosk expects one visitor at a time: take the largest detected face.
        face = max(faces, key=lambda f: (f.box[2] - f.box[0]) * (f.box[3] - f.box[1]))

        gate_decision = self.subject_gate.check_pre_embedding(face.box, now=now)
        if not gate_decision.process:
            return PipelineResult(action="gated", reason=gate_decision.reason)
        self._active_track_id = gate_decision.track_id

        height = face.box[3] - face.box[1]
        if height < self.config.min_face_pixels:
            payload = self._base_payload(occurred_at)
            payload.update(
                {
                    "embedding": None,
                    "liveness_score": None,
                    "reject_reason": "too_small",
                    "crop_jpeg_base64": None,
                }
            )
            self.subject_gate.record_processed(face.box, embedding=None, track_id=gate_decision.track_id, now=now)
            self.bestshot_buffer.reset()
            action = self._emit(payload)
            return PipelineResult(action=action, reason="too_small")

        # .copy(): some capture backends hand back a reused buffer, and the
        # candidate's landmarks must stay paired with the exact pixels they
        # were detected on.
        self.bestshot_buffer.add(Candidate(frame=frame.copy(), box=face.box, kps=face.kps, det_score=face.det_score, track_id=gate_decision.track_id), now=now)
        if not self.bestshot_buffer.ready(now):
            return PipelineResult(action="buffering")

        candidates = self.bestshot_buffer.candidates()
        self.bestshot_buffer.reset()
        if not candidates:
            return PipelineResult(action="no_face")

        # Quality gate: only frames good enough to give a reliable embedding
        # are allowed through. Nothing passes -> send nothing; the person is
        # still in front of the camera, so the next buffer gets another try.
        quality_cfg = self.config.quality_config or QualityConfig()
        assessed = [(c, assess(c.frame, c.box, c.kps, c.det_score, quality_cfg)) for c in candidates]
        passing = [(c, q) for c, q in assessed if q.ok]
        if not passing:
            reasons = [q.reason for _, q in assessed if q.reason]
            top_reason = max(set(reasons), key=reasons.count) if reasons else "low_quality"
            logger.debug("quality_gate_rejected", reason=top_reason, candidates=len(candidates))
            return PipelineResult(action="gated", reason=f"low_quality:{top_reason}")
        best, best_quality = max(passing, key=lambda cq: score_candidate(cq[0]) * cq[1].score)

        best_face = DetectedFace(box=best.box, kps=best.kps, det_score=best.det_score)

        liveness_score: float | None = None
        if self.config.liveness_enabled and (self.liveness_checker.available or self.config.liveness_required):
            if self.liveness_checker.available:
                liveness_score = self.liveness_checker.check(best.frame, best.box)
                failed = liveness_score < self.config.liveness_threshold
            else:  # model missing + fail-closed
                failed = True
            if failed:
                payload = self._base_payload(occurred_at)
                payload.update(
                    {
                        "embedding": None,
                        "liveness_score": liveness_score,
                        "reject_reason": "liveness_failed",
                        "crop_jpeg_base64": _encode_crop_base64(best.frame, best.box),
                    }
                )
                # Recognition (embedding + matching) MUST NOT run past this
                # point -- NON-NEGOTIABLE #3.
                self.subject_gate.record_processed(best.box, embedding=None, track_id=self._active_track_id, now=now)
                action = self._emit(payload)
                return PipelineResult(action=action, reason="liveness_failed")

        embedding = self.face_engine.embed(best.frame, best_face)
        if embedding is None:
            return PipelineResult(action="no_face", reason="embedding_unavailable")

        embedding_gate = self.subject_gate.check_embedding(embedding, now=now)
        if not embedding_gate.process:
            return PipelineResult(action="gated", reason=embedding_gate.reason)

        quality_score = float(min(1.0, best_quality.score if quality_cfg.enabled else best.det_score))
        payload = self._base_payload(occurred_at)
        payload.update(
            {
                "embedding": embedding.tolist(),
                "quality_score": quality_score,
                "liveness_score": liveness_score,
                "crop_jpeg_base64": _encode_crop_base64(best.frame, best.box),
                "box": list(best.box),
            }
        )
        self.subject_gate.record_processed(best.box, embedding=embedding, track_id=self._active_track_id, now=now)
        action = self._emit(payload)
        return PipelineResult(action=action)

    def replay_offline_queue(self) -> int:
        replayed = 0
        for client_event_id, payload in self.offline_queue.pending():
            self.offline_queue.mark_attempt(client_event_id)
            try:
                ok = self.post_event_fn(payload)
            except Exception:  # noqa: BLE001
                ok = False
            if ok:
                self.offline_queue.remove(client_event_id)
                replayed += 1
        return replayed
