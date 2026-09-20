"""RQ1 spatial-support production for mapped burned area.

The module implements the configured RQ1 estimands without publication
interpretation.  ACZ quantities are calculated from the governed ACZ panel and
district quantities from the governed district panel.  The original-geometry
maximum-overlap crosswalk is a required provenance authority for district
parent assignment.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .config import AnalysisContract, rq1_spatial_parameters
from .data_io import DataAuthorities
from .inequality import gini_coefficient
from .seasonality import summarise_seasonality
from .validation import AnalyticalMask, DataContractSummary, reconcile_district_to_acz
from .variables import resolve_field_role


class SpatialScaleError(ValueError):
    """Raised when an RQ1 spatial-support calculation violates its contract."""


PRIMARY_RATE_FIELD = "mean_annual_ba_per100km2_fixed_support"
ANNUAL_RATE_FIELD = "annual_ba_per100km2_fixed_support"
DEPARTURE_FIELD = "within_acz_absolute_departure"


@dataclass(frozen=True, slots=True)
class RQ1Tables:
    """Complete RQ1 machine-readable production authorities.

    The object exposes semantic machine-readable authorities independent of manuscript numbering.
    """

    acz_fire_pattern_reference: pd.DataFrame
    within_acz_district_heterogeneity: pd.DataFrame
    district_scale_authority: pd.DataFrame
    spatial_autocorrelation: pd.DataFrame
    reconciliation: pd.DataFrame
    acz_annual_rates: pd.DataFrame = field(default_factory=pd.DataFrame)
    district_annual_rates: pd.DataFrame = field(default_factory=pd.DataFrame)
    district_metrics_source: pd.DataFrame = field(default_factory=pd.DataFrame)
    spatial_statistics_authority: pd.DataFrame = field(default_factory=pd.DataFrame)
    spatial_support_source: pd.DataFrame = field(default_factory=pd.DataFrame)
    seasonality_spatial_organisation_source: pd.DataFrame = field(default_factory=pd.DataFrame)
    rq1_realised_run_metadata: dict[str, Any] = field(default_factory=dict)
    local_moran_authority: pd.DataFrame = field(default_factory=pd.DataFrame)


def _require_columns(frame: pd.DataFrame, columns: Iterable[str], context: str) -> None:
    missing = sorted(set(columns).difference(frame.columns))
    if missing:
        raise SpatialScaleError(f"Missing required columns in {context}: {missing!r}")


def _finite_numeric(series: pd.Series, name: str, *, nonnegative: bool = False) -> np.ndarray:
    values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    if values.size == 0:
        raise SpatialScaleError(f"{name} is empty")
    if not np.isfinite(values).all():
        raise SpatialScaleError(f"{name} contains missing or non-finite values")
    if nonnegative and np.any(values < 0):
        raise SpatialScaleError(f"{name} contains negative values")
    return values


def _eligible_ids(mask: AnalyticalMask) -> tuple[str, ...]:
    required = {"unit_id", "eligible", "exclusion_reasons"}
    if not required.issubset(mask.units.columns):
        raise SpatialScaleError("Analytical mask does not expose governed eligibility fields")
    retained = mask.units.loc[mask.units["eligible"].astype(bool), "unit_id"].astype(str)
    if retained.duplicated().any():
        raise SpatialScaleError("Analytical mask contains duplicate retained unit IDs")
    return tuple(sorted(retained.tolist()))


def _filter_long_run(frame: pd.DataFrame, analysis: AnalysisContract) -> tuple[pd.DataFrame, int, tuple[int, ...]]:
    _require_columns(frame, ["yyyymm", "year", "month"], "long-run panel")
    window = analysis.study["temporal_windows"]["long_run"]
    start = pd.Period(str(window["start"]), freq="M")
    end = pd.Period(str(window["end"]), freq="M")
    yyyymm = pd.to_numeric(frame["yyyymm"], errors="coerce")
    start_key = start.year * 100 + start.month
    end_key = end.year * 100 + end.month
    selected = frame.loc[yyyymm.between(start_key, end_key)].copy()
    periods = pd.period_range(start, end, freq="M")
    expected_months = len(periods)
    years = tuple(range(start.year, end.year + 1))
    if selected.empty:
        raise SpatialScaleError("Long-run temporal filter produced no rows")
    return selected, expected_months, years


def _constant_positive(group: pd.DataFrame, field: str, context: str) -> float:
    values = _finite_numeric(group[field], f"{context}.{field}", nonnegative=True)
    unique = np.unique(values)
    if unique.size != 1:
        raise SpatialScaleError(f"{context}.{field} is not constant within the governed unit")
    value = float(unique[0])
    if value <= 0.0:
        raise SpatialScaleError(f"{context}.{field} must be strictly positive")
    return value


def _seasonality_fields(group: pd.DataFrame, ba_field: str) -> dict[str, float | int | str | None]:
    values = _finite_numeric(group[ba_field], ba_field, nonnegative=True)
    months = pd.to_numeric(group["month"], errors="raise").astype(int).tolist()
    summary = summarise_seasonality(values, months)
    fields: dict[str, float | int | str | None] = {
        "peak_month_descriptive": summary.peak_month,
        "circular_mean_direction_radians": summary.circular_mean_direction_radians,
        "circular_mean_month": summary.circular_mean_month,
        "mean_resultant_length": summary.mean_resultant_length,
        "seasonality_status": summary.status,
    }
    for month, climatology in enumerate(summary.monthly_climatology, start=1):
        fields[f"climatology_ba_km2_m{month:02d}"] = float(climatology)
    if summary.monthly_shares is None:
        for month in range(1, 13):
            fields[f"monthly_share_m{month:02d}"] = None
    else:
        for month, share in enumerate(summary.monthly_shares, start=1):
            fields[f"monthly_share_m{month:02d}"] = float(share)
    return fields


def _annual_rate_table_for_unit(
    group: pd.DataFrame,
    *,
    unit_id: str,
    ba_field: str,
    denominator: float,
    scale: float,
    expected_years: Sequence[int],
) -> pd.DataFrame:
    """Calculate the configured annual fixed-support rate explicitly year by year."""

    rows: list[dict[str, object]] = []
    observed_years = sorted(pd.to_numeric(group["year"], errors="raise").astype(int).unique())
    if observed_years != list(expected_years):
        raise SpatialScaleError(
            f"{unit_id!r} years do not match configured long-run support: {observed_years!r}"
        )
    for year in expected_years:
        annual = group.loc[pd.to_numeric(group["year"], errors="raise").astype(int).eq(year)]
        if len(annual) != 12:
            raise SpatialScaleError(f"{unit_id!r}/{year} has {len(annual)} months; expected 12")
        months = sorted(pd.to_numeric(annual["month"], errors="raise").astype(int).tolist())
        if months != list(range(1, 13)):
            raise SpatialScaleError(f"{unit_id!r}/{year} does not contain exactly calendar months 1..12")
        annual_ba = float(_finite_numeric(annual[ba_field], ba_field, nonnegative=True).sum())
        rows.append(
            {
                "unit_id": str(unit_id),
                "year": int(year),
                "annual_ba_km2": annual_ba,
                "fixed_burnable_union_km2": denominator,
                ANNUAL_RATE_FIELD: float(scale) * annual_ba / denominator,
            }
        )
    return pd.DataFrame(rows)


def _summarise_units(
    frame: pd.DataFrame,
    *,
    unit_id_col: str,
    unit_code_col: str,
    unit_name_col: str,
    parent_columns: Sequence[str] = (),
    analysis: AnalysisContract,
    expected_unit_ids: Sequence[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rq1 = analysis.research_questions["rq1"]
    annual_rate = rq1["annual_rate"]
    ba_field = str(resolve_field_role(analysis, str(annual_rate["numerator_role"])))
    denominator_field = str(resolve_field_role(analysis, str(annual_rate["denominator_role"])))
    required = [
        unit_id_col, unit_code_col, unit_name_col, "yyyymm", "year", "month",
        ba_field, denominator_field, *parent_columns,
    ]
    _require_columns(frame, required, "RQ1 summary input")
    long_run, expected_months, expected_years = _filter_long_run(frame, analysis)
    if expected_unit_ids is not None:
        expected = set(map(str, expected_unit_ids))
        observed_all = set(long_run[unit_id_col].astype(str))
        missing = sorted(expected.difference(observed_all))
        if missing:
            raise SpatialScaleError(f"Eligible units are absent from panel: {missing[:8]!r}")
        long_run = long_run.loc[long_run[unit_id_col].astype(str).isin(expected)].copy()

    rows: list[dict[str, object]] = []
    annual_frames: list[pd.DataFrame] = []
    for unit_id, group in long_run.groupby(unit_id_col, sort=True, observed=True):
        if len(group) != expected_months:
            raise SpatialScaleError(f"{unit_id!r} has {len(group)} long-run rows; expected {expected_months}")
        if group["yyyymm"].duplicated().any():
            raise SpatialScaleError(f"{unit_id!r} contains duplicate long-run months")
        denominator = _constant_positive(group, denominator_field, f"unit {unit_id}")
        annual = _annual_rate_table_for_unit(
            group,
            unit_id=str(unit_id),
            ba_field=ba_field,
            denominator=denominator,
            scale=float(annual_rate["scale_per_km2"]),
            expected_years=expected_years,
        )
        annual_frames.append(annual)
        total_ba = float(annual["annual_ba_km2"].sum())
        mean_annual_ba = float(annual["annual_ba_km2"].mean())
        mean_rate = float(annual[ANNUAL_RATE_FIELD].mean())
        code_values = group[unit_code_col].dropna().astype(str).unique()
        name_values = group[unit_name_col].dropna().astype(str).unique()
        if len(name_values) != 1:
            raise SpatialScaleError(f"{unit_id!r} has inconsistent unit names")
        row: dict[str, object] = {
            "unit_id": str(unit_id),
            "unit_code": None if len(code_values) == 0 else str(code_values[0]),
            "unit_name": str(name_values[0]),
            "n_months": int(len(group)),
            "n_years": int(len(expected_years)),
            "ba_total_km2": total_ba,
            "mean_annual_ba_km2": mean_annual_ba,
            "fixed_burnable_union_km2": denominator,
            PRIMARY_RATE_FIELD: mean_rate,
        }
        for parent_col in parent_columns:
            values = group[parent_col].dropna().astype(str).unique()
            if len(values) != 1:
                raise SpatialScaleError(f"{unit_id!r} has inconsistent {parent_col}")
            row[parent_col] = str(values[0])
        row.update(_seasonality_fields(group, ba_field))
        rows.append(row)

    result = pd.DataFrame(rows).sort_values("unit_id").reset_index(drop=True)
    annual_result = pd.concat(annual_frames, ignore_index=True).sort_values(["unit_id", "year"]).reset_index(drop=True)
    if expected_unit_ids is not None and len(result) != len(set(expected_unit_ids)):
        raise SpatialScaleError("RQ1 summary did not retain exactly the governed analytical population")
    return result, annual_result


def acz_long_run_burned_area_summary(acz_panel: pd.DataFrame, analysis: AnalysisContract) -> pd.DataFrame:
    """Summarise RQ1 directly from the governed ACZ support."""

    result, _ = _summarise_units(
        acz_panel, unit_id_col="unit_id", unit_code_col="unit_code",
        unit_name_col="unit_name", analysis=analysis,
    )
    expected = int(analysis.study["populations"]["acz_monthly"]["units"])
    if len(result) != expected:
        raise SpatialScaleError(f"ACZ summary contains {len(result)} units; expected {expected}")
    return result


def district_long_run_burned_area_summary(
    district_panel: pd.DataFrame,
    analysis: AnalysisContract,
    long_run_mask: AnalyticalMask,
) -> pd.DataFrame:
    """Summarise RQ1 directly from the governed eligible district support."""

    result, _ = _summarise_units(
        district_panel,
        unit_id_col="unit_id", unit_code_col="unit_code", unit_name_col="unit_name",
        parent_columns=("parent_id", "parent_code", "parent_name"),
        analysis=analysis, expected_unit_ids=_eligible_ids(long_run_mask),
    )
    return result


def _annual_support_tables(
    authorities: DataAuthorities,
    analysis: AnalysisContract,
    mask: AnalyticalMask,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    acz_summary, acz_annual = _summarise_units(
        authorities.acz_panel, unit_id_col="unit_id", unit_code_col="unit_code",
        unit_name_col="unit_name", analysis=analysis,
    )
    district_summary, district_annual = _summarise_units(
        authorities.district_panel, unit_id_col="unit_id", unit_code_col="unit_code",
        unit_name_col="unit_name", parent_columns=("parent_id", "parent_code", "parent_name"),
        analysis=analysis, expected_unit_ids=_eligible_ids(mask),
    )
    acz_meta = acz_summary[["unit_id", "unit_code", "unit_name"]]
    district_meta = district_summary[["unit_id", "unit_code", "unit_name", "parent_id", "parent_code", "parent_name"]]
    return (
        acz_annual.merge(acz_meta, on="unit_id", validate="many_to_one"),
        district_annual.merge(district_meta, on="unit_id", validate="many_to_one"),
    )


def cross_scale_reconciliation(
    district_panel: pd.DataFrame, acz_panel: pd.DataFrame, analysis: AnalysisContract
) -> pd.DataFrame:
    """Verify configured additive RQ1 BA/support quantities before comparison."""

    annual_rate = analysis.research_questions["rq1"]["annual_rate"]
    ba_field = str(resolve_field_role(analysis, str(annual_rate["numerator_role"])))
    denominator_field = str(resolve_field_role(analysis, str(annual_rate["denominator_role"])))
    return reconcile_district_to_acz(district_panel, acz_panel, fields=[ba_field, denominator_field])


def within_acz_dispersion(
    district_summary: pd.DataFrame, *, statistic_col: str = PRIMARY_RATE_FIELD
) -> pd.DataFrame:
    """Return within-parent-ACZ median, IQR and Gini of district long-run rates."""

    _require_columns(district_summary, ["parent_id", "parent_code", "parent_name", statistic_col], "within-ACZ heterogeneity")
    rows: list[dict[str, object]] = []
    for parent_id, group in district_summary.groupby("parent_id", sort=True, observed=True):
        rates = _finite_numeric(group[statistic_col], statistic_col, nonnegative=True)
        q25, median, q75 = (float(x) for x in np.percentile(rates, [25, 50, 75]))
        rows.append({
            "parent_id": str(parent_id), "parent_code": str(group["parent_code"].iloc[0]),
            "parent_name": str(group["parent_name"].iloc[0]), "district_count": int(len(group)),
            "rate_statistic": statistic_col, "district_rate_median": median,
            "district_rate_q25": q25, "district_rate_q75": q75,
            "district_rate_iqr": q75 - q25, "district_rate_gini": gini_coefficient(rates),
        })
    return pd.DataFrame(rows).sort_values("parent_id").reset_index(drop=True)


def within_acz_absolute_departure(
    district_summary: pd.DataFrame,
    acz_summary: pd.DataFrame,
    *,
    district_statistic_col: str = PRIMARY_RATE_FIELD,
    acz_reference_col: str = PRIMARY_RATE_FIELD,
    output_col: str = DEPARTURE_FIELD,
) -> pd.DataFrame:
    """Compute raw ``district long-run rate - direct parent-ACZ long-run rate``."""

    _require_columns(district_summary, ["unit_id", "parent_id", "parent_code", district_statistic_col], "district departure input")
    _require_columns(acz_summary, ["unit_id", acz_reference_col], "ACZ departure reference")
    refs = acz_summary.set_index("unit_id")[acz_reference_col]
    rows: list[dict[str, object]] = []
    for _, source in district_summary.iterrows():
        parent_id = str(source["parent_id"])
        if parent_id not in refs.index:
            raise SpatialScaleError(f"No direct ACZ reference statistic for {parent_id!r}")
        district_value = float(source[district_statistic_col])
        reference = float(refs.loc[parent_id])
        if not np.isfinite([district_value, reference]).all():
            raise SpatialScaleError("Raw within-ACZ departure requires finite rate values")
        rows.append({
            "unit_id": str(source["unit_id"]), "parent_id": parent_id,
            "parent_code": str(source["parent_code"]),
            "district_mean_annual_ba_rate": district_value,
            "acz_mean_annual_ba_rate": reference,
            output_col: district_value - reference,
        })
    return pd.DataFrame(rows).sort_values("unit_id").reset_index(drop=True)


def _validate_and_merge_crosswalk(
    district_summary: pd.DataFrame,
    crosswalk: pd.DataFrame,
    provenance: dict[str, Any],
) -> pd.DataFrame:
    """Bind eligible district summaries to original-polygon maximum-overlap provenance."""

    required = {
        "district_id", "zone_id", "zone_code", "zone_name", "original_district_area_sq_km",
        "dominant_overlap_area_sq_km", "dominant_overlap_share", "assignment_method", "working_crs",
    }
    missing = sorted(required.difference(crosswalk.columns))
    if missing:
        raise SpatialScaleError(f"Governed crosswalk is missing fields: {missing!r}")
    cross = crosswalk.copy()
    cross["district_id"] = cross["district_id"].astype(str)
    if cross["district_id"].duplicated().any():
        raise SpatialScaleError("Governed crosswalk contains duplicate district IDs")
    eligible = set(district_summary["unit_id"].astype(str))
    selected = cross.loc[cross["district_id"].isin(eligible)].copy()
    if len(selected) != len(eligible):
        missing_ids = sorted(eligible.difference(set(selected["district_id"])))
        raise SpatialScaleError(f"Crosswalk is missing eligible districts: {missing_ids[:8]!r}")
    check = district_summary[["unit_id", "parent_id", "parent_code"]].merge(
        selected[["district_id", "zone_id", "zone_code"]],
        left_on="unit_id", right_on="district_id", validate="one_to_one",
    )
    bad = check.loc[
        check["parent_id"].astype(str).ne(check["zone_id"].astype(str))
        | check["parent_code"].astype(str).str.upper().ne(check["zone_code"].astype(str).str.upper())
    ]
    if not bad.empty:
        raise SpatialScaleError(
            "Panel parent assignment conflicts with governed maximum-overlap crosswalk: "
            + ", ".join(bad["unit_id"].astype(str).head(8))
        )
    share = pd.to_numeric(selected["dominant_overlap_share"], errors="coerce")
    if share.isna().any() or (~share.between(0.0, 1.0, inclusive="both")).any():
        raise SpatialScaleError("Dominant overlap shares must be finite values in [0,1]")
    try:
        crosswalk_sha = str(provenance["crosswalk"]["sha256"])
        district_geometry_sha = str(provenance["source_district_geometry"]["bundle_sha256"])
        acz_geometry_sha = str(provenance["source_acz_geometry"]["bundle_sha256"])
        analysis_crs = str(provenance["analysis_crs"])
        implementation_identity = str(provenance["implementation_identity"])
    except (KeyError, TypeError) as exc:
        raise SpatialScaleError("Crosswalk provenance is missing required source identities") from exc
    selected = selected.rename(columns={
        "district_id": "unit_id", "zone_id": "crosswalk_parent_id",
        "zone_code": "crosswalk_parent_code", "zone_name": "crosswalk_parent_name",
    })
    selected["crosswalk_sha256"] = crosswalk_sha
    selected["source_district_geometry_bundle_sha256"] = district_geometry_sha
    selected["source_acz_geometry_bundle_sha256"] = acz_geometry_sha
    selected["crosswalk_analysis_crs"] = analysis_crs
    selected["crosswalk_implementation_identity"] = implementation_identity
    keep = [
        "unit_id", "crosswalk_parent_id", "crosswalk_parent_code", "crosswalk_parent_name",
        "original_district_area_sq_km", "dominant_overlap_area_sq_km", "dominant_overlap_share",
        "assignment_method", "working_crs", "crosswalk_sha256",
        "source_district_geometry_bundle_sha256", "source_acz_geometry_bundle_sha256",
        "crosswalk_analysis_crs", "crosswalk_implementation_identity",
    ]
    return selected[keep].sort_values("unit_id").reset_index(drop=True)


def build_district_scale_authority(
    district_summary: pd.DataFrame,
    acz_summary: pd.DataFrame,
    *,
    crosswalk: pd.DataFrame | None = None,
    crosswalk_provenance: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Build the RQ1 district authority with optional governed overlap provenance."""

    departure = within_acz_absolute_departure(district_summary, acz_summary)
    climatology_cols = [c for c in district_summary.columns if c.startswith("climatology_ba_km2_m") or c.startswith("monthly_share_m")]
    base_cols = [
        "unit_id", "unit_name", "parent_id", "parent_code", "parent_name", "ba_total_km2",
        "mean_annual_ba_km2", "fixed_burnable_union_km2", PRIMARY_RATE_FIELD,
        "peak_month_descriptive", "circular_mean_direction_radians", "circular_mean_month",
        "mean_resultant_length", "seasonality_status", *climatology_cols,
    ]
    base = district_summary[base_cols].copy()
    keep = departure.drop(columns=["parent_id", "parent_code", "district_mean_annual_ba_rate"])
    result = base.merge(keep, on="unit_id", validate="one_to_one")
    if crosswalk is not None or crosswalk_provenance is not None:
        if crosswalk is None or crosswalk_provenance is None:
            raise SpatialScaleError("Crosswalk and provenance must be supplied together")
        provenance_table = _validate_and_merge_crosswalk(district_summary, crosswalk, crosswalk_provenance)
        result = result.merge(provenance_table, on="unit_id", validate="one_to_one")
    return result.sort_values(["parent_code", "unit_id"]).reset_index(drop=True)



