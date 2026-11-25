"""Pure publication figure renderers.

These functions do not calculate RQ statistics. They accept already governed
figure-data tables and render them deterministically.
"""

from __future__ import annotations

import io
import math
import textwrap
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import patheffects
from matplotlib.axes import Axes
from matplotlib.lines import Line2D
from matplotlib.ticker import NullFormatter, NullLocator, PercentFormatter

from .grid_rendering import (
    apply_row_vertical_padding,
    build_vertical_band_axes,
    ensure_axis_labels_inside_canvas,
    ensure_axis_titles_inside_canvas,
    ensure_vertical_band_xlabel_clearance,
)
from .style import ACZ_SERIES_STYLES, PublicationStyle, panel_label


class FigureRenderError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RenderedFigure:
    png: bytes
    pdf: bytes
    width_in: float
    height_in: float
    dpi: int


def _export(fig, style: PublicationStyle) -> RenderedFigure:
    """Export raster/vector products while preserving governed physical page size.

    PDF uses the exact configured figure dimensions.  PNG dimensions use the
    configured half-up pixel rounding rule; Matplotlib otherwise truncates
    fractional pixel extents inconsistently across dimensions.
    """
    png = io.BytesIO()
    pdf = io.BytesIO()
    original_width, original_height = (float(x) for x in fig.get_size_inches())
    pixel_width, pixel_height = style.raster_pixels_for_inches((original_width, original_height))
    raster_size = (pixel_width / style.dpi, pixel_height / style.dpi)
    fig.set_size_inches(*raster_size, forward=True)
    fig.savefig(
        png,
        format="png",
        dpi=style.dpi,
        metadata={"Software": "rp1-analysis-v1"},
    )
    fig.set_size_inches(original_width, original_height, forward=True)
    fig.savefig(
        pdf,
        format="pdf",
        dpi=style.dpi,
        metadata={
            "Creator": "rp1-analysis-v1",
            "Producer": "matplotlib",
            "CreationDate": None,
            "ModDate": None,
        },
    )
    plt.close(fig)
    return RenderedFigure(
        png.getvalue(),
        pdf.getvalue(),
        original_width,
        original_height,
        style.dpi,
    )


def _require(frame: pd.DataFrame, columns: Sequence[str]) -> None:
    missing = sorted(set(columns).difference(frame.columns))
    if missing:
        raise FigureRenderError(f"Figure data are missing columns: {missing!r}")
    if frame.empty:
        raise FigureRenderError("Figure data are empty")


def _scientific_colorbar_label(label: str | None) -> str:
    """Validate one non-map continuous colourbar's scientific label."""
    if label is None or not str(label).strip():
        raise FigureRenderError("Continuous non-map figures require a scientific colourbar label")
    cleaned = str(label).strip()
    if cleaned.casefold() == "value":
        raise FigureRenderError("Generic colourbar label 'Value' is not scientifically acceptable")
    return cleaned


def line_plot(
    frame: pd.DataFrame,
    *,
    x: str,
    y: str,
    group: str,
    title: str,
    xlabel: str,
    ylabel: str,
    style: PublicationStyle,
) -> RenderedFigure:
    _require(frame, [x, y, group])
    with plt.rc_context(matplotlib.RcParams(style.rc_params())):
        fig, ax = plt.subplots(figsize=style.single_panel)
        for key, g in frame.groupby(group, sort=True, observed=True):
            ax.plot(
                g[x], g[y], marker="o", markersize=2.5, linewidth=style.line_width, label=str(key)
            )
        ax.set(title=title, xlabel=xlabel, ylabel=ylabel)
        ax.grid(alpha=style.grid_alpha)
        ax.legend(frameon=False, ncol=2)
        fig.tight_layout()
        return _export(fig, style)


def forest_plot(
    frame: pd.DataFrame,
    *,
    label: str,
    estimate: str,
    low: str,
    high: str,
    title: str,
    xlabel: str,
    reference: float | None,
    style: PublicationStyle,
) -> RenderedFigure:
    _require(frame, [label, estimate, low, high])
    work = frame.reset_index(drop=True)
    with plt.rc_context(matplotlib.RcParams(style.rc_params())):
        fig, ax = plt.subplots(figsize=style.single_panel)
        y = np.arange(len(work))
        est = pd.to_numeric(work[estimate], errors="raise").to_numpy(float)
        lo = pd.to_numeric(work[low], errors="raise").to_numpy(float)
        hi = pd.to_numeric(work[high], errors="raise").to_numpy(float)
        ax.errorbar(est, y, xerr=np.vstack((est - lo, hi - est)), fmt="o", capsize=3)
        if reference is not None:
            ax.axvline(reference, linewidth=0.8, linestyle="--")
        ax.set_yticks(y, work[label].astype(str))
        ax.invert_yaxis()
        ax.set_xlabel(xlabel)
        ax.set_title(title)
        ax.grid(axis="x", alpha=style.grid_alpha)
        fig.tight_layout()
        return _export(fig, style)


def _build_heatmap_figure(
    frame: pd.DataFrame,
    *,
    row: str,
    column: str,
    value: str,
    title: str,
    xlabel: str,
    ylabel: str,
    colorbar_label: str | None,
    style: PublicationStyle,
):
    """Build a governed single-panel continuous heatmap for structural inspection."""
    _require(frame, [row, column, value])
    label = _scientific_colorbar_label(colorbar_label)
    pivot = frame.pivot(index=row, columns=column, values=value)
    fig, ax = plt.subplots(figsize=style.single_panel)
    image = ax.imshow(pivot.to_numpy(float), aspect="auto", interpolation="nearest")
    ax.set_xticks(np.arange(len(pivot.columns)), [str(x) for x in pivot.columns])
    ax.set_yticks(np.arange(len(pivot.index)), [str(x) for x in pivot.index])
    ax.set(xlabel=xlabel, ylabel=ylabel, title=title)
    colorbar = fig.colorbar(image, ax=ax, shrink=0.75, label=label)
    colorbar.ax.set_gid("nonmap-colorbar")
    fig.tight_layout()
    return fig, ax


