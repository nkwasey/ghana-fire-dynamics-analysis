# file: tests/test_prepare_year_type_filter.py
from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import mv_firms_panels.stages.prepare_year as py_stage
import pandas as pd
from mv_firms_panels.core.config import load_config


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_cfg():
    repo_root = _repo_root()
    loaded = load_config(
        repo_root / "configs" / "example_project.yaml", validate_paths=False, repo_root=repo_root
    )
    return loaded.config, repo_root


def _stub_join_points_to_units(**kwargs) -> gpd.GeoDataFrame:
    points: gpd.GeoDataFrame = kwargs["points"].copy()
    points["level"] = kwargs["level"]
    points["unit_id"] = pd.Series(["A1"] * len(points), index=points.index, dtype="object")
    points["unit_name"] = "Alpha"
    return points


def _polys_by_level(cfg, pts: gpd.GeoDataFrame) -> dict[str, gpd.GeoDataFrame]:
    out: dict[str, gpd.GeoDataFrame] = {}
    for lvl in cfg.io.inputs.polygons:
        cols = {lvl.unit_id_field: ["A1"]}
        if lvl.unit_name_field:
            cols[lvl.unit_name_field] = ["Alpha"]
        out[lvl.level] = gpd.GeoDataFrame(cols, geometry=pts.geometry[:1], crs="EPSG:4326")
    return out


def test_type_filter_applies_before_dedup(monkeypatch) -> None:
    cfg, repo_root = _load_cfg()
    cfg = cfg.model_copy(deep=True)
    cfg.io.inputs.land_mask = None

    monkeypatch.setattr(py_stage, "join_points_to_units", _stub_join_points_to_units)

    cm = cfg.io.inputs.firms_points["viirs"].column_map
    x = [-1.0000001, -1.0000002]
    y = [5.0000001, 5.0000002]
    pts = gpd.GeoDataFrame(
        {
            cm["latitude"]: y,
            cm["longitude"]: x,
            cm["acq_date"]: ["2020-03-15", "2020-03-15"],
            cm["acq_time"]: ["0130", "0130"],
            cm["confidence"]: ["nominal", "high"],
            cm["frp"]: [10.0, 999.0],
            cm.get("daynight", "DAYNIGHT"): ["D", "D"],
            cm.get("satellite", "SATELLITE"): ["N", "N"],
            cm["type"]: [0, 1],
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
    assert len(fires) == n_levels
    assert set(fires["type"].astype(int).tolist()) == {0}
    assert set(fires["frp_mw"].astype(float).tolist()) == {10.0}
    assert res.qa_summary["steps"]["type_filter"]["applied_before_dedup"] is True
    assert res.qa_summary["steps"]["type_filter"]["n_dropped_nonzero"] == 1


def test_type_filter_rejects_nonzero_rows_from_output(monkeypatch) -> None:
    cfg, repo_root = _load_cfg()
    cfg = cfg.model_copy(deep=True)
    cfg.io.inputs.land_mask = None

    monkeypatch.setattr(py_stage, "join_points_to_units", _stub_join_points_to_units)

    cm = cfg.io.inputs.firms_points["modis"].column_map
    x = [-1.1, -1.2, -1.3]
    y = [5.1, 5.2, 5.3]
    pts = gpd.GeoDataFrame(
        {
            cm["latitude"]: y,
            cm["longitude"]: x,
            cm["acq_date"]: ["2021-01-02", "2021-01-02", "2021-01-02"],
            cm["acq_time"]: [30, 31, 32],
            cm["confidence"]: [10, 50, 95],
            cm["frp"]: [1.0, 2.0, 3.0],
            cm.get("daynight", "DAYNIGHT"): ["N", "N", "N"],
            cm.get("satellite", "SATELLITE"): ["T", "T", "T"],
            cm["type"]: [0, 0, 2],
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

    fires = res.fires_canonical
    assert set(fires["type"].astype(int).tolist()) == {0}
    assert not (fires["type"].astype(int) != 0).any()
