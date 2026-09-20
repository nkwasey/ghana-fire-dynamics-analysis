"""RQ2 production: fixed-support annual trends with studentized permutation inference.

Scientific choices are supplied by the executable configuration and method-authority
contracts.  This module constructs the governed annual ACZ series, computes Sen's
slope as the effect-size estimate, executes the configured Romano--Tirlea
studentized global Mann--Kendall permutation test, and applies one five-member
Benjamini--Hochberg family.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import AnalysisContract, rq2_trend_parameters
from .contracts import MethodAuthorityContract
from .data_io import DataAuthorities
from .design import assert_execution_ready
from .inference import (
    benjamini_hochberg,
    sen_slope_point_estimate,
    studentized_global_mann_kendall_permutation,
)
from .method_authority import require_method_authority
from .validation import DataContractSummary
from .variables import resolve_field_role


class TrendRobustnessError(ValueError):
    """Raised when RQ2 construction violates the executable contract."""


PRIMARY_RATE = "annual_ba_per100km2_fixed_support"

PRIMARY_TREND_COLUMNS = (
    "unit_id", "parent_code", "parent_name", "n", "sen_slope",
    "effect_method_id", "effect_implementation_id", "u_n",
    "long_run_variance", "variance_floor", "variance_floor_used", "t_n",
    "realised_bandwidth", "bandwidth_rule", "permutation_count", "seed",
    "extreme_count", "raw_p", "method_id", "implementation_id",
    "empirical_cdf", "studentisation", "alternative", "p_value_method",
    "bh_q", "bh_rejected", "bh_alpha",
)


@dataclass(frozen=True, slots=True)
class RQ2Tables:
    primary_trend_authority: pd.DataFrame
    annual_acz_series: pd.DataFrame
    rq2_full_authority: pd.DataFrame
    annual_trend_source: pd.DataFrame
    realised_run_metadata: pd.DataFrame


def _require_columns(frame: pd.DataFrame, columns: Iterable[str], context: str) -> None:
    missing = sorted(set(columns).difference(frame.columns))
    if missing:
        raise TrendRobustnessError(f"Missing required columns in {context}: {missing!r}")


def _finite(values: pd.Series, name: str, *, nonnegative: bool = False) -> np.ndarray:
    arr = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    if arr.size == 0 or not np.isfinite(arr).all():
        raise TrendRobustnessError(f"{name} must contain finite numeric values")
    if nonnegative and np.any(arr < 0.0):
        raise TrendRobustnessError(f"{name} must be non-negative")
    return arr


def _window_years(analysis: AnalysisContract) -> list[int]:
    window = analysis.study["temporal_windows"]["long_run"]
    start = pd.Period(str(window["start"]), freq="M")
    end = pd.Period(str(window["end"]), freq="M")
    if start.month != 1 or end.month != 12:
        raise TrendRobustnessError("RQ2 long-run window must comprise complete calendar years")
    return list(range(start.year, end.year + 1))


def build_acz_annual_ba_series(acz_panel: pd.DataFrame, analysis: AnalysisContract) -> pd.DataFrame:
    """Construct complete annual fixed-support ACZ rates from configured roles."""

    rq2 = analysis.research_questions["rq2"]
    ba_field = str(resolve_field_role(analysis, str(rq2["rate"]["numerator_role"])))
    denominator_field = str(resolve_field_role(analysis, str(rq2["rate"]["denominator_role"])))
    keys = analysis.field_roles["keys"]
    unit_id = str(keys["unit_id"])
    unit_code = str(keys["unit_code"])
    unit_name = str(keys["unit_name"])
    yyyymm = str(keys["yyyymm"])
    year_field = str(keys["year"])
    month_field = str(keys["month"])
    _require_columns(
        acz_panel,
        [unit_id, unit_code, unit_name, yyyymm, year_field, month_field, ba_field, denominator_field],
        "ACZ panel",
    )
    years = _window_years(analysis)
    pop = analysis.study["populations"][str(rq2["population"])]
    expected_units = int(rq2["expected_series_count"])
    expected_n = int(rq2["expected_n_per_series"])
    if expected_units != int(pop["units"]):
        raise TrendRobustnessError("RQ2 series count disagrees with its configured population")
    if expected_n != len(years):
        raise TrendRobustnessError("RQ2 series length disagrees with its configured temporal window")
    scale = float(rq2["rate"]["scale_per_km2"])

    selected = acz_panel.loc[pd.to_numeric(acz_panel[year_field], errors="coerce").isin(years)].copy()
    units = selected[[unit_id, unit_code, unit_name]].drop_duplicates()
    if len(units) != expected_units:
        raise TrendRobustnessError(f"RQ2 requires {expected_units} ACZs; observed {len(units)}")

    rows: list[dict[str, object]] = []
    for uid, group in selected.groupby(unit_id, sort=True, observed=True):
        observed_years = sorted(pd.to_numeric(group[year_field], errors="raise").astype(int).unique())
        if observed_years != years:
            raise TrendRobustnessError(f"{uid!r} does not contain the configured RQ2 years")
        denominator_values = _finite(group[denominator_field], denominator_field, nonnegative=True)
        unique_denominator = np.unique(denominator_values)
        if unique_denominator.size != 1 or unique_denominator[0] <= 0.0:
            raise TrendRobustnessError(f"{uid!r} has invalid fixed support")
        fixed_denominator = float(unique_denominator[0])
        code = group[unit_code].dropna().astype(str).unique()
        name = group[unit_name].dropna().astype(str).unique()
        if len(code) != 1 or len(name) != 1:
            raise TrendRobustnessError(f"{uid!r} has inconsistent unit identity")
        for year in years:
            annual = group.loc[pd.to_numeric(group[year_field], errors="raise").astype(int).eq(year)].copy()
            months = sorted(pd.to_numeric(annual[month_field], errors="raise").astype(int).tolist())
            if months != list(range(1, 13)) or len(annual) != 12:
                raise TrendRobustnessError(f"{uid!r} year {year} lacks a complete monthly spine")
            if annual[yyyymm].duplicated().any():
                raise TrendRobustnessError(f"{uid!r} year {year} contains duplicate months")
            burned = float(_finite(annual[ba_field], ba_field, nonnegative=True).sum())
            rows.append(
                {
                    "unit_id": str(uid),
                    "unit_code": str(code[0]),
                    "unit_name": str(name[0]),
                    "year": int(year),
                    "annual_ba_km2": burned,
                    "fixed_burnable_km2": fixed_denominator,
                    PRIMARY_RATE: scale * burned / fixed_denominator,
                }
            )
    out = pd.DataFrame(rows).sort_values(["unit_id", "year"]).reset_index(drop=True)
    if len(out) != expected_units * expected_n:
        raise TrendRobustnessError("Annual ACZ series row count disagrees with configured population")
    return out


def build_rq2_tables(
    authorities: DataAuthorities,
    data_contract: DataContractSummary,
    analysis: AnalysisContract,
    methods: MethodAuthorityContract,
    *,
    configuration_sha256: str | None = None,
    dataset_sha256: str | None = None,
) -> RQ2Tables:
    """Build the complete five-ACZ RQ2 production authority."""

    del data_contract
    assert_execution_ready(analysis.to_dict(), methods, "rq2")
    params = rq2_trend_parameters(analysis)
    if params.rank_tie_contribution != "zero":
        raise TrendRobustnessError("RQ2 rank-tie contribution must remain zero")
    if params.multiple_testing_method != "benjamini_hochberg":
        raise TrendRobustnessError("RQ2 multiplicity method is not implemented")

    effect_authority = require_method_authority(methods, params.effect_estimator)
    test_authority = require_method_authority(methods, params.inferential_test)
    annual = build_acz_annual_ba_series(authorities.acz_panel, analysis)
    expected_series = int(analysis.research_questions["rq2"]["expected_series_count"])
    expected_n = int(analysis.research_questions["rq2"]["expected_n_per_series"])
    if params.family_size != expected_series:
        raise TrendRobustnessError("RQ2 BH family size must equal the configured ACZ series count")

    trend_rows: list[dict[str, object]] = []
    for uid, group in annual.groupby("unit_id", sort=True, observed=True):
        group = group.sort_values("year")
        values = group[PRIMARY_RATE].to_numpy(dtype=float)
        years = group["year"].to_numpy(dtype=float)
        if len(values) != expected_n:
            raise TrendRobustnessError(f"{uid!r} does not contain exactly {expected_n} annual values")
        sen = sen_slope_point_estimate(values, x=years)
        result = studentized_global_mann_kendall_permutation(
            values,
            bandwidth_rule=params.bandwidth_rule,
            variance_floor=params.variance_floor,
            replications=params.permutations,
            alternative=params.alternative,
            seed=params.random_seed,
            p_value_rule=params.p_value_method,
            empirical_cdf=params.empirical_cdf,
            studentisation=params.studentisation,
            method_id=test_authority.method_id,
            implementation_id=test_authority.implementation_id,
            requires_distinct_observations=params.requires_distinct_observations,
            on_ties=params.on_ties,
        )
        trend_rows.append(
            {
                "unit_id": str(uid),
                "parent_code": str(group["unit_code"].iloc[0]),
                "parent_name": str(group["unit_name"].iloc[0]),
                "n": int(result.n),
                "sen_slope": float(sen),
                "effect_method_id": effect_authority.method_id,
                "effect_implementation_id": effect_authority.implementation_id,
                "u_n": float(result.u_n),
                "long_run_variance": float(result.long_run_variance),
                "variance_floor": float(result.variance_floor),
                "variance_floor_used": bool(result.variance_floor_used),
                "t_n": float(result.t_n),
                "realised_bandwidth": int(result.realised_bandwidth),
                "bandwidth_rule": result.bandwidth_rule,
                "permutation_count": int(result.permutation_count),
                "seed": int(result.seed),
                "extreme_count": int(result.extreme_count),
                "raw_p": float(result.raw_p),
                "method_id": result.method_id,
                "implementation_id": result.implementation_id,
                "empirical_cdf": result.empirical_cdf,
                "studentisation": result.studentisation,
                "alternative": result.alternative,
                "p_value_method": result.p_value_method,
            }
        )

    primary = pd.DataFrame(trend_rows).sort_values("parent_code").reset_index(drop=True)
    if len(primary) != params.family_size or primary["unit_id"].nunique() != params.family_size:
        raise TrendRobustnessError("RQ2 production must contain exactly the configured five-test family")
    fdr = benjamini_hochberg(
        primary["raw_p"].to_numpy(dtype=float),
        family_name=str(analysis.research_questions["rq2"]["multiple_testing"]["family"]),
        alpha=params.alpha,
    )
    if fdr.n_tests != params.family_size:
        raise TrendRobustnessError("RQ2 BH family differs from the configured family size")
    primary["bh_q"] = np.asarray(fdr.adjusted_p_values, dtype=float)
    primary["bh_rejected"] = np.asarray(fdr.rejected, dtype=bool)
    primary["bh_alpha"] = float(params.alpha)
    primary = primary.loc[:, list(PRIMARY_TREND_COLUMNS)]

    annual_pub = annual.rename(
        columns={"unit_code": "parent_code", "unit_name": "parent_name", PRIMARY_RATE: "annual_rate"}
    )
    joined = annual_pub.merge(
        primary,
        on=["unit_id", "parent_code", "parent_name"],
        how="left",
        validate="many_to_one",
    )
    full_columns = [
        "parent_code", "parent_name", "unit_id", "year", "annual_rate", "annual_ba_km2",
        "fixed_burnable_km2", "n", "sen_slope", "u_n", "long_run_variance",
        "variance_floor", "variance_floor_used", "t_n", "realised_bandwidth",
        "bandwidth_rule", "permutation_count", "seed", "extreme_count", "raw_p", "bh_q",
        "bh_rejected", "bh_alpha", "effect_method_id", "method_id", "implementation_id",
        "empirical_cdf", "studentisation", "alternative", "p_value_method",
    ]
    full = joined.loc[:, full_columns].sort_values(["parent_code", "year"]).reset_index(drop=True)
    annual_trend = full[["parent_code", "parent_name", "year", "annual_rate", "sen_slope", "raw_p", "bh_q"]].copy()

    metadata = pd.DataFrame(
        [
            {
                "configuration_sha256": configuration_sha256 or "NOT_SUPPLIED",
                "dataset_sha256": dataset_sha256 or "NOT_SUPPLIED",
                "method_id": test_authority.method_id,
                "implementation_id": test_authority.implementation_id,
                "effect_method_id": effect_authority.method_id,
                "series_count": int(len(primary)),
                "n_per_series": expected_n,
                "realised_bandwidth": int(primary["realised_bandwidth"].iloc[0]),
                "bandwidth_rule": params.bandwidth_rule,
                "permutation_count": params.permutations,
                "seed": params.random_seed,
                "bh_family_size": params.family_size,
                "bh_alpha": params.alpha,
            }
        ]
    )
    return RQ2Tables(
        primary_trend_authority=primary,
        annual_acz_series=annual,
        rq2_full_authority=full,
        annual_trend_source=annual_trend,
        realised_run_metadata=metadata,
    )
