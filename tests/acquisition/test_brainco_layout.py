from realtime_eeg_viewer import BRAINCO_CHANNEL_NAMES_32, DEFAULT_64_CH_NAMES


def test_brainco_uses_official_32_channel_order() -> None:
    assert BRAINCO_CHANNEL_NAMES_32 == (
        "FP1",
        "FP2",
        "F3",
        "F4",
        "F7",
        "F8",
        "Fz",
        "C3",
        "C4",
        "Cz",
        "P3",
        "P4",
        "P7",
        "P8",
        "Pz",
        "O1",
        "O2",
        "T7",
        "T8",
        "FC1",
        "FC2",
        "FC5",
        "FC6",
        "CP1",
        "CP2",
        "CP5",
        "CP6",
        "FT9",
        "FT10",
        "TP9",
        "TP10",
        "IO",
    )


def test_neuracle_64_channel_layout_is_unchanged() -> None:
    assert len(DEFAULT_64_CH_NAMES) == 64
    assert DEFAULT_64_CH_NAMES[:5] == ["Fp1", "Fpz", "Fp2", "AF3", "AF4"]
    assert DEFAULT_64_CH_NAMES[-5:] == ["O2", "Iz", "AF7", "AF8", "PO10"]
