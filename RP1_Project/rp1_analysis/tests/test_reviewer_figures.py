from __future__ import annotations

from dataclasses import replace
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import to_hex
from pypdf import PdfReader

import rp1_analysis_v1.reviewer_figures as reviewer_figures
from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.figures import (
    FigureRenderError,
    common_trajectory_y_limits,
    draw_district_seasonal_heatmap,
    draw_seasonality_lines,
    draw_trajectory_panel,
    label_district_share_colorbar,
)
from rp1_analysis_v1.presentation import load_presentation_export_registry
from rp1_analysis_v1.reviewer_figures import REVIEWER_PRESENTATION_RENDERERS, render_reviewer_figure
from rp1_analysis_v1.style import PublicationStyle


ROOT = Path(__file__).resolve().parents[1]
ZONES = ("CZ", "FZ", "GS", "SS", "TZ")


@pytest.fixture(scope="module")
def figure_authority():
    bundle = load_configuration_bundle(ROOT / "config")
    return bundle.figure, PublicationStyle.from_contract(bundle.figure)


def support_frame() -> pd.DataFrame:
    districts = [
        dict(record_type="district", unit_id=code, zone=code,
             fixed_burnable_union_km2=10.0 + i * 100.0, long_run_rate=5.5 + i)
        for i, code in enumerate(ZONES)
    ]
    thresholds = [
        dict(record_type="threshold", zone=code, minimum_fixed_union_km2=threshold,
             n_districts=20, gini=0.6 - i / 10.0, is_primary_threshold=threshold == 50.0)
        for i, code in enumerate(ZONES) for threshold in (0.0, 50.0)
    ]
    return pd.DataFrame(districts + thresholds)


def trend_frame() -> pd.DataFrame:
    intervals = [
        dict(record_type="interval", parent_code=code, sen_slope=-i / 10.0,
             lower=-(i + 1) / 10.0, upper=0.1,
             interval_status="TARGET_SUPPORTED_ON_INDEPENDENT_SIMULATED_SERIES", interval_level=0.95)
        for i, code in enumerate(ZONES)
    ]
    power = [
        dict(record_type="detectability", parent_code="TZ", noise_scenario=noise,
             effect_pattern="concurrent_decline", target_zone="TZ",
             decline_fraction_per_decade=decline, power=probability,
             mc_lower=probability - 0.03, mc_upper=probability + 0.03,
             bank_min=probability - 0.04, bank_max=probability + 0.06, target_power=0.8)
        for noise in ("fitted_weak_ar1", "independent_years", "negative_ar1_stress", "positive_ar1_stress")
        for decline, probability in ((0.0, 0.05), (0.1, 0.7))
    ]
    return pd.DataFrame(intervals + power)


@pytest.mark.parametrize(
    ("figure_id", "export_id", "source", "pdf_labels", "presentation_headings"),
    [
        ("FS3", "rq1_burnable_support_sensitivity", support_frame,
         ("Fixed burnable area", "Gini coefficient of district rates"), ()),
        ("FS4", "rq2_trend_uncertainty", trend_frame,
         ("Sen slope", "Simulated detection probability", "80% target",
          "95% Wilson whiskers (reference bank)", "Shading = across-bank range"),
         ("Model-conditional 95% intervals", "Pointwise by agroclimatic zone",
          "Transition Zone detection (BH)", "Concurrent decline across all zones")),
    ],
)
def test_reviewer_figure_title_policy_and_shared_plot_labels(
    figure_authority, figure_id, export_id, source, pdf_labels, presentation_headings,
):
    figure_contract, style = figure_authority
    figure_size = style.dimensions_for("rectangular_one_by_two")
    frame = source()
    publication = render_reviewer_figure(figure_id, frame, style=style, figure_size=figure_size)
    spec = load_presentation_export_registry(figure_contract).export_by_id(export_id)
    standalone = REVIEWER_PRESENTATION_RENDERERS[spec.renderer_identity](
        frame, spec=spec, context=SimpleNamespace(style=replace(style, wide_single_panel=figure_size)),
    )
    for rendered, titled in ((publication, False), (standalone, True)):
        pdf = PdfReader(BytesIO(rendered.pdf)).pages[0]
        assert float(pdf.mediabox.width) == pytest.approx(200 * 72 / 25.4)
        assert float(pdf.mediabox.height) == pytest.approx(150 * 72 / 25.4)
        text = pdf.extract_text()
        assert "(a)" in text and "(b)" in text
        assert all(label in text for label in pdf_labels)
        for title in (spec.label, *presentation_headings):
            assert (title in text) is titled


