"""Adversarial configuration and source-identity contracts."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from geo_data_prep import pipeline
from geo_data_prep.pipeline import PrepError, run, validate
from geo_test_helpers import polygon
from test_pipeline import config_for, rewrite_districts, rewrite_zones


def configured(root, section, key, value):
    path = config_for(root)
    cfg = yaml.safe_load(path.read_text())
    if section is None:
        cfg[key] = value
    else:
        cfg.setdefault(section, {})[key] = value
    path.write_text(yaml.safe_dump(cfg))
    return path


def assert_no_published_run(root, name):
    assert not (root / "out" / name).exists()
    assert not list((root / "out").glob(".geo-prep-*"))


@pytest.mark.parametrize("operation", ["validate", "run"])
def test_source_change_after_read_cannot_be_bound_to_an_unread_fingerprint(synthetic_inputs, monkeypatch, operation):
    root, district_path, _ = synthetic_inputs
    config = config_for(root)
    original = pipeline.read_layer
    changed = []

    def changed_after_read(cfg, role):
        result = original(cfg, role)
        if role == "districts" and not changed:
            with district_path.open("ab") as stream:
                stream.write(b"source changed after its features were read")
            changed.append(True)
        return result

    monkeypatch.setattr(pipeline, "read_layer", changed_after_read)
    with pytest.raises(PrepError, match="[Cc]hang|[Mm]utat|[Ii]dent"):
        validate(config) if operation == "validate" else run(config, "changed-read")
    assert changed
    assert_no_published_run(root, "changed-read")


def test_source_change_while_reader_runs_is_rejected(synthetic_inputs, monkeypatch):
    root, district_path, _ = synthetic_inputs
    config = config_for(root)
    original = pipeline.gpd.read_file
    changed = []

    def changed_in_reader(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        if Path(path).resolve() == district_path.resolve() and not changed:
            with district_path.open("ab") as stream:
                stream.write(b"source changed inside reader before returning features")
            changed.append(True)
        return result

    monkeypatch.setattr(pipeline.gpd, "read_file", changed_in_reader)
    with pytest.raises(PrepError, match="[Cc]hang|[Mm]utat|[Ii]dent"):
        run(config, "changed-reader")
    assert changed
    assert_no_published_run(root, "changed-reader")


def test_configuration_parse_uses_a_bound_byte_snapshot(synthetic_inputs, monkeypatch):
    root, _, _ = synthetic_inputs
    config = config_for(root)
    original = pipeline.yaml.load
    changed = []

    def changed_after_parse(stream, *args, **kwargs):
        result = original(stream, *args, **kwargs)
        if not changed:
            config.write_text(config.read_text() + "\n# configuration changed after parsing\n")
            changed.append(True)
        return result

    monkeypatch.setattr(pipeline.yaml, "load", changed_after_parse)
    with pytest.raises(PrepError, match="[Cc]hang|[Mm]utat|[Ii]dent"):
        run(config, "changed-parse")
    assert changed
    assert_no_published_run(root, "changed-parse")


@pytest.mark.parametrize("section,key,value", [
    ("outputs", "plots", "false"),
    ("outputs", "splits", 0),
    ("assignment", "warning_share", "0.5"),
    ("assignment", "warning_margin", None),
    ("assignment", "tie_tolerance", True),
    ("qa", "area_tolerance_m2", None),
    (None, "assignment", None),
    (None, "outputs", None),
    ("expected", "districts", 0),
    ("expected", "districts", -2),
    ("expected", "districts", 2.5),
    ("expected", "districts", True),
    ("expected", "districts", "2"),
])
def test_malformed_configuration_has_a_controlled_rejection(synthetic_inputs, section, key, value):
    root, _, _ = synthetic_inputs
    config = configured(root, section, key, value)
    with pytest.raises(PrepError):
        run(config, "bad-config")
    assert_no_published_run(root, "bad-config")


@pytest.mark.parametrize("section,key,value", [
    (None, "assigment", {}),
    ("assignment", "warning_shrae", .9),
    ("outputs", "plot", False),
    ("expected", "district", 2),
])
def test_unknown_configuration_key_cannot_silently_select_a_default(synthetic_inputs, section, key, value):
    root, _, _ = synthetic_inputs
    config = configured(root, section, key, value)
    with pytest.raises(PrepError):
        run(config, "typo")
    assert_no_published_run(root, "typo")


def test_zone_identifiers_that_alias_on_case_insensitive_filesystems_are_rejected(synthetic_inputs):
    root, _, _ = synthetic_inputs
    rewrite_zones(root, {"zone_id": ["a", "A"], "zone_name": ["First", "Second"], "zone_code": ["A", "B"]},
                  [polygon(0, 0, 3000, 1000), polygon(3000, 0, 8000, 1000)])
    with pytest.raises(PrepError):
        run(config_for(root), "case-alias")
    assert_no_published_run(root, "case-alias")


def test_low_overlap_warning_assesses_the_selected_tie_winner(synthetic_inputs):
    root, _, _ = synthetic_inputs
    rewrite_districts(root, {"district_id": ["d1"], "district_name": ["One"]}, [polygon(0, 0, 1000, 1000)])
    rewrite_zones(root, {"zone_id": ["a", "b"], "zone_name": ["First", "Second"], "zone_code": ["A", "B"]},
                  [polygon(0, 0, 100, 1000), polygon(100, 0, 1000, 1000)])
    config = configured(root, "assignment", "tie_tolerance", .81)
    # The deliberately wide supplied tolerance selects lexical a with .1 share.
    # Warning semantics must remain correct for every accepted tolerance.
    qa = validate(config)
    assert any("Low selected reference overlap" in message for message in qa["warnings"])


def test_identifiers_are_scoped_by_level_in_the_unit_universe(synthetic_inputs):
    root, _, _ = synthetic_inputs
    rewrite_districts(root, {"district_id": ["a", "d2"], "district_name": ["One", "Two"]},
                      [polygon(0, 0, 4000, 1000), polygon(4000, 0, 8000, 1000)])
    output = run(config_for(root), "scoped-ids")
    units = pd.read_csv(output / "unit_universe.csv", keep_default_na=False)
    assert (units.unit_id == "a").sum() == 2
    assert not units[["level", "unit_id"]].duplicated().any()
    assert set(units.loc[units.unit_id == "a", "level"]) == {"district", "acz"}


@pytest.mark.parametrize("scope", ["top", "nested"])
def test_duplicate_yaml_keys_are_rejected_instead_of_overwriting_values(synthetic_inputs, scope):
    root, _, _ = synthetic_inputs
    config = config_for(root)
    if scope == "top":
        config.write_text(config.read_text() + "\noutputs:\n  plots: false\n")
    else:
        cfg = yaml.safe_load(config.read_text())
        del cfg["assignment"]
        config.write_text(yaml.safe_dump(cfg) + "\nassignment:\n  warning_share: 0.5\n  warning_share: 0.9\n")
    with pytest.raises(PrepError):
        run(config, "duplicate-key")
    assert_no_published_run(root, "duplicate-key")


@pytest.mark.parametrize("identifier", ["CON", "nul", "Com1", "LPT9"])
def test_reserved_platform_zone_basenames_are_rejected(synthetic_inputs, identifier):
    root, _, _ = synthetic_inputs
    rewrite_zones(root, {"zone_id": [identifier, "b"], "zone_name": ["First", "Second"], "zone_code": ["A", "B"]},
                  [polygon(0, 0, 3000, 1000), polygon(3000, 0, 8000, 1000)])
    with pytest.raises(PrepError):
        run(config_for(root), "reserved-name")
    assert_no_published_run(root, "reserved-name")


def test_serialization_must_preserve_collinear_vertices(synthetic_inputs, monkeypatch):
    from shapely.geometry import Polygon
    root, _, _ = synthetic_inputs
    geometry = Polygon([(500000, 1000000), (502000, 1000000), (504000, 1000000),
                        (504000, 1001000), (500000, 1001000), (500000, 1000000)])
    rewrite_districts(root, {"district_id": ["d1", "d2"], "district_name": ["One", "Two"]},
                      [geometry, polygon(4000, 0, 8000, 1000)])
    config = configured(root, "outputs", "splits", False)
    original = pipeline.gpd.read_file
    changed = []

    def simplified_export_readback(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        if Path(path).name == "districts_within_acz.shp" and not changed:
            simplified = result.geometry.iloc[0].simplify(0)
            assert simplified.equals(result.geometry.iloc[0])
            assert len(simplified.exterior.coords) < len(result.geometry.iloc[0].exterior.coords)
            result.loc[result.index[0], result.geometry.name] = simplified
            changed.append(True)
        return result

    monkeypatch.setattr(pipeline.gpd, "read_file", simplified_export_readback)
    with pytest.raises(PrepError, match="[Gg]eometry|[Vv]ert|[Cc]oordinat"):
        run(config, "vertex-loss")
    assert changed
    assert_no_published_run(root, "vertex-loss")


def multilayer_zone_config(root, selected_layer):
    import geopandas as gpd
    path = root / "reference.gpkg"
    attrs = {"zone_id": ["a", "b"], "zone_name": ["Zone A", "Zone B"], "zone_code": ["A", "B"]}
    for layer, split in [("first", 3000), ("second", 1000)]:
        frame = gpd.GeoDataFrame(attrs, geometry=[polygon(0, 0, split, 1000), polygon(split, 0, 8000, 1000)], crs="EPSG:32630")
        frame.to_file(path, layer=layer, driver="GPKG", index=False)
    config = config_for(root)
    cfg = yaml.safe_load(config.read_text())
    cfg["inputs"]["zones"]["path"] = path.name
    if selected_layer is not None:
        cfg["inputs"]["zones"]["layer"] = selected_layer
    config.write_text(yaml.safe_dump(cfg))
    return config


def test_explicit_geopackage_layer_selects_the_requested_scientific_reference(synthetic_inputs):
    import json
    root, _, _ = synthetic_inputs
    config = multilayer_zone_config(root, "second")
    output = run(config, "selected-layer")
    assignments = pd.read_csv(output / "crosswalks/district_zone_crosswalk.csv").set_index("district_id")
    assert assignments.loc["d1", "zone_id"] == "b"
    assert assignments.loc["d1", "dominant_overlap_share"] == pytest.approx(.75)
    recorded = json.loads((output / "run_configuration.json").read_text())
    assert recorded["inputs"]["zones"]["layer"] == "second"
    fingerprint = json.loads((output / "inputs_fingerprint.json").read_text())
    assert fingerprint["zones"]["layer"] == "second"
    provenance = json.loads((output / "crosswalks/district_to_acz_max_overlap.provenance.json").read_text())
    assert provenance["source_acz_geometry"]["layer"] == "second"


def test_ambiguous_geopackage_layer_requires_explicit_selection(synthetic_inputs):
    root, _, _ = synthetic_inputs
    with pytest.raises(PrepError):
        run(multilayer_zone_config(root, None), "ambiguous-layer")
    assert_no_published_run(root, "ambiguous-layer")


def test_missing_requested_geopackage_layer_is_rejected(synthetic_inputs):
    root, _, _ = synthetic_inputs
    with pytest.raises(PrepError):
        run(multilayer_zone_config(root, "not_present"), "missing-layer")
    assert_no_published_run(root, "missing-layer")