def _build_district_metrics_source(district: pd.DataFrame) -> pd.DataFrame:
    required = [
        "unit_id", "unit_name", "parent_code", "parent_name", "dominant_overlap_share",
        PRIMARY_RATE_FIELD, DEPARTURE_FIELD, "circular_mean_month", "mean_resultant_length",
    ]
    _require_columns(district, required, "S2 district metrics")
    out = district[required + [
        c for c in (
            "crosswalk_sha256", "source_district_geometry_bundle_sha256",
            "source_acz_geometry_bundle_sha256", "crosswalk_analysis_crs",
            "crosswalk_implementation_identity",
        ) if c in district.columns
    ]].copy()
    return out.rename(columns={PRIMARY_RATE_FIELD: "long_run_rate", DEPARTURE_FIELD: "district_departure"}).sort_values("unit_id").reset_index(drop=True)


def _build_spatial_statistics_authority(global_table: pd.DataFrame, local_table: pd.DataFrame) -> pd.DataFrame:
    if len(global_table) != 1:
        raise SpatialScaleError("RQ1 requires exactly one national Global Moran result")
    g = global_table.iloc[0]
    rows: list[dict[str, object]] = [{
        "record_type": "global_moran_national", "unit_id": "NATIONAL",
        "global_morans_i": g["morans_i"], "global_permutation_p": g["permutation_p"],
        "local_morans_i": None, "local_raw_p": None, "local_bh_q": None,
        "local_class": None, "island": False, "n_effective": g["n_effective"],
        "permutations": g["permutations"], "random_seed": g["random_seed"],
    }]
    for rec in local_table.to_dict(orient="records"):
        rows.append({
            "record_type": "local_moran", "unit_id": rec["unit_id"],
            "global_morans_i": None, "global_permutation_p": None,
            "local_morans_i": rec["local_morans_i"], "local_raw_p": rec["permutation_p"],
            "local_bh_q": rec["bh_q"], "local_class": rec["lisa_class"],
            "island": rec["diagnostic_status"] == "island", "n_effective": None,
            "permutations": rec["permutations"], "random_seed": rec["random_seed"],
        })
    return pd.DataFrame(rows)


