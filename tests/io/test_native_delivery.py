import json

import numpy as np
import pyedflib
import pytest

from neuroscope_eeg.core.models import EEGChunk, SourceMetadata
from neuroscope_eeg.desktop.protocols import StimulusEvent
from neuroscope_eeg.io.bids_export import export_delivery, validate_delivery
from neuroscope_eeg.io.edf_paths import edf_path
from neuroscope_eeg.io.external_recording import associate_external
from neuroscope_eeg.io.native_recording import NativeRecorder, read_native, write_json

PROFILE = {"confirmed": True, "manufacturer": "TestLab", "model": "Fixture", "eeg_reference": "Cz",
           "software_filters": "n/a", "power_line_frequency": 50, "physical_min": [-100, -100], "physical_max": [100, 100], "range_evidence": "Synthetic fixture specifications"}


def test_brainco_export_keeps_trigger_evidence_without_claiming_alignment(tmp_path):
    root, _ = record(tmp_path)
    path = root / "device.json"
    device = json.loads(path.read_text(encoding="utf-8"))
    device["source_type"] = "brainco"
    write_json(path, device)
    path = root / "raw/chunks.jsonl"
    chunk = json.loads(path.read_text(encoding="utf-8"))
    chunk["auxiliaries"]["brainco_trigger_events_json"] = {
        "value": json.dumps([{"event_seq": 3, "sample_counter": 12345}])}
    path.write_text(json.dumps(chunk) + "\n", encoding="utf-8")
    out = export_delivery(root, tmp_path / "delivery", allow_estimated_timing=True)
    audit = json.loads((root / "delivery/brainco_triggers.json").read_text(encoding="utf-8"))
    assert audit["summary"]["received_events"] == 1
    assert audit["summary"]["physical_onset_calibrated"] is False
    assert audit["records"][0]["sample_counter"] == 12345
    session = json.loads(next(out.rglob("session.json")).read_text(encoding="utf-8"))
    assert session["brainco_trigger_evidence"] == audit
    events = next(out.rglob("*_events.tsv")).read_text(encoding="utf-8")
    assert "software_cursor_unverified" in events


def record(tmp_path, *, external=False, invalid=False, gap=False, participant="00000001"):
    meta = SourceMetadata("fixture", "emotiv_external" if external else "fixture", 250,
                          () if external else ("C3", "C4"), () if external else ("eeg", "eeg"),
                          () if external else ("uV", "uV"), PROFILE)
    recorder = NativeRecorder.start(root_dir=tmp_path, participant_id=participant, paradigm="运动想象",
               preset="完整采集", metadata=meta, paradigm_code="MI-20261027", unique_name="FIXMI-20261027", source_sample_offset=900,
               config={"experiment_metadata": {"full_name": "MI fixture", "unique_name": "FIXMI-20261027", "description": "Synthetic test"}})
    data = np.array([np.sin(np.arange(503)/10)*25, np.cos(np.arange(503)/10)*30], dtype=np.float32)
    if not external:
        indices = np.arange(900, 1403)
        if gap:
            indices[250:] += 3
        valid = np.ones(503, dtype=bool)
        if invalid:
            valid[42] = False
        recorder.submit(EEGChunk(meta, data, indices/250, 900, indices, valid,
                               {"raw_counts": data.T.astype(np.int32), "generation": np.array(1)}))
    recorder.record_event(StimulusEvent(10., 100., "运动想象", "imagery", "left"),
                          eeg_sample_index=25, eeg_session_sec=.1)
    recorder.stop(status="completed", reason="completed")
    return recorder.session_dir, data


def test_exact_native_and_edf_samples_no_tail_padding(tmp_path):
    run_dir, data = record(tmp_path)
    run, _device, native = read_native(run_dir)
    assert run["participant_id"] == "00000001"
    assert run_dir.name == "recording-" + run["session_id"] and run_dir.parent.name == "Records"
    assert run["samples"] == 503
    np.testing.assert_array_equal(native.T, data)
    with pytest.raises(ValueError, match="对齐"):
        export_delivery(run_dir, tmp_path / "delivery")
    out = export_delivery(run_dir, tmp_path / "delivery", allow_estimated_timing=True)
    assert len(list(out.rglob("*.edf"))) == 1
    assert not list(out.rglob("*.bdf"))
    with pyedflib.EdfReader(edf_path(next(out.rglob("*.edf")))) as edf:
        np.testing.assert_array_equal(edf.getNSamples(), [503, 503])
        np.testing.assert_allclose(edf.getSampleFrequencies(), [250, 250])
        assert edf.file_duration == pytest.approx(503/250)
        for i in range(2):
            np.testing.assert_allclose(edf.readSignal(i), data[i], atol=.004)
    session = json.loads(next(out.rglob("session.json")).read_text())
    assert session["session_id"] == run["session_id"]
    assert session["recording_status"] == "complete"
    assert session["schema_version"] == 1
    assert next(out.rglob("*_events.tsv")).read_text().splitlines()[0].startswith("onset\tduration\t")
    assert (out / ".bidsignore").read_text().strip() == "**/session.json"
    assert json.loads((run_dir / "delivery/validation.json").read_text())["bids_validated"] is False
    with pytest.raises(FileExistsError):
        export_delivery(run_dir, tmp_path / "delivery", allow_estimated_timing=True)


