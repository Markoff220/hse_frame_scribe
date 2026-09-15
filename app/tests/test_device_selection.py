"""Выбор устройства ASR: cuda → mps (Apple Silicon) → cpu."""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

import asr


def _fake_torch(cuda: bool, mps: bool):
    torch = types.ModuleType("torch")
    cuda_mod = types.SimpleNamespace(is_available=lambda: cuda)
    torch.cuda = cuda_mod
    if mps:
        torch.backends = types.SimpleNamespace(
            mps=types.SimpleNamespace(is_available=lambda: True))
    else:
        torch.backends = types.SimpleNamespace(mps=None)
    return torch


def test_select_device_prefers_cuda(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(cuda=True, mps=True))
    assert asr.select_device("auto") == "cuda"


def test_select_device_falls_back_to_mps(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(cuda=False, mps=True))
    assert asr.select_device("auto") == "mps"


def test_select_device_cpu_when_no_acceleration(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(cuda=False, mps=False))
    assert asr.select_device("auto") == "cpu"


def test_select_device_respects_explicit_value(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(cuda=True, mps=True))
    assert asr.select_device("cpu") == "cpu"
    assert asr.select_device("cuda") == "cuda"