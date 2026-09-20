"""Governed secondary spatio-temporal scan integration.

Exactly two product-specific SaTScan specifications are authorised.  The
secondary analysis is separate from RQ1-RQ3 and does not estimate causal
fire drivers.  Missing SaTScan output is explicitly external-results-required;
it is never interpreted as an empty cluster set.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

from .config import AnalysisContract, ConfigurationBundle, export_realised_configuration, load_configuration_bundle, satscan_parameters
from .data_io import DataAuthorities, load_data_authorities
from .outputs import OutputRecord, OutputWriter
from .paths import ProjectPaths
from .satscan_io import (
    MODEL_DISCRETE_POISSON,
    MODEL_SPACE_TIME_PERMUTATION,
    REPORTING_HIERARCHICAL,
    ExternalResultsRequired,
    ExternalResultValidationError,
    ParsedSaTScanResults,
    SaTScanIOError,
    case_text,
    coordinate_text,
    find_satscan_executable,
    generate_parameter_file as _generate_parameter_file,
    population_text,
    sha256_file,
    validate_external_results,
)
from .variables import resolve_field_role
from .validation import (
    DataContractSummary,
    long_run_ba_district_mask,
    paired_ba_viirs_district_mask,
    validate_data_authorities,
)

INPUTS_READY = "INPUTS_READY"
EXTERNAL_RESULTS_REQUIRED = "EXTERNAL_RESULTS_REQUIRED"
RESULTS_VALIDATED = "RESULTS_VALIDATED"
SECONDARY_SECTION = "04_secondary_concentration"


class SecondaryClusterError(RuntimeError):
    """Raised when the secondary scientific/interface authority is violated."""


@dataclass(frozen=True, slots=True)
class ScanScenario:
    scenario_id: str
    product: str
    source_family: str
    model: str
    role: str
    temporal_window: str
    case_field: str
    population_field: str | None
    exposure_semantics: str
    max_spatial_percent: float
    max_temporal_months: int
    reporting_rule: str

    @property
    def requires_population(self) -> bool:
        return self.model == MODEL_DISCRETE_POISSON


@dataclass(frozen=True, slots=True)
class SecondaryInputRun:
    run_id: str
    run_dir: Path
    execution_state: str
    scan_specification_registry: pd.DataFrame
    secondary_run_registry: pd.DataFrame
    input_audit: pd.DataFrame
    output_registry: pd.DataFrame
    records: tuple[OutputRecord, ...]



def _require_columns(frame: pd.DataFrame, columns: Sequence[str], context: str) -> None:
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise SecondaryClusterError(f"{context} missing required columns: {missing!r}")


def _month_period(value: str | int) -> pd.Period:
    token = str(value)
    if re.fullmatch(r"\d{6}", token):
        year, month = int(token[:4]), int(token[4:])
        if month < 1 or month > 12:
            raise SecondaryClusterError(f"Invalid yyyymm: {value!r}")
        return pd.Period(year=year, month=month, freq="M")
    try:
        return pd.Period(token, freq="M")
    except Exception as exc:
        raise SecondaryClusterError(f"Invalid month token: {value!r}") from exc


def _window_bounds(analysis: AnalysisContract, temporal_window: str) -> tuple[pd.Period, pd.Period]:
    windows = analysis.study["temporal_windows"]
    if temporal_window == "long_run":
        raw = windows["long_run"]
    elif temporal_window == "overlap_monthly":
        raw = windows["overlap_monthly"]
    else:
        raise SecondaryClusterError(f"Unsupported secondary temporal window: {temporal_window!r}")
    return _month_period(str(raw["start"])), _month_period(str(raw["end"]))


def _months(start: pd.Period, end: pd.Period) -> pd.PeriodIndex:
    if end < start:
        raise SecondaryClusterError("Secondary temporal window is reversed")
    return pd.period_range(start, end, freq="M")


def load_scan_scenarios(analysis: AnalysisContract) -> tuple[ScanScenario, ...]:
    """Project configured secondary scenarios without re-owning study values."""
    raw = analysis.secondary_analysis.get("scenarios")
    if not isinstance(raw, tuple) or not raw:
        raise SecondaryClusterError("secondary_analysis.scenarios must be a non-empty immutable sequence")
    params = satscan_parameters(analysis)
    role = str(analysis.secondary_analysis.get("role", "secondary_noncausal"))
    scenarios: list[ScanScenario] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, Mapping):
            raise SecondaryClusterError("Each secondary scan specification must be a mapping")
        scenario_id = str(item["scenario_id"])
        if scenario_id in seen:
            raise SecondaryClusterError(f"Duplicate secondary scenario ID: {scenario_id!r}")
        seen.add(scenario_id)
        case_field = str(resolve_field_role(analysis, str(item["case_role"])))
        exposure_role = item.get("exposure_role")
        population_field = None if exposure_role is None else str(resolve_field_role(analysis, str(exposure_role)))
        model = str(item["model"])
        if model == MODEL_DISCRETE_POISSON and population_field is None:
            raise SecondaryClusterError("Discrete-Poisson configuration requires exposure")
        if model == MODEL_SPACE_TIME_PERMUTATION and population_field is not None:
            raise SecondaryClusterError("Space-time permutation configuration must not define exposure")
        scenarios.append(ScanScenario(
            scenario_id=scenario_id,
            product=str(item["product"]),
            source_family=str(item["product"]),
            model=model,
            role=role,
            temporal_window=str(item["temporal_window"]),
            case_field=case_field,
            population_field=population_field,
            exposure_semantics="configured_exposure" if population_field else "no_external_exposure",
            max_spatial_percent=float(params.max_spatial_percent),
            max_temporal_months=int(params.max_temporal_months),
            reporting_rule=str(params.reporting_method),
        ))
    return tuple(sorted(scenarios, key=lambda s: s.scenario_id))


def build_location_authority(
    district_geometry: gpd.GeoDataFrame,
    *,
    coordinate_crs: str,
    anchor_method: str,
) -> pd.DataFrame:
    required = ["dist_id", "dist_name", "zone_id", "zone_name", "zone_code", "geometry"]
    missing = [c for c in required if c not in district_geometry.columns]
    if missing:
        raise SecondaryClusterError(f"District geometry missing location fields: {missing!r}")
    if district_geometry.crs is None or district_geometry.crs.to_string() != coordinate_crs:
        raise SecondaryClusterError(f"Secondary coordinates must use {coordinate_crs}; got {district_geometry.crs}")
    if anchor_method != "centroid_inside_else_point_on_surface":
        raise SecondaryClusterError(f"Unsupported coordinate anchor method: {anchor_method!r}")
    if district_geometry["dist_id"].astype(str).duplicated().any():
        raise SecondaryClusterError("District geometry keys are not unique")
    if district_geometry.geometry.isna().any() or district_geometry.geometry.is_empty.any():
        raise SecondaryClusterError("District geometry contains missing/empty shapes")
    frame = district_geometry.sort_values("dist_id", kind="mergesort").copy()
    anchors: list[Any] = []
    anchor_methods: list[str] = []
    for geom in frame.geometry:
        centroid = geom.centroid
        if geom.covers(centroid):
            point = centroid
            method = "polygon_centroid"
        else:
            point = geom.representative_point()
            method = "point_on_surface"
        if not geom.covers(point):
            raise SecondaryClusterError("Derived SaTScan anchor is outside its governed district geometry")
        anchors.append(point)
        anchor_methods.append(method)
    result = pd.DataFrame({
        "location_id": np.arange(1, len(frame) + 1, dtype=int),
        "unit_id": frame["dist_id"].astype(str).to_numpy(),
        "unit_name": frame["dist_name"].astype(str).to_numpy(),
        "parent_code": frame["zone_code"].astype(str).to_numpy(),
        "parent_name": frame["zone_name"].astype(str).to_numpy(),
        "x": np.asarray([point.x for point in anchors], dtype=float),
        "y": np.asarray([point.y for point in anchors], dtype=float),
        "crs": coordinate_crs,
        "anchor_method": anchor_methods,
        "anchor_rule": anchor_method,
        "anchor_covered_by_geometry": True,
    })
    if not np.isfinite(result[["x", "y"]].to_numpy(dtype=float)).all():
        raise SecondaryClusterError("Non-finite district coordinates")
    return result


def _eligible_units_for_scenario(
    scenario: ScanScenario, authorities: DataAuthorities, analysis: AnalysisContract
) -> tuple[list[str], dict[str, str]]:
    if scenario.temporal_window == "long_run":
        mask = long_run_ba_district_mask(authorities.district_panel, authorities.district_geometry, analysis)
    elif scenario.temporal_window == "overlap_monthly":
        mask = paired_ba_viirs_district_mask(authorities.district_panel, authorities.district_geometry, analysis)
    else:
        raise SecondaryClusterError("Unsupported secondary temporal window")
    reasons = {str(r.unit_id): str(r.exclusion_reasons) for r in mask.units.itertuples(index=False)}
    return sorted(mask.units.loc[mask.units["eligible"], "unit_id"].astype(str).tolist()), reasons


def _scenario_support_panel(
    scenario: ScanScenario, authorities: DataAuthorities, analysis: AnalysisContract
) -> tuple[pd.DataFrame, list[str], dict[str, str]]:
    columns = ["unit_id", "unit_name", "parent_code", "parent_name", "yyyymm", "year", "month", scenario.case_field]
    if scenario.population_field:
        columns.append(scenario.population_field)
    _require_columns(authorities.district_panel, columns, scenario.scenario_id)
    start, end = _window_bounds(analysis, scenario.temporal_window)
    months = _months(start, end)
    keys = {int(p.year * 100 + p.month) for p in months}
    units, reasons = _eligible_units_for_scenario(scenario, authorities, analysis)
    panel = authorities.district_panel[
        authorities.district_panel["unit_id"].astype(str).isin(units)
        & authorities.district_panel["yyyymm"].astype(int).isin(keys)
    ].copy()
    expected = len(units) * len(months)
    if len(panel) != expected or panel[["unit_id", "yyyymm"]].duplicated().any():
        raise SecondaryClusterError(f"{scenario.scenario_id} does not have the exact complete unit-month spine")
    if sorted(panel["yyyymm"].astype(int).unique()) != sorted(keys):
        raise SecondaryClusterError(f"{scenario.scenario_id} month support differs from the contract")
    return panel.sort_values(["unit_id", "yyyymm"], kind="mergesort").reset_index(drop=True), units, reasons


def _integer_cases(series: pd.Series, context: str) -> np.ndarray:
    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values < 0).any() or not np.allclose(values, np.rint(values)):
        raise SecondaryClusterError(f"{context} must contain finite non-negative integer counts")
    return np.rint(values).astype(np.int64)


def prepare_case_input(scenario: ScanScenario, support_panel: pd.DataFrame, location_authority: pd.DataFrame) -> pd.DataFrame:
    merged = support_panel.merge(location_authority[["location_id", "unit_id"]], on="unit_id", how="left", validate="many_to_one")
    if merged["location_id"].isna().any():
        raise SecondaryClusterError("Case input contains an unmapped governed district")
    merged["cases"] = _integer_cases(merged[scenario.case_field], scenario.case_field)
    positive = merged.loc[merged["cases"].gt(0), ["location_id", "cases", "year", "month", "yyyymm"]].copy()
    positive["location_id"] = positive["location_id"].astype(int)
    positive["date"] = positive.apply(lambda r: f"{int(r.year)}/{int(r.month)}/1", axis=1)
    return positive[["location_id", "cases", "date", "yyyymm"]].sort_values(["yyyymm", "location_id"], kind="mergesort").reset_index(drop=True)


def prepare_population_input(scenario: ScanScenario, support_panel: pd.DataFrame, location_authority: pd.DataFrame) -> pd.DataFrame:
    if not scenario.requires_population or not scenario.population_field:
        raise SecondaryClusterError("Space-time permutation scans must not receive a population/exposure file")
    merged = support_panel.merge(location_authority[["location_id", "unit_id"]], on="unit_id", how="left", validate="many_to_one")
    values = pd.to_numeric(merged[scenario.population_field], errors="coerce").to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise SecondaryClusterError("Poisson exposure contains missing/non-positive values")
    out = merged[["location_id", "year", "month", "yyyymm"]].copy()
    out["population"] = values
    out["location_id"] = out["location_id"].astype(int)
    out["date"] = out.apply(lambda r: f"{int(r.year)}/{int(r.month)}/1", axis=1)
    return out[["location_id", "date", "population", "yyyymm"]].sort_values(["yyyymm", "location_id"], kind="mergesort").reset_index(drop=True)


def prepare_location_input(location_authority: pd.DataFrame, eligible_units: Iterable[str]) -> pd.DataFrame:
    units = {str(x) for x in eligible_units}
    out = location_authority[location_authority["unit_id"].isin(units)][["location_id", "x", "y"]].copy()
    if len(out) != len(units):
        raise SecondaryClusterError("Coordinate authority does not contain every eligible district")
    return out.sort_values("location_id", kind="mergesort").reset_index(drop=True)


def prepare_time_input(analysis: AnalysisContract, temporal_window: str) -> pd.DataFrame:
    start, end = _window_bounds(analysis, temporal_window)
    return pd.DataFrame(
        [
            {"time_index": i, "yyyymm": int(p.year * 100 + p.month), "date": f"{p.year}/{p.month}/1"}
            for i, p in enumerate(_months(start, end), start=1)
        ]
    )


def validate_case_population_location_keys(
    scenario: ScanScenario,
    cases: pd.DataFrame,
    population: pd.DataFrame | None,
    locations: pd.DataFrame,
    time_authority: pd.DataFrame,
) -> None:
    loc_ids = set(locations["location_id"].astype(int))
    months = set(time_authority["yyyymm"].astype(int))
    if not set(cases["location_id"].astype(int)).issubset(loc_ids):
        raise SecondaryClusterError("Case input contains location IDs outside the coordinate authority")
    if not set(cases["yyyymm"].astype(int)).issubset(months):
        raise SecondaryClusterError("Case input contains dates outside the governed temporal window")
    if scenario.requires_population:
        if population is None:
            raise SecondaryClusterError("Discrete-Poisson scan requires a population file")
        if set(population["location_id"].astype(int)) != loc_ids or set(population["yyyymm"].astype(int)) != months:
            raise SecondaryClusterError("Population support does not match location/time authorities")
        if len(population) != len(loc_ids) * len(months) or population[["location_id", "yyyymm"]].duplicated().any():
            raise SecondaryClusterError("Population input must contain one row per eligible district-month")
    elif population is not None:
        raise SecondaryClusterError("VIIRS STP exposure/population generation is prohibited")


def validate_temporal_encoding(frame: pd.DataFrame, *, date_column: str = "date") -> None:
    pattern = re.compile(r"^(\d{4})/(\d{1,2})/1$")
    for token in frame[date_column].astype(str):
        match = pattern.fullmatch(token)
        if not match or not 1 <= int(match.group(2)) <= 12:
            raise SecondaryClusterError(f"Invalid monthly SaTScan date encoding: {token!r}")


def generate_parameter_file(
    scenario: ScanScenario,
    *,
    case_path: str,
    population_path: str | None,
    location_path: str,
    results_prefix: str,
    start: pd.Period,
    end: pd.Period,
    params: Any,
) -> str:
    try:
        return _generate_parameter_file(
            scenario_id=scenario.scenario_id,
            product=scenario.product,
            model=scenario.model,
            reporting=scenario.reporting_rule,
            case_path=case_path,
            population_path=population_path,
            coordinate_path=location_path,
            results_prefix=results_prefix,
            start_date=f"{start.year}/{start.month}/1",
            end_date=f"{end.year}/{end.month}/{end.days_in_month}",
            max_spatial_percent=scenario.max_spatial_percent,
            max_temporal_months=scenario.max_temporal_months,
            monte_carlo_replicates=int(params.monte_carlo_replicates),
            analysis_type=str(params.analysis_type),
            cluster_type=str(params.cluster_type),
            spatial_window_shape=str(params.spatial_window_shape),
            geographical_overlap=bool(params.geographical_overlap),
            gini_optimised_reporting=bool(params.gini_optimised_reporting),
            report_cluster_rank=bool(params.report_cluster_rank),
            scientific_seed=int(params.scientific_seed),
            user_defined_random_seed_supported=bool(params.user_defined_random_seed_supported),
            user_defined_random_seed_parameter=params.user_defined_random_seed_parameter,
            rng_authority=str(params.rng_authority),
            engine_rng_behaviour=str(params.engine_rng_behaviour),
        )
    except SaTScanIOError as exc:
        raise SecondaryClusterError(str(exc)) from exc



def _secondary_output_id(output_contract: Any, source_attribute: str) -> str:
    matches = [item.output_id for item in output_contract.secondary_outputs if item.source_attribute == source_attribute]
    if len(matches) != 1:
        raise SecondaryClusterError(f"Expected one secondary output for {source_attribute!r}; got {matches!r}")
    return matches[0]


def _secondary_output_registry(execution_state: str, output_contract: Any) -> pd.DataFrame:
    rows = []
    for item in output_contract.secondary_outputs:
        if item.source_attribute == "secondary_output_registry":
            availability = "AVAILABLE"
        elif item.requires_results_validated and execution_state != RESULTS_VALIDATED:
            availability = "AWAITING_EXTERNAL_RESULTS"
        else:
            availability = "AVAILABLE"
        rows.append(
            {
                "output_id": item.output_id,
                "source_attribute": item.source_attribute,
                "output_type": item.output_type,
                "requires_results_validated": bool(item.requires_results_validated),
                "availability": availability,
            }
        )
    return pd.DataFrame(rows).sort_values("output_id", kind="mergesort").reset_index(drop=True)


def _summarise_exclusions(reasons: Mapping[str, str], eligible: Sequence[str]) -> str:
    keep = set(eligible)
    counts: dict[str, int] = {}
    for unit, text in reasons.items():
        if unit in keep:
            continue
        for reason in filter(None, str(text).split(";")):
            counts[reason] = counts.get(reason, 0) + 1
    return "none" if not counts else ";".join(f"{key}:{counts[key]}" for key in sorted(counts))


def build_secondary_input_run(
    *,
    paths: ProjectPaths | None = None,
    bundle: ConfigurationBundle | None = None,
    authorities: DataAuthorities | None = None,
    run_id: str = "secondary_input_reference",
) -> SecondaryInputRun:
    """Build all Python-side secondary authorities without fabricating external output."""

    paths = paths or ProjectPaths.discover()
    bundle = bundle or load_configuration_bundle(paths.root / "config")
    authorities = authorities or load_data_authorities(paths, bundle.data_schema)
    summary: DataContractSummary = validate_data_authorities(authorities, bundle.analysis, bundle.data_schema)
    scenarios = load_scan_scenarios(bundle.analysis)
    params = satscan_parameters(bundle.analysis)
    location_authority = build_location_authority(
        authorities.district_geometry,
        coordinate_crs=params.coordinate_crs,
        anchor_method=params.coordinate_anchor_method,
    )

    run_dir = paths.create_run(run_id)
    writer = OutputWriter(run_dir, bundle.output)
    export_realised_configuration(bundle, run_dir)
    records: list[OutputRecord] = []
    table_dir = f"{SECONDARY_SECTION}/tables"
    scan_root = f"{SECONDARY_SECTION}/satscan"
    monte_carlo = int(params.monte_carlo_replicates)
    alpha = float(params.alpha)

    records.append(
        writer.write_csv(
            f"{table_dir}/{_secondary_output_id(bundle.output, 'location_authority')}.csv",
            location_authority.to_dict(orient="records"),
            columns=tuple(location_authority.columns),
        )
    )

    executable = find_satscan_executable()
    scenario_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    run_rows: list[dict[str, Any]] = []

    for scenario in scenarios:
        support, eligible, reasons = _scenario_support_panel(scenario, authorities, bundle.analysis)
        start, end = _window_bounds(bundle.analysis, scenario.temporal_window)
        cases = prepare_case_input(scenario, support, location_authority)
        coords = prepare_location_input(location_authority, eligible)
        times = prepare_time_input(bundle.analysis, scenario.temporal_window)
        population = prepare_population_input(scenario, support, location_authority) if scenario.requires_population else None
        validate_case_population_location_keys(scenario, cases, population, coords, times)
        validate_temporal_encoding(cases)
        if population is not None:
            validate_temporal_encoding(population)

        prefix = f"{scan_root}/{scenario.scenario_id}"
        case_rel = f"{prefix}/{scenario.scenario_id}.cas"
        geo_rel = f"{prefix}/{scenario.scenario_id}.geo"
        pop_rel = f"{prefix}/{scenario.scenario_id}.pop" if population is not None else ""
        prm_rel = f"{prefix}/{scenario.scenario_id}.prm"
        results_prefix = f"{prefix}/results/{scenario.scenario_id}"

        case_record = writer.write_text(case_rel, case_text(cases))
        geo_record = writer.write_text(geo_rel, coordinate_text(coords))
        records.extend([case_record, geo_record])
        pop_record: OutputRecord | None = None
        if population is not None:
            pop_record = writer.write_text(pop_rel, population_text(population))
            records.append(pop_record)

        prm_text = generate_parameter_file(
            scenario,
            case_path=case_rel,
            population_path=pop_rel or None,
            location_path=geo_rel,
            results_prefix=results_prefix,
            start=start,
            end=end,
            params=params,
        )
        prm_record = writer.write_text(prm_rel, prm_text)
        records.append(prm_record)
        (run_dir / f"{prefix}/results").mkdir(parents=True, exist_ok=True)
        marker_rel = f"{prefix}/results/EXTERNAL_RESULTS_REQUIRED.txt"
        marker = writer.write_text(
            marker_rel,
            "EXTERNAL_RESULTS_REQUIRED\nNo live SaTScan result is represented by this marker.\n",
        )
        records.append(marker)

        n_months = len(times)
        positive_rows = len(cases)
        total_cases = int(pd.to_numeric(support[scenario.case_field], errors="raise").sum())
        scenario_rows.append(
            {
                "model_id": scenario.scenario_id,
                "product": scenario.product,
                "source_family": scenario.source_family,
                "model": scenario.model,
                "case_field": scenario.case_field,
                "population_field": scenario.population_field or "",
                "exposure_semantics": scenario.exposure_semantics,
                "temporal_start": str(start),
                "temporal_end": str(end),
                "eligible_districts": len(eligible),
                "max_spatial_percent": scenario.max_spatial_percent,
                "max_temporal_months": scenario.max_temporal_months,
                "monte_carlo_replicates": monte_carlo,
                "alpha": alpha,
                "reporting_rule": scenario.reporting_rule,
                "geographical_overlap": bool(params.geographical_overlap),
                "report_cluster_rank": bool(params.report_cluster_rank),
                "scientific_seed": int(params.scientific_seed),
                "user_defined_random_seed_supported": bool(params.user_defined_random_seed_supported),
                "rng_authority": str(params.rng_authority),
                "engine_rng_behaviour": str(params.engine_rng_behaviour),
            }
        )
        audit_rows.append(
            {
                "model_id": scenario.scenario_id,
                "eligible_districts": len(eligible),
                "excluded_districts": len(location_authority) - len(eligible),
                "exclusion_reasons": _summarise_exclusions(reasons, eligible),
                "months": n_months,
                "unit_month_rows": len(support),
                "positive_case_rows": positive_rows,
                "zero_case_rows": len(support) - positive_rows,
                "total_cases": total_cases,
                "population_rows": 0 if population is None else len(population),
                "coordinate_rows": len(coords),
                "stp_exposure_absent": scenario.model != MODEL_SPACE_TIME_PERMUTATION or population is None,
            }
        )
        run_rows.append(
            {
                "model_id": scenario.scenario_id,
                "scenario_id": scenario.scenario_id,
                "product": scenario.product,
                "model": scenario.model,
                "reporting_rule": scenario.reporting_rule,
                "temporal_start": str(start),
                "temporal_end": str(end),
                "max_temporal_months": int(scenario.max_temporal_months),
                "execution_state": EXTERNAL_RESULTS_REQUIRED,
                "engine_version_authority": str(params.engine_version_authority),
                "scientific_seed": int(params.scientific_seed),
                "user_defined_random_seed_supported": bool(params.user_defined_random_seed_supported),
                "user_defined_random_seed_parameter": params.user_defined_random_seed_parameter,
                "rng_authority": str(params.rng_authority),
                "engine_rng_behaviour": str(params.engine_rng_behaviour),
                "satscan_executable_detected": bool(executable),
                "satscan_executable_path": executable or "",
                "satscan_executable_version": "",
                "satscan_executable_sha256": "",
                "prm_path": prm_rel,
                "prm_sha256": prm_record.sha256,
                "case_path": case_rel,
                "case_sha256": case_record.sha256,
                "coordinate_path": geo_rel,
                "coordinate_sha256": geo_record.sha256,
                "population_path": pop_rel,
                "population_sha256": "" if pop_record is None else pop_record.sha256,
                "results_prefix": results_prefix,
                "required_report_path": results_prefix,
                "required_cluster_path": f"{results_prefix}.col.txt",
                "required_membership_path": f"{results_prefix}.gis.txt",
                "parameter_linkage_validated": False,
                "live_execution_deferred": not bool(executable),
            }
        )

    scan_specification_registry = pd.DataFrame(scenario_rows).sort_values("model_id", kind="mergesort").reset_index(drop=True)
    input_audit = pd.DataFrame(audit_rows).sort_values("model_id", kind="mergesort").reset_index(drop=True)
    external_registry = pd.DataFrame(run_rows).sort_values("model_id", kind="mergesort").reset_index(drop=True)
    output_registry = _secondary_output_registry(EXTERNAL_RESULTS_REQUIRED, bundle.output)

    for source_attribute, frame in (
        ("scan_specification_registry", scan_specification_registry),
        ("input_audit", input_audit),
        ("secondary_run_registry", external_registry),
        ("secondary_output_registry", output_registry),
    ):
        records.append(
            writer.write_csv(
                f"{table_dir}/{_secondary_output_id(bundle.output, source_attribute)}.csv",
                frame.to_dict(orient="records"),
                columns=tuple(frame.columns),
            )
        )

    status = {
        "schema": "rp1-secondary-execution-status-v1",
        "analysis": "secondary_spatiotemporal_concentration",
        "scientific_role": str(bundle.analysis.secondary_analysis["role"]),
        "external_execution_state": EXTERNAL_RESULTS_REQUIRED,
        "satscan_executable_detected": bool(executable),
        "satscan_executable_path": executable,
        "satscan_engine": params.engine,
        "satscan_engine_version_authority": params.engine_version_authority,
        "live_satscan_execution": "DEFERRED_NO_QUALIFIED_EXECUTABLE" if not executable else "AVAILABLE_NOT_AUTORUN",
        "missing_external_results_interpretation": "EXTERNAL_RESULTS_REQUIRED_not_zero_clusters",
        "model_count": len(scenarios),
        "reporting_method": params.reporting_method,
        "geographical_overlap": params.geographical_overlap,
        "coordinate_anchor_method": params.coordinate_anchor_method,
        "max_spatial_percent": params.max_spatial_percent,
        "max_temporal_months": params.max_temporal_months,
        "monte_carlo_replicates": params.monte_carlo_replicates,
        "alpha": params.alpha,
        "report_cluster_rank": params.report_cluster_rank,
        "scientific_seed": params.scientific_seed,
        "user_defined_random_seed_supported": params.user_defined_random_seed_supported,
        "user_defined_random_seed_parameter": params.user_defined_random_seed_parameter,
        "rng_authority": params.rng_authority,
        "engine_rng_behaviour": params.engine_rng_behaviour,
        "configuration_sha256": bundle.aggregate_config_sha256,
    }
    records.append(
        writer.write_json(
            f"{SECONDARY_SECTION}/{_secondary_output_id(bundle.output, 'external_execution_status')}.json",
            status,
        )
    )

    return SecondaryInputRun(
        run_id=run_id,
        run_dir=run_dir,
        execution_state=EXTERNAL_RESULTS_REQUIRED,
        scan_specification_registry=scan_specification_registry,
        secondary_run_registry=external_registry,
        input_audit=input_audit,
        output_registry=output_registry,
        records=tuple(records),
    )


def _parse_result_month(value: object) -> pd.Period:
    text = str(value).replace("-", "/")
    parts = text.split("/")
    if len(parts) < 2:
        raise ExternalResultValidationError(f"Cannot parse SaTScan result month: {value!r}")
    return pd.Period(year=int(parts[0]), month=int(parts[1]), freq="M")


def build_cluster_summary_source(
    parsed_by_model: Mapping[str, ParsedSaTScanResults], scenarios: Sequence[ScanScenario]
) -> pd.DataFrame:
    """Build cluster-summary source from validated external results only."""

    scenario_map = {s.scenario_id: s for s in scenarios}
    rows: list[dict[str, Any]] = []
    for model_id in sorted(parsed_by_model):
        parsed = parsed_by_model[model_id]
        scenario = scenario_map[model_id]
        for row in parsed.clusters.itertuples(index=False):
            members = parsed.membership.loc[parsed.membership["cluster_id"].eq(row.cluster_id), "location_id"].astype(str).tolist()
            start, end = _parse_result_month(row.start_date), _parse_result_month(row.end_date)
            rows.append(
                {
                    "model_id": model_id,
                    "product": scenario.product,
                    "model": scenario.model,
                    "cluster_id": int(row.cluster_id),
                    "cluster_rank": int(row.cluster_rank),
                    "district_location_ids": "|".join(sorted(members, key=lambda x: int(x) if x.isdigit() else x)),
                    "start_month": str(start),
                    "end_month": str(end),
                    "duration_months": int(end.ordinal - start.ordinal + 1),
                    "case_count": row.case_count,
                    "expected_count": "" if scenario.model == MODEL_SPACE_TIME_PERMUTATION else row.expected_count,
                    "relative_risk": "" if scenario.model == MODEL_SPACE_TIME_PERMUTATION else row.relative_risk,
                    "likelihood_ratio": row.likelihood_ratio,
                    "p_value": row.p_value,
                    "reporting_rule": scenario.reporting_rule,
                }
            )
    columns = [
        "model_id", "product", "model", "cluster_id", "cluster_rank", "district_location_ids", "start_month",
        "end_month", "duration_months", "case_count", "expected_count", "relative_risk",
        "likelihood_ratio", "p_value", "reporting_rule",
    ]
    return pd.DataFrame(rows, columns=columns).sort_values(["model_id", "cluster_id"], kind="mergesort").reset_index(drop=True)


def build_cluster_membership_source(
    parsed_by_model: Mapping[str, ParsedSaTScanResults],
    scenarios: Sequence[ScanScenario],
    location_authority: pd.DataFrame,
) -> pd.DataFrame:
    """Build supplementary membership with cluster interval/rank authority attached."""

    scenario_map = {s.scenario_id: s for s in scenarios}
    loc = location_authority[["location_id", "unit_id", "unit_name", "parent_code", "parent_name"]].copy()
    loc["location_id"] = loc["location_id"].astype(str)
    rows: list[pd.DataFrame] = []
    for model_id in sorted(parsed_by_model):
        parsed = parsed_by_model[model_id]
        scenario = scenario_map[model_id]
        member = parsed.membership.merge(loc, on="location_id", how="left", validate="many_to_one")
        if member["unit_id"].isna().any():
            raise ExternalResultValidationError("Parsed cluster membership contains an unknown district")
        meta = parsed.clusters[["cluster_id", "cluster_rank", "start_date", "end_date"]].copy()
        meta["start_month"] = meta["start_date"].map(lambda x: str(_parse_result_month(x)))
        meta["end_month"] = meta["end_date"].map(lambda x: str(_parse_result_month(x)))
        meta = meta.drop(columns=["start_date", "end_date"])
        member = member.merge(meta, on="cluster_id", how="left", validate="many_to_one")
        if member[["cluster_rank", "start_month", "end_month"]].isna().any().any():
            raise ExternalResultValidationError("Parsed membership cannot be bound to cluster metadata")
        member.insert(0, "model_id", model_id)
        member.insert(1, "product", scenario.product)
        member.insert(2, "model", scenario.model)
        member["reporting_rule"] = scenario.reporting_rule
        rows.append(member)
    columns = [
        "model_id", "product", "model", "cluster_id", "cluster_rank", "location_id",
        "unit_id", "unit_name", "parent_code", "parent_name", "start_month", "end_month",
        "p_value_report", "p_value", "reporting_rule",
    ]
    if not rows:
        return pd.DataFrame(columns=columns)
    out = pd.concat(rows, ignore_index=True)
    return out[columns].sort_values(["model_id", "cluster_rank", "location_id"], kind="mergesort").reset_index(drop=True)


def build_cluster_map_source(
    cluster_summary_source: pd.DataFrame, cluster_membership_source: pd.DataFrame, location_authority: pd.DataFrame
) -> pd.DataFrame:
    """Build cluster-map source from validated cluster-membership authority.

    ``cluster_summary_source`` is used only as a consistency authority.  Cluster period and
    p-value fields already travel with the validated cluster-membership rows, which
    avoids re-merging duplicate metadata and keeps the map source bound to one
    external-result parse.
    """

    loc = location_authority[["location_id", "x", "y"]].copy()
    loc["location_id"] = loc["location_id"].astype(str)
    expected = set(zip(cluster_summary_source["model_id"].astype(str), cluster_summary_source["cluster_id"].astype(int), strict=False))
    observed = set(zip(cluster_membership_source["model_id"].astype(str), cluster_membership_source["cluster_id"].astype(int), strict=False))
    if not observed.issubset(expected):
        raise ExternalResultValidationError("Cluster-map membership contains cluster IDs absent from the validated cluster-summary authority")
    out = cluster_membership_source.merge(loc, on="location_id", how="left", validate="many_to_one")
    columns = [
        "model_id", "product", "model", "cluster_id", "cluster_rank", "location_id",
        "unit_id", "unit_name", "parent_code", "start_month", "end_month",
        "p_value", "reporting_rule", "x", "y",
    ]
    if out.empty:
        return pd.DataFrame(columns=columns)
    if out[["x", "y"]].isna().any().any():
        raise ExternalResultValidationError("Cluster-map membership contains an unknown location")
    return out[columns].sort_values(["model_id", "cluster_rank", "location_id"], kind="mergesort").reset_index(drop=True)


def assert_no_false_zero_cluster_output(run: SecondaryInputRun) -> None:
    if run.execution_state == EXTERNAL_RESULTS_REQUIRED:
        forbidden = {item.output_id for item in load_configuration_bundle(run.run_dir.parents[1] / "config").output.secondary_outputs if item.requires_results_validated}
        written = {p.stem for p in (run.run_dir / SECONDARY_SECTION / "tables").glob("*.csv")}
        if forbidden & written:
            raise SecondaryClusterError("Result-dependent secondary output exists without validated SaTScan results")


__all__ = [
    "INPUTS_READY", "EXTERNAL_RESULTS_REQUIRED", "RESULTS_VALIDATED", "MODEL_DISCRETE_POISSON",
    "MODEL_SPACE_TIME_PERMUTATION", "REPORTING_HIERARCHICAL", "SecondaryClusterError",
    "ExternalResultsRequired", "ExternalResultValidationError", "ScanScenario", "SecondaryInputRun",
    "load_scan_scenarios", "build_location_authority", "_scenario_support_panel",
    "prepare_case_input", "prepare_population_input", "prepare_location_input", "prepare_time_input",
    "validate_case_population_location_keys", "validate_temporal_encoding", "generate_parameter_file",
    "validate_external_results", "build_secondary_input_run", "build_cluster_summary_source", "build_cluster_map_source",
    "build_cluster_membership_source", "_secondary_output_registry", "assert_no_false_zero_cluster_output",
]
