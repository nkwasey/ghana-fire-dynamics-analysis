from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from rp1_analysis_v1.config import load_configuration_bundle, rq2_trend_parameters
from rp1_analysis_v1.data_io import load_data_authorities
from rp1_analysis_v1.inference import (
    MethodAdmissibilityError,
    benjamini_hochberg,
    studentized_global_mann_kendall_permutation,
)
from rp1_analysis_v1.paths import ProjectPaths
from rp1_analysis_v1.trend_robustness import PRIMARY_RATE, build_acz_annual_ba_series
from .rq2_romano_tirlea_reference import (
    ReferenceAdmissibilityError,
    bh_reference,
    components,
    exact_two_sided_extreme,
    permutation_test,
)

SUBPROJECT = Path(__file__).resolve().parents[2]
CONFIG = SUBPROJECT / "config"
BOUNDARY_RANKS = [
    17, 6, 8, 19, 21, 18, 9, 15, 13, 10, 14, 7,
    11, 5, 23, 16, 3, 12, 1, 22, 4, 24, 2, 20,
]
BOUNDARY_EQUAL_PERMUTATION = [
    13, 1, 6, 14, 24, 19, 11, 2, 12, 17, 18, 9,
    3, 23, 7, 8, 4, 22, 10, 16, 21, 20, 15, 5,
]


def _prod(
    values,
    *,
    epsilon=0.001,
    replications=199,
    seed=20260822,
    requires_distinct_observations=False,
    on_ties="allow",
):
    return studentized_global_mann_kendall_permutation(
        values,
        bandwidth_rule="floor_n_power_one_third",
        variance_floor=epsilon,
        replications=replications,
        alternative="two_sided_absolute",
        seed=seed,
        p_value_rule="monte_carlo_plus_one",
        empirical_cdf="less_than_or_equal_ecdf",
        studentisation="recompute_for_each_permutation",
        method_id="studentized_global_mann_kendall_permutation",
        implementation_id="trend.romano_tirlea_studentized_global_mk.v1",
        requires_distinct_observations=requires_distinct_observations,
        on_ties=on_ties,
    )


@pytest.mark.parametrize(
    "values, expected_sign",
    [
        (list(range(1, 13)), 1),
        (list(range(12, 0, -1)), -1),
    ],
)
def test_strict_monotone_series_match_independent_reference(values, expected_sign):
    ref = permutation_test(values, epsilon=0.001, replications=199, seed=31)
    prod = _prod(values, replications=199, seed=31)
    assert math.copysign(1, prod.u_n) == expected_sign
    assert prod.u_n == pytest.approx(ref.u_n)
    assert prod.long_run_variance == pytest.approx(ref.sigma2)
    assert prod.t_n == pytest.approx(ref.t_n)
    assert prod.extreme_count == ref.extreme_count
    assert prod.raw_p == pytest.approx(ref.p_value)


def test_reference_rejects_ties_as_outside_theoretical_authority():
    with pytest.raises(ReferenceAdmissibilityError, match="tie-free"):
        permutation_test([1, 1, 2, 3], epsilon=0.001, replications=19, seed=7)


def test_strict_configured_production_guard_fails_closed_on_ties():
    with pytest.raises(MethodAdmissibilityError, match="requires tie-free annual observations"):
        _prod(
            [1, 1, 2, 3],
            replications=19,
            seed=7,
            requires_distinct_observations=True,
            on_ties="fail_closed",
        )


def test_no_obvious_trend_and_weak_serial_dependence_cases_are_finite():
    for values in (
        [3, 1, 4, 2, 6, 5, 8, 7, 10, 9, 12, 11],
        [1.0, 1.4, 1.1, 1.6, 1.3, 1.9, 1.5, 2.0, 1.7, 2.1, 1.8, 2.2],
    ):
        ref = permutation_test(values, epsilon=0.001, replications=199, seed=101)
        prod = _prod(values, replications=199, seed=101)
        assert np.isfinite([prod.u_n, prod.long_run_variance, prod.t_n, prod.raw_p]).all()
        assert prod.extreme_count == ref.extreme_count
        assert 0.0 < prod.raw_p <= 1.0


def test_variance_floor_activation_on_tie_free_input():
    prod = _prod([1, 4, 2, 3, 5, 6], epsilon=10.0, replications=49, seed=2)
    ref = permutation_test([1, 4, 2, 3, 5, 6], epsilon=10.0, replications=49, seed=2)
    assert prod.variance_floor_used is True
    assert prod.variance_floor == 10.0
    assert prod.extreme_count == ref.extreme_count


