from __future__ import annotations

import inspect
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest
import yaml

from rp1_analysis_v1.config import ConfigurationError, load_figure_contract
from rp1_analysis_v1.figures import draw_coefficient_or_plot, export_figure
from rp1_analysis_v1.grid_rendering import apply_grid_spacing, build_grid_figure
from rp1_analysis_v1.mapping import build_map_panel_axes
from rp1_analysis_v1.publication import _district_seasonal_grid_render
from rp1_analysis_v1.style import PublicationStyle

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/figure_contract.yml"


def _mutated(tmp_path: Path, mutate) -> Path:
    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    mutate(raw)
    path = tmp_path / "figure_contract.yml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def _style(path: Path = CONFIG) -> PublicationStyle:
    return PublicationStyle.from_contract(load_figure_contract(path))


def _map_viewport_height(style: PublicationStyle) -> float:
    layout = load_figure_contract(CONFIG).grid_layouts["rectangular_one_by_two"]
    grid = build_grid_figure(layout, figure_size=style.physical_inches_for(layout.size_role))
    try:
        apply_grid_spacing(grid.figure, layout, style=style)
        panel = build_map_panel_axes(grid.figure, grid.data_axes[0], style=style)
        return float(panel.map_ax.get_position().height)
    finally:
        plt.close(grid.figure)


def test_governed_publication_geometry_values_are_loaded_from_config() -> None:
    style = _style()
    geometry = style.geometry
    assert geometry.map_height_ratio == pytest.approx(1.0)
    assert geometry.map_legend_band_height == pytest.approx(0.13)
    assert geometry.map_colourbar_band_height == pytest.approx(0.08)
    assert geometry.map_inter_band_spacing == pytest.approx(0.04)
    assert geometry.heatmap_colorbar_band_fraction == pytest.approx(0.07)
    assert geometry.heatmap_colorbar_gap_fraction == pytest.approx(0.10)
    assert geometry.effect_vertical_padding_rows == pytest.approx(0.45)


def test_reducing_map_ancillary_bands_reclaims_map_viewport_height(tmp_path: Path) -> None:
    governed = _style()
    governed_height = _map_viewport_height(governed)

    enlarged = _style(
        _mutated(
            tmp_path,
            lambda raw: (
                raw["publication_geometry"]["map_panel"].__setitem__("colourbar_band_height", 0.16),
                raw["publication_geometry"]["map_panel"].__setitem__("inter_band_spacing", 0.06),
            ),
        )
    )
    enlarged_height = _map_viewport_height(enlarged)
    assert governed_height > enlarged_height


def test_map_panel_geometry_preserves_equal_aspect_and_pair_symmetry() -> None:
    contract = load_figure_contract(CONFIG)
    style = PublicationStyle.from_contract(contract)
    layout = contract.grid_layouts["rectangular_one_by_two"]
    grid = build_grid_figure(layout, figure_size=style.physical_inches_for(layout.size_role))
    try:
        apply_grid_spacing(grid.figure, layout, style=style)
        panels = tuple(build_map_panel_axes(grid.figure, ax, style=style) for ax in grid.data_axes)
        for panel in panels:
            panel.map_ax.set_aspect("equal")
        a = panels[0].map_ax.get_position().bounds
        b = panels[1].map_ax.get_position().bounds
        assert a[1] == pytest.approx(b[1], abs=1e-12)
        assert a[2] == pytest.approx(b[2], abs=1e-12)
        assert a[3] == pytest.approx(b[3], abs=1e-12)
        assert panels[0].map_ax.get_aspect() == pytest.approx(1.0)
        assert panels[1].map_ax.get_aspect() == pytest.approx(1.0)
    finally:
        plt.close(grid.figure)


