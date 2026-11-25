"""Build supplementary evidence from the same analytical authorities as the main results."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .contracts import AnalysisContract
from .data_io import DataAuthorities
from .design import rq1_support_sensitivity_settings
from .district_support import DistrictSupportDiagnostics, build_district_support_diagnostics
from .observability import RQ3Tables
from .spatial_scale import RQ1Tables
from .trend_robustness import RQ2Tables
from .trend_sensitivity import (
    TrendSensitivityResult,
    build_trend_sensitivity,
    settings_from_primary,
)
from .validation import DataContractSummary
from .viirs_confidence import build_viirs_confidence_audit

_SUPPORT_FIGURE_COLUMNS = (
    "record_type", "unit_id", "zone", "fixed_burnable_union_km2", "long_run_rate",
    "minimum_fixed_union_km2", "gini", "n_districts", "is_primary_threshold",
)
_TREND_FIGURE_COLUMNS = (
    "record_type", "parent_code", "sen_slope", "lower", "upper", "interval_status", "interval_level",
    "noise_scenario", "effect_pattern", "target_zone", "decline_fraction_per_decade",
    "power", "mc_lower", "mc_upper", "bank_min", "bank_max", "target_power",
)


def _support_figure(result: DistrictSupportDiagnostics, cutoff_km2: int) -> pd.DataFrame:
    districts = result.district_support.loc[
        result.district_support["baseline_eligible"],
        ["unit_id", "parent_code", "fixed_burnable_union_km2", "long_run_rate"],
    ].rename(columns={"parent_code": "zone"})
    thresholds = result.threshold_by_acz[[
        "parent_code", "minimum_fixed_union_km2", "district_rate_gini", "district_count"
    ]].rename(columns={"parent_code": "zone", "district_rate_gini": "gini", "district_count": "n_districts"})
    return pd.concat(
        [districts.assign(record_type="district", is_primary_threshold=False),
         thresholds.assign(
             record_type="threshold",
             is_primary_threshold=thresholds["minimum_fixed_union_km2"].eq(cutoff_km2),
         )],
        ignore_index=True,
    ).loc[:, _SUPPORT_FIGURE_COLUMNS]


def _trend_figure(result: TrendSensitivityResult) -> pd.DataFrame:
    intervals = result.intervals.loc[
        result.intervals["interval_role"].eq("calibrated_primary"),
        ["parent_code", "sen_slope", "interval_lower", "interval_upper", "status", "pointwise_interval_level"],
    ].rename(columns={
        "interval_lower": "lower", "interval_upper": "upper", "status": "interval_status",
        "pointwise_interval_level": "interval_level",
    })
    # Show the Transition zone under concurrent decline. The governed table
    # carries the full five-zone decision families and effect patterns.
    detectability = result.detectability
    curve = detectability.loc[
        detectability["parent_code"].eq("TZ")
        & detectability["effect_pattern"].isin(["all_zero", "concurrent_decline"]),
        ["parent_code", "noise_scenario", "effect_pattern", "target_zone", "decline_fraction_per_decade",
         "bh_rejection", "bh_rejection_lower_95", "bh_rejection_upper_95", "bh_bank_min", "bh_bank_max"],
    ].rename(columns={
        "bh_rejection": "power", "bh_rejection_lower_95": "mc_lower", "bh_rejection_upper_95": "mc_upper",
        "bh_bank_min": "bank_min", "bh_bank_max": "bank_max",
    })
    curve = curve.assign(
        effect_pattern="concurrent_decline", target_zone="TZ", target_power=result.settings["target_power"],
    )
    return pd.concat(
        [intervals.assign(record_type="interval"), curve.assign(record_type="detectability")], ignore_index=True,
    ).loc[:, _TREND_FIGURE_COLUMNS]


def build_supplementary_sources(
    rq1: RQ1Tables,
    rq2: RQ2Tables,
    rq3: RQ3Tables,
    authorities: DataAuthorities,
    data_contract: DataContractSummary,
    analysis: AnalysisContract,
    *,
    evidence_root: Path,
) -> dict[str, pd.DataFrame]:
    support_settings = rq1_support_sensitivity_settings(analysis.research_questions["rq1"])
    support = build_district_support_diagnostics(
        rq1, authorities, data_contract, analysis,
        thresholds_km2=support_settings.thresholds_km2,
        block_lengths_years=support_settings.block_lengths_years,
        primary_block_length_years=support_settings.primary_block_length_years,
        bootstrap_replications=support_settings.bootstrap_replications,
        seed=int(analysis.reproducibility["primary_seed"]),
        confidence_level=float(analysis.reproducibility["confidence_level"]),
        block_endpoint_materiality_fraction=support_settings.block_endpoint_materiality_fraction,
    )
    trend = build_trend_sensitivity(rq2.rq2_full_authority, settings=settings_from_primary(analysis))
    reference_slopes = rq2.rq2_full_authority.groupby("parent_code")["sen_slope"].first()
    observed_slopes = trend.intervals.loc[
        trend.intervals["interval_role"].eq("calibrated_primary")
    ].set_index("parent_code")["sen_slope"]
    if not np.allclose(reference_slopes.sort_index(), observed_slopes.sort_index(), rtol=1e-12, atol=1e-12):
        raise ValueError("Supplementary trend estimates disagree with the primary Sen slopes")
    intervals = trend.intervals.merge(
        rq2.rq2_full_authority[["parent_code", "raw_p", "bh_q"]].drop_duplicates(),
        on="parent_code", how="left", validate="many_to_one",
    )
    confidence = build_viirs_confidence_audit(
        rq3.paired_panel, analysis, authorities.manifest, evidence_root=evidence_root,
    )
    return {
        "district_burnable_support": support.district_support,
        "district_rate_variability": support.rate_variability,
        "district_denominator_distribution": support.denominator_distribution,
        "district_threshold_national": support.threshold_summary,
        "district_threshold_by_acz": support.threshold_by_acz,
        "district_threshold_by_unit": support.threshold_districts,
        "district_proof_crosswalk": support.proof_district_crosswalk,
        "trend_slope_intervals": intervals,
        "trend_interval_calibration": trend.calibration,
        "trend_detectability": trend.detectability,
        "trend_detectability_summary": trend.detectability_summary,
        "trend_simulation_settings": pd.DataFrame({"settings_json": [json.dumps(trend.settings, sort_keys=True, allow_nan=False)]}),
        "viirs_confidence_counts": confidence.counts,
        "viirs_confidence_correspondence": confidence.correspondence,
        "viirs_confidence_source_receipts": confidence.source_receipts,
        "rq1_burnable_support_figure_source": _support_figure(support, support_settings.restricted_scan_cutoff_km2),
        "rq2_trend_uncertainty_figure_source": _trend_figure(trend),
    }
