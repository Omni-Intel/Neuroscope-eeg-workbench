"""Explicitly associate a verified readable EmotivPRO EDF with one run UUID."""
import hashlib
import json
import shutil
from pathlib import Path

from neuroscope_eeg.io.edf_paths import edf_path
from neuroscope_eeg.io.native_recording import utc_now, write_json


def sha256(path):
    digest = hashlib.sha256()
    with Path(edf_path(path)).open("rb") as f:
        for block in iter(lambda: f.read(1024*1024), b""):
            digest.update(block)
    return digest.hexdigest()


def associate_external(run_dir, edf_file, *, operator_confirmed=False):
    import pyedflib
    run_dir, source = Path(edf_path(run_dir)), Path(edf_path(edf_file))
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    if not run["external_recording"] or run["recording_status"] == "recording":
        raise ValueError("仅可为已结束的 EMOTIV 外部录制实验关联 EDF")
    if not operator_confirmed:
        raise ValueError("必须人工确认 EDF 属于本次被试、范式和记录 UUID")
    if source.suffix.lower() != ".edf":
        raise ValueError("请选择 EmotivPRO 导出的 EDF 文件")
    before = source.stat()
    with pyedflib.EdfReader(edf_path(source)) as reader:
        if reader.file_duration <= 0 or reader.signals_in_file == 0:
            raise ValueError("EDF 没有有效时长或通道")
        header = {"duration": reader.file_duration, "sfreqs": reader.getSampleFrequencies().tolist(),
                  "channel_names": reader.getSignalLabels(), "channel_units": [reader.getPhysicalDimension(i) for i in range(reader.signals_in_file)],
                  "samples": reader.getNSamples().tolist(), "edf_start_time": reader.getStartdatetime().isoformat()}
    digest = sha256(source)
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("EDF 仍在变化，请完成 EmotivPRO 导出后再关联")
    confirmation = run_dir / "external_confirmation.json"
    if confirmation.exists():
        old = json.loads(confirmation.read_text(encoding="utf-8"))
        if old["sha256"] == digest:
            return old
        raise ValueError("该记录已有不同 EDF，不能覆盖；请核对记录 UUID")
    target = run_dir / "external/recording.edf"
    target.parent.mkdir(exist_ok=True)
    with source.open("rb") as src, target.open("xb") as dst:
        shutil.copyfileobj(src, dst)
    if sha256(target) != digest:
        raise ValueError("EDF 复制校验失败，原始文件未改动；请保留现场排查")
    result = {"session_id": run["session_id"], "source_path": str(source), "sha256": digest,
              "associated_at": utc_now(), "operator_confirmed": True, "header": header,
              "alignment_status": "pending", "recording_receipt_verified": False}
    write_json(confirmation, result)
    return result
