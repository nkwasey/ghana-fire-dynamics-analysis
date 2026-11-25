"""Optional validation and run-local integration of genuine SaTScan results.

This module owns the 04-02 external-result state machine. It never executes
SaTScan. Python generates deterministic interfaces in 04-01, then this module
classifies the governed result roots as absent, complete-and-valid, or
partial/invalid. Only validated genuine result families may be projected into
run-local publication sources.
"""

from __future__ import annotations

import json
import io
import os
import hashlib
import re
import shutil
import stat
import tempfile
from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

import pandas as pd

from .config import (
    ConfigurationBundle,
    ConfigurationError,
    load_configuration_bundle,
    satscan_parameters,
    validate_secondary_configuration,
)
from .data_io import load_data_authorities
from .paths import ProjectPaths, PathIsolationError
from .publication_sources import build_satscan_publication_sources
from .satscan_io import ExternalResultValidationError, ExternalResultsRequired, ParsedSaTScanResults, sha256_file, validate_external_results
from .secondary_clusters import (
    EXTERNAL_RESULTS_REQUIRED,
    RESULTS_VALIDATED,
    SECONDARY_SECTION,
    build_location_authority,
    load_scan_scenarios,
)
from .validation import validate_data_authorities

RUN_LOCAL_SOURCE_DIR = f"{SECONDARY_SECTION}/publication_sources"
RUN_LOCAL_SOURCE_MANIFEST = "M_SATSCAN_PUBLICATION_SOURCE_MANIFEST.json"
_REQUIRED_RESULT_KEYS = (
    "required_report_path",
    "required_cluster_path",
    "required_membership_path",
)
_PENDING_RESULT_MARKER = f"{EXTERNAL_RESULTS_REQUIRED}.txt"
_TRANSITION_DIRECTORY = ".satscan_integration_transaction"
_COMMIT_DIRECTORY = ".satscan_integration_commit"
_TRANSITION_JOURNAL = "transition.json"
_TRANSITION_SCHEMA = "rp1-satscan-integration-transition-v1"


class OptionalSaTScanIntegrationError(RuntimeError):
    """Raised when optional external-result material is partial or invalid."""


@dataclass(frozen=True, slots=True)
class OptionalSaTScanIntegrationResult:
    external_execution_state: str
    result_families_detected: tuple[str, ...]
    validated_model_count: int
    significant_cluster_counts: Mapping[str, int]
    membership_counts: Mapping[str, int]
    publication_source_paths: Mapping[str, str]
    provenance_summary: Mapping[str, Any]

    @property
    def execution_state(self) -> str:
        return self.external_execution_state

    def as_status_frame(self) -> pd.DataFrame:
        detected = "Yes" if self.result_families_detected else "No"
        rows: list[dict[str, object]] = [
            {"item": "Section", "value": "04-02"},
            {"item": "Result files detected", "value": detected},
            {"item": "External state", "value": self.external_execution_state},
        ]
        if self.external_execution_state == RESULTS_VALIDATED:
            rows.extend(
                [
                    {"item": "Models validated", "value": f"{self.validated_model_count}/2"},
                    {"item": "MCD significant clusters", "value": int(self.significant_cluster_counts.get("mcd64a1", 0))},
                    {"item": "VIIRS significant clusters", "value": int(self.significant_cluster_counts.get("viirs", 0))},
                    {"item": "Next action", "value": "Section 90 generates T3/F6/S6"},
                ]
            )
        else:
            rows.extend(
                [
                    {"item": "SaTScan-dependent outputs", "value": "T3/F6/S6 deferred"},
                    {"item": "Next action", "value": "Continue automatically"},
                ]
            )
        return pd.DataFrame(rows)


@dataclass(frozen=True, slots=True)
class SaTScanInspectionResult:
    """Read-only classification of one governed secondary run."""

    external_execution_state: str
    secondary_run_id: str
    result_families_detected: tuple[str, ...]
    validated_model_count: int
    integration_state: str
    provenance_summary: Mapping[str, Any]
    configuration_binding: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "PASS",
            "external_execution_state": self.external_execution_state,
            "secondary_run_id": self.secondary_run_id,
            "result_families_detected": list(self.result_families_detected),
            "validated_model_count": self.validated_model_count,
            "integration_state": self.integration_state,
            "provenance_summary": dict(self.provenance_summary),
            "configuration_binding": dict(self.configuration_binding),
            "satscan_execution_performed": False,
        }


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    text = frame.to_csv(index=False, lineterminator="\n")
    _atomic_text(path, text)


def _safe_run_child(run_dir: Path, relative: object, *, label: str) -> Path:
    rel = Path(str(relative))
    if rel.is_absolute():
        raise OptionalSaTScanIntegrationError(f"{label} must be run-relative, not absolute")
    candidate = (run_dir / rel).resolve()
    try:
        candidate.relative_to(run_dir.resolve())
    except ValueError as exc:
        raise OptionalSaTScanIntegrationError(f"{label} escapes the governed secondary run") from exc
    return candidate


def _parameter_results_file(prm: Path) -> str:
    found: list[str] = []
    for line in prm.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith(";") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        if key.strip() == "ResultsFile":
            found.append(value.strip())
    if len(found) != 1 or not found[0]:
        raise OptionalSaTScanIntegrationError("SaTScan parameter file must contain exactly one ResultsFile authority")
    return found[0].replace("\\", "/")


def _parameter_value(prm: Path, key_name: str) -> str:
    found: list[str] = []
    for line in prm.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith(";") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        if key.strip() == key_name:
            found.append(value.strip())
    if len(found) != 1:
        raise OptionalSaTScanIntegrationError(
            f"SaTScan parameter file must contain exactly one {key_name} authority"
        )
    return found[0].replace("\\", "/")


def _validate_interface_authorities(run_dir: Path, row: Mapping[str, Any]) -> tuple[Path, str]:
    model_id = str(row["model_id"])
    prm = _safe_run_child(run_dir, row["prm_path"], label="prm_path")
    if not prm.is_file() or sha256_file(prm) != str(row["prm_sha256"]):
        raise OptionalSaTScanIntegrationError(
            f"Parameter-file authority mismatch for {model_id}"
        )

    for path_key, hash_key in (
        ("case_path", "case_sha256"),
        ("coordinate_path", "coordinate_sha256"),
    ):
        path = _safe_run_child(run_dir, row[path_key], label=path_key)
        if not path.is_file() or sha256_file(path) != str(row[hash_key]):
            raise OptionalSaTScanIntegrationError(
                f"Input authority mismatch for {model_id}: {path_key}"
            )

    population_rel = str(row.get("population_path", "") or "")
    population_hash = str(row.get("population_sha256", "") or "")
    prm_population = _parameter_value(prm, "PopulationFile")
    model = str(row["model"])
    if population_rel:
        population = _safe_run_child(run_dir, population_rel, label="population_path")
        if not population.is_file() or sha256_file(population) != population_hash:
            raise OptionalSaTScanIntegrationError(
                f"Population authority mismatch for {model_id}"
            )
        if prm_population != population_rel.replace("\\", "/"):
            raise OptionalSaTScanIntegrationError(
                f"Parameter population authority mismatch for {model_id}"
            )
    elif model == "discrete_poisson":
        raise OptionalSaTScanIntegrationError(
            "Discrete-Poisson run is missing its governed exposure file"
        )
    else:
        if population_hash or prm_population:
            raise OptionalSaTScanIntegrationError(
                "Space-time permutation run must not contain an exposure authority"
            )
        if prm.with_suffix(".pop").exists():
            raise OptionalSaTScanIntegrationError(
                "Space-time permutation run contains an unexpected population file"
            )

    expected_prefix = str(row["results_prefix"]).replace("\\", "/")
    if _parameter_results_file(prm) != expected_prefix:
        raise OptionalSaTScanIntegrationError(
            f"Parameter ResultsFile authority mismatch for {model_id}"
        )
    if str(row.get("required_report_path", "")) != expected_prefix:
        raise OptionalSaTScanIntegrationError(
            f"Result-family registry does not use the exact extensionless ResultsFile for {model_id}"
        )
    if str(row.get("required_cluster_path", "")) != f"{expected_prefix}.col.txt":
        raise OptionalSaTScanIntegrationError(
            f"Result-family cluster path mismatch for {model_id}"
        )
    if str(row.get("required_membership_path", "")) != f"{expected_prefix}.gis.txt":
        raise OptionalSaTScanIntegrationError(
            f"Result-family membership path mismatch for {model_id}"
        )
    if "required_provenance_path" in row and str(row.get("required_provenance_path", "")):
        raise OptionalSaTScanIntegrationError(
            f"External provenance sidecar is not part of the governed result family for {model_id}"
        )
    return prm, expected_prefix


