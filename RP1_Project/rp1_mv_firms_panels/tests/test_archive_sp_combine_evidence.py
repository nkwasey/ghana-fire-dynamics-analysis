"""Both satellite source lineages remain bound through the AF combine stage."""
import json
from pathlib import Path
import shutil

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from mv_firms_panels.core.config import load_config
from mv_firms_panels.stages.aggregate_monthly import AggregateMonthlyError, aggregate_monthly
from mv_firms_panels.stages.combine_panels import combine_panels
from mv_firms_panels.stages.prepare_year import prepare_year
from test_archive_sp_input_profile import records, staged

ROOT = Path(__file__).resolve().parents[1]


def _case(tmp_path):
    cfg = load_config(ROOT / "configs/example_project.yaml", validate_paths=False).config
    cfg.io.inputs.land_mask = None
    cfg.processing.time_range.start_yyyymm = 202401
    cfg.processing.time_range.end_yyyymm = 202412
    shutil.copytree(ROOT / "configs/schemas", tmp_path / "configs/schemas")
    families = []
    sources = {}
    for sensor in ("modis", "viirs"):
        points = records(sensor)
        points["fire_type"] = "0"
        source, inp, authority = staged(tmp_path, points, sensor)
        families.extend(json.loads(authority.read_text())["families"])
        inp.column_map = cfg.io.inputs.firms_points[sensor].column_map
        cfg.io.inputs.firms_points[sensor] = inp
        sources[sensor] = source
    manifest = json.loads(authority.read_text())
    manifest["families"] = families
    authority.write_text(json.dumps(manifest))
    for polygon in cfg.io.inputs.polygons:
        polygon.path = f"geography/{polygon.level}.geojson"
        target = tmp_path / polygon.path
        target.parent.mkdir(exist_ok=True)
        unit_id = "Z1" if polygon.level == "acz" else "D1"
        gpd.GeoDataFrame({polygon.unit_id_field:[unit_id], polygon.unit_name_field:[unit_id]},
            geometry=[box(-3, 7, 0, 10)], crs=4326).to_file(target, driver="GeoJSON")
    for sensor in ("modis", "viirs"):
        prepare_year(cfg=cfg, repo_root=tmp_path, sensor=sensor, year=2024, run_id="sp")
        aggregate_monthly(cfg=cfg, repo_root=tmp_path, sensor=sensor, run_id="sp",
            start_yyyymm=202401, end_yyyymm=202412)
    universe = pd.DataFrame({"level":["acz","district"], "unit_id":["Z1","D1"],
        "unit_code":["Z1",pd.NA], "unit_name":["Zone 1","District 1"],
        "parent_level":[pd.NA,"acz"], "parent_id":[pd.NA,"Z1"],
        "parent_code":[pd.NA,"Z1"], "parent_name":[pd.NA,"Zone 1"]})
    kwargs = dict(cfg=cfg, repo_root=tmp_path, run_id="sp", unit_universe_df=universe,
        start_yyyymm=202401, end_yyyymm=202412)
    return kwargs, sources


def test_combine_binds_both_sources_and_admission_companions(tmp_path):
    kwargs, _ = _case(tmp_path)
    result = combine_panels(**kwargs)
    manifest = json.loads(result.manifest_path.read_text())
    method = manifest["active_fire_method"]
    assert method["input_profiles"] == {sensor:"ghana_firms_archive_sp_v1" for sensor in ("modis","viirs")}
    paths = {item["path"] for item in method["source_preparation_evidence"]}
    assert any("prepare_year_modis_2024_manifest" in p for p in paths)
    assert any("prepare_year_viirs_2024_manifest" in p for p in paths)
    assert any("source_observation_trace_modis" in p for p in paths)
    assert any("source_observation_trace_viirs" in p for p in paths)
    assert any(p.endswith("archive_sp_intake.json") for p in paths)
    assert any(p.endswith("annual-export.json") for p in paths)
    assert any(p.endswith("provenance.json") for p in paths)
    assert any(p.endswith("field_dictionary.json") for p in paths)
    assert any("fires_canonical.schema.json" in p for p in paths)


@pytest.mark.parametrize("sensor", ["modis", "viirs"])
def test_direct_combine_rejects_changed_source_for_either_sensor(tmp_path, sensor):
    kwargs, sources = _case(tmp_path)
    dbf = sources[sensor].with_suffix(".dbf")
    dbf.write_bytes(dbf.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="preparation evidence"):
        combine_panels(**kwargs, write_outputs=False)


@pytest.mark.parametrize("role", ["admission", "provenance", "trace", "schema"])
def test_direct_combine_rejects_changed_source_authorities(tmp_path, role):
    kwargs, _ = _case(tmp_path)
    if role == "admission":
        target = tmp_path / "data/raw/source_provenance/archive_sp_intake.json"
    elif role == "provenance":
        target = tmp_path / "data/raw/source_provenance/provenance.json"
    elif role == "trace":
        target = tmp_path / "out/runs/sp/qa/source_observation_trace_modis_2024.csv"
    else:
        target = tmp_path / "configs/schemas/fires_canonical.schema.json"
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="preparation evidence"):
        combine_panels(**kwargs, write_outputs=False)


def test_archive_modis_missing_annual_partition_cannot_be_zero_filled(tmp_path):
    kwargs, _ = _case(tmp_path)
    with pytest.raises(AggregateMonthlyError, match="Missing required MODIS annual partitions: \\[2023\\]"):
        aggregate_monthly(cfg=kwargs["cfg"], repo_root=tmp_path, sensor="modis", run_id="sp",
            start_yyyymm=202301, end_yyyymm=202412, write_outputs=False)


def test_combine_cannot_extend_a_pilot_to_unprepared_years(tmp_path):
    kwargs, _ = _case(tmp_path)
    kwargs["start_yyyymm"] = 202301
    with pytest.raises(ValueError, match="MODIS aggregation coverage"):
        combine_panels(**kwargs, write_outputs=False)


@pytest.mark.parametrize("sensor", ["modis", "viirs"])
@pytest.mark.parametrize("input_mode", ["in_memory", "nonannual_file"])
def test_archive_aggregation_cannot_write_unverified_monthly_artifact(tmp_path, sensor, input_mode):
    kwargs, _ = _case(tmp_path)
    canonical = tmp_path / f"out/runs/sp/fires_canonical/{sensor}/fires_canonical_{sensor}_2024.csv"
    input_kwargs = {}
    if input_mode == "in_memory":
        input_kwargs["fires_canonical_df"] = pd.read_csv(canonical)
        expected = "In-memory Archive streams"
    else:
        other = tmp_path / "arbitrary.csv"
        shutil.copyfile(canonical, other)
        input_kwargs["fires_canonical_paths"] = [other]
        expected = "governed annual canonical partitions"
    with pytest.raises(AggregateMonthlyError, match=expected):
        aggregate_monthly(cfg=kwargs["cfg"], repo_root=tmp_path, sensor=sensor,
            run_id="unverified", start_yyyymm=202401, end_yyyymm=202412,
            write_outputs=True, **input_kwargs)
    assert not (tmp_path / "out/runs/unverified").exists()
