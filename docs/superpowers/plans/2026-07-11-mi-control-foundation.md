# MI Control Foundation and Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build plan 1 of 6: an independently installable MI Control package with unified EEG contracts, deterministic simulation and replay, signal-quality foundations, safe session control, and the approved Streamlit task-workbench layout.

**Architecture:** Device-specific sources emit the same immutable metadata, EEG chunks, and events into a thread-safe session controller. Analysis and quality functions consume only those contracts, while Streamlit renders stable monitoring, quality, paradigm, and recording tabs without importing vendor SDKs.

**Tech Stack:** Python 3.12, NumPy, SciPy, MNE, Matplotlib, Streamlit, Pytest, Ruff

---

## Scope and follow-up plans

This plan produces working software by itself but intentionally covers only the approved specification's foundation stage. The full goal remains split into these later plans:

1. Foundation and task workbench — this document.
2. Neuracle and BrainCo independent adapters plus Windows probe commands.
3. Production SSVEP and motor-imagery paradigm plugins.
4. Visual-category/target-awareness, attention, and emotion plugins.
5. Windows diagnostic bundles and two-device hardware acceptance loop.
6. Repository hardening, CI, documentation, and user-approved company GitHub publication.

Do not start a later plan by weakening the contracts in this plan. Do not add vendor SDKs, trained-model claims, or GitHub remotes in this foundation phase.

## File map

```text
pyproject.toml                         Package metadata and dependencies
mi_control/__init__.py                Public package version
mi_control/core/models.py             Immutable metadata, chunks, events, states
mi_control/core/buffer.py             Thread-safe fixed-duration EEG buffer
mi_control/core/session.py            Worker lifecycle and connection state machine
mi_control/acquisition/base.py        Source protocol
mi_control/acquisition/simulated.py   Deterministic simulated EEG source
mi_control/acquisition/replay.py      NPZ replay source
mi_control/preprocessing/basic.py     Reference, notch, and band-pass functions
mi_control/analysis/spectrum.py       PSD and band-power calculations
mi_control/analysis/quality.py        Per-window health metrics
mi_control/paradigms/base.py          Plugin and model-compatibility contracts
mi_control/io/diagnostic_bundle.py    Portable metadata and replay bundle
mi_control/diagnostics/environment.py Standard-library environment report
mi_control/ui/app.py                  Approved task-workbench UI
streamlit_app.py                      Backward-compatible Streamlit entrypoint
tests/...                             Unit, replay, and UI tests
README.md                             New package usage and current limitations
```

### Task 1: Bootstrap the installable package

**Files:**
- Create: `pyproject.toml`
- Create: `mi_control/__init__.py`
- Create: `tests/test_package.py`

- [ ] **Step 1: Write the failing import check**

Run:

```bash
python3.12 -c "import mi_control"
```

Expected: FAIL with `ModuleNotFoundError: No module named 'mi_control'`.

- [ ] **Step 2: Add package metadata and development tools**

Create `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=75", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "mi-control"
version = "0.1.0"
description = "Local realtime EEG workbench for Neuracle and BrainCo"
readme = "README.md"
requires-python = ">=3.12,<3.13"
dependencies = [
  "matplotlib>=3.8",
  "mne>=1.6",
  "numpy>=1.26",
  "scipy>=1.12",
  "streamlit>=1.30",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "ruff>=0.6",
]
brainco = ["bc-ecap-sdk"]

[project.scripts]
mi-control-doctor = "mi_control.diagnostics.environment:main"

[tool.setuptools.packages.find]
include = ["mi_control*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"

[tool.ruff]
line-length = 120
target-version = "py312"
```

Create `mi_control/__init__.py`:

```python
"""MI Control realtime EEG workbench."""

__version__ = "0.1.0"
```

Create `tests/test_package.py`:

```python
from mi_control import __version__


def test_package_version() -> None:
    assert __version__ == "0.1.0"
```

- [ ] **Step 3: Create the Python 3.12 environment and install locally**

Run:

```bash
python3.12 -m venv .venv312
.venv312/bin/python -m pip install -U pip setuptools wheel
.venv312/bin/python -m pip install -e '.[dev]'
```

Expected: installation completes and reports `Successfully installed mi-control`.

- [ ] **Step 4: Run the package smoke test**

Run:

```bash
.venv312/bin/python -m pytest tests/test_package.py -v
```

Expected: `1 passed`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml mi_control/__init__.py tests/test_package.py
git commit -m "build: bootstrap mi-control package"
```

### Task 2: Define canonical EEG data contracts

**Files:**
- Create: `mi_control/core/__init__.py`
- Create: `mi_control/core/models.py`
- Create: `tests/core/test_models.py`

- [ ] **Step 1: Write contract tests**

Create `tests/core/test_models.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
.venv312/bin/python -m pytest tests/core/test_models.py -v
```

Expected: FAIL because `mi_control.core.models` does not exist.

- [ ] **Step 3: Implement immutable contracts**

Create an empty `mi_control/core/__init__.py` and create `mi_control/core/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np
from numpy.typing import NDArray


