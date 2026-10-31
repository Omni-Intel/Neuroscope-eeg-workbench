import json

import numpy as np
import pytest

from neuroscope_eeg.core.models import EEGChunk, SourceMetadata
from neuroscope_eeg.io.brainco_triggers import read_brainco_triggers
from neuroscope_eeg.io.native_recording import NativeRecorder, read_native


def recording(tmp_path):
    meta = SourceMetadata.eeg("brainco", "brainco", 250, ("CH1", "CH2"))
    recorder = NativeRecorder.start(root_dir=tmp_path, participant_id="00000001", paradigm="运动想象",
        preset="完整采集", metadata=meta, paradigm_code="MI-20261031", unique_name="TEST-20261031",
        source_sample_offset=23790, config={"experiment_metadata": {
            "full_name": "Offline BrainCo fixture", "unique_name": "TEST-20261031", "description": "Synthetic"}})
    return recorder, meta


def test_first_saved_sample_defines_origin_even_after_empty_trigger_chunk(tmp_path):
    recorder, meta = recording(tmp_path)
    event = {"event_seq": 7, "sample_counter": 88888, "source_tick": 123}
    # Trigger reception can happen on a poll without EEG. It must survive saving.
    recorder.submit(EEGChunk(meta, np.empty((2, 0)), np.array([]), 23790,
        auxiliaries={"brainco_trigger_events_json": np.asarray(json.dumps([event]))}))
    indices = np.arange(23970, 23980)
    data = np.arange(20, dtype=np.float32).reshape(2, 10)
    recorder.submit(EEGChunk(meta, data, indices/250, 23970, indices))
    recorder.stop(status="completed", reason="offline test")
    run, _, saved = read_native(recorder.session_dir)
    assert run["requested_source_sample_offset"] == 23790
    assert run["source_sample_offset"] == recorder.source_sample_offset == 23970
    assert run["source_sample_offset_basis"] == "first_saved_sample_index"
    assert run["samples"] == 10 and not run["continuity_errors"]
    np.testing.assert_array_equal(saved.T, data)
    evidence = read_brainco_triggers(recorder.session_dir)
    assert evidence["summary"]["received_events"] == 1
    assert evidence["summary"]["physical_onset_calibrated"] is False
    assert evidence["records"][0]["sample_counter"] == 88888
    assert "code" not in evidence["records"][0]
    assert "sample_index" not in evidence["records"][0]


def test_sequence_fallback_and_empty_record_origin(tmp_path):
    recorder, meta = recording(tmp_path)
    recorder.submit(EEGChunk(meta, np.ones((2, 2)), np.arange(2)/250, 91))
    recorder.stop(status="completed", reason="offline test")
    assert read_native(recorder.session_dir)[0]["source_sample_offset"] == 91
    assert read_brainco_triggers(recorder.session_dir)["summary"]["received_events"] == 0


def test_bad_trigger_records_are_not_silently_reported_as_zero(tmp_path):
    recorder, meta = recording(tmp_path)
    recorder.submit(EEGChunk(meta, np.ones((2, 2)), np.arange(2)/250, 0,
        auxiliaries={"brainco_trigger_events_json": np.asarray('{"event_seq": 1}')}))
    recorder.stop(status="completed", reason="offline test")
    with pytest.raises(ValueError, match="BrainCo trigger record invalid"):
        read_brainco_triggers(recorder.session_dir)
