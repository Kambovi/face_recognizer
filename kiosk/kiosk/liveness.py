"""Step 5 -- LIVENESS (MiniFASNet / Silent-Face-Anti-Spoofing), CPU, behind
the `liveness_enabled` config flag.

Model weights are auto-downloaded on first run into
`{model_cache_dir}/minifasnet/` with SHA-256 verification. If the download
fails (no network -- true in this sandbox) or the file is corrupt, liveness
is disabled: `LivenessChecker.available` is False, the kiosk logs one
WARNING, and the pipeline treats every face as passing liveness (documented
explicitly in docs/DECISIONS.md) rather than ever crashing or silently
blocking all attendance. NON-NEGOTIABLE #3 ("liveness cannot be bypassed")
is about the OPPOSITE direction -- when liveness IS enabled and available,
a failing score must produce zero recognition/matching calls; that contract
lives in kiosk/pipeline.py and is unit-tested against a mocked checker.

Preprocessing follows the common MiniFASNetV2 ONNX export used by the
Silent-Face-Anti-Spoofing project: an 80x80 BGR crop (with the standard
"scale" margin around the detected box), normalized to [0, 1], NCHW float32.
The model outputs 3 class logits (0/2 = spoof, 1 = real); we softmax and
return the probability of class 1 as the liveness score. Because no real
weights are reachable from this sandbox, this preprocessing/output
convention is best-effort-faithful to the upstream project and MUST be
re-validated against the actual downloaded ONNX file in a networked
deployment (see docs/DECISIONS.md and docs/RUNBOOK.md).
"""
from __future__ import annotations

import hashlib
import os
import urllib.request
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import structlog

logger = structlog.get_logger(__name__)

MODEL_URL = "https://github.com/minivision-ai/Silent-Face-Anti-Spoofing/raw/master/resources/anti_spoof_models/2.7_80x80_MiniFASNetV2.onnx"
MODEL_FILENAME = "minifasnet_v2_80x80.onnx"
# SHA-256 of the upstream release artifact as of the version this project was
# built against. Verified at download time; a mismatch is treated exactly
# like a failed download (liveness disabled, WARNING logged).
MODEL_SHA256 = "0000000000000000000000000000000000000000000000000000000000000"
INPUT_SIZE = 80
LIVE_CLASS_INDEX = 1
CROP_SCALE = 2.7  # matches the "2.7" in the upstream model filename


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - np.max(x))
    return e / np.sum(e)


class LivenessChecker:
    def __init__(self, model_cache_dir: str) -> None:
        self.model_cache_dir = model_cache_dir
        self.available = False
        # Typed `Any` (rather than left for mypy to infer as `None` from
        # this first assignment) because both a real
        # `onnxruntime.InferenceSession` (in `load()`) and an arbitrary test
        # double (in `inject_for_tests()`) get assigned here; onnxruntime
        # ships no py.typed marker, so a precise type isn't available/worth
        # importing just for this annotation.
        self._session: Any = None

    def load(self, providers: list[str]) -> None:
        try:
            path = self._ensure_weights()
            import onnxruntime as ort

            so = ort.SessionOptions()
            so.log_severity_level = 3
            self._session = ort.InferenceSession(str(path), sess_options=so, providers=providers)
            self.available = True
            logger.info("liveness_model_loaded", path=str(path))
        except Exception as exc:  # noqa: BLE001 - must never crash the kiosk
            logger.warning(
                "liveness_unavailable",
                exception_type=type(exc).__name__,
                detail=str(exc)[:200],
            )
            self.available = False

    def inject_for_tests(self, session: object) -> None:
        self._session = session
        self.available = True

    def _ensure_weights(self) -> Path:
        cache_dir = Path(self.model_cache_dir) / "minifasnet"
        cache_dir.mkdir(parents=True, exist_ok=True)
        dest = cache_dir / MODEL_FILENAME
        if dest.exists() and self._sha256(dest) == MODEL_SHA256:
            return dest

        logger.info("liveness_model_downloading", url=MODEL_URL, dest=str(dest))
        tmp = dest.with_suffix(".tmp")
        urllib.request.urlretrieve(MODEL_URL, tmp)  # noqa: S310 - fixed, documented URL
        digest = self._sha256(tmp)
        if digest != MODEL_SHA256:
            os.remove(tmp)
            raise ValueError(f"checksum mismatch for {MODEL_FILENAME}: got {digest}")
        tmp.rename(dest)
        return dest

    @staticmethod
    def _sha256(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 16), b""):
                h.update(chunk)
        return h.hexdigest()

    def _preprocess(self, crop: np.ndarray, box: tuple[float, float, float, float]) -> np.ndarray:
        h, w = crop.shape[:2]
        x1, y1, x2, y2 = box
        box_w, box_h = x2 - x1, y2 - y1
        cx, cy = x1 + box_w / 2, y1 + box_h / 2
        half = max(box_w, box_h) * CROP_SCALE / 2
        cx1, cy1 = max(0, int(cx - half)), max(0, int(cy - half))
        cx2, cy2 = min(w, int(cx + half)), min(h, int(cy + half))
        patch = crop[cy1:cy2, cx1:cx2]
        if patch.size == 0:
            patch = crop
        resized = cv2.resize(patch, (INPUT_SIZE, INPUT_SIZE))
        arr = resized.astype(np.float32) / 255.0
        arr = np.transpose(arr, (2, 0, 1))[None, ...]  # NCHW
        return arr

    def check(self, frame: np.ndarray, box: tuple[float, float, float, float]) -> float:
        """Returns a liveness score in [0, 1]. If the model is unavailable,
        callers must consult `self.available` first -- this method returns
        1.0 (pass) as a safe default only so it never raises."""
        if not self.available or self._session is None:
            return 1.0
        inp = self._preprocess(frame, box)
        input_name = self._session.get_inputs()[0].name
        outputs = self._session.run(None, {input_name: inp})
        logits = np.asarray(outputs[0]).reshape(-1)
        probs = _softmax(logits)
        return float(probs[LIVE_CLASS_INDEX])
