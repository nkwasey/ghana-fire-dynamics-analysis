"""Synthetic presentation-layout checks that require no generated study outputs."""
from __future__ import annotations

import io
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
import pytest
from PIL import Image
from pypdf import PdfReader
from shapely.geometry import box

from rp1_analysis_v1 import figures, mapping, presentation_rq3
from rp1_analysis_v1.config import load_figure_contract
from rp1_analysis_v1.grid_rendering import ensure_axis_titles_inside_canvas
from rp1_analysis_v1.presentation import get_presentation_export_spec
from rp1_analysis_v1.style import PublicationStyle


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def figure_style():
    contract = load_figure_contract(ROOT / "config/figure_contract.yml")
    size = (20.0 / 2.54, 15.0 / 2.54)
    style = replace(PublicationStyle.from_contract(contract), full_width_map=size, single_panel=size)
    return contract, style


@pytest.fixture
def geography():
    districts = gpd.GeoDataFrame(
        {
            "dist_id": ["D1", "D2", "D3"],
            "zone_id": ["Z1", "Z2", "Z3"],
            "zone_code": ["CZ", "FZ", "GS"],
            "zone_name": ["Coastal", "Forest", "Savannah"],
        },
        geometry=[box(200000, i * 350000, 800000, (i + 1) * 350000) for i in range(3)],
        crs="EPSG:32630",
    )
    acz = districts.drop(columns=["dist_id"]).copy()
    return mapping.prepare_geography(districts, acz)


def _assert_titles_inside(fig):
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    canvas = fig.get_window_extent(renderer)
    for ax in fig.axes:
        if ax.get_title():
            extent = ax.title.get_window_extent(renderer)
            assert extent.x0 >= canvas.x0
            assert extent.x1 <= canvas.x1
            assert extent.y0 >= canvas.y0
            assert extent.y1 < canvas.y1
    for title in fig.texts:
        if title.get_gid() == "map-presentation-title":
            extent = title.get_window_extent(renderer)
            assert canvas.contains(extent.x0, extent.y0)
            assert canvas.contains(extent.x1, extent.y1)


@pytest.mark.parametrize("title", [
    "District long-run mapped burned-area rate",
    "District departure from parent ACZ\nFixed-support mapped burned-area rate",
])
def test_measured_title_clearance_preserves_canvas_limits_aspect_and_ancillary_axes(figure_style, geography, title):
    _contract, style = figure_style
    frame = pd.DataFrame({"unit_id": ["D1", "D2", "D3"],
                          "support_status": ["excluded", "valid_zero", "valid_nonzero"],
                          "value": [None, 0.0, 2.0]})
    with plt.rc_context(style.rc_params()):
        fig, ax = mapping._build_choropleth_figure(
            geography, frame, value="value", title=title,
            colorbar_label="Mapped area per 100 km²", style=style,
        )
        try:
            before_size = tuple(fig.get_size_inches())
            before_limits = (ax.get_xlim(), ax.get_ylim(), ax.get_aspect())
            ancillary = {other: other.get_position().bounds for other in fig.axes if other is not ax}
            ensure_axis_titles_inside_canvas(fig, tuple(fig.axes))
            _assert_titles_inside(fig)
            assert tuple(fig.get_size_inches()) == before_size
            assert (ax.get_xlim(), ax.get_ylim(), ax.get_aspect()) == before_limits
            assert all(other.get_position().bounds == bounds for other, bounds in ancillary.items())
            position = ax.get_position().bounds
            ensure_axis_titles_inside_canvas(fig, tuple(fig.axes))
            assert ax.get_position().bounds == pytest.approx(position, abs=1e-12)
        finally:
            plt.close(fig)


