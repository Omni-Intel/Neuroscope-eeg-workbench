from __future__ import annotations

import argparse
import json
import zipfile
from datetime import datetime
from pathlib import Path

from mi_control.acquisition.simulated import SimulatedSource
from mi_control.diagnostics.environment import environment_report
from mi_control.acquisition.replay import save_replay_npz


def create_diagnostic_bundle(output: Path, duration_sec: float = 8.0) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    workdir = output.parent / f"mi-control-diagnostic-{stamp}"
    workdir.mkdir(parents=True, exist_ok=True)
    source = SimulatedSource(paced=False)
    source.start()
    chunks = []
    samples_needed = int(round(duration_sec * source.metadata.sfreq))
    samples = 0
    while samples < samples_needed:
        chunk = source.read_chunk()
        chunks.append(chunk)
        samples += chunk.n_samples
    source.stop()
    data = __import__("numpy").concatenate([chunk.data for chunk in chunks], axis=1)[:, :samples_needed]
    timestamps = __import__("numpy").concatenate([chunk.timestamps for chunk in chunks])[:samples_needed]
    replay_path = workdir / "simulated-replay.npz"
    save_replay_npz(replay_path, source.metadata, data, timestamps)
    (workdir / "environment.json").write_text(json.dumps(environment_report(), ensure_ascii=False, indent=2), encoding="utf-8")
    (workdir / "README.txt").write_text(
        "MI Control diagnostic bundle. Send the zip back with environment.json and simulated-replay.npz intact.\n",
        encoding="utf-8",
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in workdir.iterdir():
            zf.write(path, path.name)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("mi-control-diagnostic.zip"))
    parser.add_argument("--duration-sec", type=float, default=8.0)
    args = parser.parse_args(argv)
    print(create_diagnostic_bundle(args.output, args.duration_sec))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
