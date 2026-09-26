"""`make bench` -- prints per-stage latency for the kiosk-side half of the
recognition pipeline (spec steps 1-6), run via
`docker compose exec -T kiosk python -m kiosk.bench`.

This is a component-wise microbenchmark, not a full end-to-end pipeline
replay: several stages (best-shot buffering, the subject gate, motion
detection) only make their real decision across a *sequence* of frames from
one visit, so timing "the whole pipeline" for a single synthetic frame would
mostly measure how lucky the random synthetic frame was at tripping gates,
not the actual per-call cost of each stage. Instead, each stage is called
directly, in isolation, the number of times an operator actually cares
about: how much CPU (or GPU) time does one motion-gate check cost, one
detector call, one embedding, one liveness check, one best-shot score, one
subject-gate check. Summed together (roughly: motion + detect + bestshot
score x bestshot_frames + liveness + embed + subject gate), these are the
real cost centers NON-NEGOTIABLE #6 ("near-zero idle CPU") and the
CPU-vs-GPU tuning defaults in device.py are built around.

Detection and liveness run against real ONNX sessions when model weights are
available (downloaded once into `model_cache_dir`, same as the real kiosk
process); this script never trains or fine-tunes anything, so a fixed
synthetic frame is fine for timing purposes even though it contains no real
face -- the detector/recognizer/liveness graphs run their full, fixed amount
of compute regardless of what's in the frame. If weights aren't reachable
(no network), the corresponding rows are reported as "unavailable" rather
than making up numbers, and the script still exits 0 -- a missing model must
never fail `make bench`, only reduce what it can report.

Usage:
    python -m kiosk.bench [--iterations N] [--warmup N]
Env overrides (useful from `docker compose exec`): BENCH_ITERATIONS,
BENCH_WARMUP.
"""
from __future__ import annotations

import argparse
import os
import statistics
import time
from dataclasses import dataclass

import numpy as np
import structlog

from kiosk import device
from kiosk.bestshot import Candidate, score_candidate
from kiosk.config import get_kiosk_config
from kiosk.face_engine import DetectedFace, FaceEngine
from kiosk.liveness import LivenessChecker
from kiosk.motion_gate import MotionGate, MotionGateConfig
from kiosk.subject_gate import SubjectGate, SubjectGateConfig

logger = structlog.get_logger(__name__)

DEFAULT_ITERATIONS = 200
DEFAULT_WARMUP = 20

# A plausible visitor-sized box roughly centered in a 640x480 frame, used
# wherever a stage needs "a detected face" but isn't itself being timed for
# detection accuracy (embedding, liveness, best-shot scoring, subject gate).
_SYNTH_BOX: tuple[float, float, float, float] = (220.0, 100.0, 420.0, 380.0)
_SYNTH_KPS = np.array(
    [[280.0, 190.0], [360.0, 190.0], [320.0, 240.0], [290.0, 310.0], [350.0, 310.0]],
    dtype=np.float32,
)


@dataclass
class StageResult:
    name: str
    n: int
    mean_ms: float
    p50_ms: float
    p95_ms: float
    max_ms: float
    note: str = ""


def _timeit(name: str, fn, iterations: int, warmup: int) -> StageResult:
    for _ in range(warmup):
        fn()
    samples_ms: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        fn()
        samples_ms.append((time.perf_counter() - start) * 1000.0)
    samples_ms.sort()
    n = len(samples_ms)
    mean_ms = statistics.fmean(samples_ms)
    p50_ms = samples_ms[int(0.50 * (n - 1))]
    p95_ms = samples_ms[int(0.95 * (n - 1))]
    return StageResult(name=name, n=n, mean_ms=mean_ms, p50_ms=p50_ms, p95_ms=p95_ms, max_ms=samples_ms[-1])


def _skipped(name: str, reason: str) -> StageResult:
    return StageResult(name=name, n=0, mean_ms=0.0, p50_ms=0.0, p95_ms=0.0, max_ms=0.0, note=f"SKIPPED ({reason})")


def _synthetic_frame(rng: np.random.Generator, seed_variant: int) -> np.ndarray:
    """A deterministic, reproducible 640x480 BGR frame. `seed_variant`
    changes the content slightly frame-to-frame so the motion gate sees
    genuine pixel differences (it would otherwise treat every call after the
    first as a static, no-motion frame and short-circuit before doing any
    real comparison work)."""
    base = rng.integers(0, 255, size=(480, 640, 3), dtype=np.uint8)
    # Nudge a block of pixels so consecutive frames differ, without
    # reseeding the whole frame (which would make every call "all new
    # pixels" -- not representative of a real camera feed).
    base[seed_variant % 400 : seed_variant % 400 + 60, 100:400] = (seed_variant * 7) % 256
    return base