def _result_material_presence(run_dir: Path, row: Mapping[str, Any]) -> tuple[bool, bool, dict[str, Path]]:
    _, expected_prefix = _validate_interface_authorities(run_dir, row)
    paths = {
        "required_report_path": _safe_run_child(run_dir, expected_prefix, label="ResultsFile"),
        "required_cluster_path": _safe_run_child(
            run_dir, f"{expected_prefix}.col.txt", label="cluster result"
        ),
        "required_membership_path": _safe_run_child(
            run_dir, f"{expected_prefix}.gis.txt", label="membership result"
        ),
    }
    results_root = _safe_run_child(run_dir, Path(expected_prefix).parent, label="results_prefix")
    result_files = [
        path
        for path in results_root.iterdir()
        if path.is_file() and path.name != _PENDING_RESULT_MARKER
    ] if results_root.is_dir() else []
    any_material = bool(result_files)
    complete = all(path.is_file() for path in paths.values())
    return any_material, complete, paths


def _secondary_table_path(run_dir: Path, output_id: str) -> Path:
    return run_dir / SECONDARY_SECTION / "tables" / f"{output_id}.csv"


def _read_secondary_status(run_dir: Path, allowed_states: Collection[str]) -> tuple[str, Mapping[str, Any]]:
    status_path = run_dir / SECONDARY_SECTION / "secondary_external_execution_status.json"
    if not status_path.is_file():
        raise OptionalSaTScanIntegrationError("Secondary execution-status record is missing")
    if _has_run_symlink(run_dir, status_path):
        raise OptionalSaTScanIntegrationError("Secondary execution-status record must not be a symbolic link")
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OptionalSaTScanIntegrationError("Secondary execution-status record is malformed") from exc
    if not isinstance(status, Mapping):
        raise OptionalSaTScanIntegrationError("Secondary execution-status record is malformed")
    state = status.get("external_execution_state")
    if not isinstance(state, str) or state not in allowed_states:
        raise OptionalSaTScanIntegrationError(f"Unsupported secondary completion state: {state}")
    return state, status


def _recorded_secondary_state(
    run_dir: Path, bundle: ConfigurationBundle
) -> tuple[str, dict[str, Any]]:
    state, status = _read_secondary_status(run_dir, bundle.execution.allowed_secondary_completion_states)
    snapshot_path = run_dir / "00_scaffold/realised_configuration.json"
    if _has_run_symlink(run_dir, snapshot_path):
        raise OptionalSaTScanIntegrationError("Secondary realised configuration must not be a symbolic link")
    try:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        binding = validate_secondary_configuration(bundle, snapshot, status.get("configuration_sha256"))
    except ConfigurationError as exc:
        raise OptionalSaTScanIntegrationError(str(exc)) from exc
    except (OSError, ValueError) as exc:
        raise OptionalSaTScanIntegrationError("Cannot read secondary realised configuration") from exc
    return state, binding


def _has_run_symlink(run_dir: Path, candidate: Path) -> bool:
    return any(path.is_symlink() for path in (candidate, *candidate.parents)
               if path == run_dir or run_dir in path.parents)


def _pending_result_markers(run_dir: Path, registry: pd.DataFrame) -> tuple[Path, ...]:
    """Preflight only the exact governed markers, without changing them."""
    markers: list[Path] = []
    for row in registry.to_dict(orient="records"):
        relative = Path(str(row["results_prefix"]).replace("\\", "/")).parent / _PENDING_RESULT_MARKER
        unresolved = run_dir / relative
        if _has_run_symlink(run_dir, unresolved):
            raise OptionalSaTScanIntegrationError("Pending SaTScan marker must not be a symbolic link")
        marker = _safe_run_child(run_dir, relative, label="pending result marker")
        if marker.exists() and not marker.is_file():
            raise OptionalSaTScanIntegrationError("Pending SaTScan marker must be a regular file")
        markers.append(marker)
    if len(set(markers)) != len(markers):
        raise OptionalSaTScanIntegrationError("Governed SaTScan marker paths must be distinct")
    return tuple(markers)


def _transition_path(run_dir: Path) -> Path:
    return run_dir / SECONDARY_SECTION / _TRANSITION_DIRECTORY


def _require_no_incomplete_transition(run_dir: Path) -> None:
    path = _transition_path(run_dir)
    if path.exists() or path.is_symlink():
        raise OptionalSaTScanIntegrationError(
            "SaTScan integration recovery required: an incomplete transition exists; "
            "preserve the run and use the explicit recovery procedure"
        )


def _require_terminal_lifecycle(
    run_dir: Path, registry: pd.DataFrame, *, allow_active_transition: bool = False,
) -> None:
    """Shared lifecycle invariant for accepted inspection, reuse and closeout."""
    if not allow_active_transition:
        _require_no_incomplete_transition(run_dir)
    if any(marker.exists() for marker in _pending_result_markers(run_dir, registry)):
        raise OptionalSaTScanIntegrationError(
            "RESULTS_VALIDATED conflicts with pending SaTScan result markers; "
            "read-only inspection will not rewrite historical evidence"
        )


def _atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _remove_transition_directory(run_dir: Path, directory: Path) -> None:
    expected = _transition_path(run_dir)
    if directory.is_symlink() or directory.resolve() != expected.resolve():
        raise OptionalSaTScanIntegrationError("Unsafe SaTScan transition cleanup path")
    if any(p.is_symlink() for p in directory.rglob("*")):
        raise OptionalSaTScanIntegrationError("SaTScan transition contains a symbolic link")
    shutil.rmtree(directory)


def _allowed_transition_target(relative: str) -> bool:
    path = Path(relative)
    fixed = {
        f"{SECONDARY_SECTION}/tables/secondary_run_registry.csv",
        f"{SECONDARY_SECTION}/tables/secondary_output_registry.csv",
        f"{SECONDARY_SECTION}/secondary_external_execution_status.json",
        f"{RUN_LOCAL_SOURCE_DIR}/{RUN_LOCAL_SOURCE_MANIFEST}",
    }
    sources = {"table3_satscan_clusters", "cluster_membership_source", "cluster_recurrence_source", "supplement_s6_satscan"}
    if relative in fixed or relative in {f"{RUN_LOCAL_SOURCE_DIR}/{name}.csv" for name in sources}:
        return True
    parts = path.parts
    return (len(parts) == 5 and parts[0] == SECONDARY_SECTION and parts[1] == "satscan"
            and parts[3] == "results" and parts[4] == _PENDING_RESULT_MARKER)


def _canonical_transition_path(value: Any, *, label: str) -> str:
    if (not isinstance(value, str) or not value or "\\" in value or ":" in value
            or PurePosixPath(value).is_absolute() or ".." in PurePosixPath(value).parts
            or PurePosixPath(value).as_posix() != value):
        raise OptionalSaTScanIntegrationError(f"SaTScan recovery {label} is malformed")
    return value


def _transition_fixed_targets() -> set[str]:
    return {
        f"{SECONDARY_SECTION}/tables/secondary_run_registry.csv",
        f"{SECONDARY_SECTION}/tables/secondary_output_registry.csv",
        f"{SECONDARY_SECTION}/secondary_external_execution_status.json",
        f"{RUN_LOCAL_SOURCE_DIR}/{RUN_LOCAL_SOURCE_MANIFEST}",
        *(f"{RUN_LOCAL_SOURCE_DIR}/{name}.csv" for name in (
            "table3_satscan_clusters", "cluster_membership_source",
            "cluster_recurrence_source", "supplement_s6_satscan")),
    }


