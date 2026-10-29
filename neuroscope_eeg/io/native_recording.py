"""Append-only native recordings; independent of EDF quantization and display filters."""
from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from queue import Full, Queue

import numpy as np

from neuroscope_eeg.core.models import EEGChunk
from neuroscope_eeg.io.edf_paths import edf_path
from neuroscope_eeg.io.session_recorder import _PARADIGM_SLUGS, RecordingError
from neuroscope_eeg.profile_config import validate_profile
from neuroscope_eeg.project_metadata import validate_metadata, validate_unique_name
from neuroscope_eeg.provenance import implementation_snapshot

SOFTWARE = {"name": "NeuroScope", "version": "0.4.0"}


def json_value(value):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def write_json(path, value):
    path = Path(edf_path(path))
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=json_value), encoding="utf-8")
    tmp.replace(path)


def utc_now():
    return datetime.now(UTC).isoformat()


def validate_identity(participant, code, unique_name):
    if re.fullmatch(r"[0-9]{8}", participant) is None:
        raise ValueError("被试编号必须是人员平台的 8 位数字；保留前导零")
    if re.fullmatch(r"[A-Z]{1,6}-[0-9]{8}", code) is None:
        raise ValueError("请填写实际已登记范式代码：1–6 位大写字母-YYYYMMDD")
    try:
        datetime.strptime(code.split("-")[1], "%Y%m%d")
    except ValueError as exc:
        raise ValueError("范式代码中的日期无效") from exc
    validate_unique_name(unique_name)


