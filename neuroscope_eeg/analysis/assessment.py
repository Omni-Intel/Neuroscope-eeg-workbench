"""Full-record, auditable assessment. Missing evidence never becomes a zero score."""
import json
import platform
from copy import deepcopy
from itertools import pairwise
from pathlib import Path

import numpy as np
import scipy
from scipy.signal import welch

from neuroscope_eeg.analysis.protocol_segments import observed_intervals, quality_intervals
from neuroscope_eeg.analysis.response_evidence import METHODS, ResponseEvidence
from neuroscope_eeg.analysis.task_assessment import (
    band_power,
    classification_summary,
    fbcca,
    local_snr,
    mean_ci,
    mi_metrics,
)
from neuroscope_eeg.io.bids_export import _event_rows
from neuroscope_eeg.io.edf_paths import edf_path
from neuroscope_eeg.io.external_recording import sha256
from neuroscope_eeg.io.native_recording import read_jsonl, read_native
from neuroscope_eeg.profile_config import validate_profile
from neuroscope_eeg.protocol_config import AssessmentProtocol

VERSION = "assessment-v1.3.0"
CONFIG = {
    "qc_window_sec": 4, "flat_ptp_uv": .1, "large_ptp_uv": 300,
    "threshold_note": "工程筛查阈值，不是跨设备临床标准；不据此给设备评级",
    "ssvep_window_relative_flicker_sec": [.5, 4.5],
    "fbcca": {"bands_hz": [[6, 80], [14, 80], [22, 80]], "order": 4, "harmonics": 3, "weights": "k^-1.25+0.25"},
    "mi_baseline_relative_fixation_sec": [.2, 1.8], "mi_task_relative_imagery_sec": [.5, 3.5],
    "mi_bands_hz": {"mu": [8, 13], "beta": [13, 30]}, "mi_lateral_rule_db": .6,
    "bootstrap_seed": 20261028, "bootstrap_repeats": 2000,
    "notch_applied": False, "subject_training": False,
    "response_evidence": METHODS,
}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def source_files(root):
    names = ["run.json", "device.json", "config.json", "provenance.json", "events.jsonl", "behavior.csv", "alignment.json",
             "external_confirmation.json", "analysis_profile.json", "triggerbox_log.jsonl", "hardware_triggers.jsonl", "sidecars.jsonl"]
    return sorted([*(root / name for name in names if (root / name).exists()),
                   *(p for folder in ("raw", "external", "impedance") for p in (root / folder).rglob("*") if p.is_file())])


def load_recording(root):
    run, device, config = (read_json(root / f"{name}.json") for name in ("run", "device", "config"))
    if not run.get("ended_at") or run["recording_status"] == "recording":
        raise ValueError("记录尚未封存，不能生成正式报告")
    profile = {**device.get("extra", {}), **validate_profile(config.get("profile", {}))}
    if (root / "analysis_profile.json").exists():
        override = read_json(root / "analysis_profile.json")
        if override.get("session_id") not in (None, run["session_id"]) or override.get("source_id") not in (None, device["source_id"]):
            raise ValueError("关联分析配置属于其他记录或设备")
        profile.update(validate_profile(override))
    if run["external_recording"]:
        if not (root / "external_confirmation.json").exists():
            return run, device, profile, None, None, None, None
        import pyedflib
        confirmation = read_json(root / "external_confirmation.json")
        edf = root / "external/recording.edf"
        if confirmation["session_id"] != run["session_id"] or sha256(edf) != confirmation["sha256"]:
            raise ValueError("外部 EDF 的 UUID 或校验值不一致")
        with pyedflib.EdfReader(edf_path(edf)) as reader:
            fs = reader.getSampleFrequencies()
            n = reader.getNSamples()
            if len(set(fs)) != 1 or len(set(n)) != 1:
                raise ValueError("EDF 包含不同采样率或长度，当前不做隐式重采样")
            data = np.column_stack([reader.readSignal(i) for i in range(reader.signals_in_file)])
            names = reader.getSignalLabels()
            types = profile.get("channel_types", ["unknown"] * len(names))
            if len(types) != len(names):
                raise ValueError("EDF channel_types 数量与通道数量不符")
            device = {**device, "sfreq": float(fs[0]), "channel_names": names, "channel_types": types,
                      "channel_units": [reader.getPhysicalDimension(i) for i in range(len(names))]}
        valid = np.all(np.isfinite(data), axis=1)
        indices = np.arange(len(data))
        timestamps = indices / device["sfreq"]
    else:
        run, device, data = read_native(root)
        for name, size in (("eeg.f32", len(data)*data.shape[1]*4), ("valid.u8", len(data)),
                           ("sample_indices.i64", len(data)*8), ("timestamps.f64", len(data)*8)):
            if (root / "raw" / name).stat().st_size != size:
                raise ValueError(f"原始文件长度不符合样本数：{name}")
        valid = np.memmap(root / "raw/valid.u8", dtype="u1", mode="r") == 1
        for channel in range(data.shape[1]):
            valid &= np.isfinite(data[:, channel])
        indices = np.memmap(root / "raw/sample_indices.i64", dtype="<i8", mode="r")
        timestamps = np.memmap(root / "raw/timestamps.f64", dtype="<f8", mode="r")
    return run, device, profile, data, valid, indices, timestamps


