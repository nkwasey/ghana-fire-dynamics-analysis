from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from geo_data_prep.spatial.overlay import (
    AREA_METHOD_COL,
    AREA_UNITS_COL,
    ASSIGNED_SHARE_COL,
    ASSIGNMENT_METHOD_COL,
    ASSIGNMENT_STATUS_COL,
    DISTRICT_AREA_EXPLICIT_COL,
    INTERSECTION_AREA_EXPLICIT_COL,
    LEGACY_DISAGREEMENT_COL,
    LEGACY_MATCH_COL,
    LEGACY_PRESENT_COL,
    LEGACY_ZONE_CODE_COL,
    LEGACY_ZONE_ID_COL,
    LEGACY_ZONE_NAME_COL,
    OVERLAP_GAP_COL,
    OVERLAP_GAP_FRAC_COL,
    OVERLAP_SUM_COL,
    SHARE_BASIS_COL,
    TIE_BREAK_APPLIED_COL,
    TIE_CANDIDATE_COUNT_COL,
    WORKING_CRS_COL,
    assign_districts_to_zones_by_max_share,
)
from shapely.geometry import Polygon


def _square(x0: float, y0: float, x1: float, y1: float) -> Polygon:
    return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def test_overlay_assignment_max_share_emits_richer_contract_columns() -> None:
    crs = "EPSG:3857"

    zones = gpd.GeoDataFrame(
        {
            "zone_id": ["A", "B"],
            "zone_name": ["Zone A", "Zone B"],
            "zone_code": ["ZA", "ZB"],
        },
        geometry=[_square(0, 0, 3, 1), _square(3, 0, 4, 1)],
        crs=crs,
    )
    districts = gpd.GeoDataFrame(
        {"district_id": ["D1"], "district_name": ["District 1"]},
        geometry=[_square(0, 0, 4, 1)],
        crs=crs,
    )

    res = assign_districts_to_zones_by_max_share(
        districts,
        zones,
        working_crs=crs,
        district_id_col="district_id",
        zone_id_col="zone_id",
        zone_cols=("zone_name", "zone_code"),
        fail_on_unassigned=True,
    )

    out = res.districts_enriched
    row = out.iloc[0]

    # Enriched district output: one row per district with chosen assignment
    # plus district-level diagnostics.
    assert row["zone_id"] == "A"
    assert row["zone_name"] == "Zone A"
    assert row["zone_code"] == "ZA"
    assert row["ovl_share"] == pytest.approx(0.75, abs=1e-12)
    assert row[ASSIGNED_SHARE_COL] == pytest.approx(0.75, abs=1e-12)
    assert row[ASSIGNMENT_STATUS_COL] == "assigned"
    assert row[ASSIGNMENT_METHOD_COL] == "max_intersection_share"
    assert row[AREA_METHOD_COL] == "projected"
    assert row[AREA_UNITS_COL] == "sq_m"
    assert row[WORKING_CRS_COL] == crs
    assert row[SHARE_BASIS_COL] == "intersection_over_district_area"
    assert int(row[TIE_CANDIDATE_COUNT_COL]) == 1
    assert bool(row[TIE_BREAK_APPLIED_COL]) is False
    assert float(row[DISTRICT_AREA_EXPLICIT_COL]) > 0
    assert row[OVERLAP_SUM_COL] == pytest.approx(row[DISTRICT_AREA_EXPLICIT_COL], rel=0, abs=1e-9)
    assert row[OVERLAP_GAP_COL] == pytest.approx(0.0, abs=1e-9)
    assert row[OVERLAP_GAP_FRAC_COL] == pytest.approx(0.0, abs=1e-12)

    # Row-specific overlap metrics belong on the overlap table, not the
    # district-enriched assignment frame.
    assert INTERSECTION_AREA_EXPLICIT_COL not in out.columns

    tbl = res.overlap_table
    assert list(tbl["zone_id"]) == ["A", "B"]
    assert list(tbl["rank"]) == [1, 2]
    assert list(tbl["is_assigned"]) == [True, False]
    assert list(tbl[ASSIGNMENT_STATUS_COL]) == ["assigned", "candidate_not_selected"]

    assigned = tbl.loc[tbl["is_assigned"]].reset_index(drop=True)
    rejected = tbl.loc[~tbl["is_assigned"]].reset_index(drop=True)

    assert assigned.loc[0, ASSIGNED_SHARE_COL] == pytest.approx(0.75, abs=1e-12)
    assert assigned.loc[0, DISTRICT_AREA_EXPLICIT_COL] > 0
    assert assigned.loc[0, INTERSECTION_AREA_EXPLICIT_COL] > 0
    assert assigned.loc[0, INTERSECTION_AREA_EXPLICIT_COL] == pytest.approx(
        assigned.loc[0, DISTRICT_AREA_EXPLICIT_COL] * assigned.loc[0, "ovl_share"],
        rel=0,
        abs=1e-9,
    )
    assert pd.isna(rejected.loc[0, ASSIGNED_SHARE_COL])
    assert assigned.loc[0, OVERLAP_SUM_COL] == pytest.approx(
        assigned.loc[0, DISTRICT_AREA_EXPLICIT_COL],
        rel=0,
        abs=1e-9,
    )
    assert rejected.loc[0, OVERLAP_GAP_FRAC_COL] == pytest.approx(0.0, abs=1e-12)


