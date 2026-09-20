"""Optional validation and run-local integration of genuine SaTScan results.

This module owns the 04-02 external-result state machine. It never executes
SaTScan. Python generates deterministic interfaces in 04-01, then this module
classifies the governed result roots as absent, complete-and-valid, or
partial/invalid. Only validated genuine result families may be projected into
run-local publication sources.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from .config import load_configuration_bundle, satscan_parameters
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "PASS",
            "external_execution_state": self.external_execution_state,
            "secondary_run_id": self.secondary_run_id,
            "result_families_detected": list(self.result_families_detected),
            "validated_model_count": self.validated_model_count,
            "integration_state": self.integration_state,
            "provenance_summary": dict(self.provenance_summary),
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
        if path.is_file() and path.name != "EXTERNAL_RESULTS_REQUIRED.txt"
    ] if results_root.is_dir() else []
    any_material = bool(result_files)
    complete = all(path.is_file() for path in paths.values())
    return any_material, complete, paths


def _secondary_table_path(run_dir: Path, output_id: str) -> Path:
    return run_dir / SECONDARY_SECTION / "tables" / f"{output_id}.csv"


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
    source_root.mkdir(parents=True, exist_ok=True)

    source_entries: dict[str, dict[str, object]] = {}
    source_paths: dict[str, str] = {}
    for name, frame in sorted(sources.items()):
        path = source_root / f"{name}.csv"
        _atomic_csv(path, frame)
        rel = path.relative_to(run_dir).as_posix()
        source_paths[name] = rel
        source_entries[name] = {
            "path": rel,
            "sha256": sha256_file(path),
            "size_bytes": int(path.stat().st_size),
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
    _atomic_csv(_secondary_table_path(run_dir, "secondary_run_registry"), updated)

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
    _atomic_csv(_secondary_table_path(run_dir, "secondary_output_registry"), output_registry)

    status_path = section / "secondary_external_execution_status.json"
    if not status_path.is_file():
        raise OptionalSaTScanIntegrationError("Secondary execution-status record is missing")
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status.update(
        {
            "external_execution_state": RESULTS_VALIDATED,
            "live_satscan_execution": "VALIDATED_EXTERNAL_RESULTS_INGESTED",
            "validated_model_count": int(len(parsed_by_model)),
            "validated_result_source_policy": "run_local_only",
            "external_provenance_sidecar_required": False,
            "result_family_contract": "ResultsFile + .col.txt + .gis.txt",
            "run_local_publication_source_manifest": f"{RUN_LOCAL_SOURCE_DIR}/{RUN_LOCAL_SOURCE_MANIFEST}",
        }
    )
    _atomic_text(status_path, json.dumps(status, indent=2, sort_keys=True) + "\n")

    manifest = {
        "schema": "rp1-satscan-run-local-publication-sources-v1",
        "external_execution_state": RESULTS_VALIDATED,
        "secondary_run_id": run_dir.name,
        "source_policy": "run_local_only",
        "satscan_execution_performed_by_notebook": False,
        "model_count": int(len(parsed_by_model)),
        "engine_version_authority": str(params.engine_version_authority),
        "external_provenance_sidecar_required": False,
        "result_family_contract": "ResultsFile + .col.txt + .gis.txt",
        "sources": source_entries,
    }
    _atomic_text(source_root / RUN_LOCAL_SOURCE_MANIFEST, json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return source_paths



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
) -> dict[str, str]:
    """Validate an already-integrated RESULTS_VALIDATED run without writing it.

    Resuming a governed validated secondary run is intentionally read-only.
    Current external result families are revalidated and projected in memory,
    then compared byte-for-byte with the stored run-local publication sources.
    """

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
    if required_rows.empty or set(required_rows["availability"].astype(str)) != {"AVAILABLE"}:
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
    if manifest.get("schema") != "rp1-satscan-run-local-publication-sources-v1":
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
        return SaTScanInspectionResult(
            external_execution_state=EXTERNAL_RESULTS_REQUIRED,
            secondary_run_id=secondary_run_id,
            result_families_detected=(),
            validated_model_count=0,
            integration_state="NOT_INTEGRATED",
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
    validate_data_authorities(authorities, bundle.analysis, bundle.data_schema)
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

    status_path = run_dir / SECONDARY_SECTION / "secondary_external_execution_status.json"
    recorded_state = "UNKNOWN"
    if status_path.is_file():
        try:
            recorded_state = str(
                json.loads(status_path.read_text(encoding="utf-8")).get(
                    "external_execution_state", "UNKNOWN"
                )
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise OptionalSaTScanIntegrationError(
                "Secondary execution-status record is malformed"
            ) from exc

    provenance_summary = {
        model_id: {
            "scenario_id": str(parsed.provenance.get("scenario_id", "")),
            "executable_version": str(parsed.provenance.get("executable_version", "")),
            "executable_sha256": str(parsed.provenance.get("executable_sha256", "")),
            "report_sha256": str(parsed.provenance.get("report_sha256", "")),
            "cluster_sha256": str(parsed.provenance.get("cluster_sha256", "")),
            "membership_sha256": str(parsed.provenance.get("membership_sha256", "")),
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

    status_path = run_dir / SECONDARY_SECTION / "secondary_external_execution_status.json"
    if not status_path.is_file():
        raise OptionalSaTScanIntegrationError("Secondary execution-status record is missing")
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OptionalSaTScanIntegrationError("Secondary execution-status record is malformed") from exc
    recorded_state = str(status.get("external_execution_state", ""))
    if recorded_state not in bundle.execution.allowed_secondary_completion_states:
        raise OptionalSaTScanIntegrationError(
            f"Unsupported secondary completion state: {recorded_state}"
        )

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
    "validate_and_integrate_satscan_results_if_available",
]