class ConnectionState(str, Enum):
    UNCONFIGURED = "unconfigured"
    CONNECTING = "connecting"
    STREAMING = "streaming"
    DEGRADED = "degraded"
    RECONNECTING = "reconnecting"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    source_id: str
    source_type: str
    sfreq: float
    channel_names: tuple[str, ...]
    channel_types: tuple[str, ...]
    channel_units: tuple[str, ...]
    device_info: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.sfreq <= 0:
            raise ValueError("sfreq must be positive")
        lengths = {len(self.channel_names), len(self.channel_types), len(self.channel_units)}
        if len(lengths) != 1:
            raise ValueError("channel fields must have equal length")
        if not self.channel_names:
            raise ValueError("at least one channel is required")
        object.__setattr__(self, "device_info", MappingProxyType(dict(self.device_info)))

    @classmethod
    def eeg(cls, source_id: str, source_type: str, sfreq: float, channel_names: tuple[str, ...]) -> "SourceMetadata":
        count = len(channel_names)
        return cls(source_id, source_type, sfreq, channel_names, ("eeg",) * count, ("uV",) * count)

    @property
    def n_channels(self) -> int:
        return len(self.channel_names)


@dataclass(frozen=True, slots=True)
class EEGEvent:
    timestamp: float
    name: str
    code: int | None = None
    source: str = "software"
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


@dataclass(frozen=True, slots=True)
class EEGChunk:
    metadata: SourceMetadata
    data: NDArray[np.float32]
    timestamps: NDArray[np.float64]
    sequence: int
    events: tuple[EEGEvent, ...] = ()

    def __post_init__(self) -> None:
        data = np.asarray(self.data, dtype=np.float32)
        timestamps = np.asarray(self.timestamps, dtype=np.float64)
        if data.ndim != 2 or data.shape[0] != self.metadata.n_channels:
            raise ValueError(f"expected {self.metadata.n_channels} channels, got {data.shape}")
        if timestamps.ndim != 1 or timestamps.shape[0] != data.shape[1]:
            raise ValueError("timestamps must match the sample dimension")
        if timestamps.size > 1 and np.any(np.diff(timestamps) <= 0):
            raise ValueError("timestamps must be strictly increasing")
        if self.sequence < 0:
            raise ValueError("sequence must be non-negative")
        data.setflags(write=False)
        timestamps.setflags(write=False)
        object.__setattr__(self, "data", data)
        object.__setattr__(self, "timestamps", timestamps)
```

- [ ] **Step 4: Run contract tests**

Run:

```bash
.venv312/bin/python -m pytest tests/core/test_models.py -v
```

Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add mi_control/core tests/core/test_models.py
git commit -m "feat: define canonical EEG contracts"
```

### Task 3: Add the thread-safe rolling buffer

**Files:**
- Create: `mi_control/core/buffer.py`
- Create: `tests/core/test_buffer.py`

- [ ] **Step 1: Write buffer tests**

Create `tests/core/test_buffer.py`:

```python
import numpy as np

from mi_control.core.buffer import RollingBuffer
from mi_control.core.models import EEGChunk, SourceMetadata


META = SourceMetadata.eeg("sim", "simulated", 10.0, ("C3", "C4"))


def chunk(start: int, samples: int, sequence: int) -> EEGChunk:
    data = np.vstack((np.arange(start, start + samples), np.arange(start, start + samples) + 100)).astype(np.float32)
    timestamps = np.arange(start, start + samples, dtype=np.float64) / META.sfreq
    return EEGChunk(META, data, timestamps, sequence)


def test_buffer_keeps_only_capacity() -> None:
    buffer = RollingBuffer(META, capacity_samples=5)
    buffer.append(chunk(0, 3, 0))
    buffer.append(chunk(3, 4, 1))
    latest = buffer.latest(5)
    assert latest is not None
    np.testing.assert_array_equal(latest.data[0], [2, 3, 4, 5, 6])


def test_buffer_rejects_metadata_changes() -> None:
    buffer = RollingBuffer(META, capacity_samples=5)
    other = SourceMetadata.eeg("other", "simulated", 10.0, ("C3", "C4"))
    bad = EEGChunk(other, np.zeros((2, 1), np.float32), np.array([0.0]), 0)
    try:
        buffer.append(bad)
    except ValueError as exc:
        assert "metadata changed" in str(exc)
    else:
        raise AssertionError("metadata change should fail")
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv312/bin/python -m pytest tests/core/test_buffer.py -v`
Expected: FAIL because `RollingBuffer` is missing.

- [ ] **Step 3: Implement the buffer**

Create `mi_control/core/buffer.py`:

```python
from __future__ import annotations

from collections import deque
from threading import Lock

import numpy as np

from mi_control.core.models import EEGChunk, SourceMetadata


class RollingBuffer:
    def __init__(self, metadata: SourceMetadata, capacity_samples: int) -> None:
        if capacity_samples <= 0:
            raise ValueError("capacity_samples must be positive")
        self.metadata = metadata
        self.capacity_samples = capacity_samples
        self._chunks: deque[EEGChunk] = deque()
        self._sample_count = 0
        self._lock = Lock()

    def append(self, chunk: EEGChunk) -> None:
        if chunk.metadata != self.metadata:
            raise ValueError("source metadata changed during the session")
        with self._lock:
            self._chunks.append(chunk)
            self._sample_count += chunk.data.shape[1]
            while self._sample_count > self.capacity_samples:
                extra = self._sample_count - self.capacity_samples
                head = self._chunks[0]
                if head.data.shape[1] <= extra:
                    self._chunks.popleft()
                    self._sample_count -= head.data.shape[1]
                    continue
                trimmed = EEGChunk(
                    metadata=head.metadata,
                    data=head.data[:, extra:].copy(),
                    timestamps=head.timestamps[extra:].copy(),
                    sequence=head.sequence,
                    events=tuple(event for event in head.events if event.timestamp >= head.timestamps[extra]),
                )
                self._chunks[0] = trimmed
                self._sample_count -= extra

    def latest(self, sample_count: int) -> EEGChunk | None:
        with self._lock:
            if sample_count <= 0 or self._sample_count < sample_count:
                return None
            chunks = tuple(self._chunks)
        data = np.concatenate([item.data for item in chunks], axis=1)[:, -sample_count:]
        timestamps = np.concatenate([item.timestamps for item in chunks])[-sample_count:]
        events = tuple(event for item in chunks for event in item.events if event.timestamp >= timestamps[0])
        return EEGChunk(self.metadata, data, timestamps, chunks[-1].sequence, events)

    @property
    def sample_count(self) -> int:
        with self._lock:
            return self._sample_count
```

