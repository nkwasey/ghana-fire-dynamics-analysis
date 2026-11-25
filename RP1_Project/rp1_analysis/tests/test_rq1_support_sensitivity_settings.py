"""Contract consistency for the district diagnostics and named restricted scan."""

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
import yaml

from rp1_analysis_v1.design import (
    DesignValidationError,
    rq1_support_sensitivity_settings,
    validate_analysis_design,
)
from rp1_analysis_v1.supplementary_analysis import _support_figure


@pytest.fixture
def analysis_design():
    path = Path(__file__).resolve().parents[1] / "config" / "analysis_contract.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_support_figure_marks_the_governed_restricted_assay(analysis_design):
    rq1 = analysis_design["research_questions"]["rq1"]
    rq1["support_sensitivity"]["thresholds_km2"] = [0, 15, 50, 75]
    validate_analysis_design(analysis_design)
    settings = rq1_support_sensitivity_settings(rq1)
    assert settings.thresholds_km2 == (0.0, 15.0, 50.0, 75.0)
    assert settings.block_lengths_years == (2, 3, 4, 6)
    diagnostic = SimpleNamespace(
        district_support=pd.DataFrame(
            [
                dict(
                    baseline_eligible=True, unit_id="synthetic", parent_code="CZ",
                    fixed_burnable_union_km2=75.0, long_run_rate=1.0,
                )
            ],
        ),
        threshold_by_acz=pd.DataFrame(
            dict(
                parent_code="CZ", minimum_fixed_union_km2=settings.thresholds_km2,
                district_rate_gini=0.5, district_count=1,
            ),
        ),
    )
    source = _support_figure(diagnostic, settings.restricted_scan_cutoff_km2)
    selected = source.loc[source["is_primary_threshold"], "minimum_fixed_union_km2"]
    assert selected.tolist() == [50.0]


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("restricted_scan_cutoff_km2", 55, "must agree with the named BA-2001 GT50 scan"),
        ("thresholds_km2", [0, 10, 75], "must include the restricted scan cutoff"),
        ("thresholds_km2", [0, 10, 50, 50], "strictly increasing"),
        ("thresholds_km2", [0, 50, float("inf")], "must be finite"),
        ("primary_block_length_years", 1, "include the primary block"),
        ("bootstrap_replications", 1, "must be at least two"),
    ],
)
def test_inconsistent_support_settings_are_rejected(analysis_design, key, value, message):
    analysis_design["research_questions"]["rq1"]["support_sensitivity"][key] = value
    with pytest.raises(DesignValidationError, match=message):
        validate_analysis_design(analysis_design)


def test_legacy_defaults_are_explicit_and_cannot_hide_partial_settings():
    old = {"support_sensitivity": {"block_endpoint_materiality_fraction": 0.25}}
    with pytest.raises(DesignValidationError, match="missing settings"):
        rq1_support_sensitivity_settings(old)
    assert rq1_support_sensitivity_settings(old, allow_legacy_snapshot=True).thresholds_km2 == (0, 10, 50, 100)
    old["support_sensitivity"]["restricted_scan_cutoff_km2"] = 50
    with pytest.raises(DesignValidationError, match="missing settings"):
        rq1_support_sensitivity_settings(old, allow_legacy_snapshot=True)
