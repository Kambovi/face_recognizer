"""Liveness calibration tool -- run it once per camera at install time.

Anti-spoofing scores depend on the camera, lens and lighting, so the right
`liveness_threshold` for a site is measured, not guessed. Run this twice in
front of the actual entry-point camera:

    python -m kiosk.liveness_check --label real  --seconds 30   # walk past normally
    python -m kiosk.liveness_check --label spoof --seconds 30   # hold up a phone photo / printout
    python -m kiosk.liveness_check --recommend

Each run prints min / median / max live-scores and saves them to
liveness_calibration.json. `--recommend` suggests a threshold halfway
between the real faces' 10th percentile and the spoofs' 90th percentile;
set it on the Settings page (`liveness_threshold`).

Uses the same env vars as the kiosk (CAMERA_SOURCE, MODEL_CACHE_DIR,
DEVICE_PREFERENCE, INSIGHTFACE_MODEL_NAME).
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

CALIB_FILE = Path("liveness_calibration.json")


def _load() -> dict[str, list[float]]:
    try:
        return json.loads(CALIB_FILE.read_text())
    except (OSError, ValueError):
        return {}


def recommend(data: dict[str, list[float]]) -> float | None:
    real, spoof = data.get("real") or [], data.get("spoof") or []
    if not real or not spoof:
        return None
    lo_real = float(np.percentile(real, 10))
    hi_spoof = float(np.percentile(spoof, 90))
    return round((lo_real + hi_spoof) / 2, 2)


def main() -> None:  # pragma: no cover - needs a camera
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", choices=["real", "spoof"])
    ap.add_argument("--seconds", type=int, default=30)
    ap.add_argument("--recommend", action="store_true")
    args = ap.parse_args()

    if args.recommend:
        data = _load()
        for k in ("real", "spoof"):
            v = data.get(k) or []
            if v:
                print(f"{k:5}: n={len(v)}  min={min(v):.2f}  median={np.median(v):.2f}  max={max(v):.2f}")
        th = recommend(data)
        print("Run both --label real and --label spoof first." if th is None else f"Recommended liveness_threshold = {th}")
        if th is not None and np.percentile(data["real"], 10) <= np.percentile(data["spoof"], 90):
            print("WARNING: real and spoof scores overlap -- improve lighting / camera angle before relying on liveness.")
        return
    if not args.label:
        ap.error("give --label real|spoof, or --recommend")

    from kiosk import device
    from kiosk.capture import make_frame_source
    from kiosk.config import get_kiosk_config
    from kiosk.face_engine import FaceEngine
    from kiosk.liveness import LivenessChecker

    cfg = get_kiosk_config()
    providers, info = device.resolve_providers(device_preference=cfg.device_preference)
    engine = FaceEngine(cfg.model_cache_dir, cfg.insightface_model_name, providers, (640, 640))
    engine.load()
    checker = LivenessChecker(cfg.model_cache_dir)
    checker.load(providers)
    if not checker.available:
        raise SystemExit("Liveness models could not be loaded -- see the kiosk log / docs/PROJECT_BIBLE.md section 13.")
    source = make_frame_source(cfg.camera_source)
    scores: list[float] = []
    end = time.monotonic() + args.seconds
    print(f"Recording '{args.label}' for {args.seconds}s from {cfg.camera_source} ...")
    try:
        while time.monotonic() < end:
            frame = source.read()
            if frame is None:
                continue
            faces = engine.detect(frame)
            if not faces:
                continue
            face = max(faces, key=lambda f: (f.box[2] - f.box[0]) * (f.box[3] - f.box[1]))
            s = checker.check(frame, face.box)
            scores.append(s)
            print(f"  live-score {s:.2f}")
    finally:
        source.release()
    if not scores:
        raise SystemExit("No face seen -- stand in front of the camera and try again.")
    data = _load()
    data[args.label] = scores
    CALIB_FILE.write_text(json.dumps(data))
    print(f"{args.label}: n={len(scores)}  min={min(scores):.2f}  median={np.median(scores):.2f}  max={max(scores):.2f}")
    print("Saved. Run the other label, then --recommend.")


if __name__ == "__main__":  # pragma: no cover
    main()
