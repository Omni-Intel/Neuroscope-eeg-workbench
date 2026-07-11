from pathlib import Path
from zipfile import ZipFile

from mi_control.io.diagnostic_bundle import create_diagnostic_bundle


def test_create_diagnostic_bundle(tmp_path: Path) -> None:
    bundle = create_diagnostic_bundle(tmp_path / "bundle.zip", duration_sec=0.2)
    with ZipFile(bundle) as zf:
        names = set(zf.namelist())
    assert {"environment.json", "simulated-replay.npz", "README.txt"} <= names
