from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.data_io import load_data_authorities
from rp1_analysis_v1.grid_rendering import add_panel_labels, apply_grid_spacing, build_grid_figure
from rp1_analysis_v1.mapping import (
    _build_choropleth_figure,
    cluster_maps_grid,
    draw_choropleth_axis,
    prepare_geography,
)
from rp1_analysis_v1.paths import ProjectPaths
from rp1_analysis_v1.style import PublicationStyle


def _objects():
    paths = ProjectPaths.discover()
    bundle = load_configuration_bundle(paths.root / "config")
    style = PublicationStyle.from_contract(bundle.figure)
    auth = load_data_authorities(paths, bundle.data_schema)
    geo = prepare_geography(auth.district_geometry, auth.acz_geometry)
    return bundle, style, geo


def _base_frame(geo):
    ids = geo.districts["dist_id"].astype(str).tolist()
    return pd.DataFrame({
        "unit_id": ids,
        "support_status": [
            "excluded" if i == 0 else ("valid_zero" if i == 1 else "valid_nonzero")
            for i in range(len(ids))
        ],
        "value": [np.nan if i == 0 else (0.0 if i == 1 else float(i)) for i in range(len(ids))],
        "exclusion_reasons": ["synthetic" if i == 0 else "" for i in range(len(ids))],
    })


def test_single_map_scale_bar_is_lower_right_and_colourbar_labelled() -> None:
    _, style, geo = _objects()
    fig, ax = _build_choropleth_figure(
        geo,
        _base_frame(geo),
        value="value",
        title="",
        colorbar_label="Burned area rate (km² per 100 km²)",
        style=style,
    )
    line = next(x for x in ax.lines if x.get_gid() == "map-scale-bar")
    x = np.asarray(line.get_xdata(), dtype=float)
    xmin, _, xmax, _ = geo.extent
    assert x.mean() > xmin + 0.5 * (xmax - xmin)
    colorbar_ax = next(a for a in fig.axes if a.get_gid() == "map-colorbar")
    assert colorbar_ax.get_xlabel() == "Burned area rate (km² per 100 km²)"
    import matplotlib.pyplot as plt
    plt.close(fig)


def test_non_vertical_two_map_grid_has_shared_extent_below_colourbars_and_labels() -> None:
    bundle, style, geo = _objects()
    layout = bundle.figure.grid_layouts["rectangular_one_by_two"]
    grid = build_grid_figure(layout, figure_size=style.dimensions_for("rectangular_one_by_two"))
    base = _base_frame(geo)
    other = base.copy()
    other["value"] = pd.to_numeric(other["value"], errors="coerce") * -1
    apply_grid_spacing(grid.figure, layout, style=style)
    panel_a = draw_choropleth_axis(
        grid.figure, grid.data_axes[0], geo, base,
        value="value", colorbar_label="Panel A scientific unit", style=style, cmap="viridis",
    )
    panel_b = draw_choropleth_axis(
        grid.figure, grid.data_axes[1], geo, other,
        value="value", colorbar_label="Panel B scientific unit", style=style, cmap="coolwarm",
    )
    map_axes = (panel_a.map_ax, panel_b.map_ax)
    add_panel_labels(map_axes, style=style)
    try:
        grid.figure.canvas.draw()
        bounds_a = panel_a.map_ax.get_position().bounds
        bounds_b = panel_b.map_ax.get_position().bounds
        assert bounds_a[0] < bounds_b[0]
        assert bounds_a[2:] == pytest.approx(bounds_b[2:], abs=1e-12)
        assert bounds_a[1] == pytest.approx(bounds_b[1], abs=1e-12)
        assert panel_a.map_ax.get_xlim() == panel_b.map_ax.get_xlim()
        assert panel_a.map_ax.get_ylim() == panel_b.map_ax.get_ylim()
        labels = {
            text.get_text()
            for ax in map_axes
            for text in ax.texts
            if text.get_gid() and str(text.get_gid()).startswith("panel-marker")
        }
        assert labels == {"(a)", "(b)"}
        cbs = [a for a in grid.figure.axes if str(a.get_gid()).startswith("map-colorbar-grid")]
        assert {a.get_xlabel() for a in cbs} == {"Panel A scientific unit", "Panel B scientific unit"}
        for ax in map_axes:
            assert any(line.get_gid() == "map-scale-bar" for line in ax.lines)
    finally:
        import matplotlib.pyplot as plt
        plt.close(grid.figure)


def test_cluster_panels_use_generic_grid_and_categorical_key_without_colourbar() -> None:
    bundle, style, geo = _objects()
    base = _base_frame(geo)
    p1 = base.copy(); p1["product"] = "mcd64a1"; p1["cluster_ids"] = ""
    p2 = base.copy(); p2["product"] = "viirs"; p2["cluster_ids"] = ""
    rendered = cluster_maps_grid(
        geo,
        pd.concat([p1, p2], ignore_index=True),
        product_column="product",
        panel_order=["mcd64a1", "viirs"],
        style=style,
        layout=bundle.figure.grid_layouts["rectangular_one_by_two"],
        figure_size=style.dimensions_for("rectangular_one_by_two"),
    )
    assert len(rendered.png) > 10_000
    assert len(rendered.pdf) > 10_000


def test_continuous_map_support_key_and_colourbar_use_separate_below_axis_bands() -> None:
    bundle, style, geo = _objects()
    layout = bundle.figure.grid_layouts["rectangular_top_span_two_bottom"]
    grid = build_grid_figure(layout, figure_size=style.dimensions_for("rectangular_top_span_two_bottom"))
    frame = _base_frame(geo)
    apply_grid_spacing(grid.figure, layout, style=style)
    realised = draw_choropleth_axis(
        grid.figure,
        grid.data_axes[1],
        geo,
        frame,
        value="value",
        colorbar_label="Scientific continuous value",
        style=style,
        cmap="coolwarm",
    )
    try:
        before = realised.map_ax.get_position().bounds
        grid.figure.canvas.draw()
        legend = realised.support_or_status_legend_ax.get_legend()
        assert legend is not None
        colorbar_ax = realised.colorbar_or_categorical_key_ax
        renderer = grid.figure.canvas.get_renderer()
        legend_box = legend.get_window_extent(renderer=renderer)
        colorbar_box = colorbar_ax.get_window_extent(renderer=renderer)
        assert legend_box.y0 >= colorbar_box.y1
        assert realised.map_ax.get_position().bounds == pytest.approx(before, abs=1e-12)
    finally:
        import matplotlib.pyplot as plt
        plt.close(grid.figure)
