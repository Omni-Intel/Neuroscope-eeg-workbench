import numpy as np

from neuroscope_eeg.core.models import SourceMetadata
from neuroscope_eeg.desktop.app import MAX_VISIBLE_CHANNELS, NeuroScopeWindow, task_channel_view


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


def test_live_waveform_keeps_all_configured_channels_for_fixed_paradigm() -> None:
    assert MAX_VISIBLE_CHANNELS == 64
    names = ("Fp1", "Fpz", "Fp2", "T7", "T8", "O1")
    metadata = SourceMetadata.eeg("test", "neuracle", 1000.0, names)
    data = np.ones((len(names), 10), dtype=np.float32)
    captured: dict[str, object] = {}

    class Text:
        @staticmethod
        def currentText() -> str:
            return "N-back 工作记忆"

    class Tabs:
        @staticmethod
        def currentIndex() -> int:
            return 0

    class FPS:
        @staticmethod
        def tick() -> None:
            return None

    class Harness:
        paradigm_select = Text()
        tabs = Tabs()
        _fps = FPS()
        controller = type("Controller", (), {"source": type("Source", (), {"metadata": metadata})()})()

        @staticmethod
        def _latest_data():
            return data, names, metadata.sfreq

        @staticmethod
        def _is_brainco() -> bool:
            return False

        @staticmethod
        def _apply_wave_data(values, channel_names, sfreq, independent_scale=False) -> None:
            captured.update(data=values, names=channel_names, sfreq=sfreq)

    harness = Harness()
    NeuroScopeWindow._refresh_waveform(harness)

    assert captured["data"] is data
    assert captured["names"] == names
    assert harness._analysis_data is data
    assert harness._analysis_metadata is metadata
