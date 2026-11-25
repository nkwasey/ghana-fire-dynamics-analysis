"""Projected analysis boundaries retain the serialized district hierarchy."""
import hashlib
import json

import geopandas as gpd
import pandas as pd
import pytest
import yaml
from pyproj import CRS as PyCRS
from shapely import union_all
from shapely.geometry import Polygon, box

from geo_data_prep.pipeline import PrepError, run, validate
from geo_test_helpers import CRS
from test_pipeline import config_for, rewrite_districts


def configured(root, analysis):
    path = config_for(root, outputs={"root": "out", "splits": False, "plots": False})
    cfg = yaml.safe_load(path.read_text())
    cfg["crs"]["analysis"] = analysis
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


def test_projected_analysis_handoff_preserves_identity_and_district_unions(synthetic_inputs):
    root, district_source, _ = synthetic_inputs
    before = hashlib.sha256(district_source.read_bytes()).hexdigest()
    path = configured(root, "EPSG:32631")
    out = run(path, "projected")
    native_d = gpd.read_file(out / "boundaries/districts_within_acz.shp").set_index("dist_id").sort_index()
    native_z = gpd.read_file(out / "boundaries/acz.shp")
    projected_d = gpd.read_file(out / "analysis_boundaries/districts_within_acz.shp").set_index("dist_id").sort_index()
    projected_z = gpd.read_file(out / "analysis_boundaries/acz.shp").set_index("zone_id")
    assert PyCRS(native_d.crs).to_epsg() == PyCRS(native_z.crs).to_epsg() == 32630
    assert PyCRS(projected_d.crs).to_epsg() == PyCRS(projected_z.crs).to_epsg() == 32631
    assert set(native_d.index) == set(projected_d.index)
    for column in ["dist_name", "zone_id", "zone_name", "zone_code", "ovl_share", "cov_share"]:
        assert list(native_d[column]) == list(projected_d[column])
    transformed = native_d.to_crs(32631)
    assert all(a.normalize().equals_exact(b.normalize(), 0) for a, b in zip(transformed.geometry, projected_d.geometry))
    for zone_id, zone in projected_z.iterrows():
        members = projected_d[projected_d.zone_id == zone_id].geometry
        assert zone.geometry.equals(union_all(members.values))
        assert all(zone.geometry.covers(g) for g in members)
    assert hashlib.sha256(district_source.read_bytes()).hexdigest() == before
    for name in ["districts_within_acz", "acz"]:
        for ext in [".shp", ".shx", ".dbf", ".prj", ".cpg", ".geojson"]:
            assert (out / "analysis_boundaries" / (name + ext)).is_file()
    hierarchy = pd.read_csv(out / "qa/analysis_hierarchy.csv")
    assert hierarchy.exact_union_equal.all() and hierarchy.all_districts_covered.all()
    contract = json.loads((out / "contract/stage1_contract_manifest.json").read_text())
    handoff = contract["analysis_handoff"]
    assert handoff["crs"] == "EPSG:32631"
    assert handoff["districts_relative_path"] == "analysis_boundaries/districts_within_acz.shp"
    for field, name in [("district_bundle", "districts_within_acz.shp"), ("zone_bundle", "acz.shp")]:
        actual = hashlib.sha256((out / "analysis_boundaries" / name).read_bytes()).hexdigest()
        assert handoff[field]["parts"][name] == actual
    manifest = json.loads((out / "outputs_manifest.json").read_text())
    assert "analysis_boundaries/acz.shp" in manifest["files"]
    assert "qa/analysis_hierarchy.csv" in manifest["files"]


def test_optional_analysis_handoff_does_not_change_native_analytics(synthetic_inputs):
    root, _, _ = synthetic_inputs
    config = config_for(root, outputs={"root": "out", "splits": False, "plots": False})
    without = run(config, "without")
    assert not (without / "analysis_boundaries").exists()
    assert json.loads((without / "contract/stage1_contract_manifest.json").read_text())["analysis_handoff"] is None
    cfg = yaml.safe_load(config.read_text()); cfg["crs"]["analysis"] = "EPSG:32631"
    config.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    with_analysis = run(config, "with_analysis")
    for relative in ["unit_universe.csv", "crosswalks/district_zone_crosswalk.csv", "qa/reference_coverage.csv",
                     "boundaries/districts_within_acz.shp", "boundaries/acz.shp"]:
        assert (without / relative).read_bytes() == (with_analysis / relative).read_bytes()


@pytest.mark.parametrize("value", ["EPSG:4326", "EPSG:2263", "NOT_A_CRS", None, True])
def test_analysis_crs_requires_valid_metre_projected_coordinates(synthetic_inputs, value):
    root, _, _ = synthetic_inputs
    config = configured(root, value)
    with pytest.raises(PrepError, match="crs.analysis|CRS"):
        validate(config)
    assert not (root / "out").exists()


def test_districts_that_overlap_only_after_analysis_reprojection_are_rejected(synthetic_inputs):
    root, _, _ = synthetic_inputs
    west = box(500000, 1000000, 504000, 1010000)
    east = Polygon([(504000, 1000000), (508000, 1000000), (508000, 1010000),
                    (504000, 1010000), (504000, 1005000), (504000, 1000000)])
    # Only the eastern district stores a midpoint on the shared edge.
    assert west.touches(east)
    analysis = gpd.GeoSeries([west, east], crs=CRS).to_crs(32631)
    assert analysis.iloc[0].intersection(analysis.iloc[1]).area > 1
    rewrite_districts(root, {"district_id": ["d1", "d2"], "district_name": ["West", "East"]},
                      [west, east])
    config = configured(root, "EPSG:32631")
    for operation, args in [(validate, (config,)), (run, (config, "projection-overlap"))]:
        with pytest.raises(PrepError, match="Analysis districts have positive-area overlaps"):
            operation(*args)
    assert not (root / "out").exists()


def test_projected_handoff_failure_never_publishes_partial_run(synthetic_inputs, monkeypatch):
    from geo_data_prep import pipeline
    root, _, _ = synthetic_inputs
    original = pipeline.export_layer
    calls = []
    def fail_analysis_export(frame, path):
        if path.parent.name == "analysis_boundaries":
            calls.append(path)
            raise RuntimeError("simulated analysis export failure")
        return original(frame, path)
    monkeypatch.setattr(pipeline, "export_layer", fail_analysis_export)
    with pytest.raises(RuntimeError, match="analysis export failure"):
        run(configured(root, "EPSG:32631"), "failed_analysis")
    assert calls
    assert not (root / "out/failed_analysis").exists()
    assert not list((root / "out").glob(".geo-prep-*"))
