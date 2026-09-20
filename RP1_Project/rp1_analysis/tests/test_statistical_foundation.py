from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.design import assert_execution_ready
from rp1_analysis_v1.inference import (
    InferenceInputError,
    autocorrelation_diagnostics,
    benjamini_hochberg,
    coefficient_to_odds_ratio,
    normal_confidence_interval,
    sens_slope,
)
from rp1_analysis_v1.seasonality import (
    SeasonalityError,
    circular_month_distance,
    circular_mean_month,
    mean_resultant_length,
    month_angle,
    monthly_climatology,
    monthly_shares,
    peak_month,
    summarise_seasonality,
)
from rp1_analysis_v1.temporal import (
    TemporalContractError,
    add_year_month_columns,
    assert_complete_temporal_spine,
    construct_grouped_annual_series,
    month_ordinal,
    parse_yyyymm,
    validate_month_sequence,
    yyyymm_to_year_month,
)

SUBPROJECT = Path(__file__).resolve().parents[1]
CONFIG = SUBPROJECT / "config"


# ---------------------------------------------------------------------------
# Temporal foundation
# ---------------------------------------------------------------------------


def test_parse_yyyymm_and_calendar_conversion() -> None:
    ym = parse_yyyymm(201202)
    assert (ym.year, ym.month, ym.yyyymm, ym.label) == (2012, 2, 201202, "2012-02")
    assert parse_yyyymm("2024-12") == parse_yyyymm("202412")
    assert yyyymm_to_year_month(200101) == (2001, 1)
    assert month_ordinal(200102) - month_ordinal(200101) == 1


@pytest.mark.parametrize("bad", [201200, 201213, "2012-13", "2012/01", 2012.01, True])
def test_invalid_yyyymm_fails_closed(bad) -> None:
    with pytest.raises(TemporalContractError):
        parse_yyyymm(bad)


def test_month_sequence_requires_chronological_order() -> None:
    with pytest.raises(TemporalContractError, match="chronological"):
        validate_month_sequence([202001, 202003, 202002])


def test_month_sequence_detects_incomplete_spine() -> None:
    with pytest.raises(TemporalContractError, match="incomplete monthly spine"):
        validate_month_sequence([202001, 202003])


def test_add_year_month_columns_rejects_conflicting_existing_calendar() -> None:
    frame = pd.DataFrame({"yyyymm": [202001, 202002], "year": [2020, 2019]})
    with pytest.raises(TemporalContractError, match="conflicts"):
        add_year_month_columns(frame)


def test_complete_temporal_spine_by_unit() -> None:
    rows = []
    for unit in ("a", "b"):
        for month in range(1, 13):
            rows.append({"unit_id": unit, "yyyymm": 202000 + month})
    frame = pd.DataFrame(rows)
    assert_complete_temporal_spine(frame, unit_col="unit_id", start=202001, end=202012)
    broken = frame.loc[~((frame["unit_id"] == "b") & (frame["yyyymm"] == 202006))]
    with pytest.raises(TemporalContractError, match="incomplete temporal spine"):
        assert_complete_temporal_spine(broken, unit_col="unit_id", start=202001, end=202012)


def test_annualisation_sums_complete_supported_months() -> None:
    frame = pd.DataFrame(
        {
            "unit_id": ["a"] * 12,
            "yyyymm": [202000 + m for m in range(1, 13)],
            "value": np.arange(1, 13, dtype=float),
            "support": [1] * 12,
        }
    )
    annual = construct_grouped_annual_series(
        frame,
        value_col="value",
        group_cols=["unit_id"],
        support_col="support",
        aggregation="sum",
    )
    assert annual.loc[0, "year"] == 2020
    assert annual.loc[0, "value"] == 78.0
    assert annual.loc[0, "supported_months"] == 12
    assert bool(annual.loc[0, "annual_supported"])


def test_annualisation_preserves_unsupported_missingness() -> None:
    frame = pd.DataFrame(
        {
            "unit_id": ["a"] * 12,
            "yyyymm": [202000 + m for m in range(1, 13)],
            "value": [np.nan] + [1.0] * 11,
            "support": [0] + [1] * 11,
        }
    )
    annual = construct_grouped_annual_series(
        frame,
        value_col="value",
        group_cols=["unit_id"],
        support_col="support",
    )
    assert not bool(annual.loc[0, "annual_supported"])
    assert math.isnan(float(annual.loc[0, "value"]))
    assert annual.loc[0, "supported_months"] == 11


