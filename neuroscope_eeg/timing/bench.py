from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any, Iterable

from neuroscope_eeg.timing.codebook import CODEBOOK_VERSION, EVENT_CODES
from neuroscope_eeg.timing.neuracle_dcp import NDE0001Transport


BENCH_CODES = tuple(definition.code for definition in EVENT_CODES)


def run_trigger_bench(
    transport: Any,
    *,
    codes: Iterable[int] = BENCH_CODES,
    interval_sec: float = 0.05,
) -> list[dict[str, Any]]:
    if interval_sec < 0:
        raise ValueError("interval_sec must be non-negative")
    rows: list[dict[str, Any]] = []
    lookup = {definition.code: definition for definition in EVENT_CODES}
    for sequence, code in enumerate(codes, start=1):
        definition = lookup[int(code)]
        write = transport.send(definition.code)
        rows.append(
            {
                "sequence": sequence,
                "code": definition.code,
                "symbol": definition.symbol,
                "paradigm": definition.paradigm,
                "phase": definition.phase,
                "frame_hex": write.frame_hex,
                "requested_at": write.requested_at,
                "write_completed_at": write.write_completed_at,
                "write_duration_ms": (write.write_completed_at - write.requested_at) * 1000.0,
            }
        )
        if interval_sec:
            time.sleep(interval_sec)
    return rows


def write_bench_results(output_dir: Path, rows: list[dict[str, Any]], *, port: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "port": port,
        "codebook_version": CODEBOOK_VERSION,
        "identity": "TriggerBox.Titing",
        "rows": rows,
    }
    (output_dir / "trigger_bench.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    fieldnames = tuple(rows[0]) if rows else (
        "sequence",
        "code",
        "symbol",
        "paradigm",
        "phase",
        "frame_hex",
        "requested_at",
        "write_completed_at",
        "write_duration_ms",
    )
    with (output_dir / "trigger_bench.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NDE0001 全事件码台架自检")
    parser.add_argument("--port", required=True, help="串口，例如 COM5 或 /dev/cu.usbserial-xxx")
    parser.add_argument("--output", type=Path, default=Path("trigger-bench-output"))
    parser.add_argument("--interval-ms", type=float, default=50.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    transport = NDE0001Transport(args.port)
    try:
        identity = transport.open()
        print(f"NDE0001 已识别：{identity}")
        rows = run_trigger_bench(
            transport,
            interval_sec=max(0.0, float(args.interval_ms)) / 1000.0,
        )
        write_bench_results(args.output, rows, port=args.port)
    finally:
        transport.close()
    print(f"已发送 {len(rows)} 个事件码；结果：{args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
