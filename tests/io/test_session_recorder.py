import csv
import json
from pathlib import Path

import numpy as np
import pyedflib

from neuroscope_eeg.acquisition.td10_lsl import (
    ClockCorrectionSample,
    EEGTimingBatch,
    LSLMarker,
    NeuroScopeMarker,
    QualityBatch,
    TD10Sidecars,
)
from neuroscope_eeg.core.models import EEGChunk, SourceMetadata
from neuroscope_eeg.desktop.protocols import StimulusEvent
from neuroscope_eeg.io.session_recorder import SessionRecorder
from neuroscope_eeg.timing.models import HardwareTriggerSample, TriggerDispatch


def test_recorder_creates_session_immediately_and_writes_readable_bdf(tmp_path: Path) -> None:
    metadata = SourceMetadata.eeg("device-1", "neuracle", 10.0, ("Fp1", "Fp2"))
    recorder = SessionRecorder.start(
        root_dir=tmp_path,
        participant_id="S01",
        paradigm="N-back 工作记忆",
        preset="完整采集",
        metadata=metadata,
        source_sample_offset=20,
    )

    assert recorder.session_dir.parent == tmp_path / "S01"
    assert recorder.inprogress_path.exists()
    assert recorder.events_path.exists()
    assert recorder.session_path.exists()

    data = np.arange(30, dtype=np.float32).reshape(2, 15)
    recorder.submit(
        EEGChunk(
            metadata=metadata,
            data=data,
            timestamps=np.arange(15, dtype=np.float64) / metadata.sfreq,
            sequence=20,
        )
    )
    recorder.record_event(
        StimulusEvent(12.0, 34.0, "N-back 工作记忆", "nback_trial", "7", {"is_practice": False}),
        eeg_sample_index=15,
        eeg_session_sec=1.5,
    )
    recorder.stop(status="completed", reason="completed")

    assert recorder.final_path.exists()
    assert not recorder.inprogress_path.exists()
    with pyedflib.EdfReader(str(recorder.final_path)) as reader:
        assert reader.getSignalLabels() == ["Fp1", "Fp2"]
        assert reader.getSampleFrequencies().tolist() == [10.0, 10.0]
        assert reader.getNSamples().tolist() == [20, 20]
        np.testing.assert_allclose(reader.readSignal(0)[:15], data[0], atol=0.063)
        np.testing.assert_allclose(reader.readSignal(1)[:15], data[1], atol=0.063)

    session = json.loads(recorder.session_path.read_text(encoding="utf-8"))
    assert session["status"] == "completed"
    assert session["valid_samples"] == 15
    assert session["padded_samples"] == 5
    assert session["events_written"] == 1
    rows = recorder.events_path.read_text(encoding="utf-8-sig").splitlines()
    assert len(rows) == 2
    assert ",15," in rows[1]


def test_recorder_preserves_partial_file_and_error_metadata_on_abort(tmp_path: Path) -> None:
    metadata = SourceMetadata.eeg("device-1", "neuracle", 10.0, ("Fp1",))
    recorder = SessionRecorder.start(
        root_dir=tmp_path,
        participant_id="subject_2",
        paradigm="听觉 Oddball",
        preset="完整采集",
        metadata=metadata,
    )
    recorder.submit(
        EEGChunk(
            metadata=metadata,
            data=np.ones((1, 4), dtype=np.float32),
            timestamps=np.arange(4, dtype=np.float64) / 10.0,
            sequence=0,
        )
    )

    recorder.stop(status="aborted", reason="escape")

    session = json.loads(recorder.session_path.read_text(encoding="utf-8"))
    assert session["status"] == "aborted"
    assert session["stop_reason"] == "escape"
    assert session["valid_samples"] == 4
    assert session["padded_samples"] == 6
    assert recorder.final_path.exists()