def test_annualisation_rejects_incomplete_calendar_year() -> None:
    frame = pd.DataFrame(
        {
            "unit_id": ["a"] * 11,
            "yyyymm": [202000 + m for m in range(1, 12)],
            "value": [1.0] * 11,
        }
    )
    with pytest.raises(TemporalContractError, match="incomplete calendar year"):
        construct_grouped_annual_series(frame, value_col="value", group_cols=["unit_id"])


# ---------------------------------------------------------------------------
# Circular seasonality foundation
# ---------------------------------------------------------------------------


def test_circular_month_distance_wraps_year_boundary() -> None:
    assert circular_month_distance(1, 12) == 1
    assert circular_month_distance(7, 7) == 0
    assert circular_month_distance(1, 7) == 6
    assert circular_month_distance(12, 1) == 1




def test_circular_mean_month_uses_cyclic_december_january_coordinate() -> None:
    shares = [0.0] * 12
    shares[11] = 0.5  # December
    shares[0] = 0.5   # January
    mean_month = circular_mean_month(shares)
    assert mean_month is not None
    # Midpoint lies at the cyclic boundary, represented continuously as 0 ≡ 12,
    # not at the linear midpoint 6.5.
    assert mean_month == pytest.approx(12.5, abs=1e-12) or mean_month == pytest.approx(0.5, abs=1e-12)

def test_month_angle_definition() -> None:
    assert month_angle(1) == pytest.approx(0.0)
    assert month_angle(4) == pytest.approx(math.pi / 2.0)
    assert month_angle(7) == pytest.approx(math.pi)


def test_monthly_climatology_and_peak_month() -> None:
    values = list(range(1, 13)) * 2
    months = list(range(1, 13)) * 2
    clim = monthly_climatology(values, months)
    assert clim == tuple(float(x) for x in range(1, 13))
    assert peak_month(clim) == 12


def test_single_month_concentration_is_one() -> None:
    clim = [0.0] * 12
    clim[11] = 10.0
    shares = monthly_shares(clim)
    assert shares is not None
    assert mean_resultant_length(shares) == pytest.approx(1.0, abs=1e-12)


def test_uniform_monthly_shares_have_near_zero_concentration() -> None:
    shares = tuple([1.0 / 12.0] * 12)
    assert mean_resultant_length(shares) == pytest.approx(0.0, abs=1e-12)


def test_concentration_is_bounded_for_valid_shares() -> None:
    shares = monthly_shares([1, 2, 3, 4, 5, 6, 5, 4, 3, 2, 1, 1])
    assert shares is not None
    concentration = mean_resultant_length(shares)
    assert concentration is not None
    assert 0.0 <= concentration <= 1.0


def test_zero_total_seasonality_is_explicit() -> None:
    summary = summarise_seasonality([0.0] * 12, list(range(1, 13)))
    assert summary.status == "zero_total"
    assert summary.monthly_shares is None
    assert summary.peak_month is None
    assert summary.mean_resultant_length is None


def test_missing_calendar_month_in_climatology_fails() -> None:
    with pytest.raises(SeasonalityError, match="missing calendar month"):
        monthly_climatology([1.0] * 11, list(range(1, 12)))


# ---------------------------------------------------------------------------
# Sen slope and generic dependence diagnostics
# ---------------------------------------------------------------------------


def test_sen_slope_known_positive_negative_constant_and_short_series() -> None:
    positive = sens_slope([1, 3, 5, 7, 9], confidence_level=0.95)
    negative = sens_slope([9, 7, 5, 3, 1], confidence_level=0.95)
    constant = sens_slope([4, 4, 4, 4], confidence_level=0.95)
    short = sens_slope([2, 5], confidence_level=0.95)
    assert positive.slope == pytest.approx(2.0)
    assert positive.ci_low == pytest.approx(2.0)
    assert positive.ci_high == pytest.approx(2.0)
    assert negative.slope == pytest.approx(-2.0)
    assert constant.slope == pytest.approx(0.0)
    assert constant.diagnostic_status == "constant_series"
    assert short.slope == pytest.approx(3.0)


