from mi_control.acquisition.simulated import SimulatedSource
from mi_control.core.models import EEGEvent
from mi_control.paradigms.base import PARADIGMS


def test_all_paradigms_return_feature_results() -> None:
    source = SimulatedSource(paced=False)
    source.start()
    chunks = [source.read_chunk() for _ in range(90)]
    data = __import__("numpy").concatenate([chunk.data for chunk in chunks], axis=1)
    event = EEGEvent(1.0, "visual_trial", "face", {"target_present": True, "seen_reported": False})
    for paradigm in PARADIGMS.values():
        result = paradigm.analyze(source.metadata, data, (event,))
        assert result.status == "features"
        assert result.metrics
