"""A reusable preparation must still describe the current source and outputs."""
from __future__ import annotations

from pathlib import Path
import shutil

import geopandas as gpd
import pytest
import yaml
from shapely.geometry import Point, box

from mv_firms_panels.cli.commands import CliError, cmd_aggregate, cmd_prepare_year
from mv_firms_panels.core.config import load_config
from mv_firms_panels.stages.aggregate_monthly import aggregate_monthly
from mv_firms_panels.stages.prepare_year import prepare_year
from mv_firms_panels.stages.preparation_evidence import (
    PreparationEvidenceError, validate_preparation_partition,
)

ROOT = Path(__file__).resolve().parents[1]


def _prepared(tmp_path: Path, sensor: str):
    cfg = load_config(ROOT / "configs/example_project.yaml", validate_paths=False, repo_root=ROOT).config
    cfg.io.inputs.land_mask = None
    cfg.outputs.base_dir = "runs"
    cfg.processing.time_range.start_yyyymm = 202401
    cfg.processing.time_range.end_yyyymm = 202412
    fin = cfg.io.inputs.firms_points[sensor]
    fin.file_glob = f"data/raw/{sensor}/*.shp"
    source = tmp_path / f"data/raw/{sensor}/{sensor.upper()}_2024.shp"
    source.parent.mkdir(parents=True)
    cm = fin.column_map
    values = {cm["latitude"]: [5.0], cm["longitude"]: [-1.0],
              cm["acq_date"]: ["2024-01-02"], cm["acq_time"]: ["0030"],
              cm["confidence"]: [50 if sensor == "modis" else "n"],
              cm["frp"]: [4.0], cm["type"]: [0],
              cm["satellite"]: ["Aqua" if sensor == "modis" else "N"],
              cm["daynight"]: ["N"]}
    gpd.GeoDataFrame(values, geometry=[Point(-1, 5)], crs="EPSG:4326").to_file(source)
    for polygon in cfg.io.inputs.polygons:
        polygon.path = f"geography/{polygon.level}.geojson"
        target = tmp_path / polygon.path
        target.parent.mkdir(exist_ok=True)
        gpd.GeoDataFrame({polygon.unit_id_field: ["U1"], polygon.unit_name_field: ["Unit 1"]},
                         geometry=[box(-2, 4, 0, 6)], crs="EPSG:4326").to_file(target, driver="GeoJSON")
    for schema_key in ("fires_canonical", "fires_frp_canonical"):
        target = tmp_path / f"schemas/{schema_key}.schema.json"
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(ROOT / cfg.outputs.schemas[schema_key], target)
        cfg.outputs.schemas[schema_key] = target.relative_to(tmp_path).as_posix()
    result = prepare_year(cfg=cfg, repo_root=tmp_path, sensor=sensor, year=2024,
                          run_id="source_identity", write_outputs=True)
    kwargs = dict(repo_root=tmp_path, cfg=cfg, run_dir=tmp_path / "runs/source_identity",
                  run_id="source_identity", sensor=sensor, year=2024,
                  count_path=result.fires_canonical_path,
                  frp_path=result.fires_frp_canonical_path, require_configured_source=True)
    return cfg, source, result, kwargs


@pytest.mark.parametrize("sensor", ["modis", "viirs"])
def test_unchanged_preparation_reuses_current_source(tmp_path, sensor):
    _, source, _, kwargs = _prepared(tmp_path, sensor)
    qa = validate_preparation_partition(**kwargs)
    assert qa["source_file"] == source.relative_to(tmp_path).as_posix()


@pytest.mark.parametrize("sensor", ["modis", "viirs"])
@pytest.mark.parametrize("suffix", [".shp", ".shx", ".dbf", ".prj", ".cpg"])
def test_any_changed_shapefile_component_rejects_reuse(tmp_path, sensor, suffix):
    _, source, _, kwargs = _prepared(tmp_path, sensor)
    component = source.with_suffix(suffix)
    component.write_bytes(component.read_bytes() + b"tamper")
    with pytest.raises(PreparationEvidenceError, match="source input identity changed"):
        validate_preparation_partition(**kwargs)


@pytest.mark.parametrize("sensor", ["modis", "viirs"])
def test_missing_sidecar_rejects_reuse(tmp_path, sensor):
    _, source, _, kwargs = _prepared(tmp_path, sensor)
    source.with_suffix(".cpg").unlink()
    with pytest.raises(PreparationEvidenceError):
        validate_preparation_partition(**kwargs)