def heatmap(
    frame: pd.DataFrame,
    *,
    row: str,
    column: str,
    value: str,
    title: str,
    xlabel: str,
    ylabel: str,
    colorbar_label: str | None,
    style: PublicationStyle,
) -> RenderedFigure:
    with plt.rc_context(matplotlib.RcParams(style.rc_params())):
        fig, _ = _build_heatmap_figure(
            frame,
            row=row,
            column=column,
            value=value,
            title=title,
            xlabel=xlabel,
            ylabel=ylabel,
            colorbar_label=colorbar_label,
            style=style,
        )
        return _export(fig, style)


def stacked_proportions(
    frame: pd.DataFrame,
    *,
    category: str,
    state: str,
    proportion: str,
    state_order: Sequence[str],
    title: str,
    ylabel: str,
    style: PublicationStyle,
) -> RenderedFigure:
    _require(frame, [category, state, proportion])
    categories = list(dict.fromkeys(frame[category].astype(str).tolist()))
    with plt.rc_context(matplotlib.RcParams(style.rc_params())):
        fig, ax = plt.subplots(figsize=style.single_panel)
        bottom = np.zeros(len(categories), dtype=float)
        for state_value in state_order:
            values = []
            for cat in categories:
                subset = frame.loc[
                    frame[category].astype(str).eq(cat) & frame[state].astype(str).eq(state_value),
                    proportion,
                ]
                values.append(float(subset.iloc[0]) if len(subset) else 0.0)
            ax.bar(categories, values, bottom=bottom, label=state_value)
            bottom += np.asarray(values)
        ax.set_ylim(0, 1)
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.legend(
            frameon=False,
            ncol=min(4, len(state_order)),
            loc="upper center",
            bbox_to_anchor=(0.5, -0.12),
        )
        ax.tick_params(axis="x", rotation=20)
        fig.tight_layout()
        return _export(fig, style)


def grouped_bars(
    frame: pd.DataFrame,
    *,
    category: str,
    series: str,
    value: str,
    title: str,
    ylabel: str,
    style: PublicationStyle,
) -> RenderedFigure:
    _require(frame, [category, series, value])
    categories = list(dict.fromkeys(frame[category].astype(str)))
    series_values = list(dict.fromkeys(frame[series].astype(str)))
    x = np.arange(len(categories))
    width = 0.8 / max(1, len(series_values))
    with plt.rc_context(matplotlib.RcParams(style.rc_params())):
        fig, ax = plt.subplots(figsize=style.single_panel)
        for i, s in enumerate(series_values):
            vals = [
                (
                    float(
                        frame.loc[
                            frame[category].astype(str).eq(c) & frame[series].astype(str).eq(s),
                            value,
                        ].iloc[0]
                    )
                    if not frame.loc[
                        frame[category].astype(str).eq(c) & frame[series].astype(str).eq(s)
                    ].empty
                    else np.nan
                )
                for c in categories
            ]
            ax.bar(x + (i - (len(series_values) - 1) / 2) * width, vals, width=width, label=s)
        ax.set_xticks(x, categories, rotation=20)
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.legend(frameon=False)
        ax.grid(axis="y", alpha=style.grid_alpha)
        fig.tight_layout()
        return _export(fig, style)


def scatter_identity(
    frame: pd.DataFrame,
    *,
    x: str,
    y: str,
    group: str | None,
    title: str,
    xlabel: str,
    ylabel: str,
    style: PublicationStyle,
) -> RenderedFigure:
    _require(frame, [x, y] + ([group] if group else []))
    with plt.rc_context(matplotlib.RcParams(style.rc_params())):
        fig, ax = plt.subplots(figsize=style.single_panel)
        if group:
            for key, g in frame.groupby(group, sort=True, observed=True):
                ax.scatter(g[x], g[y], s=15, alpha=0.75, label=str(key))
            ax.legend(frameon=False, fontsize=style.legend_font, ncol=2)
        else:
            ax.scatter(frame[x], frame[y], s=16, alpha=0.8)
        finite = np.concatenate(
            [
                pd.to_numeric(frame[x], errors="coerce").dropna().to_numpy(),
                pd.to_numeric(frame[y], errors="coerce").dropna().to_numpy(),
            ]
        )
        if finite.size:
            lo, hi = float(np.min(finite)), float(np.max(finite))
            ax.plot([lo, hi], [lo, hi], linestyle="--", linewidth=0.8)
        ax.set(xlabel=xlabel, ylabel=ylabel, title=title)
        ax.grid(alpha=style.grid_alpha)
        fig.tight_layout()
        return _export(fig, style)


def coefficient_or_plot(
    frame: pd.DataFrame,
    *,
    title: str,
    xlabel: str,
    style: PublicationStyle,
    label: str = "term",
    estimate: str = "odds_ratio",
    low: str = "or_ci95_low",
    high: str = "or_ci95_high",
    order: str | None = None,
) -> RenderedFigure:
    """Render a configured adjusted-odds-ratio forest plot.

    Column identities are supplied by configuration; this renderer owns only
    generic plotting mechanics.
    """
    required = [label, estimate, low, high] + ([order] if order else [])
    _require(frame, required)
    work = frame.sort_values(order).reset_index(drop=True) if order else frame.reset_index(drop=True)
    with plt.rc_context(matplotlib.RcParams(style.rc_params())):
        fig, ax = plt.subplots(figsize=style.wide_single_panel)
        y = np.arange(len(work))
        est = pd.to_numeric(work[estimate], errors="raise").to_numpy(float)
        lo = pd.to_numeric(work[low], errors="raise").to_numpy(float)
        hi = pd.to_numeric(work[high], errors="raise").to_numpy(float)
        if np.any(est <= 0) or np.any(lo <= 0) or np.any(hi <= 0):
            raise FigureRenderError("Odds-ratio forest plot requires strictly positive estimates and intervals")
        ax.errorbar(est, y, xerr=np.vstack((est - lo, hi - est)), fmt="o", capsize=3)
        ax.axvline(1.0, linestyle="--", linewidth=0.8)
        ax.set_xscale("log")
        ax.set_yticks(y, work[label].astype(str))
        ax.invert_yaxis()
        ax.set_xlabel(xlabel)
        ax.set_title(title)
        ax.grid(axis="x", alpha=style.grid_alpha)
        fig.tight_layout()
        return _export(fig, style)


