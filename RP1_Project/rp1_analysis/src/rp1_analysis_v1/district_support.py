"""District burnable support, rate variability, and threshold sensitivities."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from numbers import Integral, Real

import geopandas as gpd
import numpy as np
import pandas as pd

from .config import rq1_spatial_parameters
from .contracts import AnalysisContract
from .data_io import DataAuthorities
from .fixed_denominator import constancy_policy
from .spatial_scale import (
    ANNUAL_RATE_FIELD,
    DEPARTURE_FIELD,
    PRIMARY_RATE_FIELD,
    RQ1Tables,
    within_acz_dispersion,
)
from .spatial_stats import build_rq1_spatial_association_authorities, queen_contiguity_weights
from .validation import DataContractSummary
from .variables import resolve_field_role


class DistrictSupportError(ValueError):
    """Raised for inconsistent district support or invalid computation settings."""


@dataclass(frozen=True, slots=True)
class DistrictSupportDiagnostics:
    """Source-grain district support and separately identified sensitivity results."""

    district_support: pd.DataFrame
    denominator_distribution: pd.DataFrame
    rate_variability: pd.DataFrame
    threshold_summary: pd.DataFrame
    threshold_by_acz: pd.DataFrame
    threshold_districts: pd.DataFrame
    proof_district_crosswalk: pd.DataFrame


# The IDs printed in WF26266_Proof_hi.pdf are labels, not source-data keys.
# The crosswalk records the verified identity of each district cited in the proof.
_PROOF_DISTRICT_IDS = (
    ("D008", 43, "ADAKLU", "Adaklu"),
    ("D198", 46, "SEKYERE AFRAM PLAINS NORTH", "Sekyere_Afram_Plains_North"),
)
_AREA = "fixed_burnable_union_km2"
_MAPPED_AREA = "cumulative_mapped_ba_km2"
_CASES = "cumulative_burned_pixel_cases"
_DISTRICT_FIELDS = ["unit_id", "unit_name", "parent_id", "parent_code", "parent_name"]
_SPATIAL_FIELDS = [
    "unit_id",
    "local_morans_i",
    "local_raw_p",
    "local_bh_q",
    "local_class",
    "neighbour_count",
    "spatial_status",
]
_INTERPRETABLE_LOCAL_CLASSES = ("HH", "LL", "HL", "LH", "NS")
_ENDPOINT_SPAN_TOLERANCE = 1e-12


def _require_columns(frame: pd.DataFrame, columns: Sequence[str], context: str) -> None:
    missing = sorted(set(columns).difference(frame.columns))
    if missing:
        raise DistrictSupportError(f"{context} is missing fields: {missing}")


def _integer(value: object, name: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < minimum:
        raise DistrictSupportError(f"{name} must be an integer of at least {minimum}")
    return int(value)


def _thresholds(values: Sequence[float]) -> tuple[float, ...]:
    if any(isinstance(value, bool) or not isinstance(value, Real) for value in values):
        raise DistrictSupportError("Burnable area thresholds must be numeric")
    area = tuple(float(value) for value in values)
    if not area or area[0] != 0 or any(not np.isfinite(value) or value < 0 for value in area):
        raise DistrictSupportError(
            "Thresholds must be finite, nonnegative, and start with the 0 km² baseline"
        )
    if any(lower >= upper for lower, upper in pairwise(area)):
        raise DistrictSupportError("Thresholds must be strictly increasing")
    return area


def _observed_support(
    authorities: DataAuthorities,
    data_contract: DataContractSummary,
    rq1: RQ1Tables,
    analysis: AnalysisContract,
    years: Sequence[int],
) -> pd.DataFrame:
    """Keep all district identities and derive full-window totals without filling nulls."""

    panel = authorities.district_panel
    mask = data_contract.long_run_mask.units
    area_field = str(resolve_field_role(analysis, "rq1.fixed_burnable_area"))
    burned_field = str(resolve_field_role(analysis, "rq1.burned_area"))
    cases_field = str(resolve_field_role(analysis, "secondary.mcd64a1_cases"))
    fields = [*_DISTRICT_FIELDS, "yyyymm", area_field, burned_field, cases_field]
    _require_columns(panel, fields, "district monthly panel")
    _require_columns(mask, ["unit_id", "eligible", "exclusion_reasons"], "RQ1 eligibility")
    start, end = years[0] * 100 + 1, years[-1] * 100 + 12
    months = panel["yyyymm"].astype(int)
    rows = panel.loc[months.between(start, end), fields].copy()
    rows["yyyymm"] = rows["yyyymm"].astype(int)
    rows["unit_id"] = rows["unit_id"].astype(str)
    if rows.duplicated(["unit_id", "yyyymm"]).any():
        raise DistrictSupportError("District monthly support contains duplicate unit-months")
    for field in (area_field, burned_field, cases_field):
        values = pd.to_numeric(rows[field], errors="raise")
        present = values.dropna().to_numpy(dtype=float)
        if not np.isfinite(present).all() or (present < 0).any():
            raise DistrictSupportError(
                f"District monthly field {field!r} must be nonnegative and finite if present"
            )
        if field == cases_field and not np.array_equal(present, np.rint(present)):
            raise DistrictSupportError("Mapped burned-pixel cases must be integer counts")
        rows[field] = values

    districts = rows[_DISTRICT_FIELDS].drop_duplicates()
    if districts["unit_id"].duplicated().any():
        raise DistrictSupportError("District identity or parent ACZ is inconsistent across months")
    grouped = rows.groupby("unit_id", sort=True, observed=True)
    n_months = 12 * len(years)
    month_range = pd.period_range(str(years[0]), f"{years[-1]}-12", freq="M")
    month_keys = set(month_range.year * 100 + month_range.month)
    if not set(rows["yyyymm"]).issubset(month_keys):
        raise DistrictSupportError("District monthly support contains a non-calendar month")
    totals = (
        grouped[[burned_field, cases_field]]
        .sum(min_count=n_months)
        .rename(columns={burned_field: _MAPPED_AREA, cases_field: _CASES})
    )
    denominators = grouped[area_field].agg(["count", "min", "max"])
    stable = denominators["count"].eq(n_months) & (denominators["max"] - denominators["min"]).le(
        constancy_policy(analysis)
    )
    earliest = rows.loc[rows["yyyymm"].eq(start)].set_index("unit_id")[area_field]
    totals[_AREA] = earliest.reindex(totals.index).where(stable)
    observed = mask[["unit_id", "eligible", "exclusion_reasons"]].rename(
        columns={"eligible": "baseline_eligible", "exclusion_reasons": "baseline_exclusion_reason"}
    )
    observed = observed.assign(unit_id=observed["unit_id"].astype(str)).merge(
        districts, on="unit_id", how="left", validate="one_to_one"
    )
    observed = observed.merge(
        totals, left_on="unit_id", right_index=True, how="left", validate="one_to_one"
    )
    core = rq1.district_scale_authority
    _require_columns(
        core,
        [
            "unit_id",
            _AREA,
            "ba_total_km2",
            "acz_mean_annual_ba_rate",
            PRIMARY_RATE_FIELD,
            DEPARTURE_FIELD,
        ],
        "RQ1 district authority",
    )
    observed = observed.merge(
        core[
            [
                "unit_id",
                _AREA,
                "ba_total_km2",
                "acz_mean_annual_ba_rate",
                PRIMARY_RATE_FIELD,
                DEPARTURE_FIELD,
            ]
        ],
        on="unit_id",
        how="left",
        validate="one_to_one",
        suffixes=("", "_rq1"),
    )
    eligible = observed.loc[observed["baseline_eligible"]]
    if len(eligible) == 0 or set(eligible["unit_id"]) != set(core["unit_id"]):
        raise DistrictSupportError("District rate authority and baseline eligibility disagree")
    if not np.array_equal(eligible[_AREA], eligible[f"{_AREA}_rq1"]) or not np.allclose(
        eligible[_MAPPED_AREA],
        eligible["ba_total_km2"],
        rtol=1e-12,
        atol=1e-10,
    ):
        raise DistrictSupportError("District monthly totals or fixed union do not reconcile to RQ1")
    if eligible[_CASES].isna().any() or eligible[_AREA].le(0).any():
        raise DistrictSupportError(
            "Baseline district eligibility requires complete cases and positive support"
        )
    observed[_CASES] = observed[_CASES].astype("Int64")
    return (
        observed.drop(columns=[f"{_AREA}_rq1", "ba_total_km2"])
        .rename(
            columns={
                "acz_mean_annual_ba_rate": "direct_parent_acz_rate",
                PRIMARY_RATE_FIELD: "long_run_rate",
                DEPARTURE_FIELD: "district_departure",
            }
        )
        .sort_values("unit_id")
        .reset_index(drop=True)
    )


def _annual_rates(rq1: RQ1Tables, support: pd.DataFrame, years: Sequence[int]) -> pd.DataFrame:
    annual = rq1.district_annual_rates
    _require_columns(annual, ["unit_id", "year", ANNUAL_RATE_FIELD], "annual RQ1 district rates")
    if annual.duplicated(["unit_id", "year"]).any():
        raise DistrictSupportError("Annual rate table has duplicate unit-years")
    matrix = annual.pivot(index="unit_id", columns="year", values=ANNUAL_RATE_FIELD).sort_index()
    eligible = support.loc[support["baseline_eligible"]].set_index("unit_id")
    if list(matrix.columns) != list(years) or not matrix.index.equals(eligible.index):
        raise DistrictSupportError(
            "Annual rate table does not cover the baseline districts and configured years"
        )
    values = matrix.to_numpy(dtype=float)
    if (
        not np.isfinite(values).all()
        or (values < 0).any()
        or not np.allclose(
            values.mean(axis=1),
            eligible["long_run_rate"],
            rtol=1e-12,
            atol=1e-10,
        )
    ):
        raise DistrictSupportError(
            "Annual rates do not reconcile to finite baseline long-run rates"
        )
    return matrix


def _describe_rates(annual: pd.DataFrame) -> pd.DataFrame:
    rate = annual.to_numpy(dtype=float)
    q25, median, q75 = np.quantile(rate, [0.25, 0.5, 0.75], axis=1, method="linear")
    middle = rate.shape[1] // 2
    return pd.DataFrame(
        {
            "unit_id": annual.index,
            "observed_years": rate.shape[1],
            "positive_mapped_years": (rate > 0).sum(axis=1),
            "annual_rate_q25": q25,
            "annual_rate_median": median,
            "annual_rate_q75": q75,
            "annual_rate_iqr": q75 - q25,
            "first_period_start_year": annual.columns[0],
            "first_period_end_year": annual.columns[middle - 1],
            "first_period_mean_rate": rate[:, :middle].mean(axis=1),
            "second_period_start_year": annual.columns[middle],
            "second_period_end_year": annual.columns[-1],
            "second_period_mean_rate": rate[:, middle:].mean(axis=1),
        }
    )


def _circular_block_multiplicities(
    n_years: int,
    block_length: int,
    replications: int,
    seed: int,
) -> np.ndarray:
    """Draw one calendar-year resampling plan, shared by every district."""

    generator = np.random.default_rng(seed)
    n_blocks = (n_years + block_length - 1) // block_length
    starts = generator.integers(n_years, size=(replications, n_blocks))
    indexes = ((starts[..., None] + np.arange(block_length)) % n_years).reshape(replications, -1)
    multiplicities = np.zeros((replications, n_years), dtype=np.int64)
    np.add.at(multiplicities, (np.arange(replications)[:, None], indexes[:, :n_years]), 1)
    return multiplicities


def _rate_variability(
    annual: pd.DataFrame,
    block_lengths: Sequence[int],
    primary_block_length: int,
    replications: int,
    seed: int,
    confidence_level: float,
    materiality_fraction: float,
) -> pd.DataFrame:
    years = annual.shape[1]
    rate = annual.to_numpy(dtype=float)
    positive = (rate > 0).sum(axis=1)
    tail = (1 - confidence_level) / 2
    frames = []
    for block in block_lengths:
        weights = _circular_block_multiplicities(years, block, replications, seed)
        bootstrap_means = weights @ rate.T / years
        lower, upper = np.quantile(bootstrap_means, [tail, 1 - tail], axis=0, method="linear")
        status = np.select(
            [positive == 0, np.ptp(rate, axis=1) == 0, positive <= 2, lower == upper],
            [
                "all_zero_mapped_history",
                "constant_mapped_history",
                "sparse_mapped_history",
                "zero_interval_width",
            ],
            default="ok",
        )
        frames.append(
            pd.DataFrame(
                {
                    "unit_id": annual.index,
                    "block_length_years": block,
                    "is_primary_block": block == primary_block_length,
                    "lower_rate": lower,
                    "upper_rate": upper,
                    "interval_status": status,
                    "positive_mapped_years": positive,
                    "interval_method": "synchronised_circular_year_block_percentile",
                    "confidence_level": confidence_level,
                    "bootstrap_replications": replications,
                    "seed": seed,
                }
            )
        )
    return _describe_block_sensitivity(pd.concat(frames, ignore_index=True), materiality_fraction)


def _describe_block_sensitivity(intervals: pd.DataFrame, materiality_fraction: float) -> pd.DataFrame:
    """Compare the same lower and upper endpoints across block lengths by district.

    One quarter of the primary interval width gives the default materiality
    threshold in the annual-rate units. The comparison is a descriptive screen
    for sensitivity to block length.
    """

    endpoints = intervals.groupby("unit_id", sort=False)[["lower_rate", "upper_rate"]]
    spans = endpoints.max() - endpoints.min()
    primary = intervals.loc[intervals["is_primary_block"]].set_index("unit_id")
    summary = spans.rename(
        columns={"lower_rate": "lower_endpoint_span_rate", "upper_rate": "upper_endpoint_span_rate"}
    )
    summary["blocks_compared"] = endpoints.size()
    summary["primary_interval_width_rate"] = primary["upper_rate"] - primary["lower_rate"]
    summary["block_endpoint_materiality_fraction"] = materiality_fraction
    threshold = summary["primary_interval_width_rate"] * materiality_fraction
    summary["material_endpoint_shift_threshold_rate"] = threshold
    largest_span = spans.max(axis=1)
    sensitive = (largest_span > _ENDPOINT_SPAN_TOLERANCE) & (largest_span >= threshold)
    summary["materially_block_sensitive"] = sensitive.astype("boolean").where(
        summary["blocks_compared"] > 1
    )
    return intervals.join(summary, on="unit_id", validate="many_to_one")


def _denominator_distribution(support: pd.DataFrame) -> pd.DataFrame:
    records = []
    strata = [("national", "", "", support)]
    strata.extend(
        ("acz", str(code), str(group["parent_name"].iloc[0]), group)
        for code, group in support.groupby("parent_code", sort=True, observed=True)
    )
    for scope, parent_code, parent_name, group in strata:
        denominator = group[_AREA]
        eligible = group.loc[group["baseline_eligible"], _AREA]
        quantiles = eligible.quantile([0, 0.05, 0.25, 0.5, 0.75, 0.95, 1])
        records.append(
            {
                "scope": scope,
                "parent_code": parent_code,
                "parent_name": parent_name,
                "candidate_districts": len(group),
                "baseline_eligible_districts": len(eligible),
                "zero_union_districts": int(denominator.eq(0).sum()),
                "undefined_union_districts": int(denominator.isna().sum()),
                "minimum_km2": quantiles[0.0],
                "p05_km2": quantiles[0.05],
                "q25_km2": quantiles[0.25],
                "median_km2": quantiles[0.5],
                "q75_km2": quantiles[0.75],
                "p95_km2": quantiles[0.95],
                "maximum_km2": quantiles[1.0],
            }
        )
    return pd.DataFrame(records)


def _spatial_threshold(
    retained: pd.DataFrame,
    geometry: gpd.GeoDataFrame,
    analysis: AnalysisContract,
) -> tuple[dict[str, object], pd.DataFrame]:
    """Run the primary Moran procedures on the selected induced graph."""

    selected_geometry = geometry.loc[geometry["dist_id"].isin(retained["unit_id"])]
    if len(selected_geometry) != len(retained):
        raise DistrictSupportError("Threshold district selection does not reconcile to geometry")
    islands: tuple[str, ...] = ()
    n_effective = edges = 0
    if len(retained):
        weights = queen_contiguity_weights(
            selected_geometry,
            island_policy=rq1_spatial_parameters(analysis).island_policy,
        )
        islands = weights.islands
        n_effective = len(weights.active_ids)
        edges = sum(len(neighbours) for neighbours in weights.neighbours.values()) // 2
    if n_effective < 3:
        status = "insufficient_non_island_districts"
        ids = retained["unit_id"]
        local = pd.DataFrame(
            {
                "unit_id": ids,
                "local_morans_i": np.nan,
                "local_raw_p": np.nan,
                "local_bh_q": np.nan,
                "local_class": np.where(ids.isin(islands), "ISLAND", "UNDEFINED"),
                "neighbour_count": [len(weights.neighbours[unit]) for unit in ids]
                if len(ids)
                else [],
                "spatial_status": np.where(ids.isin(islands), "island", status),
            }
        )
        global_fields = {
            "global_morans_i": np.nan,
            "global_raw_p": np.nan,
            "spatial_status": status,
        }
    else:
        authority = build_rq1_spatial_association_authorities(retained, selected_geometry, analysis)
        result = authority.global_table.iloc[0]
        local = authority.local_table.rename(
            columns={
                "permutation_p": "local_raw_p",
                "bh_q": "local_bh_q",
                "lisa_class": "local_class",
                "diagnostic_status": "spatial_status",
            }
        )[_SPATIAL_FIELDS]
        global_fields = {
            "global_morans_i": result["morans_i"],
            "global_raw_p": result["permutation_p"],
            "spatial_status": result["diagnostic_status"],
        }
    return {
        **global_fields,
        "queen_edges": edges,
        "non_island_districts": n_effective,
        "island_districts": len(islands),
        "island_unit_ids": "|".join(islands),
        "local_bh_family_size": int(local["local_raw_p"].notna().sum()),
    }, local


def _departure_ranks(districts: pd.DataFrame, value: str) -> pd.Series:
    return districts.groupby("parent_id")[value].rank(method="average", ascending=False)


def _departure_by_acz(retained: pd.DataFrame) -> pd.DataFrame:
    def changed_count(values: pd.Series) -> int:
        return int(values.ne(0).sum())

    def max_abs_shift(values: pd.Series) -> float:
        return float(values.abs().max())

    return retained.groupby("parent_id", as_index=False).agg(
        departure_min=("district_departure", "min"),
        departure_p05=("district_departure", lambda values: values.quantile(0.05)),
        departure_median=("district_departure", "median"),
        departure_p95=("district_departure", lambda values: values.quantile(0.95)),
        departure_max=("district_departure", "max"),
        shared_departure_rank_change_count=("departure_rank_change_shared", changed_count),
        max_abs_shared_departure_rank_change=("departure_rank_change_shared", max_abs_shift),
        screening_departure_rank_shift_count=("departure_rank_shift_from_screening", changed_count),
        max_abs_screening_departure_rank_shift=("departure_rank_shift_from_screening", max_abs_shift),
    )


def _proof_district_crosswalk(districts: pd.DataFrame) -> pd.DataFrame:
    proof = pd.DataFrame(
        _PROOF_DISTRICT_IDS, columns=["proof_id", "proof_page", "proof_district_name", "unit_id"]
    )
    baseline = districts.loc[
        districts["minimum_fixed_union_km2"].eq(0),
        ["unit_id", "unit_name", "parent_code", _AREA, "long_run_rate", "district_departure",
         "baseline_departure_rank"],
    ]
    return proof.merge(baseline, on="unit_id", how="left", validate="one_to_one")


def _threshold_diagnostics(
    rq1: RQ1Tables,
    support: pd.DataFrame,
    geometry: gpd.GeoDataFrame,
    analysis: AnalysisContract,
    thresholds: Sequence[float],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    baseline = support.loc[support["baseline_eligible"]]
    reference = rq1.acz_fire_pattern_reference[
        ["unit_id", "unit_code", "unit_name", PRIMARY_RATE_FIELD]
    ].rename(
        columns={
            "unit_id": "parent_id",
            "unit_code": "parent_code",
            "unit_name": "parent_name",
            PRIMARY_RATE_FIELD: "direct_parent_acz_rate",
        }
    )
    core = rq1.district_scale_authority
    baseline_departures = baseline.set_index("unit_id")["district_departure"]
    baseline_ranks = _departure_ranks(baseline.set_index("unit_id"), "district_departure")
    baseline_classes = rq1.local_moran_authority.set_index("unit_id")["lisa_class"]
    settings = rq1_spatial_parameters(analysis)
    summary, acz_frames, district_frames = [], [], []
    for threshold in thresholds:
        retained = baseline.loc[baseline[_AREA].gt(threshold)]
        kept = core.loc[core["unit_id"].isin(retained["unit_id"])]
        scenario = (
            "baseline"
            if threshold == 0
            else f"burnable_area_gt_{np.format_float_positional(threshold, trim='-')}_km2"
        )
        identifiers = {"scenario_id": scenario, "minimum_fixed_union_km2": threshold}
        spatial, local = _spatial_threshold(kept, geometry, analysis)
        district = support[
            [
                *_DISTRICT_FIELDS,
                "baseline_eligible",
                "baseline_exclusion_reason",
                _AREA,
                _MAPPED_AREA,
                _CASES,
                "direct_parent_acz_rate",
                "long_run_rate",
                "district_departure",
            ]
        ].merge(local, on="unit_id", how="left", validate="one_to_one")
        district["included"] = district["unit_id"].isin(retained["unit_id"])
        district["exclusion_reason"] = np.select(
            [district["included"], district["baseline_eligible"]],
            ["", "at_or_below_minimum_fixed_union"],
            default=district["baseline_exclusion_reason"],
        )
        district["baseline_local_class"] = district["unit_id"].map(baseline_classes)
        comparable = district["local_class"].isin(_INTERPRETABLE_LOCAL_CLASSES) & district[
            "baseline_local_class"
        ].isin(_INTERPRETABLE_LOCAL_CLASSES)
        changed = district["local_class"].ne(district["baseline_local_class"]).astype("boolean")
        district["local_class_changed"] = changed.where(comparable)
        district["baseline_departure_rank"] = district["unit_id"].map(baseline_ranks)
        retained_ranks = district.loc[district["included"]].assign(
            baseline_departure=lambda rows: rows["unit_id"].map(baseline_departures)
        )
        district["retained_baseline_departure_rank"] = _departure_ranks(
            retained_ranks, "baseline_departure"
        )
        district["retained_departure_rank"] = _departure_ranks(retained_ranks, "district_departure")
        district["departure_rank_change_shared"] = (
            district["retained_departure_rank"] - district["retained_baseline_departure_rank"]
        )
        district["departure_rank_shift_from_screening"] = (
            district["retained_baseline_departure_rank"] - district["baseline_departure_rank"]
        )
        district_frames.append(
            district.assign(
                scenario_id=scenario,
                minimum_fixed_union_km2=threshold,
            )
        )
        removed = baseline.loc[~baseline["unit_id"].isin(retained["unit_id"])]
        base_case_total = int(baseline[_CASES].sum())
        summary.append(
            {
                **identifiers,
                "candidate_districts": len(support),
                "baseline_eligible_districts": len(baseline),
                "retained_districts": len(retained),
                "threshold_excluded_districts": len(removed),
                "retained_fixed_union_km2": float(retained[_AREA].sum()),
                "removed_fixed_union_km2": float(removed[_AREA].sum()),
                "removed_fixed_union_fraction": float(removed[_AREA].sum() / baseline[_AREA].sum()),
                "retained_burned_pixel_cases": int(retained[_CASES].sum()),
                "removed_burned_pixel_cases": int(removed[_CASES].sum()),
                "removed_burned_pixel_case_fraction": (
                    float(removed[_CASES].sum() / base_case_total) if base_case_total else np.nan
                ),
                **spatial,
                "global_permutations": settings.global_permutations,
                "local_permutations": settings.local_permutations,
                "permutation_seed": settings.random_seed,
                "local_bh_alpha": settings.alpha,
                **{
                    f"local_{label.lower()}_districts": int(local["local_class"].eq(label).sum())
                    for label in _INTERPRETABLE_LOCAL_CLASSES
                },
                "common_district_local_class_changes": int(district["local_class_changed"].sum()),
            }
        )

        zone_metrics = [
            "district_count",
            "district_rate_median",
            "district_rate_q25",
            "district_rate_q75",
            "district_rate_iqr",
            "district_rate_gini",
        ]
        if len(kept):
            acz = reference.merge(
                within_acz_dispersion(kept)[["parent_id", *zone_metrics]],
                on="parent_id",
                how="left",
                validate="one_to_one",
            )
        else:
            acz = reference.assign(**dict.fromkeys(zone_metrics, np.nan))
        acz = acz.merge(
            _departure_by_acz(district.loc[district["included"]]),
            on="parent_id",
            how="left",
            validate="one_to_one",
        )
        for column in (
            "district_count", "shared_departure_rank_change_count", "screening_departure_rank_shift_count"
        ):
            acz[column] = acz[column].fillna(0).astype(int)
        acz_frames.append(acz.assign(scenario_id=scenario, minimum_fixed_union_km2=threshold))

    return (
        pd.DataFrame(summary),
        pd.concat(acz_frames, ignore_index=True),
        pd.concat(district_frames, ignore_index=True),
    )


def build_district_support_diagnostics(
    rq1: RQ1Tables,
    authorities: DataAuthorities,
    data_contract: DataContractSummary,
    analysis: AnalysisContract,
    *,
    thresholds_km2: Sequence[float],
    block_lengths_years: Sequence[int],
    primary_block_length_years: int,
    bootstrap_replications: int,
    seed: int,
    confidence_level: float,
    block_endpoint_materiality_fraction: float = 0.25,
) -> DistrictSupportDiagnostics:
    """Build finite-record summaries and conditional resampling diagnostics.

    Circular blocks sample the annual mapped-rate series and keep each district's
    denominator fixed. Percentile intervals describe sampling variability under
    approximate stationarity and short-range dependence. They do not estimate
    errors in satellite mapping or the fixed 2001–2024 record. Each threshold
    uses the baseline direct parent-zone rates and its own induced Queen graph.
    """

    thresholds = _thresholds(thresholds_km2)
    replications = _integer(bootstrap_replications, "Bootstrap replications", 2)
    seed = _integer(seed, "Bootstrap seed", 0)
    lengths = tuple(sorted(_integer(block, "Block length", 1) for block in block_lengths_years))
    primary = _integer(primary_block_length_years, "Primary block length", 1)
    if len(lengths) != len(set(lengths)) or primary not in lengths:
        raise DistrictSupportError(
            "Block lengths must be distinct and include the primary block length"
        )
    if (
        isinstance(confidence_level, bool)
        or not isinstance(confidence_level, (int, float))
        or not 0.0 < confidence_level < 1.0
    ):
        raise DistrictSupportError("Confidence level must lie strictly between zero and one")
    if (
        isinstance(block_endpoint_materiality_fraction, bool)
        or not isinstance(block_endpoint_materiality_fraction, Real)
        or not 0 < block_endpoint_materiality_fraction <= 1
    ):
        raise DistrictSupportError("Block endpoint materiality fraction must lie in (0, 1]")

    window = analysis.study["temporal_windows"]["long_run"]
    start, end = pd.Period(str(window["start"]), freq="M"), pd.Period(str(window["end"]), freq="M")
    years = tuple(range(start.year, end.year + 1))
    if start.month != 1 or end.month != 12 or len(years) < 2 or lengths[-1] >= len(years):
        raise DistrictSupportError(
            "Bootstrap diagnostics require complete calendar years and blocks shorter than the window"
        )

    support = _observed_support(authorities, data_contract, rq1, analysis, years)
    annual = _annual_rates(rq1, support, years)
    support = support.merge(
        _describe_rates(annual), on="unit_id", how="left", validate="one_to_one"
    )
    for column in (
        "observed_years",
        "positive_mapped_years",
        "first_period_start_year",
        "first_period_end_year",
        "second_period_start_year",
        "second_period_end_year",
    ):
        support[column] = support[column].astype("Int64")
    summary, zone, district = _threshold_diagnostics(
        rq1, support, authorities.district_geometry, analysis, thresholds
    )
    return DistrictSupportDiagnostics(
        district_support=support,
        denominator_distribution=_denominator_distribution(support),
        rate_variability=_rate_variability(
            annual,
            lengths,
            primary,
            replications,
            seed,
            float(confidence_level),
            float(block_endpoint_materiality_fraction),
        ),
        threshold_summary=summary,
        threshold_by_acz=zone,
        threshold_districts=district,
        proof_district_crosswalk=_proof_district_crosswalk(district),
    )
