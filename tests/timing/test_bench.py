from pathlib import Path

import pytest

from neuroscope_eeg.timing.bench import BENCH_CODES, run_trigger_bench, write_bench_results
from neuroscope_eeg.timing.codebook import EVENT_CODES
from neuroscope_eeg.timing.models import HardwareWrite


class FakeTransport:
    def __init__(self) -> None:
        self.codes: list[int] = []

    def send(self, code: int) -> HardwareWrite:
        self.codes.append(code)
        start = float(len(self.codes))
        return HardwareWrite(code, f"01 e1 01 00 {code:02x}", start, start + 0.001)


def test_bench_sends_every_codebook_entry_once() -> None:
    transport = FakeTransport()

    rows = run_trigger_bench(transport, interval_sec=0)

    assert transport.codes == list(BENCH_CODES)
    assert transport.codes == [definition.code for definition in EVENT_CODES]
    assert len(set(transport.codes)) == len(transport.codes)
    assert all(row["write_duration_ms"] == pytest.approx(1.0) for row in rows)


def test_bench_writes_machine_readable_results(tmp_path: Path) -> None:
    rows = run_trigger_bench(FakeTransport(), codes=(120, 100), interval_sec=0)

    write_bench_results(tmp_path, rows, port="COM5")

    assert (tmp_path / "trigger_bench.json").exists()
    assert "TRIGGER_PATH_CALIBRATION" in (tmp_path / "trigger_bench.csv").read_text(
        encoding="utf-8-sig"
    )
