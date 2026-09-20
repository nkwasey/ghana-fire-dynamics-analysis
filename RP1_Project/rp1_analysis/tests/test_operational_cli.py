from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from rp1_analysis_v1 import cli
from rp1_analysis_v1.operations import doctor_report, version_report

ROOT = Path(__file__).resolve().parents[1]


def test_console_script_metadata_is_package_owned() -> None:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        raw = tomllib.load(handle)
    assert raw["project"]["scripts"] == {"rp1-analysis": "rp1_analysis_v1.cli:main"}


def test_version_report_is_phase_neutral_and_uses_governed_identities() -> None:
    report = version_report()
    assert report == {
        "product": "Ghana Fire RP1 Analysis",
        "version": "1.2.3",
        "distribution": "rp1-analysis-v1",
        "package": "rp1_analysis_v1",
        "analysis_schema": "rp1-analysis-v1.1",
        "data_schema": "rp1-data-schema-v1.1",
    }
    assert re.search(r"\bV\d{3,}(?:[-_]\d+)?\b", json.dumps(report), flags=re.IGNORECASE) is None


def test_module_cli_version_matches_shared_report() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "rp1_analysis_v1.cli", "version"],
        check=False,
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == version_report()


def test_doctor_accepts_absent_external_satscan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("rp1_analysis_v1.operations.find_satscan_executable", lambda: None)
    report = doctor_report()
    assert report["status"] == "PASS"
    satscan = next(row for row in report["checks"] if row["check"] == "satscan")
    assert satscan["status"] == "NOT_AVAILABLE_EXTERNAL"
    assert satscan["required_for_ordinary_runtime"] is False


def _doctor_environment_check(report: dict[str, object]) -> dict[str, object]:
    checks = report["checks"]
    assert isinstance(checks, list)
    return next(row for row in checks if row["check"] == "environment")


def test_doctor_canonical_conda_environment_reports_name_without_collision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONDA_DEFAULT_ENV", "rp_ghana_fire")
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setattr("rp1_analysis_v1.operations.find_satscan_executable", lambda: None)

    report = doctor_report()

    assert report["status"] == "PASS"
    environment = _doctor_environment_check(report)
    assert environment == {
        "check": "environment",
        "status": "PASS",
        "kind": "conda",
        "name": "rp_ghana_fire",
    }


def test_doctor_noncanonical_conda_environment_is_advisory_and_does_not_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CONDA_DEFAULT_ENV", "base")
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setattr("rp1_analysis_v1.operations.find_satscan_executable", lambda: None)

    report = doctor_report()

    assert report["status"] == "PASS"
    environment = _doctor_environment_check(report)
    assert environment == {
        "check": "environment",
        "status": "NON_CANONICAL",
        "kind": "conda",
        "name": "base",
    }


