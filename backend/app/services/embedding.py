"""Enrollment-time face detection + embedding (server-side).

Uses app/device.py (see its module docstring) to resolve ONNX providers,
then loads insightface's combined FaceAnalysis (detection+recognition
together) -- unlike the kiosk, the backend only ever processes a handful of
still enrollment photos per admin action, not a live video stream, so there
is no perf reason to split detection from recognition here the way
kiosk/kiosk/face_engine.py does.

If the real model can't be loaded (no network to fetch buffalo_l -- true in
this sandbox), enrollment falls back to a DETERMINISTIC placeholder
embedding derived from a hash of the image bytes. This is clearly logged and
tagged with a distinct `model_version` so it can never be confused with a
real embedding, and it exists purely so `make seed` / `make smoke` and the
rest of the system (matching, dedupe, unknown clustering, analytics,
dashboard) are fully exercisable end-to-end without real model weights, per
the spec's explicit allowance for mocked model sessions. See
docs/DECISIONS.md.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
import structlog

from app.config import get_settings
from app.services.quality import compute_quality_score

logger = structlog.get_logger(__name__)

EMBEDDING_DIM = 512
MODEL_VERSION = "buffalo_l"
PLACEHOLDER_MODEL_VERSION = "placeholder-hash-v1"

MIN_QUALITY_SCORE = 0.35


@dataclass
class EnrollResult:
    accepted: bool
    reason: str | None
    quality_score: float
    embedding: list[float] | None
    model_version: str
    det_score: float | None = None


class _EngineSingleton:
    _app: Any = None
    _loaded: bool = False
    _available: bool = False

    @classmethod
    def get(cls) -> Any:
        if not cls._loaded:
            cls._load()
        return cls._app if cls._available else None

    @classmethod
    def _load(cls) -> None:
        cls._loaded = True
        try:
            from insightface.app import FaceAnalysis

            from app.device import resolve_providers

            settings = get_settings()
            providers, info = resolve_providers(
                settings.device_preference,
                engine_cache_dir=f"{settings.model_cache_dir}/trt_cache",
            )
            ctx_id = 0 if any(p != "CPUExecutionProvider" for p in providers) else -1
            app = FaceAnalysis(
                name=settings.insightface_model_name,
                root=settings.model_cache_dir,
                providers=providers,
            )
            app.prepare(ctx_id=ctx_id, det_size=tuple(info["tuning"]["det_size"]))
            cls._app = app
            cls._available = True
            logger.info("enrollment_face_engine_loaded", provider=info["provider"])
        except Exception as exc:  # noqa: BLE001 - must never crash enrollment/boot
            logger.warning(
                "enrollment_face_engine_unavailable",
                exception_type=type(exc).__name__,
                detail=str(exc)[:200],
            )
            cls._available = False

    @classmethod
    def reset_for_tests(cls) -> None:
        cls._app = None
        cls._loaded = False
        cls._available = False

    @classmethod
    def inject_for_tests(cls, fake_app: Any) -> None:
        cls._app = fake_app
        cls._loaded = True
        cls._available = True


def _decode_image(image_bytes: bytes) -> np.ndarray | None:
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    return img


def _placeholder_embedding(image_bytes: bytes) -> list[float]:
    values: list[int] = []
    seed = image_bytes
    while len(values) < EMBEDDING_DIM:
        seed = hashlib.sha256(seed).digest()
        values.extend(seed)
    arr = np.array(values[:EMBEDDING_DIM], dtype=np.float64)
    arr = (arr - 127.5) / 127.5
    norm = np.linalg.norm(arr) or 1.0
    return (arr / norm).tolist()


def process_enrollment_image(image_bytes: bytes, min_face_pixels: int) -> EnrollResult:
    app = _EngineSingleton.get()

    if app is None:
        logger.warning("enrollment_using_placeholder_embedding")
        embedding = _placeholder_embedding(image_bytes)
        return EnrollResult(
            accepted=True,
            reason=None,
            quality_score=0.5,
            embedding=embedding,
            model_version=PLACEHOLDER_MODEL_VERSION,
        )

    img = _decode_image(image_bytes)
    if img is None:
        return EnrollResult(False, "invalid_image", 0.0, None, MODEL_VERSION)

    faces = app.get(img)
    if not faces:
        return EnrollResult(False, "no_face_detected", 0.0, None, MODEL_VERSION)
    if len(faces) > 1:
        return EnrollResult(False, "multiple_faces_detected", 0.0, None, MODEL_VERSION)

    face = faces[0]
    box: tuple[float, float, float, float] = (
        float(face.bbox[0]),
        float(face.bbox[1]),
        float(face.bbox[2]),
        float(face.bbox[3]),
    )
    height = box[3] - box[1]
    if height < min_face_pixels:
        return EnrollResult(False, "face_too_small", 0.0, None, MODEL_VERSION, det_score=float(face.det_score))

    quality = compute_quality_score(img, box, getattr(face, "kps", None), float(face.det_score))
    if quality < MIN_QUALITY_SCORE:
        return EnrollResult(False, "low_quality", quality, None, MODEL_VERSION, det_score=float(face.det_score))

    embedding = np.asarray(face.normed_embedding, dtype=np.float32).tolist()
    return EnrollResult(True, None, quality, embedding, MODEL_VERSION, det_score=float(face.det_score))