def trajectory_with_sen(
    frame: pd.DataFrame,
    *,
    x: str,
    y: str,
    group: str,
    slope: str,
    title: str,
    xlabel: str,
    ylabel: str,
    style: PublicationStyle,
    panel_count: int,
    figure_size: tuple[float, float],
    panel_xlabels: Sequence[str | None],
    panel_ylabels: Sequence[str | None],
    annotation_fields: Sequence[str] = ("sen_slope", "raw_p", "bh_q"),
) -> RenderedFigure:
    """Render five governed ACZ trajectories with Sen lines and inferential annotations.

    No interval is estimated or drawn here.  The renderer consumes the point
    slope, studentised-permutation raw p-value and BH q-value already present
    in the qualified RQ2 figure source.
    """
    _require(frame, [x, y, group, slope, *annotation_fields])
    groups = list(dict.fromkeys(frame[group].astype(str).tolist()))
    if len(groups) != panel_count:
        raise FigureRenderError(
            f"RQ2 small-multiple renderer requires the configured {panel_count} groups; got {len(groups)}"
        )
    if len(panel_xlabels) != panel_count or len(panel_ylabels) != panel_count:
        raise FigureRenderError("RQ2 panel label arrays must match configured panel_count")
    with plt.rc_context(matplotlib.RcParams(style.rc_params())):
        fig, axes = plt.subplots(panel_count, 1, figsize=figure_size, sharex=True)
        axes = np.atleast_1d(axes)
        if len(axes) != panel_count:
            raise FigureRenderError("Rendered RQ2 axes do not match configured panel_count")
        for idx, (ax, key) in enumerate(zip(axes, groups, strict=True)):
            g = frame.loc[frame[group].astype(str).eq(key)].sort_values(x)
            xv = pd.to_numeric(g[x], errors="raise").to_numpy(float)
            yv = pd.to_numeric(g[y], errors="raise").to_numpy(float)
            b = pd.to_numeric(g[slope], errors="raise").to_numpy(float)
            raw_p = pd.to_numeric(g[annotation_fields[1]], errors="raise").to_numpy(float)
            q = pd.to_numeric(g[annotation_fields[2]], errors="raise").to_numpy(float)
            if not (np.isfinite(xv).all() and np.isfinite(yv).all() and np.isfinite(b).all() and np.isfinite(raw_p).all() and np.isfinite(q).all()):
                raise FigureRenderError("RQ2 trajectory source contains non-finite values")
            if not (np.allclose(b, b[0]) and np.allclose(raw_p, raw_p[0]) and np.allclose(q, q[0])):
                raise FigureRenderError("Each ACZ trajectory must carry one governed slope, p and q")
            ax.plot(xv, yv, marker="o", markersize=2.2, linewidth=0.8)
            # Presentation-only line anchoring; the governed slope itself is not re-estimated.
            anchor_x = float(np.mean(xv))
            anchor_y = float(np.mean(yv))
            xx = np.asarray([float(np.min(xv)), float(np.max(xv))])
            ax.plot(xx, anchor_y + float(b[0]) * (xx - anchor_x), linewidth=1.2)
            ax.text(
                0.015, 0.95,
                f"{key}   Sen slope={b[0]:.3f}; p={raw_p[0]:.4f}; q={q[0]:.4f}",
                transform=ax.transAxes, ha="left", va="top", fontsize=style.tick_font,
            )
            ax.text(-0.02, 1.02, panel_label(idx), transform=ax.transAxes, ha="right", va="bottom", fontweight=style.panels.label_weight, fontsize=style.panel_label_font)
            ax.grid(alpha=style.grid_alpha)
            ax.set_ylabel(str(panel_ylabels[idx] or ""))
            ax.set_xlabel(str(panel_xlabels[idx] or ""))
        axes[-1].set_xlabel(str(panel_xlabels[-1] or xlabel))
        if title:
            fig.suptitle(title)
        fig.text(0.01, 0.5, ylabel, rotation=90, va="center", fontsize=style.axis_label_font)
        fig.tight_layout(rect=(0.04, 0.01, 1, 0.99))
        return _export(fig, style)


def seasonality_lines(
    frame: pd.DataFrame,
    *,
    title: str,
    xlabel: str,
    ylabel: str,
    style: PublicationStyle,
    figure_size: tuple[float, float] | None = None,
    zone_order: Sequence[str] | None = None,
    zone_colours: Mapping[str, str] | None = None,
) -> RenderedFigure:
    """Render governed ACZ climatologies with circular timing/concentration labels."""
    with plt.rc_context(matplotlib.RcParams(style.rc_params())):
        fig, ax = plt.subplots(figsize=figure_size or style.wide_single_panel)
        fig.subplots_adjust(left=0.13, right=0.94, bottom=0.08, top=0.91 if title else 0.93)
        banded = build_vertical_band_axes(
            fig, ax, band_fraction=0.21, gap_fraction=0.11, gid_prefix="acz-seasonality",
        )
        try:
            draw_seasonality_lines(
                ax, frame, xlabel=xlabel, ylabel=ylabel, style=style,
                legend_ax=banded.band_ax, legend_ncol=2,
                zone_order=zone_order, zone_colours=zone_colours,
            )
            if title:
                ax.set_title(title)
            ensure_vertical_band_xlabel_clearance(fig, banded)
            return export_figure(fig, style)
        except Exception:
            plt.close(fig)
            raise




