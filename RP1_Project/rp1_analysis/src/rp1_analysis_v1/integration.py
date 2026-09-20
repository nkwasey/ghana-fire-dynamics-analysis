"""Canonical validation and clean notebook-execution services."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import nbformat
import pandas as pd
from nbclient import NotebookClient

from .config import load_configuration_bundle, satscan_parameters
from .contracts import AnalysisContract, OutputContract
from .data_io import load_data_authorities
from .execution_contract import (
    ExecutionContractError,
    canonical_section_gates,
    validate_completed_closeout,
    validate_execution_record,
    validate_required_artifact_presence,
    validate_secondary_completion_state,
)
from .outputs import OutputWriter
from .paths import ProjectPaths
from .provenance import sha256_file, utc_now_iso
from .registers import EVIDENCE_CLASSES, figure_specs, table_specs
from .inference import _rq2_bandwidth
from .gee import mean_model_column_provenance
from .trend_robustness import PRIMARY_TREND_COLUMNS
from .validation import validate_data_authorities


class IntegrationError(RuntimeError):
    """Raised when a canonical integration contract is violated."""


class InputValidationError(IntegrationError):
    """Raised when current inputs fail the governed scientific/data contract."""

    def __init__(self, message: str, report: dict[str, Any]):
        super().__init__(message)
        self.report = report


@dataclass(frozen=True, slots=True)
class NotebookExecutionResult:
    run_id: str
    publication_run_dir: Path
    secondary_run_dir: Path
    closeout_run_dir: Path
    executed_notebook: Path
    execution_log: Path
    code_cells: int
    executed_code_cells: int


@dataclass(frozen=True, slots=True)
class RunValidationResult:
    run_id: str
    status: str
    publication_files: int
    secondary_files: int
    closeout_files: int
    publication_tables: int
    publication_figures: int
    secondary_external_state: str
    output_inventory: pd.DataFrame
    checks: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class InteractiveFinalisationResult:
    """Outcome of package-owned direct-Jupyter closeout finalisation."""

    run_id: str
    closeout_run_dir: Path
    execution_record: Path | None
    status: str
    execution_mode: str
    reused_existing_record: bool
    deferred_to_controlled_wrapper: bool
    summary: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SecondaryInputRunSummary:
    run_id: str
    run_dir: Path
    execution_state: str
    scan_specification_registry: pd.DataFrame
    secondary_run_registry: pd.DataFrame
    input_audit: pd.DataFrame
    output_registry: pd.DataFrame


@dataclass(frozen=True, slots=True)
class PublicationRunSummary:
    run_id: str
    run_dir: Path
    table_registry: pd.DataFrame
    figure_registry: pd.DataFrame
    result_registry: pd.DataFrame
    artefact_registry: pd.DataFrame


@dataclass(frozen=True, slots=True)
class CanonicalIntegrationResult:
    """Realised end-to-end checks for the canonical analysis workflow.

    This object validates package outputs against the governed contracts.  It does
    not calculate scientific statistics and is safe for the notebook to consume
    as a thin orchestration gate.
    """

    status: str
    summary: dict[str, Any]
    checks: tuple[dict[str, Any], ...]

    def as_frame(self) -> pd.DataFrame:
        return pd.DataFrame(list(self.checks))


def validate_canonical_integration(
    *,
    bundle: Any,
    data_contract: Any,
    rq1: Any,
    rq2: Any,
    rq3: Any,
    secondary: Any,
    publication_run: Any,
) -> CanonicalIntegrationResult:
    """Validate realised RQ1/RQ2/RQ3, SaTScan and publication identities.

    All checks consume configuration and package-owned result objects.  No
    statistic is recomputed here.
    """

    checks: list[dict[str, Any]] = []

    def require(name: str, condition: bool, observed: Any) -> None:
        if not bool(condition):
            raise IntegrationError(f"Canonical integration check failed: {name}; observed={observed!r}")
        checks.append({"check": name, "status": "PASS", "observed": observed})

    analysis = bundle.analysis
    populations = analysis.study["populations"]

    # RQ1 realised authority.
    rq1_meta = rq1.rq1_realised_run_metadata
    rq1_cfg = analysis.research_questions["rq1"]
    global_rows = rq1.spatial_statistics_authority.loc[
        rq1.spatial_statistics_authority["record_type"].astype(str).eq("global_moran_national")
    ]
    local_rows = rq1.spatial_statistics_authority.loc[
        rq1.spatial_statistics_authority["record_type"].astype(str).eq("local_moran")
    ]
    require("rq1_acz_count", int(data_contract.acz_count) == int(populations["acz_monthly"]["units"]), int(data_contract.acz_count))
    require("rq1_eligible_districts", int(rq1_meta["population"]["district_units"]) == int(populations["long_run_district"]["units"]), int(rq1_meta["population"]["district_units"]))
    require("rq1_global_moran_singleton", len(global_rows) == 1, len(global_rows))
    require("rq1_local_moran_authority", len(local_rows) == int(populations["long_run_district"]["units"]), len(local_rows))

    # RQ2 realised authority.
    rq2_cfg = analysis.research_questions["rq2"]
    trend = rq2.primary_trend_authority
    annual = rq2.annual_acz_series
    require("rq2_series_count", int(annual["unit_id"].nunique()) == int(rq2_cfg["expected_series_count"]), int(annual["unit_id"].nunique()))
    realised_n = annual.groupby("unit_id", observed=True)["year"].nunique()
    require("rq2_years_per_series", realised_n.eq(int(rq2_cfg["expected_n_per_series"])).all(), sorted(set(int(v) for v in realised_n)))
    expected_bandwidth = _rq2_bandwidth(
        int(rq2_cfg["expected_n_per_series"]),
        str(rq2_cfg["inferential_test"]["bandwidth_rule"]),
    )
    require(
        "rq2_realised_bandwidth",
        trend["realised_bandwidth"].nunique() == 1
        and int(trend["realised_bandwidth"].iloc[0]) == expected_bandwidth,
        int(trend["realised_bandwidth"].iloc[0]),
    )
    require("rq2_permutation_count", trend["permutation_count"].eq(int(rq2_cfg["inferential_test"]["permutations"])).all(), int(trend["permutation_count"].iloc[0]))
    require("rq2_raw_p_and_bh_q", len(trend) == int(rq2_cfg["expected_series_count"]) and trend["raw_p"].notna().all() and trend["bh_q"].notna().all(), len(trend))
    require(
        "rq2_primary_schema",
        tuple(str(c) for c in trend.columns) == PRIMARY_TREND_COLUMNS,
        tuple(str(c) for c in trend.columns),
    )

    # RQ3 realised authority.
    rq3_cfg = analysis.research_questions["rq3"]
    paired_spec = populations[rq3_cfg["descriptive_population"]]
    model_spec = populations[rq3_cfg["model_population"]]
    configured_terms = tuple(str(item["term_name"]) for item in rq3_cfg["predictors"])
    design_terms = tuple(str(x) for x in rq3.gee_design.term_order)
    require("rq3_paired_rows", len(rq3.paired_panel) == int(paired_spec["rows"]), len(rq3.paired_panel))
    require("rq3_model_rows", len(rq3.model_population) == int(model_spec["rows"]), len(rq3.model_population))
    require("rq3_clusters", int(rq3.gee_design.n_clusters) == int(model_spec["units"]), int(rq3.gee_design.n_clusters))
    require("rq3_predictor_identities", tuple(design_terms[1:1+len(configured_terms)]) == configured_terms, tuple(design_terms[1:1+len(configured_terms)]))
    design_authority = mean_model_column_provenance(rq3.gee_design, analysis)
    design_dimensions = pd.to_numeric(
        design_authority["design_dimension"], errors="raise"
    ).astype(int).unique()
    require(
        "rq3_design_dimension",
        len(design_dimensions) == 1 and int(design_dimensions[0]) == len(design_terms),
        {"realised_terms": len(design_terms), "design_authority": design_dimensions.tolist()},
    )
    excluded_roles = tuple(str(x) for x in rq3_cfg["excluded_predictor_roles"])
    configured_field_roles = tuple(str(item["field_role"]) for item in rq3_cfg["predictors"])
    require(
        "rq3_excluded_predictors_absent",
        set(excluded_roles).isdisjoint(configured_field_roles),
        {"excluded_roles": excluded_roles, "configured_predictor_roles": configured_field_roles},
    )
    require("rq3_standard_normal_inference", str(rq3.gee_design.reference_distribution) == str(rq3_cfg["reference_distribution"]), str(rq3.gee_design.reference_distribution))
    std = rq3.standardised_probability_source
    focal_ids = {str(item["predictor_id"]) for item in rq3_cfg["predictors"] if str(item["role"]) == "focal"}
    require("rq3_standardised_probabilities", len(std) == len(focal_ids) * len(rq3_cfg["standardised_probabilities"]["focal_predictor_quantiles"]) and set(std["predictor_id"].astype(str)) == focal_ids, len(std))

    # Publication identity and availability.
    main_tables = [item.output_id for item in bundle.output.tables if item.role == "manuscript"]
    supp_tables = [item.output_id for item in bundle.output.tables if item.role == "supplementary"]
    main_figures = [item.figure_id for item in bundle.figure.figures if item.role == "manuscript"]
    supp_figures = [item.figure_id for item in bundle.figure.figures if item.role == "supplementary"]
    require(
        "publication_contract_populated",
        bool(main_tables and main_figures and supp_tables and supp_figures),
        {
            "main_tables": main_tables,
            "main_figures": main_figures,
            "supplementary_tables": supp_tables,
            "supplementary_figures": supp_figures,
        },
    )
    require("publication_table_registry", set(publication_run.table_registry["table_id"].astype(str)) == set(main_tables + supp_tables), len(publication_run.table_registry))
    require("publication_figure_registry", set(publication_run.figure_registry["figure_id"].astype(str)) == set(main_figures + supp_figures), len(publication_run.figure_registry))

    # External SaTScan boundary must be explicit in both interface and publication state.
    require("satscan_interface_state", str(secondary.execution_state) in {"EXTERNAL_RESULTS_REQUIRED", "RESULTS_VALIDATED"}, str(secondary.execution_state))
    dependent_ids = {
        item.output_id for item in bundle.output.tables
        if bool(item.builder_options.get("genuine_external_results_required", False))
    } | {
        item.figure_id for item in bundle.figure.figures
        if bool(item.data_builder_options.get("genuine_external_results_required", False))
    }
    if str(secondary.execution_state) == "EXTERNAL_RESULTS_REQUIRED":
        table_deferred = set(publication_run.table_registry.loc[publication_run.table_registry["availability"].astype(str).eq("EXTERNAL_RESULTS_REQUIRED"), "table_id"].astype(str))
        figure_deferred = set(publication_run.figure_registry.loc[publication_run.figure_registry["availability"].astype(str).eq("EXTERNAL_RESULTS_REQUIRED"), "figure_id"].astype(str))
        require("satscan_publication_deferral", table_deferred | figure_deferred == dependent_ids, sorted(table_deferred | figure_deferred))

    summary = {
        "rq1_aczs": int(data_contract.acz_count),
        "rq1_eligible_districts": int(rq1_meta["population"]["district_units"]),
        "rq2_series": int(annual["unit_id"].nunique()),
        "rq2_years_per_series": int(realised_n.iloc[0]),
        "rq2_realised_bandwidth": int(trend["realised_bandwidth"].iloc[0]),
        "rq2_permutations": int(trend["permutation_count"].iloc[0]),
        "rq3_paired_rows": int(len(rq3.paired_panel)),
        "rq3_model_rows": int(len(rq3.model_population)),
        "rq3_clusters": int(rq3.gee_design.n_clusters),
        "rq3_design_columns": int(len(design_terms)),
        "rq3_reference_distribution": str(rq3.gee_design.reference_distribution),
        "rq3_standardised_probability_rows": int(len(std)),
        "publication_main_figures": len(main_figures),
        "publication_main_tables": len(main_tables),
        "publication_supplement_tables": len(supp_tables),
        "publication_supplement_figures": len(supp_figures),
        "satscan_external_state": str(secondary.execution_state),
    }
    return CanonicalIntegrationResult(status="PASS", summary=summary, checks=tuple(checks))


def _secondary_output_id(output: OutputContract, source_attribute: str) -> str:
    matches = [
        item.output_id
        for item in output.secondary_outputs
        if item.source_attribute == source_attribute
    ]
    if len(matches) != 1:
        raise IntegrationError(
            f"Expected one configured secondary output for {source_attribute!r}; got {matches!r}"
        )
    return matches[0]


def _secondary_output_path(
    section: Path, output: OutputContract, source_attribute: str
) -> Path:
    spec = next(
        (item for item in output.secondary_outputs if item.source_attribute == source_attribute),
        None,
    )
    if spec is None:
        raise IntegrationError(f"Missing configured secondary output {source_attribute!r}")
    suffix = ".json" if spec.output_type == "manifest" else ".csv"
    base = section if spec.output_type == "manifest" else section / "tables"
    return base / f"{spec.output_id}{suffix}"


def _secondary_scenario(
    analysis: AnalysisContract, *, product: str, role: str
) -> dict[str, Any]:
    matches = [
        dict(item)
        for item in analysis.secondary_analysis["scenarios"]
        if str(item.get("product")) == product and str(item.get("role")) == role
    ]
    if len(matches) != 1:
        raise IntegrationError(
            f"Expected one secondary scenario for product={product!r}, role={role!r}; "
            f"got {len(matches)}"
        )
    return matches[0]


def build_publication_run_isolated(
    *,
    paths: ProjectPaths | None = None,
    run_id: str,
    secondary_run_id: str | None = None,
    timeout_seconds: int = 600,
) -> PublicationRunSummary:
    """Build publication outputs in a clean Python subprocess.

    The child process reloads and validates governed inputs before invoking the
    tested publication builder. This keeps figure/model memory outside the
    orchestration kernel while preserving identical scientific authorities.
    """

    governed = paths or ProjectPaths.discover()
    run_dir = governed.resolve_inside(f"out/runs/{run_id}")
    if run_dir.exists():
        _validate_publication_run(run_dir)
        integrated = run_dir / "90_integrated"
        return PublicationRunSummary(
            run_id=run_id,
            run_dir=run_dir,
            table_registry=_read_csv(integrated / "T_TABLE_REGISTRY.csv", "table registry"),
            figure_registry=_read_csv(integrated / "T_FIGURE_REGISTRY.csv", "figure registry"),
            result_registry=_read_csv(integrated / "T_RESULT_REGISTRY.csv", "result registry"),
            artefact_registry=_read_csv(
                integrated / "T_ARTEFACT_REGISTRY.csv", "artefact registry"
            ),
        )

    secondary_state: str | None = None
    if secondary_run_id is not None:
        bundle = load_configuration_bundle(governed.root / "config")
        secondary_dir = governed.resolve_inside(f"out/runs/{secondary_run_id}")
        if not secondary_dir.is_dir():
            raise IntegrationError(
                f"Publication build requires the governed secondary run: {secondary_run_id}"
            )
        secondary_state, _, _ = _validate_secondary_run(
            secondary_dir, bundle.analysis, bundle.output
        )

    child_code = """