@pytest.mark.parametrize("sensor", ["modis", "viirs"])
def test_added_annual_candidate_is_not_silently_reused(tmp_path, sensor):
    _, source, _, kwargs = _prepared(tmp_path, sensor)
    for component in source.parent.glob(source.stem + ".*"):
        shutil.copyfile(component, component.with_name("other_2024" + component.suffix))
    with pytest.raises(PreparationEvidenceError, match="Ambiguous|Multiple|multiple|ambiguous"):
        validate_preparation_partition(**kwargs)


@pytest.mark.parametrize("sensor", ["modis", "viirs"])
def test_geography_and_output_changes_invalidate_reuse(tmp_path, sensor):
    cfg, _, result, kwargs = _prepared(tmp_path, sensor)
    target = tmp_path / cfg.io.inputs.polygons[0].path
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(PreparationEvidenceError, match="geography input identity changed"):
        validate_preparation_partition(**kwargs)
    # Restore the exact bytes, then test a separate output mutation.
    target.write_bytes(target.read_bytes()[:-1])
    result.fires_canonical_path.write_bytes(result.fires_canonical_path.read_bytes() + b"\n")
    with pytest.raises(PreparationEvidenceError, match="path or hash mismatch"):
        validate_preparation_partition(**kwargs)


@pytest.mark.parametrize("sensor", ["modis", "viirs"])
def test_current_schema_identity_changes_reject_reuse(tmp_path, sensor):
    cfg, _, _, kwargs = _prepared(tmp_path, sensor)
    target = tmp_path / cfg.outputs.schemas["fires_canonical"]
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(PreparationEvidenceError, match="schema input identity changed"):
        validate_preparation_partition(**kwargs)


@pytest.mark.parametrize("sensor", ["modis", "viirs"])
def test_cli_preparation_skip_rejects_current_source_change(tmp_path, sensor):
    cfg, source, _, _ = _prepared(tmp_path, sensor)
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump(cfg.to_canonical_dict()), encoding="utf-8")
    kwargs = dict(repo_root=tmp_path, config_path=config, sensor=sensor, year=2024,
                  run_id="source_identity", skip_existing=True)
    assert cmd_prepare_year(**kwargs) == 0
    component = source.with_suffix(".dbf")
    component.write_bytes(component.read_bytes() + b"tamper")
    with pytest.raises(CliError, match="Preparation reuse rejected"):
        cmd_prepare_year(**kwargs)


@pytest.mark.parametrize("sensor", ["modis", "viirs"])
def test_aggregation_skip_checks_annual_source_chain(tmp_path, sensor):
    cfg, source, _, _ = _prepared(tmp_path, sensor)
    aggregate_monthly(cfg=cfg, repo_root=tmp_path, sensor=sensor, run_id="source_identity",
                      start_yyyymm=202401, end_yyyymm=202412, write_outputs=True)
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump(cfg.to_canonical_dict()), encoding="utf-8")
    kwargs = dict(repo_root=tmp_path, config_path=config, sensor=sensor,
                  run_id="source_identity", start_yyyymm=202401, end_yyyymm=202412,
                  skip_existing=True)
    assert cmd_aggregate(**kwargs) == 0
    component = source.with_suffix(".cpg")
    component.write_bytes(component.read_bytes() + b"tamper")
    with pytest.raises(CliError, match="Aggregation reuse rejected"):
        cmd_aggregate(**kwargs)


def test_native_in_memory_partition_is_computational_only(tmp_path):
    cfg, source, _, _ = _prepared(tmp_path, "modis")
    result = prepare_year(cfg=cfg, repo_root=tmp_path, sensor="modis", year=2024,
        run_id="memory", points_gdf=gpd.read_file(source),
        polygons_by_level={p.level:gpd.read_file(tmp_path / p.path) for p in cfg.io.inputs.polygons},
        write_outputs=True)
    kwargs = dict(repo_root=tmp_path, cfg=cfg, run_dir=tmp_path / "runs/memory",
                  run_id="memory", sensor="modis", year=2024,
                  count_path=result.fires_canonical_path)
    validate_preparation_partition(**kwargs, require_file_inputs=False)
    with pytest.raises(PreparationEvidenceError, match="file-backed"):
        validate_preparation_partition(**kwargs)


def test_native_governed_modis_aggregation_requires_all_requested_years(tmp_path):
    cfg, _, _, _ = _prepared(tmp_path, "modis")
    from mv_firms_panels.stages.aggregate_monthly import AggregateMonthlyError
    with pytest.raises(AggregateMonthlyError, match="Missing required MODIS annual partitions"):
        aggregate_monthly(cfg=cfg, repo_root=tmp_path, sensor="modis", run_id="source_identity",
            start_yyyymm=202301, end_yyyymm=202412, write_outputs=True)