def _recovery_registry(content: bytes) -> pd.DataFrame:
    try:
        registry = pd.read_csv(io.BytesIO(content), keep_default_na=False)
        required = {"model_id", "scenario_id", "results_prefix", "execution_state"}
        if not required.issubset(registry.columns) or len(registry) != 2:
            raise ValueError("missing two-model registry fields")
        if (registry["model_id"].astype(str).duplicated().any()
                or registry["model_id"].astype(str).eq("").any()
                or not registry["model_id"].astype(str).equals(registry["scenario_id"].astype(str))):
            raise ValueError("invalid model/scenario identities")
        for prefix in registry["results_prefix"]:
            _canonical_transition_path(prefix, label="registry results prefix")
    except (ValueError, TypeError, UnicodeError, pd.errors.ParserError) as exc:
        raise OptionalSaTScanIntegrationError("SaTScan recovery registry backup is malformed") from exc
    return registry


def _recovery_expected_targets(run_dir: Path, registry: pd.DataFrame) -> set[str]:
    markers = {p.relative_to(run_dir).as_posix() for p in _pending_result_markers(run_dir, registry)}
    if len(markers) != 2 or not all(_allowed_transition_target(p) for p in markers):
        raise OptionalSaTScanIntegrationError("SaTScan recovery marker authority is malformed")
    return _transition_fixed_targets() | markers


def _validate_transition_header(run_dir: Path, directory: Path, journal: Any) -> str:
    if (not isinstance(journal, Mapping)
            or set(journal) != {"schema", "secondary_run_id", "phase", "entries", "created_directories"}
            or journal.get("schema") != _TRANSITION_SCHEMA
            or journal.get("secondary_run_id") != run_dir.name):
        raise OptionalSaTScanIntegrationError("SaTScan recovery journal identity or structure is invalid")
    phase = journal.get("phase")
    if not isinstance(phase, str) or phase not in {"PREPARING", "PREPARED", "COMMITTING", "ROLLBACK_REQUIRED", "READY_TO_COMMIT"}:
        raise OptionalSaTScanIntegrationError("SaTScan recovery journal phase is invalid")
    if not isinstance(journal["entries"], list) or not isinstance(journal["created_directories"], list):
        raise OptionalSaTScanIntegrationError("SaTScan recovery journal entries/directories are malformed")
    created = [_canonical_transition_path(p, label="created directory") for p in journal["created_directories"]]
    if len(created) != len(set(created)):
        raise OptionalSaTScanIntegrationError("SaTScan recovery created directories are duplicated")
    if directory.is_symlink() or _has_run_symlink(run_dir, directory):
        raise OptionalSaTScanIntegrationError("SaTScan recovery transition contains a symbolic link")
    for path in directory.rglob("*"):
        if path.is_symlink():
            raise OptionalSaTScanIntegrationError("SaTScan recovery transition contains a symbolic link")
        if path.is_dir():
            if path.relative_to(directory).as_posix() not in {"backup", "staged"}:
                raise OptionalSaTScanIntegrationError("SaTScan recovery contains an unexpected transition directory")
        elif not path.is_file():
            raise OptionalSaTScanIntegrationError("SaTScan recovery contains nonregular transition evidence")
    committed = run_dir / SECONDARY_SECTION / _COMMIT_DIRECTORY
    if committed.exists() or committed.is_symlink():
        raise OptionalSaTScanIntegrationError("SaTScan recovery conflicts with an already sealed commit")
    return phase


def _recovery_target(run_dir: Path, relative: str) -> Path:
    target = _safe_run_child(run_dir, relative, label="recovery target")
    if _has_run_symlink(run_dir, run_dir / relative) or (target.exists() and not target.is_file()):
        raise OptionalSaTScanIntegrationError("SaTScan recovery target is not a regular file")
    parent = target.parent
    while parent != run_dir:
        if parent.exists() and not parent.is_dir():
            raise OptionalSaTScanIntegrationError("SaTScan recovery target parent is not a directory")
        parent = parent.parent
    return target


def _checked_transition_entries(
    run_dir: Path, directory: Path, journal: Mapping[str, Any],
) -> list[tuple[Path, Mapping[str, Any], bytes | None]]:
    """Validate the complete pre-state before touching any governed authority."""
    phase = _validate_transition_header(run_dir, directory, journal)
    if phase == "PREPARING" or not journal["entries"]:
        raise OptionalSaTScanIntegrationError("SaTScan recovery journal has no complete prepared target set")
    checked: list[tuple[Path, Mapping[str, Any], bytes | None]] = []
    paths: list[str] = []
    expected_files = {_TRANSITION_JOURNAL}
    for index, entry in enumerate(journal["entries"]):
        if not isinstance(entry, Mapping) or type(entry.get("existed")) is not bool:
            raise OptionalSaTScanIntegrationError("SaTScan recovery journal entry/existed flag is malformed")
        fields = {"path", "existed", "before_sha256", "after_sha256"}
        if entry["existed"]:
            fields |= {"backup", "mode", "atime_ns", "mtime_ns"}
        if set(entry) != fields:
            raise OptionalSaTScanIntegrationError("SaTScan recovery journal entry fields are malformed")
        relative = _canonical_transition_path(entry["path"], label="target")
        if relative in paths or not _allowed_transition_target(relative):
            raise OptionalSaTScanIntegrationError("SaTScan recovery target is duplicated or not a governed authority")
        paths.append(relative)
        target = _recovery_target(run_dir, relative)
        marker = relative.endswith("/" + _PENDING_RESULT_MARKER)
        after = entry["after_sha256"]
        if (marker and after is not None) or (not marker and (
                not isinstance(after, str) or re.fullmatch(r"[0-9a-f]{64}", after) is None)):
            raise OptionalSaTScanIntegrationError("SaTScan recovery after hash is malformed")
        if not marker:
            staged_name = f"staged/{index:03d}.txt"
            staged = _safe_run_child(directory, staged_name, label="staged authority")
            if not staged.is_file() or sha256_file(staged) != after:
                raise OptionalSaTScanIntegrationError("SaTScan recovery staged authority is missing or corrupt")
            expected_files.add(staged_name)
        before = entry["before_sha256"]
        content = None
        if entry["existed"]:
            if not isinstance(before, str) or re.fullmatch(r"[0-9a-f]{64}", before) is None:
                raise OptionalSaTScanIntegrationError("SaTScan recovery before hash is malformed")
            backup_name = f"backup/{index:03d}.bin"
            if entry["backup"] != backup_name:
                raise OptionalSaTScanIntegrationError("SaTScan recovery backup path is malformed")
            if (type(entry["mode"]) is not int or not 0 <= entry["mode"] <= 0o7777
                    or any(type(entry[key]) is not int or not -(2 ** 63) <= entry[key] < 2 ** 63
                           for key in ("atime_ns", "mtime_ns"))):
                raise OptionalSaTScanIntegrationError("SaTScan recovery metadata is malformed")
            backup = _safe_run_child(directory, backup_name, label="transition backup")
            if not backup.is_file():
                raise OptionalSaTScanIntegrationError("SaTScan recovery backup is missing or unsafe")
            content = backup.read_bytes()
            if hashlib.sha256(content).hexdigest() != before:
                raise OptionalSaTScanIntegrationError("SaTScan recovery backup hash mismatch")
            expected_files.add(backup_name)
        elif before is not None:
            raise OptionalSaTScanIntegrationError("SaTScan recovery absent target has a before hash")
        if target.exists() and sha256_file(target) not in {before, after}:
            raise OptionalSaTScanIntegrationError("SaTScan recovery target changed outside the transition")
        checked.append((target, entry, content))
    if paths != sorted(paths):
        raise OptionalSaTScanIntegrationError("SaTScan recovery journal target order is malformed")
    by_path = {entry["path"]: (entry, content) for _, entry, content in checked}
    registry_name = f"{SECONDARY_SECTION}/tables/secondary_run_registry.csv"
    status_name = f"{SECONDARY_SECTION}/secondary_external_execution_status.json"
    for relative in (registry_name, status_name):
        if relative not in by_path or by_path[relative][0]["existed"] is not True:
            raise OptionalSaTScanIntegrationError("SaTScan recovery mandatory pre-state authority is missing")
    registry = _recovery_registry(by_path[registry_name][1])
    if set(paths) != _recovery_expected_targets(run_dir, registry):
        raise OptionalSaTScanIntegrationError("SaTScan recovery journal target set is incomplete or unexpected")
    try:
        status = json.loads(by_path[status_name][1])
        if not isinstance(status, Mapping) or status.get("external_execution_state") != EXTERNAL_RESULTS_REQUIRED:
            raise ValueError("invalid pending pre-state")
    except (ValueError, TypeError) as exc:
        raise OptionalSaTScanIntegrationError("SaTScan recovery status backup is malformed") from exc
    allowed_directories = {parent.as_posix() for relative in paths for parent in PurePosixPath(relative).parents
                           if parent.as_posix() != "."}
    existed_parents = {parent.as_posix() for relative, (entry, _) in by_path.items() if entry["existed"]
                       for parent in PurePosixPath(relative).parents if parent.as_posix() != "."}
    if any(p not in allowed_directories or p in existed_parents for p in journal["created_directories"]):
        raise OptionalSaTScanIntegrationError("SaTScan recovery created directory is not a new governed parent")
    actual_files = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}
    # A crash can leave an owned atomic-write temporary beside a journal,
    # staged payload or backup. Unrecognised material is preserved for review.
    extras = actual_files - expected_files
    for relative in extras:
        temporary = PurePosixPath(relative)
        if not any(temporary.parent == PurePosixPath(p).parent
                   and temporary.name.startswith("." + PurePosixPath(p).name + ".")
                   and temporary.name.endswith(".tmp") for p in expected_files):
            raise OptionalSaTScanIntegrationError("SaTScan recovery contains unexpected transition evidence")
    return checked