- [ ] **Step 4: Run buffer and contract tests**

Run: `.venv312/bin/python -m pytest tests/core/test_buffer.py tests/core/test_models.py -v`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add mi_control/core/buffer.py tests/core/test_buffer.py
git commit -m "feat: add thread-safe EEG rolling buffer"
```

### Task 4: Add the source protocol and deterministic simulator

**Files:**
- Create: `mi_control/acquisition/__init__.py`
- Create: `mi_control/acquisition/base.py`
- Create: `mi_control/acquisition/simulated.py`
- Create: `tests/acquisition/test_simulated.py`

- [ ] **Step 1: Write simulator tests**

Create `tests/acquisition/test_simulated.py`:

```python
import numpy as np

from mi_control.acquisition.simulated import SimulatedSource


def test_simulator_is_deterministic_and_timestamped() -> None:
    left = SimulatedSource(sfreq=250.0, channel_names=("C3", "C4", "Oz"), seed=17, packet_samples=25)
    right = SimulatedSource(sfreq=250.0, channel_names=("C3", "C4", "Oz"), seed=17, packet_samples=25)
    left.start()
    right.start()
    first = left.read()
    second = right.read()
    np.testing.assert_allclose(first.data, second.data)
    np.testing.assert_allclose(np.diff(first.timestamps), 1 / 250.0)
    assert first.sequence == 0


def test_simulator_injects_visible_occipital_ssvep() -> None:
    source = SimulatedSource(sfreq=250.0, channel_names=("C3", "C4", "Oz"), seed=17, packet_samples=1000, ssvep_hz=12.0)
    source.start()
    chunk = source.read()
    freqs = np.fft.rfftfreq(chunk.data.shape[1], 1 / 250.0)
    oz_power = np.abs(np.fft.rfft(chunk.data[2])) ** 2
    assert freqs[int(np.argmax(oz_power[1:]) + 1)] == 12.0
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv312/bin/python -m pytest tests/acquisition/test_simulated.py -v`
Expected: FAIL because acquisition modules do not exist.

- [ ] **Step 3: Define the protocol and simulator**

Create an empty `mi_control/acquisition/__init__.py` and `mi_control/acquisition/base.py`:

```python
from typing import Protocol

from mi_control.core.models import EEGChunk, SourceMetadata


class EEGSource(Protocol):
    @property
    def metadata(self) -> SourceMetadata: ...
    def start(self) -> None: ...
    def read(self) -> EEGChunk: ...
    def stop(self) -> None: ...
```

Create `mi_control/acquisition/simulated.py`:

```python
from __future__ import annotations

import time

import numpy as np

from mi_control.core.models import EEGChunk, SourceMetadata


class SimulatedSource:
    def __init__(
        self,
        sfreq: float = 250.0,
        channel_names: tuple[str, ...] = ("C3", "Cz", "C4", "O1", "Oz", "O2"),
        seed: int = 17,
        packet_samples: int = 25,
        ssvep_hz: float = 12.0,
        realtime: bool = False,
    ) -> None:
        self.metadata = SourceMetadata.eeg("simulated-1", "simulated", sfreq, channel_names)
        self._rng = np.random.default_rng(seed)
        self._packet_samples = packet_samples
        self._ssvep_hz = ssvep_hz
        self._realtime = realtime
        self._sample_index = 0
        self._running = False

    def start(self) -> None:
        self._sample_index = 0
        self._running = True

    def read(self) -> EEGChunk:
        if not self._running:
            raise RuntimeError("source is not started")
        index = np.arange(self._sample_index, self._sample_index + self._packet_samples)
        timestamps = index.astype(np.float64) / self.metadata.sfreq
        data = self._rng.normal(0.0, 3.0, (self.metadata.n_channels, self._packet_samples)).astype(np.float32)
        wave = np.sin(2 * np.pi * self._ssvep_hz * timestamps).astype(np.float32)
        for channel, name in enumerate(self.metadata.channel_names):
            if name.upper().startswith(("O", "PO")):
                data[channel] += 15.0 * wave
        sequence = self._sample_index // self._packet_samples
        self._sample_index += self._packet_samples
        if self._realtime:
            time.sleep(self._packet_samples / self.metadata.sfreq)
        return EEGChunk(self.metadata, data, timestamps, sequence)

    def stop(self) -> None:
        self._running = False
```

- [ ] **Step 4: Run simulator tests**

Run: `.venv312/bin/python -m pytest tests/acquisition/test_simulated.py -v`
Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add mi_control/acquisition tests/acquisition/test_simulated.py
git commit -m "feat: add deterministic EEG simulator"
```

### Task 5: Add portable NPZ replay

**Files:**
- Create: `mi_control/acquisition/replay.py`
- Create: `tests/acquisition/test_replay.py`
- Create: `tests/fixtures/.gitkeep`

- [ ] **Step 1: Write replay tests**

Create `tests/acquisition/test_replay.py`:

