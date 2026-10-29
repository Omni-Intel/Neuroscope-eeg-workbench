"""Single-record EEGQC delivery, conforming to acq-task-template-main/data/README.md.

An export is unvalidated until a real BIDS Validator invocation passes.
"""
from __future__ import annotations

import csv
import json
import math
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from neuroscope_eeg.io.edf_paths import edf_path
from neuroscope_eeg.io.external_recording import sha256
from neuroscope_eeg.io.native_recording import read_jsonl, read_native, validate_identity, write_json
from neuroscope_eeg.io.storage_layout import delivery_validation_path


def _tsv(path, columns, rows):
    with Path(edf_path(path)).open("x", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _event_rows(run_dir, run, sfreq, n, allow_estimated):
    events = read_jsonl(run_dir / "events.jsonl")
    aligned_path = run_dir / "alignment.json"
    alignment = json.loads(aligned_path.read_text(encoding="utf-8")) if aligned_path.exists() else None
    if alignment and (alignment.get("session_id") != run["session_id"] or not alignment.get("evidence")):
        raise ValueError("alignment.json 必须注明本次 session_id 与对齐依据 evidence")
    if alignment and not alignment.get("method"):
        raise ValueError("对齐表必须填写 method")
    mapping = {x["event_index"]: x for x in alignment["events"]} if alignment else {}
    if mapping and len(mapping) != len(alignment["events"]):
        raise ValueError("对齐表中存在重复 event_index")
    next_step = {}
    following = None
    for index in range(len(events) - 1, -1, -1):
        step = events[index].get("payload", {}).get("guided_step")
        if step is not None:
            if following is not None and following[0] != step:
                next_step[index] = following[1]
            following = (step, index)
    rows = []
    for i, event in enumerate(events):
        event_kind = "phase_transition"
        if i in mapping:
            entry = mapping[i]
            onset, duration = float(entry["onset"]), float(entry["duration"])
            method = str(alignment["method"])
        elif run["external_recording"] or not allow_estimated:
            raise ValueError("事件缺少对齐依据：请提供 alignment.json；本机记录也可显式允许未经校准的软件估计")
        else:
            onset = float(event["sample_cursor"]) / sfreq
            # Events mark transitions, not a claimed measured stimulus duration.
            duration, method = 0.0, "software_cursor_unverified"
            if i in next_step and event["phase"] in {"cue", "flicker", "imagery", "fixation", "rest", "baseline_eyes_open", "baseline_eyes_closed"}:
                boundary = events[next_step[i]]
                duration = (float(boundary["sample_cursor"]) - float(event["sample_cursor"])) / sfreq
                event_kind = "software_phase_interval"
        if i in mapping and duration > 0:
            event_kind = "aligned_interval"
        if not np.isfinite(onset) or not np.isfinite(duration) or duration < 0 or onset < 0 or onset + duration > n/sfreq + 1/sfreq:
            raise ValueError(f"事件 {i} 的 onset/duration 无效或超出记录末尾")
        payload = event.get("payload", {})
        timing = payload.get("trigger_timing", {})
        rows.append({"onset": f"{onset:.9f}", "duration": f"{duration:.9f}",
                     "trial_type": event["phase"], "value": timing.get("hardware_code") or "n/a",
                     "event_index": i, "timing_method": method,
                     "label": event.get("label", "n/a"), "trial": payload.get("trial", "n/a"),
                     "condition": payload.get("condition", payload.get("target_frequency", "n/a")),
                     "is_practice": str(payload.get("is_practice", False)).lower(), "block": payload.get("block", "n/a"),
                     "event_kind": event_kind, "context_json": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))})
    return rows


