"""Raw observations must reach FRP independently of count deduplication."""
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pandas.testing as pdt
import pytest
from shapely.geometry import Polygon

from mv_firms_panels.core.config import load_config
from mv_firms_panels.stages import prepare_year as prep
from mv_firms_panels.stages.aggregate_monthly import AggregateMonthlyError, aggregate_monthly
from mv_firms_panels.stages.combine_panels import combine_panels


ROOT = Path(__file__).resolve().parents[1]


def setup_case(monkeypatch, tmp_path, confidence=("low", "nominal"), frp=(100.0, 4.0), year=2020, date=None, time="0130"):
    cfg = load_config(ROOT / "configs/example_project.yaml", validate_paths=False, repo_root=ROOT).config
    cfg.io.inputs.land_mask = None
    cfg.outputs.base_dir = "runs"
    cm = cfg.io.inputs.firms_points["viirs"].column_map
    points = gpd.GeoDataFrame({
        cm["latitude"]: [5.0] * len(frp), cm["longitude"]: [-1.0] * len(frp),
        cm["acq_date"]: [date or f"{year}-03-15"] * len(frp), cm["acq_time"]: [time] * len(frp),
        cm["confidence"]: list(confidence), cm["frp"]: list(frp), cm["type"]: [0] * len(frp),
        cm.get("satellite", "SATELLITE"): ["N"] * len(frp),
        cm.get("daynight", "DAYNIGHT"): ["D"] * len(frp),
    }, geometry=gpd.points_from_xy([-1.0] * len(frp), [5.0] * len(frp)), crs="EPSG:4326")
    def join(**kw):
        result = kw["points"].copy()
        result["unit_id"] = "U1"
        return result
    monkeypatch.setattr(prep, "join_points_to_units", join)
    polygons = {lvl.level: gpd.GeoDataFrame({lvl.unit_id_field: ["U1"]}, geometry=points.geometry[:1], crs=points.crs) for lvl in cfg.io.inputs.polygons}
    source = tmp_path / f"source_{year}.csv"
    source.write_text("fixture source", encoding="utf-8")
    prepared = prep.prepare_year(cfg=cfg, repo_root=tmp_path, sensor="viirs", year=year,
        run_id="test", points_gdf=points, points_path=source, polygons_by_level=polygons,
        write_outputs=True, validate_schema=False)
    return cfg, prepared


def test_raw_competition_streaming_and_memory(monkeypatch, tmp_path):
    cfg, prepared = setup_case(monkeypatch, tmp_path)
    assert set(prepared.fires_canonical.frp_mw) == {100.0}
    assert set(prepared.fires_canonical.conf_cat) == {"l"}
    assert set(prepared.fires_frp_canonical.frp_mw) == {4.0}
    memory = aggregate_monthly(cfg=cfg, repo_root=tmp_path, sensor="viirs", run_id="test",
        fires_canonical_df=prepared.fires_canonical, fires_frp_canonical_df=prepared.fires_frp_canonical,
        start_yyyymm=202003, end_yyyymm=202003, write_outputs=False).panel_sensor_monthly
    disk = aggregate_monthly(cfg=cfg, repo_root=tmp_path, sensor="viirs", run_id="test",
        start_yyyymm=202003, end_yyyymm=202003, write_outputs=False).panel_sensor_monthly
    pdt.assert_frame_equal(memory, disk)
    assert memory.viirs_det_low.eq(1).all()
    assert memory.viirs_det_nh.eq(0).all()
    assert memory.viirs_days_active_nh.eq(0).all()
    assert memory.viirs_frp_mean_mw.eq(4).all()
    assert memory.viirs_frp_active_days.eq(1).all()


def test_frp_only_geographic_support_in_memory(monkeypatch, tmp_path):
    cfg, prepared = setup_case(monkeypatch, tmp_path)
    monthly = aggregate_monthly(cfg=cfg, repo_root=tmp_path, sensor="viirs", run_id="test",
        fires_canonical_df=prepared.fires_canonical.iloc[:0], fires_frp_canonical_df=prepared.fires_frp_canonical,
        start_yyyymm=202003, end_yyyymm=202003, write_outputs=False).panel_sensor_monthly
    assert monthly.viirs_det_nh.eq(0).all()
    assert monthly.viirs_frp_mean_mw.eq(4).all()


def test_empty_partition_and_tampering(monkeypatch, tmp_path):
    cfg, prepared = setup_case(monkeypatch, tmp_path, ("low", "low"), (100., 4.))
    assert prepared.fires_frp_canonical.empty
    result = aggregate_monthly(cfg=cfg, repo_root=tmp_path, sensor="viirs", run_id="test", start_yyyymm=202003, end_yyyymm=202003, write_outputs=False)
    assert result.panel_sensor_monthly.viirs_frp_mean_mw.isna().all()
    prepared.fires_frp_canonical_path.write_text("broken\n", encoding="utf-8")
    with pytest.raises(AggregateMonthlyError):
        aggregate_monthly(cfg=cfg, repo_root=tmp_path, sensor="viirs", run_id="test", start_yyyymm=202003, end_yyyymm=202003, write_outputs=False)


