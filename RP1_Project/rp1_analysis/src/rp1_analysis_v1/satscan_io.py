"""Deterministic SaTScan interface, parser, and external-execution provenance.

The module deliberately separates Python-side authority construction from live
SaTScan execution.  A missing executable is an explicit deferral, never a
zero-cluster result.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from calendar import monthrange
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd
from scipy.spatial.distance import pdist

MODEL_DISCRETE_POISSON = "discrete_poisson"
MODEL_SPACE_TIME_PERMUTATION = "space_time_permutation"
REPORTING_HIERARCHICAL = "hierarchical_non_overlapping"


class SaTScanIOError(RuntimeError):
    """Raised when the governed SaTScan interface is invalid."""


class ExternalResultsRequired(SaTScanIOError):
    """Raised when real external results are required but are absent."""


class ExternalResultValidationError(SaTScanIOError):
    """Raised when external output cannot be tied to its exact run authority."""



_FATAL_EXECUTION_DIAGNOSTICS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "Invalid Parameter Setting",
        re.compile(r"\binvalid\s+parameter\s+setting\b", re.IGNORECASE),
    ),
    (
        "parameter settings prevent SaTScan from continuing",
        re.compile(
            r"\bparameter\s+settings?\s+prevent\s+satscan\s+from\s+continuing\b",
            re.IGNORECASE,
        ),
    ),
)


def _assert_no_fatal_execution_diagnostic(text: str, *, context: str) -> None:
    """Fail closed on recognised SaTScan semantic execution rejections."""

    for label, pattern in _FATAL_EXECUTION_DIAGNOSTICS:
        if pattern.search(text):
            raise ExternalResultValidationError(
                f"{context} contains fatal SaTScan diagnostic: {label}"
            )


def _execution_platform() -> str:
    """Record the host without launching shell/WMI subprocesses."""
    if hasattr(sys, "getwindowsversion"):
        version = sys.getwindowsversion()
        return f"{sys.platform} {version.major}.{version.minor}.{version.build}"
    if hasattr(os, "uname"):
        version = os.uname()
        return f"{version.sysname} {version.release} {version.machine}"
    return f"{sys.platform} ({os.name})"


def _relative_run_path(path: str | Path, *, root: Path, label: str) -> str:
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise ExternalResultValidationError(
            f"{label} must resolve inside the governed SaTScan run directory"
        ) from exc


def _normalised_results_prefix(value: str | Path, *, root: Path) -> str:
    token = _normalise_posix(str(value))
    candidate = Path(value)
    if candidate.is_absolute():
        return _relative_run_path(candidate, root=root, label="results_prefix")
    return token

@dataclass(frozen=True, slots=True)
class ExecutableProvenance:
    path: str
    sha256: str
    version: str


@dataclass(frozen=True, slots=True)
class ParsedSaTScanResults:
    scenario_id: str
    model: str
    clusters: pd.DataFrame
    membership: pd.DataFrame
    provenance: Mapping[str, Any]


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")).hexdigest()


def _normalise_posix(path: str) -> str:
    return str(path).replace("\\", "/")


def coordinate_text(frame: pd.DataFrame) -> str:
    required = ["location_id", "x", "y"]
    if list(frame.columns) != required:
        raise SaTScanIOError(f"Coordinate frame must have exact columns {required!r}")
    work = frame.sort_values("location_id", kind="mergesort")
    if work["location_id"].duplicated().any():
        raise SaTScanIOError("Coordinate location IDs must be unique")
    values = work[["x", "y"]].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise SaTScanIOError("Coordinates contain non-finite values")
    return "".join(
        f"{int(row.location_id)} {float(row.x):.6f} {float(row.y):.6f}\n"
        for row in work.itertuples(index=False)
    )


def case_text(frame: pd.DataFrame) -> str:
    required = ["location_id", "cases", "date", "yyyymm"]
    if list(frame.columns) != required:
        raise SaTScanIOError(f"Case frame must have exact columns {required!r}")
    work = frame.sort_values(["yyyymm", "location_id"], kind="mergesort")
    values = pd.to_numeric(work["cases"], errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any() or not np.allclose(values, np.rint(values)):
        raise SaTScanIOError("Case rows must contain positive integer counts")
    return "".join(
        f"{int(row.location_id)} {int(row.cases)} {row.date}\n"
        for row in work.itertuples(index=False)
    )


def population_text(frame: pd.DataFrame) -> str:
    required = ["location_id", "date", "population", "yyyymm"]
    if list(frame.columns) != required:
        raise SaTScanIOError(f"Population frame must have exact columns {required!r}")
    work = frame.sort_values(["yyyymm", "location_id"], kind="mergesort")
    values = pd.to_numeric(work["population"], errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise SaTScanIOError("Population/exposure rows must be positive and finite")
    return "".join(
        f"{int(row.location_id)} {row.date} {float(row.population):.9f}\n"
        for row in work.itertuples(index=False)
    )


def _validate_monthly_study_period(start_date: str, end_date: str) -> None:
    """Validate SaTScan monthly study-period boundary semantics.

    SaTScan monthly precision requires the study period to begin on the first
    calendar day of the configured starting month and end on the final
    calendar day of the configured ending month.  The dates remain supplied
    by the caller; this function validates interface legality only.
    """

    def parse_boundary(value: str, label: str) -> tuple[int, int, int]:
        match = re.fullmatch(r"(\d{4})/(\d{1,2})/(\d{1,2})", str(value))
        if not match:
            raise SaTScanIOError(
                f"{label} must use SaTScan calendar format YYYY/M/D; got {value!r}"
            )
        year, month, day = (int(part) for part in match.groups())
        try:
            datetime(year, month, day)
        except ValueError as exc:
            raise SaTScanIOError(f"Invalid {label}: {value!r}") from exc
        return year, month, day

    start_year, start_month, start_day = parse_boundary(start_date, "monthly study-period start date")
    end_year, end_month, end_day = parse_boundary(end_date, "monthly study-period end date")

    if start_day != 1:
        raise SaTScanIOError(
            "Monthly study-period start date must be the first calendar day of its month"
        )
    required_end_day = monthrange(end_year, end_month)[1]
    if end_day != required_end_day:
        raise SaTScanIOError(
            "Monthly study-period end date must be the final calendar day of its month; "
            f"got {end_date!r}, expected {end_year}/{end_month}/{required_end_day}"
        )
    if (end_year, end_month) < (start_year, start_month):
        raise SaTScanIOError("Monthly SaTScan study period is reversed")


def generate_parameter_file(
    *,
    scenario_id: str,
    product: str,
    model: str,
    reporting: str,
    case_path: str,
    population_path: str | None,
    coordinate_path: str,
    results_prefix: str,
    start_date: str,
    end_date: str,
    max_spatial_percent: float,
    max_temporal_months: int,
    monte_carlo_replicates: int,
    analysis_type: str,
    cluster_type: str,
    spatial_window_shape: str,
    geographical_overlap: bool,
    gini_optimised_reporting: bool,
    report_cluster_rank: bool,
    scientific_seed: int,
    user_defined_random_seed_supported: bool,
    user_defined_random_seed_parameter: str | None,
    rng_authority: str,
    engine_rng_behaviour: str,
) -> str:
    """Serialise a config-supplied retrospective space-time SaTScan run.

    Study parameters are supplied by the executable analysis contract.  This
    function validates only what is mathematically or interface-wise legal for
    the implemented SaTScan models; it does not impose Ghana study values.

    SaTScan 10.3.x does not expose a documented user-defined Monte Carlo seed
    parameter in the governed interface.  When the configured authority says
    no such field exists, the scientific seed is recorded in comments and run
    metadata but no invented parameter assignment is written.
    """
    _validate_monthly_study_period(start_date, end_date)

    if not isinstance(max_spatial_percent, (int, float)) or isinstance(max_spatial_percent, bool):
        raise SaTScanIOError("max_spatial_percent must be numeric")
    max_spatial_percent = float(max_spatial_percent)
    if not 0.0 < max_spatial_percent <= 100.0:
        raise SaTScanIOError("max_spatial_percent must lie in (0, 100]")
    if isinstance(max_temporal_months, bool) or not isinstance(max_temporal_months, int) or max_temporal_months < 1:
        raise SaTScanIOError("max_temporal_months must be a positive integer")
    if isinstance(monte_carlo_replicates, bool) or not isinstance(monte_carlo_replicates, int) or monte_carlo_replicates < 1:
        raise SaTScanIOError("monte_carlo_replicates must be a positive integer")
    if isinstance(scientific_seed, bool) or not isinstance(scientific_seed, int) or scientific_seed < 0:
        raise SaTScanIOError("scientific_seed must be a non-negative integer")
    if not isinstance(gini_optimised_reporting, bool):
        raise SaTScanIOError("gini_optimised_reporting must be boolean")
    if not isinstance(report_cluster_rank, bool):
        raise SaTScanIOError("report_cluster_rank must be boolean")
    if analysis_type != "retrospective":
        raise SaTScanIOError(f"Unsupported SaTScan analysis type: {analysis_type!r}")
    if cluster_type != "high_only":
        raise SaTScanIOError(f"Unsupported SaTScan cluster type: {cluster_type!r}")
    if spatial_window_shape != "circular":
        raise SaTScanIOError(f"Unsupported SaTScan spatial-window shape: {spatial_window_shape!r}")
    if reporting != REPORTING_HIERARCHICAL:
        raise SaTScanIOError(f"Unsupported SaTScan cluster-reporting method: {reporting!r}")
    if geographical_overlap:
        raise SaTScanIOError("Current hierarchical reporting implementation supports no geographical overlap")
    if reporting == REPORTING_HIERARCHICAL and gini_optimised_reporting:
        raise SaTScanIOError("Hierarchical non-overlapping reporting forbids Gini optimisation")
    if not isinstance(rng_authority, str) or not rng_authority.strip():
        raise SaTScanIOError("rng_authority must be a non-empty string")
    if not isinstance(engine_rng_behaviour, str) or not engine_rng_behaviour.strip():
        raise SaTScanIOError("engine_rng_behaviour must be a non-empty string")

    seed_line = ""
    if user_defined_random_seed_supported:
        if not isinstance(user_defined_random_seed_parameter, str) or not user_defined_random_seed_parameter.strip():
            raise SaTScanIOError("Supported user-defined seed requires the exact documented SaTScan field name")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", user_defined_random_seed_parameter):
            raise SaTScanIOError("SaTScan random-seed parameter field name is invalid")
        seed_line = f"{user_defined_random_seed_parameter}={scientific_seed}\n"
    elif user_defined_random_seed_parameter is not None:
        raise SaTScanIOError("Unsupported user-defined seed must not define a SaTScan field")

    if model == MODEL_DISCRETE_POISSON:
        if not population_path:
            raise SaTScanIOError("Discrete-Poisson scan requires a population/exposure file")
        model_type = 0
        relative_risk_output = "y"
    elif model == MODEL_SPACE_TIME_PERMUTATION:
        if population_path is not None:
            raise SaTScanIOError("Space-time permutation scan must not receive exposure")
        model_type = 2
        relative_risk_output = "n"
    else:
        raise SaTScanIOError(f"Unsupported SaTScan model identity: {model!r}")

    population_value = "" if population_path is None else _normalise_posix(population_path)
    spatial_token = f"{max_spatial_percent:g}"
    gini_token = "y" if gini_optimised_reporting else "n"
    rank_token = "y" if report_cluster_rank else "n"
    return f"""; Ghana Fire RP1 Analysis - config-realised SaTScan run