def test_reviewer_figures_reject_ambiguous_threshold_and_invalid_power(figure_authority):
    _, style = figure_authority
    support = support_frame()
    support.loc[support["record_type"].eq("threshold"), "is_primary_threshold"] = True
    with pytest.raises(FigureRenderError, match="exactly one positive principal threshold"):
        render_reviewer_figure("FS3", support, style=style)
    power = trend_frame()
    power.loc[power["record_type"].eq("detectability"), "power"] = 1.1
    with pytest.raises(FigureRenderError, match="invalid simulated probabilities"):
        render_reviewer_figure("FS4", power, style=style)
    power = trend_frame()
    power.loc[power["record_type"].eq("detectability"), "target_zone"] = "FZ"
    with pytest.raises(FigureRenderError, match="requires the Transition concurrent-decline series"):
        render_reviewer_figure("FS4", power, style=style)
    power = trend_frame()
    power.loc[power["record_type"].eq("detectability"), "bank_min"] = 0.75
    with pytest.raises(FigureRenderError, match="invalid across-bank range"):
        render_reviewer_figure("FS4", power, style=style)


def test_seasonality_and_burnable_support_share_zone_styles(figure_authority):
    _, style = figure_authority
    seasonal = pd.DataFrame([
        dict(parent_code=code, unit_name=code, month=month, value=0.1 * month,
             circular_mean_month=2.3, mean_resultant_length=0.65)
        for code in ZONES for month in range(1, 13)
    ])
    fig, (seasonality, rates, gini) = plt.subplots(1, 3)
    try:
        draw_seasonality_lines(seasonality, seasonal, xlabel="Month", ylabel="Area", style=style)
        reviewer_figures._draw_support((rates, gini), support_frame(), style=style)
        for code, first, second, points in zip(ZONES, seasonality.lines, gini.lines[:5], rates.collections, strict=True):
            expected = style.acz_colours[code].lower()
            assert to_hex(first.get_color()) == to_hex(second.get_color()) == to_hex(points.get_facecolor()[0]) == expected
            assert first.get_marker() == second.get_marker()
            assert first.get_linestyle() == second.get_linestyle()
        assert seasonality.lines[0].get_path_effects() and seasonality.lines[2].get_path_effects()
    finally:
        plt.close(fig)


def test_district_share_scale_preserves_observed_zero_and_keys_undefined():
    pivot = pd.DataFrame([[0.0, 0.5, 1.0, np.nan] * 3])
    fig, ax = plt.subplots()
    try:
        image = draw_district_seasonal_heatmap(ax, pivot, xlabel="Month", ylabel="Districts")
        colorbar = fig.colorbar(image, ax=ax, orientation="horizontal")
        label_district_share_colorbar(colorbar, image)
        assert image.get_clim() == (0.0, 1.0)
        assert image.get_cmap().name == "viridis_r"
        assert not image.get_array().mask[0, 0]
        assert image.get_array().mask[0, 3]
        assert to_hex(image.get_cmap().get_bad()) == "#ffffff"
        assert to_hex(image.get_cmap()(0.0)) != "#ffffff"
        assert "White = undefined share" in colorbar.ax.xaxis.label.get_text()
    finally:
        plt.close(fig)