def district_seasonal_diagnostics(
    frame: pd.DataFrame,
    *,
    style: PublicationStyle,
    panel_count: int,
    figure_size: tuple[float, float],
    panel_xlabels: Sequence[str | None],
    panel_ylabels: Sequence[str | None],
) -> RenderedFigure:
    """Render full district monthly shares, circular mean month and resultant length."""
    pivot, summary = district_seasonal_components(frame)
    if panel_count != 3:
        raise FigureRenderError("District seasonal diagnostics require the configured three-panel structure")
    if len(panel_xlabels) != panel_count or len(panel_ylabels) != panel_count:
        raise FigureRenderError("District seasonal panel label arrays must match configured panel_count")
    with plt.rc_context(matplotlib.RcParams(style.rc_params())):
        fig, axes = plt.subplots(
            panel_count, 1, figsize=figure_size, gridspec_kw={"height_ratios": [2.4, 1.0, 1.0]},
        )
        xlabels = [str(label or "") for label in panel_xlabels]
        ylabels = [str(label or "") for label in panel_ylabels]
        image = draw_district_seasonal_heatmap(axes[0], pivot, xlabel=xlabels[0], ylabel=ylabels[0])
        colorbar = fig.colorbar(image, ax=axes[0], orientation="horizontal", fraction=0.04, pad=0.08)
        label_district_share_colorbar(colorbar, image)
        draw_circular_mean_timing(axes[1], summary, xlabel=xlabels[1], ylabel=ylabels[1], style=style)
        draw_resultant_length_by_group(axes[2], summary, xlabel=xlabels[2], ylabel=ylabels[2])
        for idx,ax in enumerate(axes):
            ax.text(-0.02,1.02,panel_label(idx),transform=ax.transAxes,ha="right",va="bottom",fontweight=style.panels.label_weight,fontsize=style.panel_label_font)
            ax.grid(alpha=style.grid_alpha if idx else 0)
        fig.tight_layout()
        return _export(fig,style)

def probability_plot(
    frame: pd.DataFrame, *, title: str, xlabel: str, ylabel: str, style: PublicationStyle
) -> RenderedFigure:
    _require(frame, ["varied_predictor", "raw_value", "predicted_probability"])
    with plt.rc_context(matplotlib.RcParams(style.rc_params())):
        fig, ax = plt.subplots(figsize=style.wide_single_panel)
        for key, g in frame.groupby("varied_predictor", sort=True, observed=True):
            ax.plot(g["raw_value"], g["predicted_probability"], marker="o", label=str(key))
        ax.set_ylim(0, 1)
        ax.set(xlabel=xlabel, ylabel=ylabel, title=title)
        ax.grid(alpha=style.grid_alpha)
        ax.legend(frameon=False, fontsize=style.legend_font, ncol=2)
        fig.tight_layout()
        return _export(fig, style)


def distribution_boxplot(
    frame: pd.DataFrame,
    *,
    category: str,
    value: str,
    title: str,
    ylabel: str,
    style: PublicationStyle,
    xlabel: str | None = None,
) -> RenderedFigure:
    _require(frame, [category, value])
    groups = [
        (str(k), pd.to_numeric(g[value], errors="raise").to_numpy(float))
        for k, g in frame.groupby(category, sort=True, observed=True)
    ]
    with plt.rc_context(matplotlib.RcParams(style.rc_params())):
        fig, ax = plt.subplots(figsize=style.single_panel)
        ax.boxplot([v for _, v in groups], tick_labels=[k for k, _ in groups], showfliers=False)
        ax.set(xlabel=xlabel or "", ylabel=ylabel, title=title)
        ax.tick_params(axis="x", rotation=20)
        ax.grid(axis="y", alpha=style.grid_alpha)
        fig.tight_layout()
        return _export(fig, style)


def observation_framework(
    frame: pd.DataFrame, *, title: str, style: PublicationStyle
) -> RenderedFigure:
    _require(frame, ["node", "label", "x", "y", "kind"])
    with plt.rc_context(matplotlib.RcParams(style.rc_params())):
        fig, ax = plt.subplots(figsize=style.wide_single_panel)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        position_values = frame.loc[:, ["x", "y"]].to_numpy(dtype=np.float64)
        positions = {
            str(node): (float(coords[0]), float(coords[1]))
            for node, coords in zip(frame["node"], position_values, strict=True)
        }
        node_artists = {}
        for r in frame.itertuples():
            x, y = positions[str(r.node)]
            node_artists[str(r.node)] = ax.text(
                x,
                y,
                str(r.label),
                ha="center",
                va="center",
                bbox={"boxstyle": "round,pad=0.4", "facecolor": "white", "edgecolor": "0.35"},
            )
        edges = [
            ("viirs", "condition"),
            ("ba", "condition"),
            ("modisaf", "corroboration"),
            ("condition", "outcome"),
            ("corroboration", "outcome"),
        ]
        for a, b in edges:
            if a in positions and b in positions:
                source_patch = node_artists[a].get_bbox_patch()
                target_patch = node_artists[b].get_bbox_patch()
                if source_patch is None or target_patch is None:
                    raise FigureRenderError(
                        "Observation-framework nodes require bounding-box patches"
                    )
                ax.annotate(
                    "",
                    xy=positions[b],
                    xytext=positions[a],
                    arrowprops={
                        "arrowstyle": "->",
                        "linewidth": 0.9,
                        "patchA": source_patch,
                        "patchB": target_patch,
                        "shrinkA": 4.0,
                        "shrinkB": 4.0,
                    },
                )
        ax.set_title(title)
        fig.tight_layout()
        return _export(fig, style)






def horizontal_bars(
    frame: pd.DataFrame,
    *,
    label: str,
    value: str,
    title: str,
    xlabel: str,
    style: PublicationStyle,
    reference: float | None = None,
) -> RenderedFigure:
    _require(frame, [label, value])
    work = frame.reset_index(drop=True)
    with plt.rc_context(matplotlib.RcParams(style.rc_params())):
        fig, ax = plt.subplots(figsize=style.single_panel)
        y = np.arange(len(work))
        ax.barh(y, work[value].to_numpy(float))
        ax.set_yticks(y, work[label].astype(str))
        ax.invert_yaxis()
        if reference is not None:
            ax.axvline(reference, linestyle="--", linewidth=0.8)
        ax.set(xlabel=xlabel, title=title)
        ax.grid(axis="x", alpha=style.grid_alpha)
        fig.tight_layout()
        return _export(fig, style)