```python
from pathlib import Path

import numpy as np

from mi_control.acquisition.replay import ReplaySource


def test_replay_returns_ordered_packets(tmp_path: Path) -> None:
    path = tmp_path / "session.npz"
    np.savez(path, data=np.arange(20, dtype=np.float32).reshape(2, 10), sfreq=10.0, channel_names=np.array(["C3", "C4"]))
    source = ReplaySource(path, packet_samples=4)
    source.start()
    first = source.read()
    second = source.read()
    assert first.data.shape == (2, 4)
    assert second.sequence == 1
    np.testing.assert_array_equal(second.data[0], [4, 5, 6, 7])
```

- [ ] **Step 2: Run the test to verify failure**

Run: `.venv312/bin/python -m pytest tests/acquisition/test_replay.py -v`
Expected: FAIL because `ReplaySource` is missing.

- [ ] **Step 3: Implement replay with explicit end-of-stream**

Create `mi_control/acquisition/replay.py`:

```python
from pathlib import Path

import numpy as np

from mi_control.core.models import EEGChunk, SourceMetadata


class ReplaySource:
    def __init__(self, path: Path, packet_samples: int = 25) -> None:
        payload = np.load(path, allow_pickle=False)
        self._data = np.asarray(payload["data"], dtype=np.float32)
        names = tuple(str(item) for item in payload["channel_names"])
        self.metadata = SourceMetadata.eeg(path.stem, "replay", float(payload["sfreq"]), names)
        if self._data.ndim != 2 or self._data.shape[0] != self.metadata.n_channels:
            raise ValueError("replay data does not match channel metadata")
        self._packet_samples = packet_samples
        self._cursor = 0

    def start(self) -> None:
        self._cursor = 0

    def read(self) -> EEGChunk:
        if self._cursor >= self._data.shape[1]:
            raise EOFError("replay completed")
        stop = min(self._cursor + self._packet_samples, self._data.shape[1])
        indices = np.arange(self._cursor, stop)
        chunk = EEGChunk(
            self.metadata,
            self._data[:, self._cursor:stop].copy(),
            indices.astype(np.float64) / self.metadata.sfreq,
            self._cursor // self._packet_samples,
        )
        self._cursor = stop
        return chunk

    def stop(self) -> None:
        self._cursor = self._data.shape[1]
```

Create the empty fixture-directory marker:

```bash
mkdir -p tests/fixtures
touch tests/fixtures/.gitkeep
```

- [ ] **Step 4: Run acquisition tests**

Run: `.venv312/bin/python -m pytest tests/acquisition -v`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add mi_control/acquisition/replay.py tests/acquisition/test_replay.py tests/fixtures/.gitkeep
git commit -m "feat: add portable EEG replay source"
```

### Task 6: Extract preprocessing and spectral analysis

**Files:**
- Create: `mi_control/preprocessing/__init__.py`
- Create: `mi_control/preprocessing/basic.py`
- Create: `mi_control/analysis/__init__.py`
- Create: `mi_control/analysis/spectrum.py`
- Create: `tests/analysis/test_spectrum.py`

- [ ] **Step 1: Write numerical tests**

Create `tests/analysis/test_spectrum.py`:

```python
import numpy as np

from mi_control.analysis.spectrum import BAND_LIMITS, band_power_db, power_spectrum
from mi_control.preprocessing.basic import common_average_reference


def test_common_average_reference_has_zero_instantaneous_mean() -> None:
    data = np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
    referenced = common_average_reference(data)
    np.testing.assert_allclose(referenced.mean(axis=0), 0.0)


def test_spectrum_finds_12_hz_peak() -> None:
    sfreq = 250.0
    t = np.arange(1000) / sfreq
    data = np.vstack([np.sin(2 * np.pi * 12 * t), np.sin(2 * np.pi * 12 * t)]).astype(np.float32)
    freqs, psd = power_spectrum(data, sfreq, max_hz=45.0)
    peak = freqs[int(np.argmax(psd.mean(axis=0)[1:]) + 1)]
    assert peak == 12.0
    assert band_power_db(freqs, psd)["alpha"].shape == (2,)


def test_band_definitions_do_not_overlap() -> None:
    for left, right in zip(BAND_LIMITS, BAND_LIMITS[1:]):
        assert left[2] == right[1]
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv312/bin/python -m pytest tests/analysis/test_spectrum.py -v`
Expected: FAIL because preprocessing and analysis modules are missing.

- [ ] **Step 3: Implement the minimal functions**

Create empty package `__init__.py` files and `mi_control/preprocessing/basic.py`:

```python
import numpy as np
from numpy.typing import NDArray


def common_average_reference(data: NDArray[np.floating]) -> NDArray[np.float32]:
    array = np.asarray(data, dtype=np.float32)
    return np.asarray(array - array.mean(axis=0, keepdims=True), dtype=np.float32)
```

Create `mi_control/analysis/spectrum.py`:

```python
import numpy as np
from numpy.typing import NDArray

BAND_LIMITS = (
    ("delta", 1.0, 4.0),
    ("theta", 4.0, 8.0),
    ("alpha", 8.0, 13.0),
    ("beta", 13.0, 30.0),
    ("gamma", 30.0, 45.0),
)


def power_spectrum(data: NDArray[np.floating], sfreq: float, max_hz: float) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    centered = np.nan_to_num(np.asarray(data, dtype=np.float32) - np.mean(data, axis=1, keepdims=True))
    window = np.hanning(centered.shape[1])
    spectrum = np.abs(np.fft.rfft(centered * window[None, :], axis=1)) ** 2
    freqs = np.fft.rfftfreq(centered.shape[1], 1.0 / sfreq)
    mask = freqs <= max_hz
    return freqs[mask], spectrum[:, mask]