@pytest.mark.parametrize("kwargs", [{"invalid": True}, {"gap": True}])
def test_invalid_or_discontinuous_native_preserved_not_fabricated(tmp_path, kwargs):
    path, data = record(tmp_path, **kwargs)
    _, _, native = read_native(path)
    np.testing.assert_array_equal(native.T, data)
    with pytest.raises(ValueError, match="无效样本或丢样"):
        export_delivery(path, tmp_path / "out", allow_estimated_timing=True)


def test_repeat_runs_and_identity_validation(tmp_path):
    a, _ = record(tmp_path)
    b, _ = record(tmp_path)
    assert a != b
    with pytest.raises(ValueError, match="8 位"):
        record(tmp_path, participant="S01")


def test_chinese_output_directory_is_supported(tmp_path):
    run, _ = record(tmp_path / "中文原始数据")
    target = export_delivery(run, tmp_path / "中文交付", allow_estimated_timing=True)
    with pyedflib.EdfReader(edf_path(next(target.rglob("*.edf")))) as reader:
        assert reader.getNSamples()[0] == 503


def test_external_edf_requires_identity_and_explicit_alignment(tmp_path):
    native, _ = record(tmp_path)
    exported = export_delivery(native, tmp_path / "out", allow_estimated_timing=True)
    source = next(exported.rglob("*.edf"))
    external, _ = record(tmp_path, external=True)
    with pytest.raises(ValueError, match="人工确认"):
        associate_external(external, source)
    receipt = associate_external(external, source, operator_confirmed=True)
    assert receipt["session_id"] == external.name.removeprefix("recording-")
    assert receipt["alignment_status"] == "pending"
    profile = {**PROFILE, "channel_types": ["eeg", "eeg"], "edf_timezone": "+08:00"}
    with pytest.raises(ValueError, match="对齐"):
        export_delivery(external, tmp_path / "out", profile=profile)
    write_json(external / "alignment.json", {"session_id": external.name.removeprefix("recording-"), "method": "test_marker_annotation",
               "evidence": "Fixture annotation at EDF sample 25", "events": [{"event_index": 0, "onset": .1, "duration": 0}]})
    out = export_delivery(external, tmp_path / "out", profile=profile)
    assert next(out.rglob("*.edf")).read_bytes() == source.read_bytes()
    assert json.loads(next(out.rglob("session.json")).read_text())["started_at"].endswith("+08:00")


def test_validator_does_not_infer_success_from_exit_code_only(tmp_path, monkeypatch):
    class Result:
        returncode, stdout, stderr = 0, "not a validator report", ""
    monkeypatch.setattr("neuroscope_eeg.io.bids_export.subprocess.run", lambda *a, **kw: Result())
    package = tmp_path / "recording-example"
    package.mkdir()
    assert validate_delivery(package, validation_path=tmp_path / "validation.json")["bids_validated"] is False


def test_native_copies_reused_sdk_buffers_and_retains_source_time(tmp_path):
    meta = SourceMetadata.eeg("fixture", "fixture", 250, ("C3",))
    recorder = NativeRecorder.start(root_dir=tmp_path, participant_id="00000001", paradigm="SSVEP",
        preset="完整采集", metadata=meta, paradigm_code="SSVEP-20261027", unique_name="FIX-20261027",
        config={"experiment_metadata": {"full_name": "SSVEP fixture", "unique_name": "FIX-20261027", "description": "Synthetic test"}})
    values = np.array([[1., 2., 3.]], dtype=np.float32)
    times = np.array([100., 100.004, 100.008])
    recorder.submit(EEGChunk(meta, values, times, 25000, np.arange(25000, 25003)))
    values[:] = 99
    times[:] = 0
    recorder.stop(status="aborted", reason="device_disconnected")
    info, _, saved = read_native(recorder.session_dir)
    np.testing.assert_array_equal(saved.T, [[1, 2, 3]])
    np.testing.assert_array_equal(np.fromfile(recorder.session_dir / "raw/timestamps.f64", dtype="<f8"), [100., 100.004, 100.008])
    assert info["recording_status"] == "aborted"
    assert info["stop_reason"] == "device_disconnected"
