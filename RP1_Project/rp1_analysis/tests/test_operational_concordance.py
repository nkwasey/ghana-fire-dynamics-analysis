from __future__ import annotations

import json
from pathlib import Path

import pytest

from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.execution_contract import (
    ExecutionContractError,
    canonical_section_gates,
    validate_completed_closeout,
)
from rp1_analysis_v1.provenance import sha256_file

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _valid_closeout(
    tmp_path: Path,
    *,
    mode: str,
    canonical_input_identity: str = "MATCH",
) -> tuple[Path, dict[str, object]]:
    bundle = load_configuration_bundle(CONFIG)
    run_id = "operational_concordance_matrix"
    run_dir = tmp_path / f"{run_id}_close"
    section = run_dir / bundle.execution.closeout_section
    section.mkdir(parents=True)

    gate: dict[str, object] = {
        "canonical_notebook": "RP1_Analysis_v1.ipynb",
        "configuration_sha256": bundle.configuration_sha256,
        "input_validation_status": "PASS",
        "canonical_input_identity": canonical_input_identity,
        "scaffold_gate": "PASS",
        "rq1_gate": "PASS",
        "rq2_gate": "PASS",
        "rq3_gate": "PASS",
        "secondary_gate": "PASS",
        "secondary_external_state": "RESULTS_VALIDATED",
        "publication_gate": "PASS",
        "final_run_gate": "PASS",
    }
    provenance: dict[str, object] = {
        "schema_version": bundle.analysis.schema_version,
        "run_id": f"{run_id}_close",
        "started_at_utc": "2026-09-10T10:00:00Z",
        "ended_at_utc": "2026-09-10T10:01:00Z",
        "configuration_sha256": bundle.configuration_sha256,
        "input_validation_status": "PASS",
        "canonical_input_identity": canonical_input_identity,
        "inputs": [{"path": "data/raw/example.csv", "sha256": "a" * 64, "size_bytes": 1}],
        "environment": {},
        "determinism_note": "test fixture",
    }
    gate_path = section / bundle.execution.artifact_roles["canonical_gate"]
    provenance_path = section / bundle.execution.artifact_roles["reproducibility_manifest"]
    _write_json(gate_path, gate)
    _write_json(provenance_path, provenance)

    spec = bundle.execution.mode(mode)
    record: dict[str, object] = {
        "schema": bundle.execution.execution_record_schema,
        "status": "PASS",
        "run_id": run_id,
        "execution_mode": mode,
        "canonical_notebook": "RP1_Analysis_v1.ipynb",
        "package_version": bundle.package_version,
        "analysis_schema_version": bundle.analysis.schema_version,
        "data_schema_version": bundle.data_schema.data_schema_version,
        "configuration_sha256": bundle.configuration_sha256,
        "operational_configuration_sha256": bundle.operational_configuration_sha256,
        "final_section_reached": True,
        "canonical_gate_status": "PASS",
        "canonical_gate_sha256": sha256_file(gate_path),
        "reproducibility_manifest_sha256": sha256_file(provenance_path),
        "publication_gate_status": "PASS",
        "section_gates": canonical_section_gates(gate),
        "input_validation_status": "PASS",
        "canonical_input_identity": canonical_input_identity,
        "secondary_execution_state": "RESULTS_VALIDATED",
        "secondary_integration_state": "INTEGRATED",
        "secondary_validated_model_count": 2,
        "satscan_execution_performed": False,
        "notebook_snapshot_required": spec.notebook_snapshot_required,
        "notebook_snapshot_available": spec.notebook_snapshot_required,
        "completion_timestamp_utc": "2026-09-10T10:02:00Z",
    }
    if mode == "controlled_nbclient":
        executed = section / bundle.execution.artifact_roles["executed_notebook"]
        executed.write_text('{"cells": [], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}\n', encoding="utf-8")
        record.update(
            {
                "kernel_name": "python3",
                "execution_cwd_policy": "isolated_temporary_directory",
                "code_cells": 14,
                "executed_code_cells": 14,
                "executed_notebook_sha256": sha256_file(executed),
            }
        )
    else:
        record["provenance_limitations"] = [
            "Interactive kernel cannot attest the Jupyter front-end save state."
        ]

    execution_path = section / bundle.execution.artifact_roles["execution_record"]
    _write_json(execution_path, record)
    context = {
        "bundle": bundle,
        "run_id": run_id,
        "section": section,
        "gate": gate,
        "gate_path": gate_path,
        "provenance": provenance,
        "provenance_path": provenance_path,
        "record": record,
        "execution_path": execution_path,
    }
    return run_dir, context