@pytest.mark.parametrize(("kind", "has_colourbar", "has_side_key"), [
    ("district", True, False),
    ("district_signed", True, True),
    ("district_percent", True, True),
    ("acz", True, False),
    ("categorical", False, True),
    ("support", False, False),
    ("support_acz", False, True),
    ("context", False, True),
])
def test_map_families_export_complete_titles_on_exact_png_and_pdf_canvas(
    monkeypatch, figure_style, geography, kind, has_colourbar, has_side_key,
):
    _contract, style = figure_style
    original_export = figures._export
    inspected = []

    def inspect_export(fig, configured_style):
        _assert_titles_inside(fig)
        if kind != "support":
            renderer = fig.canvas.get_renderer()
            map_ax = next(ax for ax in fig.axes if str(ax.get_gid()).endswith("map-viewport"))
            map_bounds = map_ax.get_window_extent(renderer)
            keys = [
                ax.get_legend() for ax in fig.axes
                if ax.get_legend() is not None and ax.get_legend().get_gid() == "map-presentation-right-key"
            ]
            bars = [ax for ax in fig.axes if ax.get_gid() in {"map-colorbar", "map-colorbar-grid"}]
            assert len(keys) == int(has_side_key)
            assert len(bars) == int(has_colourbar)
            assert any(text.get_gid() == "map-north-arrow" for text in map_ax.texts)
            assert any(line.get_gid() == "map-scale-bar" for line in map_ax.lines)
            if keys:
                key = keys[0]
                bounds = key.get_window_extent(renderer)
                assert key.get_frame_on()
                assert bounds.x0 > map_bounds.x1
                assert bounds.x1 < fig.bbox.x1
                assert map_bounds.y0 <= bounds.y0 <= bounds.y1 <= map_bounds.y1
                key_texts = [text.get_text() for text in key.get_texts()]
                if kind == "district_signed":
                    assert key_texts == ["Below ACZ", "Above ACZ", "Valid zero"]
                elif kind == "district_percent":
                    assert key_texts == ["Valid zero", "Excluded / unsupported"]
            if bars:
                bar = bars[0]
                bounds = bar.get_tightbbox(renderer)
                assert bounds.y1 < map_bounds.y0 and bounds.y0 > fig.bbox.y0
                assert bounds.width > bounds.height
                if kind == "district_percent":
                    assert bar.get_xlim() == pytest.approx((0.0, 1.0))
                    assert all(tick.get_text().endswith("%") for tick in bar.get_xticklabels())
        inspected.append(True)
        return original_export(fig, configured_style)

    monkeypatch.setattr(figures, "_export", inspect_export)
    frame = pd.DataFrame({"unit_id": ["D1", "D2", "D3"],
                          "parent_code": ["CZ", "FZ", "GS"],
                          "support_status": ["valid_nonzero"] * 3,
                          "value": [1.0, 2.0, 3.0], "local_class": ["HH", "LL", "NS"]})
    title = "Mapped burned-area patterns\nComplete title within the physical page"
    if kind == "district":
        result = mapping.choropleth(geography, frame, value="value", title=title, colorbar_label="Area rate", style=style)
    elif kind == "district_signed":
        frame["support_status"] = ["valid_nonzero", "valid_zero", "valid_nonzero"]
        frame["value"] = [-4.0, 0.0, 8.0]
        result = mapping.choropleth(
            geography, frame, value="value", title=title, colorbar_label="Area rate departure",
            style=style, cmap="coolwarm", symmetric_about_zero=True,
        )
    elif kind == "district_percent":
        frame["support_status"] = ["excluded", "valid_zero", "valid_nonzero"]
        frame["value"] = [None, 0.0, 0.75]
        result = mapping.choropleth(
            geography, frame, value="value", title=title, colorbar_label="Conditional absence",
            style=style, show_percent=True,
        )
    elif kind == "acz":
        acz_frame = pd.DataFrame({"unit_id": ["Z1", "Z2", "Z3"], "value": [1.0, 2.0, 3.0]})
        result = mapping.acz_choropleth(geography, acz_frame, value="value", title=title, colorbar_label="Area rate", style=style)
    elif kind == "categorical":
        result = mapping.categorical_map(geography, frame, category="local_class", title=title, style=style)
    elif kind == "support":
        result = mapping.support_map(geography, frame, title=title, style=style)
    elif kind == "support_acz":
        result = mapping.support_acz_map(geography, frame, title=title, style=style)
    else:
        result = mapping.acz_categorical_context_map(
            geography.acz, category="zone_code", category_order=("CZ", "FZ", "GS"),
            category_colours={"CZ": "gold", "FZ": "green", "GS": "orange"},
            category_labels={}, title=title, style=style,
        )
    assert inspected == [True]
    with Image.open(io.BytesIO(result.png)) as image:
        assert image.size == style.raster_pixels_for_inches(style.full_width_map)
    page = PdfReader(io.BytesIO(result.pdf)).pages[0]
    assert float(page.mediabox.width) == pytest.approx(style.full_width_map[0] * 72.0)
    assert float(page.mediabox.height) == pytest.approx(style.full_width_map[1] * 72.0)
    assert "Complete title within the physical page" in page.extract_text()


