"""Supplementary figures rendered from governed reviewer-analysis projections."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Protocol

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.ticker import FuncFormatter, NullFormatter, PercentFormatter

from .contracts import PresentationExportSpecificationContract
from .figures import FigureRenderError, RenderedFigure, acz_line_style, export_figure
from .grid_rendering import add_panel_labels
from .style import ACZ_SERIES_STYLES, PublicationStyle


class RenderContextLike(Protocol):
    style: PublicationStyle


_ZONE_NAMES = {
    "CZ": "Coastal",
    "FZ": "Forest",
    "GS": "Guinea Savannah",
    "SS": "Sudan Savannah",
    "TZ": "Transition",
}
_INTERVAL_ZONE_LABELS = {
    "GS": "Guinea\nSavannah",
    "SS": "Sudan\nSavannah",
}
_NOISE_STYLES = {
    "fitted_weak_ar1": ("Fitted weak AR(1)", "o", "-"),
    "independent_years": ("Independent years", "s", "--"),
    "negative_ar1_stress": ("Negative AR(1)", "^", "-."),
    "positive_ar1_stress": ("Positive AR(1)", "D", ":"),
}
_ESTIMATE_COLOUR = "#30343B"
_REFERENCE_COLOUR = "#777777"


def _numeric(frame: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    values = frame.loc[:, list(columns)].apply(pd.to_numeric, errors="raise")
    if not np.isfinite(values.to_numpy(dtype=float)).all():
        raise FigureRenderError(f"Non-finite reviewer figure values in {tuple(columns)}")
    return values


def _draw_support(axes: tuple[Axes, Axes], frame: pd.DataFrame, *, style: PublicationStyle) -> None:
    rate_ax, sensitivity_ax = axes
    districts = frame.loc[frame["record_type"].eq("district")]
    thresholds = frame.loc[frame["record_type"].eq("threshold")]
    if districts.empty or thresholds.empty or len(districts) + len(thresholds) != len(frame):
        raise FigureRenderError("Burnable support figure requires district and threshold records")
    if districts["unit_id"].duplicated().any() or thresholds.duplicated(["zone", "minimum_fixed_union_km2"]).any():
        raise FigureRenderError("Burnable support figure contains duplicate district or threshold keys")
    if not set(districts["zone"]).union(thresholds["zone"]).issubset(_ZONE_NAMES):
        raise FigureRenderError("Burnable support figure has an unknown zone code")
    area = pd.to_numeric(districts["fixed_burnable_union_km2"], errors="raise")
    if (area.dropna() < 0).any() or not np.isfinite(area.dropna()).all() or not area.gt(0).any():
        raise FigureRenderError("Burnable support figure requires a distribution of positive support")
    rates = pd.to_numeric(districts["long_run_rate"], errors="raise")
    plotted = area.gt(0) & rates.notna()
    if not np.isfinite(rates.loc[plotted]).all() or (rates.loc[plotted] < 0).any():
        raise FigureRenderError("Burnable support figure requires nonnegative district rates")
    marked = thresholds["is_primary_threshold"].astype(str).str.casefold().eq("true")
    primary = _numeric(thresholds.loc[marked], ("minimum_fixed_union_km2",))["minimum_fixed_union_km2"].unique()
    if len(primary) != 1 or primary[0] <= 0:
        raise FigureRenderError("Burnable support figure requires exactly one positive principal threshold")
    cutoff = float(primary[0])
    for zone, label in _ZONE_NAMES.items():
        colour = style.acz_colours[zone]
        marker, _ = ACZ_SERIES_STYLES[zone]
        district_rows = districts["zone"].eq(zone) & plotted
        rate_ax.scatter(
            area.loc[district_rows], rates.loc[district_rows], label=label,
            color=colour, marker=marker, s=14, edgecolors="#4B5260", linewidths=0.35,
        )
        subset = thresholds.loc[thresholds["zone"].eq(zone)]
        if subset.empty:
            continue
        x = _numeric(subset, ("minimum_fixed_union_km2", "n_districts"))
        gini = pd.to_numeric(subset["gini"], errors="raise")
        if (x < 0).any().any() or not gini.dropna().between(0, 1).all():
            raise FigureRenderError("Burnable support thresholds and Gini values are outside their domains")
        rows = x.assign(gini=gini).sort_values("minimum_fixed_union_km2")
        sensitivity_ax.plot(
            rows["minimum_fixed_union_km2"], rows["gini"], markersize=3.5,
            **acz_line_style(zone, colour=colour, width=style.line_width),
        )
    for panel in axes:
        panel.axvline(cutoff, linewidth=0.8, linestyle="--", color=_REFERENCE_COLOUR, zorder=0)
    rate_ax.set_xscale("log")
    rate_ax.xaxis.set_major_formatter(
        FuncFormatter(lambda value, _: np.format_float_positional(value, trim="-"))
    )
    rate_ax.xaxis.set_minor_formatter(NullFormatter())
    rate_ax.set_xlabel("Fixed burnable area (km²)")
    rate_ax.set_ylabel("District rate (km² per 100 km² yr⁻¹)")
    sensitivity_ax.set_xlabel("Minimum fixed burnable area (km²)")
    sensitivity_ax.set_ylabel("Gini coefficient of district rates")
    sensitivity_ax.set_ylim(0, 1)
    rate_ax.legend(loc="upper left", fontsize="small", frameon=False)


def _draw_intervals(ax: Axes, frame: pd.DataFrame, *, label_font: float, show_title: bool) -> None:
    if frame["parent_code"].duplicated().any() or set(frame["parent_code"]) != set(_ZONE_NAMES):
        raise FigureRenderError("Trend uncertainty figure requires one slope for each of the five zones")
    intervals = frame.set_index("parent_code").loc[list(_ZONE_NAMES)]
    slopes = _numeric(intervals, ("sen_slope",))["sen_slope"]
    levels = _numeric(intervals, ("interval_level",))["interval_level"].unique()
    if len(levels) != 1 or not 0 < levels[0] < 1:
        raise FigureRenderError("Trend uncertainty figure requires one pointwise interval level")
    bounds = intervals[["lower", "upper"]].apply(pd.to_numeric, errors="raise")
    present = bounds["lower"].notna()
    if not present.equals(bounds["upper"].notna()) or not np.isfinite(bounds.loc[present]).all().all():
        raise FigureRenderError("Trend uncertainty figure requires both finite bounds or neither")
    if (bounds.loc[present, "lower"] > bounds.loc[present, "upper"]).any():
        raise FigureRenderError("Trend uncertainty figure has a reversed interval")
    status = intervals["interval_status"]
    supported = status.eq("TARGET_SUPPORTED_ON_INDEPENDENT_SIMULATED_SERIES")
    limited = status.eq("LIMITED_INDEPENDENT_SIMULATION_COVERAGE")
    failed = status.eq("CALIBRATION_FAILED")
    unavailable = status.isin({
        "UNAVAILABLE_NONPOSITIVE_RATES",
        "UNAVAILABLE_NONPOSITIVE_FITTED_PATH",
        "UNAVAILABLE_DEGENERATE_RESIDUALS",
    })
    if not (supported | limited | failed | unavailable).all() or not present.equals(supported | limited):
        raise FigureRenderError("Trend uncertainty figure has inconsistent calibration status and bounds")
    row = np.arange(len(intervals))
    ax.axvline(0.0, color=_REFERENCE_COLOUR, linewidth=0.8, linestyle="--")
    ax.hlines(
        row[supported], bounds.loc[supported, "lower"], bounds.loc[supported, "upper"], color=_ESTIMATE_COLOUR,
    )
    ax.plot(slopes.loc[supported], row[supported], "o", color=_ESTIMATE_COLOUR, markersize=4)
    ax.hlines(
        row[limited], bounds.loc[limited, "lower"], bounds.loc[limited, "upper"],
        color=_ESTIMATE_COLOUR, linestyles="dashed",
    )
    for mask, marker, label in (
        (limited, "o", "Coverage target unmet (S13)"),
        (failed, "x", "Calibration failed (S13)"),
        (unavailable, "+", "Model inapplicable (S13)"),
    ):
        if mask.any():
            ax.plot(slopes.loc[mask], row[mask], marker, color=_ESTIMATE_COLOUR, markerfacecolor="white",
                    markersize=4, label=label)
    if not supported.all():
        ax.legend(loc="best", frameon=False, fontsize="small")
    labels = [_INTERVAL_ZONE_LABELS.get(code, name) for code, name in _ZONE_NAMES.items()]
    ax.set_yticks(
        row, labels, rotation=90, ha="center", va="center", multialignment="center",
        linespacing=0.95, fontsize=label_font,
    )
    ax.tick_params(axis="y", length=2, pad=12)
    ax.invert_yaxis()
    if show_title:
        ax.set_title(f"Model-conditional {100 * levels[0]:g}% intervals\nPointwise by agroclimatic zone")
    ax.set_xlabel("Sen slope (annual-rate units per year)")


def _draw_detectability(
    ax: Axes, frame: pd.DataFrame, *, legend_font: float, show_title: bool, style: PublicationStyle,
) -> None:
    if show_title:
        ax.set_title("Transition Zone detection (BH)\nConcurrent decline across all zones")
    if frame.empty:
        ax.set_axis_off()
        ax.text(
            0.5, 0.5, "No complete five-zone power analysis\nSee S16-S17 for availability",
            ha="center", va="center", transform=ax.transAxes,
        )
        return
    if not (
        frame["effect_pattern"].eq("concurrent_decline")
        & frame["target_zone"].eq("TZ")
        & frame["parent_code"].eq("TZ")
    ).all():
        raise FigureRenderError("Trend detectability figure requires the Transition concurrent-decline series")
    if not frame["noise_scenario"].isin(_NOISE_STYLES).all():
        raise FigureRenderError("Trend detectability figure requires declared noise scenarios")
    if frame.duplicated(["noise_scenario", "decline_fraction_per_decade"]).any():
        raise FigureRenderError("Trend detectability figure contains duplicate curve coordinates")
    targets = _numeric(frame, ("target_power",))["target_power"].unique()
    if len(targets) != 1 or not 0 < targets[0] < 1:
        raise FigureRenderError("Trend detectability figure requires one target probability")
    for noise, group in frame.groupby("noise_scenario", sort=True, observed=True):
        data = _numeric(group, ("decline_fraction_per_decade", "power", "mc_lower", "mc_upper", "bank_min", "bank_max"))
        data = data.sort_values("decline_fraction_per_decade")
        if not data.apply(lambda column: column.between(0, 1)).all().all() or not (
            (data["mc_lower"] <= data["power"]) & (data["power"] <= data["mc_upper"])
        ).all():
            raise FigureRenderError("Trend detectability figure has invalid simulated probabilities or Wilson limits")
        if not ((data["bank_min"] <= data["power"]) & (data["power"] <= data["bank_max"])).all():
            raise FigureRenderError("Trend detectability figure has an invalid across-bank range")
        label, marker, linestyle = _NOISE_STYLES[noise]
        colour = style.detection_scenario_colours[noise]
        ax.fill_between(
            data["decline_fraction_per_decade"], data["bank_min"], data["bank_max"],
            color=colour, alpha=0.13, linewidth=0,
        )
        ax.errorbar(
            data["decline_fraction_per_decade"], data["power"],
            yerr=np.vstack([data["power"] - data["mc_lower"], data["mc_upper"] - data["power"]]),
            marker=marker, linestyle=linestyle, color=colour, capsize=2.0, markersize=3.2, linewidth=0.9,
            label=label,
        )
    ax.axhline(
        targets[0], color=_REFERENCE_COLOUR, linestyle="--", linewidth=0.8,
        label=f"{100 * targets[0]:g}% target",
    )
    ax.set_ylim(0, 1.03)
    ax.xaxis.set_major_formatter(PercentFormatter(xmax=1, decimals=0))
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=1, decimals=0))
    ax.set_xlabel("Simulated decline per decade (%)")
    ax.set_ylabel("Simulated detection probability (%)")
    ax.legend(
        loc="upper left", frameon=False, fontsize=legend_font, title_fontsize=legend_font,
        ncols=2, columnspacing=0.8, handletextpad=0.5,
        title="95% Wilson whiskers (reference bank)\nShading = across-bank range",
    )


def render_reviewer_figure(
    figure_id: str,
    frame: pd.DataFrame | None,
    *,
    style: PublicationStyle,
    figure_size: tuple[float, float] | None = None,
    title: str | None = None,
) -> RenderedFigure:
    """Render a supplementary figure with an optional presentation title."""
    if frame is None or frame.empty:
        raise FigureRenderError(f"{figure_id} requires governed reviewer figure data")
    if figure_id not in {"FS3", "FS4"}:
        raise FigureRenderError(f"Unknown reviewer figure {figure_id!r}")
    with plt.rc_context(matplotlib.RcParams(style.rc_params())):
        size = figure_size or style.wide_single_panel
        if figure_id == "FS3":
            fig, axes = plt.subplots(1, 2, figsize=size, layout="constrained")
        else:
            # Stacked vertical labels need extra left margin, and the right y-axis
            # title and tick labels share the wider inter-panel gutter.
            fig, axes = plt.subplots(1, 2, figsize=size, gridspec_kw={"width_ratios": (0.95, 1.12)})
            fig.subplots_adjust(
                left=0.133, right=0.980, bottom=0.125, top=0.820 if title else 0.915,
                wspace=0.44,
            )
        try:
            if title:
                fig.suptitle(title, fontsize=style.base_font + 1)
            if figure_id == "FS3":
                _draw_support(tuple(axes), frame, style=style)
            else:
                intervals = frame["record_type"].eq("interval")
                detectability = frame["record_type"].eq("detectability")
                if not (intervals | detectability).all():
                    raise FigureRenderError("Trend uncertainty figure has an unknown record type")
                # A 7.2 pt label remains over 5 pt when the 200 mm figure is reduced to 140 mm.
                label_font = max(7.2, style.tick_font)
                _draw_intervals(axes[0], frame.loc[intervals], label_font=label_font, show_title=bool(title))
                _draw_detectability(
                    axes[1], frame.loc[detectability], legend_font=label_font, show_title=bool(title), style=style,
                )
            label_style = style
            if figure_id == "FS4" and title:
                geometry = replace(style.geometry, panel_label_offset_x=style.geometry.panel_label_offset_x - 0.035)
                label_style = replace(style, geometry=geometry)
            add_panel_labels(tuple(axes), style=label_style)
            return export_figure(fig, style)
        finally:
            plt.close(fig)


def render_burnable_support(
    frame: pd.DataFrame | None, *, spec: PresentationExportSpecificationContract, context: RenderContextLike,
) -> RenderedFigure:
    return render_reviewer_figure("FS3", frame, style=context.style, title=spec.label)


def render_trend_uncertainty(
    frame: pd.DataFrame | None, *, spec: PresentationExportSpecificationContract, context: RenderContextLike,
) -> RenderedFigure:
    return render_reviewer_figure("FS4", frame, style=context.style, title=spec.label)


REVIEWER_PRESENTATION_RENDERERS = {
    "rq1_burnable_support_sensitivity": render_burnable_support,
    "rq2_trend_uncertainty": render_trend_uncertainty,
}