def test_hand_calculable_n4_components():
    u_n, bandwidth, sigma2, floor_used, t_n = components([1, 4, 2, 3], 0.001)
    assert u_n == pytest.approx(1 / 3)
    assert bandwidth == 1
    assert sigma2 == pytest.approx(1 / 9)
    assert floor_used is False
    assert t_n == pytest.approx(2.0)
    prod = _prod([1, 4, 2, 3], replications=19, seed=17)
    assert prod.u_n == pytest.approx(u_n)
    assert prod.long_run_variance == pytest.approx(sigma2)
    assert prod.t_n == pytest.approx(t_n)


def test_deterministic_permutation_sequence_and_result():
    values = [4, 1, 3, 2, 5, 8, 7, 6]
    a = _prod(values, replications=299, seed=1234)
    b = _prod(values, replications=299, seed=1234)
    assert a == b


def test_plus_one_rule_and_zero_p_impossible():
    prod = _prod(range(1, 16), replications=99, seed=14)
    assert prod.raw_p == pytest.approx((prod.extreme_count + 1) / 100)
    assert prod.raw_p >= 1 / 100
    assert prod.raw_p != 0.0


def test_n24_realises_bandwidth_two_and_configured_floor_is_unchanged():
    prod = _prod(range(24), replications=19, seed=3)
    params = rq2_trend_parameters(load_configuration_bundle(CONFIG).analysis)
    assert prod.realised_bandwidth == 2
    assert params.bandwidth_rule == "floor_n_power_one_third"
    assert params.variance_floor == 0.001


def test_bh_reference_across_exactly_five_raw_p_values():
    raw = [0.003, 0.02, 0.07, 0.5, 0.9]
    expected = bh_reference(raw)
    prod = benjamini_hochberg(raw, family_name="exactly_five", alpha=0.05)
    assert prod.n_tests == 5
    assert list(prod.adjusted_p_values) == pytest.approx(expected)


def test_exact_boundary_rank_case_counts_equality_and_returns_forest_tail():
    ref = permutation_test(BOUNDARY_RANKS, epsilon=0.001, replications=9999, seed=20260822)
    prod = _prod(BOUNDARY_RANKS, replications=9999, seed=20260822)
    assert ref.extreme_count == 5740
    assert ref.p_value == pytest.approx(0.5741, abs=0.0)
    assert prod.extreme_count == 5740
    assert prod.raw_p == pytest.approx(0.5741, abs=0.0)

    # Seeded permutation index 5641 is a distinct rank ordering whose exact
    # squared studentized statistic equals the observed Forest-rank statistic.
    # Both >= directions therefore hold, proving exact equality is retained in
    # the governed two-sided tail rather than lost to floating round-off.
    assert BOUNDARY_EQUAL_PERMUTATION != BOUNDARY_RANKS
    assert exact_two_sided_extreme(
        BOUNDARY_RANKS, BOUNDARY_EQUAL_PERMUTATION, epsilon=0.001
    ) is True
    assert exact_two_sided_extreme(
        BOUNDARY_EQUAL_PERMUTATION, BOUNDARY_RANKS, epsilon=0.001
    ) is True


def test_all_five_actual_ghana_rq2_series_are_tie_free_and_match_reference():
    bundle = load_configuration_bundle(CONFIG)
    params = rq2_trend_parameters(bundle.analysis)
    authorities = load_data_authorities(ProjectPaths(SUBPROJECT), bundle.data_schema)
    annual = build_acz_annual_ba_series(authorities.acz_panel, bundle.analysis)
    observed_raw = []
    for _, group in annual.groupby("unit_id", sort=True, observed=True):
        values = group.sort_values("year")[PRIMARY_RATE].to_numpy(dtype=float)
        assert np.unique(values).size == values.size == 24
        ref = permutation_test(
            values,
            epsilon=params.variance_floor,
            replications=params.permutations,
            seed=params.random_seed,
        )
        prod = _prod(
            values,
            epsilon=params.variance_floor,
            replications=params.permutations,
            seed=params.random_seed,
            requires_distinct_observations=params.requires_distinct_observations,
            on_ties=params.on_ties,
        )
        assert prod.u_n == pytest.approx(ref.u_n, rel=0.0, abs=1e-15)
        assert prod.long_run_variance == pytest.approx(ref.sigma2, rel=0.0, abs=1e-15)
        assert prod.t_n == pytest.approx(ref.t_n, rel=0.0, abs=1e-14)
        assert prod.extreme_count == ref.extreme_count
        assert prod.raw_p == pytest.approx(ref.p_value, rel=0.0, abs=0.0)
        observed_raw.append(prod.raw_p)
    assert len(observed_raw) == params.family_size == 5
