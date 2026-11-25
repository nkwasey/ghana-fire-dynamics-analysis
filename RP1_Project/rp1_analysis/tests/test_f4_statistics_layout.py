"""Regression coverage for notebook and presentation F4 layout semantics."""

from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from rp1_analysis_v1 import figures, publication
from rp1_analysis_v1.config import load_figure_contract
from rp1_analysis_v1.presentation import get_figure_spec, get_presentation_export_spec
from rp1_analysis_v1.presentation_export import _presentation_style
from rp1_analysis_v1.presentation_rq2 import render_rq2_five_acz_comparison
from rp1_analysis_v1.style import PublicationStyle


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("presentation", [False, True])
def test_f4_places_keyed_governed_statistics_below_legend(monkeypatch, presentation):
    contract = load_figure_contract(ROOT / "config" / "figure_contract.yml")
    spec = get_figure_spec("F4", contract)
    groups = tuple(spec.renderer_options["panel_order"])
    codes = ("CZ", "FZ", "GS", "SS", "TZ")
    statistics = [
        (-0.174, 0.2322, 0.2903),
        (-0.053, 0.6016, 0.6016),
        (-0.458, 0.0833, 0.2082),
        (-0.497, 0.1385, 0.2308),
        (-0.673, 0.0576, 0.2082),
    ]
    rates = [
        [3.0 + year % 10 for year in range(2001, 2025)],
        [10.0 + year % 5 for year in range(2001, 2025)],
        [58.9 if year == 2005 else 45.0 for year in range(2001, 2025)],
        [55.96 if year == 2005 else 42.0 for year in range(2001, 2025)],
        [23.0 + year % 8 for year in range(2001, 2025)],
    ]
    frame = pd.concat(
        [
            pd.DataFrame(
                {
                    "parent_code": code,
                    "parent_name": zone,
                    "year": range(2001, 2025),
                    "annual_rate": annual,
                    "sen_slope": slope,
                    "raw_p": p,
                    "bh_q": q,
                }
            )
            for code, zone, annual, (slope, p, q) in zip(codes, groups, rates, statistics, strict=True)
        ],
        ignore_index=True,
    )
    original = frame.copy(deep=True)
    title = get_presentation_export_spec("rq2_five_acz_comparison", contract).label
    original_export = figures._export

    def inspect(fig, style):
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        panels = [ax for ax in fig.axes if ax.lines]
        assert len(panels) == 5
        assert all(ax.get_ylim() == (0, 60) for ax in panels)
        assert all(not ax.get_title() for ax in panels)
        if presentation:
            assert fig._suptitle.get_text() == title
            title_bounds = fig._suptitle.get_window_extent(renderer)
        else:
            assert fig._suptitle is None
        for index, (ax, zone, annual) in enumerate(zip(panels, groups, rates, strict=True)):
            assert list(ax.lines[0].get_ydata()) == annual
            observed, slope_line = ax.lines
            assert observed.get_color() == "#0072B2"
            assert observed.get_linestyle() == "-"
            assert observed.get_marker() == "o"
            assert slope_line.get_color() == "#D55E00"
            assert slope_line.get_linestyle() == "--"
            label = next(text for text in ax.texts if text.get_gid() == "trajectory-panel-group")
            assert label.get_text() == zone.title()
            marker = next(text for text in ax.texts if text.get_gid() == f"panel-marker-{chr(97 + index)}")
            assert marker.get_text() == f"({chr(97 + index)})"
            if presentation:
                assert title_bounds.y0 > label.get_window_extent(renderer).y1
        auxiliary = next(ax for ax in fig.axes if ax.tables)
        legend = auxiliary.get_legend()
        assert [handle.get_color() for handle in legend.legend_handles] == ["#0072B2", "#D55E00"]
        table, = auxiliary.tables
        assert table.get_gid() == "f4-statistics-below-key"
        table_bounds = table.get_window_extent(renderer)
        legend_bounds = legend.get_window_extent(renderer)
        assert legend_bounds.y0 > table_bounds.y1
        auxiliary_bounds = auxiliary.get_window_extent(renderer)
        assert all(
            auxiliary_bounds.contains(x, y)
            for x, y in (table_bounds.min, table_bounds.max, legend_bounds.min, legend_bounds.max)
        ), (auxiliary_bounds, table_bounds, legend_bounds)
        cells = table.get_celld()
        assert [cells[0, index].get_text().get_text() for index in range(4)] == [
            "ACZ", "Sen slope", "Raw p", "BH q",
        ]
        for index, (zone, (slope, p, q)) in enumerate(zip(groups, statistics, strict=True), start=1):
            assert [cells[index, column].get_text().get_text() for column in range(4)] == [
                f"({chr(96 + index)}) {zone.title()}", f"{slope:.3f}", f"{p:.4f}", f"{q:.4f}",
            ]
        for cell in cells.values():
            text = cell.get_text().get_window_extent(renderer)
            box = cell.get_window_extent(renderer)
            assert box.contains(text.x0, text.y0) and box.contains(text.x1, text.y1)
        return original_export(fig, style)

    monkeypatch.setattr(figures, "_export", inspect)
    if presentation:
        export_spec = get_presentation_export_spec("rq2_five_acz_comparison", contract)
        analysis = SimpleNamespace(study={"temporal_windows": {"long_run": {"start": "2001-01", "end": "2024-12"}}})
        bundle = SimpleNamespace(figure=contract, analysis=analysis)
        context = SimpleNamespace(bundle=bundle, style=_presentation_style(bundle, export_spec))
        rendered = render_rq2_five_acz_comparison(frame, spec=export_spec, context=context)
    else:
        rendered = publication._trajectory_grid_render(spec, frame, style=PublicationStyle.from_contract(contract))
    assert rendered.png.startswith(b"\x89PNG")
    assert rendered.pdf.startswith(b"%PDF")
    pd.testing.assert_frame_equal(frame, original)