def band_power_db(freqs: NDArray[np.float64], spectrum: NDArray[np.float64]) -> dict[str, NDArray[np.float64]]:
    result: dict[str, NDArray[np.float64]] = {}
    for name, low, high in BAND_LIMITS:
        mask = (freqs >= low) & (freqs < high)
        if not np.any(mask):
            raise ValueError(f"spectrum has no bins for {name}")
        result[name] = 10.0 * np.log10(np.mean(spectrum[:, mask], axis=1) + 1e-12)
    return result
```

- [ ] **Step 4: Run analysis tests**

Run: `.venv312/bin/python -m pytest tests/analysis/test_spectrum.py -v`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add mi_control/preprocessing mi_control/analysis tests/analysis/test_spectrum.py
git commit -m "feat: add reusable EEG spectral analysis"
```

### Task 7: Compute auditable signal-quality metrics

**Files:**
- Create: `mi_control/analysis/quality.py`
- Create: `tests/analysis/test_quality.py`

- [ ] **Step 1: Write quality tests**

Create `tests/analysis/test_quality.py`:

```python
import numpy as np

from mi_control.analysis.quality import assess_quality


def test_quality_flags_flat_and_nonfinite_channels() -> None:
    data = np.vstack((np.zeros(250), np.ones(250), np.linspace(-5, 5, 250))).astype(np.float32)
    data[1, 10] = np.nan
    report = assess_quality(data, sfreq=250.0)
    assert report.flat_channels == (0,)
    assert report.nonfinite_channels == (1,)
    assert report.rms_uv.shape == (3,)


def test_quality_reports_measured_sample_rate() -> None:
    timestamps = np.arange(250, dtype=np.float64) / 250.0
    report = assess_quality(np.ones((2, 250), np.float32), sfreq=250.0, timestamps=timestamps)
    assert abs(report.measured_sfreq - 250.0) < 1e-6
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv312/bin/python -m pytest tests/analysis/test_quality.py -v`
Expected: FAIL because quality analysis is missing.

- [ ] **Step 3: Implement the quality report**

Create `mi_control/analysis/quality.py`:

```python
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class QualityReport:
    rms_uv: NDArray[np.float64]
    flat_channels: tuple[int, ...]
    nonfinite_channels: tuple[int, ...]
    measured_sfreq: float | None


def assess_quality(
    data: NDArray[np.floating],
    sfreq: float,
    timestamps: NDArray[np.float64] | None = None,
) -> QualityReport:
    array = np.asarray(data, dtype=np.float32)
    nonfinite = tuple(int(index) for index in np.flatnonzero(~np.isfinite(array).all(axis=1)))
    safe = np.nan_to_num(array)
    centered = safe - safe.mean(axis=1, keepdims=True)
    rms = np.sqrt(np.mean(centered.astype(np.float64) ** 2, axis=1))
    flat = tuple(int(index) for index in np.flatnonzero(rms < 1e-6))
    measured = None
    if timestamps is not None and len(timestamps) > 1:
        measured = float(1.0 / np.median(np.diff(timestamps)))
    return QualityReport(rms, flat, nonfinite, measured)
```

- [ ] **Step 4: Run quality tests**

Run: `.venv312/bin/python -m pytest tests/analysis/test_quality.py -v`
Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add mi_control/analysis/quality.py tests/analysis/test_quality.py
git commit -m "feat: report auditable EEG signal quality"
```

### Task 8: Define paradigm and model compatibility gates

**Files:**
- Create: `mi_control/paradigms/__init__.py`
- Create: `mi_control/paradigms/base.py`
- Create: `tests/paradigms/test_base.py`

- [ ] **Step 1: Write compatibility tests**

Create `tests/paradigms/test_base.py`:

```python
from mi_control.core.models import SourceMetadata
from mi_control.paradigms.base import ModelManifest, ParadigmRequirements, validate_requirements


def test_missing_required_channels_blocks_analysis() -> None:
    metadata = SourceMetadata.eeg("sim", "simulated", 250.0, ("C3", "C4"))
    errors = validate_requirements(metadata, ParadigmRequirements(required_channels=("O1", "Oz", "O2")))
    assert errors == ("missing channels: O1, Oz, O2",)


def test_model_label_mismatch_is_explicit() -> None:
    metadata = SourceMetadata.eeg("sim", "simulated", 250.0, ("C3", "C4"))
    manifest = ModelManifest("mi-v1", 250.0, ("C3", "C4"), ("left", "right"))
    assert manifest.validate(metadata, expected_labels=("left", "right", "idle")) == ("model labels do not match the paradigm",)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv312/bin/python -m pytest tests/paradigms/test_base.py -v`
Expected: FAIL because paradigm contracts are missing.

- [ ] **Step 3: Implement requirement and manifest validation**

Create an empty `mi_control/paradigms/__init__.py` and `mi_control/paradigms/base.py`:

```python
from dataclasses import dataclass

from mi_control.core.models import SourceMetadata


