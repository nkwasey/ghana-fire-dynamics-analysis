from __future__ import annotations

import copy
import hashlib
import shutil
from pathlib import Path

import pytest
import yaml

from rp1_analysis_v1.config import (
    ConfigurationError,
    load_configuration_bundle,
    load_execution_contract,
)
from rp1_analysis_v1.execution_contract import (
    ExecutionContractError,
    optional_artifact_filenames,
    required_artifact_filenames,
    resolve_execution_mode,
    validate_execution_record,
    validate_required_artifact_presence,
    validate_secondary_completion_state,
)

SUBPROJECT = Path(__file__).resolve().parents[1]
CONFIG = SUBPROJECT / "config"


def _copy_project_config(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir(parents=True)
    shutil.copytree(CONFIG, root / "config")
    shutil.copy2(SUBPROJECT / "pyproject.toml", root / "pyproject.toml")
    return root / "config"


def _mutate(path: Path, mutate) -> None:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(raw)
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


def _controlled_record(**updates):
    record = {
        "schema": "rp1-notebook-execution-v3",
        "status": "PASS",
        "run_id": "example_run",
        "execution_mode": "controlled_nbclient",
        "canonical_notebook": "RP1_Analysis_v1.ipynb",
        "package_version": "1.2.3",
        "analysis_schema_version": "rp1-analysis-v1.1",
        "data_schema_version": "rp1-data-schema-v1.1",
        "configuration_sha256": "c" * 64,
        "operational_configuration_sha256": "e" * 64,
        "final_section_reached": True,
        "canonical_gate_status": "PASS",
        "canonical_gate_sha256": "d" * 64,
        "reproducibility_manifest_sha256": "b" * 64,
        "publication_gate_status": "PASS",
        "section_gates": {
            "scaffold": "PASS",
            "rq1": "PASS",
            "rq2": "PASS",
            "rq3": "PASS",
            "secondary": "PASS",
        },
        "input_validation_status": "PASS",
        "canonical_input_identity": "MATCH",
        "secondary_execution_state": "RESULTS_VALIDATED",
        "secondary_integration_state": "INTEGRATED",
        "secondary_validated_model_count": 2,
        "satscan_execution_performed": False,
        "notebook_snapshot_required": True,
        "notebook_snapshot_available": True,
        "completion_timestamp_utc": "2026-09-10T10:00:00Z",
        "kernel_name": "python3",
        "execution_cwd_policy": "isolated_temporary_directory",
        "code_cells": 18,
        "executed_code_cells": 18,
        "executed_notebook_sha256": "a" * 64,
    }
    record.update(updates)
    return record


def _interactive_record(**updates):
    record = {
        "schema": "rp1-notebook-execution-v3",
        "status": "PASS",
        "run_id": "example_run",
        "execution_mode": "interactive_jupyter",
        "canonical_notebook": "RP1_Analysis_v1.ipynb",
        "final_section_reached": True,
        "canonical_gate_status": "PASS",
        "reproducibility_manifest_sha256": "b" * 64,
        "configuration_sha256": "c" * 64,
        "secondary_execution_state": "RESULTS_VALIDATED",
        "secondary_integration_state": "INTEGRATED",
        "completion_timestamp_utc": "2026-09-10T10:00:00Z",
        "canonical_gate_sha256": "d" * 64,
        "operational_configuration_sha256": "e" * 64,
        "package_version": "1.2.3",
        "analysis_schema_version": "rp1-analysis-v1.1",
        "data_schema_version": "rp1-data-schema-v1.1",
        "publication_gate_status": "PASS",
        "section_gates": {"scaffold": "PASS", "rq1": "PASS", "rq2": "PASS", "rq3": "PASS", "secondary": "PASS"},
        "input_validation_status": "PASS",
        "canonical_input_identity": "MATCH",
        "secondary_validated_model_count": 2,
        "satscan_execution_performed": False,
        "notebook_snapshot_required": False,
        "notebook_snapshot_available": False,
        "provenance_limitations": ["interactive frontend save state not attested"],
    }
    record.update(updates)
    return record


def test_execution_contract_loads_as_separate_operational_authority() -> None:
    bundle = load_configuration_bundle(CONFIG)
    contract = bundle.execution
    assert contract.schema_version == "rp1-execution-contract-v1"
    assert contract.contract_id == "rp1-run-completion-v1"
    assert contract.execution_record_schema == "rp1-notebook-execution-v3"
    assert set(contract.modes) == {"controlled_nbclient", "interactive_jupyter"}
    assert set(bundle.file_hashes) == {
        "analysis_contract.yml",
        "data_schema_contract.yml",
        "method_authorities.yml",
        "output_contract.yml",
        "figure_contract.yml",
    }
    assert set(bundle.operational_file_hashes) == {"execution_contract.yml"}
    assert len(bundle.configuration_sha256) == 64
    assert len(bundle.operational_configuration_sha256) == 64


def test_execution_contract_is_recorded_separately_in_realised_configuration() -> None:
    realised = load_configuration_bundle(CONFIG).realised_dict()
    assert set(realised["operational_config_file_sha256"]) == {"execution_contract.yml"}
    assert realised["operational_contracts"]["execution_contract.yml"]["contract_id"] == "rp1-run-completion-v1"
    assert "execution_contract.yml" not in realised["config_file_sha256"]
    assert "execution_contract.yml" not in realised["contracts"]


def test_operational_mutation_changes_only_operational_hash(tmp_path: Path) -> None:
    original = load_configuration_bundle(CONFIG)
    config = _copy_project_config(tmp_path)
    _mutate(
        config / "execution_contract.yml",
        lambda raw: raw["modes"]["interactive_jupyter"]["optional_artifact_roles"].clear(),
    )
    # Clearing the sole optional role is a semantically valid operational mutation.
    mutated = load_configuration_bundle(config)
    assert mutated.configuration_sha256 == original.configuration_sha256
    assert mutated.file_hashes == original.file_hashes
    assert mutated.operational_configuration_sha256 != original.operational_configuration_sha256


def test_mode_artifact_requirements_are_explicit() -> None:
    contract = load_execution_contract(CONFIG / "execution_contract.yml")
    assert required_artifact_filenames(contract, "controlled_nbclient") == (
        "M_CANONICAL_EXECUTION_GATE.json",
        "M_REPRODUCIBILITY_MANIFEST.json",
        "M_NOTEBOOK_EXECUTION.json",
        "RP1_Analysis_v1.executed.ipynb",
    )
    assert required_artifact_filenames(contract, "interactive_jupyter") == (
        "M_CANONICAL_EXECUTION_GATE.json",
        "M_REPRODUCIBILITY_MANIFEST.json",
        "M_NOTEBOOK_EXECUTION.json",
    )
    assert optional_artifact_filenames(contract, "interactive_jupyter") == (
        "RP1_Analysis_v1.executed.ipynb",
    )


def test_missing_and_unknown_execution_modes_fail_closed() -> None:
    contract = load_execution_contract(CONFIG / "execution_contract.yml")
    with pytest.raises(ExecutionContractError, match="missing execution_mode"):
        resolve_execution_mode(contract, {"status": "PASS"})
    with pytest.raises(ExecutionContractError, match="Unsupported execution mode"):
        resolve_execution_mode(contract, {"execution_mode": "invented_mode"})



def test_execution_record_schema_mismatch_fails_closed() -> None:
    contract = load_execution_contract(CONFIG / "execution_contract.yml")
    with pytest.raises(ExecutionContractError, match="record schema"):
        validate_execution_record(_controlled_record(schema="rp1-notebook-execution-v1"), contract)


def test_controlled_mode_preserves_strict_code_cell_and_snapshot_evidence() -> None:
    contract = load_execution_contract(CONFIG / "execution_contract.yml")
    mode = validate_execution_record(_controlled_record(), contract, expected_run_id="example_run")
    assert mode.mode_id == "controlled_nbclient"
    with pytest.raises(ExecutionContractError, match="incomplete code-cell execution"):
        validate_execution_record(_controlled_record(executed_code_cells=17), contract)
    with pytest.raises(ExecutionContractError, match="executed_notebook_sha256"):
        validate_execution_record(_controlled_record(executed_notebook_sha256="bad"), contract)


def test_controlled_mode_accepts_valid_noncanonical_input_identity() -> None:
    contract = load_execution_contract(CONFIG / "execution_contract.yml")
    mode = validate_execution_record(
        _controlled_record(canonical_input_identity="DIFFERENT"),
        contract,
        expected_run_id="example_run",
    )
    assert mode.mode_id == "controlled_nbclient"


def test_interactive_mode_does_not_claim_wrapper_code_cell_or_snapshot_requirement() -> None:
    contract = load_execution_contract(CONFIG / "execution_contract.yml")
    mode = validate_execution_record(_interactive_record(), contract, expected_run_id="example_run")
    assert mode.mode_id == "interactive_jupyter"
    assert mode.notebook_snapshot_required is False
    assert mode.notebook_snapshot_sha256_required is False
    assert mode.code_cell_completion_rule == "not_required"
    assert "executed_notebook" not in mode.required_artifact_roles


def test_execution_record_missing_required_field_fails_closed() -> None:
    contract = load_execution_contract(CONFIG / "execution_contract.yml")
    record = _interactive_record()
    del record["reproducibility_manifest_sha256"]
    with pytest.raises(ExecutionContractError, match="missing required field"):
        validate_execution_record(record, contract)


def test_execution_record_run_identity_and_status_fail_closed() -> None:
    contract = load_execution_contract(CONFIG / "execution_contract.yml")
    with pytest.raises(ExecutionContractError, match="run_id mismatch"):
        validate_execution_record(_controlled_record(), contract, expected_run_id="other")
    with pytest.raises(ExecutionContractError, match="status must be PASS"):
        validate_execution_record(_controlled_record(status="FAIL"), contract)


def test_interactive_results_validated_requires_integrated_secondary_state() -> None:
    contract = load_execution_contract(CONFIG / "execution_contract.yml")
    with pytest.raises(ExecutionContractError, match="requires secondary integration state INTEGRATED"):
        validate_execution_record(_interactive_record(secondary_integration_state="NOT_INTEGRATED"), contract)
    with pytest.raises(ExecutionContractError, match="Unsupported secondary completion state"):
        validate_execution_record(_interactive_record(secondary_execution_state="INPUTS_READY"), contract)


def test_interactive_external_results_required_is_legitimate_without_integrated_state() -> None:
    contract = load_execution_contract(CONFIG / "execution_contract.yml")
    record = _interactive_record(
        secondary_execution_state="EXTERNAL_RESULTS_REQUIRED",
        secondary_integration_state="NOT_INTEGRATED",
        secondary_validated_model_count=0,
    )
    assert validate_execution_record(record, contract).mode_id == "interactive_jupyter"


def test_interactive_final_section_gate_hashes_and_timestamp_are_fail_closed() -> None:
    contract = load_execution_contract(CONFIG / "execution_contract.yml")
    with pytest.raises(ExecutionContractError, match="final_section_reached=true"):
        validate_execution_record(_interactive_record(final_section_reached=False), contract)
    with pytest.raises(ExecutionContractError, match="canonical_gate_status=PASS"):
        validate_execution_record(_interactive_record(canonical_gate_status="FAIL"), contract)
    with pytest.raises(ExecutionContractError, match="configuration_sha256"):
        validate_execution_record(_interactive_record(configuration_sha256="bad"), contract)
    with pytest.raises(ExecutionContractError, match="UTC Z-suffixed"):
        validate_execution_record(_interactive_record(completion_timestamp_utc="2026-09-10"), contract)


def test_mode_specific_artifact_presence_is_enforced(tmp_path: Path) -> None:
    contract = load_execution_contract(CONFIG / "execution_contract.yml")
    for name in required_artifact_filenames(contract, "interactive_jupyter"):
        (tmp_path / name).write_text("x", encoding="utf-8")
    validate_required_artifact_presence(contract, "interactive_jupyter", tmp_path)
    with pytest.raises(ExecutionContractError, match="RP1_Analysis_v1.executed.ipynb"):
        validate_required_artifact_presence(contract, "controlled_nbclient", tmp_path)


def test_execution_contract_rejects_unknown_mode_configuration(tmp_path: Path) -> None:
    config = _copy_project_config(tmp_path)
    _mutate(
        config / "execution_contract.yml",
        lambda raw: raw["modes"].__setitem__("invented", copy.deepcopy(raw["modes"]["interactive_jupyter"])),
    )
    with pytest.raises(ConfigurationError, match="modes must contain exactly"):
        load_execution_contract(config / "execution_contract.yml")


def test_execution_contract_rejects_missing_mode_and_weakened_automated_evidence(tmp_path: Path) -> None:
    config = _copy_project_config(tmp_path)
    _mutate(config / "execution_contract.yml", lambda raw: raw["modes"].pop("interactive_jupyter"))
    with pytest.raises(ConfigurationError, match="modes must contain exactly"):
        load_execution_contract(config / "execution_contract.yml")

    config = _copy_project_config(tmp_path / "second")
    _mutate(
        config / "execution_contract.yml",
        lambda raw: raw["modes"]["controlled_nbclient"].__setitem__("notebook_snapshot_required", False),
    )
    with pytest.raises(ConfigurationError, match="controlled_nbclient must require"):
        load_execution_contract(config / "execution_contract.yml")


def test_execution_contract_rejects_interactive_snapshot_requirement(tmp_path: Path) -> None:
    config = _copy_project_config(tmp_path)
    _mutate(
        config / "execution_contract.yml",
        lambda raw: raw["modes"]["interactive_jupyter"].__setitem__("notebook_snapshot_required", True),
    )
    with pytest.raises(ConfigurationError, match="interactive_jupyter must not require"):
        load_execution_contract(config / "execution_contract.yml")


def test_execution_contract_rejects_non_fail_closed_policy(tmp_path: Path) -> None:
    config = _copy_project_config(tmp_path)
    _mutate(
        config / "execution_contract.yml",
        lambda raw: raw["validation"].__setitem__("unknown_mode_policy", "fallback"),
    )
    with pytest.raises(ConfigurationError, match="must be fail_closed"):
        load_execution_contract(config / "execution_contract.yml")


def test_scientific_contract_hashes_are_unchanged_by_execution_contract_addition() -> None:
    bundle = load_configuration_bundle(CONFIG)
    expected = {
        "analysis_contract.yml": "9692b53595028e3832c0106e3476edf5d83b7d7763830777bf9c97c9629569ec",
        "data_schema_contract.yml": "d7b8ed574438804457e50d04b0135066161061976ca4aa8c6f0944b61a163abf",
        "figure_contract.yml": "2ae903fd375fee6276fb54938fdaf92843ba853f35ea1213bfd476b3493aeeb1",
        "method_authorities.yml": "248bb4aa5f0d05c75fcfd402eb68446184f7486a1060980849c8bf62ab0bdd70",
        "output_contract.yml": "ac4559a71526eb37969fdcd1f2572f7868ab8837a1aebc5cad9418eafab74c3d",
    }
    assert dict(bundle.file_hashes) == expected
    expected_digest = hashlib.sha256(
        __import__("json").dumps(dict(sorted(expected.items())), separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    assert bundle.configuration_sha256 == expected_digest == "19b683cd27d3593bdcca90f4980aad467fda8203d28a9fff6d5ad88d5211c332"


def test_secondary_completion_state_is_contract_driven() -> None:
    contract = load_execution_contract(CONFIG / "execution_contract.yml")
    assert validate_secondary_completion_state(contract, "EXTERNAL_RESULTS_REQUIRED") == "EXTERNAL_RESULTS_REQUIRED"
    assert validate_secondary_completion_state(contract, "RESULTS_VALIDATED") == "RESULTS_VALIDATED"
    with pytest.raises(ExecutionContractError, match="Unsupported secondary completion state"):
        validate_secondary_completion_state(contract, "INPUTS_READY")


def test_results_validated_state_can_require_integrated_evidence_when_available() -> None:
    contract = load_execution_contract(CONFIG / "execution_contract.yml")
    assert (
        validate_secondary_completion_state(
            contract,
            "RESULTS_VALIDATED",
            integration_state="INTEGRATED",
            require_integrated_if_validated=True,
        )
        == "RESULTS_VALIDATED"
    )
    with pytest.raises(ExecutionContractError, match="requires secondary integration state INTEGRATED"):
        validate_secondary_completion_state(
            contract,
            "RESULTS_VALIDATED",
            integration_state="NOT_INTEGRATED",
            require_integrated_if_validated=True,
        )


def test_interactive_completion_requires_honest_extended_provenance_fields() -> None:
    contract = load_execution_contract(CONFIG / "execution_contract.yml")
    with pytest.raises(ExecutionContractError, match="publication_gate_status=PASS"):
        validate_execution_record(_interactive_record(publication_gate_status="FAIL"), contract)
    with pytest.raises(ExecutionContractError, match="every section gate to PASS"):
        validate_execution_record(_interactive_record(section_gates={"rq1": "FAIL"}), contract)
    with pytest.raises(ExecutionContractError, match="satscan_execution_performed=false"):
        validate_execution_record(_interactive_record(satscan_execution_performed=True), contract)
    with pytest.raises(ExecutionContractError, match="provenance_limitations"):
        validate_execution_record(_interactive_record(provenance_limitations=[]), contract)
    with pytest.raises(ExecutionContractError, match="positive validated model count"):
        validate_execution_record(_interactive_record(secondary_validated_model_count=0), contract)


@pytest.mark.parametrize("identity", ["MATCH", "DIFFERENT"])
def test_execution_record_rejects_failed_input_validation_for_any_identity(identity: str) -> None:
    contract = load_execution_contract(CONFIG / "execution_contract.yml")
    with pytest.raises(ExecutionContractError, match="input_validation_status=PASS"):
        validate_execution_record(
            _controlled_record(
                input_validation_status="FAIL",
                canonical_input_identity=identity,
            ),
            contract,
        )
