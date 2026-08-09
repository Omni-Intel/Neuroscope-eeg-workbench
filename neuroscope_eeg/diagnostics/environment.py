from __future__ import annotations

import importlib.util
import json
import platform
import sys
from pathlib import Path

from neuroscope_eeg import __version__


def environment_report() -> dict[str, object]:
    packages = [
        "numpy",
        "scipy",
        "matplotlib",
        "mne",
        "streamlit",
        "PySide6",
        "pyqtgraph",
        "pylsl",
        "bcigo_sdk",
    ]
    return {
        "neuroscope_version": __version__,
        "python": sys.version,
        "platform": platform.platform(),
        "executable": sys.executable,
        "cwd": str(Path.cwd()),
        "packages": {name: importlib.util.find_spec(name) is not None for name in packages},
    }


def main() -> int:
    print(json.dumps(environment_report(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
