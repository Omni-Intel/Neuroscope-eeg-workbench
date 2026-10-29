"""Reproducible local implementation fingerprint without copying credentials."""
import hashlib
import importlib.metadata
import subprocess
from pathlib import Path


def file_hash(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def implementation_snapshot():
    root = Path(__file__).resolve().parents[1]
    paths = sorted((root / "neuroscope_eeg").rglob("*.py"))
    paths += sorted((root / "neuroscope_eeg/assets").rglob("*.dvc"))
    paths += [root / name for name in ("pyproject.toml", "uv.lock", ".python-version") if (root / name).is_file()]
    sources = {p.relative_to(root).as_posix(): file_hash(p) for p in paths}
    assets = {p.relative_to(root).as_posix(): file_hash(p) for p in (root / "neuroscope_eeg/assets").rglob("*")
              if p.is_file() and p.suffix in {".jpg", ".json", ".dvc"}}
    versions = {}
    for name in ("numpy", "scipy", "PySide6-Essentials", "pyedflib", "python-docx", "bcigo-sdk", "omnibci"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    git = {"commit": None, "dirty": None}
    try:
        flags = {"cwd": root, "capture_output": True, "text": True, "timeout": 5}
        git["commit"] = subprocess.run(["git", "rev-parse", "HEAD"], check=True, **flags).stdout.strip()
        git["dirty"] = bool(subprocess.run(["git", "status", "--porcelain"], check=True, **flags).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass  # File hashes still identify code without a Git checkout.
    return {"schema_version": 1, "git": git, "source_sha256": sources, "asset_sha256": assets, "dependencies": versions}