def _validate(run_dir: Path, ctx: dict[str, object]):
    bundle = ctx["bundle"]
    return validate_completed_closeout(
        run_dir,
        bundle.execution,  # type: ignore[attr-defined]
        expected_run_id=str(ctx["run_id"]),
        expected_configuration_sha256=bundle.configuration_sha256,  # type: ignore[attr-defined]
        expected_operational_configuration_sha256=bundle.operational_configuration_sha256,  # type: ignore[attr-defined]
        expected_package_version=bundle.package_version,  # type: ignore[attr-defined]
        expected_analysis_schema_version=bundle.analysis.schema_version,  # type: ignore[attr-defined]
        expected_data_schema_version=bundle.data_schema.data_schema_version,  # type: ignore[attr-defined]
        expected_secondary_state="RESULTS_VALIDATED",
        expected_secondary_integration_state="INTEGRATED",
        expected_secondary_validated_model_count=2,
    )


@pytest.mark.parametrize("mode", ["controlled_nbclient", "interactive_jupyter"])
def test_both_governed_completion_modes_validate_through_one_closeout_authority(tmp_path: Path, mode: str) -> None:
    run_dir, ctx = _valid_closeout(tmp_path, mode=mode)
    resolved, checks = _validate(run_dir, ctx)
    assert resolved.mode_id == mode
    assert checks
    assert all(row["status"] == "PASS" for row in checks)


@pytest.mark.parametrize("mode", ["controlled_nbclient", "interactive_jupyter"])
def test_completed_run_validator_accepts_valid_noncanonical_input_identity(tmp_path: Path, mode: str) -> None:
    run_dir, ctx = _valid_closeout(
        tmp_path,
        mode=mode,
        canonical_input_identity="DIFFERENT",
    )
    resolved, checks = _validate(run_dir, ctx)
    assert resolved.mode_id == mode
    assert all(row["status"] == "PASS" for row in checks)
    names = {row["check"] for row in checks}
    assert "canonical_input_identity" in names


def test_missing_execution_authority_fails_closed(tmp_path: Path) -> None:
    run_dir, ctx = _valid_closeout(tmp_path, mode="interactive_jupyter")
    ctx["execution_path"].unlink()  # type: ignore[attr-defined]
    with pytest.raises(
        ExecutionContractError,
        match="Missing execution authority artefact: M_NOTEBOOK_EXECUTION.json",
    ):
        _validate(run_dir, ctx)


def test_unknown_execution_mode_cannot_fall_back_to_interactive(tmp_path: Path) -> None:
    run_dir, ctx = _valid_closeout(tmp_path, mode="controlled_nbclient")
    record = ctx["record"]
    record["execution_mode"] = "unknown_mode"  # type: ignore[index]
    _write_json(ctx["execution_path"], record)  # type: ignore[arg-type]
    with pytest.raises(ExecutionContractError, match="Unsupported execution mode"):
        _validate(run_dir, ctx)


def test_controlled_mode_missing_snapshot_fails_as_mode_specific_missing_artefact(tmp_path: Path) -> None:
    run_dir, ctx = _valid_closeout(tmp_path, mode="controlled_nbclient")
    bundle = ctx["bundle"]
    (ctx["section"] / bundle.execution.artifact_roles["executed_notebook"]).unlink()  # type: ignore[operator,attr-defined]
    with pytest.raises(ExecutionContractError, match="Missing required closeout artefact.*executed.ipynb"):
        _validate(run_dir, ctx)


def test_controlled_mode_snapshot_sha_mismatch_fails_closed(tmp_path: Path) -> None:
    run_dir, ctx = _valid_closeout(tmp_path, mode="controlled_nbclient")
    record = ctx["record"]
    record["executed_notebook_sha256"] = "0" * 64  # type: ignore[index]
    _write_json(ctx["execution_path"], record)  # type: ignore[arg-type]
    with pytest.raises(ExecutionContractError, match="executed-notebook SHA-256 mismatch"):
        _validate(run_dir, ctx)


def test_interactive_mode_missing_finalisation_evidence_fails_closed(tmp_path: Path) -> None:
    run_dir, ctx = _valid_closeout(tmp_path, mode="interactive_jupyter")
    record = ctx["record"]
    del record["final_section_reached"]  # type: ignore[index]
    _write_json(ctx["execution_path"], record)  # type: ignore[arg-type]
    with pytest.raises(ExecutionContractError, match="missing required field.*final_section_reached"):
        _validate(run_dir, ctx)


def test_wrong_run_identity_fails_closed(tmp_path: Path) -> None:
    run_dir, ctx = _valid_closeout(tmp_path, mode="interactive_jupyter")
    record = ctx["record"]
    record["run_id"] = "wrong_run"  # type: ignore[index]
    _write_json(ctx["execution_path"], record)  # type: ignore[arg-type]
    with pytest.raises(ExecutionContractError, match="run_id mismatch"):
        _validate(run_dir, ctx)