def multi_model_or_plot(
    frame: pd.DataFrame, *, title: str, xlabel: str, style: PublicationStyle
) -> RenderedFigure:
    _require(frame, ["model_name", "term", "odds_ratio", "or_ci95_low", "or_ci95_high"])
    terms = list(dict.fromkeys(frame["term"].astype(str)))
    models = list(dict.fromkeys(frame["model_name"].astype(str)))
    with plt.rc_context(matplotlib.RcParams(style.rc_params())):
        fig, ax = plt.subplots(figsize=style.wide_single_panel)
        base = np.arange(len(terms), dtype=float)
        offsets = np.linspace(-0.22, 0.22, max(1, len(models)))
        for off, model in zip(offsets, models, strict=False):
            sub = frame.loc[frame["model_name"].astype(str).eq(model)].set_index("term")
            est = sub["odds_ratio"].reindex(terms).to_numpy(dtype=np.float64)
            lo = sub["or_ci95_low"].reindex(terms).to_numpy(dtype=np.float64)
            hi = sub["or_ci95_high"].reindex(terms).to_numpy(dtype=np.float64)
            ax.errorbar(
                est,
                base + off,
                xerr=np.vstack((est - lo, hi - est)),
                fmt="o",
                capsize=2,
                label=model,
            )
        ax.axvline(1.0, linestyle="--", linewidth=0.8)
        ax.set_xscale("log")
        ax.set_yticks(base, terms)
        ax.invert_yaxis()
        ax.set(xlabel=xlabel, title=title)
        ax.grid(axis="x", alpha=style.grid_alpha)
        ax.legend(frameon=False, fontsize=style.legend_font)
        fig.tight_layout()
        return _export(fig, style)


# ---------------------------------------------------------------------------
# Direct axis-level drawing primitives used by GridSpec composites.
# These functions consume governed figure-source values and never calculate
# study statistics.  Parent renderers own Figure/GridSpec creation and export.
# ---------------------------------------------------------------------------

def acz_line_style(
    zone: str, *, colour: str, width: float,
) -> dict:
    """Use the same redundant ACZ line and point encodings in every panel."""
    marker, linestyle = ACZ_SERIES_STYLES[zone]
    effects = []
    if zone in {"CZ", "GS"}:
        effects = [patheffects.Stroke(linewidth=width + 0.5, foreground="#4B5260"), patheffects.Normal()]
    return {
        "color": colour,
        "marker": marker,
        "linestyle": linestyle,
        "linewidth": width,
        "markeredgecolor": "#4B5260",
        "markeredgewidth": 0.35,
        "path_effects": effects,
    }


def draw_seasonality_lines(
    ax: Axes,
    frame: pd.DataFrame,
    *,
    xlabel: str,
    ylabel: str,
    style: PublicationStyle,
    legend_ax: Axes | None = None,
    legend_ncol: int = 3,
    compact_legend: bool = False,
    zone_order: Sequence[str] | None = None,
    zone_colours: Mapping[str, str] | None = None,
) -> None:
    _require(frame, ["unit_name", "month", "value", "circular_mean_month", "mean_resultant_length"])
    has_zone_codes = "parent_code" in frame
    zone_codes = frame["parent_code" if has_zone_codes else "unit_name"].astype(str)
    order = tuple(sorted(zone_codes.unique())) if zone_order is None else tuple(zone_order)
    if len(order) != len(set(order)) or set(zone_codes) != set(order):
        raise FigureRenderError("ACZ seasonality categories do not match configured order")
    if zone_colours is not None and not set(order).issubset(zone_colours):
        raise FigureRenderError("ACZ seasonality palette does not cover all configured zones")
    style_order = tuple(ACZ_SERIES_STYLES)
    for index, zone in enumerate(order):
        group = frame.loc[zone_codes.eq(zone)].sort_values("month")
        months = pd.to_numeric(group["month"], errors="raise").to_numpy(float)
        if not np.array_equal(months, np.arange(1, 13)):
            raise FigureRenderError(f"ACZ seasonality {zone!r} must contain months 1–12 exactly once")
        names = group["unit_name"].astype(str).unique()
        if len(names) != 1:
            raise FigureRenderError(f"ACZ seasonality {zone!r} has inconsistent zone names")
        values = pd.to_numeric(group["value"], errors="raise").to_numpy(float)
        mu = pd.to_numeric(group["circular_mean_month"], errors="raise").to_numpy(float)
        resultant = pd.to_numeric(group["mean_resultant_length"], errors="raise").to_numpy(float)
        if not np.isfinite(np.concatenate((values, mu, resultant))).all():
            raise FigureRenderError(f"ACZ seasonality {zone!r} contains non-finite source values")
        if not (np.allclose(mu, mu[0]) and np.allclose(resultant, resultant[0])):
            raise FigureRenderError(f"ACZ seasonality circular summaries vary within {zone!r}")
        style_zone = zone if zone in ACZ_SERIES_STYLES else style_order[index % len(style_order)]
        colour = zone_colours[zone] if zone_colours is not None else style.acz_colours[style_zone]
        name = names[0].title()
        label = (zone if has_zone_codes else name) if compact_legend else f"{name} (μ={mu[0]:.2f}, R={resultant[0]:.3f})"
        ax.plot(
            months,
            values,
            markersize=3.0,
            label=label,
            **acz_line_style(style_zone, colour=colour, width=max(1.0, style.line_width)),
        )
    ax.set_xticks(range(1, 13))
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    if compact_legend:
        ax.grid(False)
    else:
        ax.grid(alpha=style.grid_alpha)
    line_count = max(1, len(ax.lines))
    target_ax = legend_ax if legend_ax is not None else ax
    if legend_ax is not None:
        legend_ax.set_axis_off()
    legend = target_ax.legend(
        handles=ax.lines,
        labels=[line.get_label() for line in ax.lines],
        frameon=False,
        fontsize=style.legend_font,
        ncol=max(1, min(int(legend_ncol), line_count)),
        loc="center",
        handlelength=1.5,
        columnspacing=0.8,
        borderaxespad=0.0,
        title=None if compact_legend else style.circular_mean_month_display.legend_title,
    )
    legend.set_gid("acz-seasonality-legend")


