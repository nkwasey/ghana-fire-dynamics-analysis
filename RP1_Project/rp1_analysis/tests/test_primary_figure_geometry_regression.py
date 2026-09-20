from __future__ import annotations

from pathlib import Path
from io import BytesIO
import hashlib
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest
from PIL import Image
from pypdf import PdfReader
import io

from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.data_io import load_data_authorities
from rp1_analysis_v1.figures import (
    draw_circular_mean_timing,
    draw_coefficient_or_plot,
    draw_district_seasonal_heatmap,
    draw_resultant_length_by_group,
    draw_seasonality_lines,
    draw_shared_trajectory_key,
    draw_stacked_proportions,
    draw_trajectory_panel,
    district_seasonal_components,
    export_figure,
)
from rp1_analysis_v1.grid_rendering import (
    add_panel_labels,
    apply_axis_label_padding,
    apply_grid_spacing,
    build_grid_figure,
    build_horizontal_gutter_axes,
    build_vertical_band_axes,
    ensure_vertical_band_xlabel_clearance,
    ensure_axis_labels_inside_canvas,
)
from rp1_analysis_v1.mapping import (
    draw_acz_choropleth_axis,
    draw_categorical_axis,
    draw_choropleth_axis,
    prepare_geography,
)
from rp1_analysis_v1.paths import ProjectPaths
from rp1_analysis_v1.presentation import load_figure_specs
from rp1_analysis_v1.style import PublicationStyle

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / "data/authorities/publication"


def _intersects(a, b, tol=0.0) -> bool:
    return not (a.x1 <= b.x0 + tol or b.x1 <= a.x0 + tol or a.y1 <= b.y0 + tol or b.y1 <= a.y0 + tol)


def _assert_visible_text_inside_canvas(fig, *, tol_px: float = 1.0) -> None:
    ensure_axis_labels_inside_canvas(fig, tuple(fig.axes))
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    canvas = fig.get_window_extent(renderer)
    for text in fig.findobj(match=lambda artist: isinstance(artist, matplotlib.text.Text)):
        if not text.get_visible() or not str(text.get_text()).strip():
            continue
        box = text.get_window_extent(renderer)
        assert box.x0 >= canvas.x0 - tol_px, (text.get_text(), box.bounds, canvas.bounds)
        assert box.y0 >= canvas.y0 - tol_px, (text.get_text(), box.bounds, canvas.bounds)
        assert box.x1 <= canvas.x1 + tol_px, (text.get_text(), box.bounds, canvas.bounds)
        assert box.y1 <= canvas.y1 + tol_px, (text.get_text(), box.bounds, canvas.bounds)


@pytest.fixture(scope="module")
def context():
    paths = ProjectPaths(ROOT)
    bundle = load_configuration_bundle(ROOT / "config")
    style = PublicationStyle.from_contract(bundle.figure)
    auth = load_data_authorities(paths, bundle.data_schema)
    geo = prepare_geography(auth.district_geometry, auth.acz_geometry)
    specs = {s.figure_id: s for s in load_figure_specs(bundle.figure)}
    return bundle, style, auth, geo, specs


def _source(name: str) -> pd.DataFrame:
    return pd.read_csv(PUB / name)


def test_f2_actual_paired_map_geometry_and_cartographic_alignment(context) -> None:
    bundle, style, _auth, geo, specs = context
    spec = specs["F2"]
    frame = _source("long_run_spatial_rate_presentation_source.csv")
    layout = style.grid_for(spec.layout_role)
    grid = build_grid_figure(layout, figure_size=style.dimensions_for(spec.layout_role))
    apply_grid_spacing(grid.figure, layout, style=style)
    a = frame.loc[frame["panel"].eq("direct_acz_long_run_rate")]
    b = frame.loc[frame["panel"].eq("district_long_run_rate")]
    pa = draw_acz_choropleth_axis(grid.figure, grid.data_axes[0], geo, a, value="value", colorbar_label=str(spec.renderer_options["panel_colorbar_labels"][0]), style=style)
    pb = draw_choropleth_axis(grid.figure, grid.data_axes[1], geo, b, value="value", colorbar_label=str(spec.renderer_options["panel_colorbar_labels"][1]), style=style)
    try:
        grid.figure.canvas.draw()
        ba = pa.map_ax.get_position().bounds
        bb = pb.map_ax.get_position().bounds
        assert ba[2] == pytest.approx(bb[2], abs=1e-12)
        assert ba[3] == pytest.approx(bb[3], abs=1e-12)
        assert ba[1] == pytest.approx(bb[1], abs=1e-12)
        assert pa.map_ax.get_xlim() == pb.map_ax.get_xlim()
        assert pa.map_ax.get_ylim() == pb.map_ax.get_ylim()
        assert pa.map_ax.get_aspect() == pb.map_ax.get_aspect()
        for panel in (pa, pb):
            assert any(line.get_gid() == "map-scale-bar" for line in panel.map_ax.lines)
            assert any(getattr(x, "get_gid", lambda: None)() == "map-north-arrow" for x in panel.map_ax.texts)
        assert style.geometry.outer_left_fraction == style.geometry.outer_right_fraction == 0.08
    finally:
        plt.close(grid.figure)