def export_delivery(run_dir, output_root, *, allow_estimated_timing=False, allow_simulated=False, profile=None):
    import pyedflib
    run_dir = Path(edf_path(run_dir))
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    device = json.loads((run_dir / "device.json").read_text(encoding="utf-8"))
    validate_identity(run["participant_id"], run["paradigm_code"], run["unique_name"])
    if not re.fullmatch(r"[0-9a-f]{32}", run["session_id"]) or not re.fullmatch(r"[A-Za-z0-9]+", run["task"]):
        raise ValueError("记录 UUID 或 BIDS task 标签无效")
    if run["recording_status"] == "recording" or not run.get("ended_at"):
        raise ValueError("记录尚未封存")
    if run["simulated"] and not allow_simulated:
        raise ValueError("模拟/回放记录仅用于演示，不作为真实设备 EEGQC 交付")
    p = {**device.get("extra", {}), **(profile or {})}
    required = ["manufacturer", "model", "eeg_reference", "software_filters", "power_line_frequency"]
    if p.get("confirmed") is not True or any(key not in p for key in required):
        raise ValueError("导出前需确认设备配置：confirmed、manufacturer、model、eeg_reference、software_filters、power_line_frequency")
    external = run["external_recording"]
    if external:
        confirmation = json.loads((run_dir / "external_confirmation.json").read_text(encoding="utf-8"))
        source = run_dir / "external/recording.edf"
        if sha256(source) != confirmation["sha256"]:
            raise ValueError("关联 EDF 的校验值已变化")
        header = confirmation["header"]
        if len(set(header["sfreqs"])) != 1:
            raise ValueError("外部 EDF 包含不同采样率；需要专门适配，不能默默重采样")
        sfreq, n = header["sfreqs"][0], header["samples"][0]
        names, units = header["channel_names"], header["channel_units"]
        types = p.get("channel_types", [])
        if len(types) != len(names):
            raise ValueError("外部 EDF 的每个通道必须按实际情况配置 channel_types")
        tz_text = p.get("edf_timezone", "")
        if not re.fullmatch(r"[+-](?:0[0-9]|1[0-4]):[0-5][0-9]", tz_text):
            raise ValueError("外部 EDF 不带时区；请在设备配置明确 edf_timezone，例如 +08:00")
        tz_minutes = (int(tz_text[1:3])*60 + int(tz_text[4:6])) * (1 if tz_text[0] == "+" else -1)
        eeg_start = datetime.fromisoformat(header["edf_start_time"]).replace(tzinfo=timezone(timedelta(minutes=tz_minutes)))
        run = {**run, "started_at": eeg_start.isoformat(), "ended_at": (eeg_start+timedelta(seconds=n/sfreq)).isoformat()}
    else:
        run, device, data = read_native(run_dir)
        if run["invalid_samples"] or run["continuity_errors"]:
            raise ValueError("记录有无效样本或丢样；原始记录保留，不补零或压缩空隙生成连续 EDF")
        sfreq, n = device["sfreq"], data.shape[0]
        names, units, types = device["channel_names"], device["channel_units"], device["channel_types"]
    if any(not str(u).strip() or str(u).lower() in {"unknown", "counts", "adc counts", "adc count"} for u in units):
        raise ValueError("通道物理单位尚未确认，不能把 ADC 计数标成微伏")
    if len(set(names)) != len(names) or any(len(x.encode("ascii", errors="replace")) > 16 or not x.isascii() for x in names):
        raise ValueError("EDF 通道名称须唯一、ASCII 且不超过 16 字符；请先确认通道映射")
    rows = _event_rows(run_dir, run, sfreq, n, allow_estimated_timing)
    parent = Path(edf_path(output_root)) / (("simulation_" if run["simulated"] else "") + run["unique_name"])
    parent.mkdir(parents=True, exist_ok=True)
    target = parent / ("recording-" + run["session_id"])
    if target.exists():
        raise FileExistsError("交付包已存在；不会覆盖。上传重试直接使用原包")
    auxiliary = run_dir / "delivery"
    auxiliary.mkdir(parents=True, exist_ok=True)
    staging = auxiliary / (".export-" + uuid.uuid4().hex)
    sub, ses = "sub-" + run["participant_id"], "ses-" + run["session_id"]
    eeg_dir = staging / sub / ses / "eeg"
    eeg_dir.mkdir(parents=True)
    prefix = f"{sub}_{ses}_task-{run['task']}_run-01"
    edf = eeg_dir / (prefix + "_eeg.edf")
    if external:
        shutil.copy2(source, edf)
    else:
        integer_fs = round(sfreq)
        if not math.isclose(integer_fs, sfreq):
            raise ValueError("当前无损时长导出要求整数采样率")
        block = math.gcd(n, integer_fs)
        duration = block / sfreq
        if duration < .001:
            raise ValueError("当前样本数和采样率无法用此 EDF 写入器精确保留时长；原始数据已保留")
        lower, upper = p.get("physical_min", []), p.get("physical_max", [])
        if len(lower) != len(names) or len(upper) != len(names) or not p.get("range_evidence"):
            raise ValueError("导出需要实际设备逐通道 physical_min / physical_max 和 range_evidence；不可从观测幅值猜量程")
        headers = []
        for c, (name, unit, lo, hi) in enumerate(zip(names, units, lower, upper)):
            if type(lo) not in (int, float) or type(hi) not in (int, float) or not np.isfinite(lo) or not np.isfinite(hi) or lo >= hi:
                raise ValueError("设备物理量程无效")
            if float(np.min(data[:, c])) < lo or float(np.max(data[:, c])) > hi:
                raise ValueError("信号超出已确认量程，不裁剪或自动扩大范围：" + name)
            # EDF numeric header fields contain at most eight ASCII characters.
            if any(len(format(v, "g")) > 8 for v in (lo, hi)):
                raise ValueError("量程超出 EDF 头可精确表达范围，请核对设备单位及编码配置")
            headers.append({"label": name, "dimension": unit, "sample_frequency": sfreq,
                            "physical_min": lo, "physical_max": hi, "digital_min": -32768, "digital_max": 32767})
        with pyedflib.EdfWriter(edf_path(edf), len(names), file_type=pyedflib.FILETYPE_EDFPLUS) as writer:
            writer.setPatientCode(run["participant_id"])
            writer.setStartdatetime(datetime.fromisoformat(run["started_at"]).replace(tzinfo=None))
            writer.setSignalHeaders(headers)
            writer.setDatarecordDuration(duration)
            # One block at a time avoids loading the full recording into RAM.
            step = block * max(1, int(sfreq*10)//block)
            for start in range(0, n, step):
                writer.writeSamples([np.asarray(data[start:start+step, c], dtype=np.float64) for c in range(len(names))])
        with pyedflib.EdfReader(edf_path(edf)) as reader:
            for index, (lo, hi) in enumerate(zip(lower, upper)):
                if not math.isclose(reader.getPhysicalMinimum(index), lo, rel_tol=1e-9, abs_tol=0) or not math.isclose(reader.getPhysicalMaximum(index), hi, rel_tol=1e-9, abs_tol=0):
                    raise ValueError("EDF 量程回读不一致；未发布交付包")
            if any(reader.getNSamples() != n) or any(abs(reader.getSampleFrequencies()-sfreq) > 1e-7):
                raise ValueError("EDF 回读的样本数或采样率不一致，交付包未封存")
    write_json(staging / "dataset_description.json", {"Name": run["unique_name"], "BIDSVersion": "1.9.0", "DatasetType": "raw",
               "GeneratedBy": [{"Name": run["acquisition_software"]["name"], "Version": run["acquisition_software"]["version"]}], "Description": "SIMULATED DATA" if run["simulated"] else "Single continuous EEG recording"})
    (staging / ".bidsignore").write_text("**/session.json\n", encoding="utf-8")
    (staging / "README").write_text(
        "Single-record EEG delivery. Company identifiers are in sub-*/ses-*/session.json.\n"
        "Original sample values and timing logs are retained separately in the native recording.\n"
        "See events.tsv timing_method: software_cursor_unverified is an uncalibrated host estimate.\n"
        "This package contains no EEGQC score or upload receipt.\n", encoding="utf-8")
    _tsv(staging / "participants.tsv", ["participant_id"], [{"participant_id": sub}])
    write_json(eeg_dir.parent / "session.json", {"schema_version": 1, **{key: run[key] for key in (
        "participant_id", "session_id", "paradigm_code", "started_at", "ended_at", "recording_status", "stop_reason", "acquisition_software")}})
    write_json(eeg_dir / (prefix + "_eeg.json"), {
        "TaskName": run["task"], "SamplingFrequency": sfreq, "PowerLineFrequency": p["power_line_frequency"],
        "EEGReference": p["eeg_reference"], "SoftwareFilters": p["software_filters"], "RecordingType": "continuous",
        "RecordingDuration": n/sfreq, "Manufacturer": p["manufacturer"], "ManufacturersModelName": p["model"],
        "EEGChannelCount": sum(t.lower() == "eeg" for t in types), "EOGChannelCount": sum(t.lower() == "eog" for t in types),
        "ECGChannelCount": sum(t.lower() == "ecg" for t in types), "EMGChannelCount": sum(t.lower() == "emg" for t in types),
        "MISCChannelCount": sum(t.lower() not in {"eeg", "eog", "ecg", "emg", "stim", "trigger", "trg"} for t in types),
        "PhysicalRangeEvidence": p.get("range_evidence", "Original external EDF header"),
        "TriggerChannelCount": sum(t.lower() in {"stim", "trigger", "trg"} for t in types),
    })
    type_map = {"stim": "TRIG", "trigger": "TRIG", "trg": "TRIG"}
    _tsv(eeg_dir / (prefix + "_channels.tsv"), ["name", "type", "units"],
         [{"name": name, "type": type_map.get(kind.lower(), kind.upper()), "units": unit} for name, kind, unit in zip(names, types, units)])
    columns = ["onset", "duration", "trial_type", "value", "event_index", "timing_method", "label", "trial", "condition", "is_practice", "block", "event_kind", "context_json"]
    _tsv(eeg_dir / (prefix + "_events.tsv"), columns, rows)
    descriptions = {"onset": "Seconds relative to first saved EDF sample; see timing_method for uncertainty",
                    "duration": "Aligned duration if supplied; otherwise observed guided-phase sample-cursor difference (uncalibrated), or zero for instantaneous/unfinished transitions",
                    "trial_type": "Original paradigm phase", "value": "Requested hardware marker code, not proof of receipt",
                    "event_index": "Zero-based row in native events.jsonl", "timing_method": "Alignment basis; software_cursor_unverified is an uncalibrated host estimate"}
    descriptions.update(label="Original stimulus label", trial="Original zero-based trial identifier or n/a",
                        condition="MI condition or target SSVEP frequency in Hz; otherwise n/a",
                        is_practice="true for practice, excluded from formal task metrics", block="Formal block index or n/a",
                        event_kind="phase_transition: instantaneous or missing end; software_phase_interval: observed host-cursor interval, not physical display timing; aligned_interval: explicit supplied alignment",
                        context_json="NeuroScope local event payload as JSON; planned_duration_s is planned, not measured. These extensions are not company standardized event fields.")
    write_json(eeg_dir / (prefix + "_events.json"), {k: {"Description": v} for k, v in descriptions.items()})
    staging.rename(target)
    write_json(auxiliary / "validation.json", {"bids_validated": False, "status": "not_run", "package": str(target),
               "source_session_id": run["session_id"], "estimated_timing": any(r["timing_method"] == "software_cursor_unverified" for r in rows),
               "edf_sha256": sha256(next(target.rglob("*.edf")))})
    return target


def validate_delivery(package, validator="bids-validator", *, validation_path=None):
    package = Path(package).resolve()
    validation_path = Path(validation_path) if validation_path else delivery_validation_path(package)
    validation_path.parent.mkdir(parents=True, exist_ok=True)
    # No shell interpretation; only a real installed validator can mark success.
    if validator == "bids-validator":
        local = Path(sys.executable).parent / "bids-validator-deno.exe"
        if not local.is_file():
            local = Path(sys.executable).parent / "bids-validator-deno"
        validator = str(local) if local.is_file() else (shutil.which("bids-validator-deno") or validator)
    flags = ["--format", "json"] if "deno" in Path(validator).name else ["--json"]
    command = [str(validator), str(package), *flags]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, check=False)
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        parsed = None
    errors = parsed.get("issues", {}).get("errors") if isinstance(parsed, dict) else None
    combined = parsed.get("issues", {}).get("issues") if isinstance(parsed, dict) else None
    if isinstance(combined, list):
        errors = [item for item in combined if item.get("severity", "").lower() == "error"]
    passed = result.returncode == 0 and isinstance(errors, list) and not errors
    warnings = parsed.get("issues", {}).get("warnings", []) if isinstance(parsed, dict) else []
    if isinstance(combined, list):
        warnings = [item for item in combined if item.get("severity", "").lower() == "warning"]
    report = {"bids_validated": passed, "status": "passed" if passed else "failed_or_unrecognized_output",
              "command": command, "returncode": result.returncode,
              "stdout": result.stdout, "stderr": result.stderr, "warnings": warnings,
              "errors": errors, "package": str(package), "files_sha256": {
                  str(p.relative_to(Path(edf_path(package)))): sha256(p) for p in Path(edf_path(package)).rglob("*") if p.is_file()
              }}
    write_json(validation_path, report)
    return report
