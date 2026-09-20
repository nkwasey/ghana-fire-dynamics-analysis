"""Package-owned operational entry points for RP1 Analysis.

The functions in this module are intentionally thin.  They coordinate existing
configuration, validation, notebook and SaTScan implementations without owning
study-specific scientific choices.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import math
import os
import platform
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .config import load_configuration_bundle
from .integration import (
    build_secondary_input_run_isolated,
    execute_canonical_notebook,
    validate_governed_inputs,
    validate_run_authority,
)
from .outputs import OutputWriter
from .paths import ProjectPaths
from .reference_qualification import qualify as qualify_reference_methods
from .satscan_integration import (
    inspect_satscan_results,
    validate_and_integrate_satscan_results_if_available,
)
from .satscan_io import find_satscan_executable

DISTRIBUTION_NAME = "rp1-analysis-v1"
PACKAGE_NAME = "rp1_analysis_v1"
CANONICAL_ENVIRONMENT = "rp_ghana_fire"


def json_text(payload: Any) -> str:
    """Return deterministic UTF-8 JSON text suitable for CLI/file output."""

    return (
        json.dumps(
            payload,
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )


def write_json_report(path: str | Path | None, payload: Any) -> Path | None:
    if path is None:
        return None
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json_text(payload), encoding="utf-8", newline="\n")
    return destination


def version_report(paths: ProjectPaths | None = None) -> dict[str, Any]:
    governed = paths or ProjectPaths.discover()
    bundle = load_configuration_bundle(governed.root / "config")
    return {
        "product": str(bundle.analysis.project["name"]),
        "version": __version__,
        "distribution": DISTRIBUTION_NAME,
        "package": PACKAGE_NAME,
        "analysis_schema": bundle.analysis.schema_version,
        "data_schema": bundle.data_schema.data_schema_version,
    }


def _module_origin(name: str) -> str:
    module = importlib.import_module(name)
    origin = getattr(module, "__file__", None)
    return "" if origin is None else str(Path(origin).resolve())


def _distribution_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "NOT_INSTALLED"


def _distribution_install_metadata(name: str) -> dict[str, Any]:
    try:
        distribution = importlib.metadata.distribution(name)
    except importlib.metadata.PackageNotFoundError:
        return {"mode": "not_installed", "direct_url": ""}
    raw = distribution.read_text("direct_url.json")
    if not raw:
        return {"mode": "installed_distribution", "direct_url": ""}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"mode": "invalid_metadata", "direct_url": raw}
    directory = payload.get("dir_info")
    editable = isinstance(directory, dict) and bool(directory.get("editable"))
    return {
        "mode": "editable_source" if editable else "installed_distribution",
        "direct_url": str(payload.get("url", "")),
    }


def doctor_report(paths: ProjectPaths | None = None) -> dict[str, Any]:
    """Inspect the installed operational runtime without running analysis."""

    governed = paths or ProjectPaths.discover()
    checks: list[dict[str, Any]] = []

    def record(check_name: str, status: str, **details: Any) -> None:
        checks.append({"check": check_name, "status": status, **details})

    py_ok = sys.version_info[:2] == (3, 13)
    record(
        "python",
        "PASS" if py_ok else "FAIL",
        version=platform.python_version(),
        executable=str(Path(sys.executable).resolve()),
    )

    conda_name = os.environ.get("CONDA_DEFAULT_ENV")
    virtual_env = os.environ.get("VIRTUAL_ENV")
    if conda_name:
        env_status = "PASS" if conda_name == CANONICAL_ENVIRONMENT else "NON_CANONICAL"
        record("environment", env_status, kind="conda", name=conda_name)
    elif virtual_env:
        record(
            "environment",
            "DETECTED_NON_CONDA",
            kind="virtualenv",
            path=str(Path(virtual_env).resolve()),
            canonical_name=CANONICAL_ENVIRONMENT,
        )
    else:
        record(
            "environment",
            "NOT_DETECTABLE",
            canonical_name=CANONICAL_ENVIRONMENT,
            prefix=str(Path(sys.prefix).resolve()),
        )

    expected_root = governed.root.resolve()
    package_specs = (
        (PACKAGE_NAME, DISTRIBUTION_NAME, expected_root),
        ("mv_firms_panels", "mv-firms-panels", expected_root.parent / "rp1_mv_firms_panels"),
        ("geo_data_prep", "geo_data_prep_stage1", expected_root.parents[1] / "geo_data_prep"),
    )
    for module_name, distribution, expected_project in package_specs:
        try:
            origin = Path(_module_origin(module_name))
            install = _distribution_install_metadata(distribution)
            if install["mode"] == "editable_source":
                origin_ok = origin.is_relative_to(expected_project.resolve())
            elif install["mode"] == "installed_distribution":
                origin_ok = origin.is_relative_to(Path(sys.prefix).resolve())
            else:
                origin_ok = False
            record(
                f"import:{module_name}",
                "PASS" if origin_ok else "FAIL",
                origin=str(origin),
                distribution=distribution,
                distribution_version=_distribution_version(distribution),
                install_mode=install["mode"],
                direct_url=install["direct_url"],
                expected_project=str(expected_project.resolve()),
            )
        except Exception as exc:  # pragma: no cover - defensive runtime reporting
            record(f"import:{module_name}", "FAIL", error=str(exc), distribution=distribution)

    try:
        bundle = load_configuration_bundle(governed.root / "config")
        record(
            "configuration",
            "PASS",
            configuration_sha256=bundle.aggregate_config_sha256,
            files={name: digest for name, digest in sorted(bundle.file_hashes.items())},
        )
    except Exception as exc:
        record("configuration", "FAIL", error=str(exc))

    try:
        inputs = governed.governed_inputs
        missing = [name for name, path in inputs.items() if not path.is_file()]
        record(
            "governed_inputs_visibility",
            "PASS" if not missing else "FAIL",
            visible=len(inputs) - len(missing),
            expected=len(inputs),
            missing=missing,
        )
    except Exception as exc:
        record("governed_inputs_visibility", "FAIL", error=str(exc))

    runtime_modules = (
        "numpy",
        "yaml",
        "pandas",
        "geopandas",
        "pyproj",
        "scipy",
        "statsmodels",
        "matplotlib",
        "nbformat",
        "nbclient",
        "ipykernel",
    )
    dependency_failures: list[str] = []
    for name in runtime_modules:
        try:
            importlib.import_module(name)
        except Exception:
            dependency_failures.append(name)
    record(
        "runtime_dependencies",
        "PASS" if not dependency_failures else "FAIL",
        checked=list(runtime_modules),
        failed=dependency_failures,
    )

    try:
        importlib.import_module("nbclient")
        importlib.import_module("nbformat")
        notebook_exists = (governed.root / "RP1_Analysis_v1.ipynb").is_file()
        record(
            "notebook_runtime",
            "PASS" if notebook_exists else "FAIL",
            notebook=str((governed.root / "RP1_Analysis_v1.ipynb").resolve()),
        )
    except Exception as exc:
        record("notebook_runtime", "FAIL", error=str(exc))

    executable = find_satscan_executable()
    record(
        "satscan",
        "AVAILABLE_EXTERNAL" if executable else "NOT_AVAILABLE_EXTERNAL",
        executable=executable,
        required_for_ordinary_runtime=False,
    )

    hard_failures = [row["check"] for row in checks if row["status"] == "FAIL"]
    return {
        "schema": "rp1-operational-doctor-v1",
        "status": "PASS" if not hard_failures else "FAIL",
        "hard_failures": hard_failures,
        "checks": checks,
    }


def validate_inputs_report(
    *,
    paths: ProjectPaths | None = None,
    json_out: str | Path | None = None,
) -> dict[str, Any]:
    governed = paths or ProjectPaths.discover()
    bundle = load_configuration_bundle(governed.root / "config")
    report = validate_governed_inputs(governed, bundle=bundle, raise_on_failure=False)
    write_json_report(json_out, report)
    return report


def reference_check_report(
    *,
    paths: ProjectPaths | None = None,
    json_out: str | Path | None = None,
) -> dict[str, Any]:
    governed = paths or ProjectPaths.discover()
    report = qualify_reference_methods(governed.root)
    write_json_report(json_out, report)
    return report


def execute_notebook_report(
    *,
    paths: ProjectPaths | None = None,
    run_id: str | None = None,
    kernel: str = "python3",
    timeout: int = 3600,
) -> dict[str, Any]:
    governed = paths or ProjectPaths.discover()
    resolved_run_id = run_id or datetime.now(UTC).strftime("canonical_%Y%m%dT%H%M%S_%fZ")
    result = execute_canonical_notebook(
        paths=governed,
        run_id=resolved_run_id,
        kernel_name=kernel,
        timeout_seconds=timeout,
    )
    return {
        "status": "PASS",
        "run_id": result.run_id,
        "code_cells": result.code_cells,
        "executed_code_cells": result.executed_code_cells,
        "publication_run": result.publication_run_dir.name,
        "secondary_run": result.secondary_run_dir.name,
        "closeout_run": result.closeout_run_dir.name,
        "executed_notebook": result.executed_notebook.name,
        "execution_log": result.execution_log.name,
    }


def validate_run_report(
    *,
    run_id: str,
    paths: ProjectPaths | None = None,
    write_report: bool = False,
) -> dict[str, Any]:
    governed = paths or ProjectPaths.discover()
    result = validate_run_authority(paths=governed, run_id=run_id)

    if write_report:
        bundle = load_configuration_bundle(governed.root / "config")
        writer = OutputWriter(
            governed.resolve_inside(f"out/runs/{run_id}_close"),
            bundle.output,
        )
        writer.write_csv(
            "99_closeout/M_OUTPUT_HASH_INVENTORY.csv",
            result.output_inventory.to_dict(orient="records"),
            columns=list(result.output_inventory.columns),
        )
        writer.write_json(
            "99_closeout/M_RUN_VALIDATION.json",
            {
                "schema_version": bundle.analysis.schema_version,
                "run_id": result.run_id,
                "status": result.status,
                "publication_files": result.publication_files,
                "secondary_files": result.secondary_files,
                "closeout_files_before_validation_report": result.closeout_files,
                "publication_tables": result.publication_tables,
                "publication_figures": result.publication_figures,
                "secondary_external_state": result.secondary_external_state,
                "checks": list(result.checks),
            },
        )

    return {
        "status": result.status,
        "run_id": result.run_id,
        "publication_files": result.publication_files,
        "secondary_files": result.secondary_files,
        "closeout_files": result.closeout_files,
        "publication_tables": result.publication_tables,
        "publication_figures": result.publication_figures,
        "secondary_external_state": result.secondary_external_state,
        "output_inventory_rows": len(result.output_inventory),
    }


def _secondary_run_id(run_id: str | None) -> str:
    return run_id or datetime.now(UTC).strftime("secondary_%Y%m%dT%H%M%S_%fZ")


def satscan_prepare_report(
    *,
    paths: ProjectPaths | None = None,
    run_id: str | None = None,
    timeout: int = 300,
) -> dict[str, Any]:
    governed = paths or ProjectPaths.discover()
    resolved_run_id = _secondary_run_id(run_id)
    result = build_secondary_input_run_isolated(
        paths=governed,
        run_id=resolved_run_id,
        timeout_seconds=timeout,
    )
    def text_field(row: dict[str, Any], name: str) -> str:
        value = row.get(name, "")
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return ""
        return str(value)

    rows: list[dict[str, Any]] = []
    for row in result.secondary_run_registry.to_dict(orient="records"):
        rows.append(
            {
                "model_id": text_field(row, "model_id"),
                "model": text_field(row, "model"),
                "prm_path": text_field(row, "prm_path"),
                "prm_sha256": text_field(row, "prm_sha256"),
                "case_path": text_field(row, "case_path"),
                "case_sha256": text_field(row, "case_sha256"),
                "coordinate_path": text_field(row, "coordinate_path"),
                "coordinate_sha256": text_field(row, "coordinate_sha256"),
                "population_path": text_field(row, "population_path"),
                "population_sha256": text_field(row, "population_sha256"),
                "results_prefix": text_field(row, "results_prefix"),
            }
        )
    return {
        "status": "PASS",
        "external_execution_state": result.execution_state,
        "secondary_run_id": result.run_id,
        "secondary_run_dir": result.run_dir.relative_to(governed.root).as_posix(),
        "models": rows,
        "satscan_execution_performed": False,
    }


def satscan_status_report(
    *,
    secondary_run_id: str,
    paths: ProjectPaths | None = None,
) -> dict[str, Any]:
    governed = paths or ProjectPaths.discover()
    result = inspect_satscan_results(paths=governed, secondary_run_id=secondary_run_id)
    return result.to_dict()


def satscan_integrate_report(
    *,
    secondary_run_id: str,
    paths: ProjectPaths | None = None,
) -> dict[str, Any]:
    governed = paths or ProjectPaths.discover()
    result = validate_and_integrate_satscan_results_if_available(
        paths=governed,
        secondary_run_id=secondary_run_id,
    )
    return {
        "status": "PASS",
        "external_execution_state": result.external_execution_state,
        "secondary_run_id": secondary_run_id,
        "result_families_detected": list(result.result_families_detected),
        "validated_model_count": result.validated_model_count,
        "significant_cluster_counts": dict(result.significant_cluster_counts),
        "membership_counts": dict(result.membership_counts),
        "publication_source_paths": dict(result.publication_source_paths),
        "provenance_summary": dict(result.provenance_summary),
        "satscan_execution_performed": False,
    }