def channel_quality(data, device, profile, valid, progress):
    fs = device["sfreq"]
    step = max(4, round(fs*CONFIG["qc_window_sec"]))
    channels, windows, spectra = [], [], []
    line = profile.get("power_line_frequency")
    rails = profile.get("adc_rails_uv", {})
    for c, (name, kind, unit) in enumerate(zip(device["channel_names"], device["channel_types"], device["channel_units"])):
        uv = unit in {"uV", "µV", "μV"}
        rows, psds = [], []
        spectrum_freq = None
        for start in range(0, len(data), step):
            x = np.asarray(data[start:start+step, c], dtype=float)
            finite = np.isfinite(x)
            row = {"channel": name, "start_sample": start, "end_sample": start+len(x),
                   "finite_fraction": float(finite.mean()), "source_valid_fraction": float(valid[start:start+len(x)].mean()),
                   "rms_ac": None, "peak_to_peak": None, "flat_suspected": None, "large_amplitude_suspected": None,
                   "line_fraction": None, "drift_fraction": None, "high_frequency_fraction": None, "clipping_fraction": None}
            if finite.all() and len(x) >= 4:
                centered = x-x.mean()
                row.update(rms_ac=float(np.sqrt(np.mean(centered**2))), peak_to_peak=float(np.ptp(x)))
                if uv and kind == "eeg":
                    row.update(flat_suspected=bool(np.ptp(x) < CONFIG["flat_ptp_uv"]),
                               large_amplitude_suspected=bool(np.ptp(x) > CONFIG["large_ptp_uv"]))
                    if name in rails:
                        lo, hi = rails[name]
                        if not np.isfinite([lo, hi]).all() or lo >= hi:
                            raise ValueError("adc_rails_uv 必须是已确认的递增物理量程")
                        row["clipping_fraction"] = float(np.mean((x <= lo) | (x >= hi)))
                f, p = welch(x, fs=fs, nperseg=min(step, len(x)))
                for band_name, (low, high) in {"delta": (.5, 4), "theta": (4, 8), "alpha": (8, 13), "beta": (13, 30)}.items():
                    row[band_name+"_power"] = float(p[(f >= low) & (f < high)].sum()*fs/len(x)) if high < fs/2 else None
                total = p[(f >= .5) & (f <= min(100, fs/2))].sum()
                if total > 0:
                    row["drift_fraction"] = float(p[(f >= .5) & (f < 2)].sum()/total)
                    if fs/2 >= 80:
                        row["high_frequency_fraction"] = float(p[(f >= 30) & (f <= 80)].sum()/total)
                    if isinstance(line, (int, float)) and 0 < line-1 and line+1 < fs/2:
                        row["line_fraction"] = float(p[abs(f-line) <= 1].sum()/total)
                if len(x) == step and valid[start:start+len(x)].all():
                    psds.append(p)
                    spectrum_freq = f
            rows.append(row)
        flat_values = [r["flat_suspected"] for r in rows if r["flat_suspected"] is not None]
        large_values = [r["large_amplitude_suspected"] for r in rows if r["large_amplitude_suspected"] is not None]
        item = {"channel": name, "type": kind, "unit": unit, "windows": len(rows),
                "finite_fraction": float(np.isfinite(data[:, c]).mean()),
                "flat_fraction": float(np.mean(flat_values)) if flat_values else None,
                "large_amplitude_fraction": float(np.mean(large_values)) if large_values else None}
        for metric in ("rms_ac", "peak_to_peak", "line_fraction", "drift_fraction", "high_frequency_fraction", "clipping_fraction", "delta_power", "theta_power", "alpha_power", "beta_power"):
            values = [r[metric] for r in rows if r.get(metric) is not None]
            item[metric+"_median"] = float(np.median(values)) if values else None
        channels.append(item)
        windows.extend(rows)
        if psds:
            spectra.append({"channel": name, "unit": unit, "frequency": spectrum_freq.tolist(), "psd": np.mean(psds, axis=0).tolist()})
        progress(f"全程质量分析：{c+1}/{data.shape[1]} 通道")
    return channels, windows, spectra


