"""Configure the emotion asset remote from explicit metadata; never upload."""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from neuroscope_eeg.project_metadata import load_metadata


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--metadata", type=Path, required=True, help="Emotion experiment metadata.toml")
    args = parser.parse_args()
    experiment = load_metadata(args.metadata)
    remote = f"s3://oi-task-assets/{experiment['unique_name']}/dvc/"
    commands = [["remote", "add", "-f", "-d", "nas", remote],
                ["remote", "modify", "nas", "endpointurl", "http://truenas-s658v2.omni-intel.cn:9000"],
                ["remote", "modify", "nas", "allow_anonymous_login", "true"]]
    for command in commands:
        subprocess.run([sys.executable, "-m", "dvc", *command], cwd=ROOT, check=True)
    print("Configured anonymous asset read; no network transfer performed:", remote)


if __name__ == "__main__":
    main()