def print_report(results: list[StageResult], device_info: dict) -> None:
    print("=" * 78)
    print("kiosk per-stage latency benchmark")
    print("=" * 78)
    print(f"provider:      {device_info.get('provider')}")
    print(f"profile:       {device_info.get('profile')}  (device_name={device_info.get('device_name')})")
    print(f"det_size:      {device_info.get('det_size')}")
    print(f"status:        {device_info.get('status')}  fallback_from={device_info.get('fallback_from')}")
    print("-" * 78)
    header = f"{'stage':<28}{'n':>6}{'mean_ms':>11}{'p50_ms':>10}{'p95_ms':>10}{'max_ms':>10}"
    print(header)
    print("-" * len(header))
    for r in results:
        if r.note:
            print(f"{r.name:<28}{r.note}")
        else:
            print(f"{r.name:<28}{r.n:>6}{r.mean_ms:>11.3f}{r.p50_ms:>10.3f}{r.p95_ms:>10.3f}{r.max_ms:>10.3f}")
    print("-" * 78)
    summed = sum(r.mean_ms for r in results if not r.note)
    print(f"sum of per-stage means (rough one-visit cost, excludes idle-frame motion checks): {summed:.3f} ms")
    print("=" * 78)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=int(os.environ.get("BENCH_ITERATIONS", DEFAULT_ITERATIONS)))
    parser.add_argument("--warmup", type=int, default=int(os.environ.get("BENCH_WARMUP", DEFAULT_WARMUP)))
    args = parser.parse_args()

    config = get_kiosk_config()
    providers, device_info = device.resolve_providers(device_preference=config.device_preference)
    det_size_raw = device_info.get("det_size", [640, 640])
    det_size = (int(det_size_raw[0]), int(det_size_raw[1]))

    logger.info("bench_starting", providers=providers, device=device_info, iterations=args.iterations)

    face_engine = FaceEngine(
        model_cache_dir=config.model_cache_dir,
        model_name=config.insightface_model_name,
        providers=providers,
        det_size=det_size,
    )
    face_engine.load()

    liveness_checker = LivenessChecker(model_cache_dir=config.model_cache_dir)
    liveness_checker.load(providers)

    rng = np.random.default_rng(1234)
    frames = [_synthetic_frame(rng, i) for i in range(max(args.iterations, args.warmup) + 1)]
    _counter = {"i": 0}

    def _next_frame() -> np.ndarray:
        i = _counter["i"]
        _counter["i"] += 1
        return frames[i % len(frames)]

    results: list[StageResult] = []

    # -- Stage 1: motion gate --------------------------------------------------
    motion_gate = MotionGate(config=MotionGateConfig(), full_fps=6)
    motion_gate.process(_next_frame(), now=0.0)  # prime the reference frame
    _t = {"now": 1.0}

    def _motion_call() -> None:
        _t["now"] += 1.0 / 6.0
        motion_gate.process(_next_frame(), now=_t["now"])

    results.append(_timeit("motion_gate.process", _motion_call, args.iterations, args.warmup))

    # -- Stage 2: detection (real ONNX session if available) ------------------
    if face_engine.available:
        det_frame = _next_frame()
        results.append(_timeit("face_engine.detect", lambda: face_engine.detect(det_frame), args.iterations, args.warmup))
    else:
        results.append(_skipped("face_engine.detect", "model unavailable"))

    # -- Stage 1b: subject gate, pre-embedding ---------------------------------
    subject_gate = SubjectGate(config=SubjectGateConfig())
    _sg_t = {"now": 0.0}

    def _subject_pre_call() -> None:
        _sg_t["now"] += 0.2
        subject_gate.check_pre_embedding(_SYNTH_BOX, now=_sg_t["now"])

    results.append(_timeit("subject_gate.check_pre_embedding", _subject_pre_call, args.iterations, args.warmup))

    # -- Stage 4: best-shot scoring (pure CPU, no model) -----------------------
    bestshot_frame = _next_frame()
    candidate = Candidate(frame=bestshot_frame, box=_SYNTH_BOX, kps=_SYNTH_KPS, det_score=0.9)
    results.append(_timeit("bestshot.score_candidate", lambda: score_candidate(candidate), args.iterations, args.warmup))

    # -- Stage 5: liveness (real ONNX session if available) --------------------
    if liveness_checker.available:
        live_frame = _next_frame()
        results.append(
            _timeit("liveness_checker.check", lambda: liveness_checker.check(live_frame, _SYNTH_BOX), args.iterations, args.warmup)
        )
    else:
        results.append(_skipped("liveness_checker.check", "model unavailable"))

    # -- Stage 6: embedding (real ONNX session if available) -------------------
    if face_engine.available:
        embed_frame = _next_frame()
        synth_face = DetectedFace(box=_SYNTH_BOX, kps=_SYNTH_KPS, det_score=0.9)
        results.append(
            _timeit("face_engine.embed", lambda: face_engine.embed(embed_frame, synth_face), args.iterations, args.warmup)
        )
    else:
        results.append(_skipped("face_engine.embed", "model unavailable"))

    # -- Stage 1b: subject gate, post-embedding --------------------------------
    embedding_rng = np.random.default_rng(99)
    fixed_embedding = embedding_rng.normal(size=512).astype(np.float32)
    fixed_embedding /= np.linalg.norm(fixed_embedding)
    _sg2_t = {"now": 0.0}

    def _subject_embed_call() -> None:
        _sg2_t["now"] += 0.2
        subject_gate.check_embedding(fixed_embedding, now=_sg2_t["now"])

    results.append(_timeit("subject_gate.check_embedding", _subject_embed_call, args.iterations, args.warmup))

    print_report(results, device_info)


if __name__ == "__main__":
    main()
