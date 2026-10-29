"""Package-local device adapters. Display transforms never enter this layer."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path

import numpy as np

from neuroscope_eeg.core.models import EEGChunk, SourceMetadata
from neuroscope_eeg.profile_config import validate_profile
from neuroscope_eeg.timing.models import HardwareTriggerSample


def read_profile(path: str = "") -> dict:
    if not path.strip():
        return {}
    profile = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(profile, dict):
        raise ValueError("设备配置必须是 JSON 对象")  # noqa: TRY004 - user configuration validation
    return validate_profile(profile)


def metadata(kind, sfreq, n, profile=None, *, names=None, types=None, extra=None):
    p = validate_profile(profile or {})
    channel_names = tuple(p.get("channel_names", names or [f"CH{i+1}" for i in range(n)]))
    channel_types = tuple(p.get("channel_types", types or ["eeg"] * n))
    units = tuple(p.get("channel_units", ["unknown"] * n))
    if any(len(x) != n for x in (channel_names, channel_types, units)):
        raise ValueError("设备配置的通道名称、类型、单位必须与接收通道数一致")
    if len(set(channel_names)) != n:
        raise ValueError("通道名称不能重复")
    return SourceMetadata(
        str(p.get("device_id") or kind), kind, sfreq, channel_names, channel_types, units,
        {**p, "profile_confirmed": p.get("confirmed") is True, **(extra or {})},
    )


class NeuracleSource:
    stale_timeout_sec = 5.0

    def __init__(self, host="127.0.0.1", port=8712, sfreq=1000, n_channels=64, profile=None):
        self.host, self.port, self.sfreq = host, port, sfreq
        self.n_channels, self.profile = n_channels, profile or {}
        self.metadata = metadata("neuracle", sfreq, n_channels, {"device_id": self.profile.get("device_id", "neuracle")})
        self.server = None
        self._sample = 0
        self._triggers = []
        self._last_codes = {}

    def start(self):
        from neuroscope_eeg.acquisition.vendor.collect.neuracle_api import DataServerThread
        self.server = DataServerThread(
            sample_rate=int(self.sfreq), t_buffer=30, enable_save_buffer=False, record_timestamps=False
        )
        self.server.stream_error = None
        if self.server.connect(hostname=self.host, port=self.port):
            raise RuntimeError("无法连接 Neuracle/JellyFish 转发服务")
        deadline = time.monotonic() + 15
        while not self.server.isReady():
            if getattr(self.server, "stream_error", None):
                raise RuntimeError(self.server.stream_error)
            if time.monotonic() > deadline:
                raise RuntimeError("等待 Neuracle 元数据超时")
            time.sleep(.05)
        names = tuple(self.server.channelNames)
        types = tuple("stim" if str(t).upper() in {"TRG", "TRIG", "TRIGGER", "STIM", "MARKER", "EVENT"}
                      else str(t).lower() for t in self.server.channelTypes)
        if len(names) != len(types) or types.count("eeg") != self.n_channels:
            raise RuntimeError(f"Neuracle 转发了 {types.count('eeg')} 个 EEG 通道，界面填写 {self.n_channels} 个；"
                               "请填写 EEG 通道数（不含 TRG），辅助通道会一起保存")
        rates = self.server.srates
        if any(abs(float(rates[i]) - self.sfreq) > .01 for i, t in enumerate(types) if t == "eeg"):
            raise RuntimeError("Neuracle 实际 EEG 采样率与设置不一致，不进行隐式重采样")
        profile = self.profile.copy()
        # Optional auxiliary channels are announced only after connecting.
        if profile.get("channel_units") and len(profile["channel_units"]) != len(names):
            raise ValueError("设备配置需包含服务端辅助通道的单位，请核对转发通道列表")
        self.metadata = metadata("neuracle", self.sfreq, len(names), profile, names=names, types=types,
                                 extra={"timestamp_basis": "host_sample_counter", "device_model": self.server.moduleName,
                                        "native_sample_rates": list(rates), "loss_detection": "forwarder_packet_timestamp"})
        # The protocol metadata, not a profile, owns channel order/type.
        if self.metadata.channel_names != names or self.metadata.channel_types != types:
            raise ValueError("Neuracle 配置不能重命名或重排服务端通道，请按实际元数据填写")
        self._sample = 0
        self._triggers.clear()
        self._last_codes.clear()
        self.server.start()

    def stop(self):
        if self.server is not None:
            self.server.stop()
            self.server = None

    def read_chunk(self):
        if self.server.stream_error:
            raise RuntimeError(self.server.stream_error)
        data = np.asarray(self.server.buffer.getUpdate(), dtype=np.float32).copy()
        seq = self._sample
        self._sample += data.shape[1]
        for c, kind in enumerate(self.metadata.channel_types):
            if kind != "stim":
                continue
            last = self._last_codes.get(c, 0)
            for i, value in enumerate(data[c]):
                code = int(value) if np.isfinite(value) else 0
                if code and code != last:
                    self._triggers.append(HardwareTriggerSample(code, seq+i, self.metadata.channel_names[c]))
                last = code
            self._last_codes[c] = last
        indices = np.arange(seq, self._sample, dtype=np.int64)
        return EEGChunk(self.metadata, data, indices / self.sfreq, seq, indices,
                        np.all(np.isfinite(data), axis=0), received_at=time.monotonic())

    def drain_hardware_triggers(self):
        result, self._triggers = tuple(self._triggers), []
        return result


class DemoSource:
    """Adapts the authoritative demo's BrainCo and LSL backends."""
    stale_timeout_sec = 5.0

    def __init__(self, backend, kind, profile=None):
        self.backend, self.kind, self.profile = backend, kind, profile or {}
        self.metadata = metadata(kind, backend.metadata.sfreq, backend.metadata.n_channels, profile)
        self._sample = 0
        self._last_timestamp = None

    def start(self):
        self.backend.start_stream()
        self._sample = 0
        extra = {"timestamp_basis": "lsl_remote" if self.kind == "lsl" else "host_sample_counter",
                 "loss_detection": "timestamps" if self.kind == "lsl" else "unavailable_sdk_packet_sequence",
                 "adapter_reference": "acq-task-eeg-demo-main"}
        if self.kind == "lsl":
            if self.backend.stream_identity["channels"] != self.metadata.n_channels:
                raise RuntimeError("LSL 实际通道数与配置不一致，不静默丢弃额外通道")
            extra["stream_identity"] = self.backend.stream_identity
            self._correction = float(self.backend._inlet.time_correction(timeout=2.0))
            extra["timestamp_basis"] = "lsl_local_corrected"
        else:
            from importlib.metadata import version
            extra["sdk_version"] = version("bcigo-sdk")
        self.metadata = metadata(self.kind, self.metadata.sfreq, self.metadata.n_channels, self.profile, extra=extra)

    def stop(self):
        self.backend.stop_stream()

    def read_chunk(self):
        data, raw_ts = self.backend.get_new_samples()
        data = np.asarray(data, dtype=np.float32)
        indices = np.arange(self._sample, self._sample + data.shape[1], dtype=np.int64)
        aux = {}
        if self.kind == "lsl":
            ts = np.asarray(raw_ts) + self._correction
            aux = {"lsl_raw_timestamps": np.asarray(raw_ts), "lsl_clock_correction": np.asarray(self._correction)}
            if len(ts):
                joined = ts if self._last_timestamp is None else np.r_[self._last_timestamp, ts]
                if np.any(np.diff(joined) <= 0) or np.any(np.diff(joined) > 2.5/self.metadata.sfreq):
                    raise RuntimeError("LSL 时间轴中断，不能拼接为连续 EEG；请新建记录")
                self._last_timestamp = ts[-1]
        else:
            ts = indices / self.metadata.sfreq
            # SDK event_seq is an event sequence, NOT a stimulus code.
            triggers = [asdict(e) for e in self.backend.pop_trigger_events()]
            if triggers:
                aux["brainco_trigger_events_json"] = np.asarray(json.dumps(triggers))
        seq = self._sample
        self._sample += data.shape[1]
        return EEGChunk(self.metadata, data, ts, seq, indices, np.all(np.isfinite(data), axis=0), aux,
                        time.monotonic())