def test_f3_dedicated_legend_band_clearance_and_equal_lower_maps(context) -> None:
    _bundle, style, _auth, geo, specs = context
    spec = specs["F3"]
    opts = spec.renderer_options
    frame = _source("seasonality_spatial_organisation_presentation_source.csv")
    layout = style.grid_for(spec.layout_role)
    grid = build_grid_figure(layout, figure_size=style.dimensions_for(spec.layout_role))
    apply_grid_spacing(grid.figure, layout, style=style)
    banded = build_vertical_band_axes(
        grid.figure, grid.data_axes[0],
        band_fraction=float(opts["seasonality_legend_band_fraction"]),
        gap_fraction=float(opts["seasonality_legend_gap_fraction"]),
        horizontal_inset_fraction=float(opts["seasonality_horizontal_inset_fraction"]),
        gid_prefix="f3-seasonality",
    )
    p0 = frame.loc[frame["panel"].eq("acz_seasonality")]
    draw_seasonality_lines(banded.plot_ax, p0, xlabel=str(spec.panel_xlabels[0]), ylabel=str(spec.panel_ylabels[0]), style=style, legend_ax=banded.band_ax, legend_ncol=int(opts["seasonality_legend_ncol"]))
    p1 = frame.loc[frame["panel"].eq("district_departure")]
    p2 = frame.loc[frame["panel"].eq("local_moran")]
    m1 = draw_choropleth_axis(grid.figure, grid.data_axes[1], geo, p1, value="value", colorbar_label=str(opts["panel_colorbar_labels"][1]), style=style, cmap=str(opts["panel_colormaps"][1]))
    m2 = draw_categorical_axis(grid.figure, grid.data_axes[2], geo, p2, category="local_class", style=style)
    try:
        grid.figure.canvas.draw()
        renderer = grid.figure.canvas.get_renderer()
        xlabel_box = banded.plot_ax.xaxis.label.get_window_extent(renderer)
        legend = banded.band_ax.get_legend()
        assert legend is not None
        legend_box = legend.get_window_extent(renderer)
        assert not _intersects(xlabel_box, legend_box)
        lower_top = max(m1.map_ax.get_window_extent(renderer).y1, m2.map_ax.get_window_extent(renderer).y1)
        assert legend_box.y0 > lower_top
        b1, b2 = m1.map_ax.get_position().bounds, m2.map_ax.get_position().bounds
        assert b1[2] == pytest.approx(b2[2], abs=1e-12)
        assert b1[3] == pytest.approx(b2[3], abs=1e-12)
        assert b1[1] == pytest.approx(b2[1], abs=1e-12)
        assert m1.map_ax.get_xlim() == m2.map_ax.get_xlim()
        assert m1.map_ax.get_ylim() == m2.map_ax.get_ylim()
        assert style.circular_mean_month_display.legend_title in legend.get_title().get_text()
    finally:
        plt.close(grid.figure)


