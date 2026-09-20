from __future__ import annotations

import geopandas as gpd
import pandas as pd
from geo_data_prep.qa.defensibility import (
    build_sliver_diagnostics,
    run_working_crs_sensitivity_study,
)
from geo_data_prep.spatial.overlay import assign_districts_to_zones_by_max_share
from shapely.geometry import Polygon


def _square(x0: float, y0: float, x1: float, y1: float) -> Polygon:
    return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def test_build_sliver_diagnostics_summarises_small_candidate_overlaps() -> None:
    overlap = pd.DataFrame(
        [
            {
                "district_id": "D1",
                "zone_id": "Z1",
                "zone_name": "Zone 1",
                "ovl_share": 0.9,
                "intersection_area_sq_m": 90.0,
                "is_assigned": True,
                "rank": 1,
            },
            {
                "district_id": "D1",
                "zone_id": "Z2",
                "zone_name": "Zone 2",
                "ovl_share": 0.1,
                "intersection_area_sq_m": 10.0,
                "is_assigned": False,
                "rank": 2,
            },
        ]
    )

    summary = build_sliver_diagnostics(
        overlap,
        share_cutoffs=[0.2],
        area_sqkm_cutoffs=[0.00002],
        example_limit=2,
    )

    assert summary["rows"] == 2
    assert summary["candidate_only_rows"] == 1
    assert summary["share_counts_all_rows"] == [{"cutoff": 0.2, "count": 1}]
    assert summary["share_counts_candidate_only"] == [{"cutoff": 0.2, "count": 1}]
    assert summary["area_sqkm_counts_candidate_only"] == [{"cutoff": 0.00002, "count": 1}]
    assert summary["small_overlap_examples"][0]["district_id"] == "D1"
    assert summary["small_overlap_examples"][0]["zone_id"] == "Z2"


def test_working_crs_sensitivity_study_recommends_retaining_rule_when_assignments_are_stable() -> (
    None
):
    zones = gpd.GeoDataFrame(
        {
            "zone_id": ["zone_a", "zone_b"],
            "zone_name": ["Zone A", "Zone B"],
            "zone_code": ["ZA", "ZB"],
        },
        geometry=[_square(-1.0, 0.0, 0.0, 1.0), _square(0.0, 0.0, 1.0, 1.0)],
        crs="EPSG:4326",
    )
    districts = gpd.GeoDataFrame(
        {
            "district_id": ["D1", "D2"],
            "district_name": ["District 1", "District 2"],
        },
        geometry=[_square(-1.0, 0.0, 0.0, 1.0), _square(0.0, 0.0, 1.0, 1.0)],
        crs="EPSG:4326",
    )

    baseline = assign_districts_to_zones_by_max_share(
        districts,
        zones,
        working_crs="EPSG:3857",
    )
    study = run_working_crs_sensitivity_study(
        districts,
        zones,
        baseline_districts_enriched=baseline.districts_enriched,
        working_crs="EPSG:3857",
    )

    assert study.summary["status"] == "pass"
    assert study.summary["ok"] is True
    assert study.summary["assignment_identity_change_count"] == 0
    assert study.summary["recommendation"] == "retain_max_overlap_rule"
    assert study.summary["alternative_equal_area_crs"]["area_preserving"] is True
    assert study.comparison_table["assignment_identity_changed"].sum() == 0