def test_scientific_and_operational_configuration_identity_fail_closed(tmp_path: Path) -> None:
    run_dir, ctx = _valid_closeout(tmp_path, mode="interactive_jupyter")
    record = ctx["record"]
    record["configuration_sha256"] = "0" * 64  # type: ignore[index]
    _write_json(ctx["execution_path"], record)  # type: ignore[arg-type]
    with pytest.raises(ExecutionContractError, match="Invalid configuration identity.*configuration_sha256"):
        _validate(run_dir, ctx)

    run_dir, ctx = _valid_closeout(tmp_path / "operational", mode="interactive_jupyter")
    record = ctx["record"]
    record["operational_configuration_sha256"] = "0" * 64  # type: ignore[index]
    _write_json(ctx["execution_path"], record)  # type: ignore[arg-type]
    with pytest.raises(ExecutionContractError, match="operational_configuration_sha256"):
        _validate(run_dir, ctx)


def test_failed_canonical_and_publication_gates_fail_closed(tmp_path: Path) -> None:
    run_dir, ctx = _valid_closeout(tmp_path, mode="interactive_jupyter")
    gate = ctx["gate"]
    gate["rq2_gate"] = "FAIL"  # type: ignore[index]
    _write_json(ctx["gate_path"], gate)  # type: ignore[arg-type]
    with pytest.raises(ExecutionContractError, match="Canonical section gate failure"):
        _validate(run_dir, ctx)

    run_dir, ctx = _valid_closeout(tmp_path / "publication", mode="interactive_jupyter")
    gate = ctx["gate"]
    gate["publication_gate"] = "FAIL"  # type: ignore[index]
    _write_json(ctx["gate_path"], gate)  # type: ignore[arg-type]
    with pytest.raises(ExecutionContractError, match="publication gate is not PASS"):
        _validate(run_dir, ctx)


def test_malformed_closeout_execution_record_is_distinguished(tmp_path: Path) -> None:
    run_dir, ctx = _valid_closeout(tmp_path, mode="interactive_jupyter")
    ctx["execution_path"].write_text("{not-json\n", encoding="utf-8")  # type: ignore[attr-defined]
    with pytest.raises(ExecutionContractError, match="Malformed closeout execution record"):
        _validate(run_dir, ctx)


def test_unsupported_secondary_completion_state_fails_closed(tmp_path: Path) -> None:
    run_dir, ctx = _valid_closeout(tmp_path, mode="interactive_jupyter")
    record = ctx["record"]
    record["secondary_execution_state"] = "INPUTS_READY"  # type: ignore[index]
    _write_json(ctx["execution_path"], record)  # type: ignore[arg-type]
    with pytest.raises(ExecutionContractError, match="Unsupported secondary completion state"):
        _validate(run_dir, ctx)


def test_completed_run_validator_derives_different_identity_from_actual_provenance_hashes(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    run_parent = project / "out/runs"
    run_parent.mkdir(parents=True)
    data = project / "data"
    data.mkdir()
    _write_json(
        data / "input_sha256.json",
        {
            "schema_version": "rp1-analysis-v1.1",
            "provenance_schema_version": "rp1-input-provenance-v2",
            "files": [
                {
                    "origin_path": "upstream/example.csv",
                    "staged_path": "data/raw/example.csv",
                    "sha256": "b" * 64,
                    "size_bytes": 1,
                }
            ],
        },
    )
    run_dir, ctx = _valid_closeout(
        run_parent,
        mode="controlled_nbclient",
        canonical_input_identity="DIFFERENT",
    )
    resolved, checks = _validate(run_dir, ctx)
    assert resolved.mode_id == "controlled_nbclient"
    identity = next(row for row in checks if row["check"] == "canonical_input_identity")
    assert identity["observed"] == "DIFFERENT"


def test_completed_run_validator_rejects_false_match_against_actual_provenance_hashes(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    run_parent = project / "out/runs"
    run_parent.mkdir(parents=True)
    data = project / "data"
    data.mkdir()
    _write_json(
        data / "input_sha256.json",
        {
            "schema_version": "rp1-analysis-v1.1",
            "provenance_schema_version": "rp1-input-provenance-v2",
            "files": [
                {
                    "origin_path": "upstream/example.csv",
                    "staged_path": "data/raw/example.csv",
                    "sha256": "b" * 64,
                    "size_bytes": 1,
                }
            ],
        },
    )
    run_dir, ctx = _valid_closeout(run_parent, mode="interactive_jupyter")
    with pytest.raises(
        ExecutionContractError,
        match="canonical input identity disagrees with actual run-provenance input hashes",
    ):
        _validate(run_dir, ctx)