def test_f4_five_year_labels_shared_ylabel_clearance_and_key_semantics(context) -> None:
    _bundle, style, _auth, _geo, specs = context
    spec = specs["F4"]
    opts = spec.renderer_options
    frame = _source("annual_trend_source.csv")
    layout = style.grid_for(spec.layout_role)
    grid = build_grid_figure(layout, figure_size=style.dimensions_for(spec.layout_role))
    apply_grid_spacing(grid.figure, layout, style=style)
    groups = list(opts["panel_order"])
    trajectory_styles = opts["trajectory_styles"]
    for idx, (ax, key) in enumerate(zip(grid.data_axes, groups, strict=True)):
        panel = frame.loc[frame[str(opts["group"])].astype(str).eq(str(key))]
        draw_trajectory_panel(
            ax, panel, x=str(opts["x"]), y=str(opts["y"]), slope=str(opts["slope"]),
            annotation_fields=tuple(str(x) for x in opts["annotation_fields"]),
            group_label=str(key), xlabel=str(spec.panel_xlabels[idx]), ylabel="", style=style,
            trajectory_styles=trajectory_styles,
        )
    aux = grid.auxiliary_axes[str(opts["auxiliary_key"]["cell_id"])]
    draw_shared_trajectory_key(aux, entries=opts["auxiliary_key"]["entries"], style=style, trajectory_styles=trajectory_styles)
    shared = grid.figure.text(float(opts["shared_ylabel_x_fraction"]), 0.5, str(spec.ylabel), rotation=90, ha="center", va="center", fontsize=style.axis_label_font, gid="f4-shared-ylabel")
    add_panel_labels(grid.data_axes, style=style)
    apply_axis_label_padding(grid.data_axes, style=style)
    try:
        grid.figure.canvas.draw()
        renderer = grid.figure.canvas.get_renderer()
        assert len(grid.data_axes) == 5
        assert all(ax.get_xlabel() == "Year" for ax in grid.data_axes)
        assert not any(t.get_text() == "(f)" for ax in grid.figure.axes for t in ax.texts)
        canvas = grid.figure.get_window_extent(renderer)
        for ax in grid.data_axes:
            xb = ax.xaxis.label.get_window_extent(renderer)
            assert canvas.contains(xb.x0, xb.y0) and canvas.contains(xb.x1, xb.y1)
        tick_boxes = [tick.label1.get_window_extent(renderer) for ax in (grid.data_axes[0], grid.data_axes[2], grid.data_axes[4]) for tick in ax.yaxis.get_major_ticks() if tick.label1.get_text()]
        shared_box = shared.get_window_extent(renderer)
        assert all(not _intersects(shared_box, box) for box in tick_boxes)
        first = grid.data_axes[0]
        observed = next(line for line in first.lines if line.get_gid() == "f4-observed-series")
        slope = next(line for line in first.lines if line.get_gid() == "f4-sen-slope")
        legend = aux.get_legend(); assert legend is not None
        handles = legend.legend_handles
        assert handles[0].get_color() == observed.get_color()
        assert handles[1].get_color() == slope.get_color()
        assert not aux.axison
    finally:
        plt.close(grid.figure)