def test_recorder_persists_trigger_audit_and_exports_sample_locked_excel(tmp_path: Path) -> None:
    metadata = SourceMetadata.eeg("device-1", "neuracle", 1000.0, ("Fp1",))
    recorder = SessionRecorder.start(
        root_dir=tmp_path,
        participant_id="S03",
        paradigm="N-back 工作记忆",
        preset="完整采集",
        metadata=metadata,
    )
    recorder.configure_trigger_timing(mode="hardware_lsl", port="COM7", lsl_source_id="marker-source")
    recorder.record_trigger_dispatch(
        TriggerDispatch(
            event_id="EVT-000001",
            sequence=1,
            session_id="session-1",
            paradigm="N-back 工作记忆",
            phase="nback_trial",
            label="7",
            payload={"nback_level": 1, "is_target": True, "block_index": 2, "trial_index": 17},
            wall_time=1_786_400_000.0,
            intent_time=1.0,
            onset_hook_time=1.01,
            hook_type="frame_swapped",
            timing_mode="hardware_lsl",
            timing_status="hardware_dispatched_unverified",
            hardware_code=53,
            hardware_symbol="NBACK_1_TARGET",
            hardware_requested=True,
            hardware_frame_hex="01 e1 01 00 35",
            hardware_dispatch_time=1.011,
            hardware_write_complete_time=1.012,
            lsl_timestamp=10.02,
        )
    )
    recorder.submit_hardware_triggers((HardwareTriggerSample(53, 1234, "TRIGGER"),))
    recorder.stop(status="completed", reason="completed")

    assert '"event_id":"EVT-000001"' in recorder.events_jsonl_path.read_text(encoding="utf-8")
    assert '"sample_index":1234' in recorder.hardware_triggers_path.read_text(encoding="utf-8")
    assert (recorder.session_dir / "event_codebook.xlsx").is_file()
    assert (recorder.session_dir / "event_timeline.xlsx").is_file()
    session = json.loads(recorder.session_path.read_text(encoding="utf-8"))
    assert session["timing_status"] == "hardware_sample_locked"
    assert session["trigger_dispatches"] == 1
    assert session["hardware_trigger_samples"] == 1
    assert session["trigger_export_error"] is None


def test_recorder_rejects_unsafe_participant_id(tmp_path: Path) -> None:
    metadata = SourceMetadata.eeg("device-1", "neuracle", 10.0, ("Fp1",))

    try:
        SessionRecorder.start(
            root_dir=tmp_path,
            participant_id="../S01",
            paradigm="N-back 工作记忆",
            preset="完整采集",
            metadata=metadata,
        )
    except ValueError as exc:
        assert "受试者编号" in str(exc)
    else:
        raise AssertionError("unsafe participant id should fail")


def test_bdf_labels_are_unique_and_keep_original_name_mapping(tmp_path: Path) -> None:
    metadata = SourceMetadata.eeg(
        "device-1",
        "neuracle",
        10.0,
        ("very-long-channel-name", "very-long-channel-number-two"),
    )
    recorder = SessionRecorder.start(
        root_dir=tmp_path,
        participant_id="S01",
        paradigm="静息睁眼/闭眼",
        preset="完整采集",
        metadata=metadata,
    )
    recorder.stop(status="aborted", reason="test")

    session = json.loads(recorder.session_path.read_text(encoding="utf-8"))
    labels = list(session["bdf_channel_labels"])
    assert len(labels) == len(set(labels)) == 2
    assert all(len(label) <= 16 for label in labels)
    assert session["channel_names"] == list(metadata.channel_names)


def test_recorder_preserves_td10_signed_24_bit_adc_counts(tmp_path: Path) -> None:
    metadata = SourceMetadata.eeg(
        "ifet-td10-headset:eeg",
        "td10_lsl",
        125.0,
        ("EEG1", "EEG2", "EEG3", "EEG4"),
        unit="ADC counts",
    )
    recorder = SessionRecorder.start(
        root_dir=tmp_path,
        participant_id="S01",
        paradigm="静息睁眼/闭眼",
        preset="完整采集",
        metadata=metadata,
    )
    data = np.zeros((4, 125), dtype=np.float32)
    data[:, :4] = np.asarray(
        [
            [-8_388_608, -1, 0, 8_388_607],
            [8_388_607, 0, -1, -8_388_608],
            [1, 2, 3, 4],
            [-4, -3, -2, -1],
        ],
        dtype=np.float32,
    )
    timestamps = np.arange(125, dtype=np.float64) / 125.0
    recorder.submit(
        EEGChunk(metadata=metadata, data=data, timestamps=timestamps, sequence=0)
    )
    recorder.submit_sidecars(
        TD10Sidecars(
            eeg_timing=(EEGTimingBatch(0, timestamps, timestamps, 0.0),),
        )
    )
    recorder.stop(status="completed", reason="completed")

    with pyedflib.EdfReader(str(recorder.final_path)) as reader:
        assert reader.getPhysicalDimension(0) == "ADCcnt"
        np.testing.assert_array_equal(reader.readSignal(0)[:4], data[0, :4])
        np.testing.assert_array_equal(reader.readSignal(1)[:4], data[1, :4])

    session = json.loads(recorder.session_path.read_text(encoding="utf-8"))
    assert session["channel_units"] == ["ADC counts"] * 4
    assert session["clipped_samples"] == 0