def test_overlay_tie_break_is_deterministic_and_uses_zone_id_first() -> None:
    crs = "EPSG:3857"

    zones = gpd.GeoDataFrame(
        {
            "zone_id": ["B", "A"],
            "zone_name": ["Zone B", "Zone A"],
            "zone_code": ["ZB", "ZA"],
        },
        geometry=[_square(1, 0, 2, 1), _square(0, 0, 1, 1)],
        crs=crs,
    )
    districts = gpd.GeoDataFrame(
        {"district_id": ["D_tie"], "district_name": ["District tie"]},
        geometry=[_square(0, 0, 2, 1)],
        crs=crs,
    )

    res = assign_districts_to_zones_by_max_share(
        districts,
        zones,
        working_crs=crs,
        district_id_col="district_id",
        zone_id_col="zone_id",
        zone_cols=("zone_name", "zone_code"),
        tie_tol=1e-12,
        fail_on_unassigned=True,
    )

    out = res.districts_enriched.iloc[0]
    assert out["zone_id"] == "A"
    assert out["ovl_share"] == pytest.approx(0.5, abs=1e-12)
    assert int(out[TIE_CANDIDATE_COUNT_COL]) == 2
    assert bool(out[TIE_BREAK_APPLIED_COL]) is True

    tbl = res.overlap_table
    assert list(tbl["zone_id"]) == ["A", "B"]
    assert tbl["ovl_share"].tolist() == pytest.approx([0.5, 0.5], abs=1e-12)
    assert list(tbl["is_assigned"]) == [True, False]


def test_overlay_no_overlap_can_return_explicit_unassigned_state() -> None:
    crs = "EPSG:3857"

    zones = gpd.GeoDataFrame(
        {
            "zone_id": ["A"],
            "zone_name": ["Zone A"],
            "zone_code": ["ZA"],
        },
        geometry=[_square(0, 0, 1, 1)],
        crs=crs,
    )
    districts = gpd.GeoDataFrame(
        {"district_id": ["D0"], "district_name": ["District 0"]},
        geometry=[_square(10, 10, 11, 11)],
        crs=crs,
    )

    res = assign_districts_to_zones_by_max_share(
        districts,
        zones,
        working_crs=crs,
        district_id_col="district_id",
        zone_id_col="zone_id",
        zone_cols=("zone_name", "zone_code"),
        fail_on_unassigned=False,
    )

    out = res.districts_enriched.iloc[0]
    assert pd.isna(out["zone_id"])
    assert pd.isna(out["zone_name"])
    assert pd.isna(out["zone_code"])
    assert out["ovl_share"] == pytest.approx(0.0, abs=1e-12)
    assert out[ASSIGNED_SHARE_COL] == pytest.approx(0.0, abs=1e-12)
    assert out[ASSIGNMENT_STATUS_COL] == "unassigned_no_overlap"
    assert int(out[TIE_CANDIDATE_COUNT_COL]) == 0
    assert bool(out[TIE_BREAK_APPLIED_COL]) is False
    assert out[AREA_METHOD_COL] == "projected"
    assert out[AREA_UNITS_COL] == "sq_m"
    assert out[SHARE_BASIS_COL] == "intersection_over_district_area"

    tbl = res.overlap_table
    assert tbl.empty
    assert {
        "district_id",
        "zone_id",
        "zone_name",
        "zone_code",
        "ovl_share",
        "rank",
        "is_assigned",
        DISTRICT_AREA_EXPLICIT_COL,
        INTERSECTION_AREA_EXPLICIT_COL,
        OVERLAP_SUM_COL,
        OVERLAP_GAP_COL,
        OVERLAP_GAP_FRAC_COL,
        ASSIGNMENT_METHOD_COL,
        AREA_METHOD_COL,
        AREA_UNITS_COL,
        WORKING_CRS_COL,
        SHARE_BASIS_COL,
        TIE_CANDIDATE_COUNT_COL,
        TIE_BREAK_APPLIED_COL,
        ASSIGNMENT_STATUS_COL,
        LEGACY_ZONE_ID_COL,
        LEGACY_ZONE_NAME_COL,
        LEGACY_ZONE_CODE_COL,
        LEGACY_PRESENT_COL,
        LEGACY_MATCH_COL,
        LEGACY_DISAGREEMENT_COL,
    }.issubset(set(tbl.columns))