def test_f5_state_legend_and_effect_gutter_are_contained(context) -> None:
    _bundle, style, _auth, geo, specs = context
    spec = specs["F5"]
    opts = spec.renderer_options
    frame = _source("cross_product_observability_presentation_source.csv")
    layout = style.grid_for(spec.layout_role)
    grid = build_grid_figure(layout, figure_size=style.dimensions_for(spec.layout_role))
    apply_grid_spacing(grid.figure, layout, style=style)
    p0 = frame.loc[frame["panel"].eq("mismatch_geography")]
    map_panel = draw_choropleth_axis(grid.figure, grid.data_axes[0], geo, p0, value="value", colorbar_label=str(opts["panel_colorbar_labels"][0]), style=style, cmap=str(opts["panel_colormaps"][0]))
    p1 = frame.loc[frame["panel"].eq("four_state_correspondence")]
    state_band = build_vertical_band_axes(grid.figure, grid.data_axes[1], band_fraction=float(opts["state_legend_band_fraction"]), gap_fraction=float(opts["state_legend_gap_fraction"]), gid_prefix="f5-four-state")
    state_order = list(dict.fromkeys(p1["state"].astype(str).tolist()))
    draw_stacked_proportions(state_band.plot_ax, p1, category="parent_code", state="state", proportion="proportion", state_order=state_order, ylabel=str(spec.panel_ylabels[1]), style=style, legend_ax=state_band.band_ax, display_aliases=dict(opts["state_display_aliases"]), legend_ncol=int(opts["state_legend_ncol"]))
    p2 = frame.loc[frame["panel"].eq("focal_adjusted_associations")]
    gutter = build_horizontal_gutter_axes(grid.figure, grid.data_axes[2], label_fraction=float(opts["effect_label_gutter_fraction"]), gap_fraction=float(opts["effect_label_gap_fraction"]), gid_prefix="f5-focal-effects")
    draw_coefficient_or_plot(
        gutter.plot_ax,
        p2,
        xlabel=str(spec.panel_xlabels[2]),
        style=style,
        label="term",
        estimate="adjusted_or",
        low="or_lower_95",
        high="or_upper_95",
        label_ax=gutter.label_ax,
        display_aliases=dict(opts["effect_display_aliases"]),
        vertical_padding_rows=style.geometry.effect_vertical_padding_rows,
    )
    try:
        grid.figure.canvas.draw()
        renderer = grid.figure.canvas.get_renderer()
        original_b = state_band.original_cell_bounds
        b_left = original_b[0] * grid.figure.bbox.width
        b_right = (original_b[0] + original_b[2]) * grid.figure.bbox.width
        legend = state_band.band_ax.get_legend(); assert legend is not None
        lb = legend.get_window_extent(renderer)
        assert lb.x0 >= b_left - 1 and lb.x1 <= b_right + 1
        assert {t.get_text() for t in legend.get_texts()} == {"Both zero", "MCD64A1 only", "VIIRS only", "Both positive"}
        original_c = gutter.original_cell_bounds
        c_left = original_c[0] * grid.figure.bbox.width
        c_right = (original_c[0] + original_c[2]) * grid.figure.bbox.width
        map_box = map_panel.map_ax.get_window_extent(renderer)
        effect_labels = [t for t in gutter.label_ax.texts if str(t.get_gid()).startswith("f5-effect-label-")]
        assert len(effect_labels) == 2
        for text in effect_labels:
            box = text.get_window_extent(renderer)
            assert box.x0 >= c_left - 1 and box.x1 <= c_right + 1
            assert not _intersects(box, map_box)
        assert len(p2) == 2
    finally:
        plt.close(grid.figure)


def test_s1_heatmap_xlabel_and_colourbar_have_positive_clearance(context) -> None:
    _bundle, style, _auth, _geo, specs = context
    spec = specs["S1"]
    frame = _source("district_seasonal_diagnostics_source.csv")
    pivot, summary = district_seasonal_components(frame)
    layout = style.grid_for(spec.layout_role)
    grid = build_grid_figure(layout, figure_size=style.dimensions_for(spec.layout_role))
    apply_grid_spacing(grid.figure, layout, style=style)
    banded = build_vertical_band_axes(
        grid.figure,
        grid.data_axes[0],
        band_fraction=style.geometry.heatmap_colorbar_band_fraction,
        gap_fraction=style.geometry.heatmap_colorbar_gap_fraction,
        gid_prefix="s1-heatmap",
    )
    image = draw_district_seasonal_heatmap(banded.plot_ax, pivot, xlabel=str(spec.panel_xlabels[0]), ylabel=str(spec.panel_ylabels[0]))
    banded.band_ax.set_axis_on(); banded.band_ax.set_yticks([])
    cb = grid.figure.colorbar(image, cax=banded.band_ax, orientation="horizontal"); cb.set_label("Share of district long-run burned area")
    draw_circular_mean_timing(grid.data_axes[1], summary, xlabel=str(spec.panel_xlabels[1]), ylabel=str(spec.panel_ylabels[1]), style=style)
    draw_resultant_length_by_group(grid.data_axes[2], summary, xlabel=str(spec.panel_xlabels[2]), ylabel=str(spec.panel_ylabels[2]))
    apply_axis_label_padding((banded.plot_ax, grid.data_axes[1], grid.data_axes[2]), style=style)
    ensure_vertical_band_xlabel_clearance(grid.figure, banded)
    try:
        grid.figure.canvas.draw()
        renderer = grid.figure.canvas.get_renderer()
        x_box = banded.plot_ax.xaxis.label.get_window_extent(renderer)
        cb_box = banded.band_ax.get_window_extent(renderer)
        assert not _intersects(x_box, cb_box)
        assert x_box.y0 > cb_box.y1
        assert grid.data_axes[1].get_xlabel() == style.circular_mean_month_display.axis_label
    finally:
        plt.close(grid.figure)


