"""RQ3 conditional population behavior with independent FRP support."""
from types import SimpleNamespace

import pandas as pd
import pytest

import rp1_analysis_v1.gee as gee


def test_zero_count_excluded_and_required_frp_not_imputed(monkeypatch):
    analysis = SimpleNamespace(research_questions={"rq3": {
        "outcome":{"burned_area_presence_role":"ba"}, "cluster":{"id_role":"unit"},
        "predictors":[{"field_role":"frp", "transform":"log2_positive"}], "factors":[],
    }})
    monkeypatch.setattr(gee, "_population_spec", lambda *args: {"positive_role":"count"})
    monkeypatch.setattr(gee, "_role", lambda _analysis, role: {"keys.yyyymm":"month"}.get(role, role))
    monkeypatch.setattr(gee, "_required_columns", lambda _analysis: ["unit", "month", "count", "ba", "frp"])
    panel = pd.DataFrame({"unit":["a", "a"], "month":[202001, 202002],
                          "count":[0, 1], "ba":[0, 1], "frp":[4.0, 6.0]})
    model = gee.build_gee_population(panel, analysis, enforce_governed_counts=False)
    assert model["month"].tolist() == [202002]
    panel.loc[1, "frp"] = float("nan")
    with pytest.raises(gee.GEEDesignError, match="missing"):
        gee.build_gee_population(panel, analysis, enforce_governed_counts=False)
    panel.loc[1, "frp"] = 0.0
    with pytest.raises(gee.GEEDesignError, match="non-positive"):
        gee.build_gee_population(panel, analysis, enforce_governed_counts=False)