@pytest.mark.parametrize("values,expected", [((float("inf"), 4.), 4.), ((float("inf"), float("inf")), float("inf")), ((4., 4.), 4.)])
def test_finite_precedes_nonfinite_and_ties(monkeypatch, tmp_path, values, expected):
    cfg, prepared = setup_case(monkeypatch, tmp_path, ("nominal", "high"), values)
    assert set(prepared.fires_frp_canonical.frp_mw) == {expected}
    if values[0] == values[1]:
        assert set(prepared.fires_frp_canonical.conf_cat) == {"h"}
    result = aggregate_monthly(cfg=cfg, repo_root=tmp_path, sensor="viirs", run_id="test", start_yyyymm=202003, end_yyyymm=202003, write_outputs=False)
    if expected == float("inf"):
        assert result.panel_sensor_monthly.viirs_frp_mean_mw.isna().all()
    else:
        assert result.panel_sensor_monthly.viirs_frp_mean_mw.eq(expected).all()


def test_exact_threshold_is_included(monkeypatch, tmp_path):
    cfg, prepared = setup_case(monkeypatch, tmp_path, ("low", "nominal"), (100.0, 4.0))
    cfg.processing.frp_policy.min_frp_mw = 4.0
    result = aggregate_monthly(cfg=cfg, repo_root=tmp_path, sensor="viirs", run_id="test",
        fires_canonical_df=prepared.fires_canonical, fires_frp_canonical_df=prepared.fires_frp_canonical,
        start_yyyymm=202003, end_yyyymm=202003, write_outputs=False)
    assert result.panel_sensor_monthly.viirs_frp_mean_mw.eq(4).all()


def test_missing_and_stale_preparation_evidence_is_rejected(monkeypatch, tmp_path):
    cfg, prepared = setup_case(monkeypatch, tmp_path)
    prepared.fires_frp_canonical_path.unlink()
    with pytest.raises(AggregateMonthlyError):
        aggregate_monthly(cfg=cfg, repo_root=tmp_path, sensor="viirs", run_id="test",
            start_yyyymm=202003, end_yyyymm=202003, write_outputs=False)


def test_raw_competition_uses_real_spatial_join():
    cfg = load_config(ROOT / "configs/example_project.yaml", validate_paths=False, repo_root=ROOT).config
    cfg.io.inputs.land_mask = None
    cm = cfg.io.inputs.firms_points["viirs"].column_map
    points = gpd.GeoDataFrame({cm["latitude"]:[5.0, 5.0], cm["longitude"]:[-1.0, -1.0],
        cm["acq_date"]:["2020-03-15"]*2, cm["acq_time"]:["0130"]*2,
        cm["confidence"]:["low", "nominal"], cm["frp"]:[100.0, 4.0],
        cm["type"]:[0, 0], cm.get("satellite", "SATELLITE"):["N", "N"],
        cm.get("daynight", "DAYNIGHT"):["D", "D"]},
        geometry=gpd.points_from_xy([-1.0, -1.0], [5.0, 5.0]), crs="EPSG:4326")
    polygon = Polygon([(-2, 4), (0, 4), (0, 6), (-2, 6)])
    polygons = {}
    for lvl in cfg.io.inputs.polygons:
        values = {lvl.unit_id_field:["U1"]}
        if lvl.unit_name_field:
            values[lvl.unit_name_field] = ["Unit"]
        polygons[lvl.level] = gpd.GeoDataFrame(values, geometry=[polygon], crs="EPSG:4326")
    prepared = prep.prepare_year(cfg=cfg, repo_root=ROOT, sensor="viirs", year=2020, run_id="test",
        points_gdf=points, polygons_by_level=polygons, write_outputs=False)
    monthly = aggregate_monthly(cfg=cfg, repo_root=ROOT, sensor="viirs", run_id="test",
        fires_canonical_df=prepared.fires_canonical, fires_frp_canonical_df=prepared.fires_frp_canonical,
        start_yyyymm=202003, end_yyyymm=202003, write_outputs=False).panel_sensor_monthly
    assert len(monthly) == len(cfg.io.inputs.polygons)
    assert monthly.viirs_det_nh.eq(0).all()
    assert monthly.viirs_frp_mean_mw.eq(4.0).all()
    modis = aggregate_monthly(cfg=cfg, repo_root=ROOT, sensor="modis", run_id="test",
        fires_canonical_df=prepared.fires_canonical, start_yyyymm=202003, end_yyyymm=202003,
        write_outputs=False).panel_sensor_monthly
    universe = pd.DataFrame([{"level":lvl.level, "unit_id":"U1", "unit_name":"Unit"}
                             for lvl in cfg.io.inputs.polygons])
    combined = combine_panels(cfg=cfg, repo_root=ROOT, run_id="test", unit_universe_df=universe,
        viirs_monthly_df=monthly, modis_monthly_df=modis, start_yyyymm=202003, end_yyyymm=202003,
        write_outputs=False).panel_monthly
    assert combined.viirs_det_nh.eq(0).all()
    assert combined.viirs_frp_mean_mw.eq(4).all()