def _verify_unpublished_preparing_transition(
    run_dir: Path, directory: Path, journal: Mapping[str, Any],
) -> None:
    """Only clear an initial preparation whose observed pre-state is untouched.

    The durable PREPARING journal is intentionally empty: no authoritative write
    starts until a complete PREPARED journal has been persisted. Any completed
    partial backup must therefore still match its corresponding current target.
    """
    if _validate_transition_header(run_dir, directory, journal) != "PREPARING":
        raise OptionalSaTScanIntegrationError("SaTScan recovery is not in preparation")
    if journal["entries"] or journal["created_directories"]:
        raise OptionalSaTScanIntegrationError("SaTScan PREPARING journal is not an initial preparation")
    _read_secondary_status(run_dir, (EXTERNAL_RESULTS_REQUIRED,))
    registry_path = _secondary_table_path(run_dir, "secondary_run_registry")
    if not registry_path.is_file() or _has_run_symlink(run_dir, registry_path):
        raise OptionalSaTScanIntegrationError("SaTScan preparing registry is missing or unsafe")
    registry = _recovery_registry(registry_path.read_bytes())
    if not registry["execution_state"].astype(str).eq(EXTERNAL_RESULTS_REQUIRED).all():
        raise OptionalSaTScanIntegrationError("SaTScan preparation already has changed registry state")
    expected_files = {_TRANSITION_JOURNAL}
    for index, relative in enumerate(sorted(_recovery_expected_targets(run_dir, registry))):
        target = _recovery_target(run_dir, relative)
        backup_name = f"backup/{index:03d}.bin"
        staged_name = f"staged/{index:03d}.txt"
        backup, staged = directory / backup_name, directory / staged_name
        expected_files.add(backup_name)
        if not relative.endswith("/" + _PENDING_RESULT_MARKER):
            expected_files.add(staged_name)
        if backup.exists() and (not backup.is_file() or not target.is_file()
                                or sha256_file(backup) != sha256_file(target)):
            raise OptionalSaTScanIntegrationError("SaTScan preparation no longer matches its pre-state backup")
        if staged.exists() and not backup.exists() and target.exists():
            raise OptionalSaTScanIntegrationError("SaTScan preparation has an unexpectedly published target")
    actual_files = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}
    for relative in actual_files - expected_files:
        temporary = PurePosixPath(relative)
        if not any(temporary.parent == PurePosixPath(p).parent
                   and temporary.name.startswith("." + PurePosixPath(p).name + ".")
                   and temporary.name.endswith(".tmp") for p in expected_files):
            raise OptionalSaTScanIntegrationError("SaTScan preparation contains unexpected transition evidence")


def _rollback_transition(run_dir: Path, directory: Path, journal: Mapping[str, Any]) -> None:
    """Restore only snapshotted governed files; reject unexpected outside edits."""
    checked = _checked_transition_entries(run_dir, directory, journal)
    for target, entry, content in checked:
        if content is None:
            if target.exists():
                target.unlink()
        else:
            _atomic_bytes(target, content)
            os.chmod(target, int(entry["mode"]))
            os.utime(target, ns=(int(entry["atime_ns"]), int(entry["mtime_ns"])))
    for target, entry, content in checked:
        if content is None:
            if target.exists() or target.is_symlink():
                raise OptionalSaTScanIntegrationError("SaTScan recovery did not restore an absent target")
        else:
            if not target.is_file() or target.is_symlink() or sha256_file(target) != entry["before_sha256"]:
                raise OptionalSaTScanIntegrationError("SaTScan recovery did not restore the complete pre-state")
            # Hash verification may advance access time. Restore it again before
            # checking metadata and clearing the active recovery boundary.
            os.utime(target, ns=(entry["atime_ns"], entry["mtime_ns"]))
            metadata = target.stat()
            if (stat.S_IMODE(metadata.st_mode) != entry["mode"]
                    or metadata.st_atime_ns != entry["atime_ns"] or metadata.st_mtime_ns != entry["mtime_ns"]):
                raise OptionalSaTScanIntegrationError("SaTScan recovery did not restore pre-state metadata")
    # Empty directories created by publication are not scientific authorities.
    for relative in sorted(journal.get("created_directories", []), key=lambda x: len(Path(x).parts), reverse=True):
        path = _safe_run_child(run_dir, relative, label="transition-created directory")
        if path.exists() and not any(path.iterdir()):
            path.rmdir()


def recover_satscan_integration_transition(
    *, paths: ProjectPaths | None = None, secondary_run_id: str,
) -> dict[str, Any]:
    """Roll back a stopped, unsealed transition.

    The caller must ensure the original integration process is no longer running.
    Missing/corrupt backup evidence is preserved and fails closed.
    """
    governed = paths or ProjectPaths.discover()
    run_dir = governed.resolve_inside(f"out/runs/{secondary_run_id}")
    directory = _transition_path(run_dir)
    if directory.is_symlink() or not directory.is_dir() or _has_run_symlink(run_dir, directory):
        raise OptionalSaTScanIntegrationError("No recoverable SaTScan integration transition exists")
    if any(p.is_symlink() for p in directory.rglob("*")):
        raise OptionalSaTScanIntegrationError("SaTScan recovery transition contains a symbolic link")
    journal_path = directory / _TRANSITION_JOURNAL
    if not journal_path.is_file():
        raise OptionalSaTScanIntegrationError("SaTScan recovery journal is missing or not a regular file")
    try:
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OptionalSaTScanIntegrationError("SaTScan recovery journal is missing or malformed; preserve this run") from exc
    phase = _validate_transition_header(run_dir, directory, journal)
    if phase == "PREPARING":
        _verify_unpublished_preparing_transition(run_dir, directory, journal)
    else:
        _rollback_transition(run_dir, directory, journal)
    _remove_transition_directory(run_dir, directory)
    return {"status": "ROLLED_BACK", "secondary_run_id": run_dir.name, "previous_phase": phase}


