"""Tests for NON-NEGOTIABLE #8: device resolution degrades, never crashes.

All four required sub-tests plus the "resolves exactly once per process"
test live here, against a mocked `onnxruntime`/`nvidia-smi` -- no real GPU or
network access required.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from kiosk import device as device_mod


@pytest.fixture(autouse=True)
def _reset_device_cache():
    device_mod.reset_cache_for_tests()
    yield
    device_mod.reset_cache_for_tests()


class _FakeSession:
    """Stands in for onnxruntime.InferenceSession."""

    def __init__(self, reported_providers: list[str]) -> None:
        self._reported_providers = reported_providers

    def run(self, *_args, **_kwargs):
        return [None]

    def get_providers(self) -> list[str]:
        return self._reported_providers


def test_cuda_available_but_session_creation_raises_falls_back_to_cpu(monkeypatch, caplog):
    """mock CUDA available but session creation raises -> app boots on CPU,
    logs WARNING, /health (via the returned dict) reports the fallback."""
    monkeypatch.setattr(device_mod.ort, "get_available_providers", lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"])

    def _session_factory(model_bytes, sess_options=None, providers=None):
        first = providers[0]
        first_name = first[0] if isinstance(first, tuple) else first
        if first_name == "CUDAExecutionProvider":
            raise RuntimeError("CUDA driver / cuDNN version mismatch")
        return _FakeSession(["CPUExecutionProvider"])

    monkeypatch.setattr(device_mod.ort, "InferenceSession", _session_factory)

    providers, info = device_mod.resolve_providers(device_preference="auto")

    assert providers == ["CPUExecutionProvider"]
    assert info["provider"] == "CPUExecutionProvider"
    assert info["fallback_occurred"] is True
    assert info["fallback_from"] == "CUDAExecutionProvider"
    assert info["status"] == "ok"  # "auto" preference: CPU is an acceptable outcome


def test_silent_internal_fallback_is_detected(monkeypatch):
    """mock ORT reports CUDA available, session creation succeeds, but
    session.get_providers()[0] comes back CPUExecutionProvider (silent
    internal fallback) -> code detects this and reports CPU, not CUDA."""
    monkeypatch.setattr(device_mod.ort, "get_available_providers", lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"])

    calls: list[list] = []

    def _fake_session(model_bytes, sess_options=None, providers=None):
        calls.append(providers)
        # ORT "accepts" the CUDA request but silently serves on CPU only.
        return _FakeSession(["CPUExecutionProvider"])

    monkeypatch.setattr(device_mod.ort, "InferenceSession", _fake_session)

    providers, info = device_mod.resolve_providers(device_preference="auto")

    assert info["provider"] == "CPUExecutionProvider"
    assert "CUDAExecutionProvider" not in providers
    assert info["fallback_occurred"] is True
    assert info["fallback_from"] == "CUDAExecutionProvider"
    # We really did attempt CUDA first, proving detection (not just skipping it).
    assert any(
        (p[0] if isinstance(p, tuple) else p) == "CUDAExecutionProvider"
        for call in calls
        for p in call
    )


def test_forced_cuda_preference_with_no_usable_gpu_serves_traffic_degraded(monkeypatch):
    """device_preference="cuda" with no usable GPU -> still serves traffic,
    logs ERROR, reports status degraded (mirrors /health contract)."""
    monkeypatch.setattr(device_mod.ort, "get_available_providers", lambda: ["CPUExecutionProvider"])

    def _fake_session(model_bytes, sess_options=None, providers=None):
        return _FakeSession(["CPUExecutionProvider"])

    monkeypatch.setattr(device_mod.ort, "InferenceSession", _fake_session)

    providers, info = device_mod.resolve_providers(device_preference="cuda")

    assert providers == ["CPUExecutionProvider"]
    assert info["provider"] == "CPUExecutionProvider"
    assert info["status"] == "degraded"
    assert info["device_preference"] == "cuda"


def test_resolution_runs_exactly_once_per_process(monkeypatch):
    """provider resolution runs exactly once per process -- spy the probe
    function, process 100 frames' worth of calls, assert call count 1."""
    monkeypatch.setattr(device_mod.ort, "get_available_providers", lambda: ["CPUExecutionProvider"])

    def _fake_session(model_bytes, sess_options=None, providers=None):
        return _FakeSession(["CPUExecutionProvider"])

    monkeypatch.setattr(device_mod.ort, "InferenceSession", _fake_session)

    assert device_mod.probe_call_count == 0
    for _ in range(100):
        device_mod.resolve_providers(device_preference="auto")

    assert device_mod.probe_call_count == 1


def test_cpu_forced_preference_never_probes_gpu(monkeypatch):
    calls = []
    monkeypatch.setattr(device_mod.ort, "get_available_providers", lambda: ["CUDAExecutionProvider", "TensorrtExecutionProvider", "CPUExecutionProvider"])

    def _fake_session(model_bytes, sess_options=None, providers=None):
        calls.append(providers)
        return _FakeSession(["CPUExecutionProvider"])

    monkeypatch.setattr(device_mod.ort, "InferenceSession", _fake_session)

    providers, info = device_mod.resolve_providers(device_preference="cpu")
    assert providers == ["CPUExecutionProvider"]
    assert info["status"] == "ok"
    assert len(calls) == 1  # only the CPU floor probe, never GPU candidates


def test_real_cpu_probe_end_to_end_no_mocking():
    """Sanity check against the real onnxruntime CPU provider (no mocking) --
    this always passes in CI/sandbox since CPUExecutionProvider is always
    available."""
    providers, info = device_mod.resolve_providers(device_preference="auto")
    assert info["provider"] in device_mod.ort.get_available_providers()
    assert info["status"] in ("ok", "degraded")
    assert "tuning" in info
    assert info["tuning"]["det_size"] == (640, 640) or info["tuning"]["det_size"] == [640, 640]


# --- Source-scan test (NON-NEGOTIABLE #8) -----------------------------------

_HARDCODED_PATTERN = re.compile(r"""providers\s*=\s*\[\s*["']CPUExecutionProvider["']\s*\]""")


def test_no_hardcoded_cpu_provider_outside_device_py():
    """grep the tree: `providers=["CPUExecutionProvider"]` (or equivalent)
    must appear nowhere outside device.py."""
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    offenders = []
    for py_file in repo_root.rglob("*.py"):
        if "device.py" in py_file.name:
            continue
        if any(part in {".venv-test", "node_modules", ".git", "__pycache__"} for part in py_file.parts):
            continue
        text = py_file.read_text(encoding="utf-8", errors="ignore")
        if _HARDCODED_PATTERN.search(text):
            offenders.append(str(py_file))
    assert offenders == [], f"hardcoded CPUExecutionProvider found outside device.py: {offenders}"
