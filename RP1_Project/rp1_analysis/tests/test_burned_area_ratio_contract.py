"""Annual burnable-area ratios and union fractions have distinct support."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.validation import (
    DataContractError,
    _check_domains_ranges_and_nulls,
    _check_finite_numeric,
)


SUBPROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def schema():
    return load_configuration_bundle(SUBPROJECT / "config").data_schema


@pytest.mark.parametrize("family", ["ba2001", "ba2012"])
def test_annual_ratio_may_exceed_one_while_union_fraction_remains_bounded(schema, family):
    # A union mask can contain all 12 km² of the numerator even when the
    # year-specific burnable mask covers only 10 km². The latter is not a
    # fraction of the annual mask; the union-denominator fraction is 12/20.
    annual = schema.field(f"modis_burned_frac_annual_{family}")
    union = schema.field(f"modis_burned_frac_union_{family}")
    assert annual.semantic_type == "ratio"
    assert annual.minimum == 0
    assert annual.maximum is None
    assert union.semantic_type == "proportion"
    assert union.maximum == 1
    reduced = SimpleNamespace(fields=(annual, union), categorical_domains={})
    frame = pd.DataFrame({annual.name: [12 / 10], union.name: [12 / 20]})
    _check_finite_numeric(frame, "test")
    _check_domains_ranges_and_nulls(frame, "test", reduced)

    # Negative annual ratios and out-of-range union fractions remain invalid.
    bad_annual = frame.copy()
    bad_annual[annual.name] = -0.01
    with pytest.raises(DataContractError, match="below minimum"):
        _check_domains_ranges_and_nulls(bad_annual, "test", reduced)
    bad_union = frame.copy()
    bad_union[union.name] = 1.01
    with pytest.raises(DataContractError, match="above maximum"):
        _check_domains_ranges_and_nulls(bad_union, "test", reduced)


@pytest.mark.parametrize("family", ["ba2001", "ba2012"])
def test_annual_ratio_remains_finite_or_null(schema, family):
    annual = schema.field(f"modis_burned_frac_annual_{family}")
    reduced = SimpleNamespace(fields=(annual,), categorical_domains={})
    null = pd.DataFrame({annual.name: [float("nan")]})
    _check_finite_numeric(null, "test")
    _check_domains_ranges_and_nulls(null, "test", reduced)
    infinite = pd.DataFrame({annual.name: [float("inf")]})
    with pytest.raises(DataContractError, match="Infinite numeric values"):
        _check_finite_numeric(infinite, "test")


def test_area_temporal_consistency_allows_only_tiny_roundoff(schema):
    from rp1_analysis_v1.validation import _check_validation_rules
    # Exercise the temporal rule in isolation; this is a decimal-rounding
    # tolerance, not a relaxation of spatial or scientific consistency.
    rule = {"field": "modis_burnable_km2_union_ba2001", "scope": "unit_constant", "support": "ba2001_full"}
    reduced = SimpleNamespace(validation_rules={"temporal_consistency": [rule]}, source_supports=schema.source_supports)
    frame = pd.DataFrame({"unit_id": ["x", "x"], "yyyymm": [201201, 201202], rule["field"]: [10000., 10000. + 1e-11]})
    _check_validation_rules(frame, "test", reduced)
    frame.loc[1, rule["field"]] = 10000. + 1e-5
    with pytest.raises(DataContractError, match="beyond 1e-9"):
        _check_validation_rules(frame, "test", reduced)