@dataclass(frozen=True, slots=True)
class ParadigmRequirements:
    required_channels: tuple[str, ...] = ()
    min_sfreq: float = 1.0
    required_events: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ModelManifest:
    model_id: str
    sfreq: float
    channel_names: tuple[str, ...]
    labels: tuple[str, ...]

    def validate(self, metadata: SourceMetadata, expected_labels: tuple[str, ...]) -> tuple[str, ...]:
        errors: list[str] = []
        if self.sfreq != metadata.sfreq:
            errors.append("model sample rate does not match the source")
        if self.channel_names != metadata.channel_names:
            errors.append("model channels do not match the source")
        if self.labels != expected_labels:
            errors.append("model labels do not match the paradigm")
        return tuple(errors)


def validate_requirements(metadata: SourceMetadata, requirements: ParadigmRequirements) -> tuple[str, ...]:
    errors: list[str] = []
    missing = [name for name in requirements.required_channels if name not in metadata.channel_names]
    if missing:
        errors.append(f"missing channels: {', '.join(missing)}")
    if metadata.sfreq < requirements.min_sfreq:
        errors.append(f"sample rate must be at least {requirements.min_sfreq:g} Hz")
    return tuple(errors)
```

- [ ] **Step 4: Run compatibility tests**

Run: `.venv312/bin/python -m pytest tests/paradigms/test_base.py -v`
Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add mi_control/paradigms tests/paradigms/test_base.py
git commit -m "feat: gate paradigm and model compatibility"
```

### Task 9: Add safe session lifecycle management

**Files:**
- Create: `mi_control/core/session.py`
- Create: `tests/core/test_session.py`

- [ ] **Step 1: Write lifecycle tests**

Create `tests/core/test_session.py`:

```python
import time

from mi_control.acquisition.simulated import SimulatedSource
from mi_control.core.models import ConnectionState
from mi_control.core.session import SessionController


def test_session_starts_collects_and_stops() -> None:
    source = SimulatedSource(packet_samples=25)
    controller = SessionController(source, buffer_seconds=2.0)
    controller.start()
    deadline = time.monotonic() + 1.0
    while controller.buffer.sample_count == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert controller.state is ConnectionState.STREAMING
    assert controller.buffer.sample_count > 0
    controller.stop()
    assert controller.state is ConnectionState.STOPPED
    assert not controller.worker_alive
```

- [ ] **Step 2: Run the test to verify failure**

Run: `.venv312/bin/python -m pytest tests/core/test_session.py -v`
Expected: FAIL because `SessionController` is missing.

- [ ] **Step 3: Implement the minimal controller**

Create `mi_control/core/session.py`:

```python
from __future__ import annotations

from threading import Event, Lock, Thread

from mi_control.acquisition.base import EEGSource
from mi_control.core.buffer import RollingBuffer
from mi_control.core.models import ConnectionState


class SessionController:
    def __init__(self, source: EEGSource, buffer_seconds: float = 30.0) -> None:
        self.source = source
        self.buffer = RollingBuffer(source.metadata, int(round(buffer_seconds * source.metadata.sfreq)))
        self.state = ConnectionState.UNCONFIGURED
        self.error: str | None = None
        self._stop = Event()
        self._worker: Thread | None = None
        self._lock = Lock()

    def start(self) -> None:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                raise RuntimeError("session is already running")
            self.state = ConnectionState.CONNECTING
            self.error = None
            self._stop.clear()
            self._worker = Thread(target=self._run, daemon=True)
            self._worker.start()

    def _run(self) -> None:
        try:
            self.source.start()
            self.state = ConnectionState.STREAMING
            while not self._stop.is_set():
                self.buffer.append(self.source.read())
        except EOFError:
            self.state = ConnectionState.STOPPED
        except Exception as exc:
            self.error = str(exc)
            self.state = ConnectionState.FAILED
        finally:
            self.source.stop()

    def stop(self) -> None:
        self._stop.set()
        worker = self._worker
        if worker is not None:
            worker.join(timeout=2.0)
        if worker is not None and worker.is_alive():
            raise RuntimeError("source worker did not stop")
        self.state = ConnectionState.STOPPED

    @property
    def worker_alive(self) -> bool:
        return self._worker is not None and self._worker.is_alive()
```

- [ ] **Step 4: Run lifecycle tests**

Run: `.venv312/bin/python -m pytest tests/core/test_session.py -v`
Expected: `1 passed`.

- [ ] **Step 5: Commit**

```bash
git add mi_control/core/session.py tests/core/test_session.py
git commit -m "feat: add safe EEG session lifecycle"
```

### Task 10: Build the approved Streamlit task workbench

**Files:**
- Create: `mi_control/ui/__init__.py`
- Create: `mi_control/ui/app.py`
- Modify: `streamlit_app.py`
- Create: `tests/ui/test_app.py`

- [ ] **Step 1: Write a UI structure test**

Create `tests/ui/test_app.py`:

```python
from streamlit.testing.v1 import AppTest


def test_workbench_has_approved_navigation() -> None:
    app = AppTest.from_file("streamlit_app.py").run(timeout=10)
    assert not app.exception
    assert app.title[0].value == "MI Control"
    assert app.selectbox(key="source_type").value == "模拟"
    assert app.selectbox(key="paradigm").value == "SSVEP"
    assert [tab.label for tab in app.tabs] == ["实时监控", "信号质量", "范式分析", "记录"]
```

- [ ] **Step 2: Run the test to verify failure**

Run: `.venv312/bin/python -m pytest tests/ui/test_app.py -v`
Expected: FAIL because the current app does not expose the approved structure.

- [ ] **Step 3: Create the workbench shell**

Create an empty `mi_control/ui/__init__.py` and `mi_control/ui/app.py`:

```python
import streamlit as st

from mi_control.acquisition.simulated import SimulatedSource
from mi_control.core.session import SessionController

SOURCE_LABELS = ("模拟", "博睿康 Neuracle", "强脑 BrainCo", "诊断包回放")
PARADIGMS = ("SSVEP", "运动想象", "视觉图像与目标觉察", "注意力", "情绪分类")


def render_sidebar() -> tuple[str, str]:
    with st.sidebar:
        st.header("会话设置")
        source_type = st.selectbox("数据源", SOURCE_LABELS, key="source_type")
        paradigm = st.selectbox("范式", PARADIGMS, key="paradigm")
        st.text_input("受试者编号", key="subject_id")
        st.text_input("会话编号", key="session_id")
        start, stop = st.columns(2)
        if start.button("开始", type="primary", width="stretch"):
            if source_type != "模拟":
                st.error("该设备适配器将在设备独立化阶段启用。")
            else:
                controller = SessionController(SimulatedSource(realtime=True))
                controller.start()
                st.session_state.controller = controller
        if stop.button("停止", width="stretch"):
            controller = st.session_state.get("controller")
            if controller is not None:
                controller.stop()
            st.session_state.controller = None
    return source_type, paradigm


def render_app() -> None:
    st.set_page_config(page_title="MI Control", layout="wide")
    st.title("MI Control")
    source_type, paradigm = render_sidebar()
    controller = st.session_state.get("controller")
    if controller is None:
        st.info(f"已选择 {source_type} / {paradigm}，点击开始进入采集。")
    else:
        st.success(
            f"{controller.state.value} · {controller.source.metadata.sfreq:g} Hz · "
            f"{controller.source.metadata.n_channels} ch"
        )
    monitoring, quality, analysis, recording = st.tabs(("实时监控", "信号质量", "范式分析", "记录"))
    with monitoring:
        st.subheader("实时波形与频谱")
    with quality:
        st.subheader("设备与通道质量")
    with analysis:
        st.subheader(f"{paradigm} 分析")
        st.caption("未加载验证模型时仅显示信号特征。")
    with recording:
        st.subheader("会话记录与诊断导出")
```

Replace `streamlit_app.py` with:

```python
#!/usr/bin/env python3
from mi_control.ui.app import render_app


if __name__ == "__main__":
    render_app()
```

- [ ] **Step 4: Run the UI test and launch smoke test**

Run:

```bash
.venv312/bin/python -m pytest tests/ui/test_app.py -v
.venv312/bin/streamlit run streamlit_app.py --server.headless true
```

Expected: test passes; Streamlit prints a local URL and the page renders four tabs without exceptions. Stop the smoke server with `Ctrl-C`.

- [ ] **Step 5: Commit**

```bash
git add mi_control/ui streamlit_app.py tests/ui/test_app.py
git commit -m "feat: add MI Control task workbench"
```

### Task 11: Add environment reporting and diagnostic bundles

**Files:**
- Create: `mi_control/diagnostics/__init__.py`
- Create: `mi_control/diagnostics/environment.py`
- Create: `mi_control/io/__init__.py`
- Create: `mi_control/io/diagnostic_bundle.py`
- Create: `tests/diagnostics/test_environment.py`
- Create: `tests/io/test_diagnostic_bundle.py`

- [ ] **Step 1: Write environment and bundle tests**

Create `tests/diagnostics/test_environment.py`:

```python
from mi_control.diagnostics.environment import environment_report


def test_environment_report_is_serializable() -> None:
    report = environment_report()
    assert report["python"].startswith("3.12.")
    assert report["platform"]
    assert isinstance(report["dependencies"]["numpy"], bool)
```

Create `tests/io/test_diagnostic_bundle.py`:

```python
from pathlib import Path

import numpy as np

from mi_control.core.models import EEGChunk, SourceMetadata
from mi_control.io.diagnostic_bundle import read_bundle, write_bundle


def test_bundle_round_trips_without_direct_identity(tmp_path: Path) -> None:
    metadata = SourceMetadata.eeg("brainco-device", "brainco", 250.0, ("C3", "C4"))
    chunk = EEGChunk(metadata, np.ones((2, 10), np.float32), np.arange(10) / 250.0, 0)
    path = write_bundle(tmp_path / "bundle", chunk, {"subject_name": "must-not-leak", "sample_rate_error": 0.0})
    replay, summary = read_bundle(path)
    assert replay.data.shape == (2, 10)
    assert "subject_name" not in summary
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
.venv312/bin/python -m pytest tests/diagnostics/test_environment.py tests/io/test_diagnostic_bundle.py -v
```

Expected: FAIL because diagnostics and bundle modules are missing.

- [ ] **Step 3: Implement environment and bundle helpers**

Create empty package `__init__.py` files and `mi_control/diagnostics/environment.py`:

```python
import importlib.util
import json
import platform
import sys


def environment_report() -> dict[str, object]:
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "executable": sys.executable,
        "dependencies": {
            name: importlib.util.find_spec(name) is not None
            for name in ("numpy", "scipy", "mne", "streamlit", "bc_ecap_sdk")
        },
    }


def main() -> None:
    print(json.dumps(environment_report(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

Create `mi_control/io/diagnostic_bundle.py`:

```python
import json
from pathlib import Path

import numpy as np

from mi_control.core.models import EEGChunk, SourceMetadata

ALLOWED_SUMMARY_FIELDS = {"sample_rate_error", "dropped_samples", "timestamp_reversals", "duration_sec"}


