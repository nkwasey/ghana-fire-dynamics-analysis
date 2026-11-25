import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from rp1_analysis_v1.config import ConfigurationError, load_analysis_contract
from rp1_analysis_v1.inference import (
    benjamini_hochberg,
    sen_slope_point_estimate,
    studentized_global_mann_kendall_permutation,
)
from rp1_analysis_v1.supplementary_analysis import _trend_figure
from rp1_analysis_v1.trend_sensitivity import (
    _CROSSING_CANDIDATE,
    _UNCONFIRMED_CROSSING,
    TrendSensitivityError,
    TrendSensitivitySettings,
    _bank_p_values,
    _bh_rejections,
    _confirm_crossings,
    _Noise,
    _permutation_banks,
    _qualify_detectability_crossings,
    _stationary_errors,
    _summarize_detectability,
    build_trend_sensitivity,
    settings_from_primary,
)


def _annual_rates(years=range(2001, 2025)) -> pd.DataFrame:
    zones = ("CZ", "FZ", "GS", "SS", "TZ")
    return pd.DataFrame.from_records([
        {
            "parent_code": zone,
            "year": year,
            "annual_rate": 13.5 + z * 3.0 - 0.12 * t + 1.2 * np.sin(t * (0.40 + z * 0.10)) + 0.01 * t**1.5,
        }
        for z, zone in enumerate(zones)
        for t, year in enumerate(years)
    ])


@pytest.fixture
def quick_settings() -> TrendSensitivitySettings:
    return TrendSensitivitySettings(
        interval_bootstrap_replicates=51,
        calibration_bootstrap_replicates=29,
        calibration_replicates=20,
        validation_replicates=24,
        detectability_replicates=72,
        held_out_interval_replicates=12,
        null_confirmation_replicates=24,
        permutation_count=199,
        permutation_banks=2,
        decline_grid=(0.0, 0.20, 0.40),
    )


def test_trend_sensitivity_preserves_governed_estimates_and_is_replayable(quick_settings):
    input_rates = _annual_rates()
    before = input_rates.copy(deep=True)
    a = build_trend_sensitivity(input_rates, settings=quick_settings)
    b = build_trend_sensitivity(input_rates.sample(frac=1.0, random_state=21), settings=quick_settings)
    pd.testing.assert_frame_equal(before, input_rates)
    for name in ("intervals", "calibration", "detectability", "detectability_summary"):
        pd.testing.assert_frame_equal(getattr(a, name), getattr(b, name))
    assert a.settings == b.settings

    primary = a.intervals.loc[a.intervals.interval_role.eq("calibrated_primary")].set_index("parent_code")
    assert len(primary) == 5
    alternative = a.intervals.loc[a.intervals.interval_role.eq("block_length_sensitivity")]
    assert set(alternative.status) == {"UNCALIBRATED_BLOCK_LENGTH_SENSITIVITY"}
    assert set(alternative.expected_block_length) == {2, 4, 6}
    for zone, group in input_rates.groupby("parent_code"):
        assert primary.loc[zone, "sen_slope"] == pytest.approx(sen_slope_point_estimate(group.annual_rate, x=group.year))
    np.testing.assert_array_less(primary.interval_lower, primary.interval_upper)

    assert set(a.calibration["sample"]) == {"calibration", "independent_simulated_series"}
    assert set(a.calibration.loc[a.calibration["sample"].eq("independent_simulated_series"), "replicates"]) == {24}
    null = a.detectability.loc[a.detectability.effect_pattern.eq("all_zero")]
    np.testing.assert_array_equal(null.family_any_bh_rejection, null.family_fdr)
    qualifications = a.settings["interval_coverage_qualification"]
    held_out = qualifications["held_out_noise_scenarios"]
    assert len(held_out) == 3 * 2 * 5
    assert len(qualifications["directional_endpoint_diagnostics"]) == 2 * 4 * 2 * 5
    for row in held_out + qualifications["directional_endpoint_diagnostics"]:
        assert sum(row[key] for key in (
            "covered_count", "truth_below_lower_endpoint_count", "truth_above_upper_endpoint_count",
            "invalid_interval_count",
        )) == row["replicates"]
        assert row["coverage_lower_95"] <= row["coverage"] <= row["coverage_upper_95"]
    confirm = a.settings["detectability_qualification"]
    assert confirm["null_confirmation_seed_spawn_key"] != qualifications["held_out_seed_spawn_key"]
    assert len(confirm["all_null_confirmation"]) == 7
    assert all(row["replicates"] == 24 for row in confirm["all_null_confirmation"])
    assert all(row["family_fdr"] == row["family_any_bh_rejection"] for row in confirm["all_null_confirmation"])
    assert len(confirm["direction_check"]["zones"]) == 5
    assert confirm["target_crossing_confirmation"] == "NOT_TRIGGERED_NO_SUSTAINED_CROSSING"
    json.dumps(a.settings, allow_nan=False)
    assert not a.detectability_summary.empty
    assert len(a.detectability_summary) == 40
    rows = a.detectability_summary.loc[a.detectability_summary.status.eq("NOT_ATTAINED_ON_GRID")]
    assert rows.sustained_slope.isna().all()
    assert not rows.maximum_tested_decline_slope.isna().any()

    source = _trend_figure(a)
    curve = source.loc[source["record_type"].eq("detectability")].reset_index(drop=True)
    assert set(curve["noise_scenario"]) == set(a.settings["noise_scenarios"])
    published = a.detectability.loc[
        a.detectability["parent_code"].eq("TZ")
        & a.detectability["effect_pattern"].isin(["all_zero", "concurrent_decline"])
    ].reset_index(drop=True)
    for name, input_column in (
        ("power", "bh_rejection"), ("mc_lower", "bh_rejection_lower_95"), ("mc_upper", "bh_rejection_upper_95"),
        ("bank_min", "bh_bank_min"), ("bank_max", "bh_bank_max"),
    ):
        np.testing.assert_array_equal(curve[name], published[input_column])


