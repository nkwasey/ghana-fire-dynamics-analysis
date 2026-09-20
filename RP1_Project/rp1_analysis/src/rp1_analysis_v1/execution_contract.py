"""Shared operational execution/closeout contract validation.

This module owns operational completion semantics only.  It deliberately owns
no scientific study-design values.  Notebook finalisation, the controlled
wrapper, the run validator and presentation export all consume the same
``config/execution_contract.yml`` authority and fail closed on ambiguous or
contradictory completion evidence.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from .contracts import ExecutionCloseoutContract, ExecutionModeContract
from .provenance import sha256_file

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CANONICAL_SECTION_GATE_FIELDS: tuple[tuple[str, str], ...] = (
    ("scaffold", "scaffold_gate"),
    ("rq1", "rq1_gate"),
    ("rq2", "rq2_gate"),
    ("rq3", "rq3_gate"),
    ("secondary", "secondary_gate"),
)


class ExecutionContractError(ValueError):
    """Raised when execution or closeout evidence violates the contract."""


def resolve_execution_mode(
    contract: ExecutionCloseoutContract,
    record: Mapping[str, Any],
) -> ExecutionModeContract:
    """Resolve the configured mode explicitly recorded by the execution authority.

    Missing and unknown modes always fail closed.  A missing automated artefact
    can therefore never cause implicit fallback to interactive semantics.
    """

    raw_mode = record.get("execution_mode")
    if not isinstance(raw_mode, str) or not raw_mode:
        raise ExecutionContractError("Notebook execution record is missing execution_mode")
    try:
        return contract.mode(raw_mode)
    except KeyError as exc:
        raise ExecutionContractError(f"Unsupported execution mode: {raw_mode}") from exc


def artifact_filename(contract: ExecutionCloseoutContract, role: str) -> str:
    try:
        return str(contract.artifact_roles[role])
    except KeyError as exc:
        raise ExecutionContractError(f"Unknown closeout artifact role: {role}") from exc


def required_artifact_filenames(
    contract: ExecutionCloseoutContract,
    mode: ExecutionModeContract | str,
) -> tuple[str, ...]:
    spec = contract.mode(mode) if isinstance(mode, str) else mode
    return tuple(artifact_filename(contract, role) for role in spec.required_artifact_roles)


def optional_artifact_filenames(
    contract: ExecutionCloseoutContract,
    mode: ExecutionModeContract | str,
) -> tuple[str, ...]:
    spec = contract.mode(mode) if isinstance(mode, str) else mode
    return tuple(artifact_filename(contract, role) for role in spec.optional_artifact_roles)


def validate_required_artifact_presence(
    contract: ExecutionCloseoutContract,
    mode: ExecutionModeContract | str,
    closeout_dir: str | Path,
) -> tuple[Path, ...]:
    """Require the configured mode-owned mandatory artefacts to be present."""

    root = Path(closeout_dir)
    spec = contract.mode(mode) if isinstance(mode, str) else mode
    paths = tuple(root / name for name in required_artifact_filenames(contract, spec))
    missing = [path.name for path in paths if not path.is_file()]
    if missing:
        raise ExecutionContractError(
            f"Missing required closeout artefact(s) for {spec.mode_id}: {', '.join(missing)}"
        )
    return paths


def validate_secondary_completion_state(
    contract: ExecutionCloseoutContract,
    execution_state: object,
    *,
    integration_state: object | None = None,
    require_integrated_if_validated: bool = False,
) -> str:
    """Validate a secondary-run completion state against the shared contract."""

    if not isinstance(execution_state, str) or not execution_state:
        raise ExecutionContractError("Secondary execution state must be a non-empty string")
    if execution_state not in contract.allowed_secondary_completion_states:
        raise ExecutionContractError(f"Unsupported secondary completion state: {execution_state}")
    if execution_state == "RESULTS_VALIDATED" and require_integrated_if_validated:
        if integration_state != contract.results_validated_required_integration_state:
            raise ExecutionContractError(
                "RESULTS_VALIDATED completion requires secondary integration state "
                f"{contract.results_validated_required_integration_state}"
            )
    return execution_state


def canonical_section_gates(gate: Mapping[str, Any]) -> dict[str, str]:
    """Project the canonical gate record into the execution-record gate mapping."""

    missing = [field for _, field in _CANONICAL_SECTION_GATE_FIELDS if field not in gate]
    if missing:
        raise ExecutionContractError(
            "Canonical execution gate is missing required section gate field(s): "
            + ", ".join(missing)
        )
    return {name: str(gate[field]) for name, field in _CANONICAL_SECTION_GATE_FIELDS}


def _require_sha256(record: Mapping[str, Any], field: str, *, context: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ExecutionContractError(f"{context} requires valid lowercase SHA-256 {field}")
    return value


def _require_nonempty_string(record: Mapping[str, Any], field: str, *, context: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value:
        raise ExecutionContractError(f"{context} requires non-empty {field}")
    return value


def _validate_completion_timestamp(record: Mapping[str, Any], *, context: str) -> None:
    timestamp = record.get("completion_timestamp_utc")
    if not isinstance(timestamp, str) or not timestamp.endswith("Z"):
        raise ExecutionContractError(
            f"{context} completion_timestamp_utc must be a UTC Z-suffixed string"
        )
    try:
        datetime.fromisoformat(timestamp[:-1] + "+00:00")
    except ValueError as exc:
        raise ExecutionContractError(
            f"{context} completion_timestamp_utc is not a valid ISO-8601 UTC timestamp"
        ) from exc


def validate_execution_record(
    record: Mapping[str, Any],
    contract: ExecutionCloseoutContract,
    *,
    expected_run_id: str | None = None,
) -> ExecutionModeContract:
    """Validate the configured mode-specific execution-record structure."""

    if not isinstance(record, Mapping):
        raise ExecutionContractError("Notebook execution record must be a mapping")
    mode = resolve_execution_mode(contract, record)
    context = (
        "Controlled notebook execution"
        if mode.mode_id == "controlled_nbclient"
        else "Interactive Jupyter completion"
    )
    if record.get("schema") != contract.execution_record_schema:
        raise ExecutionContractError(
            f"Notebook execution record schema must be {contract.execution_record_schema}"
        )
    missing_fields = [name for name in mode.required_record_fields if name not in record]
    if missing_fields:
        raise ExecutionContractError(
            f"Notebook execution record for {mode.mode_id} is missing required field(s): "
            + ", ".join(missing_fields)
        )
    if record.get("status") != contract.required_final_gate:
        raise ExecutionContractError(
            f"Notebook execution record status must be {contract.required_final_gate}"
        )
    run_id = record.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ExecutionContractError("Notebook execution record run_id must be a non-empty string")
    if expected_run_id is not None and run_id != expected_run_id:
        raise ExecutionContractError(
            f"Notebook execution record run_id mismatch: expected {expected_run_id}, observed {run_id}"
        )

    # Shared closeout identity and gate evidence.  Both valid modes must carry
    # these fields; only wrapper-observable evidence differs by mode.
    for field in (
        "reproducibility_manifest_sha256",
        "configuration_sha256",
        "canonical_gate_sha256",
        "operational_configuration_sha256",
    ):
        _require_sha256(record, field, context=context)
    for field in (
        "canonical_notebook",
        "package_version",
        "analysis_schema_version",
        "data_schema_version",
    ):
        _require_nonempty_string(record, field, context=context)
    if record.get("final_section_reached") is not True:
        raise ExecutionContractError(f"{context} requires final_section_reached=true")
    if record.get("canonical_gate_status") != contract.required_final_gate:
        raise ExecutionContractError(f"{context} requires canonical_gate_status=PASS")
    if record.get("publication_gate_status") != contract.required_final_gate:
        raise ExecutionContractError(f"{context} requires publication_gate_status=PASS")
    if record.get("input_validation_status") != contract.required_final_gate:
        raise ExecutionContractError(f"{context} requires input_validation_status=PASS")
    canonical_identity = record.get("canonical_input_identity")
    if canonical_identity not in {"MATCH", "DIFFERENT"}:
        raise ExecutionContractError(
            f"{context} requires canonical_input_identity to be MATCH or DIFFERENT"
        )
    section_gates = record.get("section_gates")
    if not isinstance(section_gates, Mapping) or not section_gates:
        raise ExecutionContractError(f"{context} requires section_gates mapping")
    if any(value != contract.required_final_gate for value in section_gates.values()):
        raise ExecutionContractError(f"{context} requires every section gate to PASS")

    secondary_state = validate_secondary_completion_state(
        contract,
        record.get("secondary_execution_state"),
        integration_state=record.get("secondary_integration_state"),
        require_integrated_if_validated=True,
    )
    validated_model_count = record.get("secondary_validated_model_count")
    if (
        isinstance(validated_model_count, bool)
        or not isinstance(validated_model_count, int)
        or validated_model_count < 0
    ):
        raise ExecutionContractError(
            f"{context} requires non-negative secondary_validated_model_count"
        )
    if secondary_state == "RESULTS_VALIDATED" and validated_model_count <= 0:
        raise ExecutionContractError(
            f"RESULTS_VALIDATED {mode.mode_id} completion requires a positive validated model count"
        )
    if secondary_state == "EXTERNAL_RESULTS_REQUIRED" and validated_model_count != 0:
        raise ExecutionContractError(
            f"EXTERNAL_RESULTS_REQUIRED {mode.mode_id} completion requires zero validated models"
        )
    if record.get("satscan_execution_performed") is not False:
        raise ExecutionContractError(
            f"{context} must record satscan_execution_performed=false"
        )
    if record.get("notebook_snapshot_required") is not mode.notebook_snapshot_required:
        raise ExecutionContractError(
            f"{context} notebook_snapshot_required contradicts the configured execution mode"
        )
    if record.get("notebook_snapshot_available") is not mode.notebook_snapshot_required:
        raise ExecutionContractError(
            f"{context} notebook_snapshot_available contradicts the configured execution mode"
        )
    _validate_completion_timestamp(record, context=context)

    if mode.code_cell_completion_rule == "executed_equals_total":
        code_cells = record.get("code_cells")
        executed = record.get("executed_code_cells")
        if (
            isinstance(code_cells, bool)
            or isinstance(executed, bool)
            or not isinstance(code_cells, int)
            or not isinstance(executed, int)
            or code_cells < 0
            or executed < 0
        ):
            raise ExecutionContractError(
                "Controlled notebook execution requires non-negative integer code-cell counts"
            )
        if code_cells != executed:
            raise ExecutionContractError(
                "Notebook execution record shows incomplete code-cell execution"
            )
    elif mode.code_cell_completion_rule != "not_required":
        raise ExecutionContractError(
            f"Unsupported code-cell completion rule: {mode.code_cell_completion_rule}"
        )

    if mode.notebook_snapshot_sha256_required:
        _require_sha256(record, "executed_notebook_sha256", context=context)

    if mode.mode_id == "interactive_jupyter":
        limitations = record.get("provenance_limitations")
        if (
            not isinstance(limitations, list)
            or not limitations
            or not all(isinstance(item, str) and item for item in limitations)
        ):
            raise ExecutionContractError(
                "Interactive Jupyter completion requires explicit provenance_limitations"
            )

    return mode


def _read_json_mapping(path: Path, *, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExecutionContractError(f"Malformed closeout {label}: {path.name}") from exc
    if not isinstance(payload, Mapping):
        raise ExecutionContractError(f"Malformed closeout {label}: {path.name} must contain a mapping")
    return payload


def validate_completed_closeout(
    closeout_run_dir: str | Path,
    contract: ExecutionCloseoutContract,
    *,
    expected_run_id: str,
    expected_configuration_sha256: str,
    expected_operational_configuration_sha256: str,
    expected_package_version: str,
    expected_analysis_schema_version: str,
    expected_data_schema_version: str,
    expected_secondary_state: str,
    expected_secondary_integration_state: str,
    expected_secondary_validated_model_count: int,
) -> tuple[ExecutionModeContract, tuple[dict[str, Any], ...]]:
    """Validate one completed closeout using the common execution authority.

    The execution record chooses the mode.  The mode then chooses the mandatory
    artefacts.  This ordering is deliberate: absent wrapper artefacts do not
    permit interactive fallback, and interactive runs are not forced to claim
    wrapper-only evidence.
    """

    run_root = Path(closeout_run_dir)
    section = run_root / contract.closeout_section
    execution_path = section / artifact_filename(contract, "execution_record")
    if not execution_path.is_file():
        raise ExecutionContractError(
            f"Missing execution authority artefact: {execution_path.name}"
        )
    execution = _read_json_mapping(execution_path, label="execution record")
    mode = validate_execution_record(execution, contract, expected_run_id=expected_run_id)
    validate_required_artifact_presence(contract, mode, section)

    gate_path = section / artifact_filename(contract, "canonical_gate")
    provenance_path = section / artifact_filename(contract, "reproducibility_manifest")
    gate = _read_json_mapping(gate_path, label="canonical gate")
    provenance = _read_json_mapping(provenance_path, label="reproducibility manifest")

    section_gates = canonical_section_gates(gate)
    if any(value != contract.required_final_gate for value in section_gates.values()):
        raise ExecutionContractError("Canonical section gate failure in completed run")
    if gate.get("publication_gate") != contract.required_final_gate:
        raise ExecutionContractError("Canonical publication gate is not PASS")
    if gate.get("final_run_gate") != contract.required_final_gate:
        raise ExecutionContractError("Canonical notebook final run gate is not PASS")
    if gate.get("input_validation_status") != contract.required_final_gate:
        raise ExecutionContractError("Canonical input validation gate is not PASS")
    gate_identity = gate.get("canonical_input_identity")
    if gate_identity not in {"MATCH", "DIFFERENT"}:
        raise ExecutionContractError(
            "Canonical execution gate must record canonical_input_identity as MATCH or DIFFERENT"
        )
    if gate.get("configuration_sha256") != expected_configuration_sha256:
        raise ExecutionContractError("Invalid configuration identity in canonical execution gate")

    if provenance.get("run_id") != f"{expected_run_id}_close":
        raise ExecutionContractError("Reproducibility manifest run identity is inconsistent")
    if provenance.get("configuration_sha256") != expected_configuration_sha256:
        raise ExecutionContractError("Invalid configuration identity in reproducibility manifest")
    if not provenance.get("ended_at_utc"):
        raise ExecutionContractError("Reproducibility manifest is not finalised")
    if provenance.get("input_validation_status") != contract.required_final_gate:
        raise ExecutionContractError("Reproducibility manifest input validation state is not PASS")
    provenance_identity = provenance.get("canonical_input_identity")
    if provenance_identity not in {"MATCH", "DIFFERENT"}:
        raise ExecutionContractError(
            "Reproducibility manifest must record canonical_input_identity as MATCH or DIFFERENT"
        )
    if provenance_identity != gate_identity:
        raise ExecutionContractError(
            "Reproducibility manifest canonical input identity is inconsistent with execution gate"
        )
    provenance_inputs = provenance.get("inputs")
    if not isinstance(provenance_inputs, list) or not provenance_inputs:
        raise ExecutionContractError("Reproducibility manifest must record actual current input identities")
    input_map: dict[str, tuple[str, int]] = {}
    for item in provenance_inputs:
        if not isinstance(item, Mapping):
            raise ExecutionContractError("Malformed input identity in reproducibility manifest")
        path = item.get("path")
        sha = item.get("sha256")
        size = item.get("size_bytes")
        if not isinstance(path, str) or not path or path in input_map:
            raise ExecutionContractError("Malformed or duplicate input path in reproducibility manifest")
        if not isinstance(sha, str) or _SHA256_RE.fullmatch(sha) is None:
            raise ExecutionContractError("Malformed input SHA-256 in reproducibility manifest")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ExecutionContractError("Malformed input size in reproducibility manifest")
        input_map[path] = (sha, size)

    # In a real governed run the closeout lives below <project>/out/runs/.  When
    # that project-local canonical inventory is available, independently derive
    # MATCH/DIFFERENT from the actual hashes recorded in provenance.  The
    # fallback path is used only by isolated contract-unit fixtures that do not
    # carry a project data tree.
    project_root = run_root.parent.parent.parent if len(run_root.parents) >= 3 else None
    canonical_inventory_path = (project_root / "data/input_sha256.json") if project_root else None
    if canonical_inventory_path is not None and canonical_inventory_path.is_file():
        try:
            canonical_inventory = json.loads(canonical_inventory_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ExecutionContractError("Malformed canonical input inventory during closeout validation") from exc
        canonical_files = canonical_inventory.get("files") if isinstance(canonical_inventory, Mapping) else None
        if not isinstance(canonical_files, list) or not canonical_files:
            raise ExecutionContractError("Canonical input inventory contains no files during closeout validation")
        canonical_map: dict[str, tuple[str, int]] = {}
        for item in canonical_files:
            if not isinstance(item, Mapping):
                raise ExecutionContractError("Malformed canonical input inventory entry during closeout validation")
            path = item.get("staged_path")
            sha = item.get("sha256")
            size = item.get("size_bytes")
            if not isinstance(path, str) or not isinstance(sha, str) or not isinstance(size, int):
                raise ExecutionContractError("Malformed canonical input inventory identity during closeout validation")
            canonical_map[path] = (sha.lower(), size)
        derived_identity = "MATCH" if input_map == canonical_map else "DIFFERENT"
        if derived_identity != provenance_identity:
            raise ExecutionContractError(
                "Recorded canonical input identity disagrees with actual run-provenance input hashes"
            )

    identity_expectations = {
        "configuration_sha256": expected_configuration_sha256,
        "operational_configuration_sha256": expected_operational_configuration_sha256,
        "package_version": expected_package_version,
        "analysis_schema_version": expected_analysis_schema_version,
        "data_schema_version": expected_data_schema_version,
    }
    for field, expected in identity_expectations.items():
        if execution.get(field) != expected:
            raise ExecutionContractError(
                f"Invalid configuration identity in execution record: {field}"
            )
    if execution.get("canonical_gate_sha256") != sha256_file(gate_path):
        raise ExecutionContractError("Execution record canonical-gate SHA-256 mismatch")
    if execution.get("reproducibility_manifest_sha256") != sha256_file(provenance_path):
        raise ExecutionContractError("Execution record reproducibility-manifest SHA-256 mismatch")
    if execution.get("canonical_gate_status") != gate.get("final_run_gate"):
        raise ExecutionContractError("Execution record canonical gate state is inconsistent")
    if execution.get("publication_gate_status") != gate.get("publication_gate"):
        raise ExecutionContractError("Execution record publication gate state is inconsistent")
    if dict(execution.get("section_gates", {})) != section_gates:
        raise ExecutionContractError("Execution record section gates are inconsistent")
    if execution.get("input_validation_status") != gate.get("input_validation_status"):
        raise ExecutionContractError("Execution record input validation state is inconsistent")
    if execution.get("canonical_input_identity") != gate_identity:
        raise ExecutionContractError("Execution record canonical input identity is inconsistent")
    if execution.get("input_validation_status") != provenance.get("input_validation_status"):
        raise ExecutionContractError(
            "Execution record input validation state is inconsistent with reproducibility manifest"
        )
    if execution.get("canonical_input_identity") != provenance_identity:
        raise ExecutionContractError(
            "Execution record canonical input identity is inconsistent with reproducibility manifest"
        )

    if execution.get("secondary_execution_state") != expected_secondary_state:
        raise ExecutionContractError("Execution record secondary state is inconsistent with validated run")
    if execution.get("secondary_integration_state") != expected_secondary_integration_state:
        raise ExecutionContractError(
            "Execution record secondary integration state is inconsistent with validated run"
        )
    if execution.get("secondary_validated_model_count") != expected_secondary_validated_model_count:
        raise ExecutionContractError(
            "Execution record validated SaTScan model count is inconsistent with validated run"
        )

    if mode.notebook_snapshot_required:
        executed_notebook = section / artifact_filename(contract, "executed_notebook")
        observed = sha256_file(executed_notebook)
        if execution.get("executed_notebook_sha256") != observed:
            raise ExecutionContractError("Automated executed-notebook SHA-256 mismatch")

    checks: tuple[dict[str, Any], ...] = (
        {"check": "execution_mode", "status": "PASS", "observed": mode.mode_id},
        {"check": "canonical_execution_gate", "status": "PASS", "observed": "PASS"},
        {
            "check": "input_validation_status",
            "status": "PASS",
            "observed": str(execution["input_validation_status"]),
        },
        {
            "check": "canonical_input_identity",
            "status": "PASS",
            "observed": str(execution["canonical_input_identity"]),
        },
        {
            "check": "execution_configuration_identity",
            "status": "PASS",
            "observed": expected_configuration_sha256,
        },
        {
            "check": "execution_operational_configuration_identity",
            "status": "PASS",
            "observed": expected_operational_configuration_sha256,
        },
        {
            "check": "execution_secondary_state",
            "status": "PASS",
            "observed": expected_secondary_state,
        },
    )
    if mode.code_cell_completion_rule == "executed_equals_total":
        checks = checks + (
            {
                "check": "notebook_code_cells",
                "status": "PASS",
                "observed": int(execution["executed_code_cells"]),
            },
            {
                "check": "executed_notebook_sha256",
                "status": "PASS",
                "observed": str(execution["executed_notebook_sha256"]),
            },
        )
    else:
        checks = checks + (
            {
                "check": "interactive_finalisation_evidence",
                "status": "PASS",
                "observed": True,
            },
        )
    return mode, checks


__all__ = [
    "ExecutionContractError",
    "artifact_filename",
    "canonical_section_gates",
    "optional_artifact_filenames",
    "required_artifact_filenames",
    "resolve_execution_mode",
    "validate_completed_closeout",
    "validate_execution_record",
    "validate_required_artifact_presence",
    "validate_secondary_completion_state",
]
