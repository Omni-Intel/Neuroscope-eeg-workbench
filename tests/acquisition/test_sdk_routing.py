"""Real adapters must surface SDK errors, never fabricate substitute samples."""
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from neuroscope_eeg.acquisition.devices import NeuracleSource, OmniBCISource, brainco_source
from neuroscope_eeg.core.models import ConnectionState
from neuroscope_eeg.core.session import SessionController


def assert_failed_without_data(source, message):
    controller = SessionController(source)
    controller.start()
    controller._thread.join(timeout=3)
    try:
        assert not controller.worker_alive
        assert controller.source is source
        assert controller.state == ConnectionState.ERROR
        assert message in controller.error
        assert controller.samples_received == 0
        assert controller.buffer.latest_available(1) is None
    finally:
        controller.stop()


def test_omni_sdk_connection_failure_is_not_simulation():
    connect = Mock(side_effect=RuntimeError("SDK connection rejected"))
    source = OmniBCISource("serial://COM17", "stm32", sdk=SimpleNamespace(Board=SimpleNamespace(connect=connect)))
    assert_failed_without_data(source, "SDK connection rejected")
    connect.assert_called_once_with("serial://COM17", device_type="stm32")


@pytest.mark.parametrize("mode", ["test", "shorted", "unknown", None])
def test_omni_rejects_test_signal_and_unknown_frontend(mode):
    board = SimpleNamespace(get_config=lambda: SimpleNamespace(verified=True, mode=mode),
                            start=Mock(), stop=Mock(), close=Mock())
    sdk = SimpleNamespace(Board=SimpleNamespace(connect=lambda *a, **kw: board))
    source = OmniBCISource("serial://COM17", sdk=sdk)
    assert_failed_without_data(source, "不用于被试 EEG")
    board.start.assert_not_called()
    board.close.assert_called_once()


def test_neuracle_connect_failure_is_not_simulation(monkeypatch):
    server = SimpleNamespace(connect=Mock(return_value=True), stop=Mock())
    monkeypatch.setattr("neuroscope_eeg.acquisition.vendor.collect.neuracle_api.DataServerThread", lambda **kw: server)
    source = NeuracleSource("192.0.2.10", 8712)
    assert_failed_without_data(source, "无法连接 Neuracle")
    server.connect.assert_called_once_with(hostname="192.0.2.10", port=8712)
    server.stop.assert_called_once()


def test_missing_brainco_sdk_is_not_simulation(monkeypatch):
    monkeypatch.setitem(sys.modules, "bcigo_sdk", None)
    source = brainco_source()
    assert_failed_without_data(source, "bcigo_sdk")


def test_desktop_brainco_adapter_sends_normal_signal_to_sdk(monkeypatch):
    # This is the vendor adapter selected by the desktop, not the older facade.
    source = brainco_source(250, 32, "192.0.2.11", 9000, False)
    backend = source.backend
    backend._sdk = SimpleNamespace(
        set_cfg=Mock(), clear_eeg_buffer=Mock(),
        EegSampleRate=SimpleNamespace(SR_250Hz="250Hz"),
        EegSignalGain=SimpleNamespace(GAIN_6="gain6"),
        EegSignalSource=SimpleNamespace(NORMAL="normal", TEST_SIGNAL="test"),
    )
    client = SimpleNamespace(start_stream=Mock(side_effect=RuntimeError("device offline")))
    backend._client = client
    monkeypatch.setattr(backend, "_run_sdk_call", lambda fn, *a, **kw: fn(*a, **kw))
    with pytest.raises(RuntimeError, match="device offline"):
        backend._start_stream_unified("parser")
    client.start_stream.assert_called_once_with("parser", fs="250Hz", gain="gain6", signal="normal")