def test_calibration_and_independent_simulated_series_use_distinct_draws(quick_settings):
    result = build_trend_sensitivity(_annual_rates(), settings=quick_settings).calibration
    keys = ["parent_code", "noise_scenario", "decline_fraction_per_decade"]
    grouped = result.set_index(keys + ["sample"])["slope_bias"].unstack()
    assert (grouped["calibration"] != grouped["independent_simulated_series"]).all()
    assert (result.calibrated_coverage >= result.uncalibrated_coverage).all()


def test_cached_rank_bank_matches_same_bank_production_draws_for_ordered_series(quick_settings):
    seed = 21
    bank = _permutation_banks(quick_settings, np.random.default_rng(seed))
    series = np.linspace(4.0, 5.0, 24)
    estimated, _ = _bank_p_values(series[None, :], bank, quick_settings)
    production = _production_test(series, quick_settings, seed)
    assert estimated[0, 0] == production.raw_p


def _production_test(series, settings, seed):
    return studentized_global_mann_kendall_permutation(
        series,
        bandwidth_rule="floor_n_power_one_third",
        variance_floor=settings.variance_floor,
        replications=settings.permutation_count,
        alternative="two_sided_absolute",
        seed=seed,
        p_value_rule="monte_carlo_plus_one",
        empirical_cdf="less_than_or_equal_ecdf",
        studentisation="recompute_for_each_permutation",
        method_id="test",
        implementation_id="test",
        requires_distinct_observations=True,
        on_ties="fail_closed",
    )


