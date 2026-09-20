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
from calendar import monthrange
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

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
    for name in ("SaTScanBatch", "SaTScan", "satscan64", "satscan"):
        found = shutil.which(name)
        if found:
            return str(Path(found).resolve())
    return None


def executable_provenance(path: str | Path) -> ExecutableProvenance:
    executable = Path(path).resolve()
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise SaTScanIOError(f"SaTScan executable is not executable: {executable}")
    version = "UNKNOWN"
    for args in ([str(executable), "--version"], [str(executable), "-v"]):
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=10, check=False)
        except (OSError, subprocess.SubprocessError):
            continue
        text = (proc.stdout + "\n" + proc.stderr).strip()
        match = re.search(r"SaTScan[^\n]*?v(?:ersion)?\s*([0-9]+(?:\.[0-9]+)+)", text, re.I)
        if match:
            version = match.group(1)
            break
        if text and len(text) < 200:
            version = text.splitlines()[0].strip()
            break
    return ExecutableProvenance(str(executable), sha256_file(executable), version)


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
    proc = subprocess.run(
        [executable.path, str(prm)],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    completed = datetime.now(timezone.utc).isoformat()
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
        parsed = validate_external_results(run_row, run_dir=root, alpha=float(alpha))
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
        "external_provenance_sidecar_written": False,
    }

def _tokenise_ascii(path: Path) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        token = line.strip()
        if not token or token.startswith(("#", ";")):
            continue
        fields = re.split(r"\s+", token)
        if fields and re.fullmatch(r"\d+", fields[0]):
            rows.append(fields)
    return rows


def _finite_number(token: str, context: str) -> float:
    number = pd.to_numeric(str(token).lstrip("<"), errors="coerce")
    if pd.isna(number) or not np.isfinite(float(number)):
        raise ExternalResultValidationError(f"{context} is not finite numeric data")
    return float(number)


def parse_cluster_file(path: str | Path, *, alpha: float) -> pd.DataFrame:
    file = Path(path)
    if not file.is_file():
        raise ExternalResultsRequired(f"Missing SaTScan cluster result: {file}")
    records: list[dict[str, Any]] = []
    for tokens in _tokenise_ascii(file):
        if len(tokens) < 11:
            raise ExternalResultValidationError("Malformed SaTScan cluster row: fewer than 11 fields")
        p_report = tokens[10]
        p_value = _finite_number(p_report, "cluster p-value")
        if p_value > alpha:
            continue
        observed = _finite_number(tokens[11], "observed cases") if len(tokens) > 11 else math.nan
        expected = _finite_number(tokens[12], "expected cases") if len(tokens) > 12 else math.nan
        rr = _finite_number(tokens[13], "relative risk") if len(tokens) > 13 else math.nan
        records.append(
            {
                "cluster_id": int(tokens[0]),
                "cluster_rank": int(tokens[0]),
                "centroid_location_id": str(tokens[1]),
                "centroid_x": _finite_number(tokens[2], "centroid x"),
                "centroid_y": _finite_number(tokens[3], "centroid y"),
                "radius": _finite_number(tokens[4], "radius"),
                "radius_max": _finite_number(tokens[5], "maximum radius"),
                "start_date": str(tokens[6]),
                "end_date": str(tokens[7]),
                "n_locations": int(_finite_number(tokens[8], "location count")),
                "likelihood_ratio": _finite_number(tokens[9], "likelihood ratio"),
                "p_value_report": p_report,
                "p_value": p_value,
                "case_count": observed,
                "expected_count": expected,
                "relative_risk": rr,
            }
        )
    columns = [
        "cluster_id", "cluster_rank", "centroid_location_id", "centroid_x", "centroid_y", "radius",
        "radius_max", "start_date", "end_date", "n_locations", "likelihood_ratio",
        "p_value_report", "p_value", "case_count", "expected_count", "relative_risk",
    ]
    return pd.DataFrame(records, columns=columns).sort_values("cluster_id", kind="mergesort").reset_index(drop=True)


