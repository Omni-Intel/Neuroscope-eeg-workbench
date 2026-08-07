import numpy as np

from neuroscope_eeg.core.models import SourceMetadata
from neuroscope_eeg.desktop.app import task_channel_view


def test_neuracle_fixed_pilot_view_selects_only_five_target_channels() -> None:
    names = ("C3", "Fp2", "T8", "Fp1", "Fpz", "T7", "O1")
    metadata = SourceMetadata.eeg("test", "neuracle", 1000.0, names)
    data = np.arange(len(names) * 10, dtype=np.float32).reshape(len(names), 10)

    selected, selected_metadata = task_channel_view(data, metadata, "听觉 Oddball")

    assert selected_metadata.channel_names == ("Fp1", "Fpz", "Fp2", "T7", "T8")
    assert np.array_equal(selected, data[[3, 4, 1, 5, 2]])


def test_task_channel_view_keeps_full_stream_for_other_sources_and_paradigms() -> None:
    metadata = SourceMetadata.eeg("test", "neuracle", 1000.0, ("Fp1", "Fpz", "Fp2", "T7", "T8", "O1"))
    data = np.ones((6, 10), dtype=np.float32)

    selected, selected_metadata = task_channel_view(data, metadata, "SSVEP")

    assert selected is data
    assert selected_metadata is metadata
