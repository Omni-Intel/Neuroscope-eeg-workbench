from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from neuroscope_eeg.diagnostics.brainco_startup import StepwiseBrainCo
from neuroscope_eeg.acquisition.vendor.brainco_acquirer import BrainCoAcquirer
from neuroscope_eeg.diagnostics import brainco_startup as diagnostic


def test_legacy_mode_skips_negotiation_but_preserves_mode_ack_failure(monkeypatch):
    source = diagnostic.LegacyModeBrainCo()
    source._sdk = SimpleNamespace(set_cfg=Mock(), clear_eeg_buffer=Mock(),
                                 EegSampleRate=SimpleNamespace(SR_250Hz=250),
                                 EegSignalGain=SimpleNamespace(GAIN_6=6),
                                 EegSignalSource=SimpleNamespace(NORMAL="NORMAL"))
    source._client = SimpleNamespace(start_data_stream=Mock(), negotiate_eeg_stream=Mock(),
                                    enable_eeg_stream_mode=Mock(side_effect=RuntimeError("ack mismatch")))
    monkeypatch.setattr(source, "_run_sdk_call", lambda fn, *a: fn(*a))
    wait = Mock()
    monkeypatch.setattr(source, "_wait_for_samples", wait)
    with pytest.raises(RuntimeError, match="ack mismatch"):
        source._start_stream_unified("parser")
    source._client.negotiate_eeg_stream.assert_not_called()
    source._client.start_data_stream.assert_called_once_with("parser")
    wait.assert_not_called()


@pytest.mark.parametrize("outcomes,expected", [([0], 0), ([1, 0], 0), ([1, 1, 1, 1, 1], 1), ([2], 2), (["timeout"], 2), (["crash"], 2)])
def test_all_isolates_attempts_stops_after_success_or_uncertain_cleanup(tmp_path, monkeypatch, outcomes, expected):
    import json
    import subprocess
    import zipfile
    from pathlib import Path
    calls = []
    def run(command, **kwargs):
        assert kwargs["timeout"] == 180
        assert command[0] == diagnostic.sys.executable
        calls.append(command[command.index("--mode") + 1])
        if len(calls) > 1:
            assert command[command.index("--host") + 1] == "192.0.2.1"
            assert command[command.index("--port") + 1] == "9000"
        outcome = outcomes[len(calls) - 1]
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(command, 150)
        if outcome == "crash":
            return SimpleNamespace(returncode=99)
        directory = Path(command[command.index("--log-dir") + 1])
        (directory / "result.json").write_text(json.dumps({"target": "192.0.2.1:9000",
            "status": {0: "samples_received", 1: "failed", 2: "cleanup_failed"}[outcome]}))
        return SimpleNamespace(returncode=outcome)
    monkeypatch.setattr(diagnostic.subprocess, "run", run)
    monkeypatch.setattr(diagnostic.time, "sleep", lambda _: None)
    assert diagnostic.main(["--mode", "all", "--log-dir", str(tmp_path)]) == expected
    assert calls == list(diagnostic.MODES[:len(outcomes)])
    with zipfile.ZipFile(next(tmp_path.glob("*.zip"))) as bundle:
        summary = json.loads(bundle.read("summary.json"))
        assert summary["exit_code"] == expected
        assert len(summary["attempts"]) == len(outcomes)