def draw_stacked_proportions(
    ax: Axes,
    frame: pd.DataFrame,
    *,
    category: str,
    state: str,
    proportion: str,
    state_order: Sequence[str],
    ylabel: str,
    style: PublicationStyle,
    legend_ax: Axes | None = None,
    display_aliases: Mapping[str, str] | None = None,
    legend_ncol: int = 2,
    legend_loc: str = "center",
    state_styles: Mapping[str, Mapping[str, str]] | None = None,
    show_percent: bool = False,
) -> None:
    _require(frame, [category, state, proportion])
    categories = list(dict.fromkeys(frame[category].astype(str).tolist()))
    bottom = np.zeros(len(categories), dtype=float)
    for state_value in state_order:
        values: list[float] = []
        for cat in categories:
            subset = frame.loc[
                frame[category].astype(str).eq(cat) & frame[state].astype(str).eq(state_value),
                proportion,
            ]
            values.append(float(subset.iloc[0]) if len(subset) else 0.0)
        aliases = display_aliases or {}
        display_label = str(aliases.get(str(state_value), str(state_value).replace("_", " ")))
        bar_style = {"linewidth": 0.4, **(state_styles or {}).get(str(state_value), {})}
        ax.bar(categories, values, bottom=bottom, label=display_label, **bar_style)
        bottom += np.asarray(values)
    ax.set_ylim(0, 1)
    if show_percent:
        ax.set_yticks((0.0, 0.25, 0.5, 0.75, 1.0))
        ax.yaxis.set_major_formatter(PercentFormatter(xmax=1, decimals=0))
    ax.set_ylabel(ylabel)
    target_ax = legend_ax if legend_ax is not None else ax
    if legend_ax is not None:
        legend_ax.set_axis_off()
    handles, labels = ax.get_legend_handles_labels()
    legend = target_ax.legend(
        handles=handles,
        labels=labels,
        frameon=False,
        fontsize=style.legend_font,
        ncol=max(1, min(int(legend_ncol), len(state_order))),
        loc=legend_loc,
        handlelength=1.6,
        columnspacing=0.8,
        borderaxespad=0.0,
    )
    legend.set_gid("f5-state-legend")
    ax.tick_params(axis="x", rotation=0 if show_percent else 20)


def draw_coefficient_or_plot(
    ax: Axes,
    frame: pd.DataFrame,
    *,
    xlabel: str,
    style: PublicationStyle,
    label: str = "term",
    estimate: str = "odds_ratio",
    low: str = "or_ci95_low",
    high: str = "or_ci95_high",
    order: str | None = None,
    label_ax: Axes | None = None,
    display_aliases: Mapping[str, str] | None = None,
    vertical_padding_rows: float = 0.0,
    decimal_ticks: Sequence[float] = (),
    estimate_color: str | None = None,
    reference_color: str | None = None,
) -> None:
    required = [label, estimate, low, high] + ([order] if order else [])
    _require(frame, required)
    work = frame.sort_values(order).reset_index(drop=True) if order else frame.reset_index(drop=True)
    y = np.arange(len(work))
    est = pd.to_numeric(work[estimate], errors="raise").to_numpy(float)
    lo = pd.to_numeric(work[low], errors="raise").to_numpy(float)
    hi = pd.to_numeric(work[high], errors="raise").to_numpy(float)
    if np.any(est <= 0) or np.any(lo <= 0) or np.any(hi <= 0):
        raise FigureRenderError("Odds-ratio forest plot requires strictly positive estimates and intervals")
    artist = ax.errorbar(
        est, y, xerr=np.vstack((est - lo, hi - est)), fmt="o", capsize=3, color=estimate_color,
    )
    if artist.lines:
        artist.lines[0].set_gid("f5-focal-effect-estimates")
    null_line = ax.axvline(1.0, linestyle="--", linewidth=0.8, color=reference_color, zorder=1)
    null_line.set_gid("f5-focal-effect-null")
    ax.set_xscale("log")
    aliases = display_aliases or {}
    display_labels = [str(aliases.get(str(value), str(value))) for value in work[label].astype(str)]
    if label_ax is None:
        ax.set_yticks(y, [textwrap.fill(value, width=22) for value in display_labels])
    else:
        ax.set_yticks(y, [""] * len(display_labels))
    ax.invert_yaxis()
    apply_row_vertical_padding(
        ax,
        row_count=len(work),
        padding_rows=vertical_padding_rows,
    )
    ax.set_xlabel(xlabel)
    if decimal_ticks:
        ticks = tuple(float(value) for value in decimal_ticks)
        if not np.isfinite(ticks).all() or any(value <= 0 for value in ticks) or 1.0 not in ticks:
            raise FigureRenderError("Log odds-ratio ticks must be positive and include the 1.0 reference")
        ax.set_xticks(ticks, [f"{value:g}" if value != 1 else "1.0" for value in ticks])
        ax.xaxis.set_minor_locator(NullLocator())
        ax.xaxis.set_minor_formatter(NullFormatter())
        ax.set_xlim(min(float(lo.min()), min(ticks)) / 1.06, max(float(hi.max()), max(ticks)) * 1.06)
    else:
        ax.grid(axis="x", alpha=style.grid_alpha)
    if label_ax is not None:
        label_ax.set_axis_off()
        label_ax.set_ylim(ax.get_ylim())
        label_ax.set_xlim(0.0, 1.0)
        for index, (yy, text) in enumerate(zip(y, display_labels, strict=True)):
            label_ax.text(
                0.98,
                float(yy),
                text,
                transform=label_ax.get_yaxis_transform(),
                ha="right",
                va="center",
                fontsize=style.tick_font,
                gid=f"f5-effect-label-{index}",
                clip_on=True,
            )