def test_td10_recorder_persists_sidecars_and_aligns_quality_and_events(tmp_path: Path) -> None:
    metadata = SourceMetadata.eeg(
        "ifet-td10-headset:eeg",
        "td10_lsl",
        10.0,
        ("EEG1", "EEG2", "EEG3", "EEG4"),
        unit="ADC counts",
    )
    recorder = SessionRecorder.start(
        root_dir=tmp_path,
        participant_id="S01",
        paradigm="听觉 Oddball",
        preset="完整采集",
        metadata=metadata,
    )
    corrected = np.asarray([100.0, 100.1, 100.2], dtype=np.float64)
    recorder.submit(
        EEGChunk(metadata, np.ones((4, 3), dtype=np.float32), corrected, sequence=0)
    )
    recorder.submit_sidecars(
        TD10Sidecars(
            eeg_timing=(
                EEGTimingBatch(0, corrected - 0.01, corrected, 0.01),
            ),
            quality=(
                QualityBatch(
                    np.asarray([[1, 7, 3], [0, 8, 4], [1, 9, 5]], dtype=np.int32),
                    corrected - 0.02,
                    corrected,
                    0.02,
                ),
            ),
            ifet_markers=(LSLMarker("device", 99.9, 100.0, 0.1),),
            neuroscope_markers=(NeuroScopeMarker('{"phase":"stimulus"}', 100.1),),
            clock_corrections=(
                ClockCorrectionSample("eeg", "2026-08-10T00:00:00+00:00", 0.01),
            ),
        )
    )
    recorder.record_event(
        StimulusEvent(1.0, 2.0, "听觉 Oddball", "stimulus", "standard"),
        eeg_sample_index=-1,
        eeg_session_sec=-1.0,
        lsl_time=100.1,
    )
    recorder.record_event(
        StimulusEvent(1.1, 2.1, "听觉 Oddball", "stimulus", "late"),
        eeg_sample_index=-1,
        eeg_session_sec=-1.0,
        lsl_time=100.26,
    )
    recorder.stop(status="completed", reason="completed")

    np.testing.assert_array_equal(
        np.fromfile(recorder.session_dir / "lsl_timestamps.f64", dtype="<f8"),
        corrected - 0.01,
    )
    np.testing.assert_array_equal(
        np.fromfile(recorder.session_dir / "lsl_timestamps_corrected.f64", dtype="<f8"),
        corrected,
    )
    np.testing.assert_array_equal(
        np.fromfile(recorder.session_dir / "quality_raw.i32", dtype="<i4").reshape(-1, 3),
        [[1, 7, 3], [0, 8, 4], [1, 9, 5]],
    )
    np.testing.assert_array_equal(
        np.fromfile(recorder.session_dir / "quality_aligned.i32", dtype="<i4").reshape(-1, 3),
        [[1, 7, 3], [0, 8, 4], [1, 9, 5]],
    )
    assert '"value":"device"' in (recorder.session_dir / "ifet_markers.jsonl").read_text()
    assert '"lsl_timestamp":100.1' in (
        recorder.session_dir / "neuroscope_markers.jsonl"
    ).read_text()
    with recorder.events_path.open(encoding="utf-8-sig", newline="") as handle:
        event_rows = list(csv.DictReader(handle))
    assert event_rows[0]["eeg_sample_index"] == "1"
    assert event_rows[0]["alignment_method"] == "nearest_lsl_timestamp"
    assert event_rows[0]["alignment_status"] == "aligned"
    assert event_rows[1]["eeg_sample_index"] == "-1"
    assert event_rows[1]["alignment_status"] == "outside_tolerance"
    session = json.loads(recorder.session_path.read_text(encoding="utf-8"))
    assert session["source_extra"] == {}
    assert session["timing_status"] == "lsl_software_sync_uncalibrated"
    assert session["quality_invalid_samples"] == 1
    assert session["timing_health"]["quality_valid_ratio"] == 2 / 3
    assert session["timing_health"]["quality_unmatched_samples"] == 0


def test_td10_recorder_rejects_nonmonotonic_authoritative_timeline(tmp_path: Path) -> None:
    metadata = SourceMetadata.eeg(
        "ifet-td10-headset:eeg",
        "td10_lsl",
        10.0,
        ("EEG1", "EEG2", "EEG3", "EEG4"),
        unit="ADC counts",
    )
    recorder = SessionRecorder.start(
        root_dir=tmp_path,
        participant_id="S02",
        paradigm="静息睁眼/闭眼",
        preset="完整采集",
        metadata=metadata,
    )
    timestamps = np.asarray([10.0, 9.9], dtype=np.float64)
    recorder.submit(EEGChunk(metadata, np.ones((4, 2)), timestamps, sequence=0))
    recorder.submit_sidecars(
        TD10Sidecars(eeg_timing=(EEGTimingBatch(0, timestamps, timestamps, 0.0),))
    )

    recorder.stop(status="completed", reason="completed")

    session = json.loads(recorder.session_path.read_text(encoding="utf-8"))
    assert session["status"] == "error"
    assert "严格递增" in session["error"]
    assert recorder.inprogress_path.exists()
    assert not recorder.final_path.exists()
