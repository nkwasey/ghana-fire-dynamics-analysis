"""Numbered district coverage, placement geometry and plot handoffs."""
from __future__ import annotations

import hashlib
import json

import geopandas as gpd
import numpy as np
import pandas as pd
from PIL import Image
from shapely.geometry import MultiPolygon, Point, box

from geo_test_helpers import CRS, polygon
from geo_data_prep.pipeline import run
from geo_data_prep.plotting import label_layout
from test_pipeline import config_for


def crowded_districts(count=110):
    """A dense synthetic zone with exact, nonoverlapping administrative cells."""
    records = []
    for number in range(count):
        column, row = number % 10, number // 10
        records.append({
            "dist_id": f"district_{number:03d}",
            "dist_name": f"EXAMPLE ADMINISTRATIVE DISTRICT {number:03d}",
            "zone_id": "reporting_zone",
            "geometry": polygon(column * 1000, row * 1000,
                                column * 1000 + 1000, row * 1000 + 1000),
        })
    return gpd.GeoDataFrame(records, geometry="geometry", crs=CRS)


def test_crowded_layout_has_each_name_once_and_anchors_inside_districts():
    districts = crowded_districts()
    layout = label_layout(districts)
    assert len(layout) == len(districts) == 110
    assert layout.dist_id.is_unique
    assert set(layout.dist_id) == set(districts.dist_id)
    expected = districts.set_index("dist_id").dist_name.to_dict()
    assert layout.set_index("dist_id").label_text.to_dict() == expected
    assert layout.set_index("dist_id").dist_name.to_dict() == expected
    assert np.isfinite(layout[["anchor_lon", "anchor_lat"]].to_numpy()).all()
    expected_numbers = {
        record.dist_id: number
        for number, record in enumerate(
            districts.sort_values(["dist_name", "dist_id"]).itertuples(), start=1)
    }
    assert layout.set_index("dist_id").label_number.to_dict() == expected_numbers
    native = districts.to_crs(4326).set_index("dist_id")
    for row in layout.itertuples():
        assert native.loc[row.dist_id].geometry.covers(Point(row.anchor_lon, row.anchor_lat))


def test_label_layout_is_invariant_to_input_row_order():
    districts = crowded_districts(17)
    first = label_layout(districts).sort_values("dist_id").reset_index(drop=True)
    shuffled = districts.sample(frac=1, random_state=24).reset_index(drop=True)
    second = label_layout(shuffled).sort_values("dist_id").reset_index(drop=True)
    pd.testing.assert_frame_equal(first, second)


def test_identical_names_and_multipart_districts_keep_individual_labels():
    districts = crowded_districts(2)
    districts["dist_name"] = "SHARED DISPLAY NAME"
    districts.loc[0, "geometry"] = MultiPolygon([
        polygon(0, 0, 300, 300), polygon(500, 500, 800, 800)
    ])
    layout = label_layout(districts)
    assert len(layout) == 2
    assert layout.dist_id.is_unique
    assert list(layout.label_text) == ["SHARED DISPLAY NAME"] * 2
    geometry = districts.to_crs(4326).set_index("dist_id")
    for row in layout.itertuples():
        assert geometry.loc[row.dist_id].geometry.covers(Point(row.anchor_lon, row.anchor_lat))


def test_plotted_run_exports_named_png_pdf_and_inventory_in_manifest(synthetic_inputs):
    root, _, _ = synthetic_inputs
    config = config_for(root, outputs={"root": "out", "splits": True, "plots": True})
    output = run(config, "labelled")
    boundaries = gpd.read_file(output / "boundaries/districts_within_acz.shp")
    manifest = json.loads((output / "outputs_manifest.json").read_text())["files"]
    seen = []
    for zone_id, members in boundaries.groupby("zone_id"):
        stem = f"plots/per_zone/{zone_id}"
        png, pdf, inventory = [output / (stem + suffix)
                               for suffix in (".png", ".pdf", "_labels.csv")]
        with Image.open(png) as image:
            image.verify()
        with Image.open(png) as image:
            assert image.width > 100 and image.height > 100
            assert np.asarray(image).std() > 0
        pdf_bytes = pdf.read_bytes()
        assert pdf_bytes.startswith(b"%PDF-") and b"%%EOF" in pdf_bytes[-1024:]
        labels = pd.read_csv(inventory, dtype={"dist_id": str, "zone_id": str})
        assert labels.dist_id.is_unique
        assert set(labels.dist_id) == set(members.dist_id)
        assert labels.set_index("dist_id").label_text.to_dict() == members.set_index("dist_id").dist_name.to_dict()
        assert set(labels.zone_id) == {zone_id}
        assert set(labels.label_number) == set(range(1, len(members) + 1))
        assert_number_geometry(labels, members)
        seen.extend(labels.dist_id)
        for path in (png, pdf, inventory):
            relative = path.relative_to(output).as_posix()
            assert relative in manifest
            assert manifest[relative]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert len(seen) == len(set(seen)) == len(boundaries)
    assert (output / "plots/combined_zones_districts.png").exists()
    diagnostics = json.loads((output / "plots/district_label_checks.json").read_text())
    assert sum(row["district_label_count"] for row in diagnostics["zones"]) == len(boundaries)
    assert {row["zone_id"] for row in diagnostics["zones"]} == set(boundaries.zone_id)
    for row in diagnostics["zones"]:
        assert row["label_bbox_overlap_count"] == row["label_bbox_clipped_count"] == 0
        assert row["district_label_count"] == row["district_count"]
        assert row["number_inside_count"] == row["district_count"]
        assert row["number_bbox_overlap_count"] == 0
        assert row["minimum_number_font_size_pt"] >= 6