import os
from pathlib import Path
from types import SimpleNamespace
from rp1_analysis_v1.paths import ProjectPaths
from rp1_analysis_v1.publication import build_publication_run

paths = ProjectPaths.discover()
secondary_state = os.environ.get("RP1_ANALYSIS_V1_SECONDARY_STATE", "")
source_dir = os.environ.get("RP1_ANALYSIS_V1_RUN_LOCAL_PUBLICATION_SOURCES", "")
secondary = (
    None
    if not secondary_state
    else SimpleNamespace(execution_state=secondary_state)
)
result = build_publication_run(
    paths=paths,
    run_id=os.environ["RP1_ANALYSIS_V1_PUBLICATION_RUN_ID"],
    secondary_run=secondary,
    run_local_publication_sources=None if not source_dir else Path(source_dir),
)
if not result.run_dir.is_dir():
    raise RuntimeError("Publication builder did not create its run directory")
"""
    env = os.environ.copy()
    env.update(
        {
            "RP1_ANALYSIS_V1_ROOT": str(governed.root),
            "RP1_ANALYSIS_V1_PUBLICATION_RUN_ID": run_id,
            "RP1_ANALYSIS_V1_SECONDARY_STATE": secondary_state or "",
            "RP1_ANALYSIS_V1_RUN_LOCAL_PUBLICATION_SOURCES": (
                str(secondary_dir / "04_secondary_concentration" / "publication_sources")
                if secondary_run_id is not None and secondary_state == "RESULTS_VALIDATED"
                else ""
            ),
            "MPLBACKEND": "Agg",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
        }
    )
    with tempfile.TemporaryDirectory(prefix="rp1_analysis_v1_publication_cwd_") as isolated_cwd:
        try:
            completed = subprocess.run(
                [sys.executable, "-c", child_code],
                cwd=isolated_cwd,
                env=env,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise IntegrationError(f"Publication build exceeded {timeout_seconds} seconds") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown child-process failure").strip()
        raise IntegrationError(f"Publication build failed: {detail}")

    integrated = run_dir / "90_integrated"
    table_registry = _read_csv(integrated / "T_TABLE_REGISTRY.csv", "table registry")
    figure_registry = _read_csv(integrated / "T_FIGURE_REGISTRY.csv", "figure registry")
    result_registry = _read_csv(integrated / "T_RESULT_REGISTRY.csv", "result registry")
    artefact_registry = _read_csv(integrated / "T_ARTEFACT_REGISTRY.csv", "artefact registry")
    return PublicationRunSummary(
        run_id=run_id,
        run_dir=run_dir,
        table_registry=table_registry,
        figure_registry=figure_registry,
        result_registry=result_registry,
        artefact_registry=artefact_registry,
    )


def build_secondary_input_run_isolated(
    *,
    paths: ProjectPaths | None = None,
    run_id: str,
    timeout_seconds: int = 300,
) -> SecondaryInputRunSummary:
    """Prepare secondary SaTScan inputs in a clean Python subprocess.

    Isolating the preparation process prevents plotting/model state accumulated by
    the primary notebook from affecting deterministic external-input generation.
    Scientific inputs are reloaded and revalidated by the child process.
    """

    governed = paths or ProjectPaths.discover()
    run_dir = governed.resolve_inside(f"out/runs/{run_id}")
    if run_dir.exists():
        bundle = load_configuration_bundle(governed.root / "config")
        # A prepared secondary run may legitimately contain a complete,
        # provenance-valid SaTScan result family awaiting the notebook's 04-02
        # integration step.  This builder is a pre-integration resume surface,
        # not a completed-run validator, so permit only that explicit governed
        # transition.  Completed-run/export validation remains strict.
        _validate_secondary_run(
            run_dir,
            bundle.analysis,
            bundle.output,
            allow_validated_ready_for_integration=True,
        )
        section = run_dir / "04_secondary_concentration"
        status = json.loads(
            _secondary_output_path(
                section, bundle.output, "external_execution_status"
            ).read_text(encoding="utf-8")
        )
        state = str(status["external_execution_state"])
        try:
            validate_secondary_completion_state(bundle.execution, state)
        except ExecutionContractError as exc:
            raise IntegrationError(str(exc)) from exc
        return SecondaryInputRunSummary(
            run_id=run_id,
            run_dir=run_dir,
            execution_state=state,
            scan_specification_registry=_read_csv(
                _secondary_output_path(section, bundle.output, "scan_specification_registry"),
                "secondary scenario registry",
            ),
            secondary_run_registry=_read_csv(
                _secondary_output_path(section, bundle.output, "secondary_run_registry"),
                "secondary external-run registry",
            ),
            input_audit=_read_csv(
                _secondary_output_path(section, bundle.output, "input_audit"),
                "secondary input audit",
            ),
            output_registry=_read_csv(
                _secondary_output_path(section, bundle.output, "secondary_output_registry"),
                "secondary output registry",
            ),
        )

    child_code = """
