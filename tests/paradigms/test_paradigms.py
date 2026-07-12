from neuroscope_eeg.acquisition.simulated import SimulatedSource
from neuroscope_eeg.core.models import EEGEvent
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