def test_target_figures_keep_symmetric_canvas_geometry_and_clear_export_border(context) -> None:
    bundle, style, auth, _geo, specs = context
    source_map = {
        "F2": "long_run_spatial_rate_presentation_source.csv",
        "F3": "seasonality_spatial_organisation_presentation_source.csv",
        "F4": "annual_trend_source.csv",
        "F5": "cross_product_observability_presentation_source.csv",
        "S1": "district_seasonal_diagnostics_source.csv",
    }
    from rp1_analysis_v1.publication import _render
    assert style.geometry.outer_left_fraction == style.geometry.outer_right_fraction
    for fid, filename in source_map.items():
        spec = specs[fid]
        frame = _source(filename).loc[:, list(spec.required_columns)]
        rendered = _render(spec, frame, authorities=auth, style=style)
        assert (rendered.width_in, rendered.height_in) == pytest.approx((20 / 2.54, 15 / 2.54), abs=1e-12)
        image = np.asarray(Image.open(io.BytesIO(rendered.png)).convert("RGB"))
        assert image.shape[:2] == (1772, 2362)
        # Exact canvas must remain visually clear at all four physical page edges.
        edge = np.concatenate((image[:2].reshape(-1, 3), image[-2:].reshape(-1, 3), image[:, :2].reshape(-1, 3), image[:, -2:].reshape(-1, 3)))
        assert np.all(edge >= 248), fid



def test_final_target_renders_keep_exact_png_and_pdf_canvas(context) -> None:
    bundle, style, auth, _geo, specs = context
    source_map = {
        "F2": "long_run_spatial_rate_presentation_source.csv",
        "F3": "seasonality_spatial_organisation_presentation_source.csv",
        "F4": "annual_trend_source.csv",
        "F5": "cross_product_observability_presentation_source.csv",
        "S1": "district_seasonal_diagnostics_source.csv",
    }
    from rp1_analysis_v1.publication import _render

    for fid, filename in source_map.items():
        spec = specs[fid]
        frame = _source(filename).loc[:, list(spec.required_columns)]
        rendered = _render(spec, frame, authorities=auth, style=style)
        assert (rendered.width_in, rendered.height_in) == pytest.approx((20 / 2.54, 15 / 2.54), abs=1e-12)
        assert Image.open(BytesIO(rendered.png)).size == (2362, 1772)
        page = PdfReader(BytesIO(rendered.pdf)).pages[0]
        assert float(page.mediabox.width) == pytest.approx(566.9291338583, abs=1e-6)
        assert float(page.mediabox.height) == pytest.approx(425.1968503937, abs=1e-6)


def test_governed_map_colourbar_band_height_is_realised_in_f2_and_f5(context) -> None:
    _bundle, style, _auth, geo, specs = context
    cases = (
        ("F2", "long_run_spatial_rate_presentation_source.csv", "direct_acz_long_run_rate", True),
        ("F5", "cross_product_observability_presentation_source.csv", "mismatch_geography", False),
    )
    for fid, filename, panel_name, is_acz in cases:
        spec = specs[fid]
        frame = _source(filename)
        p = frame.loc[frame["panel"].eq(panel_name)]
        layout = style.grid_for(spec.layout_role)
        grid = build_grid_figure(layout, figure_size=style.dimensions_for(spec.layout_role))
        apply_grid_spacing(grid.figure, layout, style=style)
        draw = draw_acz_choropleth_axis if is_acz else draw_choropleth_axis
        panel = draw(
            grid.figure,
            grid.data_axes[0],
            geo,
            p,
            value="value",
            colorbar_label=str(spec.renderer_options["panel_colorbar_labels"][0]),
            style=style,
            **({} if is_acz else {"cmap": str(spec.renderer_options["panel_colormaps"][0])}),
        )
        try:
            original_h = panel.original_cell_bounds[3]
            total = (
                style.geometry.map_height_ratio
                + style.geometry.map_legend_band_height
                + style.geometry.map_colourbar_band_height
                + 2 * style.geometry.map_inter_band_spacing
            )
            expected = original_h * style.geometry.map_colourbar_band_height / total
            assert panel.colorbar_or_categorical_key_ax.get_position().height == pytest.approx(expected, abs=1e-12)
            assert panel.map_ax.get_position().height > panel.colorbar_or_categorical_key_ax.get_position().height * 10
            for ax in (panel.map_ax, panel.support_or_status_legend_ax, panel.colorbar_or_categorical_key_ax):
                x0, y0, w, h = ax.get_position().bounds
                assert 0 <= x0 <= 1 and 0 <= y0 <= 1
                assert x0 + w <= 1 and y0 + h <= 1
        finally:
            plt.close(grid.figure)


