"""EDFlib's C file API needs an extended Windows path for long BIDS names."""
import os
from pathlib import Path


def edf_path(path):
    value = str(Path(path).resolve())
    if os.name == "nt" and not value.startswith("\\\\?\\"):
        if value.startswith("\\\\"):
            return "\\\\?\\UNC\\" + value[2:]
        return "\\\\?\\" + value
    return value