@pytest.mark.parametrize(
    "mutate, message",
    [
        (
            lambda raw: raw["publication_geometry"]["map_panel"].__setitem__("colourbar_band_height", -0.01),
            "colourbar_band_height",
        ),
        (
            lambda raw: raw["publication_geometry"]["map_panel"].update(
                {"legend_band_height": 0.60, "colourbar_band_height": 0.35, "inter_band_spacing": 0.05}
            ),
            "ancillary bands",
        ),
        (
            lambda raw: raw["publication_geometry"].update(
                {"heatmap_colorbar_band_fraction": 0.70, "heatmap_colorbar_gap_fraction": 0.30}
            ),
            "heatmap colourbar band and gap",
        ),
        (
            lambda raw: raw["publication_geometry"].__setitem__("effect_vertical_padding_rows", -0.1),
            "effect_vertical_padding_rows",
        ),
        (
            lambda raw: raw["publication_geometry"].__setitem__("effect_vertical_padding_rows", float("inf")),
            "must be finite",
        ),
    ],
)
def test_invalid_publication_geometry_fails_closed(tmp_path: Path, mutate, message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        load_figure_contract(_mutated(tmp_path, mutate))


def test_s1_heatmap_band_and_gap_are_generic_publication_geometry_not_figure_magic() -> None:
    contract = load_figure_contract(CONFIG)
    s1 = next(item for item in contract.figures if item.figure_id == "S1")
    assert "heatmap_colorbar_band_fraction" not in s1.renderer_options
    assert "heatmap_colorbar_gap_fraction" not in s1.renderer_options
    source = inspect.getsource(_district_seasonal_grid_render)
    assert "style.geometry.heatmap_colorbar_band_fraction" in source
    assert "style.geometry.heatmap_colorbar_gap_fraction" in source


def test_effect_vertical_padding_is_config_driven_and_changes_only_y_geometry() -> None:
    style = _style()
    frame = pd.DataFrame(
        {
            "term": ["A", "B"],
            "adjusted_or": [1.25, 0.80],
            "or_lower_95": [1.05, 0.65],
            "or_upper_95": [1.50, 0.98],
        }
    )
    fig, axes = plt.subplots(1, 2)
    try:
        draw_coefficient_or_plot(
            axes[0], frame, xlabel="Adjusted odds ratio", style=style,
            label="term", estimate="adjusted_or", low="or_lower_95", high="or_upper_95",
            vertical_padding_rows=0.0,
        )
        draw_coefficient_or_plot(
            axes[1], frame, xlabel="Adjusted odds ratio", style=style,
            label="term", estimate="adjusted_or", low="or_lower_95", high="or_upper_95",
            vertical_padding_rows=style.geometry.effect_vertical_padding_rows,
        )
        x0 = np.asarray(axes[0].lines[0].get_xdata(), dtype=float)
        x1 = np.asarray(axes[1].lines[0].get_xdata(), dtype=float)
        assert np.array_equal(x0, x1)
        assert np.array_equal(x1, frame["adjusted_or"].to_numpy(float))
        assert axes[0].get_xlim() == pytest.approx(axes[1].get_xlim())
        assert axes[1].get_ylim() == pytest.approx((1.45, -0.45))
        assert abs(axes[1].get_ylim()[0] - axes[1].get_ylim()[1]) > abs(
            axes[0].get_ylim()[0] - axes[0].get_ylim()[1]
        )
    finally:
        plt.close(fig)


def test_governed_geometry_values_are_not_active_renderer_magic_constants() -> None:
    from rp1_analysis_v1 import figures, mapping, publication

    sources = (
        inspect.getsource(mapping.build_map_panel_axes),
        inspect.getsource(publication._district_seasonal_grid_render),
        inspect.getsource(figures.draw_coefficient_or_plot),
    )
    joined = "\n".join(sources)
    for literal in ("0.08", "0.04", "0.07", "0.10", "0.45"):
        assert literal not in joined


def test_governed_canvas_dimensions_remain_20x15_cm_300dpi() -> None:
    style = _style()
    assert style.geometry.canvas_width_cm == pytest.approx(20.0)
    assert style.geometry.canvas_height_cm == pytest.approx(15.0)
    assert style.dpi == 300
    assert style.raster_pixels_for_physical_role("rectangular_landscape_20x15_cm") == (2362, 1772)

    fig = plt.figure(figsize=style.physical_inches_for("rectangular_landscape_20x15_cm"))
    rendered = export_figure(fig, style)
    assert (rendered.width_in, rendered.height_in) == pytest.approx((20.0 / 2.54, 15.0 / 2.54), abs=1e-12)



def test_final_export_has_no_uncontrolled_tight_crop_resizing() -> None:
    from rp1_analysis_v1 import figures

    source = inspect.getsource(figures._export)
    assert "bbox_inches" not in source
    assert "savefig" in source
    assert "style.raster_pixels_for_inches" in source
