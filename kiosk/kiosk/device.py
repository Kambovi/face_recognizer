"""Runtime ONNX Runtime execution-provider resolution.

THIS IS THE ONLY PLACE IN THE CODEBASE THAT CHOOSES AN ONNXRUNTIME PROVIDER.
Every model session in the kiosk (detector, recognizer, liveness) is built
with the providers list returned by `resolve_providers()`. Nothing else in
this tree should ever hardcode `providers=["CPUExecutionProvider"]` or any
other fixed provider list -- `make lint` includes a grep for that pattern
outside this file (see NON-NEGOTIABLE #8, "source-scan test").

Why this is more than `onnxruntime.get_available_providers()`:
`onnxruntime-gpu` frequently *reports* CUDAExecutionProvider as available
while session creation silently fails or silently falls back to CPU
(mismatched CUDA/cuDNN, no GPU visible in the container, an exhausted GPU,
`CUDA_VISIBLE_DEVICES=""`). The only way to know a provider actually works is
to build a session pinned to it and run real inference, then check
`session.get_providers()[0]` -- ORT does not raise when it silently falls
back, it just quietly serves the request on a different provider than the one
requested. That is exactly the failure this module is built to catch.

Resolution never raises. A GPU misconfiguration must never take the kiosk
offline; degraded-on-CPU always beats offline.
"""
from __future__ import annotations

import dataclasses
import os
import subprocess
import threading
import time
from typing import Any

import numpy as np
import onnxruntime as ort
import structlog

logger = structlog.get_logger(__name__)

# Priority order for `device_preference="auto"`. CPU is not listed here: it
# is the unconditional final fallback, always appended, never probed away.
_AUTO_LADDER: list[str] = [
    "TensorrtExecutionProvider",
    "CUDAExecutionProvider",
    "CoreMLExecutionProvider",
]

_CPU_PROVIDER = "CPUExecutionProvider"

# Device-dependent tuning profile defaults, per spec table. Settings-table
# values (if the operator has overridden them) always win over these; these
# are only the *defaults* applied on first seed / when unset.
_TUNING_DEFAULTS: dict[str, dict[str, Any]] = {
    "cpu": {
        "det_size": (640, 640),
        "capture_fps": 6,
        "bestshot_frames": 5,
        "ort_intra_op_threads": min(4, os.cpu_count() or 1),
        "batch_size": 1,
    },
    "gpu": {
        "det_size": (640, 640),
        "capture_fps": 15,
        "bestshot_frames": 8,
        "ort_intra_op_threads": 1,
        "batch_size": 1,
    },
}


@dataclasses.dataclass(frozen=True)
class DeviceInfo:
    provider: str
    available_providers: list[str]
    device_preference: str
    fallback_occurred: bool
    fallback_from: str | None
    device_name: str | None
    vram_gb: float | None
    profile: str  # "cpu" | "gpu"
    probe_ms: float
    status: str  # "ok" | "degraded"
    tuning: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["det_size"] = list(self.tuning.get("det_size", (640, 640)))
        return d


_lock = threading.Lock()
_cached: DeviceInfo | None = None
# Exposed purely so tests can assert "resolution runs exactly once per
# process" by spying on this counter across many resolve_providers() calls.
probe_call_count = 0


def reset_cache_for_tests() -> None:
    """Test-only hook. Never called from production code paths."""
    global _cached, probe_call_count
    with _lock:
        _cached = None
        probe_call_count = 0


def _build_smoke_model_bytes() -> bytes:
    """A tiny in-memory ONNX graph: elementwise Add on a 1x3x64x64 tensor.
    No file I/O, no network -- safe to run in any sandbox."""
    from onnx import TensorProto, helper

    x = helper.make_tensor_value_info("x", TensorProto.FLOAT, [1, 3, 64, 64])
    y = helper.make_tensor_value_info("y", TensorProto.FLOAT, [1, 3, 64, 64])
    node = helper.make_node("Add", ["x", "x"], ["y"])
    graph = helper.make_graph([node], "device_smoke_test", [x], [y])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    return model.SerializeToString()


def _engine_cache_writable(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".write_probe")
        with open(probe, "wb") as fh:
            fh.write(b"ok")
        os.remove(probe)
        return True
    except Exception:  # noqa: BLE001 - any failure means "not writable"
        return False