@pytest.mark.parametrize("kind", ["valid", "empty", "nan", "wrong_channels", "stall", "slow"])
def test_observation_requires_sustained_valid_samples_and_keeps_preview(tmp_path, monkeypatch, kind):
    import numpy as np
    clock = [0.0]
    monkeypatch.setattr(diagnostic.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(diagnostic.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    def read():
        count = 5
        if kind == "empty" or kind == "stall" and clock[0] > 1:
            count = 0
        elif kind == "slow":
            count = 1
        return np.full((31 if kind == "wrong_channels" else 32, count),
                       np.nan if kind == "nan" else 1.0), None
    source = SimpleNamespace(get_new_samples=read, metadata=SimpleNamespace(sfreq=250),
                             _callback_sample_count=0, _raw_packet_count=0)
    if kind == "valid":
        result = diagnostic.observe_samples(source, tmp_path, seconds=4)
        assert result["observed_hz"] == pytest.approx(250)
        with np.load(tmp_path / "eeg-preview.npz") as preview:
            assert preview["eeg"].shape == (32, result["samples"])
    else:
        with pytest.raises(RuntimeError):
            diagnostic.observe_samples(source, tmp_path, seconds=4)


@pytest.mark.parametrize("failed", [None, "format", "config", "start"])
def test_stepwise_stops_at_failed_command_and_never_claims_samples(failed, monkeypatch):
    calls = []
    def command(name):
        def run(*args):
            calls.append(name)
            if name == failed:
                raise RuntimeError("ack mismatch")
            return 7
        return run
    source = StepwiseBrainCo()
    source._sdk = SimpleNamespace(set_cfg=Mock(), clear_eeg_buffer=Mock(),
                                 EegSampleRate=SimpleNamespace(SR_250Hz=250),
                                 EegSignalGain=SimpleNamespace(GAIN_6=6),
                                 EegSignalSource=SimpleNamespace(NORMAL="NORMAL"))
    source._client = SimpleNamespace(start_data_stream=command("connect"),
                                    negotiate_eeg_stream=command("format"),
                                    set_eeg_config=command("config"), start_eeg_stream=command("start"))
    monkeypatch.setattr(source, "_run_sdk_call", lambda fn, *a: fn(*a))
    wait = Mock()
    monkeypatch.setattr(source, "_wait_for_samples", wait)
    if failed:
        with pytest.raises(RuntimeError, match="ack mismatch"):
            source._start_stream_unified("parser")
        assert calls == ["connect", "format", "config", "start"][:["connect", "format", "config", "start"].index(failed)+1]
        wait.assert_not_called()
    else:
        source._start_stream_unified("parser")
        assert calls == ["connect", "format", "config", "start"]
        wait.assert_called_once()


def test_unified_error_preserves_stage_address_and_original_cause(monkeypatch, caplog):
    import sys
    sdk = SimpleNamespace(__version__="2.1.2", BCIGoClient=Mock(return_value=Mock()),
                          MessageParser=Mock(), MsgType=SimpleNamespace(BCIGo=1))
    monkeypatch.setitem(sys.modules, "bcigo_sdk", sdk)
    source = BrainCoAcquirer(brainco_addr="192.0.2.1", brainco_port=9000,
                            auto_discover=False, start_retries=1)
    monkeypatch.setattr(source, "_start_loop_thread", lambda: None)
    monkeypatch.setattr(source, "_run_sdk_call", lambda fn, *a: fn(*a))
    monkeypatch.setattr(source, "_register_sdk_callbacks", lambda: None)
    stop = Mock()
    monkeypatch.setattr(source, "stop_stream", stop)
    def fail(parser):
        source._startup_step("SDK 一键启动 EEG")
        raise RuntimeError("EEG mode acknowledgement mismatch: expected 1, got 0")
    monkeypatch.setattr(source, "_start_stream_unified", fail)
    with pytest.raises(RuntimeError, match="192.0.2.1:9000") as error:
        source.start_stream()
    assert "SDK 一键启动 EEG" in str(error.value)
    assert "expected 1, got 0" in str(error.value.__cause__)
    assert any(record.exc_info for record in caplog.records)
    stop.assert_called_once()


@pytest.fixture
def verified_source(monkeypatch):
    import json
    import logging
    source = diagnostic.VerifiedConfigBrainCo()
    source._ready_timeout_sec = .03
    source._sdk = SimpleNamespace(set_cfg=Mock(), clear_eeg_buffer=Mock(),
                                 EegSampleRate=SimpleNamespace(SR_250Hz=250),
                                 EegSignalGain=SimpleNamespace(GAIN_6=6),
                                 EegSignalSource=SimpleNamespace(NORMAL="NORMAL"))
    monkeypatch.setattr(source, "_run_sdk_call", lambda fn, *a: fn(*a))
    monkeypatch.setattr(source, "_wait_for_samples", Mock())
    expected = dict(freq="EEG_SR_250Hz", gain="EEG_GAIN_6", source="NORMAL")
    counter = [10]
    def response(config=None, error=None, explicit_mode=False, unrelated=False, return_id=True, log_id=True):
        counter[0] += 1
        ident = counter[0]
        if log_id:
            logging.getLogger("bcigo_sdk.proto.bcigo.msg_builder.bcigo_msg_builder").info(
                "encode_app_to_mcu: %s", json.dumps(json.dumps(dict(msgId=ident, eeg=dict(configReq=dict(value=True))))))
        eeg = dict(config=dict(expected if config is None else config))
        if explicit_mode:
            eeg["mode"] = "EEG_MODE_UNSPECIFIED"
        source._handle_message_response_callback("bcigo", json.dumps(dict(Mcu2App=dict(msgId=ident+1 if unrelated else ident, eeg=eeg))))
        if error:
            raise RuntimeError(error)
        return ident if return_id else ()
    source._client = SimpleNamespace(start_data_stream=Mock(), stop_leadoff_check=Mock(),
                                    stop_eeg_stream=Mock(), start_eeg_stream=Mock(),
                                    get_eeg_config=Mock(side_effect=response), set_eeg_config=Mock())
    return source, response, expected


def test_verified_config_skips_write_when_independent_readback_matches(verified_source):
    source, _, _ = verified_source
    source._start_stream_unified("parser")
    source._client.set_eeg_config.assert_not_called()
    source._client.start_eeg_stream.assert_called_once()
    source._wait_for_samples.assert_called_once()
    assert len(source.config_evidence) == 1


@pytest.mark.parametrize("bad_readback", [False, True])
def test_known_config_error_requires_fresh_matching_readback(verified_source, caplog, bad_readback):
    import logging
    caplog.set_level(logging.INFO)
    source, response, expected = verified_source
    wrong = dict(expected, freq="EEG_SR_500Hz")
    reads = iter([wrong, wrong if bad_readback else expected])
    source._client.get_eeg_config.side_effect = lambda: response(next(reads), return_id=False)
    source._client.set_eeg_config.side_effect = lambda *a: response(error="EEG mode acknowledgement mismatch: expected 1, got 0")
    if bad_readback:
        with pytest.raises(RuntimeError, match="配置读回不一致"):
            source._start_stream_unified("parser")
        source._client.start_eeg_stream.assert_not_called()
    else:
        source._start_stream_unified("parser")
        source._client.start_eeg_stream.assert_called_once()
        assert source.config_evidence[1]["sdk_error"] == "EEG mode acknowledgement mismatch: expected 1, got 0"
    assert source._client.get_eeg_config.call_count == 2


@pytest.mark.parametrize("case", ["other_error", "explicit_mode", "unrelated", "no_id", "stale"])
def test_readback_never_accepts_unverified_responses(verified_source, caplog, case):
    import logging
    caplog.set_level(logging.INFO)
    source, response, expected = verified_source
    if case == "other_error":
        action = lambda: response(error="connection lost")
    elif case == "explicit_mode":
        action = lambda: response(error="EEG mode acknowledgement mismatch: expected 1, got 0", explicit_mode=True)
    elif case == "unrelated":
        action = lambda: response(unrelated=True)
    elif case == "no_id":
        action = lambda: response(return_id=False, log_id=False)
    else:
        ident = response()
        action = lambda: ident
    with pytest.raises(RuntimeError):
        source._request_response("test", action, allow_config_mismatch=True)
    assert not source.config_evidence


def test_start_error_is_not_suppressed_after_readback(verified_source):
    source, _, _ = verified_source
    source._client.start_eeg_stream.side_effect = RuntimeError("EEG mode acknowledgement mismatch: expected 1, got 0")
    with pytest.raises(RuntimeError, match="acknowledgement mismatch"):
        source._start_stream_unified("parser")
    source._wait_for_samples.assert_not_called()


def test_readback_waits_for_delayed_callback(verified_source):
    import threading
    source, _, expected = verified_source
    timer = None
    def request():
        nonlocal timer
        timer = threading.Timer(.005, lambda: source._handle_message_response_callback(
            {"Mcu2App": {"msgId": 42, "eeg": {"config": expected}}}))
        timer.start()
        return 42
    try:
        assert source._request_response("test", request) == expected
    finally:
        timer.join()