def recorded_plan(root, run):
    from_start = run.get("protocol_start_payload", {}).get("assessment_protocol")
    from_config = read_json(root / "config.json").get("assessment_protocol")
    if from_start is not None and from_config is not None and from_start != from_config:
        raise ValueError("开始事件与保存的实验参数不一致")
    raw = from_start if from_start is not None else from_config
    if raw is None:
        return None
    plan = AssessmentProtocol.from_dict(raw)
    if plan.paradigm != run["paradigm"]:
        raise ValueError("记录范式与实验参数不一致")
    return plan


def evaluate_task(root, run, device, profile, data, valid, indices, timestamps, events):
    paradigm, fs = run["paradigm"], device["sfreq"]
    result = {"status": "unavailable", "reason": "该范式本版仅生成通用信号质量报告", "trials": [], "timecourses": []}
    if paradigm not in {"SSVEP", "运动想象"}:
        return result
    try:
        plan = recorded_plan(root, run)
    except (ValueError, TypeError) as exc:
        result["reason"] = "实验参数不可用：" + str(exc)
        return result
    if plan and plan.mi_collection:
        from neuroscope_eeg.analysis.mi_collection import audit_collection
        return audit_collection(root, run, device, data, valid, indices, timestamps, events, plan)
    windows = plan.analysis_windows() if plan else CONFIG
    durations = dict(plan.phases) if plan else ({"cue": 2, "flicker": 5, "rest": 2} if paradigm == "SSVEP" else {"fixation": 2, "cue": 1, "imagery": 4, "rest": 2})
    result["analysis_windows"] = {k: v for k, v in windows.items() if "relative_" in k}

    if not run["simulated"] and not (profile.get("confirmed") is True or profile.get("profile_confirmed") is True):
        result["reason"] = "设备电极、单位和参考方式尚未确认"
        return result
    eeg = [i for i, kind in enumerate(device["channel_types"]) if kind == "eeg"]
    lookup = {device["channel_names"][i].upper(): i for i in eeg}
    chosen = ([lookup[x] for x in ("O1", "O2", "OZ", "POZ", "PO3", "PO4") if x in lookup]
              if paradigm == "SSVEP" else [lookup[x] for x in ("C3", "C4") if x in lookup])
    if not chosen or (paradigm == "运动想象" and len(chosen) != 2):
        result["reason"] = "缺少已确认的枕区电极" if paradigm == "SSVEP" else "缺少 C3、C4 电极"
        return result
    if any(device["channel_units"][i] not in {"uV", "µV", "μV"} for i in chosen):
        result["reason"] = "任务分析要求已确认的微伏单位"
        return result
    if fs < (180 if paradigm == "SSVEP" else 100):
        result["reason"] = "采样率不满足当前固定分析配置"
        return result
    try:
        aligned = _event_rows(root, run, fs, len(data), allow_estimated=not run["external_recording"])
        if any(float(row["onset"]) < 0 for row in aligned):
            raise ValueError("存在不可用的负样本游标；需要 alignment.json")
    except (ValueError, KeyError, TypeError) as exc:
        result["reason"] = "事件对齐不可用：" + str(exc)
        return result
    result["timing_methods"] = sorted({r["timing_method"] for r in aligned})
    groups = {}
    for event, timing in zip(events, aligned):
        payload = event.get("payload", {})
        if payload.get("is_practice") or "trial" not in payload:
            continue
        if event["phase"] in {"cue", "fixation", "prep", "flicker", "imagery", "rest", "trial_complete"}:
            group = groups.setdefault(payload["trial"], {})
            group[event["phase"]] = {**event, "onset": float(timing["onset"])}
    frequencies = run.get("protocol_start_payload", {}).get("ssvep_frequencies", [])
    if paradigm == "SSVEP" and (len(frequencies) != (plan.conditions if plan else 4) or len(set(frequencies)) != len(frequencies) or any(f <= 0 or f*3 >= fs/2 for f in frequencies)):
        result["reason"] = "本次刺激频率数量与协议不符，或频率不满足采样率要求"
        return result
    evidence = ResponseEvidence(paradigm, fs, [device["channel_names"][i] for i in chosen],
                                frequencies if paradigm == "SSVEP" else [], profile.get("power_line_frequency"))
    if paradigm == "SSVEP" and plan:
        try:
            intervals = observed_intervals(root, run, fs, len(data), events)
            lo, hi = windows["ssvep_window_relative_flicker_sec"]
            evidence.prepare_resting(intervals, data, valid, indices, timestamps, chosen, round((hi-lo)*fs),
                                     profile.get("adc_rails_uv", {}))
        except (ValueError, KeyError, TypeError) as exc:
            evidence.resting["reason"] = "独立基线不可用：" + str(exc)
    for trial, phases in sorted(groups.items()):
        anchor = phases.get("flicker" if paradigm == "SSVEP" else "imagery", {})
        reference = anchor or phases.get("cue") or phases.get("fixation") or next(iter(phases.values()))
        payload = reference.get("payload", {})
        condition = payload.get("target_frequency") if paradigm == "SSVEP" else payload.get("condition", reference.get("label"))
        row = {"trial": trial, "block": payload.get("block"), "condition": condition, "completed": "trial_complete" in phases,
               "analyzable": False, "clean": False, "exclusion_reason": "", "prediction": "不确定"}
        reasons = []
        required = {*durations, 'trial_complete'}
        try:
            if not required <= phases.keys():
                raise ValueError("阶段记录或完整试次结束标记缺失")
            if condition not in (frequencies if paradigm == "SSVEP" else ["左手", "右手", "静息"]):
                raise ValueError("目标条件无效")
            onset = anchor["onset"]
            start = phases[next(iter(durations))]["onset"]
            finish = phases["trial_complete"]["onset"]
            if not (0 <= start < onset < phases["rest"]["onset"] < finish <= len(data)/fs+1/fs):
                raise ValueError("事件阶段顺序或记录边界无效")
            phase_names = [*durations, "trial_complete"]
            observed = {name: phases[next_name]["onset"] - phases[name]["onset"]
                        for name, next_name in pairwise(phase_names)}
            row["phase_durations_sec"] = observed
            if any(abs(observed[name] - duration) > .25 for name, duration in durations.items()) or abs(finish-start-sum(durations.values())) > .35:
                raise ValueError("实际阶段时长偏离计划，可能存在阻塞或对齐问题")
            a, b = round(start*fs), min(len(data), round(finish*fs))
            raw = np.asarray(data[a:b, chosen], dtype=float)
            if not valid[a:b].all() or not np.isfinite(raw).all():
                raise ValueError("包含无效样本")
            if np.any(np.diff(indices[a:b]) != 1) or not np.isfinite(timestamps[a:b]).all() or np.any(np.diff(timestamps[a:b]) <= 0):
                raise ValueError("样本或时间戳不连续")
            # Native clocks can be host-arrival clocks; report long intervals without pretending to know packet loss.
            if np.any(np.diff(timestamps[a:b]) > 2.5/fs):
                raise ValueError("时间戳存在超过 2.5 个采样周期的间隔")
            ptp = np.ptp(raw, axis=0)
            if np.any(ptp > CONFIG["large_ptp_uv"]):
                reasons.append("大幅值候选")
            if np.any(ptp < CONFIG["flat_ptp_uv"]):
                reasons.append("平直候选")
            rails = profile.get("adc_rails_uv", {})
            for j, c in enumerate(chosen):
                if device["channel_names"][c] in rails:
                    lo, hi = rails[device["channel_names"][c]]
                    if np.any((raw[:, j] <= lo) | (raw[:, j] >= hi)):
                        reasons.append("触及已确认量程")
            def segment(t0, t1):
                return np.asarray(data[round(t0*fs):round(t1*fs), chosen], dtype=float)
            if paradigm == "SSVEP":
                lo, hi = windows["ssvep_window_relative_flicker_sec"]
                x = segment(onset+lo, onset+hi)
                prediction, scores = fbcca(x, fs, frequencies)
                snrs, powers = local_snr(x, fs, condition, frequencies, profile.get("power_line_frequency"), details=True)
                row.update(prediction=frequencies[prediction], scores=scores,
                           snr_db=snrs[0], harmonic_2_snr_db=snrs[1], harmonic_3_snr_db=snrs[2], spectral_powers=powers)
            else:
                lo, hi = windows["mi_baseline_relative_fixation_sec"]
                baseline = segment(start+lo, start+hi)
                lo, hi = windows["mi_task_relative_imagery_sec"]
                task = segment(onset+lo, onset+hi)
                row.update(mi_metrics(baseline, task, fs))
                for offset in np.arange(0, durations["imagery"] - 1 + .001, .5):
                    window = segment(onset+offset, onset+offset+1)
                    for band_name, band in CONFIG["mi_bands_hz"].items():
                        base = band_power(baseline, fs, band)
                        values = 100*(band_power(window, fs, band)-base)/base
                        result["timecourses"].append({"trial": trial, "condition": condition, "clean": not reasons, "block": row["block"], "time_sec": float(offset+.5),
                                                      "band": band_name, "C3_erd_pct": float(values[0]), "C4_erd_pct": float(values[1])})
            row.update(analyzable=True, clean=not reasons, exclusion_reason="；".join(reasons))
            # Supplemental plotting/response errors must not turn a valid fixed prediction into missing data.
            checkpoint = [len(part) for part in (evidence.metrics, evidence.spectra, evidence.tfr)]
            try:
                if paradigm == "SSVEP":
                    evidence.add_ssvep(row, x)
                else:
                    evidence.add_mi(row, baseline, task, segment(onset, phases["rest"]["onset"]),
                                    segment(phases["rest"]["onset"], finish))
            except (ValueError, np.linalg.LinAlgError) as exc:
                for part, length in zip((evidence.metrics, evidence.spectra, evidence.tfr), checkpoint):
                    del part[length:]
                evidence.errors.append({"trial": trial, "reason": str(exc)})
        except (ValueError, np.linalg.LinAlgError) as exc:
            row["exclusion_reason"] = str(exc)
        result["trials"].append(row)
    rows = result["trials"]
    usable = [r for r in rows if r["analyzable"]]
    clean = [r for r in usable if r["clean"]]
    result.update(status="available" if usable else "unavailable", reason="" if usable else "没有满足阶段完整性、有效样本和对齐条件的试次",
                  selected_channels=[device["channel_names"][i] for i in chosen], counts={"observed": len(rows), "completed": sum(r["completed"] for r in rows), "analyzable": len(usable), "clean": len(clean)})
    if paradigm == "SSVEP":
        result["all_trials"] = classification_summary(rows, frequencies)
        result["analyzable_trials"] = classification_summary(usable, frequencies)
        result["clean_trials"] = classification_summary(clean, frequencies)
        result["snr_db"] = {str(f): mean_ci([r["snr_db"] for r in usable if r["condition"] == f and r["snr_db"] is not None]) for f in frequencies}
    else:
        for name, subset in (("all_trials", rows), ("analyzable_trials", usable), ("clean_trials", clean)):
            result[name] = classification_summary([r for r in subset if r["condition"] in ["左手", "右手"]], ["左手", "右手"])
        result["erd"] = {condition: {key: mean_ci([r[key] for r in usable if r["condition"] == condition])
                          for key in ("mu_C3_erd_pct", "mu_C4_erd_pct", "beta_C3_erd_pct", "beta_C4_erd_pct")}
                         for condition in ("左手", "右手", "静息")}
    result["blocks"] = {str(block): classification_summary([r for r in usable if r["block"] == block and r["condition"] in (frequencies if paradigm == "SSVEP" else ["左手", "右手"])], frequencies if paradigm == "SSVEP" else ["左手", "右手"])
                        for block in sorted({r["block"] for r in usable if r["block"] is not None})}
    result["response_evidence"] = evidence.finish(rows, frequencies if paradigm == "SSVEP" else ["左手", "右手", "静息"],
        plan.total_trials if plan else run.get("protocol_start_payload", {}).get("planned_formal_trials"))
    return result