class NativeRecorder:
    def __init__(self, *, root_dir, participant_id, paradigm, preset, metadata,
                 paradigm_code, unique_name, source_sample_offset=0, config=None):
        validate_identity(participant_id.strip(), paradigm_code.strip(), unique_name.strip())
        config = dict(config or {})
        allowed = {"experiment_metadata", "display", "profile", "assessment_protocol", "delivery", "emotiv_operator_confirmed", "emotiv_receiving_port", "paradigm", "preset"}
        if set(config) - allowed:
            raise ValueError("未知采集配置字段：" + ", ".join(sorted(set(config) - allowed)))
        if "profile" in config:
            validate_profile(config["profile"])
        delivery = config.get("delivery", {})
        if not isinstance(delivery, dict) or set(delivery) - {"allow_estimated_timing"} or ("allow_estimated_timing" in delivery and type(delivery["allow_estimated_timing"]) is not bool):
            raise ValueError("导出配置字段或类型无效")
        experiment = config.get("experiment_metadata")
        if experiment is None:
            if metadata.source_type not in {"simulated", "simulator", "replay", "npz_replay"}:
                raise ValueError("正式记录请先建立或导入实验信息")
            experiment = {"full_name": paradigm + "模拟流程", "unique_name": unique_name.strip(), "description": "仅验证软件流程，非正式实验身份"}
        experiment = validate_metadata(experiment)
        if experiment["unique_name"] != unique_name.strip():
            raise ValueError("目录名称必须来自本次实验信息")
        config["experiment_metadata"] = experiment
        provenance = implementation_snapshot()
        self.metadata, self.sfreq = metadata, metadata.sfreq
        self.source_sample_offset = int(source_sample_offset)
        self.error = None
        self._submitted = 0
        self._written = 0
        self._invalid = 0
        self._last_index = None
        self._last_timestamp = None
        self._continuity = []
        self._lock = threading.RLock()
        self._queue = Queue(maxsize=1024)
        self._queued_samples = 0
        self._stopped = False
        self._accepting = True
        session_id = uuid.uuid4().hex
        root = Path(edf_path(Path(root_dir).expanduser()))
        for folder in ("data", "Reports", "Records"):
            (root / folder).mkdir(parents=True, exist_ok=True)
        self.session_dir = root / "Records" / ("recording-" + session_id)
        self.session_dir.mkdir(parents=True, exist_ok=False)
        (self.session_dir / "raw").mkdir()
        self.run = {
            "storage_layout_version": 2, "native_schema_version": 1, "participant_id": participant_id.strip(), "session_id": session_id,
            "paradigm_code": paradigm_code.strip(), "unique_name": unique_name.strip(), "paradigm": paradigm,
            "task": _PARADIGM_SLUGS[paradigm].replace("_", ""), "preset": preset,
            "started_at": utc_now(), "ended_at": None, "recording_status": "recording", "stop_reason": "",
            "acquisition_software": SOFTWARE, "source_sample_offset": self.source_sample_offset,
            "external_recording": metadata.source_type == "emotiv_external",
            "simulated": metadata.source_type in {"simulated", "simulator", "replay", "npz_replay"},
            "bids_validated": False,
        }
        write_json(self.session_dir / "provenance.json", provenance)
        write_json(self.session_dir / "config.json", {"paradigm": paradigm, "preset": preset, **(config or {})})
        write_json(self.session_dir / "device.json", {
            "source_id": metadata.source_id, "source_type": metadata.source_type, "sfreq": metadata.sfreq,
            "channel_names": metadata.channel_names, "channel_types": metadata.channel_types,
            "channel_units": metadata.channel_units, "extra": dict(metadata.extra),
        })
        self._handles = {name: (self.session_dir / name).open("x", encoding="utf-8", newline="")
                         for name in ("events.jsonl", "triggerbox_log.jsonl", "hardware_triggers.jsonl", "sidecars.jsonl", "run.log")}
        self._raw = {name: (self.session_dir / "raw" / name).open("xb")
                     for name in ("eeg.f32", "timestamps.f64", "sample_indices.i64", "valid.u8")}
        self._chunklog = (self.session_dir / "raw/chunks.jsonl").open("x", encoding="utf-8")
        self._aux_handles = {}
        self._persist()
        self._handles["run.log"].write(f"{utc_now()} recording initialized {session_id}\n")
        self._handles["run.log"].flush()
        self._thread = threading.Thread(target=self._writer, name="neuroscope-native-writer", daemon=True)
        self._thread.start()

    @classmethod
    def start(cls, **kwargs):
        return cls(**kwargs)

    @property
    def submitted_samples(self):
        with self._lock:
            return self._submitted

    def submit(self, chunk):
        if chunk.metadata != self.metadata:
            raise RecordingError("采样率或通道配置发生变化，须新建记录")
        with self._lock:
            self._check()
            if self._queued_samples + chunk.n_samples > self.sfreq * 10:
                self.error = "写盘积压超过 10 秒，停止记录并保留已写入的数据"
                raise RecordingError(self.error)
            copied = EEGChunk(chunk.metadata, chunk.data.copy(), chunk.timestamps.copy(), chunk.sequence,
                              None if chunk.sample_indices is None else chunk.sample_indices.copy(),
                              None if chunk.valid is None else chunk.valid.copy(),
                              {k: np.asarray(v).copy() for k, v in chunk.auxiliaries.items()}, chunk.received_at)
            try:
                self._queue.put_nowait(copied)
            except Full as exc:
                self.error = "写盘队列已满"
                raise RecordingError(self.error) from exc
            self._submitted += chunk.n_samples
            self._queued_samples += chunk.n_samples

    def _check(self):
        if self.error or not self._accepting:
            raise RecordingError(self.error or "记录已结束")

    def _append(self, name, value):
        with self._lock:
            self._check()
            handle = self._handles[name]
            try:
                handle.write(json.dumps(value, ensure_ascii=False, default=json_value) + "\n")
                handle.flush()
            except (OSError, TypeError, ValueError) as exc:
                self.error = f"事件/辅助记录写入失败：{exc}"
                raise RecordingError(self.error) from exc

    def record_event(self, event, *, eeg_sample_index, eeg_session_sec, lsl_time=None):
        # The cursor is an estimate, never a hardware-aligned sample index.
        self._append("events.jsonl", {**asdict(event), "sample_cursor": eeg_sample_index,
                     "cursor_sec": eeg_session_sec, "lsl_time": lsl_time,
                     "alignment_status": "external_pending" if self.run["external_recording"] else "software_cursor_unverified"})
        if event.phase == "start":
            self.run["protocol_start_payload"] = dict(event.payload)

    def record_trigger_dispatch(self, dispatch):
        self._append("triggerbox_log.jsonl", dispatch.as_dict())

    def configure_trigger_timing(self, **kwargs):
        self.run["trigger_timing"] = {**kwargs, "physical_onset_calibrated": False}
        self._persist()

    def submit_hardware_triggers(self, samples):
        for sample in samples:
            self._append("hardware_triggers.jsonl", asdict(sample))

    def submit_sidecars(self, sidecars):
        # Includes original TD10 timestamps, quality values and clock corrections.
        self._append("sidecars.jsonl", sidecars)

    def _writer(self):
        try:
            while True:
                chunk = self._queue.get()
                if chunk is None:
                    break
                self._write_chunk(chunk)
                with self._lock:
                    self._queued_samples -= chunk.n_samples
        except Exception as exc:  # noqa: BLE001 - writer failures must remain visible to acquisition
            with self._lock:
                self.error = f"原始数据写盘失败：{exc}"

    def _write_chunk(self, chunk):
        n = chunk.n_samples
        indices = chunk.sample_indices
        if indices is None:
            indices = np.arange(chunk.sequence, chunk.sequence+n, dtype=np.int64)
        valid = np.all(np.isfinite(chunk.data), axis=0)
        if chunk.valid is not None:
            valid &= chunk.valid
        if n:
            joined = indices if self._last_index is None else np.r_[self._last_index, indices]
            if np.any(np.diff(joined) != 1):
                self._continuity.append({"offset": self._written, "reason": "sample_index_gap"})
            joined_ts = chunk.timestamps if self._last_timestamp is None else np.r_[self._last_timestamp, chunk.timestamps]
            if not np.all(np.isfinite(joined_ts)) or np.any(np.diff(joined_ts) <= 0):
                self._continuity.append({"offset": self._written, "reason": "invalid_timestamps"})
            self._last_index, self._last_timestamp = int(indices[-1]), float(chunk.timestamps[-1])
        arrays = {"eeg.f32": np.asarray(chunk.data.T, dtype="<f4"),
                  "timestamps.f64": np.asarray(chunk.timestamps, dtype="<f8"),
                  "sample_indices.i64": np.asarray(indices, dtype="<i8"), "valid.u8": valid.astype("u1")}
        for name, array in arrays.items():
            array.tofile(self._raw[name])
            self._raw[name].flush()
        aux = {}
        for key, value in chunk.auxiliaries.items():
            if not re.fullmatch(r"[a-zA-Z0-9_]+", key):
                raise ValueError("Invalid auxiliary name")
            array = np.asarray(value)
            if array.dtype.kind in "US":
                aux[key] = {"value": array.tolist()}
            elif array.dtype.kind in "biuf":
                if key not in self._aux_handles:
                    self._aux_handles[key] = (self.session_dir / "raw" / (key + ".bin")).open("xb")
                handle = self._aux_handles[key]
                aux[key] = {"offset_bytes": handle.tell(), "dtype": array.dtype.str, "shape": array.shape}
                array.tofile(handle)
                handle.flush()
            else:
                raise ValueError(f"Unsupported auxiliary type: {key}")
        self._chunklog.write(json.dumps({"offset": self._written, "samples": n, "sequence": chunk.sequence,
                                        "received_at": chunk.received_at, "auxiliaries": aux}) + "\n")
        self._chunklog.flush()  # commit marker written only after every array is flushed
        self._written += n
        self._invalid += int(np.count_nonzero(~valid))

    def _persist(self):
        write_json(self.session_dir / "run.json", {**self.run, "samples": self._written,
                   "invalid_samples": self._invalid, "continuity_errors": self._continuity, "error": self.error})

    def stop(self, *, status, reason):
        with self._lock:
            if self._stopped:
                return
            self._accepting = False
        if self._thread.is_alive():
            try:
                self._queue.put(None, timeout=15)
            except Full as exc:
                self.error = "写盘队列无法结束，文件保持未封存状态"
                self._persist()
                raise RecordingError(self.error) from exc
        self._thread.join(30)
        if self._thread.is_alive():
            self.error = "写盘线程尚未退出，文件保持未封存状态"
            self._persist()
            raise RecordingError(self.error)
        if not self.run["external_recording"] and not self._written:
            self.error = self.error or "没有收到 EEG 样本"
        for h in [*self._raw.values(), self._chunklog, *self._aux_handles.values(), *self._handles.values()]:
            h.close()
        self._stopped = True
        self.run.update(ended_at=utc_now(), recording_status="error" if self.error else ("complete" if status == "completed" else status),
                        stop_reason="recording_error" if self.error else reason)
        if self.run["external_recording"]:
            self.run["external_eeg_status"] = "awaiting_edf_association"
        with (self.session_dir / "run.log").open("a", encoding="utf-8") as f:
            f.write(f"{utc_now()} recording stopped {self.run['recording_status']} {self.run['stop_reason']}\n")
        self._persist()
        if self._written:
            try:
                from neuroscope_eeg.analysis.local_report import write_local_report
                write_local_report(self.session_dir)
            except (OSError, ValueError, RecordingError) as exc:
                with (self.session_dir / "run.log").open("a", encoding="utf-8") as f:
                    f.write(f"Local report unavailable: {exc}\n")
        import csv
        events = read_jsonl(self.session_dir / "events.jsonl")
        with (self.session_dir / "behavior.csv").open("x", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["monotonic_time", "phase", "label", "payload"])
            for event in events:
                if "response" in event["phase"] or "answer" in event["phase"]:
                    writer.writerow([event["monotonic_time"], event["phase"], event["label"], json.dumps(event["payload"], ensure_ascii=False)])


def read_jsonl(path):
    return [json.loads(line) for line in Path(edf_path(path)).read_text(encoding="utf-8").splitlines() if line.strip()]


def read_native(path):
    path = Path(edf_path(path))
    run = json.loads((path / "run.json").read_text(encoding="utf-8"))
    device = json.loads((path / "device.json").read_text(encoding="utf-8"))
    chunks = read_jsonl(path / "raw/chunks.jsonl")
    n = sum(c["samples"] for c in chunks)
    channels = len(device["channel_names"])
    if n == 0 or channels == 0:
        raise RecordingError("该记录没有本机 EEG 样本；EMOTIV 请先关联外部 EDF")
    if n != run["samples"]:
        raise RecordingError("记录未正常封存，样本计数不一致；保留原始文件待恢复")
    data = np.memmap(path / "raw/eeg.f32", dtype="<f4", mode="r", shape=(n, channels))
    return run, device, data
