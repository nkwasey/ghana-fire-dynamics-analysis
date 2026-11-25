"""Scientific and file-interface checks using analytically known polygons."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import geopandas as gpd
import pandas as pd
import pytest
import yaml
from shapely.geometry import Polygon
from shapely.ops import unary_union

from geo_data_prep.pipeline import PrepError, run, validate
from geo_test_helpers import CRS, polygon, write_layer

UNIVERSE_COLUMNS = [
    "unit_type", "level", "unit_id", "unit_code", "unit_name",
    "parent_level", "parent_id", "parent_code", "parent_name", "area_sqkm",
]
CROSSWALK_COLUMNS = {
    "district_id", "zone_id", "zone_code", "zone_name",
    "original_district_area_sq_km", "dominant_overlap_area_sq_km",
    "dominant_overlap_share", "assignment_method", "working_crs",
}


def config_for(root: Path, **overrides):
    cfg = {
        "project_root": ".",
        "inputs": {
            "districts": {"path": "districts.gpkg", "id_field": "district_id", "name_field": "district_name"},
            "zones": {"path": "zones.gpkg", "id_field": "zone_id", "name_field": "zone_name", "code_field": "zone_code"},
        },
        "crs": {"working": CRS, "area": CRS, "output": CRS},
        "assignment": {"tie_tolerance": 1e-12, "warning_share": 0.5, "warning_margin": 0.05},
        "qa": {"area_tolerance_m2": 1e-4},
        "outputs": {"root": "out", "splits": True, "plots": False},
    }
    cfg.update(overrides)
    p = root / "config.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return p


def table(out: Path):
    return pd.read_csv(out / "crosswalks/district_to_acz_max_overlap.csv", dtype={"district_id": str})


def digest(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rewrite_districts(root, attrs, geom):
    (root / "districts.gpkg").unlink()
    write_layer(root / "districts.gpkg", attrs, geom)


def rewrite_zones(root, attrs, geom):
    (root / "zones.gpkg").unlink()
    write_layer(root / "zones.gpkg", attrs, geom)


def test_whole_district_assignment_dissolve_and_consumer_contract(synthetic_inputs):
    root, district_path, zone_path = synthetic_inputs
    before = {p.name: digest(p) for p in [district_path, zone_path]}
    out = run(config_for(root), "sample")
    assignments = table(out).set_index("district_id")
    assert assignments.loc["d1", "zone_id"] == "a"
    assert assignments.loc["d1", "dominant_overlap_share"] == pytest.approx(0.75)
    assert assignments.loc["d1", "original_district_area_sq_km"] == pytest.approx(4.0)
    assert assignments.loc["d1", "dominant_overlap_area_sq_km"] == pytest.approx(3.0)
    assert assignments.loc["d2", "zone_id"] == "b"
    assert CROSSWALK_COLUMNS <= set(assignments.reset_index().columns)
    source = gpd.read_file(district_path).set_index("district_id")
    districts = gpd.read_file(out / "boundaries/districts_within_acz.shp").set_index("dist_id")
    zones = gpd.read_file(out / "boundaries/acz.shp").set_index("zone_id")
    assert source.crs == districts.crs
    assert {"dist_name", "zone_id", "zone_name", "zone_code", "ovl_share"} <= set(districts.columns)
    for district_id in source.index:
        assert source.loc[district_id].geometry.equals(districts.loc[district_id].geometry)
    assert districts.loc["d1", "ovl_share"] == pytest.approx(.75)
    for zone_id, zone in zones.iterrows():
        members = districts.loc[districts.zone_id == zone_id].geometry
        assert zone.geometry.equals(unary_union(members))
        assert all(zone.geometry.covers(g) for g in members)
    universe = pd.read_csv(out / "unit_universe.csv", keep_default_na=False)
    assert list(universe.columns) == UNIVERSE_COLUMNS
    assert len(universe) == 4
    assert set(universe.loc[universe.unit_type == "district", "parent_id"]) == {"a", "b"}
    assert universe.unit_id.is_unique
    provenance = out / "crosswalks/district_to_acz_max_overlap.provenance.json"
    assert provenance.exists()
    assert json.loads(provenance.read_text())
    for p in [district_path, zone_path]:
        assert digest(p) == before[p.name]
    for zone_id in ["a", "b"]:
        split = gpd.read_file(out / f"splits/zones_split/acz__zone_{zone_id}.shp")
        assert split.geometry.iloc[0].equals(zones.loc[zone_id].geometry)
        split_d = gpd.read_file(out / f"splits/zone_districts/districts_within_acz__zone_{zone_id}.shp")
        assert set(split_d.dist_id) == set(districts.loc[districts.zone_id == zone_id].index)


def test_tie_is_deterministic_under_zone_row_order(synthetic_inputs):
    root, _, _ = synthetic_inputs
    rewrite_districts(root, {"district_id": ["d1"], "district_name": ["One"]}, [polygon(0, 0, 4000, 1000)])
    attrs = {"zone_id": ["b", "a"], "zone_name": ["Zone B", "Zone A"], "zone_code": ["B", "A"]}
    rewrite_zones(root, attrs, [polygon(2000, 0, 4000, 1000), polygon(0, 0, 2000, 1000)])
    config = config_for(root)
    first = table(run(config, "first")).iloc[0]
    rewrite_zones(root, {k: list(reversed(v)) for k, v in attrs.items()},
                  [polygon(0, 0, 2000, 1000), polygon(2000, 0, 4000, 1000)])
    second = table(run(config, "second")).iloc[0]
    assert first.zone_id == second.zone_id == "a"
    assert first.dominant_overlap_share == pytest.approx(0.5)


def test_reference_gap_does_not_clip_or_redefine_district_area(synthetic_inputs):
    root, _, _ = synthetic_inputs
    rewrite_districts(root, {"district_id": ["d1"], "district_name": ["One"]}, [polygon(0, 0, 4000, 1000)])
    rewrite_zones(root, {"zone_id": ["a"], "zone_name": ["Zone A"], "zone_code": ["A"]},
                  [polygon(0, 0, 1000, 1000)])
    out = run(config_for(root), "partial")
    assigned = table(out).iloc[0]
    assert assigned.dominant_overlap_share == pytest.approx(0.25)
    d = gpd.read_file(out / "boundaries/districts_within_acz.shp").geometry.iloc[0]
    assert d.equals(polygon(0, 0, 4000, 1000))
    assert d.area == pytest.approx(4_000_000)


def test_multiple_features_of_same_zone_are_combined_before_ranking(synthetic_inputs):
    root, _, _ = synthetic_inputs
    rewrite_districts(root, {"district_id": ["d1"], "district_name": ["One"]}, [polygon(0, 0, 4000, 1000)])
    rewrite_zones(root, {"zone_id": ["a", "a", "b"], "zone_name": ["Zone A", "Zone A", "Zone B"], "zone_code": ["A", "A", "B"]},
                  [polygon(0, 0, 1500, 1000), polygon(1500, 0, 2500, 1000), polygon(2500, 0, 4000, 1000)])
    assignment = table(run(config_for(root), "parts")).iloc[0]
    assert assignment.zone_id == "a"
    assert assignment.dominant_overlap_share == pytest.approx(0.625)


@pytest.mark.parametrize("zone_geometry", [polygon(9000, 0, 10000, 1000), polygon(4000, 0, 5000, 1000)])
def test_no_positive_area_overlap_fails_without_promoting_outputs(synthetic_inputs, zone_geometry):
    root, _, _ = synthetic_inputs
    rewrite_districts(root, {"district_id": ["d1"], "district_name": ["One"]}, [polygon(0, 0, 4000, 1000)])
    rewrite_zones(root, {"zone_id": ["a"], "zone_name": ["Zone A"], "zone_code": ["A"]}, [zone_geometry])
    with pytest.raises(PrepError):
        run(config_for(root), "unassigned")
    assert not (root / "out/unassigned").exists()


@pytest.mark.parametrize("problem", ["duplicate_id", "district_overlap", "invalid_geometry", "missing_field"])
def test_invalid_source_fails_before_outputs(synthetic_inputs, problem):
    root, _, _ = synthetic_inputs
    attrs = {"district_id": ["d1", "d2"], "district_name": ["One", "Two"]}
    geometries = [polygon(0, 0, 4000, 1000), polygon(4000, 0, 8000, 1000)]
    if problem == "duplicate_id":
        attrs["district_id"] = ["d1", "d1"]
    elif problem == "district_overlap":
        geometries[1] = polygon(3000, 0, 8000, 1000)
    elif problem == "invalid_geometry":
        geometries[0] = Polygon([(500000, 1000000), (504000, 1001000), (500000, 1001000), (504000, 1000000), (500000, 1000000)])
    elif problem == "missing_field":
        del attrs["district_name"]
    rewrite_districts(root, attrs, geometries)
    with pytest.raises(PrepError):
        run(config_for(root), "invalid")
    assert not (root / "out/invalid").exists()


def test_geographic_area_crs_is_rejected(synthetic_inputs):
    root, _, _ = synthetic_inputs
    cfg = config_for(root, crs={"working": "EPSG:4326", "area": "EPSG:4326"})
    with pytest.raises(PrepError):
        run(cfg, "degrees")
    assert not (root / "out/degrees").exists()


def test_existing_run_is_not_overwritten(synthetic_inputs):
    root, _, _ = synthetic_inputs
    cfg = config_for(root)
    out = run(cfg, "fixed")
    marker = out / "keep.txt"
    marker.write_text("retain", encoding="utf-8")
    with pytest.raises(PrepError):
        run(cfg, "fixed")
    assert marker.read_text() == "retain"


@pytest.mark.parametrize("run_id", ["../escape", "a/b", "", "/absolute"])
def test_unsafe_run_id_rejected(synthetic_inputs, run_id):
    root, _, _ = synthetic_inputs
    with pytest.raises(PrepError):
        run(config_for(root), run_id)


def test_expected_counts_are_profile_specific(synthetic_inputs):
    root, _, _ = synthetic_inputs
    cfg = config_for(root, expected={"districts": 2, "zones": 2})
    assert run(cfg, "toy").exists()
    cfg = config_for(root, expected={"districts": 260, "zones": 5})
    with pytest.raises(PrepError):
        run(cfg, "wrong-profile")
    assert not (root / "out/wrong-profile").exists()


def test_relocated_project_and_cli_validate(synthetic_inputs, tmp_path):
    root, _, _ = synthetic_inputs
    cfg = config_for(root)
    moved = tmp_path / "relocated"
    shutil.copytree(root, moved)
    result = validate(moved / cfg.name)
    assert isinstance(result, dict)
    out = run(moved / cfg.name, "portable")
    assert out.parent == moved / "out"
    assert not (root / "out").exists()
    cli = subprocess.run([sys.executable, "-m", "geo_data_prep", "validate", "--config", str(moved / cfg.name)],
                         cwd=tmp_path, capture_output=True, text=True)
    assert cli.returncode == 0, cli.stdout + cli.stderr


def test_validate_does_not_write_outputs(synthetic_inputs):
    root, _, _ = synthetic_inputs
    result = validate(config_for(root))
    assert isinstance(result, dict)
    assert not (root / "out").exists()


def test_reference_overlap_is_diagnostic_and_fraction_denominator_remains_whole_district(synthetic_inputs):
    root, _, _ = synthetic_inputs
    rewrite_districts(root, {"district_id": ["d1"], "district_name": ["One"]}, [polygon(0, 0, 4000, 1000)])
    rewrite_zones(root, {"zone_id": ["a", "b"], "zone_name": ["Zone A", "Zone B"], "zone_code": ["A", "B"]},
                  [polygon(0, 0, 3500, 1000), polygon(2000, 0, 4000, 1000)])
    out = run(config_for(root), "overlapping-reference")
    assigned = table(out).iloc[0]
    assert assigned.zone_id == "a"
    assert assigned.dominant_overlap_share == pytest.approx(.875)
    evidence = pd.read_csv(out / "qa/district_zone_overlap.csv")
    assert evidence.overlap_share.sum() == pytest.approx(1.375)
    qa = json.loads((out / "qa/qa_summary.json").read_text())
    assert qa["status"] == "WARN"
    assert qa["warnings"]


def test_missing_crs_is_rejected(synthetic_inputs):
    root, _, _ = synthetic_inputs
    path = root / "districts.shp"
    gpd.GeoDataFrame({"dist_id": ["d1"], "dist_name": ["One"]},
                     geometry=[polygon(0, 0, 4000, 1000)], crs=CRS).to_file(path, index=False)
    path.with_suffix(".prj").unlink()
    cfg_path = config_for(root)
    cfg = yaml.safe_load(cfg_path.read_text())
    cfg["inputs"]["districts"].update(path=path.name, id_field="dist_id", name_field="dist_name")
    cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    with pytest.raises(PrepError, match="[Cc][Rr][Ss]|[Cc]omponent"):
        run(cfg_path, "no-crs")
    assert not (root / "out/no-crs").exists()


def test_inconsistent_zone_metadata_is_rejected(synthetic_inputs):
    root, _, _ = synthetic_inputs
    rewrite_zones(root, {"zone_id": ["a", "a"], "zone_name": ["Zone A", "Different"], "zone_code": ["A", "A"]},
                  [polygon(0, 0, 4000, 1000), polygon(4000, 0, 8000, 1000)])
    with pytest.raises(PrepError):
        run(config_for(root), "bad-zone-label")
    assert not (root / "out/bad-zone-label").exists()


def test_string_identifiers_preserve_leading_zeroes(synthetic_inputs):
    root, _, _ = synthetic_inputs
    rewrite_districts(root, {"district_id": ["001", "002"], "district_name": ["One", "Two"]},
                      [polygon(0, 0, 4000, 1000), polygon(4000, 0, 8000, 1000)])
    rewrite_zones(root, {"zone_id": ["01", "02"], "zone_name": ["Zone A", "Zone B"], "zone_code": ["01", "02"]},
                  [polygon(0, 0, 3000, 1000), polygon(3000, 0, 8000, 1000)])
    out = run(config_for(root), "string-ids")
    selected = pd.read_csv(out / "crosswalks/district_zone_crosswalk.csv", dtype=str)
    assert list(selected.district_id) == ["001", "002"]
    assert list(selected.zone_id) == ["01", "02"]
    districts = gpd.read_file(out / "boundaries/districts_within_acz.shp")
    assert set(districts.dist_id) == {"001", "002"}
    assert set(districts.zone_code) == {"01", "02"}


def test_failed_output_write_never_publishes_partial_run(synthetic_inputs, monkeypatch):
    from geo_data_prep import pipeline
    root, _, _ = synthetic_inputs
    original = pipeline.export_layer
    calls = []
    def interrupted_export(frame, path):
        calls.append(path)
        if len(calls) == 2:
            raise RuntimeError("simulated output interruption")
        return original(frame, path)
    monkeypatch.setattr(pipeline, "export_layer", interrupted_export)
    with pytest.raises(RuntimeError, match="interruption"):
        run(config_for(root), "interrupted")
    assert calls
    assert not (root / "out/interrupted").exists()
    assert not list((root / "out").glob(".geo-prep-*"))


def test_output_manifest_hashes_and_crosswalk_provenance_bind_actual_files(synthetic_inputs):
    root, _, _ = synthetic_inputs
    out = run(config_for(root), "recorded")
    manifest = json.loads((out / "outputs_manifest.json").read_text())
    listed = manifest["files"]
    actual = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    assert set(listed) == actual - {"outputs_manifest.json"}
    for relative, info in listed.items():
        assert digest(out / relative) == info["sha256"]
        assert (out / relative).stat().st_size == info["bytes"]
    provenance = json.loads((out / "crosswalks/district_to_acz_max_overlap.provenance.json").read_text())
    assert digest(out / provenance["crosswalk"]["relative_path"]) == provenance["crosswalk"]["sha256"]
    assert provenance["source_district_geometry"]["parts"]["districts.gpkg"] == digest(root / "districts.gpkg")
    assert provenance["source_acz_geometry"]["parts"]["zones.gpkg"] == digest(root / "zones.gpkg")


def test_generated_zone_codes_are_invariant_to_input_order(synthetic_inputs):
    root, _, _ = synthetic_inputs
    attrs = {"zone_id": ["a", "b"], "zone_name": ["Alpha Zone", "Another Zone"]}
    rewrite_zones(root, attrs, [polygon(0, 0, 3000, 1000), polygon(3000, 0, 8000, 1000)])
    cfg_path = config_for(root)
    cfg = yaml.safe_load(cfg_path.read_text())
    del cfg["inputs"]["zones"]["code_field"]
    cfg_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    first = table(run(cfg_path, "ordered")).set_index("zone_id").zone_code.to_dict()
    rewrite_zones(root, {k: list(reversed(v)) for k, v in attrs.items()},
                  [polygon(3000, 0, 8000, 1000), polygon(0, 0, 3000, 1000)])
    second = table(run(cfg_path, "reversed")).set_index("zone_id").zone_code.to_dict()
    assert first == second
    assert len(set(first.values())) == 2


@pytest.mark.parametrize("crs", ["EPSG:NOT_A_CODE", "definitely not a coordinate system"])
def test_malformed_crs_has_a_controlled_error(synthetic_inputs, crs):
    root, _, _ = synthetic_inputs
    cfg = config_for(root, crs={"working": crs, "area": CRS})
    with pytest.raises(PrepError, match="[Cc][Rr][Ss]"):
        run(cfg, "malformed-crs")
    assert not (root / "out/malformed-crs").exists()


def test_config_mutation_during_output_write_prevents_promotion(synthetic_inputs, monkeypatch):
    from geo_data_prep import pipeline
    root, _, _ = synthetic_inputs
    cfg_path = config_for(root)
    original = pipeline.export_layer
    changed = []
    def changed_config_export(frame, path):
        result = original(frame, path)
        if not changed:
            cfg_path.write_text(cfg_path.read_text() + "\n# configuration modified while processing\n", encoding="utf-8")
            changed.append(True)
        return result
    monkeypatch.setattr(pipeline, "export_layer", changed_config_export)
    with pytest.raises(PrepError, match="[Cc]hang|[Mm]utat|[Ii]dent"):
        run(cfg_path, "changed-config")
    assert not (root / "out/changed-config").exists()
    assert not list((root / "out").glob(".geo-prep-*"))


def test_nonfinite_projected_coordinates_are_rejected(synthetic_inputs):
    root, _, _ = synthetic_inputs
    (root / "districts.gpkg").unlink()
    (root / "zones.gpkg").unlink()
    invalid_latitude = Polygon([(0, 95), (1, 95), (1, 96), (0, 96), (0, 95)])
    write_layer(root / "districts.gpkg", {"district_id": ["d1"], "district_name": ["One"]}, [invalid_latitude], crs="EPSG:4326")
    write_layer(root / "zones.gpkg", {"zone_id": ["a"], "zone_name": ["Zone A"], "zone_code": ["A"]}, [invalid_latitude], crs="EPSG:4326")
    cfg = config_for(root, crs={"working": CRS, "area": CRS, "output": "EPSG:4326"})
    with pytest.raises(PrepError):
        run(cfg, "nonfinite")
    assert not (root / "out/nonfinite").exists()


def test_source_mutation_during_output_write_prevents_promotion(synthetic_inputs, monkeypatch):
    from geo_data_prep import pipeline
    root, _, zone_path = synthetic_inputs
    cfg_path = config_for(root)
    original = pipeline.export_layer
    changed = []
    def changed_source_export(frame, path):
        result = original(frame, path)
        if not changed:
            with zone_path.open("ab") as stream:
                stream.write(b"source identity changed during processing")
            changed.append(True)
        return result
    monkeypatch.setattr(pipeline, "export_layer", changed_source_export)
    with pytest.raises(PrepError, match="[Cc]hang|[Mm]utat|[Ii]dent"):
        run(cfg_path, "changed-source")
    assert not (root / "out/changed-source").exists()
    assert not list((root / "out").glob(".geo-prep-*"))


def test_keyboard_interrupt_removes_staged_run(synthetic_inputs, monkeypatch):
    from geo_data_prep import pipeline
    root, _, _ = synthetic_inputs
    original = pipeline.export_layer
    calls = []
    def interrupt_export(frame, path):
        calls.append(path)
        if len(calls) == 2:
            raise KeyboardInterrupt("simulated user interruption")
        return original(frame, path)
    monkeypatch.setattr(pipeline, "export_layer", interrupt_export)
    with pytest.raises(KeyboardInterrupt):
        run(config_for(root), "cancelled")
    assert calls
    assert not (root / "out/cancelled").exists()
    assert not list((root / "out").glob(".geo-prep-*"))
