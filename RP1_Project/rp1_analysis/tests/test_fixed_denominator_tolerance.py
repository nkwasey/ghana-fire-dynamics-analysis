import numpy as np
import pytest
from rp1_analysis_v1.fixed_denominator import fixed_denominator


def test_earliest_month_representative_and_observed_range():
    values = [14890.695007328062, 14890.695007328064]
    selected, lo, hi, spread = fixed_denominator(values, 1e-9)
    assert selected == values[0]
    assert lo == min(values) and hi == max(values)
    assert 0 < spread < 1e-9

@pytest.mark.parametrize('values', [[1, 1.000001], [0, 1], [1, np.nan], [-1, 1], []])
def test_invalid_denominators_fail(values):
    with pytest.raises(ValueError):
        fixed_denominator(values, 1e-9)

@pytest.mark.parametrize('tolerance', [-1, float('nan'), float('inf')])
def test_invalid_tolerance_fails(tolerance):
    with pytest.raises(ValueError):
        fixed_denominator([1], tolerance)