@pytest.mark.parametrize(("observed_index", "expected_extremes", "reject"), (
    (8505, 399, True),
    (8340, 400, False),
))
def test_rank_bank_matches_production_on_identical_draws_at_bh_boundary(
    observed_index, expected_extremes, reject,
):
    settings = replace(TrendSensitivitySettings(), permutation_banks=1)
    seed = 190235
    orderings = np.argsort(np.random.default_rng(seed).random((9999, 24)), axis=1, kind="stable") + 1
    observed = orderings[observed_index].astype(float)

    # Reference ranks identify the same draws as production permutations of
    # the corresponding observed positions, even for non-monotone series.
    locations = np.argsort(observed, kind="stable")[orderings - 1]
    np.testing.assert_array_equal(observed[locations], orderings)
    keys = np.argsort(locations, axis=1, kind="stable") / len(observed)
    bank = _permutation_banks(settings, np.random.default_rng(seed))
    estimated, floor = _bank_p_values(observed[None, :], bank, settings)
    with patch("rp1_analysis_v1.inference.np.random.default_rng") as generator:
        generator.return_value.random.return_value = keys
        production = _production_test(observed, settings, seed)
    assert production.extreme_count == expected_extremes
    assert not floor[0]
    assert estimated[0, 0] == production.raw_p == (expected_extremes + 1) / 10000

    family = np.array([[0.0101, 0.0201, 0.0301, estimated[0, 0], 0.1]])[..., None]
    governed = benjamini_hochberg(family[0, :, 0], family_name="five_acz", alpha=settings.bh_alpha)
    expected = (True, True, True, True, False) if reject else (False,) * 5
    assert governed.rejected == expected
    np.testing.assert_array_equal(_bh_rejections(family, settings.bh_alpha)[0, :, 0], governed.rejected)


def test_bh_matches_governed_five_member_adjustment():
    p_values = np.array([
        [0.034, 0.150, 0.300, 0.500, 0.750],
        [0.010, 0.020, 0.030, 0.040, 0.050],
        [0.004, 0.035, 0.019, 0.090, 0.501],
    ])
    expected = np.array([
        benjamini_hochberg(row, family_name="five_acz", alpha=0.05).rejected for row in p_values
    ])
    np.testing.assert_array_equal(_bh_rejections(p_values[:, :, None], 0.05)[:, :, 0], expected)


@pytest.mark.parametrize(("rank", "cutoff"), tuple(enumerate((0.01, 0.02, 0.03, 0.04, 0.05), start=1)))
def test_simulated_bh_matches_production_at_each_cutoff_and_adjacent_floats(rank, cutoff):
    near_cutoff = (np.nextafter(cutoff, 0.0), cutoff, np.nextafter(cutoff, 1.0))
    p_values = np.array([
        np.roll([0.0] * (rank - 1) + [p] + [1.0] * (5 - rank), shift=2)
        for p in near_cutoff
    ])
    expected = np.array([
        benjamini_hochberg(row, family_name="five_acz", alpha=0.05).rejected for row in p_values
    ])
    np.testing.assert_array_equal(_bh_rejections(p_values[:, :, None], 0.05)[:, :, 0], expected)


@pytest.fixture
def primary_contract():
    return load_analysis_contract(Path(__file__).resolve().parents[1] / "config" / "analysis_contract.yml")


def test_settings_bind_to_governed_numeric_decision_rule(primary_contract):
    canonical = settings_from_primary(primary_contract)
    assert (canonical.bandwidth, canonical.variance_floor, canonical.permutation_count, canonical.bh_alpha) == (
        2, 0.001, 9999, 0.05,
    )
    modified = primary_contract.to_dict()
    test = modified["research_questions"]["rq2"]["inferential_test"]
    test.update(permutations=199, variance_floor=0.002)
    modified["reproducibility"]["alpha"] = 0.10
    bound = settings_from_primary(replace(
        primary_contract,
        research_questions=modified["research_questions"],
        reproducibility=modified["reproducibility"],
    ))
    assert (bound.bandwidth, bound.variance_floor, bound.permutation_count, bound.bh_alpha) == (
        2, 0.002, 199, 0.10,
    )
    assert bound.seed == canonical.seed


@pytest.mark.parametrize(("key", "value", "message"), [
    ("null_confirmation_replicates", 3999, "4,000"),
    ("fitted_lag_limit", 1.1, "stationary AR"),
    ("held_out_interval_replicates", True, "invalid numeric"),
    ("skew_strenght", 0.60, "unexpected"),
])
def test_contract_rejects_invalid_sensitivity_profile(primary_contract, tmp_path, key, value, message):
    raw = primary_contract.to_dict()
    raw["research_questions"]["rq2"]["trend_sensitivity"][key] = value
    source = tmp_path / "analysis_contract.yml"
    source.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ConfigurationError, match=message):
        load_analysis_contract(source)