def parse_membership_file(path: str | Path, *, alpha: float) -> pd.DataFrame:
    file = Path(path)
    if not file.is_file():
        raise ExternalResultsRequired(f"Missing SaTScan membership result: {file}")
    records: list[dict[str, Any]] = []
    for tokens in _tokenise_ascii(file):
        if len(tokens) < 3:
            raise ExternalResultValidationError("Malformed SaTScan membership row: fewer than 3 fields")
        p_report = tokens[2]
        p_value = _finite_number(p_report, "membership p-value")
        if p_value <= alpha:
            records.append(
                {
                    "location_id": str(tokens[0]),
                    "cluster_id": int(_finite_number(tokens[1], "membership cluster id")),
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


def _coordinate_location_ids(path: Path) -> set[str]:
    ids: set[str] = set()
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        token = line.strip()
        if not token or token.startswith(("#", ";")):
            continue
        fields = re.split(r"\s+", token)
        if len(fields) < 3:
            raise ExternalResultValidationError("Malformed governed coordinate file")
        if fields[0] in ids:
            raise ExternalResultValidationError("Duplicate location ID in governed coordinate file")
        ids.add(fields[0])
    if not ids:
        raise ExternalResultValidationError("Governed coordinate file contains no locations")
    return ids


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
        raise ExternalResultValidationError(
            f"SaTScan parameter file must contain exactly one {key_name} authority"
        )
    return _normalise_posix(found[0])


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
    match = re.search(
        r"Study\s+period.*?:\s*(\d{4}/\d{1,2}/\d{1,2})\s+to\s+(\d{4}/\d{1,2}/\d{1,2})",
        report_text,
        flags=re.IGNORECASE,
    )
    if not match:
        raise ExternalResultValidationError(
            "SaTScan report does not expose a parseable study period"
        )
    observed_start = pd.Timestamp(match.group(1)).normalize()
    observed_end = pd.Timestamp(match.group(2)).normalize()
    expected_start = governed_start.start_time.normalize()
    expected_end = governed_end.end_time.normalize()
    if observed_start != expected_start or observed_end != expected_end:
        raise ExternalResultValidationError(
            "SaTScan report study period does not match the governed run "
            f"(observed {observed_start.date()} to {observed_end.date()}, expected "
            f"{expected_start.date()} to {expected_end.date()})"
        )


def validate_external_results(
    run_row: Mapping[str, Any], *, run_dir: str | Path, alpha: float
) -> ParsedSaTScanResults:
    """Validate a genuine SaTScan result family against its current run authority.

    The .prm ResultsFile entry is the naming authority.  The core family is exactly
    the extensionless ResultsFile plus ``.col.txt`` and ``.gis.txt``.  No duplicate
    ``ResultsFile + '.txt'`` and no external ``*.provenance.json`` are required.
    """

    root = Path(run_dir).resolve()
    prm = _safe_child(root, str(run_row["prm_path"]))
    if not prm.is_file() or sha256_file(prm) != str(run_row["prm_sha256"]):
        raise ExternalResultValidationError("Parameter-file authority does not match run registry")

    results_prefix = _normalise_posix(str(run_row.get("results_prefix", "")))
    if not results_prefix:
        raise ExternalResultValidationError("Run registry is missing the governed ResultsFile prefix")
    if _parameter_value(prm, "ResultsFile") != results_prefix:
        raise ExternalResultValidationError("Parameter ResultsFile authority differs from the governed result prefix")
    if run_row.get("required_report_path") not in (None, "", results_prefix):
        raise ExternalResultValidationError("Run registry report path is inconsistent with ResultsFile authority")

    input_paths: dict[str, Path] = {}
    for path_key, hash_key in (
        ("case_path", "case_sha256"),
        ("coordinate_path", "coordinate_sha256"),
    ):
        path = _safe_child(root, str(run_row[path_key]))
        if not path.is_file() or sha256_file(path) != str(run_row[hash_key]):
            raise ExternalResultValidationError(f"Input authority mismatch for {path_key}")
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

    authority_mtime_ns = max(
        p.stat().st_mtime_ns
        for p in (prm, input_paths["case_path"], input_paths["coordinate_path"], population)
        if p is not None
    )
    for path in (report, clusters_path, membership_path):
        if path.stat().st_mtime_ns < authority_mtime_ns:
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
    if expected_label.lower() not in report_text.lower():
        raise ExternalResultValidationError("SaTScan report model identity does not match the run authority")

    governed_start = _period_month(run_row["temporal_start"], "governed temporal start")
    governed_end = _period_month(run_row["temporal_end"], "governed temporal end")
    _validate_report_period(report_text, governed_start=governed_start, governed_end=governed_end)

    clusters = parse_cluster_file(clusters_path, alpha=alpha)
    membership = parse_membership_file(membership_path, alpha=alpha)
    if not membership.empty and not set(membership["cluster_id"]).issubset(set(clusters["cluster_id"])):
        raise ExternalResultValidationError("Cluster membership references a non-significant or absent cluster")
    if not clusters.empty:
        counts = membership.groupby("cluster_id", observed=True)["location_id"].nunique()
        for row in clusters.itertuples(index=False):
            if int(counts.get(row.cluster_id, 0)) != int(row.n_locations):
                raise ExternalResultValidationError("Cluster membership count does not match cluster output")

    governed_locations = _coordinate_location_ids(input_paths["coordinate_path"])
    if not set(membership["location_id"].astype(str)).issubset(governed_locations):
        raise ExternalResultValidationError("Cluster membership contains a location outside the governed run")
    if not set(clusters["centroid_location_id"].astype(str)).issubset(governed_locations):
        raise ExternalResultValidationError("Cluster centroid contains a location outside the governed run")

    max_temporal_months = int(run_row.get("max_temporal_months", 0) or 0)
    for row in clusters.itertuples(index=False):
        start = _period_month(row.start_date, "cluster start")
        end = _period_month(row.end_date, "cluster end")
        if start < governed_start or end > governed_end or end < start:
            raise ExternalResultValidationError("SaTScan cluster interval lies outside the governed period")
        if max_temporal_months > 0 and int(end.ordinal - start.ordinal + 1) > max_temporal_months:
            raise ExternalResultValidationError("SaTScan cluster exceeds the governed temporal-window maximum")

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
        "validation_basis": "direct_resultsfile_validation_without_external_provenance_sidecar",
        "external_provenance_sidecar_required": False,
    }
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