def test_doctor_virtualenv_environment_is_diagnostic_and_does_not_crash(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    virtual_env = tmp_path / "venv"
    monkeypatch.delenv("CONDA_DEFAULT_ENV", raising=False)
    monkeypatch.setenv("VIRTUAL_ENV", str(virtual_env))
    monkeypatch.setattr("rp1_analysis_v1.operations.find_satscan_executable", lambda: None)

    report = doctor_report()

    assert report["status"] == "PASS"
    environment = _doctor_environment_check(report)
    assert environment["check"] == "environment"
    assert environment["status"] == "DETECTED_NON_CONDA"
    assert environment["kind"] == "virtualenv"
    assert environment["path"] == str(virtual_env.resolve())
    assert environment["canonical_name"] == "rp_ghana_fire"


def test_doctor_without_detectable_environment_is_diagnostic_and_does_not_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CONDA_DEFAULT_ENV", raising=False)
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.setattr("rp1_analysis_v1.operations.find_satscan_executable", lambda: None)

    report = doctor_report()

    assert report["status"] == "PASS"
    environment = _doctor_environment_check(report)
    assert environment["check"] == "environment"
    assert environment["status"] == "NOT_DETECTABLE"
    assert environment["canonical_name"] == "rp_ghana_fire"


def test_module_cli_doctor_passes_in_canonical_conda_context() -> None:
    env = dict(os.environ)
    env["CONDA_DEFAULT_ENV"] = "rp_ghana_fire"
    env.pop("VIRTUAL_ENV", None)
    completed = subprocess.run(
        [sys.executable, "-m", "rp1_analysis_v1.cli", "doctor"],
        check=False,
        text=True,
        capture_output=True,
        cwd=ROOT,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["status"] == "PASS"
    assert _doctor_environment_check(report) == {
        "check": "environment",
        "status": "PASS",
        "kind": "conda",
        "name": "rp_ghana_fire",
    }


def test_approved_command_surface_and_no_satscan_run() -> None:
    parser = cli.build_parser()
    assert parser.parse_args(["version"]).command == "version"
    assert parser.parse_args(["doctor"]).command == "doctor"
    assert parser.parse_args(["validate-inputs"]).command == "validate-inputs"
    assert parser.parse_args(["reference-check"]).command == "reference-check"
    run = parser.parse_args(["run", "--run-id", "x", "--kernel", "python3", "--timeout", "10"])
    assert (run.run_id, run.kernel, run.timeout) == ("x", "python3", 10)
    validate = parser.parse_args(["validate-run", "--run-id", "x", "--write-report"])
    assert validate.run_id == "x" and validate.write_report is True
    assert parser.parse_args(["satscan", "prepare"]).satscan_command == "prepare"
    assert parser.parse_args(["satscan", "status", "--run-id", "x"]).satscan_command == "status"
    assert parser.parse_args(["satscan", "integrate", "--run-id", "x"]).satscan_command == "integrate"
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["satscan", "run"])
    assert exc.value.code == 2


def test_required_arguments_fail_with_argparse_exit_2() -> None:
    parser = cli.build_parser()
    for argv in (["validate-run"], ["satscan", "status"], ["satscan", "integrate"]):
        with pytest.raises(SystemExit) as exc:
            parser.parse_args(argv)
        assert exc.value.code == 2


def test_legacy_scripts_delegate_to_package_owned_operations() -> None:
    scripts = ROOT / "scripts"
    checks = {
        "validate_inputs.py": "validate_inputs_report",
        "qualify_reference_methods.py": "reference_check_report",
        "execute_notebook.py": "execute_notebook_report",
        "validate_run.py": "validate_run_report",
    }
    for name, operation in checks.items():
        text = (scripts / name).read_text(encoding="utf-8")
        assert "rp1_analysis_v1.operations" in text
        assert operation in text


def test_satscan_cli_delegates_without_engine_launch(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    expected = {
        "status": "PASS",
        "external_execution_state": "EXTERNAL_RESULTS_REQUIRED",
        "secondary_run_id": "secondary_x",
        "satscan_execution_performed": False,
    }
    monkeypatch.setattr(cli, "satscan_status_report", lambda *, secondary_run_id: {**expected, "secondary_run_id": secondary_run_id})
    code = cli.main(["satscan", "status", "--run-id", "secondary_x"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == expected


def test_validate_inputs_cli_reports_runtime_validation_and_canonical_identity_separately(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "validate_inputs_report",
        lambda **_: {
            "status": "PASS",
            "input_validation_status": "PASS",
            "canonical_input_identity": "DIFFERENT",
        },
    )
    assert cli.main(["validate-inputs"]) == 0
    stdout = capsys.readouterr().out
    assert "RP1_ANALYSIS_V1_INPUT_VALIDATION=PASS" in stdout
    assert "CANONICAL_INPUT_IDENTITY=DIFFERENT" in stdout

    monkeypatch.setattr(
        cli,
        "validate_inputs_report",
        lambda **_: {
            "status": "FAIL",
            "input_validation_status": "FAIL",
            "canonical_input_identity": "DIFFERENT",
        },
    )
    assert cli.main(["validate-inputs"]) == 1
    stdout = capsys.readouterr().out
    assert "RP1_ANALYSIS_V1_INPUT_VALIDATION=FAIL" in stdout
    assert "CANONICAL_INPUT_IDENTITY=DIFFERENT" in stdout
