import json

import pytest
from test_native_delivery import PROFILE, record

from neuroscope_eeg.io.bids_export import _event_rows, export_delivery
from neuroscope_eeg.io.native_recording import write_json
from neuroscope_eeg.profile_config import validate_profile
from neuroscope_eeg.project_metadata import load_metadata, save_metadata, validate_metadata
from neuroscope_eeg.protocol_config import AssessmentProtocol


@pytest.mark.parametrize("name", ["lower-20261029", "SSVEP-20260230", "TOOLONG-20261029", "SSVEP_20261029"])
def test_invalid_experiment_identity(name):
    with pytest.raises(ValueError):
        validate_metadata({"full_name": "Experiment", "unique_name": name, "description": "Task"})


def test_metadata_roundtrip_and_unknown_fields(tmp_path):
    data = {"full_name": '中文 "实验"', "unique_name": "SSVEP-20261029", "description": "第一行\n第二行"}
    path = tmp_path / "metadata.toml"
    save_metadata(path, data)
    assert load_metadata(path) == data
    with pytest.raises(ValueError):
        validate_metadata({**data, "typo": 1})


def test_strict_protocol_and_profile():
    with pytest.raises(ValueError, match="未知"):
        AssessmentProtocol.from_dict({**AssessmentProtocol.defaults("SSVEP").to_dict(), "task_secs": 8})
    with pytest.raises(ValueError, match="未知"):
        validate_profile({"confirmd": True})
    with pytest.raises(ValueError, match="量程"):
        validate_profile({"physical_min": [1], "physical_max": [0], "range_evidence": "test"})
    with pytest.raises(ValueError):
        validate_profile({"power_line_frequency": True})


def test_device_range_required_and_not_silently_expanded(tmp_path):
    run, _ = record(tmp_path)
    device = json.loads((run / "device.json").read_text(encoding="utf-8"))
    for key in ("physical_min", "physical_max", "range_evidence"):
        device["extra"].pop(key)
    write_json(run / "device.json", device)
    with pytest.raises(ValueError, match="实际设备"):
        export_delivery(run, tmp_path / "data", allow_estimated_timing=True)
    with pytest.raises(ValueError, match="超出已确认量程"):
        export_delivery(run, tmp_path / "data", allow_estimated_timing=True,
                        profile={**PROFILE, "physical_min": [-1, -1], "physical_max": [1, 1]})
    assert not list((tmp_path / "data").rglob("*.edf"))
    assert (run / "raw/eeg.f32").exists()


def test_event_interval_uses_observed_cursor_not_planned_duration(tmp_path):
    run, _ = record(tmp_path)
    info = json.loads((run / "run.json").read_text(encoding="utf-8"))
    events = [{"phase": "flicker", "label": "目标 10 Hz", "sample_cursor": 25,
               "payload": {"guided_step": 4, "trial": 2, "is_practice": False, "target_frequency": 10,
                           "planned_duration_s": 999}},
              {"phase": "rest", "label": "休息", "sample_cursor": 275, "payload": {"guided_step": 5}}]
    (run / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events), encoding="utf-8")
    rows = _event_rows(run, info, 250, 503, True)
    assert float(rows[0]["duration"]) == 1
    assert rows[0]["event_kind"] == "software_phase_interval"
    assert rows[0]["timing_method"] == "software_cursor_unverified"
    assert rows[0]["condition"] == 10 and rows[0]["trial"] == 2
    assert float(rows[1]["duration"]) == 0  # No observed end: never invent it.
    provenance = json.loads((run / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["source_sha256"] and provenance["dependencies"]["numpy"]