def assess(root, progress=lambda _: None):
    root = Path(root)
    run, device, profile, data, valid, indices, timestamps = load_recording(root)
    progress("校验输入文件与分析配置")
    fingerprints = {str(p.relative_to(root)): sha256(p) for p in source_files(root)}
    events = read_jsonl(root / "events.jsonl")
    version = ('assessment-v1.4.0' if run.get('protocol_start_payload', {}).get('assessment_protocol', {}).get('version') == 'guided-assessment-v3' else VERSION)
    if run.get('protocol_start_payload', {}).get('assessment_protocol', {}).get('version') == 'guided-assessment-v4':
        version = 'assessment-v1.5.0'
    if run.get('protocol_start_payload', {}).get('assessment_protocol', {}).get('version') == 'guided-assessment-v5':
        version = 'assessment-v1.6.0'
    report = {"analysis_version": version, "configuration": deepcopy(CONFIG), "source_session_id": run["session_id"], "run": run,
              "device": device, "profile": profile, "input_sha256": fingerprints,
              "runtime": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__},
              "channels": [], "windows": [], "spectra": [], "task": {"status": "unavailable", "reason": "等待关联外部 EDF", "trials": [], "timecourses": []},
              "limitations": ["结论仅描述本次记录，不能单独证明设备优劣或被试能力。",
                              "工程筛查阈值并非跨设备标准；参考方式、电极位置、环境及被试状态均可能影响结果。",
                              "软件游标及 frameSwapped 不是物理刺激时刻；未经硬件验证的时间误差未知。",
                              "未检测到序号间断不等于没有丢包；需结合设备序号能力。",
                              "高频比例可能包含肌电、工频或真实活动，不能据此确认肌电伪迹。",
                              "置信区间以试次为单位；同一被试内重复试次可能相关，区间仅作描述性参考。",
                              "运动想象反应弱可能来自任务策略、个体差异或采集条件，不能直接归因于设备。"]}
    report["implementation_sha256"] = {p.name: sha256(p) for p in (Path(__file__), Path(__file__).with_name("task_assessment.py"),
                                       Path(__file__).with_name("response_evidence.py"), Path(__file__).with_name("general_features.py"), Path(__file__).with_name("protocol_segments.py"), Path(__file__).with_name("mi_collection.py"))}
    report["impedance"] = [read_json(p) for p in sorted((root / "impedance").glob("*.json")) if ".source." not in p.name]
    report["impedance"] = [r for r in report["impedance"] if r.get("session_id") == run["session_id"] and r.get("source_id") == device["source_id"]]
    stop = next((e for e in reversed(events) if e["phase"] == "stop"), {})
    report["protocol"] = {"planned": run.get("protocol_start_payload", {}).get("planned_formal_trials"),
                          "completed": stop.get("payload", {}).get("completed_formal_trials"),
                          "missed_frames_estimate": stop.get("payload", {}).get("missed_frames_estimate"),
                          "trigger_mode": run.get("trigger_timing", {}), "event_count": len(events)}
    report['protocol']['display_timing'] = stop.get('payload', {}).get('display_timing')
    report["phase_intervals"] = []
    report["segment_quality"] = []
    try:
        plan = recorded_plan(root, run)
        report["protocol"]["settings"] = plan.to_dict() if plan else None
        if plan:
            report["configuration"].update(plan.analysis_windows())
    except (ValueError, TypeError) as exc:
        plan = None
        report["protocol"]["settings_error"] = str(exc)
    dispatches = read_jsonl(root / "triggerbox_log.jsonl") if (root / "triggerbox_log.jsonl").exists() else []
    hardware = read_jsonl(root / "hardware_triggers.jsonl") if (root / "hardware_triggers.jsonl").exists() else []
    from neuroscope_eeg.io.brainco_triggers import read_brainco_triggers
    brainco = read_brainco_triggers(root)
    if brainco is not None:
        report["protocol"]["brainco_triggers"] = brainco["summary"]
    report["protocol"].update(hardware_send_requests=sum(bool(r.get("hardware_requested")) for r in dispatches),
                              hardware_send_errors=sum(bool(r.get("hardware_error")) for r in dispatches),
                              lsl_send_errors=sum(bool(r.get("lsl_error")) for r in dispatches),
                              received_hardware_markers=len(hardware) if hardware else None)
    if brainco is not None:
        report["protocol"]["received_hardware_markers"] = brainco["summary"]["received_events"]
    if data is not None:
        report["integrity"] = {"samples": len(data), "duration_sec": len(data)/device["sfreq"], "invalid_samples": int((~valid).sum()),
                               "sample_index_gaps": int(np.sum(np.diff(indices) != 1)) if not run["external_recording"] else None,
                               "timestamp_nonmonotonic": int(np.sum(np.diff(timestamps) <= 0)) if not run["external_recording"] else None,
                               "timestamp_long_intervals": int(np.sum(np.diff(timestamps) > 2.5/device["sfreq"])) if not run["external_recording"] else None,
                               "packet_loss_rate": None, "packet_loss_reason": "没有通用且已确认的设备包计数定义，不以本机样本序号替代真实丢包率"}
        report["channels"], report["windows"], report["spectra"] = channel_quality(data, device, profile, valid, progress)
        if plan:
            try:
                rows = observed_intervals(root, run, device["sfreq"], len(data), events)
                report["phase_intervals"] = rows
                for interval in quality_intervals(rows):
                    a, b = interval["start_sample"], interval["end_sample"]
                    if b <= a:
                        continue
                    progress("分段质量分析：" + interval["label"])
                    channels, _, _ = channel_quality(data[a:b], device, profile, valid[a:b], lambda _: None)
                    report["segment_quality"].append({**interval, "duration_sec": (b-a)/device["sfreq"],
                                                       "valid_fraction": float(valid[a:b].mean()), "channels": channels})
            except (ValueError, KeyError, TypeError) as exc:
                report["protocol"]["segment_quality_error"] = str(exc)
        progress("分析正式试次：固定参数，无个体化校准")
        report["task"] = evaluate_task(root, run, device, profile, data, valid, indices, timestamps, events)
        if run['paradigm'] in {'SSVEP', '运动想象'}:
            from neuroscope_eeg.analysis.general_features import assess_features
            report['general_features'] = assess_features(data, valid, indices, timestamps, device, profile,
                report['phase_intervals'], report['task'].get('selected_channels', []), progress)
    else:
        report["integrity"] = {"samples": 0, "duration_sec": None, "invalid_samples": None}
    # Detect concurrent edits or association during analysis; never publish a mixed-input report.
    if fingerprints != {str(p.relative_to(root)): sha256(p) for p in source_files(root)}:
        raise ValueError("分析期间输入文件变化，请待关联或保存完成后重试")
    return report
