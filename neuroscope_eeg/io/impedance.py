"""Explicit run-bound contact measurements; never convert CQ/EQ to impedance."""
import csv
import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path

import numpy as np

from neuroscope_eeg.io.external_recording import sha256
from neuroscope_eeg.io.native_recording import utc_now, write_json


def import_measurement(run_dir, source):
    root, source = Path(run_dir), Path(source)
    run = json.loads((root / "run.json").read_text(encoding="utf-8"))
    device = json.loads((root / "device.json").read_text(encoding="utf-8"))
    if run["recording_status"] == "recording":
        raise ValueError("请先完成记录，再关联测量凭据")
    if source.suffix.lower() == ".csv":
        with source.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        if not rows:
            raise ValueError("CSV 无测量行")
        keys = ("source_id", "measured_at", "stage", "unit", "method")
        if any(len({row.get(key) for row in rows}) != 1 for key in keys):
            raise ValueError("一次导入的设备、时间、阶段、单位和来源必须一致")
        measurement = {key: rows[0].get(key) for key in keys}
        measurement["channels"] = [{"channel": row["channel"], "value": float(row["value"]) if row.get("value") else None,
                                    "status": row.get("status", "")} for row in rows]
    else:
        measurement = json.loads(source.read_text(encoding="utf-8-sig"))
    if measurement.get("source_id") != device["source_id"]:
        raise ValueError("测量设备 source_id 与本次记录不一致；请勿跨设备关联")
    if measurement.get("session_id") not in (None, "", run["session_id"]):
        raise ValueError("测量已绑定其他记录 UUID")
    measured_at = datetime.fromisoformat(measurement.get("measured_at", ""))
    if measured_at.tzinfo is None:
        raise ValueError("测量时间必须包含时区")
    if measurement.get("stage") not in ("pre", "post"):
        raise ValueError("stage 必须为 pre（采集前）或 post（采集后）")
    if measurement["stage"] == "pre" and measured_at > datetime.fromisoformat(run["started_at"]):
        raise ValueError("标为采集前的测量时间晚于记录开始，请核对时区与阶段")
    if measurement["stage"] == "post" and measured_at < datetime.fromisoformat(run["ended_at"]):
        raise ValueError("标为采集后的测量时间早于记录结束，请核对时区与阶段")
    endpoint = device.get("extra", {}).get("endpoint")
    if endpoint and measurement.get("endpoint") and endpoint != measurement["endpoint"]:
        raise ValueError("测量 SDK 地址与本次记录不同，请核对设备连接")
    if not measurement.get("method") or measurement.get("unit") not in ("kOhm", "Ohm", "CQ", "EQ", "unknown"):
        raise ValueError("须填写来源 method 与原始单位 kOhm/Ohm/CQ/EQ/unknown")
    channels = measurement.get("channels", [])
    if not isinstance(channels, list):
        raise ValueError("channels 必须为逐通道列表")  # noqa: TRY004 - user-facing configuration error
    known_names = device["channel_names"]
    if run["external_recording"] and (root / "external_confirmation.json").exists():
        known_names = json.loads((root / "external_confirmation.json").read_text(encoding="utf-8"))["header"]["channel_names"]
    names = [c["channel"] for c in channels]
    if len(names) != len(set(names)) or any(name not in known_names for name in names):
        raise ValueError("测量通道重复或无法对应记录电极；请先核对映射 / 关联 EDF")
    for row in channels:
        value = row.get("value")
        if value is not None and (not isinstance(value, (float, int)) or not np.isfinite(value) or value < 0):
            raise ValueError("测量值须为非负有限数，缺失用 null / 空值")
    attachment = measurement.get("attachment")
    if not channels and not attachment:
        raise ValueError("至少需要逐通道数据或原始截图凭据")
    original = None
    if attachment:
        original = (source.parent / attachment).resolve()
        if original.suffix.lower() not in {".png", ".jpg", ".jpeg", ".pdf"} or not original.is_file():
            raise ValueError("attachment 必须指向存在的 PNG/JPG/PDF 凭据")
    target = root / "impedance"
    target.mkdir(exist_ok=True)
    key = uuid.uuid4().hex
    # Keep the provided source, exact values and their provenance alongside normalized metadata.
    shutil.copy2(source, target / (key + ".source" + source.suffix.lower()))
    if original:
        name = key + original.suffix.lower()
        shutil.copy2(original, target / name)
        measurement["attachment"] = name
        measurement["attachment_sha256"] = sha256(target / name)
    measurement.update(session_id=run["session_id"], imported_at=utc_now(), source_sha256=sha256(source),
                       source_filename=source.name, operator_confirmed=True,
                       time_offset_from_start_sec=(measured_at-datetime.fromisoformat(run["started_at"])).total_seconds())
    destination = target / (key + ".json")
    write_json(destination, measurement)
    return destination
