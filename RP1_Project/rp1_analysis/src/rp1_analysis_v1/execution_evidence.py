"""Prospective external execution receipts and separate, immutable evidence bundles.

An execution receipt is created by an observed invocation, never by importing an
old output directory. Historical/manual result ingestion remains supported and
does not acquire a retroactive executable attestation.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
from io import StringIO
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import tempfile
from types import SimpleNamespace
from typing import Any, Mapping

import nbformat
import pandas as pd

from .atomic_io import publish_file_no_replace
from .satscan_io import ExternalResultValidationError, sha256_file

RECEIPT_SCHEMA = "rp1-satscan-observed-execution-v2"
_LEGACY_RECEIPT_SCHEMA = "rp1-satscan-observed-execution-v1"
BUNDLE_SCHEMA = "rp1-execution-evidence-bundle-v1"
_MANIFEST = "EXECUTION_EVIDENCE_MANIFEST.json"
_CANONICAL_NOTEBOOK = "RP1_Analysis_v1.ipynb"
_NOTEBOOK_AUTHORITY = f"authority/{_CANONICAL_NOTEBOOK}"
_PRIMARY_MODELS = {
    "MCD64A1_POISSON_PRIMARY": ("mcd64a1", "discrete_poisson"),
    "VIIRS_STP_PRIMARY": ("viirs", "space_time_permutation"),
}
_SHA = re.compile(r"^[0-9a-f]{64}$")
_INPUT_ROLES = (("parameter", "prm_path", "prm_sha256"),
                ("case", "case_path", "case_sha256"),
                ("coordinate", "coordinate_path", "coordinate_sha256"),
                ("population", "population_path", "population_sha256"))


def _child(root: Path, relative: str) -> Path:
    if not isinstance(relative, str):
        raise ExternalResultValidationError("Execution-evidence path must be a string")
    token = PurePosixPath(relative)
    if (not relative or token.is_absolute() or ".." in token.parts or "\\" in relative
            or ":" in relative or token.as_posix() != relative):
        raise ExternalResultValidationError(f"Unsafe execution-evidence path: {relative!r}")
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()):
        raise ExternalResultValidationError("Execution-evidence path escapes the run")
    current = root
    for part in token.parts:
        current = current / part
        if current.is_symlink():
            raise ExternalResultValidationError("Linked execution-evidence paths are not accepted")
    return path


def _identity(root: Path, path: Path) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    path = _child(root, relative)
    if not path.is_file():
        raise ExternalResultValidationError(f"Missing execution-evidence file: {relative}")
    return {"path": relative, "sha256": sha256_file(path), "bytes": path.stat().st_size}


def _publish(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".execution_", suffix=".tmp", dir=path.parent)
    temp = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
        publish_file_no_replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _publish_json(path: Path, record: Mapping[str, Any]) -> str:
    payload = (json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    digest = sha256(payload).hexdigest()
    _publish(path, payload)
    return digest


def _text(value: Any) -> str:
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value or "")


def _input_identities(root: Path, row: Mapping[str, Any]) -> dict[str, Any]:
    identities = {}
    for role, path_key, hash_key in _INPUT_ROLES:
        relative = str(row.get(path_key, "") or "")
        if role == "population" and not relative:
            continue
        identity = _identity(root, _child(root, relative))
        if identity["sha256"] != str(row.get(hash_key, "")):
            raise ExternalResultValidationError(f"Pre-execution input authority mismatch: {path_key}")
        identities[role] = identity
    return identities


def _validate_parameter_inputs(root: Path, row: Mapping[str, Any]) -> None:
    """Bind the actually invoked parameter file to every recorded input path."""
    from .satscan_io import _parameter_value
    parameter = _child(root, str(row["prm_path"]))
    for key, column in (("CaseFile", "case_path"), ("CoordinatesFile", "coordinate_path"),
                        ("PopulationFile", "population_path"), ("ResultsFile", "results_prefix")):
        if _parameter_value(parameter, key) != str(row.get(column, "") or ""):
            raise ExternalResultValidationError(f"Parameter {key} differs from the recorded run authority")


def execute_satscan_with_evidence(
    *, run_row: Mapping[str, Any], run_dir: str | Path,
    executable_path: str | Path, alpha: float, timeout_seconds: int = 3600,
) -> Mapping[str, Any]:
    """Explicitly invoke one new external model and retain its observed evidence.

    Existing output/receipt/log paths are refused. A failed invocation keeps a
    failure record and any raw output; use a fresh run/model destination instead
    of replacing that history. This function never integrates or edits registries.
    """
    from . import satscan_io
    root = Path(run_dir).resolve()
    if not root.is_dir() or timeout_seconds <= 0:
        raise ExternalResultValidationError("A run directory and positive timeout are required")
    row = dict(run_row)
    prefix = str(row.get("results_prefix", ""))
    report = _child(root, prefix)
    outputs = {"report": report, "clusters": _child(root, prefix + ".col.txt"),
               "membership": _child(root, prefix + ".gis.txt")}
    maxima = _child(root, prefix + ".llr.txt")
    receipt_path = _child(root, prefix + ".execution.json")
    failure_path = _child(root, prefix + ".execution.failed.json")
    log_paths = {"stdout": _child(root, prefix + ".stdout.log"),
                 "stderr": _child(root, prefix + ".stderr.log")}
    lock = _child(root, prefix + ".execution.lock")
    collisions = [p for p in [*outputs.values(), maxima, receipt_path, failure_path, *log_paths.values(), lock]
                  if p.exists()]
    if collisions:
        raise ExternalResultValidationError(f"Execution refuses existing output/evidence: {collisions[0]}")
    report.parent.mkdir(parents=True, exist_ok=True)
    # A per-prefix exclusive reservation prevents two wrappers claiming one run.
    with lock.open("x", encoding="utf-8") as handle:
        handle.write("Observed execution in progress; retain on interruption.\n")
    observed: dict[str, Any] = {}
    try:
        before = _input_identities(root, row)
        _validate_parameter_inputs(root, row)
        binary = satscan_io.executable_provenance(executable_path)
        if binary.version != str(row["engine_version_authority"]):
            raise ExternalResultValidationError("Observed executable version differs from the governed authority")
        binary_path = Path(binary.path)
        if not binary_path.is_file() or sha256_file(binary_path) != binary.sha256:
            raise ExternalResultValidationError("Executable identity changed before execution")
        result = satscan_io.run_satscan(
            executable_path=binary_path, parameter_path=_child(root, str(row["prm_path"])),
            case_path=_child(root, str(row["case_path"])), coordinate_path=_child(root, str(row["coordinate_path"])),
            population_path=None if "population" not in before else _child(root, before["population"]["path"]),
            scenario_id=str(row["scenario_id"]), product=str(row["product"]), model=str(row["model"]),
            temporal_start=str(row["temporal_start"]), temporal_end=str(row["temporal_end"]),
            results_prefix=prefix, cwd=root, engine_version_authority=str(row["engine_version_authority"]),
            scientific_seed=int(row["scientific_seed"]),
            user_defined_random_seed_supported=str(row.get("user_defined_random_seed_supported", False)).lower() == "true",
            user_defined_random_seed_parameter=str(row.get("user_defined_random_seed_parameter", "") or "") or None,
            rng_authority=str(row["rng_authority"]), engine_rng_behaviour=str(row["engine_rng_behaviour"]),
            alpha=float(alpha), max_temporal_months=int(row["max_temporal_months"]),
            timeout_seconds=timeout_seconds, execution_observer=lambda event: observed.update(event),
        )
        after = _input_identities(root, row)
        if after != before or sha256_file(binary_path) != binary.sha256:
            raise ExternalResultValidationError("Executable or governed input changed during execution")
        if any(result[key] != expected for key, expected in (
                ("executable_path", binary.path), ("executable_sha256", binary.sha256),
                ("executable_version", binary.version))):
            raise ExternalResultValidationError("Invoked executable differs from the preflight identity")
        if maxima.exists() or maxima.is_symlink():
            outputs["monte_carlo_maxima"] = maxima
        output_identities = {role: _identity(root, path) for role, path in outputs.items()}
        validated_hashes = {
            "report": result["validated_report_sha256"],
            "clusters": result["validated_cluster_sha256"],
            "membership": result["validated_membership_sha256"],
        }
        if result["validated_maxima_sha256"] is not None:
            validated_hashes["monte_carlo_maxima"] = result["validated_maxima_sha256"]
        if {role: identity["sha256"] for role, identity in output_identities.items()} != validated_hashes:
            raise ExternalResultValidationError("SaTScan native outputs changed after validation")
        for stream, path in log_paths.items():
            _publish(path, _text(observed.get(stream)).encode("utf-8"))
        receipt = {
            "schema": RECEIPT_SCHEMA, "status": "PASS", "capture_method": "observed_subprocess",
            "scenario_id": str(row["scenario_id"]), "product": str(row["product"]),
            "model": str(row["model"]), "results_prefix": prefix,
            "executable": {"path": binary.path, "version": binary.version, "sha256": binary.sha256},
            "command": observed["command"], "working_directory": observed["working_directory"],
            "platform": observed["platform"], "execution_started_utc": observed["execution_started_utc"],
            "execution_completed_utc": observed["execution_completed_utc"],
            "return_code": observed["return_code"], "timed_out": observed["timed_out"],
            "inputs_before": before, "inputs_after": after,
            "executable_sha256_after": sha256_file(binary_path),
            "outputs": output_identities,
            "logs": {role: _identity(root, path) for role, path in log_paths.items()},
            "result_family_validated": bool(result["result_family_validated"]),
        }
        # A PASS receipt is the terminal marker. Validate before publishing it.
        try:
            _validate_receipt_record(receipt, run_row=row, root=root)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ExternalResultValidationError(f"Invalid prospective execution receipt: {exc}") from exc
        receipt_digest = _publish_json(receipt_path, receipt)
        return {"status": "PASS", "receipt_path": receipt_path.relative_to(root).as_posix(),
                "receipt_sha256": receipt_digest, **receipt}
    except BaseException as exc:
        # Preserve observed failure evidence without falsely attesting success.
        for stream, path in log_paths.items():
            if not path.exists():
                _publish(path, _text(observed.get(stream)).encode("utf-8"))
        if not failure_path.exists():
            _publish_json(failure_path, {"schema": RECEIPT_SCHEMA, "status": "FAIL",
                "capture_method": "observed_subprocess", "scenario_id": str(row.get("scenario_id", "")),
                "execution_observed": bool(observed), "error_type": type(exc).__name__, "error": str(exc),
                "observed": {k: _text(v) if k in {"stdout", "stderr"} else v for k, v in observed.items()},
                "recorded_utc": datetime.now(timezone.utc).isoformat()})
        raise
    finally:
        lock.unlink(missing_ok=True)


def validate_satscan_execution_receipt(
    receipt_path: str | Path, *, run_row: Mapping[str, Any], run_dir: str | Path,
) -> Mapping[str, Any]:
    """Validate optional prospective evidence; never infer it from old result bytes."""
    root = Path(run_dir).resolve()
    prefix = str(run_row.get("results_prefix", ""))
    expected_path = _child(root, prefix + ".execution.json")
    if Path(receipt_path).resolve() != expected_path.resolve():
        raise ExternalResultValidationError("Execution receipt is not at its governed ResultsFile path")
    try:
        record = _read_evidence_json(expected_path)
        for suffix in (".execution.failed.json", ".execution.lock"):
            if _child(root, prefix + suffix).exists():
                raise ValueError("Execution receipt contradicts a failed or in-progress invocation")
        _validate_receipt_record(record, run_row=run_row, root=root)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ExternalResultValidationError(f"Invalid prospective execution receipt: {exc}") from exc
    return record


def _validate_receipt_record(
    record: Mapping[str, Any], *, run_row: Mapping[str, Any], root: Path,
) -> None:
    """Check terminal receipt semantics against the current input and output bytes."""
    prefix = str(run_row["results_prefix"])
    if (record["schema"] not in {RECEIPT_SCHEMA, _LEGACY_RECEIPT_SCHEMA} or record["status"] != "PASS"
            or record["capture_method"] != "observed_subprocess"
            or type(record["return_code"]) is not int or record["return_code"] != 0
            or record["timed_out"] is not False
            or record["result_family_validated"] is not True):
        raise ValueError("Execution is not a successful observed invocation")
    for key in ("scenario_id", "product", "model", "results_prefix"):
        if record[key] != str(run_row[key]):
            raise ValueError(f"Execution receipt identity mismatch: {key}")
    binary = record["executable"]
    if (not _SHA.fullmatch(binary["sha256"]) or binary["version"] != str(run_row["engine_version_authority"])
            or record["executable_sha256_after"] != binary["sha256"]):
        raise ValueError("Execution receipt executable identity mismatch")
    if (not isinstance(record["command"], list) or len(record["command"]) != 2
            or record["command"][0] != binary["path"] or not record["platform"]
            or not record["working_directory"]):
        raise ValueError("Execution receipt lacks observed command/environment")
    # Lexical validation retains portability: the original execution machine
    # and binary need not exist on the machine validating a transferred run.
    path_type = PureWindowsPath if "\\" in record["working_directory"] or re.match(r"^[A-Za-z]:", record["working_directory"]) else PurePosixPath
    working_directory = path_type(record["working_directory"])
    if (not working_directory.is_absolute() or path_type(record["command"][1]) !=
            working_directory.joinpath(*PurePosixPath(str(run_row["prm_path"])).parts)):
        raise ValueError("Execution receipt command does not invoke its governed parameter file")
    started = datetime.fromisoformat(record["execution_started_utc"])
    ended = datetime.fromisoformat(record["execution_completed_utc"])
    if started.tzinfo is None or ended.tzinfo is None or ended < started:
        raise ValueError("Execution receipt has invalid timestamps")
    expected_inputs = _input_identities(root, run_row)
    _validate_parameter_inputs(root, run_row)
    if record["inputs_before"] != expected_inputs or record["inputs_after"] != expected_inputs:
        raise ValueError("Execution receipt input identities do not match current authorities")
    expected_outputs = {"report": prefix, "clusters": prefix + ".col.txt", "membership": prefix + ".gis.txt"}
    if record["schema"] == RECEIPT_SCHEMA:
        maxima = prefix + ".llr.txt"
        if _child(root, maxima).exists():
            expected_outputs["monte_carlo_maxima"] = maxima
    for group, expected in [("outputs", expected_outputs), ("logs", {"stdout": prefix + ".stdout.log", "stderr": prefix + ".stderr.log"})]:
        if set(record[group]) != set(expected):
            raise ValueError(f"Execution receipt {group} membership mismatch")
        for role, relative in expected.items():
            if record[group][role] != _identity(root, _child(root, relative)):
                raise ValueError(f"Execution receipt {group} hash mismatch: {role}")


def execute_registered_satscan_model(*, paths: Any, secondary_run_id: str, model_id: str,
                                    executable_path: str | Path, timeout_seconds: int = 3600) -> Mapping[str, Any]:
    """Resolve an existing 04-01 registry and explicitly execute one selected model."""
    from .config import load_configuration_bundle, satscan_parameters
    from .satscan_integration import _secondary_table_path
    run = paths.resolve_inside(f"out/runs/{secondary_run_id}")
    registry = pd.read_csv(_secondary_table_path(run, "secondary_run_registry"), keep_default_na=False)
    rows = registry.loc[registry["model_id"].astype(str).eq(model_id)]
    if len(rows) != 1 or registry["model_id"].duplicated().any() or len(registry) != 2:
        raise ExternalResultValidationError("Select exactly one model from the governed two-model registry")
    params = satscan_parameters(load_configuration_bundle(paths.root / "config").analysis)
    return execute_satscan_with_evidence(run_row=rows.iloc[0].to_dict(), run_dir=run,
        executable_path=executable_path, alpha=float(params.alpha), timeout_seconds=timeout_seconds)


def _snapshot_file(root: Path, relative: str) -> dict[str, Any]:
    """Read one stable regular file, retaining source freshness as well as bytes."""
    path = _child(root, relative)
    try:
        before = path.stat()
        if not path.is_file():
            raise ExternalResultValidationError(f"Missing execution-evidence file: {relative}")
        digest = sha256_file(path)
        after = path.stat()
    except OSError as exc:
        raise ExternalResultValidationError(f"Execution-evidence snapshot changed: {relative}") from exc
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise ExternalResultValidationError(f"Execution-evidence snapshot changed: {relative}")
    return {"sha256": digest, "bytes": after.st_size, "mtime_ns": after.st_mtime_ns}


def _snapshot_tree(root: Path) -> dict[str, dict[str, Any]]:
    """Inventory all file members before validation; never follow linked entries."""
    if root.is_symlink() or not root.is_dir():
        raise ExternalResultValidationError("Execution-evidence snapshot needs an unlinked directory")
    try:
        result = {}
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise ExternalResultValidationError("Evidence bundle refuses symlinks")
            if path.is_file():
                relative = path.relative_to(root).as_posix()
                result[relative] = _snapshot_file(root, relative)
            elif not path.is_dir():
                raise ExternalResultValidationError("Evidence bundle refuses non-regular entries")
        return result
    except OSError as exc:
        raise ExternalResultValidationError("Execution-evidence directory changed during snapshot") from exc


def _snapshot_authorities(root: Path) -> dict[str, dict[str, Any]]:
    """Pin the selected configuration, notebook and package-version authority."""
    result = {f"config/{name}": identity for name, identity in _snapshot_tree(root / "config").items()}
    for relative in ("RP1_Analysis_v1.ipynb", "pyproject.toml"):
        result[relative] = _snapshot_file(root, relative)
    return result


def _verify_export_snapshot(roots: Mapping[str, Path], snapshots: Mapping[str, Any],
                            project_root: Path, authorities: Mapping[str, Any]) -> None:
    if (_snapshot_authorities(project_root) != authorities
            or any(_snapshot_tree(root) != snapshots[kind] for kind, root in roots.items())):
        raise ExternalResultValidationError("Evidence source or selected authority changed after its initial snapshot")


def _content_inventory(snapshot: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    # Copy timestamps are not execution attestations. Only source freshness is
    # pinned; a transferred bundle binds its file content and membership.
    return {name: {"sha256": item["sha256"], "bytes": item["bytes"]} for name, item in snapshot.items()}


def _read_evidence_json(path: Path) -> Mapping[str, Any]:
    return _decode_evidence_json(path.read_text(encoding="utf-8"), label=path.name)


def _decode_evidence_json(text: str, *, label: str) -> Mapping[str, Any]:
    def unique_object(entries: list[tuple[str, Any]]) -> dict[str, Any]:
        result = dict(entries)
        if len(result) != len(entries):
            raise ValueError(f"Repeated JSON key in {label}")
        return result

    record = json.loads(text, object_pairs_hook=unique_object)
    if not isinstance(record, dict):
        raise ValueError(f"Expected a JSON object in {label}")
    return record


def _primary_scan_authorities(secondary: Path) -> tuple[list[dict[str, Any]], Mapping[str, Any]]:
    from .satscan_integration import _secondary_table_path

    registry_path = _secondary_table_path(secondary, "secondary_run_registry")
    registry = pd.read_csv(registry_path, keep_default_na=False)
    rows = registry.to_dict(orient="records")
    if (len(rows) != len(_PRIMARY_MODELS)
            or {row["model_id"] for row in rows} != set(_PRIMARY_MODELS)):
        raise ValueError("Execution evidence requires the two governed primary scan registry identities")
    status = _read_evidence_json(registry_path.parent.parent / "secondary_external_execution_status.json")
    state = status["external_execution_state"]
    if (state not in {"RESULTS_VALIDATED", "EXTERNAL_RESULTS_REQUIRED"}
            or type(status["validated_model_count"]) is not int
            or status["validated_model_count"] != (len(rows) if state == "RESULTS_VALIDATED" else 0)):
        raise ValueError("Invalid secondary scan completion state or validated model count")
    paths = set()
    for row in rows:
        if (row["scenario_id"] != row["model_id"]
                or (row["product"], row["model"]) != _PRIMARY_MODELS[row["model_id"]]
                or row["execution_state"] != state):
            raise ValueError("Primary scan registry identity or completion state is inconsistent")
        prefix = str(row["results_prefix"])
        receipt_path = _child(secondary, prefix + ".execution.json")
        if receipt_path in paths or receipt_path.is_relative_to(secondary / "support_sensitivity"):
            raise ValueError("Primary scan result prefixes must be distinct and outside the restricted scan")
        paths.add(receipt_path)
    return rows, status


def _verified_notebook(
    closeout: Path, contract: Any, *, run_id: str, configuration_sha256: str,
    secondary_status: Mapping[str, Any], canonical_source: Path | None,
) -> dict[str, str] | None:
    from .execution_contract import validate_completed_closeout
    from .publication_sources import PublicationSourceError, _notebook_payload_digest, _notebook_source_digest

    section = closeout / contract.closeout_section
    record = _read_evidence_json(section / contract.artifact_roles["execution_record"])
    state = secondary_status["external_execution_state"]
    mode, _ = validate_completed_closeout(
        closeout, contract, expected_run_id=run_id, expected_configuration_sha256=configuration_sha256,
        expected_operational_configuration_sha256=record["operational_configuration_sha256"],
        expected_package_version=record["package_version"],
        expected_analysis_schema_version=record["analysis_schema_version"],
        expected_data_schema_version=record["data_schema_version"], expected_secondary_state=state,
        expected_secondary_integration_state="INTEGRATED" if state == "RESULTS_VALIDATED" else "NOT_INTEGRATED",
        expected_secondary_validated_model_count=secondary_status["validated_model_count"],
    )
    if record["canonical_notebook"] != _CANONICAL_NOTEBOOK:
        raise ValueError("Execution record names a different canonical notebook")
    if not mode.notebook_snapshot_required:
        if "executed_notebook_sha256" in record:
            raise ValueError("Interactive execution record claims an executed notebook hash")
        return None

    notebook_path = section / contract.artifact_roles["executed_notebook"]
    try:
        nb = nbformat.read(notebook_path, as_version=4)
        nbformat.validate(nb)
        source_sha256 = _notebook_payload_digest(nb)
        canonical_sha256 = _notebook_source_digest(canonical_source) if canonical_source is not None else None
    except (nbformat.reader.NotJSONError, nbformat.ValidationError, PublicationSourceError) as exc:
        raise ValueError(f"Invalid executed or canonical notebook: {exc}") from exc
    code = [cell for cell in nb.cells if cell.cell_type == "code"]
    if (not code or len(code) != record["code_cells"]
            or any(type(cell.execution_count) is not int or cell.execution_count < 1
                   or any(output.output_type == "error" for output in cell.outputs) for cell in code)):
        raise ValueError("Executed notebook lacks controlled complete-cell evidence")
    if canonical_sha256 != source_sha256:
        raise ValueError("Executed notebook source differs from the canonical notebook authority")
    return {"source_sha256": source_sha256, "executed_sha256": sha256_file(notebook_path)}


def _restricted_scan_evidence(
    secondary: Path, *, run_id: str, transferred: bool,
) -> tuple[dict[str, Any] | None, str | None, str | None, dict[str, pd.DataFrame]]:
    from .scan_sensitivity import (
        MIN_SUPPORT_KM2, RESULT_NAMES, RESULTS_PREFIX, SCENARIO_ID,
        scan_sensitivity_summary_path, validate_scan_sensitivity,
    )

    restricted = secondary / "support_sensitivity"
    completed = scan_sensitivity_summary_path(restricted)
    legacy = restricted / "modis_gt50_summary.json"
    receipt = restricted / f"{RESULTS_PREFIX}.execution.json"
    if completed.exists() and legacy.exists():
        raise ValueError("Conflicting restricted scan completion summaries")
    summary_path = completed if completed.exists() else legacy
    if not summary_path.is_file():
        if receipt.exists():
            raise ValueError("Restricted scan receipt lacks a completed sensitivity comparison")
        return None, None, "Restricted burned-area Poisson scan result is unavailable", {}

    design = _read_evidence_json(restricted / "modis_gt50_design.json")
    summary = _read_evidence_json(summary_path)
    row = design["run_authority"]
    if (design["scenario_id"] != SCENARIO_ID or summary["scenario_id"] != SCENARIO_ID
            or design["baseline_secondary_run"] != f"{run_id}_sec"
            or row["model_id"] != SCENARIO_ID or row["scenario_id"] != SCENARIO_ID
            or (row["product"], row["model"]) != _PRIMARY_MODELS["MCD64A1_POISSON_PRIMARY"]
            or row["results_prefix"] != RESULTS_PREFIX):
        raise ValueError("Restricted scan scenario or baseline identity is inconsistent")
    tables = {}
    if summary_path == completed:
        if transferred:
            from .publication import restricted_scan_publication_sources
            result = validate_scan_sensitivity(baseline_secondary_dir=secondary, run_dir=restricted,
                                               expected_baseline_run_id=f"{run_id}_sec")
            tables = restricted_scan_publication_sources(
                result.summary, clusters=result.clusters, recurrence=result.recurrence,
                window_comparison=result.window_comparison,
            )
        else:
            validate_scan_sensitivity(baseline_secondary_dir=secondary, run_dir=restricted)
    else:
        sources = design["baseline_sources"]
        if (design["cutoff_km2"] != MIN_SUPPORT_KM2 or design["admission"] != "strictly_greater_than"
                or set(sources) != {"case_path", "coordinate_path", "locations", "population_path", "prm_path",
                                    "registry", "required_cluster_path", "required_membership_path",
                                    "required_report_path", "specification", "status"}):
            raise ValueError("Restricted scan cutoff or baseline source inventory is inconsistent")
        for source in sources.values():
            if _identity(secondary, _child(secondary, source["path"]))["sha256"] != source["sha256"]:
                raise ValueError("Restricted scan baseline source hash mismatch")
        if transferred:
            # This layout predates portable input-derivation evidence and S24.
            # Reconcile the available exports without promoting the run's status.
            from .publication import restricted_scan_publication_sources
            tables = restricted_scan_publication_sources(
                summary, clusters=pd.read_csv(restricted / RESULT_NAMES["clusters"]),
                recurrence=pd.read_csv(restricted / RESULT_NAMES["recurrence"]),
                window_comparison=pd.DataFrame(),
            )
            del tables["restricted_scan_window_comparison"]
    identity = _identity(secondary, receipt) if receipt.exists() else None
    expected = ({"path": receipt.relative_to(restricted).as_posix(), "sha256": identity["sha256"]}
                if identity is not None else None)
    if summary["execution_receipt"] != expected:
        raise ValueError("Restricted scan summary contradicts its receipt")
    if identity is None:
        return None, None, "No observed executable receipt for the restricted burned-area Poisson scan", tables
    observed = validate_satscan_execution_receipt(receipt, run_row=row, run_dir=restricted)
    limitation = ("Restricted scan comparison lacks portable input-derivation evidence"
                  if summary_path == legacy else None)
    return identity, observed["executable"]["path"], limitation, tables


def _verified_scan_receipts(
    secondary: Path, rows: list[dict[str, Any]], status: Mapping[str, Any], *, run_id: str, transferred: bool,
) -> tuple[list[dict[str, Any]], set[str], list[str], dict[str, pd.DataFrame]]:
    from .satscan_integration import RUN_LOCAL_SOURCE_DIR, RUN_LOCAL_SOURCE_MANIFEST, _execution_evidence_status

    receipts = []
    integration_receipts = {}
    executable_paths = set()
    limitations = []
    for row in rows:
        relative = str(row["results_prefix"]) + ".execution.json"
        receipt = _child(secondary, relative)
        if receipt.exists():
            observed = validate_satscan_execution_receipt(receipt, run_row=row, run_dir=secondary)
            identity = _identity(secondary, receipt)
            receipts.append(identity)
            integration_receipts[row["model_id"]] = {
                "execution_receipt_path": relative, "execution_receipt_sha256": identity["sha256"],
                "executable_path": observed["executable"]["path"],
                "executable_version": observed["executable"]["version"],
                "executable_sha256": observed["executable"]["sha256"],
            }
            executable_paths.add(observed["executable"]["path"])
        else:
            limitations.append(f"No observed executable receipt for {row['model_id']}")
    if status["external_execution_state"] == "RESULTS_VALIDATED":
        name = f"{RUN_LOCAL_SOURCE_DIR}/{RUN_LOCAL_SOURCE_MANIFEST}"
        integration = _read_evidence_json(_child(secondary, name))
        expected = _execution_evidence_status(integration_receipts, len(rows))
        if (status["satscan_execution_receipts"] != integration_receipts
                or status["external_execution_evidence"] != expected
                or status["run_local_publication_source_manifest"] != name
                or integration["secondary_run_id"] != f"{run_id}_sec"
                or integration["external_execution_state"] != "RESULTS_VALIDATED"
                or integration["external_execution_evidence"] != expected
                or integration["execution_receipts"] != integration_receipts):
            raise ValueError("Secondary integration records contradict the primary scan receipts or run identity")
    restricted, executable, limitation, tables = _restricted_scan_evidence(
        secondary, run_id=run_id, transferred=transferred,
    )
    if restricted is not None:
        receipts.append(restricted)
        executable_paths.add(executable)
    if limitation is not None:
        limitations.append(limitation)
    expected = {item["path"] for item in receipts}
    actual = {path.relative_to(secondary).as_posix() for path in secondary.rglob("*.execution.json")}
    if expected != actual:
        raise ValueError("Execution receipt inventory includes ungoverned or unverified receipts")
    return receipts, executable_paths, limitations, tables


def _execution_limitations(
    secondary_status: Mapping[str, Any], notebook: Mapping[str, Any] | None, scan_limitations: list[str],
) -> list[str]:
    limitations = []
    if secondary_status["external_execution_state"] != "RESULTS_VALIDATED":
        limitations.append("External result families remain deferred")
    if notebook is None:
        limitations.append("No executed notebook snapshot or wrapper-observed completion is claimed")
    return limitations + scan_limitations


def export_execution_evidence(*, paths: Any, run_id: str, output_dir: str | Path,
                              allow_declared_limitations: bool = False) -> Mapping[str, Any]:
    """Copy a validated run family to a separate no-overwrite evidence bundle.

    Strict mode requires a controlled executed notebook and observed engine
    receipts for the two primary scans and the restricted burned-area scan.
    An export with declared limitations records each missing attestation.
    """
    from .config import load_configuration_bundle
    from .integration import validate_run_authority
    roots = {kind: paths.resolve_inside(f"out/runs/{run_id}_{suffix}")
             for kind, suffix in [("publication", "pub"), ("secondary", "sec"), ("closeout", "close")]}
    # The same complete generation must be validated and copied. Taking a new
    # baseline after validation could bless a concurrent, unvalidated edit.
    authorities = _snapshot_authorities(paths.root)
    source_snapshots = {kind: _snapshot_tree(source) for kind, source in roots.items()}
    validate_run_authority(paths=paths, run_id=run_id)
    _verify_export_snapshot(roots, source_snapshots, paths.root, authorities)
    bundle = load_configuration_bundle(paths.root / "config")
    canonical_source = paths.root / _CANONICAL_NOTEBOOK
    try:
        rows, status = _primary_scan_authorities(roots["secondary"])
        notebook_identity = _verified_notebook(
            roots["closeout"], bundle.execution, run_id=run_id, configuration_sha256=bundle.configuration_sha256,
            secondary_status=status, canonical_source=canonical_source,
        )
        receipts, executables, scan_limitations, _ = _verified_scan_receipts(
            roots["secondary"], rows, status, run_id=run_id, transferred=False,
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ExternalResultValidationError(f"Invalid execution evidence: {exc}") from exc
    limitations = _execution_limitations(status, notebook_identity, scan_limitations)
    executable_paths = {Path(path).resolve() for path in executables}
    if limitations and not allow_declared_limitations:
        raise ExternalResultValidationError("Strict execution-evidence export refused: " + "; ".join(limitations))
    _verify_export_snapshot(roots, source_snapshots, paths.root, authorities)
    target = Path(output_dir).expanduser().resolve()
    if target.exists() or target.is_relative_to(paths.root.resolve()):
        raise ExternalResultValidationError("Use a fresh evidence directory outside the operational analysis tree")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".execution_bundle_", dir=target.parent))
    try:
        inventory = {}
        for kind, source in roots.items():
            _verify_export_snapshot(roots, source_snapshots, paths.root, authorities)
            for relative, expected in source_snapshots[kind].items():
                source_file = _child(source, relative)
                if source_file.resolve() in executable_paths:
                    raise ExternalResultValidationError("Keep executable binaries outside the scientific run family")
                rel = Path(kind) / relative
                destination = staging / rel
                destination.parent.mkdir(parents=True, exist_ok=True)
                if _snapshot_file(source, relative) != expected:
                    raise ExternalResultValidationError("Evidence source changed before copying")
                shutil.copyfile(source_file, destination)
                expected_content = {"sha256": expected["sha256"], "bytes": expected["bytes"]}
                copied = _snapshot_file(staging, rel.as_posix())
                if (_snapshot_file(source, relative) != expected
                        or {key: copied[key] for key in expected_content} != expected_content):
                    raise ExternalResultValidationError("Evidence source or staged copy changed while copying")
                inventory[rel.as_posix()] = expected_content
        if notebook_identity is not None:
            authority_copy = staging / _NOTEBOOK_AUTHORITY
            authority_copy.parent.mkdir()
            shutil.copyfile(canonical_source, authority_copy)
            inventory.update(_content_inventory({_NOTEBOOK_AUTHORITY: authorities[_CANONICAL_NOTEBOOK]}))
        _verify_export_snapshot(roots, source_snapshots, paths.root, authorities)
        if _content_inventory(_snapshot_tree(staging)) != inventory:
            raise ExternalResultValidationError("Staged evidence does not match the validated snapshot")
        result = {"schema": BUNDLE_SCHEMA, "run_id": run_id,
            "status": "QUALIFIED_EXECUTION_EVIDENCE" if not limitations else "DECLARED_LIMITATIONS",
            "created_utc": datetime.now(timezone.utc).isoformat(), "configuration_sha256": bundle.configuration_sha256,
            "notebook_identity": notebook_identity, "observed_execution_receipts": receipts,
            "limitations": limitations, "original_input_data_embedded": False,
            "derived_scan_inputs_embedded": True, "executable_binary_embedded": False,
            "files": inventory}
        # Reservation prevents accidental replacement even on POSIX directory rename.
        target.mkdir(exist_ok=False)
        try:
            for item in staging.iterdir():
                shutil.move(str(item), str(target / item.name))
            _verify_export_snapshot(roots, source_snapshots, paths.root, authorities)
            if _content_inventory(_snapshot_tree(target)) != inventory:
                raise ExternalResultValidationError("Published evidence does not match the validated snapshot")
            _publish_json(target / _MANIFEST, result)
        except BaseException:
            # An incomplete bundle is visible and cannot be mistaken for success.
            (target / "BUNDLE_INCOMPLETE.txt").write_text("Evidence publication interrupted; preserve and use a fresh directory.\n", encoding="utf-8")
            raise
        return {"output_dir": str(target), "manifest_sha256": sha256_file(target / _MANIFEST),
                "status": result["status"], "files": len(inventory), "limitations": limitations}
    finally:
        shutil.rmtree(staging)


def _read_publication_registry(path: Path, fieldnames: tuple[str, ...]) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        if reader.fieldnames != list(fieldnames):
            raise ValueError(f"Invalid publication registry columns: {path.name}")
        entries = {}
        for row in reader:
            key = row[fieldnames[0]]
            if None in row or None in row.values() or not key or key in entries:
                raise ValueError(f"Invalid or duplicate publication registry entry: {path.name}")
            entries[key] = row
    return entries


def _verified_csv_source(root: Path, relative: str, entry: Mapping[str, Any]) -> pd.DataFrame:
    content = _child(root, relative).read_bytes()
    if (entry["path"] != relative or type(entry["size_bytes"]) is not int
            or entry["size_bytes"] != len(content) or entry["sha256"] != sha256(content).hexdigest()):
        raise ValueError(f"Publication source path, hash or size mismatch: {relative}")
    source_text = content.decode("utf-8")
    reader = csv.reader(StringIO(source_text, newline=""), strict=True)
    columns = next(reader, None)
    if not columns or len(columns) != len(set(columns)) or columns != entry["columns"]:
        raise ValueError(f"Publication source column mismatch: {relative}")
    rows = 0
    for row in reader:
        if len(row) != len(columns):
            raise ValueError(f"Malformed publication source record: {relative}")
        rows += 1
    if type(entry["rows"]) is not int or entry["rows"] != rows:
        raise ValueError(f"Publication source row count mismatch: {relative}")
    return pd.read_csv(StringIO(source_text))


def _compare_transferred_frame(actual: pd.DataFrame, expected: pd.DataFrame, *, error: str) -> None:
    # Round-trip the reconstructed values through the null and scalar conventions of a CSV.
    expected = pd.read_csv(StringIO(expected.to_csv(index=False)))
    try:
        pd.testing.assert_frame_equal(
            actual, expected, check_dtype=False, check_exact=False, rtol=1e-14, atol=0,
        )
    except AssertionError as exc:
        raise ValueError(error) from exc


def _verified_transferred_primary_sources(
    secondary: Path, rows: list[dict[str, Any]], status: Mapping[str, Any], analysis_mapping: Mapping[str, Any],
) -> dict[str, pd.DataFrame]:
    from .config import satscan_parameters
    from .contracts import AnalysisContract, freeze
    from .publication_sources import (
        SATSCAN_PUBLICATION_SOURCE_NAMES, PublicationSourceError, build_satscan_publication_sources,
    )
    from .satscan_integration import RUN_LOCAL_SOURCE_DIR, RUN_LOCAL_SOURCE_MANIFEST, _secondary_table_path
    from .satscan_io import ExternalResultsRequired, _governed_coordinates, validate_external_results
    from .secondary_clusters import SecondaryClusterError, load_scan_scenarios
    from .validation import AnalyticalMask

    manifest = _read_evidence_json(_child(secondary, f"{RUN_LOCAL_SOURCE_DIR}/{RUN_LOCAL_SOURCE_MANIFEST}"))
    if (manifest["schema"] != "rp1-satscan-run-local-publication-sources-v2"
            or manifest["source_policy"] != "run_local_only"
            or manifest["satscan_execution_performed_by_notebook"] is not False
            or type(manifest["model_count"]) is not int or manifest["model_count"] != len(rows)):
        raise ValueError("Invalid run-local SaTScan publication-source authority")
    entries = manifest["sources"]
    if not isinstance(entries, dict) or set(entries) != set(SATSCAN_PUBLICATION_SOURCE_NAMES):
        raise ValueError("Run-local SaTScan publication-source inventory is incomplete or unexpected")
    verified = {name: _verified_csv_source(secondary, f"{RUN_LOCAL_SOURCE_DIR}/{name}.csv", entries[name])
                for name in SATSCAN_PUBLICATION_SOURCE_NAMES}

    analysis = AnalysisContract(**freeze(analysis_mapping))
    params = satscan_parameters(analysis)
    if any(row["engine_version_authority"] != params.engine_version_authority for row in rows):
        raise ValueError("Primary scan engine version contradicts the embedded analysis contract")
    if manifest["engine_version_authority"] != params.engine_version_authority:
        raise ValueError("Primary SaTScan publication authority has an inconsistent engine version")
    location_path = _secondary_table_path(secondary, "secondary_location_authority")
    location = pd.read_csv(_child(secondary, location_path.relative_to(secondary).as_posix()),
                           keep_default_na=False, float_precision="round_trip")
    if (location.empty or location["location_id"].duplicated().any() or location["unit_id"].duplicated().any()
            or location["unit_id"].eq("").any()):
        raise ValueError("Invalid embedded SaTScan location authority")
    location_ids = location["location_id"].astype(str)
    coordinates = {row_id: (Decimal(f"{x:.6f}"), Decimal(f"{y:.6f}"))
                   for row_id, x, y in zip(location_ids, location["x"], location["y"], strict=True)}
    recurrence = verified["cluster_recurrence_source"]
    masks = {}
    parsed = {}
    try:
        for row in rows:
            model, product = row["model_id"], row["product"]
            # Transferring a bundle can change filesystem timestamps. Identities above and the
            # native parser below bind the recorded files without relying on extraction times.
            parsed[model] = validate_external_results(
                row, run_dir=secondary, alpha=float(params.alpha), enforce_freshness=False,
            )
            native_coordinates = _governed_coordinates(_child(secondary, row["coordinate_path"]))
            if any(coordinates.get(key) != value for key, value in native_coordinates.items()):
                raise ValueError(f"Location authority contradicts native SaTScan coordinates: {model}")
            recorded = recurrence.loc[recurrence["product"].eq(product), ["unit_id", "exclusion_reasons"]]
            if recorded["unit_id"].duplicated().any() or set(recorded["unit_id"]) != set(location["unit_id"]):
                raise ValueError(f"Primary scan recurrence does not cover the governed district roster: {product}")
            # Native input IDs establish eligibility. The portable bundle retains the recorded
            # reasons for excluded districts, since the original source panels stay separate.
            units = location[["unit_id"]].copy()
            units["eligible"] = location_ids.isin(native_coordinates)
            units["exclusion_reasons"] = units["unit_id"].map(recorded.set_index("unit_id")["exclusion_reasons"])
            masks[product] = AnalyticalMask(product, units)
        expected = build_satscan_publication_sources(
            parsed_by_model=parsed, scenarios=load_scan_scenarios(analysis), location_authority=location,
            data_contract=SimpleNamespace(long_run_mask=masks["mcd64a1"], paired_mask=masks["viirs"]),
            run_registry=pd.DataFrame(rows), run_dir=secondary,
        )
    except (ExternalResultsRequired, PublicationSourceError, SecondaryClusterError) as exc:
        raise ValueError(f"Cannot reconstruct primary SaTScan publication sources: {exc}") from exc
    if "native_reconciliation" in manifest or "native_reconciliation" in status:
        native = {model: result.provenance["native_reconciliation"] for model, result in parsed.items()}
        if manifest.get("native_reconciliation") != native or status.get("native_reconciliation") != native:
            raise ValueError("Recorded native SaTScan reconciliation contradicts the transferred results")
    for name, frame in verified.items():
        _compare_transferred_frame(frame, expected[name],
                                   error=f"Publication source contradicts native SaTScan results: {name}")
    return verified


def _validate_transferred_f6(
    publication: Path, config: Mapping[str, Any], source: pd.DataFrame,
) -> None:
    from .secondary_clusters import SECONDARY_SECTION

    fields = ("figure_id", "rq", "title", "role", "evidence_class", "availability", "figure_data_path",
              "figure_data_sha256", "png_path", "pdf_path", "manifest_path")
    registry = _read_publication_registry(_child(publication, "90_integrated/T_FIGURE_REGISTRY.csv"), fields)
    row = registry["F6"]
    manifest_name = f"{SECONDARY_SECTION}/manifests/F6.manifest.json"
    data_name = f"{SECONDARY_SECTION}/figure_data/FD_F6.csv"
    if row["availability"] != "AVAILABLE" or row["manifest_path"] != manifest_name or row["figure_data_path"] != data_name:
        raise ValueError("F6 figure registry contradicts the governed recurrence projection")
    manifest = _read_evidence_json(_child(publication, manifest_name))
    spec = [item for item in config["contracts"]["figure_contract.yml"]["figures"] if item["id"] == "F6"]
    data = manifest["figure_data"]
    if (len(spec) != 1 or spec[0]["source_attribute"] != "cluster_recurrence_source"
            or manifest["source_attribute"] != "cluster_recurrence_source" or manifest["figure_id"] != "F6"
            or manifest["availability"] != "AVAILABLE" or manifest["configuration_sha256"] != config["configuration_sha256"]
            or row["figure_data_sha256"] != data["sha256"] or data["columns"] != spec[0]["required_columns"]):
        raise ValueError("F6 manifest contradicts the embedded publication contract")
    actual = _verified_csv_source(publication, data_name, data)
    _compare_transferred_frame(actual, source[data["columns"]],
                               error="Transferred figure data contradicts primary scan results: FD_F6")


def _validate_transferred_publication(
    root: Path, *, record: Mapping[str, Any], secondary_rows: list[dict[str, Any]],
    secondary_status: Mapping[str, Any], restricted_sources: Mapping[str, pd.DataFrame],
) -> None:
    from .publication import RESTRICTED_SCAN_RESULTS_REQUIRED, _section
    from .secondary_clusters import EXTERNAL_RESULTS_REQUIRED

    artefact_name = "90_integrated/T_ARTEFACT_REGISTRY.csv"
    table_name = "90_integrated/T_TABLE_REGISTRY.csv"
    meta = ("rq", "title", "role", "family_id", "evidence_class")
    publication = _child(root, "publication")
    artefacts = _read_publication_registry(
        _child(publication, artefact_name), ("path", "sha256", "size_bytes"),
    )
    tables = _read_publication_registry(
        _child(publication, table_name), ("table_id", *meta, "availability", "path", "sha256", "size_bytes"),
    )
    inventory = {relative.removeprefix("publication/"): item for relative, item in record["files"].items()
                 if relative.startswith("publication/")}
    if set(inventory) != set(artefacts) | {artefact_name} or artefact_name in artefacts:
        raise ValueError("Embedded publication artefact registry membership contradicts the bundle")
    for relative, row in artefacts.items():
        entry = inventory[relative]
        if (row["sha256"], row["size_bytes"]) != (entry["sha256"], str(entry["bytes"])):
            raise ValueError(f"Embedded publication artefact registry hash or size mismatch: {relative}")
    config = _read_evidence_json(_child(root, "closeout/00_scaffold/realised_configuration.json"))
    if config["configuration_sha256"] != record["configuration_sha256"]:
        raise ValueError("Embedded publication contract contradicts the configuration identity")
    external_state = secondary_status["external_execution_state"]
    expected_primary = {"T3": "table3_satscan_clusters", "S6": "supplement_s6_satscan"}
    primary_sources = (
        _verified_transferred_primary_sources(
            _child(root, "secondary"), secondary_rows, secondary_status, config["contracts"]["analysis_contract.yml"],
        )
        if external_state == "RESULTS_VALIDATED" else {}
    )
    specs = config["contracts"]["output_contract.yml"]["publication_outputs"]["tables"]
    ids = [spec["id"] for spec in specs]
    if len(set(ids)) != len(ids) or set(ids) != set(tables):
        raise ValueError("Embedded publication table registry membership contradicts the output contract")
    if not expected_primary.keys() <= tables.keys():
        raise ValueError("Transferred publication is missing a primary scan table registry entry")
    expected_restricted = dict(zip(("S21", "S22", "S23", "S24"), (
        "restricted_scan_summary", "restricted_scan_clusters", "restricted_scan_recurrence",
        "restricted_scan_window_comparison",
    )))
    verified_restricted = set()
    for spec in specs:
        table_id = spec["id"]
        row = tables[table_id]
        if any(row[name] != spec[name] for name in meta):
            raise ValueError(f"Embedded publication table registry metadata mismatch: {table_id}")
        source = spec["source_attribute"]
        options = spec["builder_options"]
        restricted = options.get("requires_restricted_scan", False)
        genuine_primary = options.get("genuine_external_results_required") is True
        if table_id in expected_primary and (not genuine_primary or restricted or expected_primary[table_id] != source):
            raise ValueError(f"Embedded publication contract substitutes primary scan source: {table_id}")
        if table_id in expected_restricted and (not restricted or expected_restricted[table_id] != source):
            raise ValueError(f"Embedded publication contract substitutes restricted scan source: {table_id}")
        if restricted and source not in restricted_sources:
            state = RESTRICTED_SCAN_RESULTS_REQUIRED
        elif genuine_primary and external_state == EXTERNAL_RESULTS_REQUIRED:
            state = EXTERNAL_RESULTS_REQUIRED
        else:
            state = "AVAILABLE"
        if row["availability"] != state:
            raise ValueError(f"Embedded publication table availability mismatch: {table_id}")
        if state != "AVAILABLE":
            if (row["path"], row["sha256"], row["size_bytes"]) != ("", "", "0"):
                raise ValueError(f"Deferred publication table claims an artefact: {table_id}")
            continue
        relative = f"{_section(spec['rq'])}/tables/{table_id}.csv"
        artefact = artefacts.get(relative)
        if (artefact is None or
                any(row[field] != artefact[field] for field in ("path", "sha256", "size_bytes"))):
            raise ValueError(f"Embedded publication table registry contradicts the registered artefact: {table_id}")
        path = _child(publication, relative)
        columns = spec["required_columns"]
        with path.open(encoding="utf-8", newline="") as handle:
            if next(csv.reader(handle, strict=True), None) != columns:
                raise ValueError(f"Transferred publication table violates its column contract: {table_id}")
        if restricted:
            _compare_transferred_frame(pd.read_csv(path), restricted_sources[source][columns],
                                       error=f"Transferred publication table contradicts restricted scan results: {table_id}")
            if table_id in expected_restricted:
                verified_restricted.add(source)
        if table_id in expected_primary:
            _compare_transferred_frame(pd.read_csv(path), primary_sources[source][columns],
                                       error=f"Transferred publication table contradicts primary scan results: {table_id}")
    if verified_restricted != set(restricted_sources):
        raise ValueError("Transferred publication is missing a restricted scan table")
    if primary_sources:
        _validate_transferred_f6(publication, config, primary_sources["cluster_recurrence_source"])


def validate_execution_evidence_bundle(
    output_dir: str | Path, *, expected_manifest_sha256: str | None = None,
) -> Mapping[str, Any]:
    """Verify contents and execution claims, with an optional independently pinned manifest."""
    from .config import load_execution_contract
    from .paths import ProjectPaths, _RUN_ID_RE

    root = Path(output_dir).expanduser()
    if root.is_symlink():
        raise ExternalResultValidationError("Execution-evidence bundle contains a symlink")
    root = root.resolve()
    if (root / "BUNDLE_INCOMPLETE.txt").exists():
        raise ExternalResultValidationError("Execution-evidence bundle publication is incomplete")
    try:
        manifest = _child(root, _MANIFEST)
        if not manifest.is_file():
            raise ValueError("Execution-evidence manifest is missing")
        manifest_bytes = manifest.read_bytes()
        if expected_manifest_sha256 is not None and (
                not isinstance(expected_manifest_sha256, str) or not _SHA.fullmatch(expected_manifest_sha256.lower())
                or sha256(manifest_bytes).hexdigest() != expected_manifest_sha256.lower()):
            raise ValueError("Execution-evidence manifest hash mismatch")
        record = _decode_evidence_json(manifest_bytes.decode("utf-8"), label=manifest.name)
        if (record["schema"] != BUNDLE_SCHEMA
                or record["status"] not in {"QUALIFIED_EXECUTION_EVIDENCE", "DECLARED_LIMITATIONS"}):
            raise ValueError("Unknown execution-evidence bundle")
        created = datetime.fromisoformat(record["created_utc"])
        if (not _RUN_ID_RE.fullmatch(record["run_id"]) or not _SHA.fullmatch(record["configuration_sha256"])
                or created.tzinfo is None
                or record["original_input_data_embedded"] is not False
                or record["derived_scan_inputs_embedded"] is not True or record["executable_binary_embedded"] is not False):
            raise ValueError("Invalid execution-evidence run identity or embedding claims")
        if not isinstance(record["files"], dict) or _MANIFEST in record["files"]:
            raise ValueError("Invalid execution-evidence file inventory")
        for relative, entry in record["files"].items():
            actual = _identity(root, _child(root, relative))
            if (not isinstance(entry, dict) or type(entry.get("bytes")) is not int
                    or {"sha256": actual["sha256"], "bytes": actual["bytes"]} != entry):
                raise ValueError(f"Execution-evidence bundle hash mismatch: {relative}")
        members = set()
        for path in root.rglob("*"):
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                raise ValueError("Execution-evidence bundle contains a symlink or other non-regular entry")
            if path.is_file():
                members.add(path.relative_to(root).as_posix())
        if members != set(record["files"]) | {_MANIFEST}:
            raise ValueError("Execution-evidence bundle membership mismatch")
        if any(name.endswith(".execution.json") and not name.startswith("secondary/") for name in members):
            raise ValueError("Execution evidence contains a scan receipt outside the secondary run")
        families = {relative.partition("/")[0] for relative in record["files"]}
        if families - {"authority", "closeout", "publication", "secondary"} or not {
                "closeout", "publication", "secondary"}.issubset(families):
            raise ValueError("Execution-evidence bundle run family inventory mismatch")
        authority_files = {name for name in record["files"] if name.startswith("authority/")}
        if authority_files - {_NOTEBOOK_AUTHORITY}:
            raise ValueError("Execution-evidence bundle contains unexpected notebook authorities")

        secondary = root / "secondary"
        rows, status = _primary_scan_authorities(secondary)
        contract = load_execution_contract(ProjectPaths.discover().root / "config/execution_contract.yml")
        notebook = _verified_notebook(
            root / "closeout", contract, run_id=record["run_id"], configuration_sha256=record["configuration_sha256"],
            secondary_status=status, canonical_source=root / _NOTEBOOK_AUTHORITY if authority_files else None,
        )
        receipts, _, scan_limitations, restricted_sources = _verified_scan_receipts(
            secondary, rows, status, run_id=record["run_id"], transferred=True,
        )
        _validate_transferred_publication(
            root, record=record, secondary_rows=rows, secondary_status=status, restricted_sources=restricted_sources,
        )
        limitations = _execution_limitations(status, notebook, scan_limitations)
        expected_status = "DECLARED_LIMITATIONS" if limitations else "QUALIFIED_EXECUTION_EVIDENCE"
        if record["notebook_identity"] != notebook or bool(authority_files) != (notebook is not None):
            raise ValueError("Execution-evidence manifest notebook identity contradicts the verified snapshot")
        claims = record["observed_execution_receipts"]
        if not isinstance(claims, list) or len(claims) != len(receipts) or sorted(
                claims, key=lambda item: item["path"]) != sorted(receipts, key=lambda item: item["path"]):
            raise ValueError("Execution-evidence manifest receipt inventory contradicts the governed receipts")
        if (not isinstance(record["limitations"], list) or sorted(record["limitations"]) != sorted(limitations)
                or record["status"] != expected_status):
            raise ValueError("Execution-evidence manifest status or declared limitations contradict verified evidence")
    except (OSError, ValueError, KeyError, TypeError, csv.Error) as exc:
        raise ExternalResultValidationError(f"Invalid execution-evidence bundle: {exc}") from exc
    return record