def _build_spatial_support_source(
    acz: pd.DataFrame,
    district: pd.DataFrame,
    mask: AnalyticalMask,
    crosswalk: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    cross = crosswalk.set_index(crosswalk["district_id"].astype(str))
    mask_table = mask.units.set_index(mask.units["unit_id"].astype(str))
    for unit_id in sorted(cross.index):
        cw = cross.loc[unit_id]
        eligible = bool(mask_table.loc[unit_id, "eligible"]) if unit_id in mask_table.index else False
        reasons = str(mask_table.loc[unit_id, "exclusion_reasons"]) if unit_id in mask_table.index else "not_in_long_run_mask"
        rows.append({
            "panel": "spatial_supports", "unit_id": unit_id, "unit_name": unit_id.replace("_", " "),
            "parent_code": str(cw["zone_code"]), "support_status": "eligible" if eligible else "excluded",
            "value": None, "exclusion_reasons": "" if eligible else reasons,
        })
    for rec in acz.to_dict(orient="records"):
        rows.append({
            "panel": "direct_acz_long_run_rate", "unit_id": rec["unit_id"], "unit_name": rec["unit_name"],
            "parent_code": rec["unit_code"], "support_status": "eligible", "value": rec[PRIMARY_RATE_FIELD],
            "exclusion_reasons": "",
        })
    for rec in district.to_dict(orient="records"):
        rows.append({
            "panel": "district_long_run_rate", "unit_id": rec["unit_id"], "unit_name": rec["unit_name"],
            "parent_code": rec["parent_code"], "support_status": "eligible", "value": rec[PRIMARY_RATE_FIELD],
            "exclusion_reasons": "",
        })
    return pd.DataFrame(rows)


def _build_seasonality_spatial_organisation_source(acz: pd.DataFrame, district: pd.DataFrame, local: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "panel", "record_type", "unit_id", "unit_name", "parent_code", "month", "value",
        "circular_mean_month", "mean_resultant_length", "local_class", "support_status", "exclusion_reasons",
    ]
    rows: list[dict[str, object]] = []
    for rec in acz.to_dict(orient="records"):
        for month in range(1, 13):
            rows.append({
                "panel": "acz_seasonality", "record_type": "acz_monthly_climatology",
                "unit_id": rec["unit_id"], "unit_name": rec["unit_name"], "parent_code": rec["unit_code"],
                "month": month, "value": rec[f"climatology_ba_km2_m{month:02d}"],
                "circular_mean_month": rec["circular_mean_month"], "mean_resultant_length": rec["mean_resultant_length"],
                "local_class": None, "support_status": "eligible", "exclusion_reasons": "",
            })
    for rec in district.to_dict(orient="records"):
        rows.append({
            "panel": "district_departure", "record_type": "district_departure",
            "unit_id": rec["unit_id"], "unit_name": rec["unit_name"], "parent_code": rec["parent_code"],
            "month": None, "value": rec[DEPARTURE_FIELD], "circular_mean_month": rec["circular_mean_month"],
            "mean_resultant_length": rec["mean_resultant_length"], "local_class": None,
            "support_status": "eligible", "exclusion_reasons": "",
        })
    district_names = district.set_index("unit_id")[["unit_name", "parent_code"]]
    for rec in local.to_dict(orient="records"):
        unit_id = str(rec["unit_id"])
        meta = district_names.loc[unit_id]
        rows.append({
            "panel": "local_moran", "record_type": "local_moran", "unit_id": unit_id,
            "unit_name": meta["unit_name"], "parent_code": meta["parent_code"], "month": None,
            "value": rec["local_morans_i"], "circular_mean_month": None, "mean_resultant_length": None,
            "local_class": rec["lisa_class"],
            "support_status": "island" if rec["diagnostic_status"] == "island" else "eligible",
            "exclusion_reasons": "queen_island" if rec["diagnostic_status"] == "island" else "",
        })
    return pd.DataFrame(rows, columns=columns)


def build_rq1_tables(
    authorities: DataAuthorities,
    data_contract: DataContractSummary,
    analysis: AnalysisContract,
) -> RQ1Tables:
    """Build the complete configured RQ1 production authority set."""

    if data_contract.long_run_eligible_count != data_contract.long_run_mask.retained_units:
        raise SpatialScaleError("Data-contract long-run population authority is inconsistent")

    reconciliation = cross_scale_reconciliation(authorities.district_panel, authorities.acz_panel, analysis)
    acz, acz_annual = _summarise_units(
        authorities.acz_panel, unit_id_col="unit_id", unit_code_col="unit_code", unit_name_col="unit_name", analysis=analysis,
    )
    expected_acz = int(analysis.study["populations"]["acz_monthly"]["units"])
    if len(acz) != expected_acz:
        raise SpatialScaleError(f"ACZ summary contains {len(acz)} units; expected {expected_acz}")
    district_summary, district_annual = _summarise_units(
        authorities.district_panel, unit_id_col="unit_id", unit_code_col="unit_code", unit_name_col="unit_name",
        parent_columns=("parent_id", "parent_code", "parent_name"), analysis=analysis,
        expected_unit_ids=_eligible_ids(data_contract.long_run_mask),
    )
    heterogeneity = within_acz_dispersion(district_summary)
    district = build_district_scale_authority(
        district_summary, acz,
        crosswalk=authorities.district_to_acz_crosswalk,
        crosswalk_provenance=authorities.district_to_acz_crosswalk_provenance,
    )

    from .spatial_stats import build_rq1_spatial_association_authorities

    spatial = build_rq1_spatial_association_authorities(district, authorities.district_geometry, analysis)
    if len(spatial.global_table) != 1:
        raise SpatialScaleError("Exactly one national Global Moran result is required")
    district_metrics = _build_district_metrics_source(district)
    spatial_statistics = _build_spatial_statistics_authority(spatial.global_table, spatial.local_table)
    spatial_support = _build_spatial_support_source(acz, district, data_contract.long_run_mask, authorities.district_to_acz_crosswalk)
    seasonality_spatial = _build_seasonality_spatial_organisation_source(acz, district, spatial.local_table)
    params = rq1_spatial_parameters(analysis)
    metadata: dict[str, Any] = {
        "schema_version": "rp1-rq1-realised-run-v1",
        "population": {
            "acz_units": int(len(acz)), "district_units": int(len(district)),
            "district_months": int(len(district_summary) * int(district_summary["n_months"].iloc[0])),
            "years": int(district_summary["n_years"].iloc[0]), "climatology_months": 12,
        },
        "rate": {"annual_rate_field": ANNUAL_RATE_FIELD, "long_run_rate_field": PRIMARY_RATE_FIELD},
        "crosswalk": {
            "sha256": str(authorities.district_to_acz_crosswalk_provenance["crosswalk"]["sha256"]),
            "source_district_geometry_bundle_sha256": str(authorities.district_to_acz_crosswalk_provenance["source_district_geometry"]["bundle_sha256"]),
            "source_acz_geometry_bundle_sha256": str(authorities.district_to_acz_crosswalk_provenance["source_acz_geometry"]["bundle_sha256"]),
            "analysis_crs": str(authorities.district_to_acz_crosswalk_provenance["analysis_crs"]),
        },
        "spatial": {
            "weight_method": params.weight_method, "weight_order": params.weight_order,
            "weight_transform": params.weight_transform, "island_policy": params.island_policy,
            "candidate_units": int(len(spatial.weights.ids)), "non_island_units": int(len(spatial.weights.active_ids)),
            "island_count": int(len(spatial.weights.islands)), "island_ids": list(spatial.weights.islands),
            "global_permutations": params.global_permutations, "local_permutations": params.local_permutations,
            "seed": params.random_seed, "local_p_value_method": params.local_p_value_method,
            "local_permutation_scheme": params.local_permutation_scheme,
            "multiplicity_method": params.multiplicity_method,
            "local_bh_family_size": int(len(spatial.weights.active_ids)),
        },
    }
    return RQ1Tables(
        acz_fire_pattern_reference=acz,
        within_acz_district_heterogeneity=heterogeneity,
        district_scale_authority=district,
        spatial_autocorrelation=spatial.global_table,
        reconciliation=reconciliation,
        acz_annual_rates=acz_annual.merge(acz[["unit_id", "unit_code", "unit_name"]], on="unit_id", validate="many_to_one"),
        district_annual_rates=district_annual.merge(
            district[["unit_id", "unit_name", "parent_id", "parent_code", "parent_name", "dominant_overlap_share"]],
            on="unit_id", validate="many_to_one",
        ),
        district_metrics_source=district_metrics,
        spatial_statistics_authority=spatial_statistics,
        spatial_support_source=spatial_support,
        seasonality_spatial_organisation_source=seasonality_spatial,
        rq1_realised_run_metadata=metadata,
        local_moran_authority=spatial.local_table,
    )
