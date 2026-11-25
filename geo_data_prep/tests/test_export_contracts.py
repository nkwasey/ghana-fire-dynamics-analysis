"""Portable output identifiers and standards-compliant geographic exports."""
from __future__ import annotations

import json
import math

import geopandas as gpd
import pytest
from shapely import get_coordinates
from shapely.geometry import box

from geo_data_prep.pipeline import PrepError, export_layer, run, validate
from geo_test_helpers import CRS, write_layer
from test_pipeline import config_for


@pytest.mark.parametrize("run_id", ["CON", "nul", "PrN", "AUX", "COM1", "lpt9", "COM1.csv", "NUL.backup", "trial.", "trial..", None, 123])
def test_invalid_or_nonportable_run_names_fail_before_input_processing(tmp_path, run_id):
    # A missing config proves the identifier is rejected before any input read.
    with pytest.raises(PrepError, match="[Rr]un ID"):
        run(tmp_path / "missing.yaml", run_id)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("run_id", ["local_test", "ACZ-2026", "trial.v1", "console", "com10", "auxiliary"])
def test_portable_run_names_produce_complete_runs(synthetic_inputs, run_id):
    root, _, _ = synthetic_inputs
    config = config_for(root, outputs={"root": "out", "plots": False, "splits": False})
    output = run(config, run_id)
    assert output.name == run_id
    assert (output / "outputs_manifest.json").is_file()
    assert not list(output.parent.glob(".geo-prep-*"))


def nontransformable_config(root):
    # Native coordinates are finite/valid, but outside the UTM inverse domain.
    geometry = box(100000000, 100000000, 100004000, 100001000)
    for name in ("districts.gpkg", "zones.gpkg"):
        (root / name).unlink()
    write_layer(root / "districts.gpkg", {"district_id": ["d1"], "district_name": ["One"]}, [geometry])
    write_layer(root / "zones.gpkg", {"zone_id": ["a"], "zone_name": ["Zone A"], "zone_code": ["A"]}, [geometry])
    return config_for(root, outputs={"root": "out", "plots": False, "splits": False})


@pytest.mark.parametrize("operation", ["validate", "run"])
def test_nonfinite_geographic_transformation_is_rejected_without_outputs(synthetic_inputs, operation):
    root, _, _ = synthetic_inputs
    config = nontransformable_config(root)
    with pytest.raises(PrepError, match="EPSG:4326"):
        validate(config) if operation == "validate" else run(config, "invalid-transform")
    assert not (root / "out").exists()


def test_every_geojson_export_rejects_nonfinite_coordinates(tmp_path):
    frame = gpd.GeoDataFrame({"dist_id": ["d1"]}, geometry=[box(100000000, 100000000, 100004000, 100001000)], crs=CRS)
    path = tmp_path / "districts.shp"
    with pytest.raises(PrepError, match="EPSG:4326"):
        export_layer(frame, path)
    assert not path.with_suffix(".geojson").exists()


def test_geojson_outputs_are_strict_json_and_valid_wgs84(synthetic_inputs):
    root, _, _ = synthetic_inputs
    config = config_for(root, outputs={"root": "out", "plots": False, "splits": False})
    output = run(config, "strict-json")

    def reject_constant(value):
        raise AssertionError(f"Nonstandard JSON numeric constant: {value}")

    paths = sorted((output / "boundaries").glob("*.geojson"))
    assert len(paths) == 2
    for path in paths:
        parsed = json.loads(path.read_text(), parse_constant=reject_constant)
        assert parsed["type"] == "FeatureCollection" and parsed["features"]
        frame = gpd.read_file(path)
        assert frame.crs.to_epsg() == 4326
        assert frame.geometry.is_valid.all() and not frame.geometry.is_empty.any()
        for x, y in get_coordinates(frame.geometry.values):
            assert math.isfinite(x) and math.isfinite(y)
            assert -180 <= x <= 180 and -90 <= y <= 90