def brainco_source(sfreq=250, n_channels=32, addr="", port=0, auto=True, profile=None):
    from neuroscope_eeg.acquisition.vendor.brainco_acquirer import BrainCoAcquirer
    return DemoSource(BrainCoAcquirer(sfreq=sfreq, n_channels=n_channels, brainco_addr=addr,
                                     brainco_port=port, auto_discover=auto), "brainco", profile)


def lsl_source(sfreq=250, n_channels=32, source_id="", profile=None):
    from neuroscope_eeg.acquisition.vendor.lsl_acquirer import LSLAcquirer
    return DemoSource(LSLAcquirer(sfreq=sfreq, n_channels=n_channels, source_id=source_id), "lsl", profile)


class OmniBCISource:
    stale_timeout_sec = 5.0

    def __init__(self, endpoint, device_type="esp32", profile=None, sdk=None):
        self.endpoint, self.device_type, self.profile, self.sdk = endpoint, device_type, profile or {}, sdk
        n = 32 if device_type == "stm32" else 8
        p = {"channel_units": ["uV"] * n, **self.profile}
        if p["channel_units"] != ["uV"] * n:
            raise ValueError("OmniBCI eeg_uv 固定使用微伏，不允许通过配置改写单位")
        self.metadata = metadata("omnibci", 250, n, p)
        self.board = None
        self._sample = 0
        self._last_index = None
        self._fatal = None

    def start(self):
        if self.sdk is None:
            try:
                import omnibci
            except ImportError as exc:
                raise RuntimeError("请安装 vendor_sdk/omnibci 中的公司 SDK wheel") from exc
            self.sdk = omnibci
        self.board = self.sdk.Board.connect(self.endpoint, device_type=self.device_type)
        config = self.board.get_config()
        if getattr(config, "verified", False) is not True:
            raise RuntimeError("OmniBCI 前端配置尚未验证，请先用厂商工具确认配置")
        if getattr(config, "mode", None) not in {"eeg", "both_bias", "no_bias"}:
            raise RuntimeError(
                f"OmniBCI 前端模式 {getattr(config, 'mode', None)!r} 不用于被试 EEG 采集；"
                "请在厂商工具中确认并切换 EEG 模式，不能使用 test 测试信号或 shorted 短接模式"
            )
        self.metadata = metadata("omnibci", 250, self.metadata.n_channels,
            {"channel_units": ["uV"] * self.metadata.n_channels, **self.profile}, extra={
                "sdk_version": self.sdk.__version__, "sdk_revision": getattr(self.sdk, "SDK_REVISION", "unknown"),
                "native_sdk_version": getattr(self.sdk, "SDK_VERSION", "unknown"),
                "device_model": self.device_type, "endpoint": self.endpoint,
                "frontend_config": asdict(config) if is_dataclass(config) else str(config),
                "timestamp_basis": "device_sample_indices", "loss_detection": "sdk_valid_and_sample_indices"})
        self.board.start()

    def stop(self):
        board, self.board = self.board, None
        if board is not None:
            try:
                board.stop()
            finally:
                board.close()

    def read_chunk(self):
        if self._fatal:
            raise RuntimeError(self._fatal)
        try:
            batch = self.board.read(timeout=.2)
        except self.sdk.OmniBCIError as exc:
            batch = getattr(exc, "partial", None)
            if batch is None:
                if isinstance(exc, self.sdk.DeviceTimeoutError):
                    return EEGChunk(self.metadata, np.empty((self.metadata.n_channels, 0)), np.empty(0), self._sample)
                raise
            self._fatal = str(exc) or type(exc).__name__  # consumed partial samples must reach the writer first
        indices = np.asarray(batch.sample_indices, dtype=np.int64)
        if batch.sample_rate_hz != self.metadata.sfreq or np.asarray(batch.eeg_uv).shape[1] != self.metadata.n_channels:
            raise RuntimeError("OmniBCI 实际采样率或通道数发生变化")
        if len(indices):
            joined = indices if self._last_index is None else np.r_[self._last_index, indices]
            if np.any(np.diff(joined) != 1) or not np.all(batch.valid):
                self._fatal = "OmniBCI 报告丢样或无效样本，保留原始数据并结束本段"
            self._last_index = indices[-1]
        aux = {k: np.asarray(getattr(batch, k)) for k in (
            "raw_counts", "sequence", "status", "mode", "source_timestamp_us", "source_timestamp_valid")}
        aux["generation"] = np.asarray(batch.generation)
        aux["triggers_json"] = np.asarray(json.dumps([
            asdict(e) if is_dataclass(e) else str(e) for e in self.board.read_triggers()
        ], default=str))
        seq = self._sample
        self._sample += len(indices)
        return EEGChunk(self.metadata, np.asarray(batch.eeg_uv).T, indices / 250.0, seq,
                        indices, batch.valid, aux, batch.received_at)


class ExternalEmotivSource:
    """Event-only run. No generated EEG samples or fictional connection status."""
    metadata = SourceMetadata("emotiv", "emotiv_external", 1.0, (), (), (),
                              {"external_recording": True, "timestamp_basis": "external_edf_pending"})

    def start(self):
        pass

    def stop(self):
        pass

    def read_chunk(self):
        time.sleep(.02)
        return EEGChunk(self.metadata, np.empty((0, 0)), np.empty(0), 0)