def test_detection_scenario_encodings_are_stable_when_other_scenarios_are_absent(figure_authority):
    _, style = figure_authority
    frame = trend_frame().query("noise_scenario in ['negative_ar1_stress', 'positive_ar1_stress']")
    fig, ax = plt.subplots()
    try:
        reviewer_figures._draw_detectability(ax, frame, legend_font=8, show_title=False, style=style)
        for container, (label, colour, marker, linestyle) in zip(ax.containers, (
            ("Negative AR(1)", "#009e73", "^", "-."),
            ("Positive AR(1)", "#482677", "D", ":"),
        ), strict=True):
            line, caps, _ = container.lines
            assert container.get_label() == label
            assert (to_hex(line.get_color()), line.get_marker(), line.get_linestyle()) == (colour, marker, linestyle)
            assert len(caps) == 2
    finally:
        plt.close(fig)


def test_burnable_support_log_ticks_are_plain_and_readable_at_print_widths(figure_authority, monkeypatch):
    _, style = figure_authority
    original_export = reviewer_figures.export_figure

    def inspect_export(fig, render_style):
        rendered = original_export(fig, render_style)
        canvas = FigureCanvasAgg(fig)
        canvas.draw()
        renderer = canvas.get_renderer()
        rate_ax, _ = fig.axes
        assert rate_ax.get_xscale() == "log"
        lower, upper = rate_ax.get_xlim()
        ticks = [
            tick.label1 for tick in rate_ax.xaxis.get_major_ticks()
            if lower <= tick.get_loc() <= upper
        ]
        assert [tick.get_text() for tick in ticks] == ["10", "100"]
        assert all(not label.get_text() for label in rate_ax.get_xticklabels(minor=True))
        for width in (140, 160):
            assert all(tick.get_fontsize() * (width / 200) >= 5 for tick in ticks)
        boxes = [tick.get_window_extent(renderer) for tick in ticks]
        assert all(left.x1 < right.x0 for left, right in zip(boxes, boxes[1:]))
        return rendered

    monkeypatch.setattr(reviewer_figures, "export_figure", inspect_export)
    render_reviewer_figure("FS3", support_frame(), style=style)


def test_trend_uncertainty_distinguishes_unsupported_intervals(figure_authority):
    _, style = figure_authority
    trend = trend_frame()
    trend.loc[trend["parent_code"].eq("TZ") & trend["record_type"].eq("interval"), "interval_status"] = (
        "LIMITED_INDEPENDENT_SIMULATION_COVERAGE"
    )
    trend.loc[trend["parent_code"].eq("SS"), ["interval_status", "lower", "upper"]] = (
        "CALIBRATION_FAILED", np.nan, np.nan,
    )
    rendered = render_reviewer_figure("FS4", trend, style=style)
    pdf_text = PdfReader(BytesIO(rendered.pdf)).pages[0].extract_text()
    assert "Coverage target unmet (S13)" in pdf_text
    assert "Calibration failed (S13)" in pdf_text
    trend.loc[trend["parent_code"].eq("SS"), "interval_status"] = (
        "TARGET_SUPPORTED_ON_INDEPENDENT_SIMULATED_SERIES"
    )
    with pytest.raises(FigureRenderError, match="inconsistent calibration status"):
        render_reviewer_figure("FS4", trend, style=style)


def test_trend_uncertainty_exports_when_full_family_is_unavailable(figure_authority):
    _, style = figure_authority
    trend = trend_frame().query("record_type == 'interval'").copy()
    trend.loc[trend["parent_code"].eq("CZ"), ["interval_status", "lower", "upper"]] = (
        "UNAVAILABLE_NONPOSITIVE_RATES", np.nan, np.nan,
    )
    rendered = render_reviewer_figure("FS4", trend, style=style)
    pdf_text = PdfReader(BytesIO(rendered.pdf)).pages[0].extract_text()
    assert "Model inapplicable (S13)" in pdf_text
    assert "No complete five-zone power analysis" in pdf_text
    assert "80% target" not in pdf_text


