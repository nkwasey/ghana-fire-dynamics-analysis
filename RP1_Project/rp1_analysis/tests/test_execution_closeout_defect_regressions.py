from __future__ import annotations

import inspect
from pathlib import Path
from dataclasses import dataclass
from types import SimpleNamespace

import nbformat
import pandas as pd
import pytest

from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.execution_contract import validate_secondary_completion_state

from rp1_analysis_v1 import integration, presentation_export

SUBPROJECT = Path(__file__).resolve().parents[1]
NOTEBOOK = SUBPROJECT / "RP1_Analysis_v1.ipynb"
VALIDATED_FIXTURE_STATUS = (
    SUBPROJECT
    / "tests/fixtures/qualified_presentation_run/qualified_presentation_fixture_sec"
    / "04_secondary_concentration/secondary_external_execution_status.json"
)


def _cell_source(cell_id: str) -> str:
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    for cell in notebook.cells:
        if cell.get("id") == cell_id:
            return "".join(cell.get("source", ""))
    raise AssertionError(f"Notebook cell not found: {cell_id}")


def test_repository_fixture_proves_results_validated_is_a_legitimate_secondary_state() -> None:
    import json

    payload = json.loads(VALIDATED_FIXTURE_STATUS.read_text(encoding="utf-8"))
    assert payload["external_execution_state"] == "RESULTS_VALIDATED"
    assert payload["validated_model_count"] == 2
    assert payload["live_satscan_execution"] == "VALIDATED_EXTERNAL_RESULTS_INGESTED"


def test_section_04_01_accepts_preexisting_results_validated_state() -> None:
    """The canonical Section 04-01 must accept an already validated run."""

    @dataclass(frozen=True)
    class _Parameters:
        marker: str = "configured"

    bundle = load_configuration_bundle(SUBPROJECT / "config")
    model_ids = [
        str(item["scenario_id"])
        for item in bundle.analysis.secondary_analysis["scenarios"]
    ]
    secondary = SimpleNamespace(
        execution_state="RESULTS_VALIDATED",
        scan_specification_registry=pd.DataFrame({"model_id": model_ids}),
        secondary_run_registry=pd.DataFrame(
            {"model_id": model_ids, "execution_state": ["RESULTS_VALIDATED"] * len(model_ids)}
        ),
    )
    source = _cell_source("rp1-code-04-01")
    namespace = {
        "asdict": __import__("dataclasses").asdict,
        "pd": pd,
        "display": lambda _value: None,
        "satscan_parameters": lambda _analysis: _Parameters(),
        "contracts": bundle,
        "build_secondary_input_run_isolated": lambda **_kwargs: secondary,
        "validate_secondary_completion_state": validate_secondary_completion_state,
        "paths": object(),
        "run_ids": {"secondary": "regression_sec"},
    }
    exec(compile(source, str(NOTEBOOK), "exec"), namespace, namespace)
    assert namespace["secondary_gate"] == "PASS"
    assert namespace["secondary"].execution_state == "RESULTS_VALIDATED"


def test_section_04_01_uses_the_shared_execution_contract_for_secondary_state() -> None:
    source = _cell_source("rp1-code-04-01")
    assert "validate_secondary_completion_state(contracts.execution, secondary.execution_state)" in source
    assert "secondary.execution_state == EXTERNAL_RESULTS_REQUIRED" not in source


def test_direct_notebook_section_99_calls_package_owned_interactive_finalisation() -> None:
    section_99 = _cell_source("rp1-code-99-01") + "\n" + _cell_source("rp1-code-99-02")
    assert "finalise_interactive_run(" in section_99
    assert "M_NOTEBOOK_EXECUTION.json" not in section_99
    assert "RP1_Analysis_v1.executed.ipynb" not in section_99


def test_canonical_closeout_gate_persists_every_shared_section_gate() -> None:
    section_99 = _cell_source("rp1-code-99-02")
    for field in ("scaffold_gate", "rq1_gate", "rq2_gate", "rq3_gate", "secondary_gate"):
        assert f'"{field}": {field}' in section_99


def test_completed_run_validator_delegates_to_shared_execution_contract() -> None:
    source = inspect.getsource(integration._validate_closeout_run)
    assert "validate_completed_closeout(" in source
    assert 'section / "M_NOTEBOOK_EXECUTION.json"' not in source
    assert 'section / "RP1_Analysis_v1.executed.ipynb"' not in source


def test_automated_wrapper_emits_and_self_validates_shared_completion_evidence() -> None:
    source = inspect.getsource(integration.execute_canonical_notebook)
    assert "bundle.execution.artifact_roles[\'executed_notebook\']" in source
    assert "bundle.execution.artifact_roles[\'execution_record\']" in source
    assert "validate_execution_record(" in source
    assert "validate_completed_closeout(" in source
    assert '"execution_mode": controlled_mode' in source
    assert '"RP1_NOTEBOOK_EXECUTION_MODE": controlled_mode' in source


def test_presentation_export_preflight_uses_configured_closeout_authority() -> None:
    source = inspect.getsource(presentation_export.validate_run_configuration_compatibility)
    assert "current.execution.closeout_section" in source
    assert 'current.execution.artifact_roles["reproducibility_manifest"]' in source
    assert 'run.closeout_run / "99_closeout" / "M_REPRODUCIBILITY_MANIFEST.json"' not in source
