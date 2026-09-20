from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from rp1_analysis_v1.integration import (
    IntegrationError,
    validate_governed_inputs,
    validate_run_authority,
)
from rp1_analysis_v1.paths import ProjectPaths

SUBPROJECT = Path(__file__).resolve().parents[1]
SRC = SUBPROJECT / "src"


@pytest.fixture(scope="module")
def governed_validation_result(tmp_path_factory: pytest.TempPathFactory) -> tuple[subprocess.CompletedProcess[str], dict]:
    cwd = tmp_path_factory.mktemp("validate_inputs_cwd")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    result = subprocess.run(
        [sys.executable, str(SUBPROJECT / "scripts/validate_inputs.py")],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    marker = "\nRP1_ANALYSIS_V1_INPUT_VALIDATION=PASS"
    payload = result.stdout.split(marker, 1)[0]
    report = json.loads(payload) if payload.strip() else {}
    return result, report


def test_validate_inputs_script_is_cwd_independent(
    governed_validation_result: tuple[subprocess.CompletedProcess[str], dict],
) -> None:
    result, report = governed_validation_result
    assert result.returncode == 0, result.stderr
    assert "RP1_ANALYSIS_V1_INPUT_VALIDATION=PASS" in result.stdout
    assert "CANONICAL_INPUT_IDENTITY=MATCH" in result.stdout
    assert report["input_validation_status"] == "PASS"


def test_governed_input_validation_report_is_complete(
    governed_validation_result: tuple[subprocess.CompletedProcess[str], dict],
) -> None:
    result, report = governed_validation_result
    assert result.returncode == 0, result.stderr
    assert report["status"] == "PASS"
    assert report["input_validation_status"] == "PASS"
    assert report["canonical_input_identity"] == "MATCH"
    assert report["governed_file_count"] == 15
    assert report["populations"] == {
        "ACZ_MONTHLY_ROWS": 1440,
        "DISTRICT_MONTHLY_ROWS": 74880,
        "DISTRICT_UNITS": 260,
        "LONG_RUN_DISTRICTS": 250,
        "LONG_RUN_ROWS": 72000,
        "PAIRED_DISTRICTS": 249,
        "PAIRED_ROWS": 38595,
        "RQ3_GEE_DISTRICTS": 249,
        "RQ3_GEE_ROWS": 22939,
    }
    assert all(row["hash_match"] and row["size_match"] for row in report["hashes"])
    assert all(row["passed"] for row in report["reconciliation"])


def _temporary_paths_with_inventory(
    tmp_path: Path,
    inventory: dict,
) -> ProjectPaths:
    shutil.copytree(SUBPROJECT / "config", tmp_path / "config")
    shutil.copy2(SUBPROJECT / "pyproject.toml", tmp_path / "pyproject.toml")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "input_sha256.json").write_text(
        json.dumps(inventory, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return ProjectPaths(tmp_path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("staged_path", "", "Malformed input-hash inventory staged_path"),
        ("origin_path", "", "Malformed input-hash inventory origin_path"),
        ("sha256", "not-a-sha256", "Malformed input-hash inventory SHA-256"),
        ("sha256", "g" * 64, "Malformed input-hash inventory SHA-256"),
        ("size_bytes", "1058317", "Malformed input-hash inventory size_bytes"),
        ("size_bytes", True, "Malformed input-hash inventory size_bytes"),
        ("size_bytes", -1, "Malformed input-hash inventory size_bytes"),
    ],
)
def test_governed_input_validation_rejects_malformed_identity(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    inventory = json.loads((SUBPROJECT / "data" / "input_sha256.json").read_text(encoding="utf-8"))
    item = dict(inventory["files"][0])
    item[field] = value
    inventory["files"] = [item]

    paths = _temporary_paths_with_inventory(tmp_path, inventory)

    with pytest.raises(IntegrationError, match=message):
        validate_governed_inputs(paths)


def test_run_validator_fails_closed_for_missing_run(tmp_path: Path) -> None:
    paths = ProjectPaths.discover(SUBPROJECT)
    with pytest.raises(IntegrationError, match="Missing governed run directory"):
        validate_run_authority(paths=paths, run_id="nonexistent_clean_run")


def test_canonical_notebook_has_no_preexisting_publication_output_dependency() -> None:
    text = (SUBPROJECT / "RP1_Analysis_v1.ipynb").read_text(encoding="utf-8")
    assert "publication_reference" not in text
    assert "PUBLICATION_RUN = build_publication_run_isolated" in text


def test_release_documentation_and_runtime_are_product_scoped() -> None:
    repository = SUBPROJECT.parents[1]
    candidates = [*sorted((SUBPROJECT / "src").rglob("*.py")), *sorted((SUBPROJECT / "scripts").rglob("*.py")), *sorted((SUBPROJECT / "docs").rglob("*.md")), SUBPROJECT / "README.md", SUBPROJECT / "RP1_Analysis_v1.ipynb", repository / "README.md", repository / "RP1_Project/RP1_README.md", repository / "RP1_Project/docs/rp1_setup.md", repository / "RP1_Project/rp1_mv_firms_panels/docs/rp1_setup.md", repository / "RP1_Project/merge_af_ba_panels.py", repository / "tools/qualify_environment.py", repository / "geo_data_prep/pyproject.toml", repository / "pyproject.toml", repository / "environment.yml"]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in candidates)
    assert "rp1-analysis-v1" in combined
    assert "1.2.3" in combined
    machine_patterns = (re.compile(r"/home/[A-Za-z0-9._-]+/"), re.compile(r"/mnt/[A-Za-z]/"), re.compile(r"[A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/]"))
    for path in [*candidates, SUBPROJECT / "data/raw/fire_panel_manifest.json"]:
        text = path.read_text(encoding="utf-8")
        assert not any(pattern.search(text) for pattern in machine_patterns), path