; scenario_id={scenario_id}
; product={product}
; model_identity={model}
; reporting_identity={reporting}
; scientific_seed={scientific_seed}
; user_defined_random_seed_supported={str(user_defined_random_seed_supported).lower()}
; rng_authority={rng_authority}
; engine_rng_behaviour={engine_rng_behaviour}
[Input]
CaseFile={_normalise_posix(case_path)}
ControlFile=
PrecisionCaseTimes=2
StartDate={start_date}
EndDate={end_date}
PopulationFile={population_value}
CoordinatesFile={_normalise_posix(coordinate_path)}
UseGridFile=n
GridFile=
CoordinatesType=0

[Analysis]
AnalysisType=3
ModelType={model_type}
ScanAreas=1
TimeAggregationUnits=2
TimeAggregationLength=1

[Spatial Window]
MaxSpatialSizeInPopulationAtRisk={spatial_token}
UseMaxCirclePopulationFileOption=n
UseDistanceFromCenterOption=n
IncludePurelyTemporal=n
SpatialWindowShapeType=0

[Temporal Window]
MinimumTemporalClusterSize=1
MaxTemporalSizeInterpretation=1
MaxTemporalSize={max_temporal_months}
IncludePurelySpatial=n
IncludeClusters=0

[Inference]
PValueReportType=1
ReportGumbel=n
MonteCarloReps={monte_carlo_replicates}
{seed_line}AdjustForEarlierAnalyses=n
IterativeScan=n

[Spatial Output]
ReportHierarchicalClusters=y
CriteriaForReportingSecondaryClusters=0
ReportGiniClusters={gini_token}
UseReportOnlySmallerClusters=n

[Other Output]
ReportClusterRank={rank_token}
PrintAsciiColumnHeaders=y