def test_f5_effect_labels_are_fully_contained_and_scientific_x_data_are_unchanged(context) -> None:
    _bundle, style, _auth, _geo, specs = context
    spec = specs["F5"]
    opts = spec.renderer_options
    p2 = _source("cross_product_observability_presentation_source.csv").loc[
        lambda x: x["panel"].eq("focal_adjusted_associations")
    ].reset_index(drop=True)
    layout = style.grid_for(spec.layout_role)
    grid = build_grid_figure(layout, figure_size=style.dimensions_for(spec.layout_role))
    apply_grid_spacing(grid.figure, layout, style=style)
    gutter = build_horizontal_gutter_axes(
        grid.figure,
        grid.data_axes[2],
        label_fraction=float(opts["effect_label_gutter_fraction"]),
        gap_fraction=float(opts["effect_label_gap_fraction"]),
        gid_prefix="f5-focal-effects",
    )
    draw_coefficient_or_plot(
        gutter.plot_ax,
        p2,
        xlabel=str(spec.panel_xlabels[2]),
        style=style,
        label="term",
        estimate="adjusted_or",
        low="or_lower_95",
        high="or_upper_95",
        label_ax=gutter.label_ax,
        display_aliases=dict(opts["effect_display_aliases"]),
        vertical_padding_rows=style.geometry.effect_vertical_padding_rows,
    )
    try:
        grid.figure.canvas.draw()
        renderer = grid.figure.canvas.get_renderer()
        label_box = gutter.label_ax.get_window_extent(renderer)
        labels = sorted(
            (t for t in gutter.label_ax.texts if str(t.get_gid()).startswith("f5-effect-label-")),
            key=lambda t: str(t.get_gid()),
        )
        assert [t.get_text() for t in labels] == [
            "VIIRS detection count\n(per doubling)",
            "Mean VIIRS FRP\n(per doubling)",
        ]
        for text in labels:
            box = text.get_window_extent(renderer)
            assert box.x0 >= label_box.x0 - 1 and box.x1 <= label_box.x1 + 1
            assert box.y0 >= label_box.y0 - 1 and box.y1 <= label_box.y1 + 1
        points = np.asarray(gutter.plot_ax.lines[0].get_xdata(), dtype=float)
        assert np.array_equal(points, p2["adjusted_or"].to_numpy(float))
        segments = gutter.plot_ax.collections[0].get_segments()
        assert len(segments) == len(p2)
        for seg, lo, hi in zip(segments, p2["or_lower_95"], p2["or_upper_95"], strict=True):
            xs = np.asarray(seg)[:, 0]
            assert xs.min() == pytest.approx(float(lo), abs=1e-12)
            assert xs.max() == pytest.approx(float(hi), abs=1e-12)
    finally:
        plt.close(grid.figure)


