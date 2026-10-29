from types import SimpleNamespace

import numpy as np
import pytest

from neuroscope_eeg.acquisition import simulated


class Clock:
    def __init__(self):
        self.now = 100.0
        self.sleeps = []

    def sleep(self, seconds):
        assert seconds > 0
        self.sleeps.append(seconds)
        self.now += seconds + .001  # Repeatable scheduler overshoot.


def source_with_clock(monkeypatch, *, paced=True):
    clock = Clock()
    monkeypatch.setattr(simulated, "time", SimpleNamespace(monotonic=lambda: clock.now, sleep=clock.sleep))
    source = simulated.SimulatedSource(sfreq=250, packet_sec=.02, paced=paced)
    source.start()
    return source, clock


def test_processing_and_sleep_overhead_do_not_accumulate(monkeypatch):
    source, clock = source_with_clock(monkeypatch)
    chunks = []
    for _ in range(450):
        clock.now += .002  # Computation and consumer overhead between packets.
        chunks.append(source.read_chunk())
    assert clock.now - 100 == pytest.approx(9.001)
    assert sum(c.n_samples for c in chunks) == 2250
    assert [c.sequence for c in chunks] == list(range(0, 2250, 5))
    np.testing.assert_allclose(np.concatenate([c.timestamps for c in chunks]), np.arange(2250)/250)


def test_late_reader_catches_up_without_skipping_samples_and_restart_resets_clock(monkeypatch):
    source, clock = source_with_clock(monkeypatch)
    clock.now += .1
    chunks = [source.read_chunk() for _ in range(5)]
    assert clock.sleeps == []
    assert [c.sequence for c in chunks] == [0, 5, 10, 15, 20]
    source.read_chunk()
    assert clock.now == pytest.approx(100.121)
    source.stop()
    clock.now += 60
    origin = clock.now
    source.start()
    chunk = source.read_chunk()
    assert chunk.sequence == 0 and chunk.timestamps[0] == 0
    assert clock.now - origin == pytest.approx(.021)


def test_unpaced_generation_does_not_wait_or_change_signal(monkeypatch):
    source, clock = source_with_clock(monkeypatch, paced=False)
    fast = source.read_chunk()
    assert clock.sleeps == [] and clock.now == 100
    paced = simulated.SimulatedSource(sfreq=250, packet_sec=.02)
    paced.start()
    slow = paced.read_chunk()
    np.testing.assert_array_equal(fast.data, slow.data)
    np.testing.assert_array_equal(fast.timestamps, slow.timestamps)
