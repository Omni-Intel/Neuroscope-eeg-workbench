from neuroscope_eeg.acquisition.simulated import SimulatedSource
from neuroscope_eeg.core.buffer import RollingBuffer


def test_rolling_buffer_keeps_recent_samples_only() -> None:
    source = SimulatedSource(sfreq=100.0, packet_sec=0.1, paced=False)
    source.start()
    buffer = RollingBuffer(source.metadata, duration_sec=0.25)
    for _ in range(5):
        buffer.append(source.read_chunk())
    data, timestamps = buffer.snapshot()
    assert data.shape == (source.metadata.n_channels, 25)
    assert timestamps.shape == (25,)


def test_latest_available_returns_partial_buffer_without_waiting() -> None:
    source = SimulatedSource(sfreq=100.0, packet_sec=0.1, paced=False)
    source.start()
    buffer = RollingBuffer(source.metadata, duration_sec=30.0)
    chunk = source.read_chunk()
    buffer.append(chunk)

    data, timestamps = buffer.latest_available(duration_sec=4.0)

    assert data.shape == (source.metadata.n_channels, 10)
    assert timestamps.shape == (10,)