def test_crossing_qualification_retests_preceding_point_and_complete_grid_tail(quick_settings):
    quick_settings = replace(quick_settings, decline_grid=(0.0, 0.20, 0.40, 0.60))
    center = np.linspace(16, 20, 5)
    independent = _Noise("independent", np.zeros(5), np.ones(5) * 0.2, np.eye(5))
    candidate = pd.DataFrame([{
        "noise_scenario": independent.name,
        "status": _CROSSING_CANDIDATE,
        "effect_pattern": "single_zone_decline",
        "target_zone": "SS",
        "parent_code": "SS",
        "sustained_decline_fraction_per_decade": quick_settings.decline_grid[1],
    }])
    result = _confirm_crossings(candidate, (independent,), center, quick_settings, np.random.SeedSequence(5))
    assert tuple(row["decline_fraction_per_decade"] for row in result) == quick_settings.decline_grid
    assert all(row["replicates"] == quick_settings.null_confirmation_replicates for row in result)
    assert all(len(row["bank_bh_rejection"]) == quick_settings.permutation_banks for row in result)
    assert all(row["injected_slope"] == -center[3] * (row["decline_fraction_per_decade"] / 10) for row in result)


@pytest.mark.parametrize(("confirmed_by_level", "expected_status", "expected_crossing"), [
    ((True, True, True), "ATTAINED_ON_GRID", 0.2),
    ((True, False, True), "ATTAINED_ON_GRID", 0.6),
    ((True, True, False), _UNCONFIRMED_CROSSING, None),
    ((True, True, None), _UNCONFIRMED_CROSSING, None),
    ((None, None, None), _UNCONFIRMED_CROSSING, None),
])
def test_detectability_summary_requires_sustained_independent_confirmation(
    confirmed_by_level, expected_status, expected_crossing,
):
    identity = dict(noise_scenario="fitted", effect_pattern="single_zone_decline", target_zone="TZ", parent_code="TZ")
    grid = (0.0, 0.2, 0.4, 0.6)
    frame = pd.DataFrame([
        dict(identity, decline_fraction_per_decade=decline, injected_slope=-decline,
             bh_rejection=0.92, bh_bank_lower_95_min=0.87)
        for decline in grid[1:]
    ])
    summary = _summarize_detectability(frame, 0.8)
    assert summary.iloc[0]["status"] == _CROSSING_CANDIDATE
    diagnostics = [
        dict(identity, decline_fraction_per_decade=decline, injected_slope=-decline,
             target_supported_by_all_bank_lower_bounds=supported)
        for decline, supported in zip(grid[1:], confirmed_by_level, strict=True)
        if supported is not None
    ]
    final = _qualify_detectability_crossings(summary, diagnostics, grid).iloc[0]
    assert final["status"] == expected_status
    if expected_crossing is None:
        assert pd.isna(final["sustained_decline_fraction_per_decade"])
        assert pd.isna(final["sustained_slope"])
    else:
        assert final["sustained_decline_fraction_per_decade"] == expected_crossing
        assert final["sustained_slope"] == -expected_crossing


@pytest.mark.parametrize(("transform", "strength"), [
    ("symmetric_tail_stretch", 1.25), ("positive_half_stretch", 0.60),
])
def test_held_out_transforms_preserve_median_and_dispersion(transform, strength):
    noise = _Noise("stress", np.array([0.0, 0.4]), np.array([1.0, 2.0]), np.eye(2), transform, strength)
    errors = _stationary_errors(noise, 15000, np.random.default_rng(37), 24)
    np.testing.assert_allclose(np.median(errors, axis=(0, 2)), 0, atol=0.015)
    np.testing.assert_allclose(errors.std(axis=(0, 2)), noise.log_dispersion, atol=0.035)
    standardized = (errors - errors.mean(axis=(0, 2), keepdims=True)) / noise.log_dispersion[None, :, None]
    if transform == "symmetric_tail_stretch":
        assert (np.mean(standardized**4, axis=(0, 2)) > 4).all()
    else:
        assert (np.mean(standardized**3, axis=(0, 2)) > 0.5).all()


