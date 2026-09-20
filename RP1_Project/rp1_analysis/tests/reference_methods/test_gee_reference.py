"""Independent hand-verifiable checks for the fixed GEE mean-model design."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.contracts import freeze
from rp1_analysis_v1.gee import build_gee_mean_model_design

SUBPROJECT = Path(__file__).resolve().parents[2]


def test_small_design_matches_independent_hand_calculation():
    analysis = load_configuration_bundle(SUBPROJECT / "config").analysis
    # A tiny controlled frame; disable governed n/count enforcement only for reference qualification.
    frame = pd.DataFrame({
        "unit_id": ["a", "a", "b", "b"],
        "yyyymm": [201301, 201302, 201401, 201402],
        "year": [2013, 2013, 2014, 2014],
        "month": [1, 2, 1, 2],
        "parent_code": ["CZ", "CZ", "FZ", "FZ"],
        "viirs_det_primary_any": [1, 1, 1, 1],
        "modis_ba_any_ba2012": [0, 1, 0, 1],
        "viirs_det_primary": [1.0, 2.0, 4.0, 8.0],
        "viirs_frp_mean_mw": [2.0, 4.0, 8.0, 16.0],
        "modis_burnable_km2_union_ba2012": [64.0, 64.0, 128.0, 128.0],
        "mismatch_y": [1, 0, 1, 0],
    })
    design = build_gee_mean_model_design(frame, analysis, enforce_governed_counts=False)
    X = design.design_matrix
    np.testing.assert_allclose(X["log2_viirs_det_primary"], [0, 1, 2, 3])
    np.testing.assert_allclose(X["log2_viirs_frp_mean_mw"], [1, 2, 3, 4])
    np.testing.assert_allclose(X["log2_modis_burnable_km2_union_ba2012"], [6, 6, 7, 7])
    assert list(X.columns[:4]) == [
        "Intercept",
        "log2_viirs_det_primary",
        "log2_viirs_frp_mean_mw",
        "log2_modis_burnable_km2_union_ba2012",
    ]
    np.testing.assert_allclose(X["month_2"], [0, 1, 0, 1])
    np.testing.assert_allclose(X["year_2014"], [0, 0, 1, 1])
    np.testing.assert_allclose(X["acz_FZ"], [0, 0, 1, 1])
    assert "month_1" not in X
    assert "year_2013" not in X
    assert "acz_CZ" not in X
