"""Observed intervals from frame events, never reconstructed from planned durations."""
from itertools import pairwise

from neuroscope_eeg.io.bids_export import _event_rows

PHASE_LABELS = {
    "instructions": "实验说明", "task_instructions": "任务指导", "practice_ready": "练习准备",
    "baseline_ready": "基线准备", "baseline_eyes_open": "睁眼静息", "baseline_close_prepare": "闭眼准备",
    "baseline_eyes_closed": "闭眼静息", "baseline_open_recovery": "睁眼恢复", "formal_ready": "正式准备",
    "block_rest": "组间最短休息", "block_ready": "组间等待", "fixation": "试次前基线",
    "cue": "条件提示", "prep": "目标常亮定位", "flicker": "闪烁", "imagery": "想象／静息", "rest": "试次内休息",
}


def observed_intervals(root, run, fs, samples, events):
    aligned = _event_rows(root, run, fs, samples, allow_estimated=not run["external_recording"])
    starts = [(e, float(t["onset"])) for e, t in zip(events, aligned)
              if ("guided_step" in e.get("payload", {}) and e["phase"] in {*PHASE_LABELS, "protocol_complete"}) or e["phase"] == "stop"]
    rows = []
    for (event, start), (following, end) in pairwise(starts):
        phase = event["phase"]
        if phase not in PHASE_LABELS:
            continue
        if not 0 <= start <= end <= samples / fs + 1/fs:
            raise ValueError("阶段事件超出数据范围或顺序无效")
        payload = event["payload"]
        label = '中央注视准备' if phase == 'fixation' and run['paradigm'] == 'SSVEP' else PHASE_LABELS[phase]
        rows.append({"phase": phase, "label": label, "segment": payload.get("segment"),
                     "is_practice": payload.get("is_practice", False), "block": payload.get("block"),
                     "trial": payload.get("trial"), "start_sec": start, "end_sec": end, "actual_sec": end - start,
                     "planned_sec": payload.get("planned_duration_s"),
                     "completed": following["phase"] != "stop", "start_sample": round(start*fs),
                     "end_sample": min(samples, round(end*fs))})
    return rows


def quality_intervals(rows):
    """Merge only adjacent formal phases in the same block, never across pauses."""
    intervals = []
    for row in rows:
        if row["phase"] in {"baseline_eyes_open", "baseline_eyes_closed"}:
            category = row["label"]
        elif row["segment"] == "formal" and not row["is_practice"]:
            category = f"正式第 {row['block']} 组"
        else:
            continue
        if intervals and intervals[-1]["label"] == category and intervals[-1]["end_sample"] == row["start_sample"]:
            intervals[-1]["end_sample"] = row["end_sample"]
            intervals[-1]["completed"] = row["completed"]
        else:
            intervals.append({"label": category, "start_sample": row["start_sample"],
                              "end_sample": row["end_sample"], "completed": row["completed"]})
    return intervals