def write_bundle(directory: Path, chunk: EEGChunk, summary: dict[str, object]) -> Path:
    directory.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(
        directory / "replay.npz",
        data=chunk.data,
        sfreq=chunk.metadata.sfreq,
        channel_names=np.asarray(chunk.metadata.channel_names),
    )
    safe_summary = {key: summary[key] for key in ALLOWED_SUMMARY_FIELDS if key in summary}
    (directory / "summary.json").write_text(json.dumps(safe_summary, indent=2), encoding="utf-8")
    return directory


def read_bundle(directory: Path) -> tuple[EEGChunk, dict[str, object]]:
    payload = np.load(directory / "replay.npz", allow_pickle=False)
    names = tuple(str(item) for item in payload["channel_names"])
    metadata = SourceMetadata.eeg(directory.name, "replay", float(payload["sfreq"]), names)
    data = np.asarray(payload["data"], dtype=np.float32)
    timestamps = np.arange(data.shape[1], dtype=np.float64) / metadata.sfreq
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    return EEGChunk(metadata, data, timestamps, 0), summary
```

- [ ] **Step 4: Run diagnostics tests**

Run:

```bash
.venv312/bin/python -m pytest tests/diagnostics/test_environment.py tests/io/test_diagnostic_bundle.py -v
.venv312/bin/mi-control-doctor
```

Expected: `2 passed`; doctor prints JSON with Python, platform, executable, and dependency booleans.

- [ ] **Step 5: Commit**

```bash
git add mi_control/diagnostics mi_control/io tests/diagnostics tests/io
git commit -m "feat: add environment and diagnostic bundle tools"
```

### Task 12: Replace prototype documentation and verify the foundation

**Files:**
- Modify: `README.md`
- Modify: `.gitignore`
- Remove: `requirements.txt`
- Remove: `requirements-brainco.txt`
- Retain temporarily: `realtime_eeg_viewer.py`
- Test: all tests under `tests/`

- [ ] **Step 1: Replace README with verified foundation instructions**

Document exactly these commands and boundaries:

````markdown
# MI Control

Local EEG workbench for simulated data, diagnostic replay, Neuracle, and BrainCo.

## Foundation status

The foundation currently supports deterministic simulation, NPZ replay, signal-quality primitives, and the Streamlit task workbench. Neuracle and BrainCo adapters will be migrated and hardware-validated in later plans; do not claim either device is validated from the macOS simulator.

## Development

```bash
python3.12 -m venv .venv312
.venv312/bin/python -m pip install -e '.[dev]'
.venv312/bin/python -m pytest
.venv312/bin/streamlit run streamlit_app.py
```

## Windows

Create a separate Python 3.12 virtual environment on the acquisition computer. Never copy a macOS virtual environment to Windows.

## Safety of analysis results

Feature views may run without a model. Classification results appear only when the model manifest matches channels, sample rate, and labels.
````

- [ ] **Step 2: Consolidate dependency and ignored-path policy**

Delete `requirements.txt` and `requirements-brainco.txt`; `pyproject.toml` becomes the only dependency source. Ensure `.gitignore` contains:

```gitignore
.venv/
.venv312/
__pycache__/
*.pyc
outputs/
.superpowers/
.DS_Store
```

Keep `realtime_eeg_viewer.py` in this phase as an explicitly documented legacy reference. Remove it only after the full workbench reproduces its topomap and SSVEP behavior in plan 3.

- [ ] **Step 3: Run the complete foundation verification**

Run:

```bash
.venv312/bin/python -m ruff check mi_control tests streamlit_app.py
.venv312/bin/python -m pytest -v
.venv312/bin/python -m pip check
.venv312/bin/mi-control-doctor
git diff --check
```

Expected:

- Ruff reports `All checks passed!`;
- all tests pass;
- pip reports `No broken requirements found.`;
- doctor JSON reports Python `3.12.x` and all foundation dependencies as available;
- `git diff --check` prints nothing.

- [ ] **Step 4: Run a real browser smoke test**

Run:

```bash
.venv312/bin/streamlit run streamlit_app.py --server.headless true --server.port 8501
```

Verify in a browser:

- page title is `MI Control`;
- A-layout sidebar contains source, paradigm, subject, session, start, and stop;
- the four approved tabs are visible without horizontal clipping at 1280x720;
- simulated start changes the top status to `streaming`;
- stop changes it to `stopped` and leaves no source worker running;
- selecting a hardware source shows a truthful “later device-adapter phase” message.

Stop the server with `Ctrl-C`.

- [ ] **Step 5: Commit the completed foundation**

```bash
git add README.md .gitignore pyproject.toml mi_control tests streamlit_app.py realtime_eeg_viewer.py
git commit -m "feat: establish MI Control foundation"
```

After this commit, inspect `git status --short`. Expected: no untracked product files and no modified files. Do not add a remote or push.

## Plan self-check matrix

| Approved design requirement | Foundation task |
|---|---|
| Independent Python package and Python 3.12 | Task 1 |
| Immutable metadata, chunk, event contracts | Task 2 |
| Thread-safe rolling buffer | Task 3 |
| Deterministic simulation | Task 4 |
| Portable replay | Task 5 |
| Shared preprocessing and spectrum | Task 6 |
| Auditable quality primitives | Task 7 |
| No-model and incompatibility gates | Task 8 |
| Safe start/stop lifecycle | Task 9 |
| Approved A task-workbench shell | Task 10 |
| Environment report and diagnostic bundle base | Task 11 |
| Reproducible docs and full QA | Task 12 |

Neuracle/BrainCo vendor logic, complete paradigm algorithms, Windows hardware evidence, and GitHub publication are deliberately assigned to plans 2–6 rather than partially implemented here.
