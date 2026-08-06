from neuroscope_eeg.acquisition.simulated import SimulatedSource
from neuroscope_eeg.core.models import EEGEvent, SourceMetadata
from neuroscope_eeg.paradigms.base import PARADIGMS


def test_all_paradigms_return_immediate_decoder_results() -> None:
    source = SimulatedSource(paced=False)
    source.start()
    chunks = [source.read_chunk() for _ in range(90)]
    data = __import__("numpy").concatenate([chunk.data for chunk in chunks], axis=1)
    event = EEGEvent(
        1.0,
        "visual_trial",
        "face",
        {
            "image_category": "face",
            "target_present": True,
            "seen_reported": False,
            "ssvep_targets": (8.0, 10.0, 12.0, 15.0),
        },
    )
    for paradigm in PARADIGMS.values():
        result = paradigm.analyze(source.metadata, data, (event,))
        assert result.status in {"estimated", "not_decoded"}
        assert result.decoder_name
        assert result.source == "即时基线估计"
        assert 0.0 <= result.confidence <= 1.0
        assert result.metrics


def test_visual_decoder_does_not_claim_image_category_prediction() -> None:
    source = SimulatedSource(paced=False)
    source.start()
    chunks = [source.read_chunk() for _ in range(90)]
    data = __import__("numpy").concatenate([chunk.data for chunk in chunks], axis=1)
    event = EEGEvent(1.0, "visual_trial", "face", {"image_category": "face", "target_present": True})

    result = PARADIGMS["视觉图像识别"].analyze(source.metadata, data, (event,))

    assert result.metrics["图像类别预测"] == "尚未解码"


def test_auditory_paradigms_are_registered_without_removing_existing_ones() -> None:
    assert tuple(PARADIGMS) == (
        "SSVEP",
        "运动想象",
        "视觉图像识别",
        "注意力",
        "情绪分类",
        "听觉 ASSR",
        "听觉 Oddball",
    )


def test_assr_decoder_finds_synthetic_40_hz_following() -> None:
    np = __import__("numpy")
    sfreq = 250.0
    metadata = SourceMetadata.eeg("headband", "headband", sfreq, ("Fp1", "Fp2", "Fpz", "T3", "T4"))
    time = np.arange(int(sfreq * 8.0)) / sfreq
    rng = np.random.default_rng(4)
    noise = rng.normal(0.0, 1.0, (5, time.size))
    signal = noise.copy()
    signal[3:] += 5.0 * np.sin(2.0 * np.pi * 40.0 * time)

    result = PARADIGMS["听觉 ASSR"].analyze(metadata, signal.astype(np.float32))

    assert result.status == "estimated"
    assert result.metrics["40 Hz SNR dB"] > 6.0
    assert "频率跟随" in result.headline


def test_oddball_decoder_refuses_erp_before_timing_calibration() -> None:
    np = __import__("numpy")
    metadata = SourceMetadata.eeg("headband", "headband", 250.0, ("Fp1", "Fp2", "Fpz", "T3", "T4"))
    event = EEGEvent(
        1.0,
        "stimulus_event",
        "deviant",
        {"timing_calibrated": False, "trials": 75, "targets": 15, "hits": 12, "false_alarms": 2},
    )

    result = PARADIGMS["听觉 Oddball"].analyze(metadata, np.zeros((5, 1000), np.float32), (event,))

    assert result.headline == "ERP 时序待校准"
    assert result.metrics["行为命中率"] == 0.8
    assert "事件标记" in result.detail
