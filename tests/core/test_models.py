import numpy as np
import pytest

from mi_control.core.models import ConnectionState, EEGChunk, EEGEvent, SourceMetadata


def test_metadata_rejects_mismatched_channel_fields() -> None:
    with pytest.raises(ValueError, match="channel fields must have equal length"):
        SourceMetadata(
            source_id="sim-1",
            source_type="simulated",
            sfreq=250.0,
            channel_names=("C3", "C4"),
            channel_types=("eeg",),
            channel_units=("uV", "uV"),
        )


def test_chunk_requires_channel_major_data_and_timestamps() -> None:
    metadata = SourceMetadata.eeg("sim-1", "simulated", 250.0, ("C3", "C4"))
    with pytest.raises(ValueError, match="expected 2 channels"):
        EEGChunk(metadata=metadata, data=np.zeros((1, 10), np.float32), timestamps=np.arange(10), sequence=0)


def test_event_keeps_target_present_separate_from_seen_reported() -> None:
    event = EEGEvent(timestamp=1.5, name="stimulus", code=7, payload={"target_present": True, "seen_reported": False})
    assert event.payload["target_present"] is True
    assert event.payload["seen_reported"] is False


def test_connection_states_are_explicit() -> None:
    assert ConnectionState.RECONNECTING.value == "reconnecting"