import os
from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.data_io import load_data_authorities
from rp1_analysis_v1.paths import ProjectPaths
from rp1_analysis_v1.execution_contract import validate_secondary_completion_state
from rp1_analysis_v1.secondary_clusters import build_secondary_input_run

paths = ProjectPaths.discover()
bundle = load_configuration_bundle(paths.root / "config")
authorities = load_data_authorities(paths)
result = build_secondary_input_run(
    paths=paths,
    run_id=os.environ["RP1_ANALYSIS_V1_SECONDARY_RUN_ID"],
    bundle=bundle,
    authorities=authorities,
)
validate_secondary_completion_state(bundle.execution, result.execution_state)
"""
    env = os.environ.copy()
    env["RP1_ANALYSIS_V1_ROOT"] = str(governed.root)
    env["RP1_ANALYSIS_V1_SECONDARY_RUN_ID"] = run_id
    env.setdefault("MPLBACKEND", "Agg")
    with tempfile.TemporaryDirectory(prefix="rp1_analysis_v1_secondary_cwd_") as isolated_cwd:
        try:
            completed = subprocess.run(
                [sys.executable, "-c", child_code],
                cwd=isolated_cwd,
                env=env,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise IntegrationError(
                f"Secondary input preparation exceeded {timeout_seconds} seconds"
            ) from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown child-process failure").strip()
        raise IntegrationError(f"Secondary input preparation failed: {detail}")

    bundle = load_configuration_bundle(governed.root / "config")
    section = run_dir / "04_secondary_concentration"
    status_path = _secondary_output_path(section, bundle.output, "external_execution_status")
    if not status_path.is_file():
        raise IntegrationError(
            "Secondary input preparation did not write its execution-status record"
        )
    status = json.loads(status_path.read_text(encoding="utf-8"))
    state = str(status.get("external_execution_state"))
    try:
        validate_secondary_completion_state(bundle.execution, state)
    except ExecutionContractError as exc:
        raise IntegrationError(str(exc)) from exc

    scan_specification_registry = _read_csv(
        _secondary_output_path(section, bundle.output, "scan_specification_registry"),
        "secondary scenario registry",
    )
    input_audit = _read_csv(
        _secondary_output_path(section, bundle.output, "input_audit"), "secondary input audit"
    )
    external_registry = _read_csv(
        _secondary_output_path(section, bundle.output, "secondary_run_registry"),
        "secondary external-run registry",
    )
    output_registry = _read_csv(
        _secondary_output_path(section, bundle.output, "secondary_output_registry"),
        "secondary output registry",
    )
    return SecondaryInputRunSummary(
        run_id=run_id,
        run_dir=run_dir,
        execution_state=state,
        scan_specification_registry=scan_specification_registry,
        secondary_run_registry=external_registry,
        input_audit=input_audit,
        output_registry=output_registry,
    )


def validate_governed_inputs(
    paths: ProjectPaths | None = None,
    *,
    bundle=None,
    raise_on_failure: bool = True,
) -> dict[str, Any]:
    """Validate current inputs scientifically and report canonical byte identity separately.

    ``data/input_sha256.json`` remains the immutable canonical-release byte inventory.
    A hash/size difference is recorded as ``canonical_input_identity=DIFFERENT`` but is
    not, by itself, a runtime scientific failure.  Current inputs are admitted only when
    the complete package-owned scientific/data validators pass.
    """

    governed = paths or ProjectPaths.discover()
    bundle = bundle or load_configuration_bundle(governed.root / "config")
    try:
        inventory = json.loads(governed.input_hash_inventory.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrationError("Unable to read canonical input-hash inventory") from exc
    if not isinstance(inventory, dict):
        raise IntegrationError("Input-hash inventory must contain a mapping")
    if inventory.get("schema_version") != bundle.analysis.schema_version:
        raise IntegrationError("Input-hash inventory schema does not match the analysis schema")
    if inventory.get("provenance_schema_version") != "rp1-input-provenance-v2":
        raise IntegrationError("Input-hash inventory provenance schema is not supported")
    files = inventory.get("files")
    if not isinstance(files, list) or not files:
        raise IntegrationError("Input-hash inventory contains no governed files")

    hash_rows: list[dict[str, Any]] = []
    access_errors: list[str] = []
    seen_staged_paths: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            raise IntegrationError("Malformed input-hash inventory entry")
        origin_path = item.get("origin_path")
        staged_path = item.get("staged_path")
        expected_hash = item.get("sha256")
        expected_size = item.get("size_bytes")
        if (
            not isinstance(origin_path, str)
            or not origin_path
            or PurePosixPath(origin_path).is_absolute()
            or ".." in PurePosixPath(origin_path).parts
        ):
            raise IntegrationError("Malformed input-hash inventory origin_path")
        if (
            not isinstance(staged_path, str)
            or not staged_path
            or PurePosixPath(staged_path).is_absolute()
            or ".." in PurePosixPath(staged_path).parts
        ):
            raise IntegrationError("Malformed input-hash inventory staged_path")
        if staged_path in seen_staged_paths:
            raise IntegrationError(f"Duplicate staged_path in input-hash inventory: {staged_path}")
        seen_staged_paths.add(staged_path)
        if (
            not isinstance(expected_hash, str)
            or len(expected_hash) != 64
            or any(char not in "0123456789abcdefABCDEF" for char in expected_hash)
        ):
            raise IntegrationError("Malformed input-hash inventory SHA-256")
        expected_hash = expected_hash.lower()
        if (
            isinstance(expected_size, bool)
            or not isinstance(expected_size, int)
            or expected_size < 0
        ):
            raise IntegrationError("Malformed input-hash inventory size_bytes")

        # Runtime access is deliberately staged_path-only. origin_path is provenance
        # and may legitimately name a historical source location that is no longer present.
        source = governed.resolve_inside(staged_path)
        actual_hash: str | None = None
        actual_size: int | None = None
        access_status = "PASS"
        access_error = ""
        if not source.is_file():
            access_status = "FAIL"
            access_error = f"Missing governed staged input: {staged_path}"
            access_errors.append(access_error)
        else:
            try:
                actual_hash = sha256_file(source)
                actual_size = int(source.stat().st_size)
            except OSError as exc:
                access_status = "FAIL"
                access_error = f"Unreadable governed staged input: {staged_path}: {exc}"
                access_errors.append(access_error)
        hash_match = actual_hash == expected_hash
        size_match = actual_size == expected_size
        identity_match = bool(hash_match and size_match)
        hash_rows.append(
            {
                "origin_path": origin_path,
                "staged_path": staged_path,
                "expected_sha256": expected_hash,
                "actual_sha256": actual_hash,
                "observed_sha256": actual_hash,
                "expected_size_bytes": expected_size,
                "actual_size_bytes": actual_size,
                "observed_size_bytes": actual_size,
                "hash_match": bool(hash_match),
                "size_match": bool(size_match),
                "identity_match": identity_match,
                "access_status": access_status,
                "access_error": access_error,
            }
        )

    canonical_identity = "MATCH" if all(row["identity_match"] for row in hash_rows) else "DIFFERENT"
    report: dict[str, Any] = {
        "schema_version": bundle.analysis.schema_version,
        "configuration_sha256": bundle.configuration_sha256,
        "status": "PENDING",
        "input_validation_status": "PENDING",
        "canonical_input_identity": canonical_identity,
        "canonical_inventory_schema": {
            "schema_version": str(inventory["schema_version"]),
            "provenance_schema_version": str(inventory["provenance_schema_version"]),
        },
        "governed_file_count": len(hash_rows),
        "current_input_identities": hash_rows,
        # Backwards-compatible name retained for consumers of the v1.2.2 report.
        "hashes": hash_rows,
        "panel_schema_validation": {
            "status": "NOT_RUN",
            "analysis_schema_version": bundle.analysis.schema_version,
            "data_schema_version": bundle.data_schema.data_schema_version,
            "panel_schema_version": bundle.data_schema.panel_schema_version,
        },
        "temporal_support": {},
        "populations": {},
        "population_summary": {},
        "geometry": {},
        "geometry_summary": {},
        "reconciliation": [],
        "reconciliation_summary": {"status": "NOT_RUN"},
        "rq3_mcd64a1_support_by_month": [],
        "validation_error": None,
    }

    def fail(exc: Exception | str) -> dict[str, Any]:
        message = str(exc)
        report["status"] = "FAIL"
        report["input_validation_status"] = "FAIL"
        report["validation_error"] = {
            "type": type(exc).__name__ if isinstance(exc, Exception) else "InputAccessError",
            "message": message,
        }
        report["panel_schema_validation"]["status"] = "FAIL"
        if raise_on_failure:
            raise InputValidationError(
                f"Governed input scientific/data validation failed: {message}", report
            ) from exc if isinstance(exc, Exception) else None
        return report

    if access_errors:
        return fail("; ".join(access_errors))

    try:
        authorities = load_data_authorities(governed, bundle.data_schema)
        summary = validate_data_authorities(authorities, bundle.analysis, bundle.data_schema)
        reconciliation = summary.reconciliation.copy()
        if not bool(reconciliation["passed"].all()):
            raise IntegrationError("District-to-ACZ reconciliation failed")

        # RQ3 source-support audit: preserve supported zeroes as numerical zeroes and
        # fail if any paired MCD64A1 observation is structurally/numerically missing.
        # Construct only the governed paired slice needed by the support audit; input
        # validation must not import or execute the RQ3 estimator stack.
        from .validation import rq3_mcd64a1_support_audit

        paired_ids = set(
            summary.paired_mask.units.loc[
                summary.paired_mask.units["eligible"], "unit_id"
            ].astype(str)
        )
        paired_spec = bundle.analysis.study["populations"]["paired_overlap"]
        start_year, start_month = (int(value) for value in str(paired_spec["start"]).split("-"))
        end_year, end_month = (int(value) for value in str(paired_spec["end"]).split("-"))
        start_yyyymm = start_year * 100 + start_month
        end_yyyymm = end_year * 100 + end_month
        rq3_paired = authorities.district_panel.loc[
            authorities.district_panel["unit_id"].astype(str).isin(paired_ids)
            & authorities.district_panel["yyyymm"].between(start_yyyymm, end_yyyymm)
        ].copy()
        rq3_support = rq3_mcd64a1_support_audit(rq3_paired)
    except Exception as exc:
        return fail(exc)

    populations = {
        "ACZ_MONTHLY_ROWS": int(summary.acz_monthly_rows),
        "DISTRICT_MONTHLY_ROWS": int(summary.district_monthly_rows),
        "DISTRICT_UNITS": int(summary.district_spatial_universe_count),
        "LONG_RUN_DISTRICTS": int(summary.long_run_eligible_count),
        "LONG_RUN_ROWS": int(summary.long_run_rows),
        "PAIRED_DISTRICTS": int(summary.paired_eligible_count),
        "PAIRED_ROWS": int(summary.paired_rows),
        "RQ3_GEE_DISTRICTS": int(summary.rq3_gee_units),
        "RQ3_GEE_ROWS": int(summary.rq3_gee_rows),
    }
    temporal_support = {
        "long_run_start": summary.long_run_start,
        "long_run_end": summary.long_run_end,
        "overlap_start": summary.overlap_start,
        "overlap_end": summary.overlap_end,
        "complete_year_start": int(summary.complete_year_start),
        "complete_year_end": int(summary.complete_year_end),
    }
    geometry = {
        "acz_features": int(len(authorities.acz_geometry)),
        "district_features": int(len(authorities.district_geometry)),
        "acz_crs": str(authorities.acz_geometry.crs),
        "district_crs": str(authorities.district_geometry.crs),
    }
    report.update(
        {
            "status": "PASS",
            "input_validation_status": "PASS",
            "panel_schema_validation": {
                "status": "PASS",
                "analysis_schema_version": bundle.analysis.schema_version,
                "data_schema_version": bundle.data_schema.data_schema_version,
                "panel_schema_version": bundle.data_schema.panel_schema_version,
                "acz_rows": int(summary.acz_monthly_rows),
                "district_rows": int(summary.district_monthly_rows),
            },
            "populations": populations,
            "population_summary": populations,
            "temporal_support": temporal_support,
            "geometry": geometry,
            "geometry_summary": {"status": "PASS", **geometry},
            "reconciliation": reconciliation.to_dict(orient="records"),
            "reconciliation_summary": {
                "status": "PASS",
                "rows": int(len(reconciliation)),
                "all_passed": True,
                "absolute_tolerance": float(summary.reconciliation_absolute_tolerance),
                "relative_tolerance": float(summary.reconciliation_relative_tolerance),
            },
            "rq3_mcd64a1_support_by_month": rq3_support.to_dict(orient="records"),
            "validation_error": None,
        }
    )
    return report


@contextmanager
def _temporary_environment(values: dict[str, str]) -> Iterator[None]:
    original = {key: os.environ.get(key) for key in values}
    try:
        os.environ.update(values)
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def finalise_interactive_run(
    *,
    paths: ProjectPaths | None = None,
    run_id: str,
) -> InteractiveFinalisationResult:
    """Finalise a completed direct-Jupyter run without fabricating notebook-save evidence.

    The function is intentionally closeout-only: it does not execute scientific
    analysis, execute SaTScan, or create an executed-notebook snapshot.  When the
    notebook is being executed by the controlled nbclient wrapper, finalisation is
    explicitly deferred so the wrapper can write its stronger execution evidence.
    """

    governed = paths or ProjectPaths.discover()
    bundle = load_configuration_bundle(governed.root / "config")
    context_mode = os.environ.get("RP1_NOTEBOOK_EXECUTION_MODE", "interactive_jupyter")
    if context_mode == "controlled_nbclient":
        return InteractiveFinalisationResult(
            run_id=run_id,
            closeout_run_dir=governed.resolve_inside(f"out/runs/{run_id}_close"),
            execution_record=None,
            status="DEFERRED_TO_CONTROLLED_WRAPPER",
            execution_mode=context_mode,
            reused_existing_record=False,
            deferred_to_controlled_wrapper=True,
            summary={
                "run_id": run_id,
                "execution_mode": context_mode,
                "status": "DEFERRED_TO_CONTROLLED_WRAPPER",
            },
        )
    if context_mode != "interactive_jupyter":
        raise IntegrationError(f"Unsupported notebook execution context: {context_mode}")

    publication_run_dir = governed.resolve_inside(f"out/runs/{run_id}_pub")
    secondary_run_dir = governed.resolve_inside(f"out/runs/{run_id}_sec")
    closeout_run_dir = governed.resolve_inside(f"out/runs/{run_id}_close")
    for path in (publication_run_dir, secondary_run_dir, closeout_run_dir):
        if not path.is_dir():
            raise IntegrationError(f"Missing governed run directory for interactive finalisation: {path.name}")

    closeout_section = closeout_run_dir / bundle.execution.closeout_section
    gate_path = closeout_section / bundle.execution.artifact_roles["canonical_gate"]
    provenance_path = closeout_section / bundle.execution.artifact_roles["reproducibility_manifest"]
    execution_path = closeout_section / bundle.execution.artifact_roles["execution_record"]
    if not gate_path.is_file():
        raise IntegrationError("Interactive finalisation requires the canonical execution gate")
    if not provenance_path.is_file():
        raise IntegrationError("Interactive finalisation requires the reproducibility manifest")

    try:
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrationError("Interactive closeout authority is malformed") from exc

    required_gate_fields = (
        "scaffold_gate",
        "rq1_gate",
        "rq2_gate",
        "rq3_gate",
        "secondary_gate",
        "publication_gate",
        "final_run_gate",
    )
    missing_gate_fields = [name for name in required_gate_fields if name not in gate]
    if missing_gate_fields:
        raise IntegrationError(
            "Canonical execution gate is missing required completion field(s): "
            + ", ".join(missing_gate_fields)
        )
    if any(gate[name] != bundle.execution.required_final_gate for name in required_gate_fields):
        raise IntegrationError("Interactive finalisation requires every canonical section/publication gate to PASS")
    if gate.get("input_validation_status") != bundle.execution.required_final_gate:
        raise IntegrationError("Interactive finalisation requires input_validation_status=PASS")
    if gate.get("canonical_input_identity") not in {"MATCH", "DIFFERENT"}:
        raise IntegrationError(
            "Interactive finalisation requires canonical_input_identity=MATCH or DIFFERENT"
        )
    if gate.get("configuration_sha256") != bundle.configuration_sha256:
        raise IntegrationError("Canonical execution gate configuration identity is inconsistent")

    if provenance.get("run_id") != f"{run_id}_close":
        raise IntegrationError("Reproducibility manifest run identity is inconsistent")
    if provenance.get("configuration_sha256") != bundle.configuration_sha256:
        raise IntegrationError("Reproducibility manifest configuration identity is inconsistent")
    if not provenance.get("ended_at_utc"):
        raise IntegrationError("Reproducibility manifest is not finalised")
    if provenance.get("input_validation_status") != bundle.execution.required_final_gate:
        raise IntegrationError("Reproducibility manifest input validation state is inconsistent")
    if provenance.get("canonical_input_identity") != gate.get("canonical_input_identity"):
        raise IntegrationError("Reproducibility manifest canonical input identity is inconsistent")
    if not isinstance(provenance.get("inputs"), list) or not provenance.get("inputs"):
        raise IntegrationError("Reproducibility manifest does not record actual current input identities")

    secondary_section = secondary_run_dir / "04_secondary_concentration"
    status_path = _secondary_output_path(
        secondary_section, bundle.output, "external_execution_status"
    )
    registry_path = _secondary_output_path(
        secondary_section, bundle.output, "secondary_run_registry"
    )
    if not status_path.is_file() or not registry_path.is_file():
        raise IntegrationError("Interactive finalisation requires secondary state authorities")
    try:
        status_payload = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrationError("Secondary execution-status record is malformed") from exc
    secondary_state = str(status_payload.get("external_execution_state", ""))
    try:
        validate_secondary_completion_state(bundle.execution, secondary_state)
    except ExecutionContractError as exc:
        raise IntegrationError(str(exc)) from exc
    try:
        secondary_registry = pd.read_csv(registry_path, keep_default_na=False)
    except Exception as exc:
        raise IntegrationError("Secondary run registry is malformed") from exc
    configured_model_count = len(tuple(bundle.analysis.secondary_analysis["scenarios"]))
    if len(secondary_registry) != configured_model_count:
        raise IntegrationError("Secondary run registry model count is inconsistent")
    if set(secondary_registry["execution_state"].astype(str)) != {secondary_state}:
        raise IntegrationError("Secondary run registry state is inconsistent with execution status")
    if int(status_payload.get("model_count", -1)) != configured_model_count:
        raise IntegrationError("Secondary execution-status model count is inconsistent")
    try:
        validated_model_count = int(status_payload.get("validated_model_count", 0))
    except (TypeError, ValueError) as exc:
        raise IntegrationError("Secondary validated_model_count is malformed") from exc
    if secondary_state == "RESULTS_VALIDATED":
        secondary_integration_state = bundle.execution.results_validated_required_integration_state
        if validated_model_count != configured_model_count:
            raise IntegrationError("RESULTS_VALIDATED secondary run has an inconsistent validated model count")
        source_manifest = (
            secondary_section / "publication_sources" / "M_SATSCAN_PUBLICATION_SOURCE_MANIFEST.json"
        )
        if not source_manifest.is_file():
            raise IntegrationError("RESULTS_VALIDATED secondary run is missing integrated publication-source authority")
        try:
            source_payload = json.loads(source_manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise IntegrationError("Run-local SaTScan publication-source manifest is malformed") from exc
        if source_payload.get("external_execution_state") != "RESULTS_VALIDATED":
            raise IntegrationError("Run-local SaTScan publication-source state is inconsistent")
    else:
        secondary_integration_state = "NOT_INTEGRATED"
        if validated_model_count != 0:
            raise IntegrationError("EXTERNAL_RESULTS_REQUIRED secondary run reports validated models")

    try:
        section_gates = canonical_section_gates(gate)
    except ExecutionContractError as exc:
        raise IntegrationError(str(exc)) from exc
    interactive_mode = bundle.execution.mode("interactive_jupyter")
    record: dict[str, Any] = {
        "schema": bundle.execution.execution_record_schema,
        "status": bundle.execution.required_final_gate,
        "run_id": run_id,
        "execution_mode": interactive_mode.mode_id,
        "canonical_notebook": str(bundle.analysis.project["canonical_notebook"]),
        "package_version": bundle.package_version,
        "analysis_schema_version": bundle.analysis.schema_version,
        "data_schema_version": bundle.data_schema.data_schema_version,
        "configuration_sha256": bundle.configuration_sha256,
        "operational_configuration_sha256": bundle.operational_configuration_sha256,
        "final_section_reached": True,
        "canonical_gate_status": str(gate["final_run_gate"]),
        "canonical_gate_sha256": sha256_file(gate_path),
        "reproducibility_manifest_sha256": sha256_file(provenance_path),
        "publication_gate_status": str(gate["publication_gate"]),
        "section_gates": section_gates,
        "input_validation_status": str(gate["input_validation_status"]),
        "canonical_input_identity": str(gate["canonical_input_identity"]),
        "secondary_execution_state": secondary_state,
        "secondary_integration_state": secondary_integration_state,
        "secondary_validated_model_count": validated_model_count,
        "satscan_execution_performed": False,
        "notebook_snapshot_required": interactive_mode.notebook_snapshot_required,
        "notebook_snapshot_available": False,
        "provenance_limitations": [
            "Interactive kernel execution does not attest that the Jupyter front-end saved the current notebook document.",
            "No executed-notebook snapshot or wrapper-observed code-cell completion is claimed for interactive execution.",
        ],
        "publication_run": publication_run_dir.relative_to(governed.root).as_posix(),
        "secondary_run": secondary_run_dir.relative_to(governed.root).as_posix(),
        "closeout_run": closeout_run_dir.relative_to(governed.root).as_posix(),
        "completion_timestamp_utc": utc_now_iso(),
    }
    try:
        validate_execution_record(record, bundle.execution, expected_run_id=run_id)
    except ExecutionContractError as exc:
        raise IntegrationError(str(exc)) from exc

    if execution_path.exists():
        try:
            existing = json.loads(execution_path.read_text(encoding="utf-8"))
            validate_execution_record(existing, bundle.execution, expected_run_id=run_id)
        except (OSError, json.JSONDecodeError, ExecutionContractError) as exc:
            raise IntegrationError("Existing interactive execution record is invalid") from exc
        if existing.get("execution_mode") != "interactive_jupyter":
            raise IntegrationError("Existing execution record conflicts with interactive finalisation")
        invariant_fields = (
            "schema",
            "status",
            "run_id",
            "execution_mode",
            "canonical_notebook",
            "package_version",
            "analysis_schema_version",
            "data_schema_version",
            "configuration_sha256",
            "operational_configuration_sha256",
            "final_section_reached",
            "canonical_gate_status",
            "canonical_gate_sha256",
            "reproducibility_manifest_sha256",
            "publication_gate_status",
            "section_gates",
            "input_validation_status",
            "canonical_input_identity",
            "secondary_execution_state",
            "secondary_integration_state",
            "secondary_validated_model_count",
            "satscan_execution_performed",
            "notebook_snapshot_required",
            "notebook_snapshot_available",
            "provenance_limitations",
            "publication_run",
            "secondary_run",
            "closeout_run",
        )
        changed = [name for name in invariant_fields if existing.get(name) != record.get(name)]
        if changed:
            raise IntegrationError(
                "Existing interactive execution record conflicts with current run state: "
                + ", ".join(changed)
            )
        try:
            validate_completed_closeout(
                closeout_run_dir,
                bundle.execution,
                expected_run_id=run_id,
                expected_configuration_sha256=bundle.configuration_sha256,
                expected_operational_configuration_sha256=bundle.operational_configuration_sha256,
                expected_package_version=bundle.package_version,
                expected_analysis_schema_version=bundle.analysis.schema_version,
                expected_data_schema_version=bundle.data_schema.data_schema_version,
                expected_secondary_state=secondary_state,
                expected_secondary_integration_state=secondary_integration_state,
                expected_secondary_validated_model_count=validated_model_count,
            )
        except ExecutionContractError as exc:
            raise IntegrationError(f"Interactive closeout validation failed: {exc}") from exc
        return InteractiveFinalisationResult(
            run_id=run_id,
            closeout_run_dir=closeout_run_dir,
            execution_record=execution_path,
            status="PASS",
            execution_mode="interactive_jupyter",
            reused_existing_record=True,
            deferred_to_controlled_wrapper=False,
            summary=dict(existing),
        )

    writer = OutputWriter(closeout_run_dir, bundle.output)
    output_record = writer.write_json(
        f"{bundle.execution.closeout_section}/{bundle.execution.artifact_roles['execution_record']}",
        record,
        role="internal_authority",
    )
    execution_path = closeout_run_dir / output_record.path
    validate_required_artifact_presence(
        bundle.execution, interactive_mode, closeout_section
    )
    try:
        validate_completed_closeout(
            closeout_run_dir,
            bundle.execution,
            expected_run_id=run_id,
            expected_configuration_sha256=bundle.configuration_sha256,
            expected_operational_configuration_sha256=bundle.operational_configuration_sha256,
            expected_package_version=bundle.package_version,
            expected_analysis_schema_version=bundle.analysis.schema_version,
            expected_data_schema_version=bundle.data_schema.data_schema_version,
            expected_secondary_state=secondary_state,
            expected_secondary_integration_state=secondary_integration_state,
            expected_secondary_validated_model_count=validated_model_count,
        )
    except ExecutionContractError as exc:
        raise IntegrationError(f"Interactive closeout validation failed: {exc}") from exc
    return InteractiveFinalisationResult(
        run_id=run_id,
        closeout_run_dir=closeout_run_dir,
        execution_record=execution_path,
        status="PASS",
        execution_mode="interactive_jupyter",
        reused_existing_record=False,
        deferred_to_controlled_wrapper=False,
        summary=record,
    )


def execute_canonical_notebook(
    *,
    paths: ProjectPaths | None = None,
    run_id: str,
    kernel_name: str = "python3",
    timeout_seconds: int = 3600,
) -> NotebookExecutionResult:
    """Execute the canonical notebook in a fresh kernel from an unrelated cwd."""

    governed = paths or ProjectPaths.discover()
    notebook_path = governed.resolve_inside("RP1_Analysis_v1.ipynb")
    if not notebook_path.is_file():
        raise IntegrationError(f"Canonical notebook is missing: {notebook_path}")

    publication_run_dir = governed.resolve_inside(f"out/runs/{run_id}_pub")
    secondary_run_dir = governed.resolve_inside(f"out/runs/{run_id}_sec")
    closeout_run_dir = governed.resolve_inside(f"out/runs/{run_id}_close")
    collisions = [p for p in (publication_run_dir, closeout_run_dir) if p.exists()]
    if collisions:
        raise IntegrationError(
            f"Run identifier collides with existing output: {collisions[0].name}"
        )
    if secondary_run_dir.exists():
        bundle = load_configuration_bundle(governed.root / "config")
        _validate_secondary_run(
            secondary_run_dir,
            bundle.analysis,
            bundle.output,
            allow_validated_ready_for_integration=True,
        )

    # The canonical notebook is the thin orchestration authority for the run.
    # A pre-existing, validated 04-01 secondary run is intentionally reusable so
    # an operator can execute SaTScan outside Python, place genuine results at
    # the parameter-governed ResultsFile paths, and then resume the same run.
    # It creates the governed publication, secondary-interface and closeout
    # directories through package APIs inside the fresh kernel.
    print("[rp1-analysis-v1] starting canonical notebook kernel", flush=True)

    nb = nbformat.read(notebook_path, as_version=4)
    code_cells = sum(cell.cell_type == "code" for cell in nb.cells)
    bundle = load_configuration_bundle(governed.root / "config")
    controlled_mode_spec = bundle.execution.mode("controlled_nbclient")
    controlled_mode = controlled_mode_spec.mode_id
    with tempfile.TemporaryDirectory(prefix="rp1_analysis_v1_notebook_cwd_") as isolated_cwd:
        env = {
            "RP1_ANALYSIS_V1_ROOT": str(governed.root),
            "RP1_NOTEBOOK_RUN_ID": run_id,
            "RP1_NOTEBOOK_EXECUTION_MODE": controlled_mode,
            "MPLBACKEND": "Agg",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            "PYTHONHASHSEED": "0",
        }
        with _temporary_environment(env):
            client = NotebookClient(
                nb,
                timeout=timeout_seconds,
                kernel_name=kernel_name,
                allow_errors=False,
                resources={"metadata": {"path": isolated_cwd}},
                on_cell_start=lambda cell, cell_index: print(
                    f"[rp1-analysis-v1] cell-start {cell_index}: {cell.get('id', '<no-id>')}",
                    flush=True,
                ),
            )
            try:
                executed = client.execute()
            except Exception as exc:  # nbclient exposes several execution-specific exception types
                raise IntegrationError(f"Canonical notebook execution failed: {exc}") from exc

    if not closeout_run_dir.is_dir():
        raise IntegrationError("Notebook did not create the governed closeout run directory")
    if not publication_run_dir.is_dir():
        raise IntegrationError("Notebook did not create the governed publication run directory")
    if not secondary_run_dir.is_dir():
        raise IntegrationError("Notebook did not create the governed secondary run directory")

    executed_code_cells = 0
    for cell in executed.cells:
        if cell.cell_type != "code":
            continue
        if cell.get("execution_count") is not None:
            executed_code_cells += 1
    if executed_code_cells != code_cells:
        raise IntegrationError(
            f"Notebook execution incomplete: executed {executed_code_cells}/{code_cells} code cells"
        )

    bundle = load_configuration_bundle(governed.root / "config")
    writer = OutputWriter(closeout_run_dir, bundle.output)
    executed_bytes = nbformat.writes(executed).encode("utf-8")
    nb_record = writer.write_bytes(
        f"{bundle.execution.closeout_section}/{bundle.execution.artifact_roles['executed_notebook']}",
        executed_bytes,
    )

    secondary_state, _, secondary_details = _validate_secondary_run(
        secondary_run_dir, bundle.analysis, bundle.output
    )
    closeout_section = closeout_run_dir / bundle.execution.closeout_section
    gate_path = closeout_section / bundle.execution.artifact_roles["canonical_gate"]
    provenance_path = closeout_section / bundle.execution.artifact_roles["reproducibility_manifest"]
    try:
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrationError("Controlled wrapper closeout authority is malformed") from exc
    if not isinstance(gate, dict) or not isinstance(provenance, dict):
        raise IntegrationError("Controlled wrapper closeout authority is malformed")
    try:
        section_gates = canonical_section_gates(gate)
    except ExecutionContractError as exc:
        raise IntegrationError(str(exc)) from exc

    log = {
        "schema": bundle.execution.execution_record_schema,
        "status": bundle.execution.required_final_gate,
        "run_id": run_id,
        "execution_mode": controlled_mode,
        "canonical_notebook": str(bundle.analysis.project["canonical_notebook"]),
        "package_version": bundle.package_version,
        "analysis_schema_version": bundle.analysis.schema_version,
        "data_schema_version": bundle.data_schema.data_schema_version,
        "configuration_sha256": bundle.configuration_sha256,
        "operational_configuration_sha256": bundle.operational_configuration_sha256,
        "final_section_reached": True,
        "canonical_gate_status": str(gate.get("final_run_gate", "")),
        "canonical_gate_sha256": sha256_file(gate_path),
        "reproducibility_manifest_sha256": sha256_file(provenance_path),
        "publication_gate_status": str(gate.get("publication_gate", "")),
        "section_gates": section_gates,
        "input_validation_status": str(gate.get("input_validation_status", "")),
        "canonical_input_identity": str(gate.get("canonical_input_identity", "")),
        "secondary_execution_state": secondary_state,
        "secondary_integration_state": str(secondary_details["integration_state"]),
        "secondary_validated_model_count": int(secondary_details["validated_model_count"]),
        "satscan_execution_performed": False,
        "notebook_snapshot_required": controlled_mode_spec.notebook_snapshot_required,
        "notebook_snapshot_available": True,
        "completion_timestamp_utc": utc_now_iso(),
        "kernel_name": kernel_name,
        "execution_cwd_policy": "isolated_temporary_directory",
        "code_cells": int(code_cells),
        "executed_code_cells": int(executed_code_cells),
        "executed_notebook_path": nb_record.path,
        "executed_notebook_sha256": nb_record.sha256,
        "publication_run": publication_run_dir.relative_to(governed.root).as_posix(),
        "secondary_run": secondary_run_dir.relative_to(governed.root).as_posix(),
        "closeout_run": closeout_run_dir.relative_to(governed.root).as_posix(),
    }
    try:
        validate_execution_record(log, bundle.execution, expected_run_id=run_id)
    except ExecutionContractError as exc:
        raise IntegrationError(f"Controlled wrapper completion evidence is invalid: {exc}") from exc
    log_record = writer.write_json(
        f"{bundle.execution.closeout_section}/{bundle.execution.artifact_roles['execution_record']}",
        log,
    )
    try:
        validate_completed_closeout(
            closeout_run_dir,
            bundle.execution,
            expected_run_id=run_id,
            expected_configuration_sha256=bundle.configuration_sha256,
            expected_operational_configuration_sha256=bundle.operational_configuration_sha256,
            expected_package_version=bundle.package_version,
            expected_analysis_schema_version=bundle.analysis.schema_version,
            expected_data_schema_version=bundle.data_schema.data_schema_version,
            expected_secondary_state=secondary_state,
            expected_secondary_integration_state=str(secondary_details["integration_state"]),
            expected_secondary_validated_model_count=int(secondary_details["validated_model_count"]),
        )
    except ExecutionContractError as exc:
        raise IntegrationError(f"Controlled wrapper closeout validation failed: {exc}") from exc
    return NotebookExecutionResult(
        run_id=run_id,
        publication_run_dir=publication_run_dir,
        secondary_run_dir=secondary_run_dir,
        closeout_run_dir=closeout_run_dir,
        executed_notebook=closeout_run_dir / nb_record.path,
        execution_log=closeout_run_dir / log_record.path,
        code_cells=int(code_cells),
        executed_code_cells=int(executed_code_cells),
    )


def _read_csv(path: Path, label: str) -> pd.DataFrame:
    if not path.is_file():
        raise IntegrationError(f"Missing {label}: {path.name}")
    try:
        return pd.read_csv(path)
    except Exception as exc:
        raise IntegrationError(f"Unable to read {label}: {path}") from exc


def _verify_hash(path: Path, expected: str, context: str) -> None:
    if not path.is_file():
        raise IntegrationError(f"Missing {context}: {path}")
    observed = sha256_file(path)
    if observed != str(expected):
        raise IntegrationError(f"SHA-256 mismatch for {context}: {path}")


def _validate_publication_run(run_dir: Path) -> tuple[int, int, list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    integrated = run_dir / "90_integrated"
    table_reg = _read_csv(integrated / "T_TABLE_REGISTRY.csv", "table registry")
    figure_reg = _read_csv(integrated / "T_FIGURE_REGISTRY.csv", "figure registry")
    result_reg = _read_csv(integrated / "T_RESULT_REGISTRY.csv", "result registry")
    artefact_reg = _read_csv(integrated / "T_ARTEFACT_REGISTRY.csv", "artefact registry")

    bundle = load_configuration_bundle(run_dir.parents[2] / "config")
    expected_tables = {spec[0] for spec in table_specs(bundle.output)}
    expected_figures = {spec[0] for spec in figure_specs(bundle.figure)}
    if set(table_reg["table_id"].astype(str)) != expected_tables:
        raise IntegrationError("Publication table registry does not match the output contract")
    if set(figure_reg["figure_id"].astype(str)) != expected_figures:
        raise IntegrationError("Publication figure registry does not match the output contract")
    if table_reg["table_id"].duplicated().any() or figure_reg["figure_id"].duplicated().any():
        raise IntegrationError("Publication registry contains duplicate identifiers")
    if result_reg["result_id"].duplicated().any():
        raise IntegrationError("Result registry contains duplicate identifiers")
    if not set(result_reg["evidence_class"].astype(str)).issubset(EVIDENCE_CLASSES):
        raise IntegrationError("Result registry contains an unsupported evidence class")

    table_specs_by_id = {item.output_id: item for item in bundle.output.tables}
    figure_specs_by_id = {item.figure_id: item for item in bundle.figure.figures}

    for row in table_reg.to_dict(orient="records"):
        table_id = str(row["table_id"])
        availability = str(row["availability"])
        spec = table_specs_by_id.get(table_id)
        if spec is None:
            raise IntegrationError(f"Publication registry contains unknown table: {table_id}")
        if availability == "AVAILABLE":
            target = run_dir / str(row["path"])
            _verify_hash(target, str(row["sha256"]), f"table {table_id}")
            if target.stat().st_size != int(row["size_bytes"]):
                raise IntegrationError(f"Size mismatch for table {table_id}")
            continue
        if availability != "EXTERNAL_RESULTS_REQUIRED" or not spec.requires_results_validated:
            raise IntegrationError(
                f"Unsupported deferred publication-table state for {table_id}: {availability}"
            )
        path_missing = pd.isna(row["path"]) or str(row["path"]) == ""
        hash_missing = pd.isna(row["sha256"]) or str(row["sha256"]) == ""
        if not path_missing or not hash_missing or int(row["size_bytes"]) != 0:
            raise IntegrationError(
                f"Deferred publication table {table_id} must not claim a materialised result"
            )

    for row in figure_reg.to_dict(orient="records"):
        figure_id = str(row["figure_id"])
        availability = str(row["availability"])
        spec = figure_specs_by_id.get(figure_id)
        if spec is None:
            raise IntegrationError(f"Publication registry contains unknown figure: {figure_id}")
        manifest_path = run_dir / str(row["manifest_path"])
        if not manifest_path.is_file():
            raise IntegrationError(f"Missing figure manifest: {figure_id}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("figure_id") != figure_id:
            raise IntegrationError(f"Figure manifest identity mismatch: {figure_id}")
        if str(manifest.get("availability", "AVAILABLE")) != availability:
            raise IntegrationError(f"Figure registry/manifest availability mismatch: {figure_id}")
        fd = manifest.get("figure_data", {})
        fd_path = run_dir / str(fd.get("path"))
        _verify_hash(fd_path, str(fd.get("sha256")), f"figure data {figure_id}")
        if str(row["figure_data_sha256"]) != str(fd.get("sha256")):
            raise IntegrationError(f"Figure registry/data hash mismatch: {figure_id}")
        images = manifest.get("images")
        if not isinstance(images, list):
            raise IntegrationError(f"Figure manifest images field is malformed: {figure_id}")
        if availability == "AVAILABLE":
            if {x.get("format") for x in images} != {"png", "pdf"}:
                raise IntegrationError(
                    f"Figure manifest does not contain PNG and PDF: {figure_id}"
                )
            for image in images:
                image_path = run_dir / str(image.get("path"))
                _verify_hash(image_path, str(image.get("sha256")), f"figure image {figure_id}")
            continue
        if availability != "EXTERNAL_RESULTS_REQUIRED" or not spec.requires_results_validated:
            raise IntegrationError(
                f"Unsupported deferred publication-figure state for {figure_id}: {availability}"
            )
        if images:
            raise IntegrationError(
                f"Deferred publication figure {figure_id} must not claim rendered images"
            )
        if not (pd.isna(row["png_path"]) or str(row["png_path"]) == ""):
            raise IntegrationError(f"Deferred publication figure {figure_id} has a PNG path")
        if not (pd.isna(row["pdf_path"]) or str(row["pdf_path"]) == ""):
            raise IntegrationError(f"Deferred publication figure {figure_id} has a PDF path")

    registered_paths = set()
    for row in artefact_reg.to_dict(orient="records"):
        rel = str(row["path"])
        if rel in registered_paths:
            raise IntegrationError(f"Duplicate artefact-registry path: {rel}")
        registered_paths.add(rel)
        target = run_dir / rel
        _verify_hash(target, str(row["sha256"]), f"publication artefact {rel}")
        if target.stat().st_size != int(row["size_bytes"]):
            raise IntegrationError(f"Publication artefact size mismatch: {rel}")

    actual_paths = {p.relative_to(run_dir).as_posix() for p in run_dir.rglob("*") if p.is_file()}
    expected_paths = registered_paths | {"90_integrated/T_ARTEFACT_REGISTRY.csv"}
    if actual_paths != expected_paths:
        missing = sorted(expected_paths - actual_paths)
        orphan = sorted(actual_paths - expected_paths)
        raise IntegrationError(
            f"Publication artefact-set mismatch; missing={missing!r}, orphan={orphan!r}"
        )

    checks.extend(
        [
            {"check": "publication_table_registry", "status": "PASS", "observed": len(table_reg)},
            {"check": "publication_figure_registry", "status": "PASS", "observed": len(figure_reg)},
            {
                "check": "publication_artefact_hashes",
                "status": "PASS",
                "observed": len(artefact_reg),
            },
        ]
    )
    return len(table_reg), len(figure_reg), checks


def _validate_secondary_run(
    run_dir: Path,
    analysis: AnalysisContract,
    output: OutputContract,
    *,
    allow_validated_ready_for_integration: bool = False,
) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    """Validate the config-realised external SaTScan execution boundary.

    Completed-run validation performs read-only SaTScan result-family inspection
    so stale, partial or provenance-invalid external results cannot be treated as
    valid completion evidence.  The sole relaxed transition is an explicit
    pre-notebook resume check: a run still recorded as
    ``EXTERNAL_RESULTS_REQUIRED`` may contain a complete, provenance-valid result
    family that is ``VALIDATED_READY_FOR_INTEGRATION``.  That transition is
    accepted only when ``allow_validated_ready_for_integration`` is true; normal
    completed-run validation remains strict.
    """
    checks: list[dict[str, Any]] = []
    section = run_dir / "04_secondary_concentration"
    status_path = _secondary_output_path(section, output, "external_execution_status")
    if not status_path.is_file():
        raise IntegrationError("Secondary execution-status record is missing")
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntegrationError("Secondary execution-status record is malformed") from exc
    if not isinstance(status, dict):
        raise IntegrationError("Secondary execution-status record is malformed")
    state = str(status.get("external_execution_state"))
    supported_states = {"INPUTS_READY", "EXTERNAL_RESULTS_REQUIRED", "RESULTS_VALIDATED"}
    if state not in supported_states:
        raise IntegrationError(f"Unsupported secondary execution state: {state}")

    params = satscan_parameters(analysis)
    configured = tuple(analysis.secondary_analysis["scenarios"])
    if int(status.get("model_count", -1)) != len(configured):
        raise IntegrationError("Secondary status model count differs from executable configuration")
    status_checks = {
        "reporting_method": params.reporting_method,
        "geographical_overlap": params.geographical_overlap,
        "coordinate_anchor_method": params.coordinate_anchor_method,
        "max_spatial_percent": params.max_spatial_percent,
        "max_temporal_months": params.max_temporal_months,
        "monte_carlo_replicates": params.monte_carlo_replicates,
        "alpha": params.alpha,
        "user_defined_random_seed_supported": params.user_defined_random_seed_supported,
        "rng_authority": params.rng_authority,
    }
    for key, expected in status_checks.items():
        observed = status.get(key)
        if isinstance(expected, float):
            try:
                match = abs(float(observed) - expected) <= 1e-12
            except Exception:
                match = False
        else:
            match = observed == expected
        if not match:
            raise IntegrationError(f"Secondary status {key} differs from executable configuration")

    scenario = _read_csv(
        _secondary_output_path(section, output, "scan_specification_registry"),
        "secondary scan specification registry",
    )
    external = _read_csv(
        _secondary_output_path(section, output, "secondary_run_registry"),
        "secondary external-run registry",
    )
    outputs = _read_csv(
        _secondary_output_path(section, output, "secondary_output_registry"),
        "secondary output registry",
    )
    if scenario["model_id"].duplicated().any() or len(scenario) != len(configured):
        raise IntegrationError("Secondary scan registry does not match configured scenario cardinality")
    expected_ids = {str(item["scenario_id"]) for item in configured}
    if set(scenario["model_id"].astype(str)) != expected_ids:
        raise IntegrationError("Secondary scan registry scenario IDs differ from executable configuration")
    if set(scenario["max_spatial_percent"].astype(float)) != {float(params.max_spatial_percent)}:
        raise IntegrationError("Secondary scan registry spatial ceiling differs from executable configuration")
    if set(scenario["max_temporal_months"].astype(int)) != {int(params.max_temporal_months)}:
        raise IntegrationError("Secondary scan registry temporal maximum differs from executable configuration")
    if set(scenario["monte_carlo_replicates"].astype(int)) != {int(params.monte_carlo_replicates)}:
        raise IntegrationError("Secondary scan registry Monte Carlo count differs from executable configuration")
    by_id = {str(item["scenario_id"]): item for item in configured}
    for row in scenario.to_dict(orient="records"):
        item = by_id[str(row["model_id"])]
        if str(row["model"]) != str(item["model"]):
            raise IntegrationError(f"Secondary model identity differs for {row['model_id']}")
        population_value = str(row.get("population_field", ""))
        has_population = population_value not in {"", "nan", "None"}
        if str(item["model"]) == "space_time_permutation" and has_population:
            raise IntegrationError("Space-time permutation registry contains an exposure field")
        if str(item["model"]) == "discrete_poisson" and not has_population:
            raise IntegrationError("Discrete-Poisson registry is missing its exposure field")
    if set(external["execution_state"].astype(str)) != {state}:
        raise IntegrationError("Secondary run registry state is inconsistent with execution status")

    missing_result_state = str(analysis.secondary_analysis["external_execution"]["missing_result_policy"])
    if state == missing_result_state:
        result_ids = {
            item.output_id
            for item in output.secondary_outputs
            if item.output_type == "table" and item.requires_results_validated
        }
        generated = {p.stem for p in (section / "tables").glob("*.csv")}
        if result_ids.intersection(generated):
            raise IntegrationError("Result-dependent secondary outputs exist without validated external results")
        awaiting = outputs.loc[outputs["requires_results_validated"].astype(bool), "availability"].astype(str)
        if awaiting.empty or set(awaiting) != {"AWAITING_EXTERNAL_RESULTS"}:
            raise IntegrationError("Secondary output registry does not preserve the external-results boundary")
    elif state == "RESULTS_VALIDATED":
        source_root = section / "publication_sources"
        source_manifest = source_root / "M_SATSCAN_PUBLICATION_SOURCE_MANIFEST.json"
        if not source_manifest.is_file():
            raise IntegrationError("RESULTS_VALIDATED secondary run is missing its run-local publication-source manifest")
        try:
            payload = json.loads(source_manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise IntegrationError("Run-local SaTScan source manifest is malformed") from exc
        if payload.get("schema") != "rp1-satscan-run-local-publication-sources-v1":
            raise IntegrationError("Run-local SaTScan source manifest schema is invalid")
        if payload.get("external_execution_state") != "RESULTS_VALIDATED":
            raise IntegrationError("Run-local SaTScan source manifest state is inconsistent")
        required_names = {
            "table3_satscan_clusters", "cluster_membership_source",
            "cluster_recurrence_source", "supplement_s6_satscan",
        }
        if set(payload.get("sources", {})) != required_names:
            raise IntegrationError("Run-local SaTScan publication-source set is incomplete")
        run_root = run_dir.resolve()
        for name, entry in payload["sources"].items():
            path = (run_dir / str(entry["path"])).resolve()
            try:
                path.relative_to(run_root)
            except ValueError as exc:
                raise IntegrationError("Run-local SaTScan source path escapes secondary run") from exc
            if not path.is_file():
                raise IntegrationError(f"Run-local SaTScan source is missing: {name}")
            _verify_hash(path, str(entry["sha256"]), f"run-local SaTScan source {name}")
        available = outputs.loc[outputs["requires_results_validated"].astype(bool), "availability"].astype(str)
        if not available.empty and set(available) != {"AVAILABLE"}:
            raise IntegrationError("RESULTS_VALIDATED secondary output registry is not fully available")

    # Inspect the actual result family independently of the recorded state.
    # This catches stale state linkage, partial families and invalid external
    # provenance before a completed run can validate or be exported.
    from .satscan_integration import OptionalSaTScanIntegrationError, inspect_satscan_results

    try:
        inspection = inspect_satscan_results(
            paths=ProjectPaths(run_dir.parents[2]), secondary_run_id=run_dir.name
        )
    except OptionalSaTScanIntegrationError as exc:
        raise IntegrationError(f"Unvalidated SaTScan result family: {exc}") from exc
    pending_validated_results = (
        allow_validated_ready_for_integration
        and state == missing_result_state
        and inspection.external_execution_state == "RESULTS_VALIDATED"
        and inspection.integration_state == "VALIDATED_READY_FOR_INTEGRATION"
        and inspection.validated_model_count == len(configured)
    )
    if inspection.external_execution_state != state and not pending_validated_results:
        raise IntegrationError(
            "Secondary execution state is stale or inconsistent with the current SaTScan result family"
        )
    try:
        recorded_validated_count = int(status.get("validated_model_count", 0))
    except (TypeError, ValueError) as exc:
        raise IntegrationError("Secondary validated_model_count is malformed") from exc
    if pending_validated_results:
        if recorded_validated_count != 0:
            raise IntegrationError(
                "EXTERNAL_RESULTS_REQUIRED resume state must record zero validated models before integration"
            )
    elif recorded_validated_count != inspection.validated_model_count:
        raise IntegrationError(
            "Secondary validated_model_count is inconsistent with validated SaTScan provenance"
        )
    if state == "RESULTS_VALIDATED" and inspection.integration_state != "INTEGRATED":
        raise IntegrationError("RESULTS_VALIDATED secondary state is not fully integrated")

    details = {
        "integration_state": inspection.integration_state,
        "validated_model_count": int(inspection.validated_model_count),
        "result_families_detected": tuple(inspection.result_families_detected),
    }
    checks.extend([
        {"check": "secondary_execution_state", "status": "PASS", "observed": state},
        {"check": "secondary_scan_config_projection", "status": "PASS", "observed": len(scenario)},
        {"check": "secondary_result_family_provenance", "status": "PASS", "observed": inspection.integration_state},
    ])
    return state, checks, details

def _validate_closeout_run(
    run_dir: Path,
    run_id: str,
    *,
    bundle: Any,
    secondary_state: str,
    secondary_details: dict[str, Any],
) -> list[dict[str, Any]]:
    """Validate completed-run closeout through the shared execution contract."""

    try:
        _, checks = validate_completed_closeout(
            run_dir,
            bundle.execution,
            expected_run_id=run_id,
            expected_configuration_sha256=bundle.configuration_sha256,
            expected_operational_configuration_sha256=bundle.operational_configuration_sha256,
            expected_package_version=bundle.package_version,
            expected_analysis_schema_version=bundle.analysis.schema_version,
            expected_data_schema_version=bundle.data_schema.data_schema_version,
            expected_secondary_state=secondary_state,
            expected_secondary_integration_state=str(secondary_details["integration_state"]),
            expected_secondary_validated_model_count=int(secondary_details["validated_model_count"]),
        )
    except ExecutionContractError as exc:
        raise IntegrationError(str(exc)) from exc
    return list(checks)

def _inventory_runs(governed: ProjectPaths, run_dirs: list[Path]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for run_dir in run_dirs:
        for path in sorted(p for p in run_dir.rglob("*") if p.is_file()):
            rows.append(
                {
                    "path": path.relative_to(governed.root).as_posix(),
                    "sha256": sha256_file(path),
                    "size_bytes": int(path.stat().st_size),
                }
            )
    return pd.DataFrame(rows).sort_values("path").reset_index(drop=True)


def validate_run_authority(
    *,
    paths: ProjectPaths | None = None,
    run_id: str,
) -> RunValidationResult:
    """Validate the complete primary run, secondary state and reproducibility closeout."""

    governed = paths or ProjectPaths.discover()
    publication_run = governed.resolve_inside(f"out/runs/{run_id}_pub")
    secondary_run = governed.resolve_inside(f"out/runs/{run_id}_sec")
    closeout_run = governed.resolve_inside(f"out/runs/{run_id}_close")
    for path in (publication_run, secondary_run, closeout_run):
        if not path.is_dir():
            raise IntegrationError(f"Missing governed run directory: {path.name}")

    bundle = load_configuration_bundle(governed.root / "config")
    table_count, figure_count, publication_checks = _validate_publication_run(publication_run)
    secondary_state, secondary_checks, secondary_details = _validate_secondary_run(
        secondary_run, bundle.analysis, bundle.output
    )
    closeout_checks = _validate_closeout_run(
        closeout_run,
        run_id,
        bundle=bundle,
        secondary_state=secondary_state,
        secondary_details=secondary_details,
    )
    inventory = _inventory_runs(governed, [publication_run, secondary_run, closeout_run])
    checks = tuple(publication_checks + secondary_checks + closeout_checks)

    return RunValidationResult(
        run_id=run_id,
        status="PASS",
        publication_files=sum(p.is_file() for p in publication_run.rglob("*")),
        secondary_files=sum(p.is_file() for p in secondary_run.rglob("*")),
        closeout_files=sum(p.is_file() for p in closeout_run.rglob("*")),
        publication_tables=table_count,
        publication_figures=figure_count,
        secondary_external_state=secondary_state,
        output_inventory=inventory,
        checks=checks,
    )