def test_independent_zone_draws_keep_coordinates_when_fitted_lags_round(quick_settings):
    lags = np.array([-0.021682695433791685, -0.4132794500684883, -0.2946712748177344,
                     0.05414946759141082, -0.2960779437343126])
    rounded_lags = np.array([-0.021682695433791775, -0.41327945006848843, -0.2946712748177342,
                             0.054149467591410906, -0.29607794373431257])
    noise = _Noise("independent_zones_fitted_ar1", lags, np.ones(5), np.eye(5), independent_zones=True)
    n, years, seed = 43, len(quick_settings.years), 912
    errors = _stationary_errors(noise, n, np.random.default_rng(seed), years)
    rounded = _stationary_errors(replace(noise, lag1=rounded_lags), n, np.random.default_rng(seed), years)
    expected = np.random.default_rng(seed)
    expected.standard_normal((n, years, 5))
    np.testing.assert_array_equal(errors[..., 0], expected.standard_normal((n, 5)))
    np.testing.assert_allclose(errors, rounded, rtol=0, atol=2e-15)
    banks = _permutation_banks(quick_settings, np.random.default_rng(seed + 1))
    p, floor = _bank_p_values(np.exp(errors), banks, quick_settings)
    rounded_p, rounded_floor = _bank_p_values(np.exp(rounded), banks, quick_settings)
    np.testing.assert_array_equal(p, rounded_p)
    np.testing.assert_array_equal(floor, rounded_floor)


def test_alternate_complete_calendar_updates_bandwidth_and_feasible_declines(primary_contract, quick_settings):
    modified = primary_contract.to_dict()
    modified["study"]["temporal_windows"]["long_run"] = {"start": "1998-01", "end": "2027-12"}
    modified["research_questions"]["rq2"]["expected_n_per_series"] = 30
    active_contract = replace(primary_contract, study=modified["study"], research_questions=modified["research_questions"])
    bound = settings_from_primary(active_contract)
    assert bound.years == tuple(range(1998, 2028))
    assert bound.bandwidth == 3
    assert bound.decline_grid[-1] == 0.60
    active_settings = replace(quick_settings, years=bound.years, bandwidth=bound.bandwidth, decline_grid=bound.decline_grid)
    result = build_trend_sensitivity(_annual_rates(bound.years), settings=active_settings)
    assert set(result.intervals.n_years) == {30}
    assert result.settings["years"] == list(bound.years)
    assert result.detectability.decline_fraction_per_decade.max() == bound.decline_grid[-1]
    with pytest.raises(TrendSensitivityError, match="declared annual calendar"):
        build_trend_sensitivity(_annual_rates(), settings=active_settings)


def test_proportional_model_reports_unavailable_zone_without_losing_other_intervals(quick_settings):
    inputs = _annual_rates()
    inputs.loc[inputs.parent_code.eq("CZ") & inputs.year.eq(2001), "annual_rate"] = 0.0
    result = build_trend_sensitivity(inputs, settings=quick_settings)
    absent = result.intervals.parent_code.eq("CZ")
    assert set(result.intervals.loc[absent, "status"]) == {"UNAVAILABLE_NONPOSITIVE_RATES"}
    assert result.intervals.loc[absent, "sen_slope"].notna().all()
    assert result.intervals.loc[absent, ["interval_lower", "interval_upper"]].isna().all().all()
    assert result.intervals.loc[~absent, ["interval_lower", "interval_upper"]].notna().all().all()
    assert set(result.calibration.parent_code) == {"FZ", "GS", "SS", "TZ"}
    assert result.detectability.empty and "family_fdr" in result.detectability.columns
    assert set(result.detectability_summary.status) == {"UNAVAILABLE_INCOMPLETE_FIVE_ZONE_FAMILY"}
    assert result.detectability_summary.peak_bh_detection.isna().all()
    assert result.settings["zone_availability"]["CZ"] == "UNAVAILABLE_NONPOSITIVE_RATES"
    assert result.settings["detectability_status"] == "UNAVAILABLE_INCOMPLETE_FIVE_ZONE_FAMILY"
    json.dumps(result.settings, allow_nan=False)


