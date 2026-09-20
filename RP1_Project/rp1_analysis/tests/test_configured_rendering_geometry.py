from __future__ import annotations

import inspect
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from rp1_analysis_v1.config import ConfigurationError, load_configuration_bundle, load_figure_contract
from rp1_analysis_v1.data_io import load_data_authorities
from rp1_analysis_v1.grid_rendering import apply_grid_spacing, build_grid_figure
from rp1_analysis_v1.mapping import (
    draw_categorical_axis,
    draw_choropleth_axis,
    prepare_geography,
)
from rp1_analysis_v1.paths import ProjectPaths
from rp1_analysis_v1.style import PublicationStyle

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/figure_contract.yml"


def _mutated(tmp_path: Path, mutate) -> Path:
    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    mutate(raw)
    path = tmp_path / "figure_contract.yml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def _objects():
    paths = ProjectPaths.discover()
    bundle = load_configuration_bundle(paths.root / "config")
    style = PublicationStyle.from_contract(bundle.figure)
    auth = load_data_authorities(paths, bundle.data_schema)
    geography = prepare_geography(auth.district_geometry, auth.acz_geometry)
    return bundle, style, geography


def _continuous_frame(geography):
    ids = geography.districts["dist_id"].astype(str).tolist()
    return pd.DataFrame(
        {
            "unit_id": ids,
            "support_status": [
                "excluded" if i == 0 else ("valid_zero" if i == 1 else "valid_nonzero")
                for i in range(len(ids))
            ],
            "value": [np.nan if i == 0 else (0.0 if i == 1 else float(i)) for i in range(len(ids))],
            "exclusion_reasons": ["fixture" if i == 0 else "" for i in range(len(ids))],
        }
    )