def _gpu_name_and_vram() -> tuple[str | None, float | None]:
    """Best-effort GPU identification for the startup log line. Never raises,
    never required for correctness -- purely observability."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if out.returncode == 0 and out.stdout.strip():
            name, mem_mib = [p.strip() for p in out.stdout.strip().splitlines()[0].split(",")]
            return name, round(float(mem_mib) / 1024, 1)
    except Exception:  # noqa: BLE001
        pass
    return None, None


def _probe_provider(provider: str, engine_cache_dir: str) -> tuple[bool, float, str | None, float | None]:
    """Try to actually run inference on `provider`. Returns
    (worked, elapsed_ms, device_name, vram_gb). Never raises."""
    global probe_call_count
    probe_call_count += 1
    start = time.monotonic()
    try:
        model_bytes = _build_smoke_model_bytes()
        so = ort.SessionOptions()
        so.log_severity_level = 3

        provider_entry: Any = provider
        if provider == "TensorrtExecutionProvider":
            provider_entry = (
                provider,
                {
                    "trt_engine_cache_enable": True,
                    "trt_engine_cache_path": engine_cache_dir,
                },
            )

        providers_list = [provider_entry] if provider == _CPU_PROVIDER else [provider_entry, _CPU_PROVIDER]
        session = ort.InferenceSession(
            model_bytes,
            sess_options=so,
            providers=providers_list,
        )
        x = np.random.rand(1, 3, 64, 64).astype(np.float32)
        session.run(None, {"x": x})

        actual = session.get_providers()[0]
        elapsed_ms = (time.monotonic() - start) * 1000
        if actual != provider:
            # ORT accepted the request but silently served it on a different
            # provider -- the exact silent-fallback failure mode this module
            # exists to catch.
            logger.warning(
                "device_probe_silent_fallback",
                requested=provider,
                actual=actual,
            )
            return False, elapsed_ms, None, None

        device_name, vram_gb = (None, None)
        if provider in ("CUDAExecutionProvider", "TensorrtExecutionProvider"):
            device_name, vram_gb = _gpu_name_and_vram()
        elif provider == "CoreMLExecutionProvider":
            device_name = "Apple Silicon (CoreML)"

        return True, elapsed_ms, device_name, vram_gb
    except Exception as exc:  # noqa: BLE001 - a GPU problem must never raise
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.warning(
            "device_probe_failed",
            provider=provider,
            exception_type=type(exc).__name__,
        )
        return False, elapsed_ms, None, None


def _candidates_for(preference: str) -> list[str]:
    pref = (preference or "auto").lower()
    if pref == "cpu":
        return []
    if pref == "cuda":
        return ["CUDAExecutionProvider"]
    if pref == "tensorrt":
        return ["TensorrtExecutionProvider", "CUDAExecutionProvider"]
    return list(_AUTO_LADDER)  # "auto" (default) and any unrecognized value


def resolve_providers(
    device_preference: str = "auto",
    engine_cache_dir: str = "/models/trt_cache",
    force_reprobe: bool = False,
) -> tuple[list[str], dict[str, Any]]:
    """Resolve the ONNX Runtime provider to use, once per process.

    Returns (providers_list, info_dict). `providers_list` is what callers
    should pass straight to `onnxruntime.InferenceSession(..., providers=...)`
    for their REAL model sessions (detector/recognizer/liveness) -- it always
    ends with CPUExecutionProvider so ORT itself has a final fallback even if
    something about the *real* model differs from our smoke graph.
    `info_dict` is the full DeviceInfo, suitable for logging and for
    `GET /health`'s `device` block.
    """
    global _cached
    with _lock:
        if _cached is not None and not force_reprobe:
            return _output(_cached)

        pref = (device_preference or "auto").lower()
        available = list(ort.get_available_providers())
        candidates = _candidates_for(pref)

        resolved_provider = _CPU_PROVIDER
        device_name: str | None = None
        vram_gb: float | None = None
        total_probe_ms = 0.0
        fallback_from: str | None = None

        for candidate in candidates:
            if candidate not in available:
                continue
            if candidate == "TensorrtExecutionProvider" and not _engine_cache_writable(engine_cache_dir):
                logger.warning(
                    "device_probe_skipped",
                    provider=candidate,
                    reason="engine_cache_dir_not_writable",
                )
                if fallback_from is None:
                    fallback_from = candidate
                continue

            ok, elapsed_ms, name, vram = _probe_provider(candidate, engine_cache_dir)
            total_probe_ms += elapsed_ms
            if ok:
                resolved_provider = candidate
                device_name = name
                vram_gb = vram
                break
            if fallback_from is None:
                fallback_from = candidate

        status = "ok"
        if resolved_provider == _CPU_PROVIDER:
            # Always prove the CPU floor works too, so probe_ms/logging is
            # consistent and we never silently ship a provider we never ran.
            ok, elapsed_ms, _, _ = _probe_provider(_CPU_PROVIDER, engine_cache_dir)
            total_probe_ms += elapsed_ms
            if pref in ("cuda", "tensorrt"):
                # Contract: a forced GPU preference that couldn't be honored
                # still serves traffic on CPU, but is loudly degraded.
                status = "degraded"
                logger.error(
                    "device_resolution_degraded",
                    requested_preference=pref,
                    resolved_provider=resolved_provider,
                    fallback_from=fallback_from,
                )
            if not ok:  # pragma: no cover - CPU EP failing is exceptional
                logger.error("device_resolution_cpu_probe_failed")
                status = "degraded"

        profile = "cpu" if resolved_provider == _CPU_PROVIDER else "gpu"
        tuning = dict(_TUNING_DEFAULTS[profile])

        info = DeviceInfo(
            provider=resolved_provider,
            available_providers=available,
            device_preference=pref,
            fallback_occurred=fallback_from is not None,
            fallback_from=fallback_from,
            device_name=device_name,
            vram_gb=vram_gb,
            profile=profile,
            probe_ms=round(total_probe_ms, 2),
            status=status,
            tuning=tuning,
        )
        _cached = info

        logger.info(
            "device_resolved",
            provider=info.provider,
            device_name=info.device_name,
            vram_gb=info.vram_gb,
            profile=info.profile,
            probe_ms=info.probe_ms,
            fallback_from=info.fallback_from,
            status=info.status,
        )
        return _output(info)


def _output(info: DeviceInfo) -> tuple[list[str], dict[str, Any]]:
    providers = [info.provider] if info.provider == _CPU_PROVIDER else [info.provider, _CPU_PROVIDER]
    return providers, info.as_dict()


def get_cached_device_info() -> dict[str, Any] | None:
    """Read-only accessor for already-resolved device info (e.g. for
    heartbeats), without triggering a resolution."""
    with _lock:
        return _cached.as_dict() if _cached else None
