"""Input-derived integration references have independent synthetic checks."""
import pandas as pd
import pytest

import scientific_input_reference as reference


@pytest.fixture
def recorded_panel(monkeypatch):
    rows = []
    for unit, code, denominator, detections, burned in (
        ("a", "CZ", 100.0, (1, 2), (0, 1)),
        ("b", "FZ", 200.0, (0, 4), (1, 0)),
        ("excluded", "GS", 0.0, (3, 3), (0, 0)),
    ):
        for month, viirs, ba in zip((2, 3), detections, burned, strict=True):
            rows.append({"unit_id": unit, "parent_code": code, "year": 2012, "month": month,
                         "yyyymm": 201200 + month, "viirs_det_primary": viirs,
                         "modis_ba_any_ba2012": ba,
                         "modis_burnable_km2_union_ba2001": denominator,
                         "modis_burnable_km2_union_ba2012": denominator,
                         "viirs_supported_flag": 1, "ba2012_supported_flag": 1,
                         "full_overlap_supported_flag": 1})
    panel = pd.DataFrame(rows)
    reference.paired_input_reference.cache_clear()
    reference.model_input_reference.cache_clear()
    monkeypatch.setattr(reference, "panel_input_reference", lambda *args: panel.copy())
    yield panel
    reference.paired_input_reference.cache_clear()
    reference.model_input_reference.cache_clear()


def test_population_references_filter_current_denominator_and_support(recorded_panel):
    paired = reference.paired_input_reference()
    assert paired.unit_id.tolist() == ["a", "a", "b", "b"]
    model = reference.model_input_reference()
    assert model.unit_id.tolist() == ["a", "a", "b"]
    assert model.mismatch_y.tolist() == [1, 0, 1]


def test_factor_and_cluster_counts_come_from_input_outcomes(recorded_panel):
    clusters = reference.cluster_reference()
    assert clusters.loc["a"].to_dict() == {"size": 2, "sum": 1}
    assert clusters.loc["b"].to_dict() == {"size": 1, "sum": 1}
    month = reference.factor_outcome_reference().loc[lambda x: x.factor.eq("month")].set_index("level")
    assert month.loc["2", ["n", "y1", "y0"]].tolist() == [1, 1, 0]
    assert month.loc["3", ["n", "y1", "y0"]].tolist() == [2, 1, 1]
    assert bool(month.loc["2", "complete_separation"])
    assert not bool(month.loc["3", "complete_separation"])
    assert set(reference.factor_outcome_reference().factor) == {"month", "year", "parent_code"}


def test_design_terms_follow_input_levels_and_configured_references(recorded_panel):
    terms = reference.design_terms_reference()
    assert "month_1" not in terms and "month_2" in terms and "month_3" in terms
    assert "year_2012" in terms
    assert "acz_CZ" not in terms and "acz_FZ" in terms