def test_overlay_preserves_legacy_assignment_diagnostics_when_recomputed_assignment_differs() -> (
    None
):
    crs = "EPSG:3857"

    zones = gpd.GeoDataFrame(
        {
            "zone_id": ["A", "B"],
            "zone_name": ["Zone A", "Zone B"],
            "zone_code": ["ZA", "ZB"],
        },
        geometry=[_square(0, 0, 3, 1), _square(3, 0, 4, 1)],
        crs=crs,
    )
    districts = gpd.GeoDataFrame(
        {
            "district_id": ["D_legacy"],
            "district_name": ["District legacy"],
            "zone_id": ["B"],
            "zone_name": ["Zone B"],
            "zone_code": ["ZB"],
        },
        geometry=[_square(0, 0, 4, 1)],
        crs=crs,
    )

    res = assign_districts_to_zones_by_max_share(
        districts,
        zones,
        working_crs=crs,
        district_id_col="district_id",
        zone_id_col="zone_id",
        zone_cols=("zone_name", "zone_code"),
        fail_on_unassigned=True,
    )

    out = res.districts_enriched.iloc[0]
    assert out["zone_id"] == "A"
    assert bool(out[LEGACY_PRESENT_COL]) is True
    assert out[LEGACY_ZONE_ID_COL] == "B"
    assert out[LEGACY_ZONE_NAME_COL] == "Zone B"
    assert out[LEGACY_ZONE_CODE_COL] == "ZB"
    assert bool(out[LEGACY_MATCH_COL]) is False
    assert bool(out[LEGACY_DISAGREEMENT_COL]) is True

    tbl = res.overlap_table
    assigned = tbl.loc[tbl["is_assigned"]].reset_index(drop=True)
    rejected = tbl.loc[~tbl["is_assigned"]].reset_index(drop=True)

    assert assigned.loc[0, "zone_id"] == "A"
    assert bool(assigned.loc[0, LEGACY_MATCH_COL]) is False
    assert bool(assigned.loc[0, LEGACY_DISAGREEMENT_COL]) is True

    assert rejected.loc[0, "zone_id"] == "B"
    assert bool(rejected.loc[0, LEGACY_MATCH_COL]) is True
    assert bool(rejected.loc[0, LEGACY_DISAGREEMENT_COL]) is False


def test_overlay_normalises_tolerance_level_share_overshoot_before_serialisation(monkeypatch) -> None:
    """Tiny floating-point overshoot must not leak into the assignment-share contract."""
    crs = "EPSG:3857"
    zones = gpd.GeoDataFrame(
        {"zone_id": ["A"], "zone_name": ["Zone A"], "zone_code": ["ZA"]},
        geometry=[_square(0, 0, 1, 1)],
        crs=crs,
    )
    districts = gpd.GeoDataFrame(
        {"district_id": ["D1"], "district_name": ["District 1"]},
        geometry=[_square(0, 0, 1, 1)],
        crs=crs,
    )

    import geo_data_prep.spatial.area as area_module

    calls = {"n": 0}

    def fake_projected_area_series(gdf, *, projected_crs=None, units="sq_km"):
        calls["n"] += 1
        value = 1.0 if calls["n"] == 1 else 1.0 + 5e-13
        return pd.Series([value] * len(gdf), index=gdf.index, dtype=float)

    monkeypatch.setattr(area_module, "projected_area_series", fake_projected_area_series)

    result = assign_districts_to_zones_by_max_share(
        districts,
        zones,
        working_crs=crs,
        district_id_col="district_id",
        zone_id_col="zone_id",
        zone_cols=("zone_name", "zone_code"),
    )

    assigned = result.districts_enriched.iloc[0]
    overlap = result.overlap_table.iloc[0]
    assert assigned["ovl_share"] == 1.0
    assert overlap["ovl_share"] == 1.0
    assert overlap[DISTRICT_AREA_EXPLICIT_COL] == pytest.approx(1.0)
    assert overlap[INTERSECTION_AREA_EXPLICIT_COL] == pytest.approx(1.0 + 5e-13)
