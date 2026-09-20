# file: tests/test_prepare_year_contract.py
"""
Contract tests for stage: prepare_year.

Requirements covered
--------------------
- Validate fires_canonical schema contract using synthetic data (no real shapefiles).
- Validate deterministic dedup behaviour (rounding + tie-break).
- Validate required columns and fixed column order.

Implementation note
-------------------
We stub the polygon join (join_points_to_units) via monkeypatch to avoid
GeoPandas/Shapely version compatibility issues in test environments.
The spatial join implementation is tested separately (tests/test_geo_join_smoke.py).

This contract suite MUST NOT depend on on-disk shapefiles. We therefore:
- pass points_gdf explicitly (no points file reads)
- pass polygons_by_level for all configured levels (no boundary reads)
- disable land mask in the copied config (no land-mask reads)
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import mv_firms_panels.stages.prepare_year as py_stage
import pandas as pd
import pytest
from mv_firms_panels.core.config import load_config
from mv_firms_panels.core.schema import load_json_schema, validate_dataframe_against_schema


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_cfg():
    repo_root = _repo_root()
    loaded = load_config(
        repo_root / "configs" / "example_project.yaml", validate_paths=False, repo_root=repo_root
    )
    return loaded.config, repo_root


def _stub_join_points_to_units(**kwargs) -> gpd.GeoDataFrame:
    """Deterministic stub for join_points_to_units.

    - Assigns unit_id="A1" for most points.
    - Assigns unit_id=<NA> for a sentinel point at (lat==0, lon==0) to simulate 'unmatched' drops.
    """
    points: gpd.GeoDataFrame = kwargs["points"].copy()
    level: str = kwargs["level"]

    points["level"] = level

    is_unmatched = (points["latitude"] == 0.0) & (points["longitude"] == 0.0)
    points["unit_id"] = pd.Series(["A1"] * len(points), index=points.index, dtype="object")
    points.loc[is_unmatched, "unit_id"] = pd.NA
    points["unit_name"] = "Alpha"
    return points


def _polys_by_level(cfg, pts: gpd.GeoDataFrame) -> dict[str, gpd.GeoDataFrame]:
    """Create placeholder polygons for *all* configured levels.

    These are not used by the join stub, but are required by the call path.
    """
    out: dict[str, gpd.GeoDataFrame] = {}
    for lvl in cfg.io.inputs.polygons:
        cols = {lvl.unit_id_field: ["A1"]}
        if lvl.unit_name_field:
            cols[lvl.unit_name_field] = ["Alpha"]
        out[lvl.level] = gpd.GeoDataFrame(cols, geometry=pts.geometry[:1], crs="EPSG:4326")
    return out


def test_prepare_year_viirs_dedup_schema_and_columns(monkeypatch):
    cfg, repo_root = _load_cfg()
    cfg = cfg.model_copy(deep=True)
    cfg.io.inputs.land_mask = None  # avoid disk IO

    monkeypatch.setattr(py_stage, "join_points_to_units", _stub_join_points_to_units)

    # Two duplicates collapse to one (same time + rounded coords); keep the higher FRP.
    cm = cfg.io.inputs.firms_points["viirs"].column_map  # canonical -> source
    x = [-1.0000001, -1.0000002, 0.0]
    y = [5.0000001, 5.0000002, 0.0]
    pts = gpd.GeoDataFrame(
        {
            cm["latitude"]: y,
            cm["longitude"]: x,
            cm["acq_date"]: ["2020-03-15", "2020-03-15", "2020-03-15"],
            cm["acq_time"]: ["0130", "0130", "0130"],
            cm["confidence"]: ["nominal", "high", "high"],
            cm["frp"]: [10.0, 20.0, 5.0],
            cm.get("daynight", "DAYNIGHT"): ["D", "D", "D"],
            cm.get("satellite", "SATELLITE"): ["N", "N", "N"],
            cm["type"]: [0, 1, 0],
        },
        geometry=gpd.points_from_xy(x, y),
        crs="EPSG:4326",
    )

    res = py_stage.prepare_year(
        cfg=cfg,
        repo_root=repo_root,
        sensor="viirs",
        year=2020,
        run_id="testrun",
        points_gdf=pts,
        polygons_by_level=_polys_by_level(cfg, pts),
        write_outputs=False,
        validate_schema=True,
    )

    fires = res.fires_canonical
    n_levels = len(cfg.io.inputs.polygons)

    # Unmatched sentinel dropped; duplicates collapsed to 1 kept detection per configured level.
    assert len(fires) == n_levels
    assert set(fires["level"].astype(str).tolist()) == {lvl.level for lvl in cfg.io.inputs.polygons}
    assert all(float(x) == 10.0 for x in fires["frp_mw"].tolist())
    assert set(fires["conf_cat"].tolist()) == {"n"}
    assert set(fires["yyyymm"].astype(int).tolist()) == {202003}
    assert set(fires["type"].astype(int).tolist()) == {0}
    assert res.qa_summary["steps"]["type_filter"]["applied_before_dedup"] is True
    assert res.qa_summary["steps"]["type_filter"]["n_dropped_nonzero"] == 1

    # Fixed column order must match config
    expected_cols = cfg.determinism.column_order["fires_canonical"]
    assert list(fires.columns) == expected_cols

    # Explicit schema validation
    schema_path = (repo_root / cfg.outputs.schemas["fires_canonical"]).resolve()
    schema = load_json_schema(schema_path)
    validate_dataframe_against_schema(
        df=fires, schema=schema, expected_columns=expected_cols, allow_reorder=True
    )


def test_prepare_year_modis_confidence_mapping(monkeypatch):
    cfg, repo_root = _load_cfg()
    cfg = cfg.model_copy(deep=True)
    cfg.io.inputs.land_mask = None  # avoid disk IO

    monkeypatch.setattr(py_stage, "join_points_to_units", _stub_join_points_to_units)

    cm = cfg.io.inputs.firms_points["modis"].column_map
    x = [-1.1, -1.2]
    y = [5.1, 5.2]
    pts = gpd.GeoDataFrame(
        {
            cm["latitude"]: y,
            cm["longitude"]: x,
            cm["acq_date"]: ["2021-01-02", "2021-01-02"],
            cm["acq_time"]: [30, 30],
            cm["confidence"]: [
                10,
                95,
            ],  # low, high under default thresholds (low_lt=30, high_ge=80)
            cm["frp"]: [1.0, 2.0],
            cm.get("daynight", "DAYNIGHT"): ["N", "N"],
            cm.get("satellite", "SATELLITE"): ["T", "T"],
            cm["type"]: [0, 0],
        },
        geometry=gpd.points_from_xy(x, y),
        crs="EPSG:4326",
    )

    res = py_stage.prepare_year(
        cfg=cfg,
        repo_root=repo_root,
        sensor="modis",
        year=2021,
        run_id="testrun",
        points_gdf=pts,
        polygons_by_level=_polys_by_level(cfg, pts),
        write_outputs=False,
        validate_schema=True,
    )

    fires = res.fires_canonical.sort_values(["frp_mw"], kind="mergesort")
    n_levels = len(cfg.io.inputs.polygons)
    assert list(fires["conf_cat"]) == (["l"] * n_levels) + (["h"] * n_levels)


def test_prepare_year_missing_firms_file_reports_access_guidance(tmp_path: Path) -> None:
    with pytest.raises(py_stage.PrepareYearError) as excinfo:
        py_stage.resolve_annual_points_path(
            repo_root=tmp_path,
            file_glob="data/raw/firms/viirs/*.csv",
            sensor="viirs",
            year=2020,
        )

    msg = str(excinfo.value)
    assert "Missing required Stage 2 input `firms_points[viirs]`" in msg
    assert "docs/data_access.md" in msg
    assert "README.md" in msg
    assert "Required by stage: rp1_mv_firms_panels prepare_year." in msg
