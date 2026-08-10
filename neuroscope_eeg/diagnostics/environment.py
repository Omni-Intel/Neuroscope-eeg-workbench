from __future__ import annotations

import importlib.util
import importlib
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
    package_status = {name: importlib.util.find_spec(name) is not None for name in packages}
    pylsl_runtime: dict[str, object] = {"importable": False, "error": None}
    if package_status["pylsl"]:
        try:
            module = importlib.import_module("pylsl")
            pylsl_runtime = {
                "importable": True,
                "version": getattr(module, "__version__", "unknown"),
                "error": None,
            }
        except (ImportError, RuntimeError, OSError) as exc:
            package_status["pylsl"] = False
            pylsl_runtime["error"] = str(exc)
    return {
        "neuroscope_version": __version__,
        "python": sys.version,
        "platform": platform.platform(),
        "executable": sys.executable,
        "cwd": str(Path.cwd()),
        "packages": package_status,
        "pylsl_runtime": pylsl_runtime,
    }


def main() -> int:
    print(json.dumps(environment_report(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