[Output]
ResultsFile={_normalise_posix(results_prefix)}
MostLikelyClusterEachCentroidASCII=y
MostLikelyClusterCaseInfoEachCentroidASCII=y
CensusAreasReportedClustersASCII=y
IncludeRelativeRisksCensusAreasASCII={relative_risk_output}
SaveSimLLRsASCII=y
OutputShapefiles=n
OutputGoogleEarthKML=n
OutputGoogleMaps=n
"""


def find_satscan_executable() -> str | None:
    for name in ("SaTScanBatch64", "SaTScanBatch", "SaTScan", "satscan64", "satscan"):
        found = shutil.which(name)
        if found:
            return str(Path(found).resolve())
    return None


def executable_provenance(path: str | Path) -> ExecutableProvenance:
    """Read the version from the executable itself and diagnose failed probes."""
    executable = Path(path).resolve()
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise SaTScanIOError(f"SaTScan executable is not executable: {executable}")
    failures = []
    for option in ("--version", "-v"):
        try:
            proc = subprocess.run(
                [str(executable), option], capture_output=True, text=True,
                errors="replace", timeout=10, check=False,
            )
        except OSError as exc:
            failures.append(f"{option} could not launch: {exc}")
            continue
        except subprocess.TimeoutExpired as exc:
            failures.append(f"{option} timed out after {exc.timeout} seconds")
            continue
        except subprocess.SubprocessError as exc:
            failures.append(f"{option} failed: {exc}")
            continue
        text = (proc.stdout + "\n" + proc.stderr).strip()
        # Batch 10.3.3 reports "SaTScan 10.3.3  (64-bit)" without a v marker.
        match = re.search(r"\bSaTScan\s*(?:v(?:ersion)?\s*)?([0-9]+(?:\.[0-9]+)+)\b", text, re.I)
        if match:
            return ExecutableProvenance(str(executable), sha256_file(executable), match.group(1))
        first_line = text.partition("\n")[0].strip()
        if len(text) < 200 and re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", first_line):
            return ExecutableProvenance(str(executable), sha256_file(executable), first_line)
        failures.append(f"{option} exited with code {proc.returncode} without a recognized SaTScan version")
    diagnostics = "\n".join(failures)
    raise SaTScanIOError(f"Unable to establish the SaTScan executable version for {executable}\n{diagnostics}")


def run_satscan(
    *,
    executable_path: str | Path,
    parameter_path: str | Path,
    case_path: str | Path,
    coordinate_path: str | Path,
    population_path: str | Path | None,
    scenario_id: str,
    product: str,
    model: str,
    temporal_start: str,
    temporal_end: str,
    results_prefix: str | Path,
    cwd: str | Path,
    engine_version_authority: str,
    scientific_seed: int,
    user_defined_random_seed_supported: bool,
    user_defined_random_seed_parameter: str | None,
    rng_authority: str,
    engine_rng_behaviour: str,
    alpha: float,
    max_temporal_months: int,
    timeout_seconds: int = 300,
    execution_observer: Callable[[Mapping[str, Any]], None] | None = None,
) -> Mapping[str, Any]:
    """Run and qualify one external SaTScan calculation fail-closed.

    Process return code is only one execution signal.  Success additionally requires
    absence of recognised fatal diagnostics and acceptance of the complete governed
    ``ResultsFile`` family by :func:`validate_external_results`.  The canonical
    result-family validator therefore remains the single definition of scientific
    result readiness used by execution, status and integration paths.
    """

    root = Path(cwd).resolve()
    prm = Path(parameter_path).resolve()
    case = Path(case_path).resolve()
    coordinate = Path(coordinate_path).resolve()
    population = None if population_path is None else Path(population_path).resolve()

    executable = executable_provenance(executable_path)
    if executable.version != engine_version_authority:
        raise ExternalResultValidationError(
            f"SaTScan executable version {executable.version!r} does not match governed authority {engine_version_authority!r}"
        )

    prm_rel = _relative_run_path(prm, root=root, label="parameter_path")
    case_rel = _relative_run_path(case, root=root, label="case_path")
    coordinate_rel = _relative_run_path(coordinate, root=root, label="coordinate_path")
    population_rel = (
        "" if population is None else _relative_run_path(population, root=root, label="population_path")
    )
    governed_prefix = _parameter_value(prm, "ResultsFile")
    supplied_prefix = _normalised_results_prefix(results_prefix, root=root)
    if supplied_prefix != governed_prefix:
        raise ExternalResultValidationError(
            "Supplied results_prefix differs from the parameter-file ResultsFile authority"
        )

    started = datetime.now(timezone.utc).isoformat()
    command = [executable.path, str(prm)]
    try:
        proc = subprocess.run(
            command, cwd=str(root), capture_output=True, text=True,
            timeout=timeout_seconds, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        if execution_observer is not None:
            execution_observer({"command": command, "working_directory": str(root),
                "platform": _execution_platform(), "execution_started_utc": started,
                "execution_completed_utc": datetime.now(timezone.utc).isoformat(),
                "return_code": None, "timed_out": True,
                "stdout": exc.stdout or "", "stderr": exc.stderr or ""})
        raise
    completed = datetime.now(timezone.utc).isoformat()
    observed_execution = {"command": command, "working_directory": str(root),
        "platform": _execution_platform(), "execution_started_utc": started,
        "execution_completed_utc": completed, "return_code": int(proc.returncode),
        "timed_out": False, "stdout": proc.stdout, "stderr": proc.stderr}
    if execution_observer is not None:
        execution_observer(observed_execution)
    diagnostic_text = "\n".join(part for part in (proc.stdout, proc.stderr) if part)
    if proc.returncode != 0:
        raise ExternalResultValidationError(
            f"SaTScan execution failed for {scenario_id} with return code {proc.returncode}"
        )
    _assert_no_fatal_execution_diagnostic(
        diagnostic_text, context=f"SaTScan execution for {scenario_id}"
    )

    run_row: dict[str, Any] = {
        "scenario_id": scenario_id,
        "product": product,
        "model": model,
        "temporal_start": temporal_start,
        "temporal_end": temporal_end,
        "max_temporal_months": int(max_temporal_months),
        "engine_version_authority": engine_version_authority,
        "prm_path": prm_rel,
        "prm_sha256": sha256_file(prm),
        "case_path": case_rel,
        "case_sha256": sha256_file(case),
        "coordinate_path": coordinate_rel,
        "coordinate_sha256": sha256_file(coordinate),
        "population_path": population_rel,
        "population_sha256": "" if population is None else sha256_file(population),
        "results_prefix": governed_prefix,
        "required_report_path": governed_prefix,
        "required_cluster_path": governed_prefix + ".col.txt",
        "required_membership_path": governed_prefix + ".gis.txt",
    }
    try:
        parsed = validate_external_results(run_row, run_dir=root, alpha=float(alpha),
            _observed_execution_in_progress=execution_observer is not None)
    except ExternalResultsRequired as exc:
        raise ExternalResultValidationError(
            f"SaTScan execution for {scenario_id} returned code 0 but produced an incomplete result family: {exc}"
        ) from exc

    return {
        "scenario_id": scenario_id,
        "product_identity": product,
        "model_identity": model,
        "temporal_start": temporal_start,
        "temporal_end": temporal_end,
        "results_prefix": governed_prefix,
        "executable_path": executable.path,
        "executable_version": executable.version,
        "executable_sha256": executable.sha256,
        "parameter_sha256": sha256_file(prm),
        "case_sha256": sha256_file(case),
        "coordinate_sha256": sha256_file(coordinate),
        "population_sha256": "" if population is None else sha256_file(population),
        "scientific_seed": int(scientific_seed),
        "user_defined_random_seed_supported": bool(user_defined_random_seed_supported),
        "user_defined_random_seed_parameter": user_defined_random_seed_parameter,
        "rng_authority": rng_authority,
        "engine_rng_behaviour": engine_rng_behaviour,
        "execution_started_utc": started,
        "execution_completed_utc": completed,
        "return_code": int(proc.returncode),
        "fatal_execution_diagnostic_detected": False,
        "result_family_validated": True,
        "validated_report_sha256": str(parsed.provenance["report_sha256"]),
        "validated_cluster_sha256": str(parsed.provenance["cluster_sha256"]),
        "validated_membership_sha256": str(parsed.provenance["membership_sha256"]),
        "validated_maxima_sha256": parsed.provenance["native_reconciliation"]["simulation_maxima"].get("sha256"),
        "external_provenance_sidecar_written": False,
        **observed_execution,
    }

def _ascii_table(path: Path, context: str) -> tuple[dict[str, int], list[list[str]]]:
    """Read a whitespace-delimited SaTScan ASCII table using its actual header."""
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except UnicodeDecodeError as exc:
        raise ExternalResultValidationError(f"{context} is not UTF-8 text") from exc
    lines = [line.strip() for line in lines if line.strip() and not line.lstrip().startswith(("#", ";"))]
    if not lines:
        raise ExternalResultValidationError(f"{context} has no header")
    names = re.split(r"\s+", lines[0])
    names = [name.upper() for name in names]
    if len(names) != len(set(names)):
        raise ExternalResultValidationError(f"{context} has duplicate header names")
    header = {name: i for i, name in enumerate(names)}
    rows = []
    for number, line in enumerate(lines[1:], start=2):
        fields = re.split(r"\s+", line)
        if len(fields) != len(names):
            raise ExternalResultValidationError(
                f"Malformed SaTScan {context} row {number}: expected {len(names)} fields, got {len(fields)}"
            )
        rows.append(fields)
    return header, rows


def _finite_number(token: str, context: str) -> float:
    number = pd.to_numeric(str(token), errors="coerce")
    if pd.isna(number) or not np.isfinite(float(number)):
        raise ExternalResultValidationError(f"{context} is not finite numeric data")
    return float(number)


def _header_field(header: Mapping[str, int], aliases: tuple[str, ...], context: str) -> int:
    found = [name for name in aliases if name in header]
    if len(found) != 1:
        raise ExternalResultValidationError(
            f"SaTScan header must contain exactly one {context} field; found {found}"
        )
    return header[found[0]]


def _integer(token: str, context: str) -> int:
    value = _finite_number(token, context)
    if not value.is_integer() or value < 1:
        raise ExternalResultValidationError(f"{context} must be a positive integer")
    return int(value)


def _reported_p(token: str, alpha: float, context: str) -> tuple[float, bool]:
    match = re.fullmatch(r"(<=|<)?(\d*\.?\d+(?:[eE][+-]?\d+)?)", token)
    if match is None:
        raise ExternalResultValidationError(f"{context} has an unsupported p-value format")
    qualifier, number = match.groups()
    value = _finite_number(number, context)
    if not 0 <= value <= 1:
        raise ExternalResultValidationError(f"{context} is outside [0, 1]")
    if qualifier and value > alpha:
        raise ExternalResultValidationError(
            f"{context} is reported as {token}; significance at alpha={alpha} is indeterminate"
        )
    return value, value <= alpha


def _p_signature(token: str) -> tuple[str, Decimal]:
    """Compare written p-values numerically while retaining bound semantics."""
    match = re.fullmatch(r"(<=|<)?(\d*\.?\d+(?:[eE][+-]?\d+)?)", token)
    if match is None:
        raise ExternalResultValidationError("Invalid reported p-value")
    qualifier, number = match.groups()
    return qualifier or "", Decimal(number)


def _check_alpha(alpha: float) -> None:
    if not np.isfinite(alpha) or not 0 < alpha <= 1:
        raise ExternalResultValidationError("SaTScan alpha must lie in (0, 1]")


def _result_date(token: str, context: str) -> datetime:
    if re.fullmatch(r"\d{4}/\d{1,2}/\d{1,2}", token) is None:
        raise ExternalResultValidationError(f"{context} is not a full SaTScan date")
    try:
        return datetime.strptime(token, "%Y/%m/%d")
    except ValueError as exc:
        raise ExternalResultValidationError(f"{context} is not a valid date") from exc


def parse_cluster_file(
    path: str | Path, *, alpha: float, model: str | None = None
) -> pd.DataFrame:
    file = Path(path)
    if not file.is_file():
        raise ExternalResultsRequired(f"Missing SaTScan cluster result: {file}")
    _check_alpha(alpha)
    header, rows = _ascii_table(file, "cluster")
    fields = {
        "cluster_id": ("CLUSTER",), "centroid_location_id": ("LOC_ID", "LOCATION"),
        "centroid_x": ("X",), "centroid_y": ("Y",), "radius": ("RADIUS",),
        "radius_max": ("SPAN", "RADIUS_MAX"), "start_date": ("START_DATE",),
        "end_date": ("END_DATE",), "n_locations": ("NUMBER_LOC",),
        "p_value": ("P_VALUE",), "case_count": ("OBSERVED",),
        "expected_count": ("EXPECTED",), "observed_expected_ratio": ("ODE",),
    }
    idx = {key: _header_field(header, aliases, key) for key, aliases in fields.items()}
    has_llr = "LLR" in header
    has_test_stat = "TEST_STAT" in header
    has_rr = "REL_RISK" in header or "RR" in header
    if has_llr == has_test_stat:
        raise ExternalResultValidationError("SaTScan cluster header must contain exactly one of LLR or TEST_STAT")
    inferred_model = MODEL_DISCRETE_POISSON if has_llr else MODEL_SPACE_TIME_PERMUTATION
    if model is None:
        model = inferred_model
    if model not in (MODEL_DISCRETE_POISSON, MODEL_SPACE_TIME_PERMUTATION) or model != inferred_model:
        raise ExternalResultValidationError("SaTScan cluster header does not match the governed model")
    if model == MODEL_DISCRETE_POISSON:
        rr_index = _header_field(header, ("REL_RISK", "RR"), "relative_risk")
    elif has_rr:
        raise ExternalResultValidationError("Space-time permutation header unexpectedly contains relative risk")
    else:
        rr_index = None
    statistic_type = "LLR" if has_llr else "TEST_STAT"
    statistic_index = header[statistic_type]
    records: list[dict[str, Any]] = []
    seen: set[int] = set()
    for tokens in rows:
        cluster_id = _integer(tokens[idx["cluster_id"]], "cluster id")
        if cluster_id in seen:
            raise ExternalResultValidationError("Duplicate SaTScan cluster id")
        seen.add(cluster_id)
        p_report = tokens[idx["p_value"]]
        p_value, significant = _reported_p(p_report, alpha, "cluster p-value")
        observed = _native_decimal(tokens[idx["case_count"]], "observed cases")
        if observed != observed.to_integral_value():
            raise ExternalResultValidationError("SaTScan observed cases must be an integer")
        if observed > 2**53:
            raise ExternalResultValidationError("SaTScan observed cases exceed the exact range of the numeric output schema")
        expected = _finite_number(tokens[idx["expected_count"]], "expected cases")
        observed_expected = _finite_number(tokens[idx["observed_expected_ratio"]], "observed/expected ratio")
        rr = _finite_number(tokens[rr_index], "relative risk") if rr_index is not None else math.nan
        statistic = _finite_number(tokens[statistic_index], statistic_type)
        start_date = tokens[idx["start_date"]]
        end_date = tokens[idx["end_date"]]
        if _result_date(end_date, "cluster end") < _result_date(start_date, "cluster start"):
            raise ExternalResultValidationError("SaTScan cluster end precedes start")
        radius = _finite_number(tokens[idx["radius"]], "radius")
        radius_max = _finite_number(tokens[idx["radius_max"]], "maximum radius")
        if radius < 0 or radius_max < 0:
            raise ExternalResultValidationError("SaTScan cluster radius must be nonnegative")
        if observed < 0 or expected < 0 or observed_expected < 0 or (rr_index is not None and rr < 0):
            raise ExternalResultValidationError("SaTScan count, expected value and ratios must be nonnegative")
        if not significant:
            continue
        records.append(
            {
                "cluster_id": cluster_id,
                "cluster_rank": cluster_id,
                "centroid_location_id": tokens[idx["centroid_location_id"]],
                "centroid_x": _finite_number(tokens[idx["centroid_x"]], "centroid x"),
                "centroid_y": _finite_number(tokens[idx["centroid_y"]], "centroid y"),
                "radius": radius,
                "radius_max": radius_max,
                "start_date": start_date,
                "end_date": end_date,
                "n_locations": _integer(tokens[idx["n_locations"]], "location count"),
                "log_likelihood_ratio": statistic if has_llr else math.nan,
                "test_statistic": statistic,
                "test_statistic_type": statistic_type,
                "p_value_report": p_report,
                "p_value": p_value,
                "case_count": float(observed),
                "expected_count": expected if model == MODEL_DISCRETE_POISSON else math.nan,
                "conditional_expected": expected if model == MODEL_SPACE_TIME_PERMUTATION else math.nan,
                "observed_expected_ratio": observed_expected,
                "relative_risk": rr,
            }
        )
    columns = [
        "cluster_id", "cluster_rank", "centroid_location_id", "centroid_x", "centroid_y", "radius",
        "radius_max", "start_date", "end_date", "n_locations", "log_likelihood_ratio",
        "test_statistic", "test_statistic_type", "p_value_report", "p_value",
        "case_count", "expected_count", "conditional_expected", "observed_expected_ratio", "relative_risk",
    ]
    return pd.DataFrame(records, columns=columns).sort_values("cluster_id", kind="mergesort").reset_index(drop=True)


def parse_membership_file(path: str | Path, *, alpha: float) -> pd.DataFrame:
    file = Path(path)
    if not file.is_file():
        raise ExternalResultsRequired(f"Missing SaTScan membership result: {file}")
    _check_alpha(alpha)
    header, rows = _ascii_table(file, "membership")
    loc = _header_field(header, ("LOC_ID", "LOCATION"), "location_id")
    cluster = _header_field(header, ("CLUSTER",), "cluster_id")
    p_col = _header_field(header, ("P_VALUE",), "p_value")
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for tokens in rows:
        location_id = tokens[loc]
        cluster_id = _integer(tokens[cluster], "membership cluster id")
        if (location_id, cluster_id) in seen:
            raise ExternalResultValidationError("Duplicate SaTScan cluster/location membership")
        seen.add((location_id, cluster_id))
        p_report = tokens[p_col]
        p_value, significant = _reported_p(p_report, alpha, "membership p-value")
        if significant:
            records.append(
                {
                    "location_id": location_id,
                    "cluster_id": cluster_id,
                    "p_value_report": p_report,
                    "p_value": p_value,
                }
            )
    columns = ["location_id", "cluster_id", "p_value_report", "p_value"]
    return pd.DataFrame(records, columns=columns).sort_values(["cluster_id", "location_id"], kind="mergesort").reset_index(drop=True)


def _safe_child(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise ExternalResultValidationError(f"External run path escapes run directory: {relative}") from None
    return path


def _period_month(value: object, context: str) -> pd.Period:
    token = str(value).strip().replace("-", "/")
    parts = token.split("/")
    if len(parts) < 2:
        raise ExternalResultValidationError(f"{context} is not a parseable month: {value!r}")
    try:
        return pd.Period(year=int(parts[0]), month=int(parts[1]), freq="M")
    except (TypeError, ValueError) as exc:
        raise ExternalResultValidationError(f"{context} is not a valid month: {value!r}") from exc


def _governed_coordinates(path: Path) -> dict[str, tuple[Decimal, Decimal]]:
    coordinates: dict[str, tuple[Decimal, Decimal]] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        token = line.strip()
        if not token or token.startswith(("#", ";")):
            continue
        fields = token.split()
        if len(fields) != 3:
            raise ExternalResultValidationError("Malformed governed coordinate file")
        location, x_token, y_token = fields
        if location in coordinates:
            raise ExternalResultValidationError("Duplicate location ID in governed coordinate file")
        x = _native_decimal(x_token, "governed coordinate X")
        y = _native_decimal(y_token, "governed coordinate Y")
        if not all(math.isfinite(float(value)) for value in (x, y)):
            raise ExternalResultValidationError("Governed coordinates exceed the supported numeric range")
        coordinates[location] = (x, y)
    if not coordinates:
        raise ExternalResultValidationError("Governed coordinate file contains no locations")
    return coordinates


def _parameter_authority(prm: Path) -> dict[str, str]:
    parameters: dict[str, str] = {}
    for line in prm.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith(";") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        if key in parameters:
            raise ExternalResultValidationError(f"Duplicate SaTScan parameter authority for {key}")
        parameters[key] = _normalise_posix(value.strip())
    return parameters


def _parameter_value(prm: Path, key_name: str) -> str:
    parameters = _parameter_authority(prm)
    if key_name not in parameters:
        raise ExternalResultValidationError(
            f"SaTScan parameter file must contain exactly one {key_name} authority"
        )
    return parameters[key_name]


def _report_version(report_text: str) -> str:
    match = re.search(
        r"\bSaTScan\s+v([0-9]+(?:\.[0-9]+)+)\b",
        report_text,
        flags=re.IGNORECASE,
    )
    if not match:
        raise ExternalResultValidationError(
            "SaTScan report does not expose a parseable engine version"
        )
    return match.group(1)


def _validate_report_period(
    report_text: str, *, governed_start: pd.Period, governed_end: pd.Period
) -> None:
    matches = re.findall(
        r"^[ \t]*Study[ \t]+period[ \t.]*:[ \t]*(\S+)[ \t]+to[ \t]+(\S+)[ \t]*$",
        report_text,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if len(matches) != 1:
        raise ExternalResultValidationError(
            "SaTScan report does not expose a parseable study period"
        )
    native_start, native_end = matches[0]
    observed_start = _result_date(native_start, "reported study start").date()
    observed_end = _result_date(native_end, "reported study end").date()
    expected_start = governed_start.start_time.date()
    expected_end = governed_end.end_time.date()
    if observed_start != expected_start or observed_end != expected_end:
        raise ExternalResultValidationError(
            "SaTScan report study period does not match the governed run "
            f"(observed {observed_start} to {observed_end}, expected {expected_start} to {expected_end})"
        )


def _native_decimal(token: str, context: str) -> Decimal:
    try:
        value = Decimal(token)
    except InvalidOperation as exc:
        raise ExternalResultValidationError(f"{context} is not numeric") from exc
    if not value.is_finite():
        raise ExternalResultValidationError(f"{context} is not finite")
    if not re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", token):
        raise ExternalResultValidationError(f"{context} has an unsupported numeric format")
    return value


def _native_report_number(token: str, context: str) -> Decimal:
    if not re.fullmatch(r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][+-]?\d+)?", token):
        raise ExternalResultValidationError(f"{context} is not a supported nonnegative report number")
    return _native_decimal(token.replace(",", ""), context)


def _native_month(token: str, context: str) -> pd.Period:
    date = _result_date(token, context)
    return pd.Period(date, freq="M")


def _governed_monthly_cases(
    path: Path, locations: set[str], start: pd.Period, end: pd.Period,
) -> dict[tuple[str, int], int]:
    cells: dict[tuple[str, int], int] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith(("#", ";")):
            continue
        fields = line.split()
        if len(fields) != 3 or fields[0] not in locations or not re.fullmatch(r"[1-9]\d*", fields[1]):
            raise ExternalResultValidationError("Invalid location or case count in governed case file")
        location, count, token = fields
        month = _native_month(token, "governed case date")
        if not start <= month <= end:
            raise ExternalResultValidationError("Governed case date is outside the study period")
        key = (location, month.ordinal)
        cells[key] = cells.get(key, 0) + int(count)
    return cells


def _fixed_governed_population(
    path: Path, locations: set[str],
) -> dict[str, Decimal] | None:
    by_location: dict[str, dict[datetime, Decimal]] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith(("#", ";")):
            continue
        fields = line.split()
        if len(fields) != 3 or fields[0] not in locations:
            raise ExternalResultValidationError("Invalid location in governed population file")
        location, token, value = fields
        date = _result_date(token, "governed population date")
        exposure = _native_decimal(value, "governed population value")
        dated_values = by_location.setdefault(location, {})
        if exposure <= 0 or date in dated_values:
            raise ExternalResultValidationError("Invalid or duplicate exposure in governed population file")
        dated_values[date] = exposure
    if set(by_location) != locations:
        raise ExternalResultValidationError("Governed population locations do not match the coordinate roster")
    fixed = {location: set(values.values()) for location, values in by_location.items()}
    if any(len(values) != 1 for values in fixed.values()):
        return None
    return {location: next(iter(values)) for location, values in fixed.items()}


def _printed_interval(number: Decimal) -> tuple[Decimal, Decimal]:
    half_unit = Decimal("0.5").scaleb(number.as_tuple().exponent)
    return number - half_unit, number + half_unit


def _requires_full_native_family(parameters: Mapping[str, str], report_text: str) -> bool:
    ascii_options = (
        "PrintAsciiColumnHeaders", "MostLikelyClusterEachCentroidASCII", "CensusAreasReportedClustersASCII",
    )
    return all(parameters.get(option) == "y" for option in ascii_options) or bool(
        re.search(r"^[ \t]*(?:CLUSTERS DETECTED|PARAMETER SETTINGS)[ \t]*$", report_text, re.I | re.M)
    )


def _reconcile_native_report(
    report_text: str,
    *,
    parameters: Mapping[str, str],
    model_label: str,
    input_paths: Mapping[str, Path],
    population: Path | None,
    fixed_population: dict[str, Decimal] | None,
    require_full: bool,
    root: Path,
    governed_locations: set[str],
    governed_start: pd.Period,
    governed_end: pd.Period,
    total_cases: int,
    max_temporal_months: int,
) -> dict[str, Any]:
    settings: dict[str, str] = {}
    unavailable: list[str] = []
    parameter_sections = re.split(
        r"^[ \t]*PARAMETER SETTINGS[ \t]*$", report_text, flags=re.IGNORECASE | re.MULTILINE,
    )
    if len(parameter_sections) > 2:
        raise ExternalResultValidationError("SaTScan report has duplicate parameter sections")
    report_parameters = parameter_sections[-1] if len(parameter_sections) == 2 else ""

    def value(label: str, text: str = report_text) -> str | None:
        matches = re.findall(
            rf"^[ \t]*{re.escape(label)}[ \t.]*:[ \t]*([^\r\n]*)$",
            text,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        if not matches:
            unavailable.append(label)
            return None
        if len(matches) != 1 or not matches[0].strip():
            raise ExternalResultValidationError(f"SaTScan report has an empty or duplicate {label}")
        return matches[0].strip()

    def compare(label: str, observed: object, expected: object) -> None:
        if observed != expected:
            raise ExternalResultValidationError(
                f"SaTScan report {label} differs from governed values ({observed!r} versus {expected!r})"
            )
        settings[label] = str(observed)

    # Match each exposed setting to its governed PRM code or an explicit run authority.
    enumerated = {
        "Time Precision": ("PrecisionCaseTimes", "2", "Month"),
        "Coordinates": ("CoordinatesType", "0", "Cartesian"),
        "Type of Analysis": ("AnalysisType", "3", "Retrospective Space-Time"),
        "Probability Model": ("ModelType", "0" if model_label == "Discrete Poisson" else "2", model_label),
        "Scan For Areas With": ("ScanAreas", "1", "High Rates"),
        "Time Aggregation Units": ("TimeAggregationUnits", "2", "Month"),
        "Include Purely Temporal Clusters": ("IncludePurelyTemporal", "n", "No"),
        "Window Shape": ("SpatialWindowShapeType", "0", "Circular"),
        "Include Purely Spatial Clusters": ("IncludePurelySpatial", "n", "No"),
        "P-Value Reporting": ("PValueReportType", "1", "Standard Monte Carlo"),
        "Report Gumbel Based P-Values": ("ReportGumbel", "n", "No"),
        "Report Hierarchical Clusters": ("ReportHierarchicalClusters", "y", "Yes"),
        "Criteria for Reporting Secondary Clusters": (
            "CriteriaForReportingSecondaryClusters", "0", "No Geographical Overlap",
        ),
        "Restrict Reporting to Smaller Clusters": ("UseReportOnlySmallerClusters", "n", "No"),
        "Print ASCII Column Headers": ("PrintAsciiColumnHeaders", "y", "Yes"),
    }
    for label, (key, prm_code, expected) in enumerated.items():
        if key in parameters and parameters[key] != prm_code:
            raise ExternalResultValidationError(f"Unsupported governed SaTScan setting {key}")
        observed = value(label)
        if observed is not None:
            compare(label, observed.casefold(), expected.casefold())
    observed_rank = value("Report Monte Carlo Rank")
    if observed_rank is not None and "ReportClusterRank" in parameters:
        compare("Report Monte Carlo Rank", observed_rank.casefold(), {"y": "yes", "n": "no"}.get(parameters["ReportClusterRank"]))
    elif observed_rank is not None:
        unavailable.append("Report Monte Carlo Rank")

    if report_parameters:
        simulations_label = (
            "Simulated Log Likelihood Ratios" if model_label == "Discrete Poisson" else "Simulated Test Statistics"
        )
        for label, key, ascii_option in (
            ("Cluster Information", "MostLikelyClusterEachCentroidASCII", True),
            ("Stratified Cluster Information", "MostLikelyClusterCaseInfoEachCentroidASCII", True),
            ("Location Information", "CensusAreasReportedClustersASCII", True),
            ("Risk Estimates for Each Location", "IncludeRelativeRisksCensusAreasASCII", True),
            (simulations_label, "SaveSimLLRsASCII", True),
            ("HTML file for Google Map", "OutputGoogleMaps", False),
            ("KML file for Google Earth", "OutputGoogleEarthKML", False),
            ("Shapefile for GIS software", "OutputShapefiles", False),
        ):
            observed = value(label, report_parameters)
            if observed is not None and key in parameters:
                expected = {"y": "yes", "n": "no"}.get(parameters[key])
                if expected is not None and ascii_option:
                    expected += " (ascii), no (dbase)"
                compare(label, observed.casefold(), expected)
            elif observed is not None:
                unavailable.append(label)

    for label, path in (
        ("Case File", input_paths["case_path"]),
        ("Coordinates File", input_paths["coordinate_path"]),
        ("Population File", population),
        ("Main Results File", root / parameters["ResultsFile"]),
    ):
        observed = value(label)
        if observed is not None:
            # Strip the engine's working-directory prefix while preserving the governed suffix.
            normalised = _normalise_posix(observed)
            expected = path.relative_to(root).as_posix() if path is not None else ""
            observed_relative = normalised
            if expected and normalised.endswith("/" + expected):
                observed_relative = expected
            compare(label, observed_relative, expected)

    for label, month, key, boundary in (
        ("Start Date", governed_start, "StartDate", "start"),
        ("End Date", governed_end, "EndDate", "end"),
    ):
        expected = (month.start_time if boundary == "start" else month.end_time).date()
        if key in parameters and _result_date(parameters[key], f"parameter {key}").date() != expected:
            raise ExternalResultValidationError(f"SaTScan parameter {key} differs from the governed calendar")
        observed = value(label)
        if observed is not None:
            compare(label, _result_date(observed, f"report {label}").date(), expected)

    for label, key, suffix, authority in (
        ("Time Aggregation Length", "TimeAggregationLength", "", 1),
        ("Maximum Spatial Cluster Size", "MaxSpatialSizeInPopulationAtRisk", r" percent of population at risk", None),
        ("Minimum Temporal Cluster Size", "MinimumTemporalClusterSize", r" months?", 1),
        ("Maximum Temporal Cluster Size", "MaxTemporalSize", r" months?", max_temporal_months or None),
        ("Number of Replications", "MonteCarloReps", "", None),
        ("Number of locations", None, "", len(governed_locations)),
        ("Total number of cases", None, "", total_cases),
    ):
        expected = _native_report_number(parameters[key], f"parameter {key}") if key in parameters else authority
        if authority is not None and expected != authority:
            raise ExternalResultValidationError(f"SaTScan parameter {key} differs from governed values")
        observed = value(label)
        if observed is None:
            continue
        match = re.fullmatch(r"(\S+)" + suffix, observed, flags=re.IGNORECASE)
        if match is None:
            raise ExternalResultValidationError(f"SaTScan report {label} has an unsupported format")
        if expected is None:
            unavailable.append(label)
            continue
        compare(label, _native_report_number(match.group(1), f"report {label}"), expected)

    if "MaxTemporalSizeInterpretation" in parameters and parameters["MaxTemporalSizeInterpretation"] != "1":
        raise ExternalResultValidationError("Governed SaTScan maximum temporal window must use months")
    if parameters.get("ReportGiniClusters", "n") != "n":
        raise ExternalResultValidationError("Governed hierarchical SaTScan reporting does not use Gini selection")
    reported_population = value("Population, averaged over time")
    if population is not None:
        if reported_population is not None and fixed_population is not None:
            lower, upper = _printed_interval(_native_report_number(reported_population, "reported mean population"))
            if not lower <= sum(fixed_population.values()) <= upper:
                raise ExternalResultValidationError("SaTScan report average population differs from governed exposure")
            settings["Population, averaged over time"] = reported_population
        elif reported_population is not None:
            unavailable.append("Population, averaged over time")
    elif reported_population is not None:
        raise ExternalResultValidationError("SaTScan STP report unexpectedly contains population totals")
    else:
        unavailable.remove("Population, averaged over time")

    if population is None and "Population File" in unavailable:
        unavailable.remove("Population File")
    if re.search(r"^[ \t]*SUMMARY OF DATA[ \t]*$", report_text, flags=re.I | re.M):
        missing = {"Number of locations", "Total number of cases"} - settings.keys()
        if missing:
            raise ExternalResultValidationError("SaTScan summary is missing " + ", ".join(sorted(missing)))
    if require_full:
        required = {
            "Number of locations", "Total number of cases", "Case File", "Coordinates File", "Main Results File",
            "Start Date", "End Date", "Time Precision", "Coordinates", "Type of Analysis", "Probability Model",
            "Scan For Areas With", "Time Aggregation Units", "Time Aggregation Length",
            "Window Shape", "Maximum Spatial Cluster Size", "Minimum Temporal Cluster Size",
            "Maximum Temporal Cluster Size", "Number of Replications", "P-Value Reporting",
            "Report Gumbel Based P-Values", "Report Hierarchical Clusters",
            "Criteria for Reporting Secondary Clusters", "Print ASCII Column Headers",
            "Cluster Information", "Location Information",
        }
        if population is not None:
            required.update(("Population File", "Population, averaged over time"))
        missing = required - settings.keys()
        if missing:
            raise ExternalResultValidationError("SaTScan native parameter or summary section is missing "
                                                + ", ".join(sorted(missing)))
        if not re.search(r"^[ \t]*SUMMARY OF DATA[ \t]*$", report_text, flags=re.I | re.M):
            raise ExternalResultValidationError("SaTScan native report has no summary section")
    else:
        unavailable.append("Native cluster report, GIS effect fields, and model reconstruction unavailable in compact profile")
    return {"report_fields_verified": settings, "report_fields_unavailable": unavailable}


def _native_cluster_blocks(report_text: str) -> dict[int, str]:
    section = re.search(
        r"^[ \t]*CLUSTERS DETECTED[ \t]*$([\s\S]*?)(?=^[ \t]*PARAMETER SETTINGS[ \t]*$)",
        report_text, re.I | re.M,
    )
    no_clusters = r"^[ \t]*No clusters (?:were found(?: by this analysis)?|reported)\.[ \t]*$"
    if section is None:
        beginning = re.split(r"^[ \t]*PARAMETER SETTINGS[ \t]*$", report_text, maxsplit=1, flags=re.I | re.M)[0]
        if re.search(no_clusters, beginning, re.I | re.M):
            return {}
        raise ExternalResultValidationError("SaTScan native report has no cluster section")
    parts = re.split(
        r"^[ \t]*(\d+)\.[ \t]*Location IDs included[ \t.]*:[ \t]*", section.group(1), flags=re.I | re.M,
    )
    blocks: dict[int, str] = {}
    for i in range(1, len(parts), 2):
        cluster = int(parts[i])
        if cluster in blocks:
            raise ExternalResultValidationError("SaTScan native report has duplicate cluster IDs")
        blocks[cluster] = parts[i + 1]
    if not blocks and not re.search(no_clusters, section.group(1), re.I | re.M):
        raise ExternalResultValidationError("SaTScan native report lists no clusters without an explicit engine finding")
    return blocks


def _native_cluster_field(block: str, label: str, context: str) -> str:
    matches = re.findall(rf"^[ \t]*{re.escape(label)}[ \t.]*:[ \t]*(\S[^\r\n]*)$", block, re.I | re.M)
    if len(matches) != 1:
        raise ExternalResultValidationError(f"{context} must contain exactly one report field {label}")
    return matches[0].strip()


def _require_native_rounding(
    printed: Decimal, calculated: Decimal, field: str, context: str, *,
    engine_tolerance: Decimal = Decimal(0),
) -> None:
    lower, upper = _printed_interval(printed)
    if not lower - engine_tolerance <= calculated <= upper + engine_tolerance:
        raise ExternalResultValidationError(
            f"{context} {field} differs from governed reconstruction "
            f"(reported {printed}, calculated {calculated:.12g})"
        )


def _reconcile_native_geometry(
    values: Mapping[str, str],
    members: set[str],
    governed_coordinates: Mapping[str, tuple[Decimal, Decimal]],
    coordinates: np.ndarray,
    location_indices: Mapping[str, int],
    context: str,
) -> None:
    centre = values["LOC_ID"]
    if centre not in members:
        raise ExternalResultValidationError(f"{context} governed centre is not among the window members")
    for axis, authority in zip(("X", "Y"), governed_coordinates[centre], strict=True):
        printed = _native_decimal(values[axis], f"{context} {axis}")
        # SaTScan prints Cartesian centres with six significant digits, even
        # when general formatting suppresses trailing zeroes.
        half_unit = Decimal("0.5").scaleb(authority.adjusted() - 5) if authority else Decimal(0)
        if abs(printed - authority) > half_unit:
            raise ExternalResultValidationError(f"{context} reported {axis} differs from the governed centre")

    member_indices = [location_indices[location] for location in members]
    x_offset, y_offset = (coordinates - coordinates[location_indices[centre]]).T
    distances = np.hypot(x_offset, y_offset)
    radius = float(distances[member_indices].max())
    span = float(pdist(coordinates[member_indices]).max(initial=0))
    # Distances are printed to hundredths of the governed Cartesian unit.
    # Reserve only a tiny extra tolerance for floating-point distance arithmetic.
    distance_tolerance = Decimal("1e-8")
    for field, measured in (("RADIUS", radius), ("SPAN", span)):
        printed = _native_decimal(values[field], f"{context} {field}")
        precision = min(printed.as_tuple().exponent, -2)
        printed = printed.quantize(Decimal(1).scaleb(precision))
        _require_native_rounding(
            printed, Decimal(str(measured)), field, context, engine_tolerance=distance_tolerance,
        )
    outsiders = np.ones(len(coordinates), dtype=bool)
    outsiders[member_indices] = False
    # The unrounded farthest member fixes the circle. A printed RADIUS can
    # round up, so it cannot decide whether a nearby outsider lies inside.
    if np.any(distances[outsiders] <= radius + float(distance_tolerance)):
        raise ExternalResultValidationError(f"{context} omits a governed location inside its circular window")


def _reconcile_native_clusters(
    report_text: str,
    clusters_path: Path,
    membership_path: Path,
    *,
    model: str,
    governed_coordinates: Mapping[str, tuple[Decimal, Decimal]],
    governed_start: pd.Period,
    governed_end: pd.Period,
    max_spatial_percent: Decimal,
    max_temporal_months: int,
    monthly_cases: Mapping[tuple[str, int], int],
    population: Mapping[str, Decimal] | None,
) -> None:
    is_poisson = model == MODEL_DISCRETE_POISSON
    governed_locations = governed_coordinates.keys()
    report_blocks = _native_cluster_blocks(report_text)
    column_header, column_rows = _ascii_table(clusters_path, "native cluster output")
    gis_header, gis_rows = _ascii_table(membership_path, "native membership output")
    statistic = "LLR" if is_poisson else "TEST_STAT"
    report_fields = {
        "OBSERVED": "Number of cases", "EXPECTED": "Expected cases", "ODE": "Observed / expected",
        statistic: "Log likelihood ratio" if is_poisson else "Test statistic",
    }
    gis_fields = {"OBSERVED": "CLU_OBS", "EXPECTED": "CLU_EXP", "ODE": "CLU_ODE"}
    if is_poisson:
        report_fields.update({"REL_RISK": "Relative risk", "POPULATION": "Population"})
        gis_fields.update({"REL_RISK": "CLU_RR", "POPULATION": "CLU_POP"})
    required_columns = set(report_fields) | {
        "CLUSTER", "LOC_ID", "X", "Y", "RADIUS", "SPAN", "START_DATE", "END_DATE", "NUMBER_LOC", "P_VALUE",
    }
    required_gis = set(gis_fields.values()) | {"CLUSTER", "LOC_ID", "P_VALUE"}
    if required_columns - column_header.keys() or required_gis - gis_header.keys():
        raise ExternalResultValidationError("SaTScan native ASCII outputs lack required cluster-effect fields")
    if not is_poisson and {"CLU_RR", "CLU_POP"} & gis_header.keys():
        raise ExternalResultValidationError("SaTScan STP membership contains unsupported population effects")
    columns = {
        _integer(row[column_header["CLUSTER"]], "native cluster ID"): dict(zip(column_header, row))
        for row in column_rows
    }
    memberships: dict[int, dict[str, list[str]]] = {}
    for row in gis_rows:
        cluster = _integer(row[gis_header["CLUSTER"]], "native membership cluster ID")
        memberships.setdefault(cluster, {})[row[gis_header["LOC_ID"]]] = row
    if any(set(columns) != ids for ids in (set(report_blocks), set(memberships))):
        raise ExternalResultValidationError("SaTScan native report and ASCII outputs disagree on cluster IDs")
    if is_poisson and population is None:
        raise ExternalResultValidationError("SaTScan native Poisson reconciliation requires fixed governed exposure")

    location_indices = {location: i for i, location in enumerate(governed_coordinates)}
    coordinate_array = np.array(tuple(governed_coordinates.values()), dtype=float)
    location_cases: Counter[str] = Counter()
    time_cases: Counter[int] = Counter()
    for (location, month), count in monthly_cases.items():
        location_cases[location] += count
        time_cases[month] += count
    total_cases = sum(location_cases.values())
    study_days = (governed_end.end_time.date() - governed_start.start_time.date()).days + 1
    # Native Poisson effects use population inputs rounded to binary32. The
    # independent reconstruction sums those governed values at higher precision
    # so the LLR can be checked at its six-decimal output precision.
    if population is not None:
        population = {
            location: Decimal.from_float(float(np.float32(float(value))))
            for location, value in population.items()
        }
    total_population = sum(population.values()) if population is not None else Decimal(0)

    for cluster, values in columns.items():
        context = f"SaTScan native cluster {cluster}"
        block = report_blocks[cluster]
        coordinates = re.search(
            r"^[ \t]*Coordinates / radius[ \t.]*:[ \t]*\(([^,]+),([^\)]+)\)[ \t]*/[ \t]*(\S+)",
            block, re.I | re.M,
        )
        if coordinates is None:
            raise ExternalResultValidationError(f"{context} report is missing centroid/radius")
        for key, token in zip(("X", "Y", "RADIUS"), coordinates.groups(), strict=True):
            if _native_decimal(token.strip(), f"{context} reported {key}") != _native_decimal(values[key], key):
                raise ExternalResultValidationError(f"{context} report and cluster output disagree on {key}")
        if _native_report_number(_native_cluster_field(block, "Span", context), f"{context} report span") != (
            _native_decimal(values["SPAN"], f"{context} cluster output span")
        ):
            raise ExternalResultValidationError(f"{context} report and cluster output disagree on span")
        member_list = [
            token.strip() for token in block[:coordinates.start()].replace("\n", " ").strip().split(",")
        ]
        members = set(member_list)
        gis_members = memberships[cluster]
        if (
            len(members) != len(member_list) or members != set(gis_members) or not members <= governed_locations
            or values["LOC_ID"] not in governed_locations or len(members) != _integer(values["NUMBER_LOC"], "member count")
        ):
            raise ExternalResultValidationError(f"{context} report and membership locations disagree")
        _reconcile_native_geometry(values, members, governed_coordinates, coordinate_array, location_indices, context)

        start_date = _result_date(values["START_DATE"], f"{context} start")
        end_date = _result_date(values["END_DATE"], f"{context} end")
        dates = re.fullmatch(r"(\S+) to (\S+)", _native_cluster_field(block, "Time frame", context))
        if dates is None or tuple(_result_date(date, f"{context} report date") for date in dates.groups()) != (
            start_date, end_date,
        ):
            raise ExternalResultValidationError(f"{context} report and cluster output disagree on time frame")
        start, end = pd.Period(start_date, freq="M"), pd.Period(end_date, freq="M")
        months = range(start.ordinal, end.ordinal + 1)
        if (
            start < governed_start or end > governed_end
            or start_date != start.start_time or end_date != end.end_time.normalize()
            or (max_temporal_months > 0 and len(months) > max_temporal_months)
        ):
            raise ExternalResultValidationError(f"{context} is outside the governed monthly window bounds")

        p_value = _p_signature(values["P_VALUE"])
        if p_value != _p_signature(_native_cluster_field(block, "P-value", context)):
            raise ExternalResultValidationError(f"{context} report and cluster output disagree on p-value")
        effects = {key: _native_decimal(values[key], f"{context} {key}") for key in report_fields}
        for key, label in report_fields.items():
            reported = _native_report_number(_native_cluster_field(block, label, context), f"{context} {label}")
            if key == "POPULATION":
                if effects[key].as_tuple().exponent > -2 or reported.as_tuple().exponent > 0:
                    raise ExternalResultValidationError(f"{context} POPULATION omits native decimal precision")
                _require_native_rounding(reported, effects[key], key, context + " report")
            elif effects[key] != reported:
                raise ExternalResultValidationError(f"{context} report and cluster output disagree on {key}")
        for row in gis_members.values():
            if p_value != _p_signature(row[gis_header["P_VALUE"]]):
                raise ExternalResultValidationError(f"{context} membership output disagrees on p-value")
            for key, gis_key in gis_fields.items():
                if effects[key] != _native_decimal(row[gis_header[gis_key]], f"{context} {gis_key}"):
                    raise ExternalResultValidationError(f"{context} membership and cluster output disagree on {key}")

        observed = sum(monthly_cases.get((location, month), 0) for location in members for month in months)
        if effects["OBSERVED"] != observed:
            raise ExternalResultValidationError(f"{context} observed cases differ from the governed case window")
        if population is not None:
            exposure = sum(population[location] for location in members)
            if 100 * exposure > max_spatial_percent * total_population:
                raise ExternalResultValidationError(f"{context} exceeds the governed spatial-window exposure maximum")
            window_days = (end_date - start_date).days + 1
            expected = Decimal(total_cases) * exposure * window_days / (total_population * study_days)
            _require_native_rounding(
                effects["POPULATION"], exposure, "POPULATION", context, engine_tolerance=Decimal("1e-8"),
            )
        else:
            spatial_cases = sum(location_cases[location] for location in members)
            if 100 * spatial_cases > max_spatial_percent * total_cases:
                raise ExternalResultValidationError(f"{context} exceeds the governed spatial-window case maximum")
            expected = Decimal(spatial_cases) * sum(time_cases[month] for month in months) / total_cases
        if not 0 < expected < total_cases or observed <= expected:
            raise ExternalResultValidationError(f"{context} does not represent a governed high-rate window")
        ratio = observed / expected
        outside_cases = total_cases - observed
        outside_expected = total_cases - expected
        calculated = {"EXPECTED": expected, "ODE": ratio}
        if is_poisson:
            if outside_cases == 0:
                raise ExternalResultValidationError(f"{context} has undefined finite Poisson relative risk")
            calculated["REL_RISK"] = ratio / (outside_cases / outside_expected)
        calculated[statistic] = Decimal(str(
            observed * math.log(float(ratio))
            + (outside_cases * math.log(float(outside_cases / outside_expected)) if outside_cases else 0)
        ))
        for key, value in calculated.items():
            width = 6 if key == statistic else 2
            if effects[key].as_tuple().exponent > -width:
                raise ExternalResultValidationError(f"{context} {key} omits native decimal precision")
            _require_native_rounding(effects[key], value, key, context, engine_tolerance=Decimal("1e-8"))


def _reconcile_simulation_maxima(
    path: Path, clusters_path: Path, clusters: pd.DataFrame, parameters: Mapping[str, str],
) -> dict[str, Any]:
    if not path.is_file():
        return {"status": "not_supplied"}
    header, rows = _ascii_table(path, "simulation maxima")
    if tuple(header) not in (("LLR",), ("TEST_STAT",), ("TST_STAT",)):
        raise ExternalResultValidationError("SaTScan simulation maxima has an unsupported ASCII header")
    maxima = [_native_decimal(row[0], "simulation maximum") for row in rows]
    replications = parameters.get("MonteCarloReps")
    if replications is not None and _native_report_number(replications, "parameter MonteCarloReps") != len(maxima):
        raise ExternalResultValidationError("SaTScan simulation maxima count differs from governed replications")
    verified = {"sha256": sha256_file(path), "maxima": len(maxima)}
    if replications is None or parameters.get("PValueReportType") != "1" or parameters.get("ReportGumbel") != "n":
        return {**verified, "status": "standard_monte_carlo_authority_unavailable"}

    # Printed statistics may be tied only because they were rounded before export.
    cluster_header, cluster_rows = _ascii_table(clusters_path, "cluster")
    statistic_index = _header_field(cluster_header, ("LLR", "TEST_STAT"), "statistic")
    cluster_index = cluster_header["CLUSTER"]
    p_index = cluster_header["P_VALUE"]
    max_intervals = [_printed_interval(number) for number in maxima]
    ambiguous = 0
    for row in cluster_rows:
        cluster_id = _integer(row[cluster_index], "cluster id")
        threshold_low, threshold_high = _printed_interval(_native_decimal(row[statistic_index], "cluster statistic"))
        denominator = Decimal(len(maxima) + 1)
        lower = Decimal(1 + sum(low >= threshold_high for low, _ in max_intervals)) / denominator
        upper = Decimal(1 + sum(high >= threshold_low for _, high in max_intervals)) / denominator
        qualifier, reported = _p_signature(row[p_index])
        if qualifier:
            compatible = lower < reported if qualifier == "<" else lower <= reported
        else:
            reported_low, reported_high = _printed_interval(reported)
            compatible = lower <= reported_high and reported_low <= upper
        if not compatible:
            raise ExternalResultValidationError(
                f"SaTScan cluster {cluster_id} p-value differs from the native simulation maxima rank"
            )
        ambiguous += int(lower != upper)
    return {
        **verified,
        "status": "verified_with_printed_precision",
        "clusters_checked": len(cluster_rows),
        "significant_clusters_checked": len(clusters),
        "clusters_with_precision_ambiguous_rank": ambiguous,
    }


def validate_external_results(
    run_row: Mapping[str, Any], *, run_dir: str | Path, alpha: float,
    _observed_execution_in_progress: bool = False,
    enforce_freshness: bool = True,
) -> ParsedSaTScanResults:
    """Validate a genuine SaTScan result family against its current run authority.

    The .prm ResultsFile entry is the naming authority.  The core family is exactly
    the extensionless ResultsFile plus ``.col.txt`` and ``.gis.txt``. Native settings
    and summary fields are required for the governed ASCII result profile. Pass
    ``enforce_freshness=False`` only for separately authenticated portable evidence.
    """

    root = Path(run_dir).resolve()
    prm = _safe_child(root, str(run_row["prm_path"]))
    if not prm.is_file() or sha256_file(prm) != str(run_row["prm_sha256"]):
        raise ExternalResultValidationError("Parameter-file authority does not match run registry")
    parameters = _parameter_authority(prm)

    results_prefix = _normalise_posix(str(run_row.get("results_prefix", "")))
    if not results_prefix:
        raise ExternalResultValidationError("Run registry is missing the governed ResultsFile prefix")
    if not _observed_execution_in_progress and _safe_child(root, results_prefix + ".execution.lock").exists():
        raise ExternalResultValidationError("Observed execution is still in progress or interrupted; preserve and use a fresh run")
    if parameters.get("ResultsFile") != results_prefix:
        raise ExternalResultValidationError("Parameter ResultsFile authority differs from the governed result prefix")
    if run_row.get("required_report_path") not in (None, "", results_prefix):
        raise ExternalResultValidationError("Run registry report path is inconsistent with ResultsFile authority")

    input_paths: dict[str, Path] = {}
    for path_key, hash_key, prm_key in (
        ("case_path", "case_sha256", "CaseFile"),
        ("coordinate_path", "coordinate_sha256", "CoordinatesFile"),
    ):
        path = _safe_child(root, str(run_row[path_key]))
        if not path.is_file() or sha256_file(path) != str(run_row[hash_key]):
            raise ExternalResultValidationError(f"Input authority mismatch for {path_key}")
        if prm_key in parameters and parameters[prm_key] != _normalise_posix(str(run_row[path_key])):
            raise ExternalResultValidationError(f"Parameter {prm_key} authority differs from run registry")
        input_paths[path_key] = path

    population_path = str(run_row.get("population_path", "") or "")
    population: Path | None = None
    model = str(run_row["model"])
    prm_population = _parameter_value(prm, "PopulationFile")
    if population_path:
        population = _safe_child(root, population_path)
        if not population.is_file() or sha256_file(population) != str(run_row.get("population_sha256", "")):
            raise ExternalResultValidationError("Input authority mismatch for population_path")
        if prm_population != _normalise_posix(population_path):
            raise ExternalResultValidationError("Parameter population authority differs from run registry")
    elif model == MODEL_DISCRETE_POISSON:
        raise ExternalResultValidationError("Discrete-Poisson run registry is missing population authority")
    elif prm_population:
        raise ExternalResultValidationError("STP parameter file contains prohibited population authority")

    if model == MODEL_SPACE_TIME_PERMUTATION:
        if population_path or str(run_row.get("population_sha256", "") or ""):
            raise ExternalResultValidationError("STP run registry contains prohibited exposure authority")
        unexpected_pop = prm.with_suffix(".pop")
        if unexpected_pop.exists():
            raise ExternalResultValidationError("STP run contains an unexpected population file")

    report = _safe_child(root, results_prefix)
    clusters_path = _safe_child(root, results_prefix + ".col.txt")
    membership_path = _safe_child(root, results_prefix + ".gis.txt")
    maxima_path = _safe_child(root, results_prefix + ".llr.txt")
    expected_cluster = results_prefix + ".col.txt"
    expected_membership = results_prefix + ".gis.txt"
    if run_row.get("required_cluster_path") not in (None, "", expected_cluster):
        raise ExternalResultValidationError("Run registry cluster path is inconsistent with ResultsFile authority")
    if run_row.get("required_membership_path") not in (None, "", expected_membership):
        raise ExternalResultValidationError("Run registry membership path is inconsistent with ResultsFile authority")

    missing = [
        p.relative_to(root).as_posix()
        for p in (report, clusters_path, membership_path)
        if not p.is_file()
    ]
    if missing:
        raise ExternalResultsRequired("SaTScan external results are required; missing: " + ", ".join(missing))

    if enforce_freshness:
        authority_mtime_ns = max(
            p.stat().st_mtime_ns
            for p in (prm, input_paths["case_path"], input_paths["coordinate_path"], population)
            if p is not None
        )
        for path in (report, clusters_path, membership_path, maxima_path):
            if path.is_file() and path.stat().st_mtime_ns < authority_mtime_ns:
                raise ExternalResultValidationError(
                    "SaTScan output is stale relative to the current parameter/input authority"
                )

    if report.stat().st_size == 0:
        raise ExternalResultValidationError("SaTScan main report is empty")
    report_text = report.read_text(encoding="utf-8", errors="ignore")
    _assert_no_fatal_execution_diagnostic(report_text, context="SaTScan main report")
    if "Program completed" not in report_text:
        raise ExternalResultValidationError("SaTScan report does not record successful completion")
    observed_version = _report_version(report_text)
    expected_version = str(run_row["engine_version_authority"])
    if observed_version != expected_version:
        raise ExternalResultValidationError(
            f"SaTScan version mismatch: observed={observed_version}, expected={expected_version}"
        )
    expected_label = (
        "Space-Time Permutation" if model == MODEL_SPACE_TIME_PERMUTATION else "Discrete Poisson"
    )
    require_full_native = _requires_full_native_family(parameters, report_text)
    model_statements = re.findall(r"^[ \t]*using the ([^\r\n]+?) model\.[ \t]*$", report_text, flags=re.I | re.M)
    if (
        expected_label.casefold() not in report_text.casefold()
        or any(statement.casefold() != expected_label.casefold() for statement in model_statements)
        or (require_full_native and len(model_statements) != 1)
    ):
        raise ExternalResultValidationError("SaTScan report model identity does not match the run authority")

    governed_start = _period_month(run_row["temporal_start"], "governed temporal start")
    governed_end = _period_month(run_row["temporal_end"], "governed temporal end")
    _validate_report_period(report_text, governed_start=governed_start, governed_end=governed_end)

    clusters = parse_cluster_file(clusters_path, alpha=alpha, model=model)
    membership = parse_membership_file(membership_path, alpha=alpha)
    if not membership.empty and not set(membership["cluster_id"]).issubset(set(clusters["cluster_id"])):
        raise ExternalResultValidationError("Cluster membership references a non-significant or absent cluster")
    if not clusters.empty:
        cluster_p = {
            int(row.cluster_id): _p_signature(str(row.p_value_report))
            for row in clusters.itertuples(index=False)
        }
        for row in membership.itertuples(index=False):
            if _p_signature(str(row.p_value_report)) != cluster_p[int(row.cluster_id)]:
                raise ExternalResultValidationError(
                    "Cluster membership p-value disagrees with the cluster output"
                )
        counts = membership.groupby("cluster_id", observed=True)["location_id"].nunique()
        for row in clusters.itertuples(index=False):
            if int(counts.get(row.cluster_id, 0)) != int(row.n_locations):
                raise ExternalResultValidationError("Cluster membership count does not match cluster output")

    governed_coordinates = _governed_coordinates(input_paths["coordinate_path"])
    governed_locations = set(governed_coordinates)
    if not set(membership["location_id"].astype(str)).issubset(governed_locations):
        raise ExternalResultValidationError("Cluster membership contains a location outside the governed run")
    if not set(clusters["centroid_location_id"].astype(str)).issubset(governed_locations):
        raise ExternalResultValidationError("Cluster centroid contains a location outside the governed run")

    max_temporal_months = int(run_row.get("max_temporal_months", 0) or 0)
    monthly_cases = _governed_monthly_cases(
        input_paths["case_path"], governed_locations, governed_start, governed_end,
    )
    total_cases = sum(monthly_cases.values())
    fixed_population = _fixed_governed_population(population, governed_locations) if population is not None else None
    native_reconciliation = _reconcile_native_report(
        report_text,
        parameters=parameters,
        model_label=expected_label,
        input_paths=input_paths,
        population=population,
        fixed_population=fixed_population,
        require_full=require_full_native,
        root=root,
        governed_locations=governed_locations,
        governed_start=governed_start,
        governed_end=governed_end,
        total_cases=total_cases,
        max_temporal_months=max_temporal_months,
    )
    locations_by_cluster = membership.groupby("cluster_id", observed=True)["location_id"].agg(set)
    for row in clusters.itertuples(index=False):
        start = _period_month(row.start_date, "cluster start")
        end = _period_month(row.end_date, "cluster end")
        if start < governed_start or end > governed_end or end < start:
            raise ExternalResultValidationError("SaTScan cluster interval lies outside the governed period")
        if max_temporal_months > 0 and int(end.ordinal - start.ordinal + 1) > max_temporal_months:
            raise ExternalResultValidationError("SaTScan cluster exceeds the governed temporal-window maximum")
        if "Time Precision" in native_reconciliation["report_fields_verified"] and (
            _result_date(row.start_date, "cluster start") != start.start_time
            or _result_date(row.end_date, "cluster end") != end.end_time.normalize()
        ):
            raise ExternalResultValidationError("SaTScan cluster dates do not span whole governed months")
        window_cases = sum(
            monthly_cases.get((location, month), 0)
            for location in locations_by_cluster[row.cluster_id]
            for month in range(start.ordinal, end.ordinal + 1)
        )
        if row.case_count != window_cases:
            raise ExternalResultValidationError(
                f"SaTScan cluster {row.cluster_id} observed cases differ from the governed case window "
                f"({row.case_count} versus {window_cases})"
            )
    if require_full_native:
        max_spatial_percent = _native_decimal(
            parameters["MaxSpatialSizeInPopulationAtRisk"], "governed maximum spatial window percent",
        )
        if not 0 < max_spatial_percent <= 100:
            raise ExternalResultValidationError("Governed maximum spatial window percent must lie in (0, 100]")
        for option in ("UseGridFile", "UseMaxCirclePopulationFileOption", "UseDistanceFromCenterOption"):
            if parameters.get(option, "n") != "n":
                raise ExternalResultValidationError(f"Unsupported governed SaTScan setting {option}")
        _reconcile_native_clusters(
            report_text, clusters_path, membership_path, model=model, governed_coordinates=governed_coordinates,
            governed_start=governed_start, governed_end=governed_end,
            max_spatial_percent=max_spatial_percent, max_temporal_months=max_temporal_months,
            monthly_cases=monthly_cases, population=fixed_population,
        )

    native_reconciliation.update({
        "governed_location_count": len(governed_locations),
        "governed_total_cases": total_cases,
        "significant_cluster_case_windows_verified": len(clusters),
        "simulation_maxima": _reconcile_simulation_maxima(maxima_path, clusters_path, clusters, parameters),
    })

    if model == MODEL_SPACE_TIME_PERMUTATION and not clusters.empty:
        clusters = clusters.copy()
        clusters["relative_risk"] = np.nan

    validation_metadata = {
        "scenario_id": str(run_row["scenario_id"]),
        "product_identity": str(run_row["product"]),
        "model_identity": model,
        "temporal_start": str(run_row["temporal_start"]),
        "temporal_end": str(run_row["temporal_end"]),
        "executable_path": "",
        "executable_version": observed_version,
        "executable_sha256": "",
        "parameter_sha256": sha256_file(prm),
        "case_sha256": sha256_file(input_paths["case_path"]),
        "coordinate_sha256": sha256_file(input_paths["coordinate_path"]),
        "population_sha256": "" if population is None else sha256_file(population),
        "report_sha256": sha256_file(report),
        "cluster_sha256": sha256_file(clusters_path),
        "membership_sha256": sha256_file(membership_path),
        "native_reconciliation": native_reconciliation,
        "validation_basis": "direct_resultsfile_validation_without_external_provenance_sidecar",
        "external_provenance_sidecar_required": False,
    }
    receipt = _safe_child(root, results_prefix + ".execution.json")
    if _safe_child(root, results_prefix + ".execution.failed.json").exists():
        raise ExternalResultValidationError("A failed observed execution is recorded; preserve it and use a fresh run")
    if receipt.exists():
        # Execution receipts are optional for manual deliveries.
        # Once present, a malformed or mismatched receipt cannot be ignored.
        from .execution_evidence import validate_satscan_execution_receipt
        evidence = validate_satscan_execution_receipt(receipt, run_row=run_row, run_dir=root)
        validation_metadata.update({
            "executable_path": evidence["executable"]["path"],
            "executable_version": evidence["executable"]["version"],
            "executable_sha256": evidence["executable"]["sha256"],
            "execution_receipt_path": receipt.relative_to(root).as_posix(),
            "execution_receipt_sha256": sha256_file(receipt),
            "validation_basis": "direct_resultsfile_validation_with_prospective_execution_receipt",
        })
    return ParsedSaTScanResults(
        scenario_id=str(run_row["scenario_id"]),
        model=model,
        clusters=clusters,
        membership=membership,
        provenance=validation_metadata,
    )


__all__ = [
    "MODEL_DISCRETE_POISSON", "MODEL_SPACE_TIME_PERMUTATION", "REPORTING_HIERARCHICAL",
    "SaTScanIOError", "ExternalResultsRequired",
    "ExternalResultValidationError", "ExecutableProvenance", "ParsedSaTScanResults",
    "sha256_file", "sha256_text", "coordinate_text", "case_text", "population_text",
    "generate_parameter_file", "find_satscan_executable", "executable_provenance", "run_satscan",
    "parse_cluster_file", "parse_membership_file", "validate_external_results",
]
