"""Run the MODIS Poisson scan on districts with more than 50 km² of burnable support."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256
from io import StringIO
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from typing import Any

import pandas as pd

from .config import load_configuration_bundle, validate_secondary_configuration
from .design import NAMED_BA2001_GT_CUTOFF_KM2, rq1_support_sensitivity_settings
from .execution_evidence import execute_satscan_with_evidence, validate_satscan_execution_receipt
from .paths import ProjectPaths
from .satscan_io import (
    MODEL_DISCRETE_POISSON,
    ParsedSaTScanResults,
    sha256_file,
    validate_external_results,
)

PRIMARY_ID = "MCD64A1_POISSON_PRIMARY"
SCENARIO_ID = "MCD64A1_POISSON_BA2001_GT50"
MIN_SUPPORT_KM2 = Decimal(NAMED_BA2001_GT_CUTOFF_KM2)
SECONDARY_PREFIX = "04_secondary_concentration"
RESULTS_PREFIX = "results/modis_gt50"
DESIGN_NAME = "modis_gt50_design.json"
EXPOSURE_NAME = "modis_gt50_exposure_authority.csv"
EXPOSURE_COLUMNS = ("location_id", "unit_id", "fixed_ba2001_support_km2")
SUMMARY_NAME = "modis_gt50_summary.json"
DERIVED_DIR = "derived"
NATIVE_RESULT_ROLES = ("required_report_path", "required_cluster_path", "required_membership_path")
MATCH_RULE = "exact_start_and_end_dates_and_identical_retained_district_membership"
WINDOW_COLUMNS = (
    "match_status", "primary_cluster_id", "restricted_cluster_id", "primary_rank", "restricted_rank", "rank_change",
    "primary_start_month", "primary_end_month", "restricted_start_month", "restricted_end_month",
    "primary_duration_months", "restricted_duration_months", "overlap_months",
    "primary_full_districts", "primary_shared_districts", "restricted_districts",
    "shared_district_intersection", "shared_district_jaccard", "primary_leading_window", "restricted_leading_window",
    "primary_observed", "restricted_observed", "observed_change",
    "primary_expected", "restricted_expected", "expected_change",
    "primary_observed_expected_ratio", "restricted_observed_expected_ratio", "observed_expected_ratio_change",
    "primary_relative_risk", "restricted_relative_risk", "relative_risk_change",
    "primary_log_likelihood_ratio", "restricted_log_likelihood_ratio", "log_likelihood_ratio_change",
    "primary_p_value", "restricted_p_value", "p_value_change",
)
BASELINE_INPUTS = {"prm_path": "prm_sha256", "case_path": "case_sha256",
                   "coordinate_path": "coordinate_sha256", "population_path": "population_sha256"}
INPUT_NAMES = {"prm_path": "modis_gt50.prm", "case_path": "modis_gt50.cas",
               "coordinate_path": "modis_gt50.geo", "population_path": "modis_gt50.pop"}
RESULT_NAMES = {"clusters": "modis_gt50_clusters.csv", "membership": "modis_gt50_membership.csv",
                "recurrence": "modis_gt50_recurrence.csv", "window_comparison": "modis_gt50_window_comparison.csv"}


@dataclass(frozen=True, slots=True)
class RestrictedScanResult:
    summary: dict[str, Any]
    clusters: pd.DataFrame
    membership: pd.DataFrame
    recurrence: pd.DataFrame
    window_comparison: pd.DataFrame


@dataclass(frozen=True, slots=True)
class _PrimaryBaseline:
    directory: Path
    run_id: str
    row: dict[str, str]
    specification: dict[str, str]
    sources: dict[str, dict[str, str]]
    evidence: str
    scan_digest: str
    panel_path: str
    cutoff_km2: int
    locations: dict[str, dict[str, str]]
    result: ParsedSaTScanResults

    def source(self, role: str) -> Path:
        return _child(self.directory, self.sources[role]["path"])


def _child(root: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or candidate.anchor or ".." in candidate.parts:
        raise ValueError(f"Invalid relative source file: {relative}")
    path = (root / candidate).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"Missing or invalid source file: {relative}")
    return path


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _tokens(path: Path) -> list[list[str]]:
    return [line.split() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _subsets(case: Path, coordinates: Path, population: Path, expected_months: int,
             exposure_authority: dict[str, Decimal], *, cutoff_km2: int,
             ) -> tuple[dict[str, Decimal], set[str], dict[str, list[list[str]]]]:
    """Filter all three interfaces using the same fixed-exposure population."""
    tables = {"case_path": _tokens(case), "coordinate_path": _tokens(coordinates),
              "population_path": _tokens(population)}
    support: dict[str, Decimal] = {}
    dates: dict[str, set[str]] = defaultdict(set)
    for location, day, area in tables["population_path"]:
        value = Decimal(area)
        if not value.is_finite() or value <= 0:
            raise ValueError("The primary Poisson population must have positive finite exposure")
        if support.setdefault(location, value) != value or day in dates[location]:
            raise ValueError(f"Duplicate date or varying fixed exposure for location {location}")
        dates[location].add(day)
    if not support:
        raise ValueError("The primary Poisson population has no locations")
    calendar = next(iter(dates.values()))
    if len(calendar) != expected_months or any(values != calendar for values in dates.values()):
        raise ValueError("Primary population is missing a complete common monthly exposure spine")
    coordinate_counts = Counter(location for location, _, _ in tables["coordinate_path"])
    if coordinate_counts != Counter(support.keys()):
        raise ValueError("Primary coordinate IDs do not exactly match the exposure population")
    case_keys: set[tuple[str, str]] = set()
    for location, count, day in tables["case_path"]:
        if location not in dates or day not in dates[location] or (location, day) in case_keys:
            raise ValueError("Primary case row has an invalid or duplicate district-month")
        if int(count) < 0:
            raise ValueError("Primary case count cannot be negative")
        case_keys.add((location, day))
    if exposure_authority.keys() != support.keys():
        raise ValueError("The unrounded roster IDs do not match the primary population")
    for location, area in exposure_authority.items():
        if not area.is_finite() or area <= 0 or Decimal(f"{float(area):.9f}") != support[location]:
            raise ValueError(f"Unrounded support does not reproduce the primary input for location {location}")
    retained = {location for location, exposure in exposure_authority.items() if exposure > cutoff_km2}
    if not retained or len(retained) == len(support):
        raise ValueError("The stated sensitivity cutoff must define a nonempty restricted population")
    filtered = {role: [row for row in records if row[0] in retained] for role, records in tables.items()}
    return exposure_authority, retained, filtered


def _retarget_parameter(text: str, replacements: dict[str, str]) -> str:
    lines = text.splitlines()
    for key, replacement in replacements.items():
        matches = [index for index, line in enumerate(lines) if line.startswith(f"{key}=")]
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one parameter entry for {key!r}")
        lines[matches[0]] = f"{key}={replacement}"
    return "\n".join(lines) + "\n"


def _write_json(path: Path, record: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(record, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def _source_record(root: Path, relative: str) -> dict[str, str]:
    return {"path": relative, "sha256": sha256_file(_child(root, relative))}


def _load_baseline(
    baseline: Path, *, expected_run_id: str | None = None, enforce_freshness: bool = True,
) -> _PrimaryBaseline:
    tables = f"{SECONDARY_PREFIX}/tables"
    source_names = {
        "registry": f"{tables}/secondary_run_registry.csv",
        "specification": f"{tables}/secondary_scan_specification_registry.csv",
        "locations": f"{tables}/secondary_location_authority.csv",
        "status": f"{SECONDARY_PREFIX}/secondary_external_execution_status.json",
        "configuration": "00_scaffold/realised_configuration.json",
    }
    sources = {role: _child(baseline, relative) for role, relative in source_names.items()}
    state = json.loads(sources["status"].read_text(encoding="utf-8"))
    if state["external_execution_state"] != "RESULTS_VALIDATED":
        raise ValueError("The primary baseline must have validated external results")
    source_names["publication_manifest"] = state["run_local_publication_source_manifest"]
    manifest = json.loads(_child(baseline, source_names["publication_manifest"]).read_text(encoding="utf-8"))
    run_id = manifest.get("secondary_run_id")
    if (
        manifest.get("schema") != "rp1-satscan-run-local-publication-sources-v2"
        or manifest.get("external_execution_state") != state["external_execution_state"]
        or manifest.get("external_execution_evidence") != state["external_execution_evidence"]
        or manifest.get("model_count") != state["validated_model_count"]
        or not isinstance(run_id, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", run_id) is None
        or (expected_run_id is not None and run_id != expected_run_id)
        or (baseline.parent.name == "runs" and baseline.parent.parent.name == "out" and run_id != baseline.name)
    ):
        raise ValueError("Stored primary secondary-run identity does not agree with the selected baseline")
    [primary] = [row for row in _rows(sources["registry"]) if row["model_id"] == PRIMARY_ID]
    [specification] = [row for row in _rows(sources["specification"]) if row["model_id"] == PRIMARY_ID]
    if primary["model"] != MODEL_DISCRETE_POISSON or primary["product"] != "mcd64a1":
        raise ValueError("Baseline primary scan does not describe a MODIS discrete Poisson calculation")
    if specification["population_field"] != "modis_burnable_km2_union_ba2001":
        raise ValueError("Baseline primary exposure is not the fixed BA2001 union")
    for role in (*BASELINE_INPUTS, *NATIVE_RESULT_ROLES):
        source_names[role] = primary[role]
    maxima = primary["results_prefix"] + ".llr.txt"
    if (baseline / maxima).is_file():
        source_names["monte_carlo_maxima"] = maxima
    realised = json.loads(sources["configuration"].read_text(encoding="utf-8"))
    if realised["configuration_sha256"] != state["configuration_sha256"]:
        raise ValueError("Primary status and realised configuration identify different configurations")
    analysis = realised["contracts"]["analysis_contract.yml"]
    panel = realised["contracts"]["data_schema_contract.yml"]["panels"]["district_monthly"]
    roles = analysis["field_roles"]["secondary"]
    support_settings = rq1_support_sensitivity_settings(analysis["research_questions"]["rq1"], allow_legacy_snapshot=True)
    if (
        roles["mcd64a1_cases"] != specification["case_field"]
        or roles["mcd64a1_exposure"] != specification["population_field"]
        or panel["primary_key"] != ["unit_id", "yyyymm"]
        or panel["start"] > primary["temporal_start"]
        or panel["end"] < primary["temporal_end"]
        or float(analysis["reproducibility"]["alpha"]) != float(specification["alpha"])
    ):
        raise ValueError("Primary scan specification and realised scientific configuration disagree")
    location_rows = _rows(sources["locations"])
    locations = {row["location_id"]: row for row in location_rows}
    if len(locations) != len(location_rows) or len({row["unit_id"] for row in location_rows}) != len(location_rows):
        raise ValueError("Primary location authority must uniquely map district and location IDs")
    scope = {
        "panel": panel, "secondary": analysis["secondary_analysis"], "field_roles": roles,
        "study": analysis["study"], "reproducibility": analysis["reproducibility"], "specification": specification,
    }
    scan_digest = sha256(json.dumps(scope, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    source_records = {role: _source_record(baseline, relative) for role, relative in source_names.items()}
    result = validate_external_results(
        primary, run_dir=baseline, alpha=float(specification["alpha"]), enforce_freshness=enforce_freshness,
    )
    return _PrimaryBaseline(
        baseline, run_id, primary, specification, source_records,
        state["external_execution_evidence"], scan_digest, panel["path"],
        support_settings.restricted_scan_cutoff_km2, locations, result,
    )


def _admit_exposure_authority(
    baseline: _PrimaryBaseline, paths: ProjectPaths,
) -> tuple[dict[str, Decimal], dict[str, Any]]:
    """Prove the unrounded staged-panel projection against every primary population and case row."""
    configuration = json.loads(baseline.source("configuration").read_text(encoding="utf-8"))
    validate_secondary_configuration(
        load_configuration_bundle(paths.root / "config"), configuration, configuration["configuration_sha256"],
    )
    inventory_path = paths.input_hash_inventory
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    records = [item for item in inventory["files"] if item["staged_path"] == baseline.panel_path]
    if inventory["provenance_schema_version"] != "rp1-input-provenance-v2" or len(records) != 1:
        raise ValueError("The unrounded district panel is absent from the governed input inventory")
    [record] = records
    panel = paths.resolve_inside(baseline.panel_path)
    if panel.stat().st_size != record["size_bytes"] or sha256_file(panel) != record["sha256"]:
        raise ValueError("Unrounded district panel differs from the governed input inventory")
    exposure_field = baseline.specification["population_field"]
    case_field = baseline.specification["case_field"]
    primary_population = {
        (loc, day): Decimal(area) for loc, day, area in _tokens(baseline.source("population_path"))
    }
    primary_cases = {(loc, day): int(count) for loc, count, day in _tokens(baseline.source("case_path"))}
    locations = {baseline.locations[loc]["unit_id"]: loc for loc, _ in primary_population}
    exposures: dict[str, Decimal] = {}
    seen: set[tuple[str, str]] = set()
    columns = ["unit_id", "yyyymm", exposure_field, case_field]
    with panel.open(encoding="utf-8-sig", newline="") as handle:
        rows = csv.DictReader(handle)
        if not set(columns) <= set(rows.fieldnames or ()):
            raise ValueError("Governed district panel omits required scan fields")
        for row in rows:
            loc = locations.get(row["unit_id"])
            if loc is None:
                continue
            month = row["yyyymm"]
            key = (loc, f"{int(month[:4])}/{int(month[4:])}/1")
            if key not in primary_population:
                continue
            area, cases = Decimal(row[exposure_field]), Decimal(row[case_field])
            if (
                key in seen or not area.is_finite() or area <= 0
                or exposures.setdefault(loc, area) != area
                or Decimal(f"{float(area):.9f}") != primary_population[key]
                or cases != primary_cases.get(key, 0)
            ):
                raise ValueError(f"Governed unrounded panel cannot reproduce primary scan authority at {key}")
            seen.add(key)
    if seen != primary_population.keys():
        raise ValueError("Governed unrounded panel omits primary population months")
    for loc, x, y in _tokens(baseline.source("coordinate_path")):
        authority = baseline.locations[loc]
        if (x, y) != (f"{float(authority['x']):.6f}", f"{float(authority['y']):.6f}"):
            raise ValueError(f"Primary coordinate does not reproduce the district location authority for {loc}")
    provenance = {
        "path": baseline.panel_path, "sha256": record["sha256"], "size_bytes": record["size_bytes"],
        "input_inventory_sha256": sha256_file(inventory_path),
        "exposure_field": exposure_field, "case_field": case_field,
        "projection": "complete_primary_location_months_exact_counts_and_serialized_exposure",
        "fixed_area_policy": "identical_unrounded_area_in_every_primary_month",
    }
    return exposures, provenance


def _exposure_payload(exposure: dict[str, Decimal], baseline: _PrimaryBaseline) -> bytes:
    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(EXPOSURE_COLUMNS)
    for loc in sorted(exposure, key=int):
        writer.writerow((loc, baseline.locations[loc]["unit_id"], str(exposure[loc])))
    return buffer.getvalue().encode("utf-8")


def _derive_design(baseline: _PrimaryBaseline, exposure_authority: dict[str, Decimal],
                   provenance: dict[str, Any]):
    primary, specification = baseline.row, baseline.specification
    period = pd.period_range(primary["temporal_start"], primary["temporal_end"], freq="M")
    exposure, retained, filtered = _subsets(
        baseline.source("case_path"), baseline.source("coordinate_path"), baseline.source("population_path"),
        len(period), exposure_authority, cutoff_km2=baseline.cutoff_km2,
    )
    if not exposure.keys() <= baseline.locations.keys() or len(exposure) != int(specification["eligible_districts"]):
        raise ValueError("The primary population and geographic location authority disagree")
    if {day for _, day, _ in filtered["population_path"]} != {f"{m.year}/{m.month}/1" for m in period}:
        raise ValueError("Primary population dates differ from the governed primary scan period")

    paths = INPUT_NAMES
    parameter = _retarget_parameter(
        baseline.source("prm_path").read_text(encoding="utf-8"),
        {"; scenario_id": SCENARIO_ID, "CaseFile": paths["case_path"],
         "CoordinatesFile": paths["coordinate_path"], "PopulationFile": paths["population_path"],
         "ResultsFile": RESULTS_PREFIX},
    )
    contents = {paths[role]: "".join(" ".join(row) + "\n" for row in records).encode()
                for role, records in filtered.items()}
    contents[paths["prm_path"]] = parameter.encode()
    hashes = {column: sha256(contents[paths[role]]).hexdigest() for role, column in BASELINE_INPUTS.items()}
    exposure_bytes = _exposure_payload(exposure, baseline)
    contents[EXPOSURE_NAME] = exposure_bytes
    row = {
        **primary, **paths, **hashes, "scenario_id": SCENARIO_ID, "model_id": SCENARIO_ID,
        "results_prefix": RESULTS_PREFIX, "required_report_path": RESULTS_PREFIX,
        "required_cluster_path": RESULTS_PREFIX + ".col.txt",
        "required_membership_path": RESULTS_PREFIX + ".gis.txt",
        "execution_state": "EXTERNAL_RESULTS_REQUIRED",
    }
    design = {
        "schema": "rp1-modis-support-sensitivity-v2",
        "scenario_id": SCENARIO_ID, "cutoff_km2": baseline.cutoff_km2, "admission": "strictly_greater_than",
        "baseline_secondary_run": baseline.run_id, "baseline_evidence": baseline.evidence,
        "baseline_sources": baseline.sources, "baseline_scan_science_sha256": baseline.scan_digest,
        "unrounded_exposure_authority": {
            **provenance, "roster_path": EXPOSURE_NAME, "roster_sha256": sha256(exposure_bytes).hexdigest(),
        },
        "run_authority": row,
        "retained_districts": len(retained), "excluded_districts": len(exposure) - len(retained),
        "population_rows": len(filtered["population_path"]), "positive_case_rows": len(filtered["case_path"]),
        "total_cases": sum(int(line[1]) for line in filtered["case_path"]),
    }
    return design, contents, retained, filtered


def prepare_scan_sensitivity(
    *, baseline_secondary_dir: str | Path, run_dir: str | Path, paths: ProjectPaths | None = None,
) -> dict[str, Any]:
    """Write the parameter file and input subset for a selected validated primary run."""
    baseline_dir = Path(baseline_secondary_dir).resolve(strict=True)
    destination = Path(run_dir).resolve()
    if destination.exists() or (
        destination.is_relative_to(baseline_dir) and destination != baseline_dir / "support_sensitivity"
    ):
        raise ValueError("Choose a fresh sensitivity run directory")
    baseline = _load_baseline(baseline_dir)
    exposure, provenance = _admit_exposure_authority(baseline, paths or ProjectPaths.discover())
    design, contents, *_ = _derive_design(baseline, exposure, provenance)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".restricted_scan_", dir=destination.parent) as staging:
        stage = Path(staging) / "run"
        (stage / "results").mkdir(parents=True)
        for filename, payload in contents.items():
            (stage / filename).write_bytes(payload)
        _write_json(stage / DESIGN_NAME, design)
        if destination.exists():
            raise FileExistsError(destination)
        stage.rename(destination)
    return design


def _reconcile_design(baseline: _PrimaryBaseline, destination: Path, *, established_transfer: bool):
    recorded = json.loads(_child(destination, DESIGN_NAME).read_text(encoding="utf-8"))
    if recorded.get("schema") != "rp1-modis-support-sensitivity-v2":
        raise ValueError("Restricted scan design lacks a governed unrounded exposure roster")
    authority = recorded["unrounded_exposure_authority"]
    if established_transfer:
        # The caller authenticates transferred bytes and supplies the selected run ID.
        # Here the restricted design is recomputed against the transferred primary inputs.
        exposure_rows = _rows(_child(destination, EXPOSURE_NAME))
        exposure = {row["location_id"]: Decimal(row[EXPOSURE_COLUMNS[-1]]) for row in exposure_rows}
        provenance = {key: value for key, value in authority.items() if key not in {"roster_path", "roster_sha256"}}
        if (
            provenance.get("path") != baseline.panel_path
            or provenance.get("exposure_field") != baseline.specification["population_field"]
            or provenance.get("case_field") != baseline.specification["case_field"]
            or provenance.get("projection") != "complete_primary_location_months_exact_counts_and_serialized_exposure"
            or provenance.get("fixed_area_policy") != "identical_unrounded_area_in_every_primary_month"
            or not isinstance(provenance.get("size_bytes"), int)
            or provenance["size_bytes"] <= 0
            or any(not re.fullmatch(r"[0-9a-f]{64}", str(provenance.get(key)))
                   for key in ("sha256", "input_inventory_sha256"))
        ):
            raise ValueError("Transferred unrounded exposure provenance disagrees with the selected primary authority")
    else:
        exposure, provenance = _admit_exposure_authority(baseline, ProjectPaths.discover())
    design, inputs, retained, filtered = _derive_design(baseline, exposure, provenance)
    if recorded != design or any(_child(destination, key).read_bytes() != value for key, value in inputs.items()):
        raise ValueError("Restricted scan design or inputs differ from the selected primary authority")
    return design, exposure, retained, filtered


def _window_comparison(
    primary: ParsedSaTScanResults, restricted: ParsedSaTScanResults, retained: set[str],
) -> pd.DataFrame:
    def build_index(result: ParsedSaTScanResults, *, is_restricted: bool):
        membership = result.membership.groupby("cluster_id")["location_id"].agg(frozenset).to_dict()
        index = {}
        for row in result.clusters.itertuples(index=False):
            members = membership[row.cluster_id]
            start, end = (date(*(int(value) for value in field.split("/")))
                          for field in (row.start_date, row.end_date))
            shared = members & retained
            if is_restricted and shared != members:
                raise ValueError("The restricted scan contains members outside the retained district domain")
            # An entirely excluded footprint has no comparable member set.
            key = (start, end, shared, row.cluster_id if not shared else None)
            if key in index:
                raise ValueError("Scan windows have an ambiguous matching identity on the retained district domain")
            index[key] = (row, members)
        return index

    left = build_index(primary, is_restricted=False)
    right = build_index(restricted, is_restricted=True)
    records = []
    native_fields = {
        "observed": "case_count", "expected": "expected_count", "observed_expected_ratio": "observed_expected_ratio",
        "relative_risk": "relative_risk", "log_likelihood_ratio": "log_likelihood_ratio", "p_value": "p_value",
    }
    for key in dict.fromkeys((*left, *right)):
        primary_window, primary_members = left.get(key, (None, None))
        restricted_window, restricted_members = right.get(key, (None, None))
        matched = primary_window is not None and restricted_window is not None
        start, end, shared, _ = key
        duration = (end.year - start.year) * 12 + end.month - start.month + 1
        record = {
            "match_status": ("matched_exact_shared_domain" if matched else
                             "primary_only" if primary_window is not None else "restricted_only"),
            "overlap_months": duration if matched else None,
            "primary_full_districts": len(primary_members) if primary_members is not None else None,
            "primary_shared_districts": len(shared) if primary_members is not None else None,
            "restricted_districts": len(restricted_members) if restricted_members is not None else None,
            "shared_district_intersection": len(shared) if matched else None,
            "shared_district_jaccard": 1.0 if matched else None,
        }
        for side, window in (("primary", primary_window), ("restricted", restricted_window)):
            record.update({
                f"{side}_cluster_id": window.cluster_id if window is not None else None,
                f"{side}_rank": window.cluster_rank if window is not None else None,
                f"{side}_start_month": start.strftime("%Y-%m") if window is not None else None,
                f"{side}_end_month": end.strftime("%Y-%m") if window is not None else None,
                f"{side}_duration_months": duration if window is not None else None,
                f"{side}_leading_window": window.cluster_rank == 1 if window is not None else None,
            })
            for field, native in native_fields.items():
                record[f"{side}_{field}"] = getattr(window, native) if window is not None else None
        for field in ("rank", *native_fields):
            record[f"{field}_change"] = record[f"restricted_{field}"] - record[f"primary_{field}"] if matched else None
        records.append(record)
    frame = pd.DataFrame.from_records(records, columns=WINDOW_COLUMNS)
    integer_fields = (
        "cluster_id", "rank", "duration_months", "observed",
    )
    for field in (
        *(f"{side}_{name}" for side in ("primary", "restricted") for name in integer_fields),
        "rank_change", "overlap_months", "primary_full_districts", "primary_shared_districts",
        "restricted_districts", "shared_district_intersection", "observed_change",
    ):
        frame[field] = frame[field].astype("Int64")
    return frame


def _read_scan(baseline_dir: Path, destination: Path, *, expected_baseline_run_id: str | None) -> RestrictedScanResult:
    established_transfer = expected_baseline_run_id is not None
    baseline = _load_baseline(
        baseline_dir, expected_run_id=expected_baseline_run_id, enforce_freshness=not established_transfer,
    )
    design, exposure, retained, filtered = _reconcile_design(
        baseline, destination, established_transfer=established_transfer,
    )
    alpha = float(baseline.specification["alpha"])
    row = design["run_authority"]
    sensitivity_result = validate_external_results(
        row, run_dir=destination, alpha=alpha, enforce_freshness=not established_transfer,
    )
    receipt_path = destination / f"{RESULTS_PREFIX}.execution.json"
    receipt = None
    if receipt_path.is_file():
        bound = _child(destination, f"{RESULTS_PREFIX}.execution.json")
        validate_satscan_execution_receipt(bound, run_row=row, run_dir=destination)
        receipt = {"path": f"{RESULTS_PREFIX}.execution.json", "sha256": sha256_file(bound)}

    clusters = sensitivity_result.clusters
    locations, primary_result = baseline.locations, baseline.result
    membership = sensitivity_result.membership.assign(
        unit_id=lambda data: data["location_id"].map({loc: record["unit_id"] for loc, record in locations.items()})
    )
    primary_counts = Counter(primary_result.membership["location_id"])
    sensitivity_counts = Counter(membership["location_id"])
    comparison = []
    for location in sorted(exposure, key=int):
        loc = locations[location]
        kept = location in retained
        comparison.append({
            "location_id": location, "unit_id": loc["unit_id"], "unit_name": loc["unit_name"],
            "parent_code": loc["parent_code"], "fixed_ba2001_support_km2": str(exposure[location]),
            "retained": kept, "primary_cluster_count": primary_counts[location],
            "sensitivity_cluster_count": sensitivity_counts[location] if kept else None,
            "cluster_count_change": sensitivity_counts[location] - primary_counts[location] if kept else None,
        })
    windows = _window_comparison(primary_result, sensitivity_result, retained)
    matched = int(windows["match_status"].eq("matched_exact_shared_domain").sum())
    primary_exposure = sum(exposure.values())
    removed_exposure = sum(exposure[loc] for loc in exposure.keys() - retained)
    primary_cases = sum(int(count) for _, count, _ in _tokens(baseline.source("case_path")))
    restricted_cases = sum(int(count) for _, count, _ in filtered["case_path"])
    removed_cases = primary_cases - restricted_cases
    native_result_sources = {role: _source_record(destination, row[role]) for role in NATIVE_RESULT_ROLES}
    maxima = RESULTS_PREFIX + ".llr.txt"
    if (destination / maxima).is_file():
        native_result_sources["monte_carlo_maxima"] = _source_record(destination, maxima)
    summary = {
        "scenario_id": SCENARIO_ID, "p_value_threshold": alpha,
        "primary_significant_clusters": int(len(primary_result.clusters)),
        "sensitivity_significant_clusters": int(len(clusters)),
        "primary_eligible_districts": len(exposure), "sensitivity_eligible_districts": len(retained),
        "excluded_districts_by_acz": dict(Counter(locations[loc]["parent_code"] for loc in exposure.keys() - retained)),
        "primary_median_recurrence_common_districts": median(primary_counts[loc] for loc in retained),
        "sensitivity_median_recurrence_common_districts": median(sensitivity_counts[loc] for loc in retained),
        "changed_recurrence_common_districts": sum(primary_counts[loc] != sensitivity_counts[loc] for loc in retained),
        "primary_exposure_km2": float(primary_exposure),
        "restricted_exposure_km2": float(primary_exposure - removed_exposure),
        "removed_exposure_km2": float(removed_exposure),
        "removed_exposure_fraction": float(removed_exposure / primary_exposure),
        "primary_total_cases": primary_cases, "restricted_total_cases": restricted_cases, "removed_total_cases": removed_cases,
        "removed_case_fraction": removed_cases / primary_cases if primary_cases else None,
        "matched_significant_windows": matched,
        "unmatched_primary_windows": len(primary_result.clusters) - matched,
        "unmatched_restricted_windows": len(clusters) - matched,
        "window_match_rule": MATCH_RULE,
        "native_result_sources": native_result_sources,
        "execution_receipt": receipt,
    }
    return RestrictedScanResult(summary, clusters, membership, pd.DataFrame(comparison), windows)


def _csv_text(frame: pd.DataFrame) -> str:
    return frame.to_csv(index=False, lineterminator="\n")


def scan_sensitivity_summary_path(run_dir: str | Path) -> Path:
    """Return the completion marker for the derived restricted scan family."""
    return Path(run_dir) / DERIVED_DIR / SUMMARY_NAME


def _validate_derived(destination: Path, result: RestrictedScanResult) -> None:
    marker = _child(destination, f"{DERIVED_DIR}/{SUMMARY_NAME}")
    if json.loads(marker.read_text(encoding="utf-8")) != result.summary:
        raise ValueError("Restricted scan summary does not reconcile to native results")
    for attribute, filename in RESULT_NAMES.items():
        payload = _csv_text(getattr(result, attribute)).encode("utf-8")
        if _child(destination, f"{DERIVED_DIR}/{filename}").read_bytes() != payload:
            raise ValueError(f"Restricted scan derived table does not reconcile to native results: {filename}")


def integrate_scan_sensitivity(*, baseline_secondary_dir: str | Path, run_dir: str | Path) -> dict[str, Any]:
    """Validate the native results and publish the complete derived family as one directory."""
    baseline, destination = Path(baseline_secondary_dir).resolve(), Path(run_dir).resolve()
    result = _read_scan(baseline, destination, expected_baseline_run_id=None)
    derived = destination / DERIVED_DIR
    if derived.exists() or derived.is_symlink():
        _validate_derived(destination, result)
        return result.summary
    with TemporaryDirectory(prefix=".restricted_derived_", dir=destination) as staging:
        stage = Path(staging) / "derived"
        stage.mkdir()
        for attribute, filename in RESULT_NAMES.items():
            (stage / filename).write_bytes(_csv_text(getattr(result, attribute)).encode("utf-8"))
        _write_json(stage / SUMMARY_NAME, result.summary)
        try:
            stage.rename(derived)
        except OSError:
            if not derived.is_dir():
                raise
            _validate_derived(destination, result)
    return result.summary


def validate_scan_sensitivity(
    *, baseline_secondary_dir: str | Path, run_dir: str | Path, expected_baseline_run_id: str | None = None,
) -> RestrictedScanResult:
    """Reconcile the selected authorities, native outputs and published comparison.

    Supply an independently selected baseline ID for a byte-authenticated transfer.
    This permits portable validation when governed staged inputs and source times
    are unavailable.
    """
    baseline, destination = Path(baseline_secondary_dir).resolve(), Path(run_dir).resolve()
    result = _read_scan(baseline, destination, expected_baseline_run_id=expected_baseline_run_id)
    _validate_derived(destination, result)
    return result


def execute_scan_sensitivity(
    *, baseline_secondary_dir: str | Path, run_dir: str | Path, executable_path: str | Path,
    timeout_seconds: int = 3600,
) -> dict[str, Any]:
    """Prepare, execute and validate the restricted run through the recorded engine wrapper."""
    baseline, destination = Path(baseline_secondary_dir).resolve(), Path(run_dir).resolve()
    if destination.exists():
        if (destination / f"{RESULTS_PREFIX}.execution.json").is_file():
            return integrate_scan_sensitivity(baseline_secondary_dir=baseline, run_dir=destination)
        selected = _load_baseline(baseline)
        design, *_ = _reconcile_design(selected, destination, established_transfer=False)
    else:
        design = prepare_scan_sensitivity(baseline_secondary_dir=baseline, run_dir=destination)
    alpha = float(next(
        row["alpha"] for row in _rows(_child(baseline, design["baseline_sources"]["specification"]["path"]))
        if row["model_id"] == PRIMARY_ID
    ))
    execute_satscan_with_evidence(
        run_row=design["run_authority"], run_dir=destination, executable_path=executable_path,
        alpha=alpha, timeout_seconds=timeout_seconds,
    )
    return integrate_scan_sensitivity(baseline_secondary_dir=baseline, run_dir=destination)
