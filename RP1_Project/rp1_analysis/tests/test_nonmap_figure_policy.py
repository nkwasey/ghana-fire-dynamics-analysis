from __future__ import annotations

import pandas as pd

from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.figures import (
    coefficient_or_plot,
    draw_seasonality_lines,
    draw_shared_trajectory_key,
    draw_trajectory_panel,
)
from rp1_analysis_v1.grid_rendering import build_grid_figure
from rp1_analysis_v1.paths import ProjectPaths
from rp1_analysis_v1.style import PublicationStyle


def _style() -> PublicationStyle:
    paths = ProjectPaths.discover()
    return PublicationStyle.from_contract(load_configuration_bundle(paths.root / "config").figure)


def test_seasonality_draws_directly_into_parent_owned_axis() -> None:
    rows = []
    for name in ["A", "B"]:
        for month in range(1, 13):
            rows.append({
                "unit_name": name,
                "month": month,
                "value": float(month),
                "circular_mean_month": 1.5,
                "mean_resultant_length": 0.8,
            })
    style = _style()
    layout = style.grid_for("rectangular_one_by_two")
    grid = build_grid_figure(layout, figure_size=style.dimensions_for("rectangular_one_by_two"))
    try:
        before = len(grid.figure.axes)
        draw_seasonality_lines(
            grid.data_axes[0],
            pd.DataFrame(rows),
            xlabel="Month",
            ylabel="Mapped burned area",
            style=style,
        )
        assert len(grid.figure.axes) == before
        assert len(grid.data_axes[0].lines) == 2
    finally:
        import matplotlib.pyplot as plt
        plt.close(grid.figure)


def test_trajectory_axis_renderer_consumes_governed_sen_fields_without_ci_estimation() -> None:
    frame = pd.DataFrame({
        "year": [2001, 2002, 2003],
        "rate": [1.0, 0.9, 0.8],
        "slope": [-0.1, -0.1, -0.1],
        "sen_slope": [-0.1, -0.1, -0.1],
        "raw_p": [0.12, 0.12, 0.12],
        "bh_q": [0.25, 0.25, 0.25],
    })
    style = _style()
    layout = style.grid_for("single_panel")
    grid = build_grid_figure(layout, figure_size=style.dimensions_for("single_panel"))
    try:
        draw_trajectory_panel(
            grid.data_axes[0], frame,
            x="year", y="rate", slope="slope",
            annotation_fields=("sen_slope", "raw_p", "bh_q"),
            group_label="A", xlabel="Year", ylabel="Rate", style=style,
        )
        assert len(grid.data_axes[0].lines) == 2
        assert not grid.data_axes[0].collections
    finally:
        import matplotlib.pyplot as plt
        plt.close(grid.figure)


def test_pgee_forest_renderer_uses_configurable_columns() -> None:
    frame = pd.DataFrame({
        "order": [1, 2],
        "label": ["x", "y"],
        "or": [0.8, 1.2],
        "lo": [0.6, 1.0],
        "hi": [1.0, 1.5],
    })
    rendered = coefficient_or_plot(
        frame,
        title="",
        xlabel="Adjusted odds ratio",
        style=_style(),
        label="label",
        estimate="or",
        low="lo",
        high="hi",
        order="order",
    )
    assert len(rendered.png) > 1000


def test_shared_trajectory_key_matches_observed_and_slope_line_colours() -> None:
    import matplotlib.pyplot as plt

    style = _style()
    fig, ax = plt.subplots()
    try:
        draw_shared_trajectory_key(
            ax,
            entries=(
                {"label": "Annual fixed-support rate", "kind": "observed_series"},
                {"label": "Sen slope", "kind": "sen_slope"},
            ),
            style=style,
        )
        legend = ax.get_legend()
        assert legend is not None
        handles = legend.legend_handles
        colours = plt.rcParams["axes.prop_cycle"].by_key()["color"]
        assert handles[0].get_color() == colours[0]
        assert handles[1].get_color() == colours[1]
    finally:
        plt.close(fig)
