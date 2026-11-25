"""Derived population sizes come from validated inputs, not expected results."""
from types import SimpleNamespace
import pytest
from rp1_analysis_v1.publication_sources import _population_table


def test_publication_population_table_uses_realised_counts():
    populations = {name: {"source_panel":"district_monthly", "units":None, "rows":None,
                         "start":"2020-01", "end":"2020-12", "eligibility":"configured_rule"}
                   for name in ("acz_monthly","district_monthly","long_run_district","paired_overlap","rq3_model")}
    bundle = SimpleNamespace(analysis=SimpleNamespace(study={"populations":populations}))
    summary = SimpleNamespace(acz_count=2,acz_monthly_rows=24,district_spatial_universe_count=7,district_monthly_rows=84,
        long_run_eligible_count=6,long_run_rows=72,paired_eligible_count=5,paired_rows=60,rq3_gee_units=4,rq3_gee_rows=19)
    result = _population_table(bundle,summary).set_index("population_id")
    assert result.loc["rq3_model","units"] == 4
    assert result.loc["rq3_model","rows"] == 19
    assert result.loc["long_run_district","rows"] == 72
