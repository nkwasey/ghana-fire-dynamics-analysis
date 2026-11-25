"""Source-only RQ2 presentation checks for explicitly declared study periods."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import matplotlib.pyplot as plt
import pandas as pd
import pytest

from rp1_analysis_v1 import figures, presentation_rq2 as rq2
from rp1_analysis_v1.config import load_figure_contract
from rp1_analysis_v1.figures import FigureRenderError
from rp1_analysis_v1.presentation import get_presentation_export_spec
from rp1_analysis_v1.style import PublicationStyle


ROOT = Path(__file__).resolve().parents[1]


def _context(first, last):
    contract = load_figure_contract(ROOT / "config/figure_contract.yml")
    analysis = SimpleNamespace(
        study={"temporal_windows": {"long_run": {"start": f"{first}-01", "end": f"{last}-12"}}},
        reproducibility={"alpha": 0.05},
    )
    style = replace(PublicationStyle.from_contract(contract), single_panel=(20 / 2.54, 15 / 2.54))
    return SimpleNamespace(bundle=SimpleNamespace(figure=contract, analysis=analysis),
                           registry=contract.presentation_export, style=style)


def _series(first, last, *, code="CZ", name="COASTAL ZONE"):
    return pd.DataFrame({"parent_code": code, "parent_name": name,
                         "year": range(first, last + 1),
                         "annual_rate": [float(value + 1) for value in range(last - first + 1)],
                         "sen_slope": 0.125, "raw_p": 0.25, "bh_q": 0.5})


@pytest.mark.parametrize(("first", "last"), [(2014, 2024), (2020, 2027), (2001, 2025)])
def test_annual_support_is_derived_from_the_declared_window(first, last):
    context = _context(first, last)
    years = rq2._configured_years(context)
    frame = _series(first, last)
    original = frame.copy(deep=True)
    work, _code, _name, slope, p, q = rq2._normalise_group(frame, expected_years=years, context="synthetic")
    assert tuple(work.year) == tuple(range(first, last + 1))
    assert (slope, p, q) == (0.125, 0.25, 0.5)
    pd.testing.assert_frame_equal(frame, original)


@pytest.mark.parametrize("invalid_support", ["missing_last", "missing_middle", "shifted_period", "fractional_year"])
def test_missing_duplicate_shifted_or_fractional_years_fail_closed(invalid_support):
    context = _context(2014, 2024)
    frame = _series(2014, 2024)
    if invalid_support == "missing_last":
        frame = frame.iloc[:-1].copy()
    elif invalid_support == "missing_middle":
        frame.loc[5, "year"] = frame.loc[6, "year"]
    elif invalid_support == "shifted_period":
        frame["year"] += 1
    else:
        frame["year"] = frame.year.astype(float)
        frame.loc[0, "year"] += 0.5
    with pytest.raises(FigureRenderError):
        rq2._normalise_group(frame, expected_years=rq2._configured_years(context), context="synthetic")


@pytest.mark.parametrize(("start", "end"), [("2014-02", "2024-12"), ("2014-01", "2024-11"),
                                             ("2024-01", "2014-12"), ("not-a-month", "2024-12")])
def test_period_requires_ordered_complete_calendar_years(start, end):
    context = _context(2014, 2024)
    context.bundle.analysis.study["temporal_windows"]["long_run"] = {"start": start, "end": end}
    with pytest.raises(FigureRenderError):
        rq2._configured_years(context)


@pytest.mark.parametrize(("first", "last", "ticks"), [
    (2001, 2024, [2001, 2005, 2010, 2015, 2020, 2024]),
    (2014, 2024, [2014, 2016, 2018, 2020, 2022, 2024]),
    (2024, 2024, [2024]),
])
def test_axis_bounds_and_ticks_follow_the_declared_period(first, last, ticks):
    fig, ax = plt.subplots()
    try:
        rq2._apply_temporal_axis(ax, tuple(range(first, last + 1)))
        expected_bounds = (first, last) if first != last else (first - 0.5, last + 0.5)
        assert ax.get_xlim() == pytest.approx(expected_bounds)
        assert list(ax.get_xticks()) == ticks
    finally:
        plt.close(fig)


@pytest.mark.parametrize("comparison", [False, True])
def test_production_renderers_accept_future_period_without_recalculating_values(monkeypatch, comparison):
    context = _context(2014, 2026)
    figure_contract = context.bundle.figure
    if comparison:
        spec = get_presentation_export_spec("rq2_five_acz_comparison", figure_contract)
        names = next(f.renderer_options["panel_order"] for f in figure_contract.figures if f.figure_id == "F4")
        codes = ("CZ", "FZ", "GS", "SS", "TZ")
        frame = pd.concat([_series(2014, 2026, code=code, name=name) for code, name in zip(codes, names, strict=True)], ignore_index=True)
        renderer = rq2.render_rq2_five_acz_comparison
    else:
        spec = get_presentation_export_spec("rq2_coastal_trend", figure_contract)
        frame = _series(2014, 2026)
        renderer = rq2.render_rq2_single_trend
    original = frame.copy(deep=True)
    original_export = figures._export
    checked = []

    def inspect_export(fig, style):
        axes = [ax for ax in fig.axes if ax.lines]
        assert len(axes) == (5 if comparison else 1)
        for ax in axes:
            assert ax.get_xlim() == pytest.approx((2014.0, 2026.0))
            observed = ax.lines[0]
            assert tuple(observed.get_xdata()) == tuple(range(2014, 2027))
            assert tuple(observed.get_ydata()) == tuple(float(value) for value in range(1, 14))
        checked.append(True)
        return original_export(fig, style)

    monkeypatch.setattr(figures, "_export", inspect_export)
    rendered = renderer(frame, spec=spec, context=context)
    assert checked == [True]
    assert rendered.png.startswith(b"\x89PNG") and rendered.pdf.startswith(b"%PDF")
    pd.testing.assert_frame_equal(frame, original)