def test_s1_heatmap_plotting_area_increases_against_pre_refinement_geometry(context) -> None:
    _bundle, style, _auth, _geo, specs = context
    spec = specs["S1"]
    layout = style.grid_for(spec.layout_role)

    governed = build_grid_figure(layout, figure_size=style.dimensions_for(spec.layout_role))
    legacy = build_grid_figure(layout, figure_size=style.dimensions_for(spec.layout_role))
    try:
        apply_grid_spacing(governed.figure, layout, style=style)
        apply_grid_spacing(legacy.figure, layout, style=style)
        g = build_vertical_band_axes(
            governed.figure,
            governed.data_axes[0],
            band_fraction=style.geometry.heatmap_colorbar_band_fraction,
            gap_fraction=style.geometry.heatmap_colorbar_gap_fraction,
            gid_prefix="s1-governed",
        )
        old = build_vertical_band_axes(
            legacy.figure,
            legacy.data_axes[0],
            band_fraction=0.13,
            gap_fraction=0.22,
            gid_prefix="s1-pre-refinement",
        )
        assert g.plot_ax.get_position().height > old.plot_ax.get_position().height
        assert g.band_ax.get_position().height < old.band_ax.get_position().height
        assert style.geometry.heatmap_colorbar_band_fraction == pytest.approx(0.07)
        assert style.geometry.heatmap_colorbar_gap_fraction == pytest.approx(0.10)
    finally:
        plt.close(governed.figure)
        plt.close(legacy.figure)


def test_target_publication_source_bytes_match_governed_manifest() -> None:
    manifest = json.loads((PUB / "SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
    names = {
        "long_run_spatial_rate_presentation_source",
        "seasonality_spatial_organisation_presentation_source",
        "annual_trend_source",
        "cross_product_observability_presentation_source",
        "district_seasonal_diagnostics_source",
    }
    for name in names:
        entry = manifest["sources"][name]
        path = ROOT / entry["path"]
        assert path.exists()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]
        assert path.stat().st_size == entry["size_bytes"]


def test_actual_target_figures_keep_all_visible_text_inside_canvas(context, monkeypatch) -> None:
    _bundle, style, auth, _geo, specs = context
    import rp1_analysis_v1.publication as publication
    from rp1_analysis_v1.figures import export_figure as real_export

    source_map = {
        "F2": "long_run_spatial_rate_presentation_source.csv",
        "F3": "seasonality_spatial_organisation_presentation_source.csv",
        "F4": "annual_trend_source.csv",
        "F5": "cross_product_observability_presentation_source.csv",
        "S1": "district_seasonal_diagnostics_source.csv",
    }
    inspected: list[str] = []

    def _inspecting_export(fig, render_style):
        ensure_axis_labels_inside_canvas(fig, tuple(fig.axes))
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        canvas = fig.get_window_extent(renderer)
        texts = []
        for ax in fig.axes:
            texts.extend([ax.xaxis.label, ax.yaxis.label, *ax.texts])
            x0, x1 = sorted(ax.get_xlim())
            y0, y1 = sorted(ax.get_ylim())
            for tick in ax.xaxis.get_major_ticks():
                if x0 <= float(tick.get_loc()) <= x1:
                    texts.append(tick.label1)
                    texts.append(tick.label2)
            for tick in ax.yaxis.get_major_ticks():
                if y0 <= float(tick.get_loc()) <= y1:
                    texts.append(tick.label1)
                    texts.append(tick.label2)
            legend = ax.get_legend()
            if legend is not None:
                texts.extend(legend.get_texts())
                texts.append(legend.get_title())
        for text in texts:
            if not text.get_visible() or not str(text.get_text()).strip():
                continue
            box = text.get_window_extent(renderer)
            assert box.x0 >= canvas.x0 - 1.0, (text.get_text(), box.bounds, canvas.bounds)
            assert box.y0 >= canvas.y0 - 1.0, (text.get_text(), box.bounds, canvas.bounds)
            assert box.x1 <= canvas.x1 + 1.0, (text.get_text(), box.bounds, canvas.bounds)
            assert box.y1 <= canvas.y1 + 1.0, (text.get_text(), box.bounds, canvas.bounds)
        for ax in fig.axes:
            if "map-viewport" in str(ax.get_gid()):
                box = ax.get_window_extent(renderer)
                assert box.x0 >= canvas.x0 and box.y0 >= canvas.y0
                assert box.x1 <= canvas.x1 and box.y1 <= canvas.y1
        inspected.append(str(getattr(fig, "_rp1_current_figure_id", "unknown")))
        return real_export(fig, render_style)

    monkeypatch.setattr(publication, "export_figure", _inspecting_export)
    for fid, filename in source_map.items():
        spec = specs[fid]
        frame = _source(filename).loc[:, list(spec.required_columns)]
        publication._render(spec, frame, authorities=auth, style=style)
    assert len(inspected) == len(source_map)
