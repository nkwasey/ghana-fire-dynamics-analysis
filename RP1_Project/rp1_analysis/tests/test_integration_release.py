from __future__ import annotations
from scientific_input_reference import input_population_sizes

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from rp1_analysis_v1.integration import (
    IntegrationError,
    validate_run_authority,
)
from rp1_analysis_v1.paths import ProjectPaths
from _generated_input_contract import configured_input_paths

SUBPROJECT = Path(__file__).resolve().parents[1]
SRC = SUBPROJECT / "src"
MACHINE_PATHS = (
    re.compile(r"/home/[A-Za-z0-9._-]+/"),
    re.compile(r"/mnt/[A-Za-z]/"),
    re.compile(r"[A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/]"),
)


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
    assert f"CANONICAL_INPUT_IDENTITY={report['canonical_input_identity']}" in result.stdout
    assert report["input_validation_status"] == "PASS"


def test_governed_input_validation_report_is_complete(
    governed_validation_result: tuple[subprocess.CompletedProcess[str], dict],
) -> None:
    result, report = governed_validation_result
    assert result.returncode == 0, result.stderr
    assert report["status"] == "PASS"
    assert report["input_validation_status"] == "PASS"
    expected_identity = "MATCH" if all(row["hash_match"] and row["size_match"] for row in report["hashes"]) else "DIFFERENT"
    assert report["canonical_input_identity"] == expected_identity
    expected_paths = configured_input_paths(SUBPROJECT)
    assert report["governed_file_count"] == len(expected_paths)
    assert {row["staged_path"] for row in report["current_input_identities"]} == expected_paths
    assert report["populations"] == input_population_sizes()

    assert all(row["passed"] for row in report["reconciliation"])


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
    assert "1.3.1" in combined
    for path in candidates:
        text = path.read_text(encoding="utf-8")
        assert not any(pattern.search(text) for pattern in MACHINE_PATHS), path


def test_admitted_manifest_staged_paths_are_portable() -> None:
    repository = SUBPROJECT.parents[1]
    # An admitted manifest may record local source origins. Runtime uses staged paths.
    manifest = json.loads((SUBPROJECT / "data/raw/fire_panel_manifest.json").read_text(encoding="utf-8"))
    for record in manifest["outputs"].values():
        staged = record["staged_path"]
        assert not any(pattern.search(staged) for pattern in MACHINE_PATHS)
        assert (repository / staged).resolve().is_relative_to(SUBPROJECT.resolve())
