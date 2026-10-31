"""Run with python -m neuroscope_eeg.reports.generate RUN_DIRECTORY."""
import argparse
import csv
import json
import sys
import traceback
import uuid
from pathlib import Path

import numpy as np

from neuroscope_eeg.analysis.assessment import assess, source_files
from neuroscope_eeg.io.edf_paths import edf_path
from neuroscope_eeg.io.external_recording import sha256
from neuroscope_eeg.io.native_recording import utc_now, write_json
from neuroscope_eeg.io.storage_layout import report_directory
from neuroscope_eeg.reports.layout import LAYOUT_VERSION, TEMPLATE
from neuroscope_eeg.reports.word_report import make_figures, report_title, write_word


def clean_json(value):
    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    return value


def write_csv(path, rows):
    columns = list(dict.fromkeys(key for row in rows for key in row)) or ["status"]
    with path.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows([{k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in row.items()} for row in rows])


def generate_report(run_dir, progress=lambda _: None):
    # Full Chinese report names can take a nested record past Windows MAX_PATH.
    run_dir = Path(edf_path(run_dir))
    public = report_directory(run_dir)
    base = run_dir / "analysis"
    base.mkdir(parents=True, exist_ok=True)
    generation = utc_now().replace(":", "").replace("+", "_") + "-" + uuid.uuid4().hex[:8]
    staging = base / (".pending-" + generation)
    staging.mkdir()
    write_json(staging / "status.json", {"status": "running", "started_at": utc_now()})
    try:
        report = clean_json(assess(run_dir, progress))
        report["generation"] = generation
        report["report_generated_at"] = utc_now()
        report["report_title"] = report_title(report)
        report_filename = report["report_title"] + ".docx"
        report["presentation"] = {"version": LAYOUT_VERSION, "template_sha256": sha256(TEMPLATE),
                                  "implementation_sha256": {name: sha256(Path(__file__).with_name(name))
                                      for name in ("generate.py", "word_report.py", "response_section.py", "layout.py", "protocol_section.py", "compact_report.py", "timing_section.py")}}
        write_json(staging / "assessment.json", report)
        if "brainco_triggers" in report["protocol"]:
            from neuroscope_eeg.io.brainco_triggers import read_brainco_triggers
            write_json(staging / "brainco_triggers.json", read_brainco_triggers(run_dir))
        write_csv(staging / 'display_timing.csv', (report['protocol'].get('display_timing') or {}).get('rows', []))
        ssvep_clock = (report['protocol'].get('display_timing') or {}).get('ssvep_frame_clock')
        if ssvep_clock:
            write_csv(staging / 'ssvep_frame_timing.csv', ssvep_clock.get('trials', []))
        for filename, rows in (("channels", report["channels"]), ("windows", report["windows"]),
                               ("phases", report["phase_intervals"]),
                               ("segment_channels", [{"segment": item["label"], "start_sample": item["start_sample"], "end_sample": item["end_sample"], **c} for item in report["segment_quality"] for c in item["channels"]]),
                               ("trials", report["task"]["trials"]), ("timecourses", report["task"]["timecourses"])):
            write_csv(staging / (filename+".csv"), rows)
        for key in ('epochs', 'summary', 'selection', 'errors'):
            write_csv(staging / ('general_' + key + '.csv'), report.get('general_features', {}).get(key, []))
        evidence = report["task"].get("response_evidence", {})
        for filename, key in (("trial_responses", "trial_metrics"), ("response_summary", "summary"),
                              ("block_response", "block_summary"), ("condition_spectra", "spectra"),
                              ("time_frequency", "time_frequency"), ("trial_retention", "retention"),
                              ("baseline_windows", "baseline_windows"), ("baseline_comparison", "baseline_comparison"),
                              ("harmonic_overlaps", "harmonic_overlaps"), ("response_errors", "errors")):
            write_csv(staging / (filename+".csv"), evidence.get(key, []))
        write_csv(staging / "classification.csv", [
            {"subset": key, **report["task"][key]} for key in ("all_trials", "analyzable_trials", "clean_trials")
            if key in report["task"]])
        progress("绘制证据图并生成 Word 报告")
        figures = make_figures(report, staging / "figures")
        write_word(report, staging / report_filename, figures)
        if report["input_sha256"] != {str(p.relative_to(run_dir)): sha256(p) for p in source_files(run_dir)}:
            raise ValueError("报告排版期间输入文件变化，请重新生成；本次未发布完成版本")
        destination = base / generation
        staging.rename(destination)
        staging = destination
        published = public / generation
        published.mkdir(parents=True, exist_ok=False)
        report_path = published / report_filename
        (destination / report_filename).rename(report_path)
        write_json(destination / "status.json", {"status": "completed", "ended_at": utc_now(),
                   "task_status": report["task"]["status"], "report": str(report_path)})
        write_json(base / "latest.json", {"generation": generation, "report": str(report_path), "analysis": str(destination)})
        return report_path
    except Exception as exc:
        (staging / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
        write_json(staging / "status.json", {"status": "failed", "error": str(exc), "ended_at": utc_now()})
        raise


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("run_directory")
    args = parser.parse_args()
    def progress(message):
        print(json.dumps({"progress": message}, ensure_ascii=False), flush=True)
    result = generate_report(args.run_directory, progress)
    print(json.dumps({"report": str(result)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
