from __future__ import annotations

import sys
from enum import Enum
from types import SimpleNamespace

import numpy as np
import pytest

from neuroscope_eeg.acquisition.brainco import BrainCoAcquirer
from neuroscope_eeg.acquisition.legacy import build_brainco_source


class SampleRate(Enum):
    SR_250Hz = 250
    SR_500Hz = 500
    SR_1000Hz = 1000
    SR_2000Hz = 2000


class Gain(Enum):
    GAIN_1 = 1
    GAIN_2 = 2
    GAIN_4 = 4
    GAIN_6 = 6
    GAIN_8 = 8
    GAIN_12 = 12
    GAIN_24 = 24


class SignalSource(Enum):
    NORMAL = 1
    TEST_SIGNAL = 2


class MsgType(Enum):
    BCIGo = 1


class FakeClient:
    instances: list["FakeClient"] = []

    def __init__(self, addr: str, port: int) -> None:
        self.addr = addr
        self.port = port
        self.started: tuple[object, object, object, object] | None = None
        self.disconnected = False
        FakeClient.instances.append(self)

    async def start_stream(self, parser, *, fs, gain, signal) -> None:
        self.started = (parser, fs, gain, signal)

    def disconnect_tcp_blocking(self) -> None:
        self.disconnected = True


def fake_sdk(buffer: np.ndarray) -> SimpleNamespace:
    callbacks: dict[str, object] = {}

    async def scan() -> list[tuple[str, int]]:
        return [("192.168.1.6", 8866)]

    def set_callback(name: str):
        def register(callback) -> None:
            callbacks[name] = callback

        return register

    return SimpleNamespace(
        BCIGoClient=FakeClient,
        EegSampleRate=SampleRate,
        EegSignalGain=Gain,
        EegSignalSource=SignalSource,
        MessageParser=lambda device_id, msg_type: (device_id, msg_type),
        MsgType=MsgType,
        mdns_start_scan=scan,
        mdns_stop_scan=lambda: None,
        set_cfg=lambda *_args: None,
        clear_eeg_buffer=lambda: None,
        get_eeg_buffer=lambda *_args: buffer,
        set_connection_state_callback=set_callback("connection"),
        set_received_data_callback=set_callback("received"),
        set_imp_data_callback=set_callback("impedance"),
        set_msg_resp_callback=set_callback("response"),
        _callbacks=callbacks,
    )


def test_bcigo_uses_unified_client_startup_and_normalizes_samples(monkeypatch) -> None:
    FakeClient.instances.clear()
    sdk = fake_sdk(np.arange(12, dtype=np.float32).reshape(3, 4))
    monkeypatch.setitem(sys.modules, "bcigo_sdk", sdk)
    source = BrainCoAcquirer(sfreq=250, n_channels=3, brainco_addr="10.0.0.7", brainco_port=9000, auto_discover=False)

    source.start_stream()

    client = FakeClient.instances[0]
    assert client.addr == "10.0.0.7"
    assert client.port == 9000
    assert client.started == (("bcigo", MsgType.BCIGo), SampleRate.SR_250Hz, Gain.GAIN_6, SignalSource.NORMAL)
    data, timestamps = source.get_new_samples()
    np.testing.assert_array_equal(data, np.arange(12, dtype=np.float32).reshape(3, 4))
    np.testing.assert_allclose(timestamps, [0.0, 0.004, 0.008, 0.012])

    source.stop_stream()
    assert client.disconnected


def test_bcigo_discovers_device_and_accepts_sample_major_buffer(monkeypatch) -> None:
    FakeClient.instances.clear()
    sdk = fake_sdk(np.arange(12, dtype=np.float32).reshape(4, 3))
    monkeypatch.setitem(sys.modules, "bcigo_sdk", sdk)
    source = BrainCoAcquirer(sfreq=500, n_channels=3, auto_discover=True)

    source.start_stream()

    assert (FakeClient.instances[0].addr, FakeClient.instances[0].port) == ("192.168.1.6", 8866)
    data, _ = source.get_new_samples()
    np.testing.assert_array_equal(data, np.arange(12, dtype=np.float32).reshape(4, 3).T)
    source.stop_stream()


def test_bcigo_uses_callback_discovery_when_scan_has_no_result(monkeypatch) -> None:
    FakeClient.instances.clear()
    sdk = fake_sdk(np.arange(12, dtype=np.float32).reshape(3, 4))
    sdk.mdns_start_scan = lambda: []
    sdk.mdns_start_scan_multi = lambda callback: callback({"addr": "192.168.1.9", "port": 8877})
    monkeypatch.setitem(sys.modules, "bcigo_sdk", sdk)
    source = BrainCoAcquirer(sfreq=250, n_channels=3, auto_discover=True)

    source.start_stream()

    assert (FakeClient.instances[0].addr, FakeClient.instances[0].port) == ("192.168.1.9", 8877)
    source.stop_stream()


def test_bcigo_missing_sdk_has_actionable_error(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "bcigo_sdk", raising=False)
    monkeypatch.setattr("importlib.import_module", lambda _name: (_ for _ in ()).throw(ModuleNotFoundError("missing")))
    source = BrainCoAcquirer(n_channels=3, brainco_addr="10.0.0.7", brainco_port=9000, auto_discover=False)

    with pytest.raises(RuntimeError, match="bcigo-sdk==1.0.2"):
        source.start_stream()


def test_bcigo_rejects_old_sdk_only_configuration() -> None:
    with pytest.raises(ValueError, match="250, 500, 1000, 2000"):
        BrainCoAcquirer(sfreq=125)
    with pytest.raises(ValueError, match="1, 2, 4, 6, 8, 12, 24"):
        BrainCoAcquirer(eeg_gain=3)


def test_workbench_brainco_source_has_no_oi_mi_path_dependency() -> None:
    source = build_brainco_source(250, 5, "10.0.0.7", 9000, False)

    assert source.metadata.source_type == "brainco"
    assert source.metadata.channel_names == ("FP1", "FP2", "F3", "F4", "F7")