def test_two_year_partitions_match_memory(monkeypatch, tmp_path):
    cfg, first = setup_case(monkeypatch, tmp_path, year=2019, date="2019-12-31", time="2359")
    _, second = setup_case(monkeypatch, tmp_path, year=2020, date="2020-01-01", time="0000")
    counts = pd.concat([first.fires_canonical, second.fires_canonical], ignore_index=True)
    frp = pd.concat([first.fires_frp_canonical, second.fires_frp_canonical], ignore_index=True)
    kwargs = dict(cfg=cfg, repo_root=tmp_path, sensor="viirs", run_id="test",
                  start_yyyymm=201912, end_yyyymm=202001, write_outputs=False)
    disk = aggregate_monthly(**kwargs).panel_sensor_monthly
    memory = aggregate_monthly(**kwargs, fires_canonical_df=counts, fires_frp_canonical_df=frp).panel_sensor_monthly
    pdt.assert_frame_equal(disk, memory)
    assert set(disk.yyyymm) == {201912, 202001}


def test_file_backed_governed_preparation_and_aggregation(tmp_path, monkeypatch):
    cfg = load_config(ROOT / "configs/example_project.yaml", validate_paths=False, repo_root=ROOT).config
    cfg.io.inputs.land_mask = None
    cfg.outputs.base_dir = "runs"
    cm = cfg.io.inputs.firms_points["viirs"].column_map
    points = gpd.GeoDataFrame({cm["latitude"]:[5., 5.], cm["longitude"]:[-1., -1.],
        cm["acq_date"]:["2020-03-15"]*2, cm["acq_time"]:["0130"]*2,
        cm["confidence"]:["low", "nominal"], cm["frp"]:[100., 4.], cm["type"]:[0, 0],
        cm.get("satellite", "SATELLITE"):["N", "N"], cm.get("daynight", "DAYNIGHT"):["D", "D"]},
        geometry=gpd.points_from_xy([-1., -1.], [5., 5.]), crs="EPSG:4326")
    source = tmp_path / "viirs_2020.geojson"
    points.to_file(source, driver="GeoJSON")
    polygon = Polygon([(-2, 4), (0, 4), (0, 6), (-2, 6)])
    for lvl in cfg.io.inputs.polygons:
        path = tmp_path / f"{lvl.level}.geojson"
        values = {lvl.unit_id_field:["U1"]}
        if lvl.unit_name_field:
            values[lvl.unit_name_field] = ["Unit"]
        gpd.GeoDataFrame(values, geometry=[polygon], crs="EPSG:4326").to_file(path, driver="GeoJSON")
        lvl.path = path.name
    prepared = prep.prepare_year(cfg=cfg, repo_root=tmp_path, sensor="viirs", year=2020,
        run_id="test", points_path=source, write_outputs=True, validate_schema=False)
    assert prepared.qa_summary["in_memory_inputs"] is False
    assert prepared.qa_summary["geography_file_identity"]
    result = aggregate_monthly(cfg=cfg, repo_root=tmp_path, sensor="viirs", run_id="test",
        start_yyyymm=202003, end_yyyymm=202003, write_outputs=True)
    assert result.panel_sensor_monthly.viirs_frp_mean_mw.eq(4).all()
    import importlib.util
    import json
    import sys
    import yaml
    config_file = tmp_path / "comparison_config.yaml"
    config_file.write_text(yaml.safe_dump(cfg.to_canonical_dict()))
    script = ROOT.parents[1] / "tools/compare_viirs_frp_streams.py"
    spec = importlib.util.spec_from_file_location("compare_viirs_frp_streams", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    comparison = tmp_path / "comparison"
    monkeypatch.setattr(sys, "argv", [str(script), "--firms-root", str(tmp_path), "--config", str(config_file),
        "--run-id", "test", "--start-year", "2020", "--end-year", "2020", "--output-dir", str(comparison),
        "--monthly-panel", str(result.panel_path)])
    module.main()
    audit = json.loads((comparison / "comparison_summary.json").read_text())
    assert audit["frp_records_not_in_count_nh"] == 1
    assert audit["new_eligible_unit_days"] == 1
    assert audit["fields"]["viirs_frp_mean_mw"]["became_available"] == 1
    assert not any(audit["count_persistence_check"]["mismatched_unit_months"].values())
    assert audit["rq3_active_fire_support"]["zero_count_with_frp"] == 1
    boundary = tmp_path / cfg.io.inputs.polygons[0].path
    boundary.write_text(boundary.read_text() + " ", encoding="utf-8")
    with pytest.raises(AggregateMonthlyError, match="geography input identity changed"):
        aggregate_monthly(cfg=cfg, repo_root=tmp_path, sensor="viirs", run_id="test",
            start_yyyymm=202003, end_yyyymm=202003, write_outputs=False)
