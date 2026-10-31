"""Verified configuration startup, shared by desktop and diagnostics."""
import json
import logging
import threading
import time

LOG = logging.getLogger(__name__)


class OutgoingMessages(logging.Handler):
    """Capture the SDK's logged request IDs when a public getter returns no ID."""

    def __init__(self):
        super().__init__()
        self.ids = []

    def emit(self, record):
        message = record.getMessage()
        if not record.name.startswith("bcigo_sdk.") or not message.startswith("encode_app_to_mcu: "):
            return
        try:
            payload = json.loads(message.split(": ", 1)[1])
            if isinstance(payload, str):
                payload = json.loads(payload)
            ident = payload.get("msgId")
            if type(ident) is int and ident > 0:
                self.ids.append(ident)
        except (ValueError, AttributeError, TypeError):
            pass


class VerifiedConfigStartup:
    """SDK 2.1.2 startup using independently correlated configuration readback."""

    def _init_config_verification(self):
        self._diagnostic_responses = []
        self._diagnostic_condition = threading.Condition()
        self.config_evidence = []

    def _record_config_response(self, *args):
        for value in args:
            try:
                payload = json.loads(value) if isinstance(value, (str, bytes, bytearray)) else value
                body = payload.get("Mcu2App") if isinstance(payload, dict) else None
                if (isinstance(body, dict) and type(body.get("msgId")) is int
                        and isinstance(body.get("eeg"), dict) and isinstance(body["eeg"].get("config"), dict)):
                    with self._diagnostic_condition:
                        self._diagnostic_responses.append(body)
                        self._diagnostic_condition.notify_all()
            except (ValueError, TypeError):
                continue

    def _step(self, label, method, *args):
        self._startup_step(label)
        result = self._run_sdk_call(method, *args)
        LOG.info("Step returned: %s result=%r", label, result)
        return result

    def _request_response(self, label, method, *args, allow_config_mismatch=False):
        with self._diagnostic_condition:
            marker = len(self._diagnostic_responses)
        outgoing = OutgoingMessages()
        logging.getLogger().addHandler(outgoing)
        sdk_logger = logging.getLogger("bcigo_sdk")
        previous_level = sdk_logger.level
        sdk_logger.setLevel(logging.INFO)
        error = None
        returned = None
        try:
            returned = self._step(label, method, *args)
        except RuntimeError as exc:
            if not allow_config_mismatch or str(exc) != "EEG mode acknowledgement mismatch: expected 1, got 0":
                raise
            error = str(exc)
            LOG.exception("Known config acknowledgement error retained; independent verification required")
        finally:
            logging.getLogger().removeHandler(outgoing)
            sdk_logger.setLevel(previous_level)
        ident = returned if type(returned) is int and returned > 0 else None
        ids = set(outgoing.ids)
        if ident is not None and ids and ids != {ident}:
            raise RuntimeError(f"{label}：SDK 返回 ID 与发送日志不一致")
        if ident is None and len(ids) == 1:
            ident = ids.pop()
        if ident is None:
            raise RuntimeError(f"{label}：无法确定请求 msgId，不接受无法关联的回复")
        deadline = time.monotonic() + self._ready_timeout_sec
        with self._diagnostic_condition:
            while True:
                for body in self._diagnostic_responses[marker:]:
                    if (body["msgId"] == ident and isinstance(body.get("eeg"), dict)
                            and isinstance(body["eeg"].get("config"), dict)):
                        eeg = body["eeg"]
                        if error and "mode" in eeg:
                            raise RuntimeError("配置错误回复包含显式 mode；不适用缺字段兼容路径")
                        self.config_evidence.append(dict(label=label, msgId=ident, eeg=eeg, sdk_error=error))
                        LOG.warning("Correlated device config evidence: %s", self.config_evidence[-1])
                        return eeg["config"]
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError(f"{label}：未收到 msgId={ident} 的配置回复")
                self._diagnostic_condition.wait(min(remaining, .1))

    def _start_stream_verified(self, parser):
        sdk, client = self._sdk, self._client
        sdk.set_cfg(max(int(self.metadata.sfreq * 60), 1024), max(256, int(self.metadata.sfreq)), 256)
        sdk.clear_eeg_buffer()
        self._step("建立连接并完成 SDK 内置握手", client.start_data_stream, parser)
        self._step("停止阻抗检测", client.stop_leadoff_check)
        self._step("停止 EEG，确认配置前状态", client.stop_eeg_stream)
        expected = dict(freq=f"EEG_SR_{int(self.metadata.sfreq)}Hz", gain=f"EEG_GAIN_{self._eeg_gain}", source=self._signal_source)
        def matches(config):
            return all(config.get(key) == value for key, value in expected.items())
        config = self._request_response("独立读取当前 EEG 配置", client.get_eeg_config)
        if not matches(config):
            self._request_response("设置 EEG 配置并核对回复", client.set_eeg_config,
                                   getattr(sdk.EegSampleRate, f"SR_{int(self.metadata.sfreq)}Hz"),
                                   getattr(sdk.EegSignalGain, f"GAIN_{self._eeg_gain}"),
                                   getattr(sdk.EegSignalSource, self._signal_source),
                                   allow_config_mismatch=True)
            config = self._request_response("独立读回修改后的 EEG 配置", client.get_eeg_config)
            if not matches(config):
                raise RuntimeError(f"配置读回不一致：expected={expected}, actual={config}")
        else:
            LOG.warning("Device readback already matches requested config; no config write needed")
        sdk.clear_eeg_buffer()
        self._first_sample_event.clear()
        self._step("配置已核实，启动真实 EEG", client.start_eeg_stream)
        self._startup_step("诊断：等待配置核实后的实际 EEG")
        self._wait_for_samples()
