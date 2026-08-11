from __future__ import annotations

from pathlib import Path
import sys
from types import ModuleType

import numpy as np

from neuroscope_eeg.acquisition.legacy import LegacyRealtimeSource
from realtime_eeg_viewer import NeuracleSource


class FakeBuffer:
    def __init__(self, chunks: list[np.ndarray]) -> None:
        self.chunks = list(chunks)

    def getUpdate(self) -> np.ndarray:  # noqa: N802 - vendor API name
        if not self.chunks:
            return np.empty((3, 0), dtype=np.float32)
        return self.chunks.pop(0)


class FakeDataServerThread:
    chunks: list[np.ndarray] = []

    def __init__(self, **_kwargs) -> None:
        self.channelNames = ["C3", "C4", "TRIGGER"]
        self.channelTypes = ["EEG", "EEG", "TRIGGER"]
        self.buffer = FakeBuffer(self.chunks)

    def connect(self, **_kwargs) -> bool:
        return False

    def isReady(self) -> bool:  # noqa: N802 - vendor API name
        return True

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None


def install_vendor_module(monkeypatch, chunks: list[np.ndarray]) -> None:
    FakeDataServerThread.chunks = chunks
    package = ModuleType("collect")
    package.__path__ = []  # type: ignore[attr-defined]
    api = ModuleType("collect.neuracle_api")
    api.DataServerThread = FakeDataServerThread  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "collect", package)
    monkeypatch.setitem(sys.modules, "collect.neuracle_api", api)


def test_neuracle_excludes_trigger_channel_and_detects_nonzero_edges(monkeypatch) -> None:
    install_vendor_module(
        monkeypatch,
        [
            np.asarray([[1, 2, 3, 4, 5, 6], [7, 8, 9, 10, 11, 12], [0, 53, 53, 0, 53, 0]]),
            np.asarray([[13, 14], [15, 16], [0, 84]]),
        ],
    )
    source = NeuracleSource(Path("."), "127.0.0.1", 8712, 1000.0, 2, 30.0, 1.0)
    source.start()
    first = source.get_new_samples()
    first_triggers = source.drain_hardware_triggers()
    second = source.get_new_samples()
    second_triggers = source.drain_hardware_triggers()

    assert first.shape == (2, 6)
    assert second.shape == (2, 2)
    assert [(item.code, item.sample_index, item.channel_name) for item in first_triggers] == [
        (53, 1, "TRIGGER"),
        (53, 4, "TRIGGER"),
    ]
    assert [(item.code, item.sample_index) for item in second_triggers] == [(84, 7)]
    assert source.drain_hardware_triggers() == ()


def test_legacy_wrapper_exposes_vendor_trigger_sidecar_once() -> None:
    class FakeLegacy:
        metadata = type("Metadata", (), {"name": "neuracle", "sfreq": 1000.0, "channel_names": ("C3",)})()

        def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

        def get_new_samples(self) -> np.ndarray:
            return np.ones((1, 2), dtype=np.float32)

        def drain_hardware_triggers(self):
            from neuroscope_eeg.timing.models import HardwareTriggerSample

            return (HardwareTriggerSample(51, 1, "TRIGGER"),)

    wrapper = LegacyRealtimeSource(FakeLegacy())
    wrapper.start()
    wrapper.read_chunk()
    assert wrapper.drain_hardware_triggers()[0].code == 51
