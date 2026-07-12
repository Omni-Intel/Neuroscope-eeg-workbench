from pathlib import Path

from neuroscope_eeg.acquisition.replay import NPZReplaySource, save_replay_npz
from neuroscope_eeg.acquisition.simulated import SimulatedSource


def test_simulated_source_and_npz_replay_roundtrip(tmp_path: Path) -> None:
    source = SimulatedSource(sfreq=100.0, packet_sec=0.2, paced=False)
    source.start()
    chunk = source.read_chunk()
    source.stop()
    replay_path = tmp_path / "sample.npz"
    save_replay_npz(replay_path, source.metadata, chunk.data, chunk.timestamps)
    replay = NPZReplaySource(replay_path, packet_samples=7)
    replay.start()
    replay_chunk = replay.read_chunk()
    assert replay_chunk.data.shape == (source.metadata.n_channels, 7)
    assert replay_chunk.metadata.sfreq == 100.0