def draw_trajectory_panel(
    ax: Axes,
    frame: pd.DataFrame,
    *,
    x: str,
    y: str,
    slope: str,
    annotation_fields: Sequence[str],
    group_label: str,
    xlabel: str,
    ylabel: str,
    style: PublicationStyle,
    trajectory_styles: Mapping[str, Mapping[str, object]] | None = None,
    common_y_limits: tuple[float, float] | None = None,
    show_group_title: bool = True,
) -> tuple[float, float, float]:
    _require(frame, [x, y, slope, *annotation_fields])
    g = frame.sort_values(x)
    xv = pd.to_numeric(g[x], errors="raise").to_numpy(float)
    yv = pd.to_numeric(g[y], errors="raise").to_numpy(float)
    b = pd.to_numeric(g[slope], errors="raise").to_numpy(float)
    raw_p = pd.to_numeric(g[annotation_fields[1]], errors="raise").to_numpy(float)
    q = pd.to_numeric(g[annotation_fields[2]], errors="raise").to_numpy(float)
    if not (
        np.isfinite(xv).all()
        and np.isfinite(yv).all()
        and np.isfinite(b).all()
        and np.isfinite(raw_p).all()
        and np.isfinite(q).all()
    ):
        raise FigureRenderError("RQ2 trajectory source contains non-finite values")
    if not (np.allclose(b, b[0]) and np.allclose(raw_p, raw_p[0]) and np.allclose(q, q[0])):
        raise FigureRenderError("Each trajectory must carry one governed slope, p and q")
    configured = trajectory_styles or {}
    observed_style = dict(configured.get("observed_series", {}))
    slope_style = dict(configured.get("sen_slope", {}))
    observed_style.setdefault("marker", "o")
    observed_style.setdefault("markersize", 2.2)
    observed_style.setdefault("linewidth", 0.8)
    observed_line = ax.plot(xv, yv, **observed_style)[0]
    observed_line.set_gid("f4-observed-series")
    anchor_x = float(np.mean(xv))
    anchor_y = float(np.mean(yv))
    xx = np.asarray([float(np.min(xv)), float(np.max(xv))])
    slope_style.setdefault("linewidth", 1.2)
    slope_line = ax.plot(xx, anchor_y + float(b[0]) * (xx - anchor_x), **slope_style)[0]
    slope_line.set_gid("f4-sen-slope")
    ax.set_axisbelow(True)
    ax.grid(axis="y", color="0.65", alpha=style.grid_alpha)
    if common_y_limits is None:
        ax.text(
            0.015,
            0.95,
            f"{group_label}\nSen slope={b[0]:.3f}; p={raw_p[0]:.4f}; q={q[0]:.4f}",
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=style.tick_font,
        )
    else:
        ax.set_ylim(*common_y_limits)
        if show_group_title:
            ax.set_title(group_label.title(), loc="center", fontsize=style.tick_font, pad=3)
        else:
            ax.text(
                0.02,
                1.0 + style.geometry.panel_label_offset_y,
                group_label.title(),
                transform=ax.transAxes,
                ha="left",
                va="bottom",
                fontsize=style.tick_font,
                gid="trajectory-panel-group",
            )
        first_year = int(xv[0])
        last_year = int(xv[-1])
        year_ticks = [first_year, *range(first_year + 5, last_year - 1, 5), last_year]
        ax.set_xticks(year_ticks)
        ax.set_xlim(first_year - 0.45, last_year + 0.45)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    return float(b[0]), float(raw_p[0]), float(q[0])


def common_trajectory_y_limits(
    frame: pd.DataFrame, *, group: str, x: str, y: str, slope: str,
) -> tuple[float, float]:
    """Fit a common display range around observed rates and all rendered line endpoints."""
    observed = pd.to_numeric(frame[y], errors="raise")
    minimum, maximum = float(observed.min()), float(observed.max())
    for _, series in frame.groupby(group, sort=False, observed=True):
        years = pd.to_numeric(series[x], errors="raise")
        mean_rate = float(pd.to_numeric(series[y], errors="raise").mean())
        coefficient = float(series[slope].iloc[0])
        endpoints = mean_rate + coefficient * (np.array([years.min(), years.max()]) - years.mean())
        minimum = min(minimum, float(endpoints.min()))
        maximum = max(maximum, float(endpoints.max()))
    return min(0.0, 5.0 * math.floor(minimum / 5.0)), max(5.0, 5.0 * math.ceil(maximum / 5.0))


def draw_shared_trajectory_key(
    ax: Axes,
    *,
    entries: Sequence[dict[str, str]],
    style: PublicationStyle,
    trajectory_styles: Mapping[str, Mapping[str, object]] | None = None,
    statistics: Sequence[tuple[str, tuple[float, float, float]]] = (),
) -> None:
    """Render the shared key and optional governed statistics in the auxiliary cell."""
    handles: list[Line2D] = []
    labels: list[str] = []
    configured = trajectory_styles or {}
    observed_style = dict(configured.get("observed_series", {}))
    slope_style = dict(configured.get("sen_slope", {}))
    # Preserve the established Matplotlib first/second-series semantics when
    # no explicit trajectory colours are supplied, while allowing the figure
    # contract to override them in production.  Line2D objects created outside
    # an Axes do not advance the Axes property cycle automatically.
    cycle_colours = plt.rcParams["axes.prop_cycle"].by_key().get("color", [])
    if cycle_colours:
        observed_style.setdefault("color", cycle_colours[0])
        slope_style.setdefault("color", cycle_colours[1 if len(cycle_colours) > 1 else 0])
    for entry in entries:
        kind = str(entry.get("kind", ""))
        label = str(entry.get("label", "")).strip()
        if not label:
            raise FigureRenderError("Shared trajectory key entries require non-empty labels")
        if kind == "observed_series":
            observed_style.setdefault("marker", "o")
            observed_style.setdefault("markersize", 3.0)
            observed_style.setdefault("linewidth", 0.8)
            handle = Line2D([], [], **observed_style)
        elif kind == "sen_slope":
            slope_style.setdefault("linewidth", 1.2)
            handle = Line2D([], [], **slope_style)
        else:
            raise FigureRenderError(f"Unsupported shared trajectory key kind {kind!r}")
        handles.append(handle); labels.append(label)
    if not handles:
        raise FigureRenderError("Shared trajectory key requires at least one entry")
    ax.set_axis_off()
    if not statistics:
        ax.legend(handles, labels, loc="center", frameon=False, fontsize=style.legend_font)
        return

    legend = ax.legend(
        handles,
        labels,
        loc="upper left",
        bbox_to_anchor=(0.025, 0.97),
        borderaxespad=0.0,
        ncol=len(handles),
        frameon=False,
        handlelength=1.65,
        columnspacing=1.1,
        fontsize=style.legend_font,
    )
    legend.set_gid("f4-shared-key")
    summary = ax.table(
        cellText=[
            (f"{panel_label(index)} {name.title()}", f"{slope:.3f}", f"{raw_p:.4f}", f"{q:.4f}")
            for index, (name, (slope, raw_p, q)) in enumerate(statistics)
        ],
        colLabels=("ACZ", "Sen slope", "Raw p", "BH q"),
        cellLoc="right",
        colLoc="right",
        colWidths=(0.44, 0.24, 0.16, 0.16),
        bbox=(0.025, 0.015, 0.95, 0.77),
    )
    summary.set_gid("f4-statistics-below-key")
    summary.auto_set_font_size(False)
    summary.set_fontsize(style.legend_font)
    for (row, column), cell in summary.get_celld().items():
        cell.set_facecolor("#e8e8e8" if row == 0 else "#f5f5f5")
        cell.set_edgecolor("#d1d3d4")
        cell.set_linewidth(0.4)
        cell.PAD = 0.03
        if row == 0:
            cell.get_text().set_fontweight("bold")
        if column == 0:
            cell.get_text().set_ha("left")