def assert_number_geometry(labels, districts):
    """Independently compare rendered text rectangles with source polygons."""
    required = {
        "panel", "number_lon", "number_lat", "font_size_pt",
        "bbox_min_lon", "bbox_min_lat", "bbox_max_lon", "bbox_max_lat",
    }
    assert required <= set(labels.columns)
    coordinates = list(required - {"panel"})
    assert np.isfinite(labels[coordinates].to_numpy(dtype=float)).all()
    assert (labels.font_size_pt >= 6.0).all()
    geometry = districts.to_crs(4326).set_index("dist_id").geometry
    rectangles = []
    for label in labels.itertuples():
        extent = box(label.bbox_min_lon, label.bbox_min_lat,
                     label.bbox_max_lon, label.bbox_max_lat)
        assert extent.area > 0
        assert geometry.loc[label.dist_id].covers(extent)
        assert geometry.loc[label.dist_id].covers(Point(label.number_lon, label.number_lat))
        rectangles.append((label.panel, extent))
    # In a panel every geographic-to-display transform is affine, so disjoint
    # geographic rectangles independently establish disjoint rendered boxes.
    for index, (panel, extent) in enumerate(rectangles):
        for other_panel, other_extent in rectangles[index + 1:]:
            if panel == other_panel:
                assert extent.intersection(other_extent).area == 0


def render_one_zone(districts, root):
    from geo_data_prep.plotting import render_plots
    zones = gpd.GeoDataFrame([{
        "zone_id": districts.zone_id.iloc[0], "zone_name": "REPORTING ZONE",
        "zone_code": "RZ", "geometry": districts.geometry.union_all(),
    }], geometry="geometry", crs=districts.crs)
    render_plots(districts, zones, root)
    return pd.read_csv(root / "per_zone" / (zones.zone_id.iloc[0] + "_labels.csv"),
                       dtype={"dist_id": str, "zone_id": str})


def test_rendered_numbers_in_dense_grid_fit_districts_and_do_not_overlap(tmp_path):
    districts = crowded_districts()
    # A central hole prevents centroid-only placement from satisfying the test.
    districts.loc[0, "geometry"] = districts.loc[0, "geometry"].difference(
        polygon(200, 200, 800, 800))
    labels = render_one_zone(districts, tmp_path / "dense")
    assert len(labels) == 110 and labels.dist_id.is_unique
    assert set(labels.dist_id) == set(districts.dist_id)
    assert labels.set_index("dist_id").label_text.to_dict() == districts.set_index("dist_id").dist_name.to_dict()
    assert_number_geometry(labels, districts)
    diagnostics = json.loads((tmp_path / "dense/district_label_checks.json").read_text())
    assert diagnostics["zones"][0]["key_columns"] == 4


def test_tiny_district_uses_detail_panel_instead_of_unreadable_number(tmp_path):
    districts = gpd.GeoDataFrame([
        {"dist_id": "big", "dist_name": "LARGE DISTRICT", "zone_id": "reporting_zone",
         "geometry": polygon(0, 0, 100000, 100000)},
        {"dist_id": "small", "dist_name": "SMALL DISTRICT", "zone_id": "reporting_zone",
         "geometry": polygon(100100, 0, 100110, 10)},
        {"dist_id": "medium", "dist_name": "MEDIUM DISTRICT", "zone_id": "reporting_zone",
         "geometry": polygon(100300, 0, 101300, 1000)},
    ], geometry="geometry", crs=CRS)
    labels = render_one_zone(districts, tmp_path / "detail")
    assert len(labels) == 3 and labels.dist_id.is_unique
    assert labels.set_index("dist_id").loc["small", "panel"] != "main"
    assert_number_geometry(labels, districts)
    diagnostics = json.loads((tmp_path / "detail/district_label_checks.json").read_text())
    assert diagnostics["zones"][0]["detail_panel_count"] >= 1