@pytest.mark.parametrize("title", (None, "Sen slope uncertainty and trend detectability"))
def test_trend_uncertainty_axes_and_stacked_labels_remain_clear(figure_authority, monkeypatch, title):
    _, style = figure_authority
    original_export = reviewer_figures.export_figure

    def inspect_export(fig, render_style):
        out = original_export(fig, render_style)
        canvas = FigureCanvasAgg(fig)
        canvas.draw()
        left, right = fig.axes
        renderer = canvas.get_renderer()
        labels = left.get_yticklabels()
        assert [label.get_text() for label in labels] == [
            "Coastal", "Forest", "Guinea\nSavannah", "Sudan\nSavannah", "Transition",
        ]
        assert all(label.get_rotation() == 90 for label in labels)
        label_boxes = sorted((label.get_window_extent(renderer) for label in labels), key=lambda box: box.y0)
        assert all(first.y1 < second.y0 for first, second in zip(label_boxes, label_boxes[1:]))
        assert all(fig.bbox.x0 < box.x0 < box.x1 < left.bbox.x0 for box in label_boxes)
        if title:
            heading = next(text for text in fig.texts if text.get_text() == title)
            assert heading.get_window_extent(renderer).y0 > max(
                ax.title.get_window_extent(renderer).y1 for ax in fig.axes
            )
            for axis in fig.axes:
                marker = next(text for text in axis.texts if (text.get_gid() or "").startswith("panel-marker-"))
                assert marker.get_window_extent(renderer).x1 < axis.title.get_window_extent(renderer).x0
        else:
            assert all(not ax.get_title() for ax in fig.axes)
        assert right.yaxis.label.get_window_extent(renderer).x0 > left.bbox.x1
        assert all(label.get_window_extent(renderer).x0 > left.bbox.x1 for label in right.get_yticklabels())
        legend = right.get_legend()
        legend_box = legend.get_window_extent(renderer)
        assert right.bbox.x0 <= legend_box.x0 < legend_box.x1 <= right.bbox.x1
        assert legend_box.y0 > right.transData.transform((0.0, 0.8))[1]
        for width in (140, 160):
            assert all(
                text.get_fontsize() * (width / 200) >= 5
                for text in [*labels, legend.get_title(), *legend.get_texts()]
            )
        return out

    monkeypatch.setattr(reviewer_figures, "export_figure", inspect_export)
    render_reviewer_figure("FS4", trend_frame(), style=style, title=title)


def test_annual_trajectory_common_limits_keep_values_and_move_names_outside(figure_authority):
    _, style = figure_authority
    frame = pd.DataFrame({
        "zone": ["COASTAL", "COASTAL", "GUINEA SAVANNAH", "GUINEA SAVANNAH"],
        "year": [2021, 2024, 2021, 2024],
        "rate": [5.5, 3.0, 42.5, 38.0],
        "slope": [-0.5, -0.5, -9.0, -9.0],
        "p": [0.1] * 4,
        "q": [0.2] * 4,
    })
    limits = common_trajectory_y_limits(frame, group="zone", x="year", y="rate", slope="slope")
    figure, axes = plt.subplots(1, 2)
    try:
        for ax, (zone, rows) in zip(axes, frame.groupby("zone"), strict=True):
            draw_trajectory_panel(
                ax, rows, x="year", y="rate", slope="slope", annotation_fields=("slope", "p", "q"),
                group_label=zone, xlabel="Year", ylabel="Rate", style=style, common_y_limits=limits,
            )
            assert ax.get_title() == zone.title()
            assert not ax.texts
            assert ax.get_ylim() == limits
            np.testing.assert_array_equal(ax.lines[0].get_ydata(), rows["rate"])
            assert all(limits[0] <= point <= limits[1] for point in ax.lines[1].get_ydata())
    finally:
        plt.close(figure)