def district_seasonal_components(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return presentation-only matrix/summary projections from governed source rows."""
    _require(frame, ["record_type", "unit_id", "unit_name", "parent_code", "month", "monthly_share", "circular_mean_month", "mean_resultant_length"])
    work = frame.loc[frame["record_type"].astype(str).eq("monthly_share")].copy()
    if work.empty:
        raise FigureRenderError("District seasonal source contains no monthly-share rows")
    summary = work.drop_duplicates("unit_id")[["unit_id", "unit_name", "parent_code", "circular_mean_month", "mean_resultant_length"]].copy()
    order = summary.sort_values(["parent_code", "circular_mean_month", "unit_name"])["unit_id"].tolist()
    pivot = work.pivot(index="unit_id", columns="month", values="monthly_share").reindex(
        index=order, columns=range(1, 13),
    )
    summary = summary.set_index("unit_id").reindex(order).reset_index()
    return pivot, summary


def draw_district_seasonal_heatmap(
    ax: Axes,
    pivot: pd.DataFrame,
    *,
    xlabel: str,
    ylabel: str,
):
    values = pivot.to_numpy(dtype=float, na_value=np.nan)
    if np.isinf(values).any() or np.any((values < 0.0) | (values > 1.0)):
        raise FigureRenderError("Governed district monthly shares must remain within 0–1")
    image = ax.imshow(
        np.ma.masked_invalid(values), aspect="auto", interpolation="nearest",
        cmap=matplotlib.colormaps["viridis_r"].with_extremes(bad="#FFFFFF"),
        vmin=0.0, vmax=1.0,
    )
    ax.set_xticks(np.arange(12), [str(i) for i in range(1, 13)])
    ax.set_yticks([])
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    return image


def label_district_share_colorbar(colorbar, image) -> None:
    """Key the masked cells independently of the quantitative share scale."""
    colorbar.set_ticks((0.0, 0.25, 0.5, 0.75, 1.0))
    label = "Share of district long-run burned area"
    if np.ma.getmaskarray(image.get_array()).any():
        label += "\nWhite = undefined share"
    colorbar.set_label(label)


def draw_circular_mean_timing(
    ax: Axes,
    summary: pd.DataFrame,
    *,
    xlabel: str,
    ylabel: str,
    style: PublicationStyle,
) -> None:
    y = np.arange(len(summary))
    values = pd.to_numeric(summary["circular_mean_month"], errors="coerce")
    finite = np.isfinite(values.to_numpy(float, na_value=np.nan))
    ax.scatter(values.loc[finite], y[finite], s=7, color="#30343B")
    convention = style.circular_mean_month_display
    ax.set_xlim(convention.axis_min, convention.axis_max)
    ax.set_xticks(convention.ticks, convention.tick_labels)
    ax.set_yticks([])
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)


def draw_resultant_length_by_group(
    ax: Axes,
    summary: pd.DataFrame,
    *,
    xlabel: str,
    ylabel: str,
    zone_order: Sequence[str] | None = None,
) -> None:
    groups: list[np.ndarray] = []
    zone_codes = summary["parent_code"].astype(str)
    labels = list(sorted(set(zone_codes)) if zone_order is None else zone_order)
    for code in labels:
        group = summary.loc[zone_codes.eq(code), "mean_resultant_length"]
        values = pd.to_numeric(group, errors="coerce").dropna().to_numpy(float)
        if zone_order is not None and values.size == 0:
            raise FigureRenderError(f"No finite governed resultant-length values for ACZ {code!r}")
        if np.any((values < 0.0) | (values > 1.0)):
            raise FigureRenderError("Governed mean resultant length must remain within 0–1")
        groups.append(values)
    ax.boxplot(
        groups, tick_labels=labels, showfliers=False, patch_artist=True,
        boxprops={"facecolor": "#E8E8E8", "edgecolor": "#646A73"},
        medianprops={"color": "#30343B", "linewidth": 1.25},
        whiskerprops={"color": "#646A73"}, capprops={"color": "#646A73"},
    )
    ax.set_ylim(0.0, 1.0)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)


def export_figure(fig, style: PublicationStyle) -> RenderedFigure:
    """Export a parent-owned figure without cropping the governed canvas."""
    ensure_axis_labels_inside_canvas(fig, tuple(fig.axes))
    ensure_axis_titles_inside_canvas(fig, tuple(fig.axes))
    return _export(fig, style)
