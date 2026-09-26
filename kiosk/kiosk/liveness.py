"""Step 5 -- LIVENESS (MiniFASNet anti-spoofing), behind `liveness_enabled`.

Catches a printed photo or a phone/tablet screen held up to the camera.

Weights: the Silent-Face-Anti-Spoofing MiniFASNet models (Minivision,
Apache-2.0), as ONNX exports published at
github.com/yakhyo/face-anti-spoofing (MIT) -- the same files and SHA-256
digests the `uniface` library pins. Two models are used as an ensemble, like
the upstream reference implementation: MiniFASNetV2 on a 2.7x face crop and
MiniFASNetV1SE on a 4.0x crop; their softmax outputs are averaged.

Fixed 2026-09-26 (liveness never worked before):
  * the old URL pointed at a .onnx that never existed upstream (404), and
    the SHA-256 was a zero placeholder, so every install ran with liveness
    OFF (fail-open) without anyone noticing;
  * preprocessing divided pixels by 255 -- these models expect raw 0..255
    BGR values (upstream's to_tensor doesn't normalise), which would have
    made every score meaningless even with the right weights;
  * the crop scale is now clamped to the frame the way upstream does it.

Offline / air-gapped sites: copy MiniFASNetV2.onnx and MiniFASNetV1SE.onnx
into `{MODEL_CACHE_DIR}/minifasnet/` by hand; a file with the right SHA-256
is used without any download.

If NO model can be loaded, `available` is False and the kiosk reports it in
its heartbeat (dashboard shows "Liveness OFF"). What happens to faces then
is the `liveness_required` setting's call (see kiosk/pipeline.py):
fail-closed (reject) or fail-open (accept, the old behaviour).
"""
from __future__ import annotations

import hashlib
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import structlog

logger = structlog.get_logger(__name__)

_BASE_URL = "https://github.com/yakhyo/face-anti-spoofing/releases/download/weights"


@dataclass(frozen=True)
class ModelSpec:
    filename: str
    sha256: str
    scale: float

    @property
    def url(self) -> str:
        return f"{_BASE_URL}/{self.filename}"


MODELS: tuple[ModelSpec, ...] = (
    ModelSpec("MiniFASNetV2.onnx", "b32929adc2d9c34b9486f8c4c7bc97c1b69bc0ea9befefc380e4faae4e463907", 2.7),
    ModelSpec("MiniFASNetV1SE.onnx", "ebab7f90c7833fbccd46d3a555410e78d969db5438e169b6524be444862b3676", 4.0),
)
INPUT_SIZE = 80
LIVE_CLASS_INDEX = 1  # classes: 0 = print attack, 1 = real, 2 = replay attack


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - np.max(x))
    return e / np.sum(e)


def crop_for_model(frame: np.ndarray, box: tuple[float, float, float, float], scale: float) -> np.ndarray:
    """Face-centred crop `scale` times the box size (clamped so it fits in the
    frame, as upstream does), resized to 80x80, raw BGR float32, NCHW."""
    src_h, src_w = frame.shape[:2]
    x1, y1, x2, y2 = box
    box_w, box_h = max(1.0, x2 - x1), max(1.0, y2 - y1)
    s = min((src_h - 1) / box_h, (src_w - 1) / box_w, scale)
    new_w, new_h = box_w * s, box_h * s
    cx, cy = x1 + box_w / 2, y1 + box_h / 2
    left = max(0, int(cx - new_w / 2))
    top = max(0, int(cy - new_h / 2))
    right = min(src_w - 1, int(cx + new_w / 2))
    bottom = min(src_h - 1, int(cy + new_h / 2))
    patch = frame[top : bottom + 1, left : right + 1]
    if patch.size == 0:
        patch = frame
    resized = cv2.resize(patch, (INPUT_SIZE, INPUT_SIZE))
    arr = resized.astype(np.float32)  # NO /255 -- the models expect 0..255
    return np.transpose(arr, (2, 0, 1))[None, ...]


class LivenessChecker:
    def __init__(self, model_cache_dir: str) -> None:
        self.model_cache_dir = model_cache_dir
        self.available = False
        # (spec, onnxruntime session or a test double)
        self._sessions: list[tuple[ModelSpec, Any]] = []

    @property
    def models_loaded(self) -> int:
        return len(self._sessions)

    def status(self) -> dict[str, Any]:
        """For the kiosk heartbeat -> dashboard health badge."""
        return {"available": self.available, "models": [s.filename for s, _ in self._sessions]}

    def load(self, providers: list[str]) -> None:
        self._sessions = []
        for spec in MODELS:
            try:
                path = self._ensure_weights(spec)
                import onnxruntime as ort

                so = ort.SessionOptions()
                so.log_severity_level = 3
                self._sessions.append((spec, ort.InferenceSession(str(path), sess_options=so, providers=providers)))
                logger.info("liveness_model_loaded", model=spec.filename)
            except Exception as exc:  # noqa: BLE001 - must never crash the kiosk
                logger.warning(
                    "liveness_model_unavailable",
                    model=spec.filename,
                    exception_type=type(exc).__name__,
                    detail=str(exc)[:200],
                )
        self.available = bool(self._sessions)
        if not self.available:
            logger.warning("liveness_unavailable", detail="no anti-spoofing model could be loaded")

    def inject_for_tests(self, session: object, spec: ModelSpec | None = None) -> None:
        self._sessions.append((spec or MODELS[0], session))
        self.available = True

    def _ensure_weights(self, spec: ModelSpec) -> Path:
        cache_dir = Path(self.model_cache_dir) / "minifasnet"
        cache_dir.mkdir(parents=True, exist_ok=True)
        dest = cache_dir / spec.filename
        if dest.exists() and self._sha256(dest) == spec.sha256:
            return dest

        logger.info("liveness_model_downloading", url=spec.url, dest=str(dest))
        tmp = dest.with_suffix(".tmp")
        urllib.request.urlretrieve(spec.url, tmp)  # noqa: S310 - fixed, pinned URL
        digest = self._sha256(tmp)
        if digest != spec.sha256:
            os.remove(tmp)
            raise ValueError(f"checksum mismatch for {spec.filename}: got {digest}")
        os.replace(tmp, dest)
        return dest

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 16), b""):
                h.update(chunk)
        return h.hexdigest()

    def _preprocess(self, frame: np.ndarray, box: tuple[float, float, float, float]) -> np.ndarray:
        return crop_for_model(frame, box, MODELS[0].scale)

    def check(self, frame: np.ndarray, box: tuple[float, float, float, float]) -> float:
        """Probability (0..1) that the face is a real, live person -- the
        ensemble average of every loaded model. Callers must check
        `available` first; with no model this returns 1.0 so it never
        raises (the pipeline decides what "unavailable" means)."""
        if not self._sessions:
            return 1.0
        probs = np.zeros(3, dtype=np.float64)
        for spec, session in self._sessions:
            inp = crop_for_model(frame, box, spec.scale)
            input_name = session.get_inputs()[0].name
            logits = np.asarray(session.run(None, {input_name: inp})[0], dtype=np.float64).reshape(-1)
            probs[: len(logits)] += _softmax(logits)[:3]
        probs /= len(self._sessions)
        return float(probs[LIVE_CLASS_INDEX])
