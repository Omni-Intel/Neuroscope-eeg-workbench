from neuroscope_eeg.diagnostics.environment import environment_report


def test_environment_report_contains_package_status() -> None:
    report = environment_report()
    assert report["neuroscope_version"] == "0.3.2"
    assert "packages" in report
