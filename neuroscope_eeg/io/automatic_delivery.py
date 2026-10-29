"""Idempotent automatic export; no guessed hardware metadata or silent overwrites."""
import json
from pathlib import Path

from neuroscope_eeg.io.bids_export import export_delivery, validate_delivery
from neuroscope_eeg.io.edf_paths import edf_path
from neuroscope_eeg.io.external_recording import sha256
from neuroscope_eeg.io.native_recording import utc_now, write_json
from neuroscope_eeg.io.storage_layout import record_identity
from neuroscope_eeg.profile_config import validate_profile


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _inputs(run_dir):
    names = ("run.json", "device.json", "config.json", "provenance.json", "events.jsonl", "alignment.json",
             "external_confirmation.json", "analysis_profile.json")
    paths = [run_dir / name for name in names if (run_dir / name).exists()]
    paths += [p for folder in ("raw", "external") for p in (run_dir / folder).rglob("*") if p.is_file()]
    return {str(p.relative_to(run_dir)): sha256(p) for p in sorted(paths)}


def _package_hashes(package):
    return {str(p.relative_to(package)): sha256(p) for p in sorted(package.rglob("*")) if p.is_file()}


def ensure_delivery(run_dir, progress=lambda _: None, *, validator="bids-validator"):
    run_dir = Path(edf_path(run_dir))
    root, run = record_identity(run_dir)
    auxiliary = run_dir / "delivery"
    auxiliary.mkdir(parents=True, exist_ok=True)
    status_path = auxiliary / "status.json"

    def finish(status, message, **details):
        value = {"status": status, "message": message, "session_id": run["session_id"],
                 "updated_at": utc_now(), **details}
        write_json(status_path, value)
        return value

    lock = auxiliary / ".export.lock"
    try:
        handle = lock.open("x", encoding="utf-8")
    except FileExistsError:
        return {"status": "busy", "message": "交付导出正在运行；异常中断遗留的锁需确认进程结束后移除"}
    try:
        handle.write(utc_now())
        handle.close()
        if not run.get("ended_at") or run["recording_status"] == "recording":
            return finish("waiting", "记录尚未封存")
        if run["external_recording"] and not (run_dir / "external_confirmation.json").exists():
            return finish("waiting_edf", "等待关联本次 EMOTIV EDF")
        config, device = _read(run_dir / "config.json"), _read(run_dir / "device.json")
        profile = {**device.get("extra", {}), **validate_profile(config.get("profile", {}))}
        if (run_dir / "analysis_profile.json").exists():
            override = _read(run_dir / "analysis_profile.json")
            if override.get("session_id") not in (None, run["session_id"]) or override.get("source_id") not in (None, device["source_id"]):
                return finish("needs_configuration", "补充配置与本次设备或 UUID 不一致")
            profile.update(validate_profile(override))
        # Only the built-in simulator has known synthetic metadata. Never apply this to replay or hardware.
        if device["source_type"] == "simulated" and run["simulated"]:
            profile = {"confirmed": True, "manufacturer": "NeuroScope", "model": "Software simulator",
                       "eeg_reference": "n/a", "software_filters": "n/a", "power_line_frequency": "n/a",
                       "physical_min": [-10000.] * len(device["channel_names"]), "physical_max": [10000.] * len(device["channel_names"]),
                       "range_evidence": "Built-in simulation export range; not hardware specifications"}
        if profile.get("confirmed") is not True or any(key not in profile for key in (
            "manufacturer", "model", "eeg_reference", "software_filters", "power_line_frequency"
        )):
            return finish("needs_configuration", "等待确认本次设备配置：厂家、型号、参考方式、滤波和工频；可在记录与报告中补充")
        allow_estimated = bool(config.get("delivery", {}).get("allow_estimated_timing", False))
        if not (run_dir / "alignment.json").exists() and (run["external_recording"] or not allow_estimated):
            return finish("waiting_alignment", "等待事件对齐表；本机记录也可在采集前选择允许未校准的软件估计")
        inputs = _inputs(run_dir)
        name = ("simulation_" if run["simulated"] else "") + run["unique_name"]
        package = root / "data" / name / ("recording-" + run["session_id"])
        receipt_path = auxiliary / "export.json"
        if package.exists():
            receipt = _read(receipt_path) if receipt_path.exists() else {}
            if receipt.get("input_sha256") != inputs or receipt.get("files_sha256") != _package_hashes(package):
                return finish("needs_review", "已有交付包与源记录或校验值不一致，未覆盖；请核对后处理已有交付包", package=str(package))
        else:
            progress("正在生成标准 EDF 交付包")
            package = export_delivery(run_dir, root / "data", profile=profile,
                                      allow_estimated_timing=allow_estimated, allow_simulated=run["simulated"])
            if inputs != _inputs(run_dir):
                return finish("needs_review", "导出期间源记录发生变化，交付包未标记为可用，请核对", package=str(package))
            write_json(receipt_path, {"session_id": run["session_id"], "input_sha256": inputs,
                                     "files_sha256": _package_hashes(package), "package": str(package)})
        progress("交付包已生成，正在执行 BIDS Validator")
        validation_path = auxiliary / "validation.json"
        previous = _read(validation_path) if validation_path.exists() else {}
        # A successful validation is reusable only for exactly the same package bytes.
        if previous.get("bids_validated") and previous.get("files_sha256") == _package_hashes(package):
            validation = previous
        else:
            try:
                validation = validate_delivery(package, validator, validation_path=validation_path)
            except Exception as exc:  # noqa: BLE001 - preserve package when the validator is unavailable
                write_json(validation_path, {"bids_validated": False, "status": "unavailable", "error": str(exc)})
                return finish("exported_unvalidated", f"EDF 已导出；BIDS 校验未完成：{exc}", package=str(package))
        if inputs != _inputs(run_dir) or _read(receipt_path).get("files_sha256") != _package_hashes(package):
            return finish("needs_review", "校验期间源记录或交付包发生变化，请核对；未标记本次交付完成", package=str(package))
        passed = validation["bids_validated"]
        return finish("validated" if passed else "exported_unvalidated",
                      "EDF 已导出，BIDS 校验通过" if passed else "EDF 已导出，BIDS 校验未通过；详见 Records 内校验记录",
                      package=str(package), bids_validated=passed, simulated=run["simulated"])
    except Exception as exc:  # noqa: BLE001 - export failure must not suppress the independent report
        return finish("failed", "EDF 尚未生成或确认：" + str(exc))
    finally:
        handle.close()
        lock.unlink(missing_ok=True)
