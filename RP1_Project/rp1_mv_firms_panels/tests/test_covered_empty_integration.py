"""Covered absence survives preparation, monthly balancing and merger intake."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import sys

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Polygon

from mv_firms_panels.core.config import load_config
from mv_firms_panels.stages.aggregate_monthly import AggregateMonthlyError, aggregate_monthly
from mv_firms_panels.stages.combine_panels import combine_panels
from mv_firms_panels.stages.prepare_year import prepare_year


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def covered_case(tmp_path):
    cfg = load_config(ROOT / "configs/example_project.yaml", validate_paths=False, repo_root=ROOT).config
    cfg.io.inputs.land_mask = None
    cfg.outputs.base_dir = "runs"
    cfg.outputs.prepare_year_qa_exports.enabled = False
    shutil.copytree(ROOT / "configs/schemas", tmp_path / "configs/schemas")
    universe = []
    polygon = Polygon([(-2, 4), (0, 4), (0, 6), (-2, 6)])
    for level in cfg.io.inputs.polygons:
        values = {level.unit_id_field: ["U1"]}
        if level.unit_name_field:
            values[level.unit_name_field] = ["Unit 1"]
        path = tmp_path / f"{level.level}.geojson"
        gpd.GeoDataFrame(values, geometry=[polygon], crs="EPSG:4326").to_file(path, driver="GeoJSON")
        level.path = path.name
        universe.append({"level": level.level, "unit_id": "U1", "unit_name": "Unit 1",
                         "unit_code": "U1", "parent_level": None, "parent_id": None,
                         "parent_code": None, "parent_name": None})
    # File-backed observations outside every target unit leave valid, empty
    # annual canonical outputs rather than a missing partition.
    for sensor in ("modis", "viirs"):
        cm = cfg.io.inputs.firms_points[sensor].column_map
        points = gpd.GeoDataFrame({
            cm["latitude"]: [10.], cm["longitude"]: [10.],
            cm["acq_date"]: ["2020-03-15"], cm["acq_time"]: ["0130"],
            cm["confidence"]: ["nominal" if sensor == "viirs" else 50],
            cm["frp"]: [4.], cm["type"]: [0],
            cm.get("satellite", "SATELLITE"): ["N" if sensor == "viirs" else "T"],
            cm.get("daynight", "DAYNIGHT"): ["D"],
        }, geometry=gpd.points_from_xy([10.], [10.]), crs="EPSG:4326")
        source = tmp_path / f"{sensor}_2020.geojson"
        points.to_file(source, driver="GeoJSON")
        prepared = prepare_year(cfg=cfg, repo_root=tmp_path, sensor=sensor, year=2020,
                                run_id="empty", points_path=source, write_outputs=True)
        assert prepared.fires_canonical.empty
        if sensor == "viirs":
            assert prepared.fires_frp_canonical.empty
    return cfg, tmp_path, pd.DataFrame(universe)


def _aggregate(cfg, root, sensor, **kwargs):
    options = dict(cfg=cfg, repo_root=root, sensor=sensor, run_id="empty",
                   start_yyyymm=202003, end_yyyymm=202003, write_outputs=True)
    options.update(kwargs)
    return aggregate_monthly(**options)


def test_file_backed_covered_empty_balances_exports_and_merger_intake(covered_case):
    cfg, root, universe = covered_case
    monthly = {}
    for sensor in ("modis", "viirs"):
        result = _aggregate(cfg, root, sensor)
        monthly[sensor] = pd.read_csv(result.panel_path)
        assert result.panel_sensor_monthly.empty
        assert f"{sensor}_days_active_nh" in result.panel_sensor_monthly
        assert f"{sensor}_frp_mean_mw" in pd.read_csv(result.panel_path)
        assert result.qa_summary["steps"]["covered_empty"]["status"] == "VERIFIED_COVERED_EMPTY"
    combined = combine_panels(cfg=cfg, repo_root=root, run_id="empty", unit_universe_df=universe,
                              start_yyyymm=202003, end_yyyymm=202003, write_outputs=True)
    assert len(combined.panel_monthly) == len(universe)
    for sensor in ("modis", "viirs"):
        assert combined.panel_monthly[f"{sensor}_det_nh"].eq(0).all()
        assert combined.panel_monthly[f"{sensor}_frp_sum_daily_max_mw"].eq(0).all()
        assert combined.panel_monthly[f"{sensor}_frp_mean_mw"].isna().all()
    spec = importlib.util.spec_from_file_location("covered_empty_merger", ROOT.parent / "merge_af_ba_panels.py")
    merger = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = merger
    spec.loader.exec_module(merger)
    exports = sorted((root / "runs/empty/rp1_af_exports").rglob("*.csv"))
    assert exports
    for path in exports:
        sensor = path.parent.name
        frame = merger.validate_af_content(pd.read_csv(path), sensor, str(path))
        for suffix in ("det_all", "det_nh", "days_active_nh", "streak_max_nh", "frp_active_days"):
            assert frame[f"{sensor}_{suffix}"].eq(0).all()
        assert frame[f"{sensor}_frp_mean_mw"].isna().all()
        assert frame[f"{sensor}_frp_p95_daily_max_mw"].isna().all()
        assert frame[f"{sensor}_pct_high_conf"].isna().all()
    # The balanced panel may include a structurally unsupported month while
    # covered absence remains zero inside the declared VIIRS interval.
    cfg.processing.sensor_coverage["viirs"].start_yyyymm = 202003
    balanced = combine_panels(cfg=cfg, repo_root=root, run_id="empty",
        unit_universe_df=universe, viirs_monthly_df=monthly["viirs"], modis_monthly_df=monthly["modis"],
        start_yyyymm=202002, end_yyyymm=202003, write_outputs=False).panel_monthly
    assert balanced.loc[balanced.yyyymm.eq(202002), "viirs_det_nh"].isna().all()
    assert balanced.loc[balanced.yyyymm.eq(202003), "viirs_det_nh"].eq(0).all()


@pytest.mark.parametrize("sensor", ["modis", "viirs"])
def test_empty_annual_absence_requires_receipt_coverage_and_complete_years(covered_case, sensor):
    cfg, root, _ = covered_case
    with pytest.raises(AggregateMonthlyError, match="Missing required|missing required"):
        _aggregate(cfg, root, sensor, end_yyyymm=202101)
    cfg.processing.sensor_coverage[sensor].start_yyyymm = 202004
    with pytest.raises(AggregateMonthlyError, match="declared sensor coverage|configuration mismatch"):
        _aggregate(cfg, root, sensor, write_outputs=False)


@pytest.mark.parametrize("sensor", ["modis", "viirs"])
def test_empty_annual_missing_receipt_does_not_become_zero(covered_case, sensor):
    cfg, root, _ = covered_case
    (root / f"runs/empty/qa/prepare_year_{sensor}_2020_manifest.json").unlink()
    with pytest.raises(AggregateMonthlyError, match="preparation evidence"):
        _aggregate(cfg, root, sensor, write_outputs=False)


def test_empty_viirs_requires_paired_empty_frp_evidence(covered_case):
    cfg, root, _ = covered_case
    (root / "runs/empty/fires_frp_canonical/viirs/fires_frp_canonical_viirs_2020.csv").unlink()
    with pytest.raises(AggregateMonthlyError, match="partition years"):
        _aggregate(cfg, root, "viirs")


@pytest.mark.parametrize("sensor", ["modis", "viirs"])
def test_in_memory_empty_calls_keep_existing_rejection(covered_case, sensor):
    cfg, root, _ = covered_case
    empty = pd.read_csv(root / f"runs/empty/fires_canonical/{sensor}/fires_canonical_{sensor}_2020.csv")
    with pytest.raises(AggregateMonthlyError, match="empty"):
        _aggregate(cfg, root, sensor, fires_canonical_df=empty,
                   fires_frp_canonical_df=empty if sensor == "viirs" else None, write_outputs=False)