def _categorical_frame(geography):
    ids = geography.districts["dist_id"].astype(str).tolist()
    classes = ("HH", "LL", "HL", "LH", "NS", "ISLAND")
    return pd.DataFrame(
        {
            "unit_id": ids,
            "support_status": ["excluded" if i == 0 else "valid_nonzero" for i in range(len(ids))],
            "local_class": ["NS" if i == 0 else classes[(i - 1) % len(classes)] for i in range(len(ids))],
            "exclusion_reasons": ["fixture" if i == 0 else "" for i in range(len(ids))],
        }
    )


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda raw: raw.pop("publication_geometry"), "publication_geometry"),
        (lambda raw: raw.pop("semantic_styles"), "semantic_styles"),
        (lambda raw: raw["publication_geometry"]["outer_margins"].pop("right_fraction"), "right_fraction"),
        (lambda raw: raw["semantic_styles"]["excluded"].__setitem__("hatch", ""), "hatch must be non-empty"),
        (lambda raw: raw["semantic_styles"]["not_significant"].__setitem__("face", raw["semantic_styles"]["valid_zero"]["face"]), "must be visually distinct"),
    ],
)
def test_required_presentation_contract_keys_fail_closed(tmp_path: Path, mutate, message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        load_figure_contract(_mutated(tmp_path, mutate))


def test_semantic_support_palette_is_configuration_owned_and_distinct() -> None:
    contract = load_figure_contract(CONFIG)
    semantic = contract.semantic_styles
    assert semantic.valid_zero.face == "#BFD7EA"
    assert semantic.not_significant.face == "#D9D9D9"
    assert semantic.excluded.face == "#FFFFFF"
    assert len({semantic.valid_zero.face, semantic.not_significant.face, semantic.excluded.face}) == 3
    assert semantic.excluded.hatch == "////"
    style_source = (ROOT / "src/rp1_analysis_v1/style.py").read_text(encoding="utf-8")
    mapping_source = (ROOT / "src/rp1_analysis_v1/mapping.py").read_text(encoding="utf-8")
    for configured_colour in ("#BFD7EA", "#D9D9D9", "#D55E00", "#0072B2", "#CC79A7", "#009E73", "#F0E442"):
        assert configured_colour not in style_source
        assert configured_colour not in mapping_source


def test_local_moran_semantic_identities_are_fixed_and_not_auto_palette_owned() -> None:
    contract = load_figure_contract(CONFIG)
    local = contract.semantic_styles.local_moran
    assert tuple(local) == ("HH", "LL", "HL", "LH", "NS", "ISLAND")
    assert local["HH"].face == "#D55E00"
    assert local["LL"].face == "#0072B2"
    assert local["HL"].face == "#CC79A7"
    assert local["LH"].face == "#009E73"
    assert local["NS"].face == contract.semantic_styles.not_significant.face
    assert "tab20" not in inspect.getsource(draw_categorical_axis)


def test_governed_canvas_and_outer_horizontal_margins_are_exact_and_symmetric() -> None:
    contract = load_figure_contract(CONFIG)
    style = PublicationStyle.from_contract(contract)
    geometry = style.geometry
    assert (geometry.canvas_width_cm, geometry.canvas_height_cm, geometry.orientation) == (20.0, 15.0, "landscape")
    assert geometry.outer_left_fraction == geometry.outer_right_fraction == 0.08
    assert style.physical_inches_for("rectangular_landscape_20x15_cm") == pytest.approx((7.874015748031496, 5.905511811023622), abs=1e-12)

    layout = contract.grid_layouts["rectangular_one_by_two"]
    grid = build_grid_figure(layout, figure_size=style.physical_inches_for("rectangular_landscape_20x15_cm"))
    try:
        apply_grid_spacing(grid.figure, layout, style=style)
        left_edge = min(ax.get_position().x0 for ax in grid.data_axes)
        right_edge = max(ax.get_position().x1 for ax in grid.data_axes)
        assert left_edge == pytest.approx(geometry.outer_left_fraction, abs=1e-12)
        assert 1.0 - right_edge == pytest.approx(geometry.outer_right_fraction, abs=1e-12)
        assert abs((left_edge - (1.0 - right_edge)) * 200.0) <= 1.0
    finally:
        import matplotlib.pyplot as plt
        plt.close(grid.figure)


def test_paired_map_viewports_remain_equal_with_different_ancillary_content() -> None:
    bundle, style, geography = _objects()
    layout = bundle.figure.grid_layouts["rectangular_one_by_two"]
    grid = build_grid_figure(layout, figure_size=style.physical_inches_for("rectangular_landscape_20x15_cm"))
    apply_grid_spacing(grid.figure, layout, style=style)
    continuous = _continuous_frame(geography)
    categorical = _categorical_frame(geography)
    panel_a = draw_choropleth_axis(
        grid.figure,
        grid.data_axes[0],
        geography,
        continuous,
        value="value",
        colorbar_label="A deliberately long scientific colourbar label that exercises ancillary layout",
        style=style,
        cmap="coolwarm",
    )
    panel_b = draw_categorical_axis(
        grid.figure,
        grid.data_axes[1],
        geography,
        categorical,
        category="local_class",
        style=style,
    )
    try:
        grid.figure.canvas.draw()
        a = panel_a.map_ax.get_position().bounds
        b = panel_b.map_ax.get_position().bounds
        assert a[2] == pytest.approx(b[2], abs=1e-12)
        assert a[3] == pytest.approx(b[3], abs=1e-12)
        assert a[1] == pytest.approx(b[1], abs=1e-12)
        assert panel_a.map_ax.get_xlim() == panel_b.map_ax.get_xlim()
        assert panel_a.map_ax.get_ylim() == panel_b.map_ax.get_ylim()

        before_a = panel_a.map_ax.get_position().bounds
        before_b = panel_b.map_ax.get_position().bounds
        panel_a.support_or_status_legend_ax.text(
            0.5, 0.5, "Very long support/status annotation " * 8, ha="center", va="center", wrap=True
        )
        panel_b.colorbar_or_categorical_key_ax.text(
            0.5, 0.05, "Very long categorical-key annotation " * 8, ha="center", va="bottom", wrap=True
        )
        grid.figure.canvas.draw()
        assert panel_a.map_ax.get_position().bounds == pytest.approx(before_a, abs=1e-12)
        assert panel_b.map_ax.get_position().bounds == pytest.approx(before_b, abs=1e-12)
    finally:
        import matplotlib.pyplot as plt
        plt.close(grid.figure)


def test_active_figure_layouts_are_rectangular_and_no_stale_vertical_authority_is_reintroduced() -> None:
    contract = load_figure_contract(CONFIG)
    for figure in contract.figures:
        assert "vertical" not in figure.layout_role.casefold()
    source = (ROOT / "src/rp1_analysis_v1/grid_rendering.py").read_text(encoding="utf-8").casefold()
    assert "vertical_layout" not in source
    assert "five_panel_vertical" not in source


def test_presentation_modules_do_not_own_scientific_contract_parameters() -> None:
    figure_raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    serialised = yaml.safe_dump(figure_raw, sort_keys=False).casefold()
    scientific_tokens = (
        "9999",
        "20260822",
        "firth",
        "morel",
        "mann-kendall",
        "bandwidth",
        "saTScan".casefold(),
    )
    for token in scientific_tokens:
        assert token not in serialised
    for name in ("grid_rendering.py", "mapping.py", "style.py"):
        source = (ROOT / f"src/rp1_analysis_v1/{name}").read_text(encoding="utf-8").casefold()
        assert "analysis_contract.yml" not in source
        assert "method_authorities.yml" not in source
