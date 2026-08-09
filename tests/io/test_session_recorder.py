import json
from pathlib import Path

import numpy as np
import pyedflib

from neuroscope_eeg.core.models import EEGChunk, SourceMetadata
from neuroscope_eeg.desktop.protocols import StimulusEvent
from neuroscope_eeg.io.session_recorder import SessionRecorder


def test_recorder_creates_session_immediately_and_writes_readable_bdf(tmp_path: Path) -> None:
    metadata = SourceMetadata.eeg("device-1", "neuracle", 10.0, ("Fp1", "Fp2"))
    recorder = SessionRecorder.start(
        root_dir=tmp_path,
        participant_id="S01",
        paradigm="2-back 工作记忆",
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
        StimulusEvent(12.0, 34.0, "2-back 工作记忆", "nback_trial", "7", {"is_practice": False}),
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


def test_recorder_rejects_unsafe_participant_id(tmp_path: Path) -> None:
    metadata = SourceMetadata.eeg("device-1", "neuracle", 10.0, ("Fp1",))

    try:
        SessionRecorder.start(
            root_dir=tmp_path,
            participant_id="../S01",
            paradigm="2-back 工作记忆",
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
    recorder.submit(
        EEGChunk(
            metadata=metadata,
            data=data,
            timestamps=np.arange(125, dtype=np.float64) / 125.0,
            sequence=0,
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
