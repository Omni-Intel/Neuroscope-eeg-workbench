import json
from pathlib import Path

from test_native_delivery import record

from neuroscope_eeg.io.automatic_delivery import ensure_delivery
from neuroscope_eeg.io.external_recording import sha256
from neuroscope_eeg.io.native_recording import write_json
from neuroscope_eeg.io.storage_layout import delivery_validation_path, report_directory


def permit_software_events(run):
    config = json.loads((run / "config.json").read_text(encoding="utf-8"))
    write_json(run / "config.json", {**config, "delivery": {"allow_estimated_timing": True}})


def fake_validator(monkeypatch):
    class Result:
        returncode, stdout, stderr = 0, '{"issues":{"errors":[],"warnings":[]}}', ""
    monkeypatch.setattr("neuroscope_eeg.io.bids_export.subprocess.run", lambda *a, **kw: Result())


def test_automatic_delivery_is_separate_idempotent_and_detects_modified_package(tmp_path, monkeypatch):
    fake_validator(monkeypatch)
    run, _ = record(tmp_path)
    permit_software_events(run)
    first = ensure_delivery(run)
    assert first["status"] == "validated"
    package = Path(first["package"])
    assert package == run.parent.parent / "data/FIXMI-20261027" / run.name
    assert len(list(package.rglob("*.edf"))) == 1
    assert not list((tmp_path / "data").rglob("*.validation.json"))
    assert not list((tmp_path / "data").rglob(".export-*"))
    assert delivery_validation_path(package) == run / "delivery/validation.json"
    assert report_directory(run) == run.parent.parent / "Reports/FIXMI-20261027" / run.name
    before = {str(p): (sha256(p), p.stat().st_mtime_ns) for p in package.rglob("*") if p.is_file()}
    assert ensure_delivery(run)["status"] == "validated"
    assert before == {str(p): (sha256(p), p.stat().st_mtime_ns) for p in package.rglob("*") if p.is_file()}
    edf = next(package.rglob("*.edf"))
    with edf.open("ab") as stream:
        stream.write(b"tampered")
    damaged = sha256(edf)
    assert ensure_delivery(run)["status"] == "needs_review"
    assert sha256(edf) == damaged  # Never silently overwrite evidence.


def test_missing_metadata_and_edf_are_pending_not_success(tmp_path):
    run, _ = record(tmp_path)
    assert ensure_delivery(run)["status"] == "waiting_alignment"
    device = json.loads((run / "device.json").read_text(encoding="utf-8"))
    write_json(run / "device.json", {**device, "extra": {}})
    permit_software_events(run)
    assert ensure_delivery(run)["status"] == "needs_configuration"
    assert not list((tmp_path / "data").rglob("*.edf"))
    external, _ = record(tmp_path, external=True)
    assert ensure_delivery(external)["status"] == "waiting_edf"


def test_validator_failure_keeps_export_and_retry_can_validate(tmp_path, monkeypatch):
    run, _ = record(tmp_path)
    permit_software_events(run)
    def unavailable(*args, **kwargs):
        raise FileNotFoundError("validator missing")
    monkeypatch.setattr("neuroscope_eeg.io.bids_export.subprocess.run", unavailable)
    result = ensure_delivery(run)
    assert result["status"] == "exported_unvalidated"
    package = Path(result["package"])
    assert package.exists()
    assert json.loads((run / "delivery/validation.json").read_text())["bids_validated"] is False
    fake_validator(monkeypatch)
    assert ensure_delivery(run)["status"] == "validated"


def test_failure_staging_is_outside_data_and_raw_survives(tmp_path, monkeypatch):
    run, _ = record(tmp_path)
    permit_software_events(run)
    raw = sha256(run / "raw/eeg.f32")
    def failed_writer(*args, **kwargs):
        raise OSError("injected writer failure")
    monkeypatch.setattr("pyedflib.EdfWriter", failed_writer)
    assert ensure_delivery(run)["status"] == "failed"
    assert list((run / "delivery").glob(".export-*"))
    assert not list((tmp_path / "data").rglob("recording-*"))
    assert sha256(run / "raw/eeg.f32") == raw
    assert not (run / "delivery/.export.lock").exists()


def test_changed_source_does_not_reuse_validated_package(tmp_path, monkeypatch):
    fake_validator(monkeypatch)
    run, _ = record(tmp_path)
    permit_software_events(run)
    assert ensure_delivery(run)["status"] == "validated"
    config = json.loads((run / "config.json").read_text(encoding="utf-8"))
    write_json(run / "config.json", {**config, "profile": {"model": "changed model"}})
    assert ensure_delivery(run)["status"] == "needs_review"