@pytest.mark.parametrize("active_zones", [[], ["TZ"]])
def test_proportional_model_handles_zero_or_one_available_zone(quick_settings, active_zones):
    inputs = _annual_rates()
    inputs.loc[~inputs.parent_code.isin(active_zones) & inputs.year.eq(2001), "annual_rate"] = 0.0
    result = build_trend_sensitivity(inputs, settings=quick_settings)
    assert result.settings["simulation_zone_order"] == active_zones
    assert set(result.calibration.parent_code) == set(active_zones)
    assert result.detectability.empty
    assert len(result.detectability_summary) == 5


def test_proportional_model_distinguishes_invalid_fitted_path_and_degenerate_errors(quick_settings):
    inputs = _annual_rates()
    time = np.arange(24)
    inputs.loc[inputs.parent_code.eq("CZ"), "annual_rate"] = np.exp(time / 3)
    inputs.loc[inputs.parent_code.eq("FZ"), "annual_rate"] = 20.0 + time / 8
    result = build_trend_sensitivity(inputs, settings=quick_settings)
    for zone, reason in (
        ("CZ", "UNAVAILABLE_NONPOSITIVE_FITTED_PATH"),
        ("FZ", "UNAVAILABLE_DEGENERATE_RESIDUALS"),
    ):
        assert set(result.intervals.loc[result.intervals.parent_code.eq(zone), "status"]) == {reason}
        assert result.settings["zone_availability"][zone] == reason
    assert set(result.calibration.parent_code) == {"GS", "SS", "TZ"}
    assert result.detectability.empty


@pytest.mark.parametrize("field", ["empirical_cdf", "studentisation", "alternative", "p_value_method"])
def test_settings_reject_unsupported_primary_test_conventions(primary_contract, field):
    modified = primary_contract.to_dict()
    modified["research_questions"]["rq2"]["inferential_test"][field] = "other"
    with pytest.raises(TrendSensitivityError, match=field):
        settings_from_primary(replace(primary_contract, research_questions=modified["research_questions"]))


@pytest.mark.parametrize("fault,pattern", [
    ("missing", "Complete, finite annual rates"),
    ("duplicate", "Duplicate"),
    ("ties", "distinct"),
    ("support_drift", "fixed burnable area changed"),
    ("misreported", "Supplied Sen"),
    ("permutation_count", "permutation_count"),
])
def test_invalid_annual_authority_fails_closed(quick_settings, fault, pattern):
    inputs = _annual_rates()
    if fault == "missing":
        inputs = inputs.iloc[1:]
    elif fault == "duplicate":
        inputs = pd.concat([inputs, inputs.iloc[:1]])
    elif fault == "ties":
        inputs.loc[1, "annual_rate"] = inputs.loc[0, "annual_rate"]
    elif fault == "support_drift":
        inputs["fixed_burnable_km2"] = 90.0
        inputs.loc[1, "fixed_burnable_km2"] = 100.0
    elif fault == "permutation_count":
        inputs["permutation_count"] = quick_settings.permutation_count
        inputs.loc[1, "permutation_count"] += 1
    else:
        inputs["sen_slope"] = 1.0
    with pytest.raises(TrendSensitivityError, match=pattern):
        build_trend_sensitivity(inputs, settings=quick_settings)


def test_detector_does_not_interpolate_or_ignore_later_nonattainment():
    frame = pd.DataFrame({
        "noise_scenario": ["fitted"] * 3,
        "effect_pattern": ["single_zone_decline"] * 3,
        "target_zone": ["CZ"] * 3,
        "parent_code": ["CZ"] * 3,
        "decline_fraction_per_decade": [0.1, 0.2, 0.3],
        "injected_slope": [-0.1, -0.2, -0.3],
        "bh_rejection": [0.60, 0.90, 0.73],
        "bh_bank_lower_95_min": [0.54, 0.85, 0.66],
    })
    result = _summarize_detectability(frame, 0.8).iloc[0]
    assert result["status"] == "NOT_ATTAINED_ON_GRID"
    assert result["maximum_tested_decline_slope"] == -0.3
    assert bool(result["estimated_nonmonotone"])


def test_settings_reject_physically_impossible_decline(quick_settings):
    settings = replace(quick_settings, decline_grid=(0.0, 0.2, 1.0))
    with pytest.raises(TrendSensitivityError, match="preserve positive central rates"):
        build_trend_sensitivity(_annual_rates(), settings=settings)
