"""A validation-accepted empty annual ZIP remains covered zero through merger."""
from pathlib import Path
import json
import shutil
import sys

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from c3_fixture import write_delivery
from test_archive_sp_zip_direct import archive_case, intake
from mv_firms_panels.core.config import load_config
from mv_firms_panels.stages.prepare_year import prepare_year
from mv_firms_panels.stages.aggregate_monthly import AggregateMonthlyError, aggregate_monthly
from mv_firms_panels.stages.combine_panels import combine_panels
from RP1_Project import merge_af_ba_panels as merger
from RP1_Project.rp1_ba_consolidator import core
from rp1_ba_contracts import c3


def _prepare_empty_archive_case(tmp_path, *, accepted_window=None):
    annual, acceptance, study, _ = archive_case(tmp_path / "archive", empty=True)
    if accepted_window is not None:
        study.update(start_yyyymm=accepted_window[0], end_yyyymm=accepted_window[1])
        receipt = json.loads(acceptance.read_text(encoding="utf-8"))
        receipt["study"] = study
        acceptance.write_text(json.dumps(receipt), encoding="utf-8")
    firms = tmp_path / "RP1_Project/rp1_mv_firms_panels"
    firms.mkdir(parents=True)
    intake.stage_archive(annual, firms / "consumer", study, acceptance)
    cfg = load_config(ROOT / "RP1_Project/rp1_mv_firms_panels/configs/example_project.yaml",
                      validate_paths=False).config
    cfg.io.inputs.land_mask = None
    cfg.outputs.prepare_year_qa_exports.enabled = False
    cfg.processing.time_range.start_yyyymm = 202401
    cfg.processing.time_range.end_yyyymm = 202412
    shutil.copytree(ROOT / "RP1_Project/rp1_mv_firms_panels/configs/schemas", firms / "configs/schemas")
    source, universe_path = write_delivery(tmp_path / "ba_input")
    universe = pd.read_csv(universe_path, dtype={"unit_id": str, "parent_id": str})
    for level in cfg.io.inputs.polygons:
        units = universe.loc[universe.level.eq(level.level)]
        values = {level.unit_id_field: units.unit_id.tolist(),
                  level.unit_name_field: units.unit_name.tolist()}
        path = firms / f"geography/{level.level}.geojson"
        path.parent.mkdir(exist_ok=True)
        gpd.GeoDataFrame(values, geometry=[box(-3, 7, 0, 10)] * len(units), crs=4326).to_file(path, driver="GeoJSON")
        level.path = path.relative_to(firms).as_posix()
    for sensor in ("modis", "viirs"):
        inp = cfg.io.inputs.firms_points[sensor]
        inp.input_profile = intake.PROFILE
        inp.file_glob = f"consumer/data/raw/{sensor}/*.shp"
        inp.admission_bundle_root = "consumer"
        inp.admission_manifest = intake.AUTHORITY
    for sensor in ("modis", "viirs"):
        prepared = prepare_year(cfg=cfg, repo_root=firms, sensor=sensor, year=2024, run_id="empty")
        assert prepared.fires_canonical.empty
        assert prepared.qa_summary["input_profile_evidence"]["study"] == study
    return firms, cfg, universe, source, universe_path, study


def test_verified_empty_zip_preparation_balancing_exports_and_actual_c3_merge(tmp_path):
    firms, cfg, universe, source, universe_path, study = _prepare_empty_archive_case(tmp_path)
    for sensor in ("modis", "viirs"):
        monthly = aggregate_monthly(cfg=cfg, repo_root=firms, sensor=sensor, run_id="empty",
                                    start_yyyymm=202401, end_yyyymm=202412)
        assert monthly.panel_sensor_monthly.empty
        assert monthly.qa_summary["steps"]["covered_empty"]["validated_annual_years"] == [2024]
    combined = combine_panels(cfg=cfg, repo_root=firms, run_id="empty", unit_universe_df=universe,
                              start_yyyymm=202401, end_yyyymm=202412)
    for sensor in ("modis", "viirs"):
        assert combined.panel_monthly[f"{sensor}_det_nh"].eq(0).all()
        assert combined.panel_monthly[f"{sensor}_frp_mean_mw"].isna().all()
    bundle = tmp_path / "ba_bundle"
    core.consolidate(core.ConsolidationOptions(source, bundle, start_year=2024,
                     unit_universe=universe_path, boundary_label="empty_af_fixture"))
    config = tmp_path / "merge.json"
    config.write_text(json.dumps({"version": 2, "default_profile": "c3",
        "profiles": {"c3": dict(c3.PROFILE, bundle_handoff=str(bundle / "handoff.json"))},
        "paths": {"unit_universe": str(universe_path),
                  "af_root": str(firms / "out/runs/empty/rp1_af_exports"), "output_root": str(tmp_path / "merged")},
        "study": {**study, "expected_units": {"acz": 5, "district": 5}}}), encoding="utf-8")
    args = merger.build_arg_parser().parse_args(["--repo-root", str(tmp_path), "--config", str(config)])
    try:
        paths = merger.build_paths_config(args)
        result = merger.run(paths, "covered_empty")
        for level in ("acz", "district"):
            panel = pd.read_csv(result[f"fire_panel_{level}"])
            assert len(panel) == 5 * 12
            for sensor in ("modis", "viirs"):
                for suffix in ("det_nh", "days_active_nh", "streak_max_nh", "frp_active_days", "frp_sum_daily_max_mw"):
                    assert panel[f"{sensor}_{suffix}"].eq(0).all()
                assert panel[f"{sensor}_frp_mean_mw"].isna().all()
                assert panel[f"{sensor}_pct_high_conf"].isna().all()
            assert panel["modis_ba_km2_ba2001"].eq(1).all()
    finally:
        merger.configure_study({})
    # A valid empty 2024 partition never proves coverage for unprepared 2023.
    with pytest.raises(AggregateMonthlyError, match="Missing required MODIS annual partitions"):
        aggregate_monthly(cfg=cfg, repo_root=firms, sensor="modis", run_id="empty",
                          start_yyyymm=202301, end_yyyymm=202412, write_outputs=False)


def test_annual_empty_file_does_not_expand_the_accepted_study(tmp_path):
    firms, cfg, _, _, _, _ = _prepare_empty_archive_case(tmp_path, accepted_window=(202406, 202406))
    for sensor in ("modis", "viirs"):
        # The annual file and every required year are present, but January was
        # not part of the verified June study accepted for this run.
        with pytest.raises(AggregateMonthlyError, match="Archive acceptance does not cover"):
            aggregate_monthly(cfg=cfg, repo_root=firms, sensor=sensor, run_id="empty",
                              start_yyyymm=202401, end_yyyymm=202412, write_outputs=False)