def _publish_validated_transition(
    *, run_dir: Path, bundle: Any, registry: pd.DataFrame,
    sources: Mapping[str, pd.DataFrame], payloads: Mapping[str, str],
    execution_receipts: Mapping[str, Any],
    native_reconciliation: Mapping[str, Any],
) -> None:
    """Stage/snapshot all writes, then commit only a complete coherent transition."""
    markers = _pending_result_markers(run_dir, registry)
    _require_no_incomplete_transition(run_dir)
    directory = _transition_path(run_dir)
    committed = run_dir / SECONDARY_SECTION / _COMMIT_DIRECTORY
    if committed.exists() or committed.is_symlink():
        raise OptionalSaTScanIntegrationError("A sealed SaTScan commit already exists for this run")
    # mkdir is also the per-run exclusive writer boundary.
    try:
        directory.mkdir()
    except OSError as exc:
        raise OptionalSaTScanIntegrationError("Cannot acquire the SaTScan integration transition") from exc
    journal: dict[str, Any] = {"schema": _TRANSITION_SCHEMA, "secondary_run_id": run_dir.name,
                               "phase": "PREPARING", "entries": [], "created_directories": []}
    journal_path = directory / _TRANSITION_JOURNAL
    try:
        _atomic_text(journal_path, json.dumps(journal, indent=2, sort_keys=True) + "\n")
        target_payloads = dict(payloads)
        for marker in markers:
            target_payloads.setdefault(marker.relative_to(run_dir).as_posix(), None)
        created: set[str] = set()
        for index, (relative, text) in enumerate(sorted(target_payloads.items())):
            if not _allowed_transition_target(relative):
                raise OptionalSaTScanIntegrationError("Unexpected SaTScan transition authority")
            target = _safe_run_child(run_dir, relative, label="transition target")
            if _has_run_symlink(run_dir, run_dir / relative) or (target.exists() and not target.is_file()):
                raise OptionalSaTScanIntegrationError("SaTScan transition target must be a regular file")
            entry: dict[str, Any] = {"path": relative, "existed": target.exists(),
                                     "before_sha256": None, "after_sha256": None}
            if target.exists():
                metadata = target.stat();content = target.read_bytes()
                backup = f"backup/{index:03d}.bin"
                _atomic_bytes(directory / backup, content)
                entry.update(backup=backup, before_sha256=hashlib.sha256(content).hexdigest(),
                             atime_ns=metadata.st_atime_ns, mtime_ns=metadata.st_mtime_ns,
                             mode=stat.S_IMODE(metadata.st_mode))
            if text is not None:
                # Flat short names avoid repeating the run hierarchy inside a
                # Windows transition path. The journal binds each payload to
                # its governed destination and content hash.
                _atomic_bytes(directory / "staged" / f"{index:03d}.txt", text.encode("utf-8"))
                entry["after_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
                parent = target.parent
                while parent != run_dir and not parent.exists():
                    created.add(parent.relative_to(run_dir).as_posix());parent = parent.parent
            journal["entries"].append(entry)
        journal["created_directories"] = sorted(created)
        journal["phase"] = "PREPARED"
        _atomic_text(journal_path, json.dumps(journal, indent=2, sort_keys=True) + "\n")
        journal["phase"] = "COMMITTING"
        _atomic_text(journal_path, json.dumps(journal, indent=2, sort_keys=True) + "\n")
        terminal = f"{SECONDARY_SECTION}/secondary_external_execution_status.json"
        for relative, text in sorted(payloads.items()):
            if relative != terminal:
                _atomic_text(run_dir / relative, text)
        _clear_pending_result_markers(run_dir, registry)
        _atomic_text(run_dir / terminal, payloads[terminal])
        _validate_existing_integrated_sources(run_dir=run_dir, bundle=bundle,
            registry=pd.read_csv(_secondary_table_path(run_dir, "secondary_run_registry"), keep_default_na=False),
            sources=sources, allow_active_transition=True, execution_receipts=execution_receipts,
            native_reconciliation=native_reconciliation)
        journal["phase"] = "READY_TO_COMMIT"
        _atomic_text(journal_path, json.dumps(journal, indent=2, sort_keys=True) + "\n")
        # Same-parent atomic rename is the terminal commit. Interrupted transitions
        # retain the active directory and every acceptance route rejects them.
        os.rename(directory, committed)
    except Exception:
        if directory.exists():
            try:
                if journal["phase"] != "PREPARING":
                    _rollback_transition(run_dir, directory, journal)
                _remove_transition_directory(run_dir, directory)
            except Exception as rollback_error:
                journal["phase"] = "ROLLBACK_REQUIRED"
                try:
                    _atomic_text(journal_path, json.dumps(journal, indent=2, sort_keys=True) + "\n")
                except OSError:
                    pass
                raise OptionalSaTScanIntegrationError(
                    "SaTScan integration recovery required: rollback was incomplete; preserve the transition"
                ) from rollback_error
        raise


def _clear_pending_result_markers(run_dir: Path, registry: pd.DataFrame) -> None:
    """Resolve preparation markers only after successful result integration.

    Limit cleanup to the exact governed model roots. Preflight both markers
    before deleting either, and restore removed markers if cleanup fails. This
    helper is deliberately not used by read-only inspection or validated reuse.
    """

    markers = {marker: marker.read_bytes() for marker in _pending_result_markers(run_dir, registry) if marker.exists()}

    removed: list[Path] = []
    try:
        for marker in markers:
            marker.unlink()
            removed.append(marker)
    except OSError as exc:
        for marker in removed:
            _atomic_bytes(marker, markers[marker])
        raise OptionalSaTScanIntegrationError("Could not resolve pending SaTScan result markers") from exc


def _write_validated_secondary_state(
    *,
    run_dir: Path,
    bundle: Any,
    registry: pd.DataFrame,
    parsed_by_model: Mapping[str, ParsedSaTScanResults],
    sources: Mapping[str, pd.DataFrame],
) -> dict[str, str]:
    section = run_dir / SECONDARY_SECTION
    source_root = run_dir / RUN_LOCAL_SOURCE_DIR
    payloads: dict[str, str] = {}

    def collect_text(path: Path, text: str) -> None:
        payloads[path.relative_to(run_dir).as_posix()] = text

    def collect_csv(path: Path, frame: pd.DataFrame) -> None:
        collect_text(path, frame.to_csv(index=False, lineterminator="\n"))

    source_entries: dict[str, dict[str, object]] = {}
    source_paths: dict[str, str] = {}
    for name, frame in sorted(sources.items()):
        path = source_root / f"{name}.csv"
        text = frame.to_csv(index=False, lineterminator="\n")
        collect_text(path, text)
        rel = path.relative_to(run_dir).as_posix()
        source_paths[name] = rel
        source_entries[name] = {
            "path": rel,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "size_bytes": len(text.encode("utf-8")),
            "rows": int(len(frame)),
            "columns": [str(c) for c in frame.columns],
        }

    params = satscan_parameters(bundle.analysis)
    updated = registry.copy()
    updated["execution_state"] = RESULTS_VALIDATED
    updated["parameter_linkage_validated"] = True
    updated["live_execution_deferred"] = False
    for idx, row in updated.iterrows():
        parsed = parsed_by_model[str(row["model_id"])]
        provenance = parsed.provenance
        updated.at[idx, "satscan_executable_path"] = str(provenance.get("executable_path", ""))
        updated.at[idx, "satscan_executable_version"] = str(provenance.get("executable_version", ""))
        updated.at[idx, "satscan_executable_sha256"] = str(provenance.get("executable_sha256", ""))
    collect_csv(_secondary_table_path(run_dir, "secondary_run_registry"), updated)

    output_rows: list[dict[str, object]] = []
    for item in bundle.output.secondary_outputs:
        output_rows.append(
            {
                "output_id": item.output_id,
                "source_attribute": item.source_attribute,
                "output_type": item.output_type,
                "requires_results_validated": bool(item.requires_results_validated),
                "availability": "AVAILABLE",
            }
        )
    output_registry = pd.DataFrame(output_rows).sort_values("output_id", kind="mergesort").reset_index(drop=True)
    collect_csv(_secondary_table_path(run_dir, "secondary_output_registry"), output_registry)

    status_path = section / "secondary_external_execution_status.json"
    if not status_path.is_file():
        raise OptionalSaTScanIntegrationError("Secondary execution-status record is missing")
    status = json.loads(status_path.read_text(encoding="utf-8"))
    execution_receipts = _observed_execution_receipts(parsed_by_model)
    execution_evidence = _execution_evidence_status(execution_receipts, len(parsed_by_model))
    native_reconciliation = _native_reconciliation_by_model(parsed_by_model)
    executable_paths = {str(item["executable_path"]) for item in execution_receipts.values()}
    status.update(
        {
            "external_execution_state": RESULTS_VALIDATED,
            "live_satscan_execution": "VALIDATED_EXTERNAL_RESULTS_INGESTED",
            "validated_model_count": int(len(parsed_by_model)),
            "validated_result_source_policy": "run_local_only",
            "external_provenance_sidecar_required": False,
            "result_family_contract": "ResultsFile + .col.txt + .gis.txt",
            "run_local_publication_source_manifest": f"{RUN_LOCAL_SOURCE_DIR}/{RUN_LOCAL_SOURCE_MANIFEST}",
            "external_execution_evidence": execution_evidence,
            "satscan_execution_receipts": execution_receipts,
            "native_reconciliation": native_reconciliation,
            "satscan_executable_detected": execution_evidence == "RECORDED_EXECUTION",
            "satscan_executable_path": next(iter(executable_paths)) if len(executable_paths) == 1 else None,
        }
    )
    collect_text(status_path, json.dumps(status, indent=2, sort_keys=True) + "\n")

    manifest = {
        "schema": "rp1-satscan-run-local-publication-sources-v2",
        "external_execution_state": RESULTS_VALIDATED,
        "secondary_run_id": run_dir.name,
        "source_policy": "run_local_only",
        "satscan_execution_performed_by_notebook": False,
        "model_count": int(len(parsed_by_model)),
        "engine_version_authority": str(params.engine_version_authority),
        "external_provenance_sidecar_required": False,
        "result_family_contract": "ResultsFile + .col.txt + .gis.txt",
        "external_execution_evidence": execution_evidence,
        "execution_receipts": execution_receipts,
        "native_reconciliation": native_reconciliation,
        "sources": source_entries,
    }
    collect_text(source_root / RUN_LOCAL_SOURCE_MANIFEST, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    _publish_validated_transition(run_dir=run_dir, bundle=bundle, registry=registry, sources=sources,
                                  payloads=payloads, execution_receipts=execution_receipts,
                                  native_reconciliation=native_reconciliation)
    return source_paths



def _observed_execution_receipts(parsed_by_model: Mapping[str, ParsedSaTScanResults]) -> dict[str, dict[str, str]]:
    """Collect external execution receipts present in the validated result families."""
    result: dict[str, dict[str, str]] = {}
    for model_id, parsed in sorted(parsed_by_model.items()):
        provenance = parsed.provenance
        if provenance.get("execution_receipt_sha256"):
            result[model_id] = {key: str(provenance.get(key, "")) for key in (
                "execution_receipt_path", "execution_receipt_sha256", "executable_path",
                "executable_version", "executable_sha256")}
    return result


def _execution_evidence_status(receipts: Mapping[str, Any], model_count: int) -> str:
    if len(receipts) == model_count:
        return "RECORDED_EXECUTION"
    return "PARTIAL_RECORDED_EXECUTION" if receipts else "RESULT_FILES_ONLY"


def _native_reconciliation_by_model(
    parsed_by_model: Mapping[str, ParsedSaTScanResults],
) -> dict[str, Any]:
    return {
        model_id: parsed.provenance["native_reconciliation"]
        for model_id, parsed in parsed_by_model.items()
    }


def _validate_registry_scenario_identity(
    registry: pd.DataFrame,
    scenarios: tuple[Any, ...] | list[Any],
) -> None:
    """Bind the run registry exactly to the configured scenario identities."""

    expected_ids = {str(item.scenario_id) for item in scenarios}
    observed_models = set(registry["model_id"].astype(str))
    observed_scenarios = set(registry["scenario_id"].astype(str))
    if observed_models != expected_ids:
        raise OptionalSaTScanIntegrationError(
            "Secondary run registry model IDs differ from configured SaTScan scenarios"
        )
    if observed_scenarios != expected_ids:
        raise OptionalSaTScanIntegrationError(
            "Secondary run registry scenario IDs differ from configured SaTScan scenarios"
        )
    mismatched = registry.loc[
        registry["model_id"].astype(str).ne(registry["scenario_id"].astype(str))
    ]
    if not mismatched.empty:
        raise OptionalSaTScanIntegrationError(
            "Secondary run registry model/scenario linkage is inconsistent"
        )


def _validate_existing_integrated_sources(
    *,
    run_dir: Path,
    bundle: Any,
    registry: pd.DataFrame,
    sources: Mapping[str, pd.DataFrame],
    allow_active_transition: bool = False,
    execution_receipts: Mapping[str, Any] | None = None,
    native_reconciliation: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Validate an already-integrated RESULTS_VALIDATED run without writing it.

    Resuming a governed validated secondary run is intentionally read-only.
    Current external result families are revalidated and projected in memory,
    then compared byte-for-byte with the stored run-local publication sources.
    """

    _require_terminal_lifecycle(run_dir, registry, allow_active_transition=allow_active_transition)
    section = run_dir / SECONDARY_SECTION
    status_path = section / "secondary_external_execution_status.json"
    if not status_path.is_file():
        raise OptionalSaTScanIntegrationError("Secondary execution-status record is missing")
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OptionalSaTScanIntegrationError("Secondary execution-status record is malformed") from exc
    if status.get("external_execution_state") != RESULTS_VALIDATED:
        raise OptionalSaTScanIntegrationError(
            "Read-only validated-state reuse requires external_execution_state=RESULTS_VALIDATED"
        )
    if int(status.get("validated_model_count", -1)) != len(registry):
        raise OptionalSaTScanIntegrationError(
            "RESULTS_VALIDATED status validated_model_count is inconsistent with the governed models"
        )
    if set(registry["execution_state"].astype(str)) != {RESULTS_VALIDATED}:
        raise OptionalSaTScanIntegrationError(
            "RESULTS_VALIDATED secondary run registry state is inconsistent"
        )
    if not registry["parameter_linkage_validated"].astype(bool).all():
        raise OptionalSaTScanIntegrationError(
            "RESULTS_VALIDATED secondary run lacks complete parameter-linkage validation"
        )

    output_registry_path = _secondary_table_path(run_dir, "secondary_output_registry")
    if not output_registry_path.is_file():
        raise OptionalSaTScanIntegrationError(
            "RESULTS_VALIDATED secondary output registry is missing"
        )
    output_registry = pd.read_csv(output_registry_path, keep_default_na=False)
    required_rows = output_registry.loc[output_registry["requires_results_validated"].astype(bool)]
    requires_results = any(item.requires_results_validated for item in bundle.output.secondary_outputs)
    if (requires_results and required_rows.empty) or not required_rows["availability"].eq("AVAILABLE").all():
        raise OptionalSaTScanIntegrationError(
            "RESULTS_VALIDATED secondary output registry is not fully available"
        )

    source_root = run_dir / RUN_LOCAL_SOURCE_DIR
    manifest_path = source_root / RUN_LOCAL_SOURCE_MANIFEST
    if not manifest_path.is_file():
        raise OptionalSaTScanIntegrationError(
            "RESULTS_VALIDATED secondary run is missing its run-local publication-source manifest"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OptionalSaTScanIntegrationError(
            "Run-local SaTScan publication-source manifest is malformed"
        ) from exc
    if manifest.get("schema") != "rp1-satscan-run-local-publication-sources-v2":
        raise OptionalSaTScanIntegrationError(
            "Run-local SaTScan publication-source manifest schema is invalid"
        )
    if manifest.get("external_execution_state") != RESULTS_VALIDATED:
        raise OptionalSaTScanIntegrationError(
            "Run-local SaTScan publication-source manifest state is inconsistent"
        )
    if manifest.get("secondary_run_id") != run_dir.name:
        raise OptionalSaTScanIntegrationError(
            "Run-local SaTScan publication-source manifest run identity is inconsistent"
        )
    if int(manifest.get("model_count", -1)) != len(registry):
        raise OptionalSaTScanIntegrationError(
            "Run-local SaTScan publication-source manifest model count is inconsistent"
        )
    if manifest.get("source_policy") != "run_local_only":
        raise OptionalSaTScanIntegrationError(
            "Run-local SaTScan publication-source manifest source policy is invalid"
        )
    if manifest.get("satscan_execution_performed_by_notebook") is not False:
        raise OptionalSaTScanIntegrationError(
            "Validated secondary provenance incorrectly claims notebook SaTScan execution"
        )
    if native_reconciliation is not None and (
        "native_reconciliation" in status or "native_reconciliation" in manifest
    ):
        if (
            status.get("native_reconciliation") != native_reconciliation
            or manifest.get("native_reconciliation") != native_reconciliation
        ):
            raise OptionalSaTScanIntegrationError("Secondary native SaTScan reconciliation evidence is inconsistent")
    if execution_receipts is not None:
        expected_evidence = _execution_evidence_status(execution_receipts, len(registry))
        if manifest.get("execution_receipts", {}) != dict(execution_receipts):
            raise OptionalSaTScanIntegrationError("Run-local SaTScan execution-receipt identity is inconsistent")
        if "external_execution_evidence" in manifest and manifest["external_execution_evidence"] != expected_evidence:
            raise OptionalSaTScanIntegrationError("Run-local SaTScan execution evidence state is inconsistent")
        if "satscan_execution_receipts" in status and status["satscan_execution_receipts"] != dict(execution_receipts):
            raise OptionalSaTScanIntegrationError("Secondary status execution receipts are inconsistent")
        if "external_execution_evidence" in status and status["external_execution_evidence"] != expected_evidence:
            raise OptionalSaTScanIntegrationError("Secondary status execution evidence state is inconsistent")
        if "satscan_executable_detected" in status and status["satscan_executable_detected"] is not (expected_evidence == "RECORDED_EXECUTION"):
            raise OptionalSaTScanIntegrationError("Secondary status executable attestation is inconsistent")
        for row in registry.to_dict(orient="records"):
            receipt = execution_receipts.get(str(row["model_id"]))
            if receipt is not None:
                for suffix in ("path", "version", "sha256"):
                    if str(row.get(f"satscan_executable_{suffix}", "")) != str(receipt[f"executable_{suffix}"]):
                        raise OptionalSaTScanIntegrationError("Secondary registry executable attestation is inconsistent")

    entries = manifest.get("sources")
    if not isinstance(entries, Mapping) or set(entries) != set(sources):
        raise OptionalSaTScanIntegrationError(
            "Run-local SaTScan publication-source set is incomplete or unexpected"
        )

    source_paths: dict[str, str] = {}
    for name, expected_frame in sorted(sources.items()):
        entry = entries[name]
        if not isinstance(entry, Mapping):
            raise OptionalSaTScanIntegrationError(
                f"Run-local SaTScan source manifest entry is malformed: {name}"
            )
        path = _safe_run_child(run_dir, entry.get("path"), label=f"publication source {name}")
        if not path.is_file():
            raise OptionalSaTScanIntegrationError(f"Run-local SaTScan source is missing: {name}")
        observed_hash = sha256_file(path)
        if observed_hash != str(entry.get("sha256", "")):
            raise OptionalSaTScanIntegrationError(
                f"Run-local SaTScan source hash mismatch: {name}"
            )
        if int(entry.get("size_bytes", -1)) != int(path.stat().st_size):
            raise OptionalSaTScanIntegrationError(
                f"Run-local SaTScan source size mismatch: {name}"
            )
        if int(entry.get("rows", -1)) != int(len(expected_frame)):
            raise OptionalSaTScanIntegrationError(
                f"Run-local SaTScan source row count mismatch: {name}"
            )
        if list(entry.get("columns", [])) != [str(c) for c in expected_frame.columns]:
            raise OptionalSaTScanIntegrationError(
                f"Run-local SaTScan source columns mismatch: {name}"
            )
        expected_text = expected_frame.to_csv(index=False, lineterminator="\n")
        if path.read_text(encoding="utf-8") != expected_text:
            raise OptionalSaTScanIntegrationError(
                f"Run-local SaTScan source is inconsistent with the currently validated result family: {name}"
            )
        source_paths[name] = path.relative_to(run_dir).as_posix()

    return source_paths


def inspect_satscan_results(
    *,
    paths: ProjectPaths | None = None,
    secondary_run_id: str,
) -> SaTScanInspectionResult:
    """Validate external-result readiness without modifying the secondary run."""

    governed = paths or ProjectPaths.discover()
    try:
        run_dir = governed.resolve_inside(f"out/runs/{secondary_run_id}")
    except PathIsolationError as exc:
        raise OptionalSaTScanIntegrationError(str(exc)) from exc
    if not run_dir.is_dir():
        raise OptionalSaTScanIntegrationError(f"Secondary run does not exist: {secondary_run_id}")
    _require_no_incomplete_transition(run_dir)

    bundle = load_configuration_bundle(governed.root / "config")
    registry_path = _secondary_table_path(run_dir, "secondary_run_registry")
    location_path = _secondary_table_path(run_dir, "secondary_location_authority")
    if not registry_path.is_file() or not location_path.is_file():
        raise OptionalSaTScanIntegrationError("04-01 secondary registry/location authorities are missing")

    registry = pd.read_csv(registry_path, keep_default_na=False)
    if registry["model_id"].astype(str).duplicated().any() or len(registry) != 2:
        raise OptionalSaTScanIntegrationError(
            "Secondary run registry must contain exactly two distinct governed models"
        )
    scenarios = load_scan_scenarios(bundle.analysis)
    _validate_registry_scenario_identity(registry, scenarios)
    recorded_state, configuration_binding = _recorded_secondary_state(run_dir, bundle)

    detected: list[str] = []
    complete: list[str] = []
    rows = registry.to_dict(orient="records")
    for row in rows:
        if row.get("user_defined_random_seed_parameter", "") == "":
            row["user_defined_random_seed_parameter"] = None
        any_material, is_complete, _ = _result_material_presence(run_dir, row)
        model_id = str(row["model_id"])
        if any_material:
            detected.append(model_id)
        if is_complete:
            complete.append(model_id)
        if any_material and not is_complete:
            raise OptionalSaTScanIntegrationError(
                f"Partial SaTScan result family detected for {model_id}"
            )

    if not detected:
        if recorded_state == RESULTS_VALIDATED:
            raise OptionalSaTScanIntegrationError(
                "RESULTS_VALIDATED secondary run is missing its governed external result families"
            )
        return SaTScanInspectionResult(
            external_execution_state=EXTERNAL_RESULTS_REQUIRED,
            secondary_run_id=secondary_run_id,
            result_families_detected=(),
            validated_model_count=0,
            integration_state="NOT_INTEGRATED",
            configuration_binding=configuration_binding,
            provenance_summary={
                "result_material": "absent",
                "external_provenance_sidecar_required": False,
                "result_family_contract": "ResultsFile + .col.txt + .gis.txt",
            },
        )

    if len(detected) != 2 or len(complete) != 2:
        missing = sorted(set(registry["model_id"].astype(str)) - set(complete))
        raise OptionalSaTScanIntegrationError(
            "Partial SaTScan external-result state; both governed result families are required together; "
            f"missing_or_incomplete={missing}"
        )

    params = satscan_parameters(bundle.analysis)
    parsed_by_model: dict[str, ParsedSaTScanResults] = {}
    for row in rows:
        try:
            parsed = validate_external_results(row, run_dir=run_dir, alpha=float(params.alpha))
        except ExternalResultsRequired as exc:
            raise OptionalSaTScanIntegrationError(
                "Partial SaTScan result material cannot be treated as absent"
            ) from exc
        except ExternalResultValidationError as exc:
            raise OptionalSaTScanIntegrationError(str(exc)) from exc
        parsed_by_model[str(row["model_id"])] = parsed

    authorities = load_data_authorities(governed, bundle.data_schema)
    data_contract = validate_data_authorities(authorities, bundle.analysis, bundle.data_schema)
    location_authority = pd.read_csv(location_path)
    expected_location = build_location_authority(
        authorities.district_geometry,
        coordinate_crs=str(params.coordinate_crs),
        anchor_method=str(params.coordinate_anchor_method),
    )
    try:
        pd.testing.assert_frame_equal(location_authority, expected_location, check_dtype=False)
    except AssertionError as exc:
        raise OptionalSaTScanIntegrationError(
            "SaTScan location authority does not match the current governed run"
        ) from exc

    # Hashes only prove the stored source bytes match their manifest; recompute
    # them from the validated raw SaTScan files before admitting an already
    # integrated run. This prevents a self-consistent but incorrect RR column
    # from being passed to a fresh publication run.
    if recorded_state == RESULTS_VALIDATED:
        sources = build_satscan_publication_sources(
            parsed_by_model=parsed_by_model,
            scenarios=scenarios,
            location_authority=location_authority,
            data_contract=data_contract,
            run_registry=registry,
            run_dir=run_dir,
        )
        _validate_existing_integrated_sources(
            run_dir=run_dir, bundle=bundle, registry=registry, sources=sources,
            execution_receipts=_observed_execution_receipts(parsed_by_model),
            native_reconciliation=_native_reconciliation_by_model(parsed_by_model),
        )

    provenance_summary = {
        model_id: {
            "scenario_id": str(parsed.provenance.get("scenario_id", "")),
            "executable_version": str(parsed.provenance.get("executable_version", "")),
            "executable_sha256": str(parsed.provenance.get("executable_sha256", "")),
            "report_sha256": str(parsed.provenance.get("report_sha256", "")),
            "cluster_sha256": str(parsed.provenance.get("cluster_sha256", "")),
            "membership_sha256": str(parsed.provenance.get("membership_sha256", "")),
            "native_reconciliation": parsed.provenance["native_reconciliation"],
        }
        for model_id, parsed in sorted(parsed_by_model.items())
    }
    return SaTScanInspectionResult(
        external_execution_state=RESULTS_VALIDATED,
        secondary_run_id=secondary_run_id,
        result_families_detected=tuple(sorted(detected)),
        validated_model_count=2,
        integration_state=(
            "INTEGRATED" if recorded_state == RESULTS_VALIDATED else "VALIDATED_READY_FOR_INTEGRATION"
        ),
        provenance_summary=provenance_summary,
        configuration_binding=configuration_binding,
    )

def validate_and_integrate_satscan_results_if_available(
    *,
    paths: ProjectPaths | None = None,
    secondary_run_id: str,
) -> OptionalSaTScanIntegrationResult:
    """Apply the exact three-state 04-02 contract without executing SaTScan."""

    governed = paths or ProjectPaths.discover()
    try:
        run_dir = governed.resolve_inside(f"out/runs/{secondary_run_id}")
    except PathIsolationError as exc:
        raise OptionalSaTScanIntegrationError(str(exc)) from exc
    if not run_dir.is_dir():
        raise OptionalSaTScanIntegrationError(f"Secondary run does not exist: {secondary_run_id}")
    _require_no_incomplete_transition(run_dir)

    bundle = load_configuration_bundle(governed.root / "config")
    registry_path = _secondary_table_path(run_dir, "secondary_run_registry")
    location_path = _secondary_table_path(run_dir, "secondary_location_authority")
    if not registry_path.is_file() or not location_path.is_file():
        raise OptionalSaTScanIntegrationError("04-01 secondary registry/location authorities are missing")
    registry = pd.read_csv(registry_path, keep_default_na=False)
    if registry["model_id"].astype(str).duplicated().any() or len(registry) != 2:
        raise OptionalSaTScanIntegrationError("Secondary run registry must contain exactly two distinct governed models")
    scenarios = load_scan_scenarios(bundle.analysis)
    _validate_registry_scenario_identity(registry, scenarios)

    recorded_state, _ = _recorded_secondary_state(run_dir, bundle)

    detected: list[str] = []
    complete: list[str] = []
    rows = registry.to_dict(orient="records")
    for row in rows:
        if row.get("user_defined_random_seed_parameter", "") == "":
            row["user_defined_random_seed_parameter"] = None
    for row in rows:
        any_material, is_complete, _ = _result_material_presence(run_dir, row)
        model_id = str(row["model_id"])
        if any_material:
            detected.append(model_id)
        if is_complete:
            complete.append(model_id)
        if any_material and not is_complete:
            raise OptionalSaTScanIntegrationError(f"Partial SaTScan result family detected for {model_id}")

    if not detected:
        if recorded_state == RESULTS_VALIDATED:
            raise OptionalSaTScanIntegrationError(
                "RESULTS_VALIDATED secondary run is missing its governed external result families"
            )
        return OptionalSaTScanIntegrationResult(
            external_execution_state=EXTERNAL_RESULTS_REQUIRED,
            result_families_detected=(),
            validated_model_count=0,
            significant_cluster_counts={},
            membership_counts={},
            publication_source_paths={},
            provenance_summary={
                "result_material": "absent",
                "notebook_autorun": False,
                "external_provenance_sidecar_required": False,
                "result_family_contract": "ResultsFile + .col.txt + .gis.txt",
            },
        )

    if len(detected) != 2 or len(complete) != 2:
        missing = sorted(set(registry["model_id"].astype(str)) - set(complete))
        raise OptionalSaTScanIntegrationError(
            "Partial SaTScan external-result state; both governed result families are required together; "
            f"missing_or_incomplete={missing}"
        )

    params = satscan_parameters(bundle.analysis)
    parsed_by_model: dict[str, ParsedSaTScanResults] = {}
    for row in rows:
        try:
            parsed = validate_external_results(row, run_dir=run_dir, alpha=float(params.alpha))
        except ExternalResultsRequired as exc:
            raise OptionalSaTScanIntegrationError("Partial SaTScan result material cannot be treated as absent") from exc
        except ExternalResultValidationError as exc:
            raise OptionalSaTScanIntegrationError(str(exc)) from exc
        parsed_by_model[str(row["model_id"])] = parsed

    authorities = load_data_authorities(governed, bundle.data_schema)
    data_contract = validate_data_authorities(authorities, bundle.analysis, bundle.data_schema)
    location_authority = pd.read_csv(location_path)
    expected_location = build_location_authority(
        authorities.district_geometry,
        coordinate_crs=str(params.coordinate_crs),
        anchor_method=str(params.coordinate_anchor_method),
    )
    try:
        pd.testing.assert_frame_equal(location_authority, expected_location, check_dtype=False)
    except AssertionError as exc:
        raise OptionalSaTScanIntegrationError(
            "SaTScan location authority does not match the current governed run"
        ) from exc

    sources = build_satscan_publication_sources(
        parsed_by_model=parsed_by_model,
        scenarios=scenarios,
        location_authority=location_authority,
        data_contract=data_contract,
        run_registry=registry,
        run_dir=run_dir,
    )
    if recorded_state == RESULTS_VALIDATED:
        source_paths = _validate_existing_integrated_sources(
            run_dir=run_dir,
            bundle=bundle,
            registry=registry,
            sources=sources,
            execution_receipts=_observed_execution_receipts(parsed_by_model),
            native_reconciliation=_native_reconciliation_by_model(parsed_by_model),
        )
    else:
        source_paths = _write_validated_secondary_state(
            run_dir=run_dir,
            bundle=bundle,
            registry=registry,
            parsed_by_model=parsed_by_model,
            sources=sources,
        )

    significant_counts: dict[str, int] = {}
    membership_counts: dict[str, int] = {}
    summary = sources["table3_satscan_clusters"]
    membership = sources["cluster_membership_source"]
    for product in ("mcd64a1", "viirs"):
        significant_counts[product] = int(summary.loc[summary["product"].astype(str).eq(product), "cluster_rank"].nunique())
        membership_counts[product] = int(membership.loc[membership["product"].astype(str).eq(product)].shape[0])

    provenance_summary = {
        model_id: {
            "scenario_id": str(parsed.provenance.get("scenario_id", "")),
            "executable_version": str(parsed.provenance.get("executable_version", "")),
            "executable_sha256": str(parsed.provenance.get("executable_sha256", "")),
            "report_sha256": str(parsed.provenance.get("report_sha256", "")),
            "cluster_sha256": str(parsed.provenance.get("cluster_sha256", "")),
            "membership_sha256": str(parsed.provenance.get("membership_sha256", "")),
            "native_reconciliation": parsed.provenance["native_reconciliation"],
        }
        for model_id, parsed in sorted(parsed_by_model.items())
    }
    return OptionalSaTScanIntegrationResult(
        external_execution_state=RESULTS_VALIDATED,
        result_families_detected=tuple(sorted(detected)),
        validated_model_count=2,
        significant_cluster_counts=significant_counts,
        membership_counts=membership_counts,
        publication_source_paths=source_paths,
        provenance_summary=provenance_summary,
    )


__all__ = [
    "RUN_LOCAL_SOURCE_DIR",
    "RUN_LOCAL_SOURCE_MANIFEST",
    "OptionalSaTScanIntegrationError",
    "OptionalSaTScanIntegrationResult",
    "SaTScanInspectionResult",
    "inspect_satscan_results",
    "recover_satscan_integration_transition",
    "validate_and_integrate_satscan_results_if_available",
]