def test_sen_slope_rejects_missing_or_too_short_input() -> None:
    with pytest.raises(InferenceInputError, match="at least 2"):
        sens_slope([1.0], confidence_level=0.95)
    with pytest.raises(InferenceInputError, match="non-finite"):
        sens_slope([1.0, np.nan, 2.0], confidence_level=0.95)


def _positive_ar1_series(n: int = 80, rho: float = 0.88, seed: int = 20260811) -> np.ndarray:
    rng = np.random.default_rng(seed)
    innovations = rng.normal(size=n)
    x = np.zeros(n, dtype=float)
    for i in range(1, n):
        x[i] = rho * x[i - 1] + innovations[i]
    return x


def test_autocorrelation_diagnostics_detect_positive_serial_dependence() -> None:
    series = _positive_ar1_series()
    diagnostics = autocorrelation_diagnostics(series, max_lag=3, alpha=0.05, detrend=True, rank=True)
    assert diagnostics.autocorrelations[0] > 0.5
    assert 1 in diagnostics.significant_lags
    assert diagnostics.detrending == "sens_slope"
    assert diagnostics.ranked


def test_rq2_revised_method_authority_is_loaded_and_production_ready() -> None:
    bundle = load_configuration_bundle(CONFIG)
    rq2 = bundle.analysis.research_questions["rq2"]
    assert rq2["authority_status"] == "frozen"
    assert rq2["effect_estimator"] == "sens_slope"
    assert rq2["inferential_test"]["method"] == "studentized_global_mann_kendall_permutation"
    assert rq2["inferential_test"]["bandwidth_rule"] == "floor_n_power_one_third"
    assert rq2["multiple_testing"]["family_size"] == 5
    assert_execution_ready(bundle.analysis.to_dict(), bundle.methods, "rq2")


# ---------------------------------------------------------------------------
# Multiple testing and generic model-support utilities
# ---------------------------------------------------------------------------


def test_bh_fdr_hand_verifiable_example_and_family_length() -> None:
    result = benjamini_hochberg(
        [0.01, 0.04, 0.03, 0.002, 0.8], family_name="five_primary_acz_tests", alpha=0.05
    )
    assert result.n_tests == 5
    assert result.adjusted_p_values == pytest.approx((0.025, 0.05, 0.05, 0.01, 0.8))
    assert result.rejected == (True, True, True, True, False)
    assert len(result.raw_p_values) == len(result.adjusted_p_values) == len(result.rejected)


def test_bh_adjusted_values_are_monotone_in_sorted_p_order() -> None:
    p = [0.2, 0.001, 0.04, 0.03, 0.9, 0.02]
    result = benjamini_hochberg(p, family_name="explicit_test_family", alpha=0.05)
    order = np.argsort(p)
    sorted_adjusted = np.asarray(result.adjusted_p_values)[order]
    assert np.all(np.diff(sorted_adjusted) >= -1e-15)


def test_bh_requires_explicit_family_and_valid_p_values() -> None:
    with pytest.raises(InferenceInputError, match="family_name"):
        benjamini_hochberg([0.1, 0.2], family_name="", alpha=0.05)
    with pytest.raises(InferenceInputError, match=r"\[0,1\]"):
        benjamini_hochberg([0.1, 1.2], family_name="bad", alpha=0.05)


def test_normal_confidence_interval_and_odds_ratio_transform() -> None:
    low, high = normal_confidence_interval(0.0, 1.0, confidence_level=0.95)
    assert low == pytest.approx(-1.959963984540054)
    assert high == pytest.approx(1.959963984540054)
    result = coefficient_to_odds_ratio(math.log(2.0), standard_error=0.1, confidence_level=0.95)
    assert result.odds_ratio == pytest.approx(2.0)
    assert result.ci_low is not None and result.ci_high is not None
    assert result.ci_low < result.odds_ratio < result.ci_high


def test_odds_ratio_transform_fails_on_numerically_unsafe_coefficient() -> None:
    with pytest.raises(InferenceInputError, match="safe exponential range"):
        coefficient_to_odds_ratio(1000.0, confidence_level=0.95)

def test_pgee_exponentiation_is_exact_for_finite_log_odds():
    coefficients = np.array([-0.8, 0.0, 0.65], dtype=float)
    expected = np.exp(coefficients)
    assert np.isfinite(expected).all()
    assert expected[0] < 1.0
    assert expected[1] == pytest.approx(1.0)
    assert expected[2] > 1.0

