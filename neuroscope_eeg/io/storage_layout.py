"""Three sibling output folders, linked by a continuous recording UUID."""
import json
import re
from pathlib import Path

from neuroscope_eeg.io.edf_paths import edf_path
from neuroscope_eeg.project_metadata import validate_unique_name


def recording_root(run_dir):
    path = Path(edf_path(run_dir))
    if path.parent.name != "Records" or not re.fullmatch(r"recording-[0-9a-f]{32}", path.name):
        raise ValueError("请选择保存根目录下 Records/recording-<UUID> 中的记录")
    return path.parent.parent


def record_identity(run_dir):
    path = Path(edf_path(run_dir))
    root = recording_root(path)
    run = json.loads((path / "run.json").read_text(encoding="utf-8"))
    if path.name != "recording-" + run["session_id"]:
        raise ValueError("记录目录与 UUID 不一致")
    name = run["unique_name"]
    validate_unique_name(name)
    return root, run


def report_directory(run_dir):
    root, run = record_identity(run_dir)
    return root / "Reports" / run["unique_name"] / ("recording-" + run["session_id"])


def delivery_validation_path(package):
    package = Path(edf_path(package))
    if package.parent.parent.name != "data" or not re.fullmatch(r"recording-[0-9a-f]{32}", package.name):
        raise ValueError("请选择 data/<范式>/recording-<UUID> 标准交付包")
    return package.parents[2] / "Records" / package.name / "delivery" / "validation.json"
