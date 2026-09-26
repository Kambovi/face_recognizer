"""Detection (SCRFD) + recognition (ArcFace) wrapper around insightface's
`buffalo_l` pack.

Detection and recognition are invoked as SEPARATE model calls (via
`FaceAnalysis.models['detection']` / `['recognition']`) rather than the
combined, convenience `FaceAnalysis.get()` -- that is what lets step 4
(best-shot buffering) run detection on every gated frame while paying the
ArcFace embedding cost exactly once, on the winning crop (step 6). See
docs/DECISIONS.md.

Model weights are NOT bundled. `insightface.FaceAnalysis(..., root=...)`
auto-downloads `buffalo_l` into `model_cache_dir` on first use if it isn't
already there. If that download fails (no network, e.g. this sandbox) or the
insightface/onnxruntime import itself fails, `FaceEngine.load()` catches
everything, logs one clear WARNING, and leaves the engine in a disabled
state -- `detect()`/`embed()` then return empty results rather than raising,
so the kiosk process still boots and still serves /health. Every unit test
for this module injects a fake `detection`/`recognition` model pair instead
of touching the network (see kiosk/tests/test_face_engine.py).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np
import structlog

logger = structlog.get_logger(__name__)

MODEL_VERSION = "buffalo_l"


@dataclass
class DetectedFace:
    box: tuple[float, float, float, float]
    kps: np.ndarray
    det_score: float


class _DetectionModel(Protocol):  # pragma: no cover - structural typing only
    def detect(self, img: np.ndarray, **kwargs: Any) -> tuple[np.ndarray, np.ndarray]: ...


class _RecognitionModel(Protocol):  # pragma: no cover
    def get(self, img: np.ndarray, face: Any) -> np.ndarray: ...


class FaceEngine:
    def __init__(self, model_cache_dir: str, model_name: str, providers: list[str], det_size: tuple[int, int]) -> None:
        self.model_cache_dir = model_cache_dir
        self.model_name = model_name
        self.providers = providers
        self.det_size = det_size
        self.available = False
        self._detection: _DetectionModel | None = None
        self._recognition: _RecognitionModel | None = None

    def load(self) -> None:
        try:
            from insightface.app import FaceAnalysis

            ctx_id = 0 if any(p != "CPUExecutionProvider" for p in self.providers) else -1
            app = FaceAnalysis(
                name=self.model_name,
                root=self.model_cache_dir,
                providers=self.providers,
                allowed_modules=["detection", "recognition"],
            )
            app.prepare(ctx_id=ctx_id, det_size=self.det_size)
            self._detection = app.models["detection"]
            self._recognition = app.models["recognition"]
            self.available = True
            logger.info("face_engine_loaded", model=self.model_name, providers=self.providers)
        except Exception as exc:  # noqa: BLE001 - weights/network unavailable must never crash the kiosk
            logger.warning(
                "face_engine_unavailable",
                exception_type=type(exc).__name__,
                detail=str(exc)[:200],
            )
            self.available = False

    def inject_for_tests(self, detection: _DetectionModel, recognition: _RecognitionModel) -> None:
        """Test-only hook to bypass `load()` entirely with fakes."""
        self._detection = detection
        self._recognition = recognition
        self.available = True

    def detect(self, frame: np.ndarray) -> list[DetectedFace]:
        if not self.available or self._detection is None:
            return []
        bboxes, kpss = self._detection.detect(frame, input_size=self.det_size, max_num=0)
        faces: list[DetectedFace] = []
        for i in range(bboxes.shape[0]):
            x1, y1, x2, y2, score = bboxes[i]
            kps = kpss[i] if kpss is not None else np.zeros((5, 2), dtype=np.float32)
            faces.append(DetectedFace(box=(float(x1), float(y1), float(x2), float(y2)), kps=kps, det_score=float(score)))
        return faces

    def embed(self, frame: np.ndarray, face: DetectedFace) -> np.ndarray | None:
        if not self.available or self._recognition is None:
            return None
        from insightface.app.common import Face

        face_obj = Face(bbox=np.array(face.box, dtype=np.float32), kps=face.kps, det_score=face.det_score)
        self._recognition.get(frame, face_obj)
        embedding = getattr(face_obj, "normed_embedding", None)
        if embedding is None:
            return None
        return np.asarray(embedding, dtype=np.float32)