def test_four_state_summary_is_inside_bottom_right_with_centered_legend_below(monkeypatch, figure_style):
    contract, style = figure_style
    spec = get_presentation_export_spec("rq3_four_state_correspondence", contract)
    context = SimpleNamespace(bundle=SimpleNamespace(figure=contract), registry=contract.presentation_export, style=style)
    states = presentation_rq3._EXPECTED_STATES
    frame = pd.DataFrame([{"parent_code": code, "unit_name": code, "state": state, "proportion": 0.25}
                          for code in ("CZ", "FZ", "GS", "SS", "TZ") for state in states])
    counts = dict(zip(states, [11000, 12, 22000, 33000], strict=True))
    monkeypatch.setattr(presentation_rq3, "_overall_four_state_counts", lambda _context: counts)
    original_export = figures._export
    inspected = []

    def inspect_export(fig, configured_style):
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        plot = next(ax for ax in fig.axes if ax.get_gid() == "rq3-four-state-plot")
        summary = next(text for text in plot.texts if text.get_gid() == "rq3-four-state-counts")
        legend = next(ax.get_legend() for ax in fig.axes if ax.get_legend() is not None)
        summary_bounds = summary.get_bbox_patch().get_window_extent(renderer)
        legend_bounds = legend.get_window_extent(renderer)
        plot_bounds = plot.get_window_extent(renderer)
        canvas = fig.get_window_extent(renderer)
        assert summary.get_ha() == "right" and summary.get_va() == "bottom"
        assert 0.0 < summary.get_bbox_patch().get_alpha() < 1.0
        assert summary_bounds.x0 >= plot_bounds.x0
        assert summary_bounds.x1 <= plot_bounds.x1
        assert summary_bounds.y0 >= plot_bounds.y0
        assert summary_bounds.y1 <= plot_bounds.y1
        assert summary_bounds.x1 > plot_bounds.x0 + 0.9 * plot_bounds.width
        assert summary_bounds.y0 < plot_bounds.y0 + 0.1 * plot_bounds.height
        assert legend_bounds.y1 < plot.xaxis.label.get_window_extent(renderer).y0
        assert legend_bounds.y1 < plot_bounds.y0
        assert (legend_bounds.x0 + legend_bounds.x1) / 2 == pytest.approx(
            (plot_bounds.x0 + plot_bounds.x1) / 2, abs=0.1,
        )
        assert summary_bounds.x1 <= canvas.x1 and summary_bounds.y0 >= canvas.y0
        assert f"n={sum(counts.values()):,}" in summary.get_text()
        assert all(f"{value:,}" in summary.get_text() for value in counts.values())
        assert all(patch.get_height() == pytest.approx(0.25) for container in plot.containers for patch in container.patches)
        _assert_titles_inside(fig)
        inspected.append(True)
        return original_export(fig, configured_style)

    monkeypatch.setattr(figures, "_export", inspect_export)
    result = presentation_rq3.render_rq3_four_state_correspondence(frame, spec=spec, context=context)
    assert inspected == [True]
    assert result.png.startswith(b"\x89PNG") and result.pdf.startswith(b"%PDF")
