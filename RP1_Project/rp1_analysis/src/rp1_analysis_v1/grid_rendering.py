"""Generic, configuration-owned GridSpec figure construction.

This module owns only presentation geometry.  It does not know study-specific
semantics or publication numbers.  Scientific/data panels are ordered by the
``panel_index`` values in ``figure_contract.yml``; auxiliary cells are separate
and never count as scientific panels.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from types import MappingProxyType
from typing import Mapping

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from .contracts import GridLayoutContract
from .style import PublicationStyle, panel_label


class GridRenderError(ValueError):
    """Raised when a governed grid cannot be realised safely."""


@dataclass(frozen=True, slots=True)
class GridFigureAxes:
    figure: Figure
    data_axes: tuple[Axes, ...]
    auxiliary_axes: Mapping[str, Axes]


@dataclass(frozen=True, slots=True)
class VerticalBandAxes:
    """One plot region with a separately reserved band below it."""

    plot_ax: Axes
    band_ax: Axes
    original_cell_bounds: tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class HorizontalGutterAxes:
    """One plot region with an independently reserved label gutter to its left."""

    label_ax: Axes
    plot_ax: Axes
    original_cell_bounds: tuple[float, float, float, float]


def apply_row_vertical_padding(
    ax: Axes,
    *,
    row_count: int,
    padding_rows: float,
) -> None:
    """Apply symmetric row-unit y padding without changing x-axis data geometry."""

    if isinstance(row_count, bool) or not isinstance(row_count, int) or row_count < 1:
        raise GridRenderError("row_count must be a positive integer")
    if isinstance(padding_rows, bool) or not isinstance(padding_rows, (int, float)):
        raise GridRenderError("padding_rows must be numeric")
    padding = float(padding_rows)
    if not math.isfinite(padding) or padding < 0.0:
        raise GridRenderError("padding_rows must be finite and non-negative")

    lower = -padding
    upper = float(row_count - 1) + padding
    if ax.yaxis_inverted():
        ax.set_ylim(upper, lower)
    else:
        ax.set_ylim(lower, upper)


def build_vertical_band_axes(
    fig: Figure,
    plot_ax: Axes,
    *,
    band_fraction: float,
    gap_fraction: float,
    horizontal_inset_fraction: float = 0.0,
    gid_prefix: str = "vertical-band",
) -> VerticalBandAxes:
    """Reserve a deterministic lower band without letting its contents move the plot."""

    if not (0.0 < band_fraction < 1.0):
        raise GridRenderError("band_fraction must lie strictly between 0 and 1")
    if not (0.0 <= gap_fraction < 1.0):
        raise GridRenderError("gap_fraction must lie in [0, 1)")
    if band_fraction + gap_fraction >= 1.0:
        raise GridRenderError("band_fraction + gap_fraction must leave positive plot height")
    if not (0.0 <= horizontal_inset_fraction < 0.5):
        raise GridRenderError("horizontal_inset_fraction must lie in [0, 0.5)")

    x0, y0, width, height = (float(value) for value in plot_ax.get_position().bounds)
    band_h = height * band_fraction
    gap_h = height * gap_fraction
    inset = width * horizontal_inset_fraction
    plot_x = x0 + inset
    plot_w = width - 2.0 * inset
    plot_y = y0 + band_h + gap_h
    plot_h = height - band_h - gap_h
    if min(plot_w, plot_h, band_h) <= 0.0:
        raise GridRenderError("Configured vertical-band geometry is non-positive")

    plot_ax.set_position((plot_x, plot_y, plot_w, plot_h))
    plot_ax.set_gid(f"{gid_prefix}-plot")
    band_ax = fig.add_axes((x0, y0, width, band_h))
    band_ax.set_gid(f"{gid_prefix}-band")
    band_ax.set_axis_off()
    return VerticalBandAxes(
        plot_ax=plot_ax,
        band_ax=band_ax,
        original_cell_bounds=(x0, y0, width, height),
    )


def ensure_axis_labels_inside_canvas(
    fig: Figure,
    axes: tuple[Axes, ...],
) -> None:
    """Move only realised axis-label anchors by their measured canvas overflow.

    This is a generic fail-safe for long or multiline governed labels.  It does
    not resize the figure, alter data limits, change panel geometry, or apply a
    figure-specific padding constant.
    """

    if not axes:
        return
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    canvas = fig.get_window_extent(renderer)
    for ax in axes:
        for axis_name, axis in (("x", ax.xaxis), ("y", ax.yaxis)):
            label = axis.label
            if not label.get_visible() or not str(label.get_text()).strip():
                continue
            box = label.get_window_extent(renderer)
            dx = max(float(canvas.x0 - box.x0), 0.0) - max(float(box.x1 - canvas.x1), 0.0)
            dy = max(float(canvas.y0 - box.y0), 0.0) - max(float(box.y1 - canvas.y1), 0.0)
            if dx == 0.0 and dy == 0.0:
                continue
            anchor = label.get_transform().transform(label.get_position())
            target = (float(anchor[0]) + dx, float(anchor[1]) + dy)
            new_x, new_y = ax.transAxes.inverted().transform(target)
            if axis_name == "x":
                ax.xaxis.set_label_coords(float(new_x), float(new_y), transform=ax.transAxes)
            else:
                ax.yaxis.set_label_coords(float(new_x), float(new_y), transform=ax.transAxes)
    fig.canvas.draw()


def ensure_vertical_band_xlabel_clearance(
    fig: Figure,
    axes: VerticalBandAxes,
) -> None:
    """Keep a rendered x-axis label strictly above a reserved lower band.

    The configured band and gap remain the baseline geometry.  A viewport
    correction is applied only when the rendered label touches or overlaps the
    ancillary band.  Corrections are measured in renderer pixels, include a
    one-display-pixel positive-clearance reserve, and are verified after a
    redraw rather than assumed from the requested floating-point displacement.
    """

    label = axes.plot_ax.xaxis.label
    if not label.get_visible() or not str(label.get_text()).strip():
        return

    minimum_corrected_clearance_px = 1.0
    max_adjustment_attempts = 4

    for _attempt in range(max_adjustment_attempts):
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        label_box = label.get_window_extent(renderer)
        band_box = axes.band_ax.get_window_extent(renderer)
        clearance_px = float(label_box.y0 - band_box.y1)
        if not math.isfinite(clearance_px):
            raise GridRenderError("Rendered x-axis label clearance is non-finite")
        if clearance_px > 0.0:
            return

        figure_height_px = float(fig.bbox.height)
        if not math.isfinite(figure_height_px) or figure_height_px <= 0.0:
            raise GridRenderError("Figure has non-positive display height")

        required_px = -clearance_px + minimum_corrected_clearance_px
        delta = math.nextafter(required_px / figure_height_px, math.inf)
        x0, y0, width, height = (
            float(value) for value in axes.plot_ax.get_position().bounds
        )
        new_y = y0 + delta
        new_height = height - delta
        if not math.isfinite(new_y) or not math.isfinite(new_height) or new_height <= 0.0:
            raise GridRenderError("Rendered x-axis label leaves no positive plot height")
        axes.plot_ax.set_position((x0, new_y, width, new_height))

    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    label_box = label.get_window_extent(renderer)
    band_box = axes.band_ax.get_window_extent(renderer)
    final_clearance_px = float(label_box.y0 - band_box.y1)
    if not math.isfinite(final_clearance_px) or final_clearance_px <= 0.0:
        raise GridRenderError("Unable to realise strictly positive rendered x-axis label clearance")


def build_horizontal_gutter_axes(
    fig: Figure,
    plot_ax: Axes,
    *,
    label_fraction: float,
    gap_fraction: float,
    gid_prefix: str = "horizontal-gutter",
) -> HorizontalGutterAxes:
    """Reserve a left-hand label gutter that cannot intrude into neighbouring cells."""

    if not (0.0 < label_fraction < 1.0):
        raise GridRenderError("label_fraction must lie strictly between 0 and 1")
    if not (0.0 <= gap_fraction < 1.0):
        raise GridRenderError("gap_fraction must lie in [0, 1)")
    if label_fraction + gap_fraction >= 1.0:
        raise GridRenderError("label_fraction + gap_fraction must leave positive plot width")

    x0, y0, width, height = (float(value) for value in plot_ax.get_position().bounds)
    label_w = width * label_fraction
    gap_w = width * gap_fraction
    plot_x = x0 + label_w + gap_w
    plot_w = width - label_w - gap_w
    if min(label_w, plot_w, height) <= 0.0:
        raise GridRenderError("Configured horizontal-gutter geometry is non-positive")

    plot_ax.set_position((plot_x, y0, plot_w, height))
    plot_ax.set_gid(f"{gid_prefix}-plot")
    label_ax = fig.add_axes((x0, y0, label_w, height))
    label_ax.set_gid(f"{gid_prefix}-labels")
    label_ax.set_axis_off()
    return HorizontalGutterAxes(
        label_ax=label_ax,
        plot_ax=plot_ax,
        original_cell_bounds=(x0, y0, width, height),
    )


def build_grid_figure(
    layout: GridLayoutContract,
    *,
    figure_size: tuple[float, float],
) -> GridFigureAxes:
    """Create one Figure/GridSpec directly from the validated contract layout."""
    fig = plt.figure(figsize=figure_size)
    grid = fig.add_gridspec(
        layout.rows,
        layout.columns,
        width_ratios=list(layout.width_ratios),
        height_ratios=list(layout.height_ratios),
    )
    data_axes: list[Axes | None] = [None] * len(layout.data_cells)
    auxiliary: dict[str, Axes] = {}
    for cell in layout.cells:
        spec = grid[
            cell.row : cell.row + cell.row_span,
            cell.column : cell.column + cell.column_span,
        ]
        ax = fig.add_subplot(spec)
        if cell.kind == "data":
            if cell.panel_index is None or cell.panel_index >= len(data_axes):
                plt.close(fig)
                raise GridRenderError("Validated data-cell panel index cannot be realised")
            data_axes[cell.panel_index] = ax
            ax.set_gid(f"data-panel-{cell.panel_index}")
        else:
            if cell.auxiliary_id is None:
                plt.close(fig)
                raise GridRenderError("Validated auxiliary cell is missing its identity")
            ax.set_gid(f"auxiliary-cell-{cell.auxiliary_id}")
            ax.set_axis_off()
            auxiliary[cell.auxiliary_id] = ax
    if any(ax is None for ax in data_axes):
        plt.close(fig)
        raise GridRenderError("Grid layout did not realise every configured data panel")
    return GridFigureAxes(
        figure=fig,
        data_axes=tuple(ax for ax in data_axes if ax is not None),
        auxiliary_axes=MappingProxyType(auxiliary),
    )


def build_governed_grid(
    style: PublicationStyle,
    layout_role: str,
    *,
    figure_size: tuple[float, float] | None = None,
) -> GridFigureAxes:
    """Realise a named contract GridSpec using its governed physical dimensions."""
    layout = style.grid_for(layout_role)
    size = figure_size or style.dimensions_for(layout_role)
    grid = build_grid_figure(layout, figure_size=size)
    apply_grid_spacing(grid.figure, layout, style=style)
    return grid


def add_panel_labels(
    axes: tuple[Axes, ...],
    *,
    style: PublicationStyle,
) -> None:
    """Add labels to scientific/data panels only; auxiliary cells are unlabelled."""
    for index, ax in enumerate(axes):
        marker = ax.text(
            style.geometry.panel_label_offset_x,
            1.0 + style.geometry.panel_label_offset_y,
            panel_label(index),
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            fontweight=style.panels.label_weight,
            fontsize=style.panel_label_font,
            gid=f"panel-marker-{chr(ord('a') + index)}",
        )
        marker.set_clip_on(False)


def apply_grid_spacing(
    fig: Figure,
    layout: GridLayoutContract,
    *,
    style: PublicationStyle,
) -> None:
    """Apply the validated configuration-owned page margins and grid spacing."""

    geometry = style.geometry
    fig.subplots_adjust(
        left=geometry.outer_left_fraction,
        right=1.0 - geometry.outer_right_fraction,
        top=1.0 - geometry.outer_top_fraction,
        bottom=geometry.outer_bottom_fraction,
        hspace=geometry.inter_row if layout.rows > 1 else 0.0,
        wspace=geometry.inter_column if layout.columns > 1 else 0.0,
    )


def apply_axis_label_padding(axes: tuple[Axes, ...], *, style: PublicationStyle) -> None:
    """Apply configured x/y label padding without changing font sizes or page geometry."""

    for ax in axes:
        ax.xaxis.labelpad = style.geometry.xlabel_padding_pt
        ax.yaxis.labelpad = style.geometry.ylabel_padding_pt
