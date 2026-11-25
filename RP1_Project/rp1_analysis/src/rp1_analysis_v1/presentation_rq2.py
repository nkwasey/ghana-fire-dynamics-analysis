"""Standalone RQ2 presentation renderers.

These renderers consume the governed ``annual_trend_source`` only.  They do
not estimate Sen slopes, execute the Romano--Tirlea permutation test, or
recompute Benjamini--Hochberg q-values.  The only line construction performed
here is a presentation anchoring of the already-governed Sen slope.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .contracts import FigureSpecificationContract, PresentationExportSpecificationContract
from .figures import (
    FigureRenderError,
    RenderedFigure,
    common_trajectory_y_limits,
    draw_shared_trajectory_key,
    draw_trajectory_panel,
    export_figure,
)
from .grid_rendering import add_panel_labels, apply_axis_label_padding, apply_grid_spacing, build_grid_figure
from .style import PublicationStyle


class _BundleLike(Protocol):
    figure: Any
    analysis: Any


class RenderContextLike(Protocol):
    bundle: _BundleLike
    style: PublicationStyle


_RQ2_COLUMNS = (
    "parent_code",
    "parent_name",
    "year",
    "annual_rate",
    "sen_slope",
    "raw_p",
    "bh_q",
)


def _configured_years(context: RenderContextLike) -> tuple[int, ...]:
    """Resolve the declared complete-year analysis period, independently of the data."""
    try:
        window = context.bundle.analysis.study["temporal_windows"]["long_run"]
        start = pd.Period(str(window["start"]), freq="M")
        end = pd.Period(str(window["end"]), freq="M")
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        raise FigureRenderError("Configured RQ2 analysis period is unavailable or invalid") from exc
    if pd.isna(start) or pd.isna(end) or start > end or start.month != 1 or end.month != 12:
        raise FigureRenderError("RQ2 presentation requires a declared period of complete calendar years")
    return tuple(range(start.year, end.year + 1))


def _require_columns(frame: pd.DataFrame, required: Sequence[str], *, context: str) -> None:
    missing = sorted(set(required).difference(frame.columns))
    if missing:
        raise FigureRenderError(f"{context} source missing columns: {missing!r}")
    if frame.empty:
        raise FigureRenderError(f"{context} source is empty")


def _f4_spec(context: RenderContextLike) -> FigureSpecificationContract:
    matches = tuple(item for item in context.bundle.figure.figures if item.figure_id == "F4")
    if len(matches) != 1:
        raise FigureRenderError("RQ2 presentation rendering requires exactly one governed F4 contract")
    spec = matches[0]
    if spec.renderer != "grid_trajectory_with_sen" or spec.source_attribute != "annual_trend_source":
        raise FigureRenderError("Governed F4 contract is incompatible with the RQ2 presentation renderer")
    return spec


def _trajectory_styles(f4: FigureSpecificationContract) -> Mapping[str, Mapping[str, object]]:
    styles = f4.renderer_options.get("trajectory_styles", {})
    if not isinstance(styles, Mapping):
        raise FigureRenderError("Governed F4 trajectory styles are malformed")
    return styles


def _normalise_group(
    frame: pd.DataFrame, *, expected_years: tuple[int, ...], context: str,
) -> tuple[pd.DataFrame, str, str, float, float, float]:
    _require_columns(frame, _RQ2_COLUMNS, context=context)
    work = frame.loc[:, _RQ2_COLUMNS].copy()
    expected_count = len(expected_years)
    if len(work) != expected_count:
        raise FigureRenderError(f"{context} requires exactly {expected_count} annual rows; got {len(work)}")
    codes = tuple(dict.fromkeys(work["parent_code"].astype(str)))
    names = tuple(dict.fromkeys(work["parent_name"].astype(str)))
    if len(codes) != 1 or len(names) != 1:
        raise FigureRenderError(f"{context} must contain exactly one ACZ")
    numeric_years = pd.to_numeric(work["year"], errors="raise")
    if not np.isfinite(numeric_years).all() or not numeric_years.eq(np.floor(numeric_years)).all():
        raise FigureRenderError(f"{context} years must be finite whole calendar years")
    years = numeric_years.astype(int)
    if tuple(sorted(years.tolist())) != expected_years or years.nunique() != expected_count:
        raise FigureRenderError(
            f"{context} must contain each governed year {expected_years[0]}-{expected_years[-1]} exactly once"
        )
    work["year"] = years
    work = work.sort_values("year", kind="mergesort").reset_index(drop=True)
    for column in ("annual_rate", "sen_slope", "raw_p", "bh_q"):
        values = pd.to_numeric(work[column], errors="raise").to_numpy(float)
        if not np.isfinite(values).all():
            raise FigureRenderError(f"{context} contains non-finite {column} values")
        work[column] = values
    if np.any(work["annual_rate"].to_numpy(float) < 0.0):
        raise FigureRenderError(f"{context} annual burned-area rates must be non-negative")
    for column in ("raw_p", "bh_q"):
        values = work[column].to_numpy(float)
        if np.any((values < 0.0) | (values > 1.0)):
            raise FigureRenderError(f"{context} {column} values must lie within 0-1")
    stable: dict[str, float] = {}
    for column in ("sen_slope", "raw_p", "bh_q"):
        values = work[column].to_numpy(float)
        if not np.allclose(values, values[0], rtol=0.0, atol=1e-15):
            raise FigureRenderError(f"{context} must carry one governed {column} value across all {expected_count} years")
        stable[column] = float(values[0])
    return work, codes[0], names[0], stable["sen_slope"], stable["raw_p"], stable["bh_q"]


def _configured_alpha(context: RenderContextLike) -> float:
    raw = context.bundle.analysis.reproducibility.get("alpha")
    try:
        alpha = float(raw)
    except (TypeError, ValueError) as exc:
        raise FigureRenderError("Configured RQ2 alpha is unavailable") from exc
    if not (0.0 < alpha < 1.0):
        raise FigureRenderError("Configured RQ2 alpha must lie within 0-1")
    return alpha


def _apply_temporal_axis(ax: Any, years: tuple[int, ...]) -> None:
    first, last = years[0], years[-1]
    span = last - first
    if span == 0:
        ax.set_xlim(float(first) - 0.5, float(first) + 0.5)
        ax.set_xticks([first])
        return
    target_step = span / 5.0
    magnitude = 1
    while magnitude * 10 < target_step:
        magnitude *= 10
    step = next(multiplier * magnitude for multiplier in (1, 2, 5, 10)
                if multiplier * magnitude >= target_step)
    interior = range((first // step + 1) * step, last, step)
    ax.set_xlim(float(first), float(last))
    ax.set_xticks(sorted({first, last, *interior}))


def _add_inference_status(ax: Any, *, q: float, alpha: float, style: PublicationStyle) -> None:
    # Explicitly separate the sign/magnitude of the governed Sen slope from
    # the FDR-controlled inferential decision.  No stars, bold significance
    # cues, or newly calculated values are introduced.
    text = "BH q < 0.05" if q < alpha else "BH q ≥ 0.05"
    ax.text(
        0.985,
        0.95,
        text,
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=style.tick_font,
        color="#555555",
        gid="rq2-fdr-status",
    )


def render_rq2_single_trend(
    frame: pd.DataFrame | None,
    *,
    spec: PresentationExportSpecificationContract,
    context: RenderContextLike,
) -> RenderedFigure:
    """Render one selected ACZ trend from governed annual values and inference."""
    if frame is None:
        raise FigureRenderError("RQ2 single-ACZ renderer requires the governed annual trend source")
    expected_years = _configured_years(context)
    work, code, name, _slope, _raw_p, q = _normalise_group(
        frame, expected_years=expected_years, context=spec.export_id,
    )
    selector_column = str(spec.selector.get("column", ""))
    selector_value = str(spec.selector.get("equals", ""))
    if selector_column != "parent_code" or selector_value != code:
        raise FigureRenderError(
            f"{spec.export_id} selected ACZ {code!r} does not match its configured selector"
        )
    f4 = _f4_spec(context)
    styles = _trajectory_styles(f4)
    alpha = _configured_alpha(context)
    with plt.rc_context(matplotlib.RcParams(context.style.rc_params())):
        fig, ax = plt.subplots(figsize=context.style.single_panel)
        draw_trajectory_panel(
            ax,
            work,
            x="year",
            y="annual_rate",
            slope="sen_slope",
            annotation_fields=("sen_slope", "raw_p", "bh_q"),
            group_label=name,
            xlabel=str(f4.xlabel or "Year"),
            ylabel=str(f4.ylabel or spec.units.split(";", 1)[0].strip()),
            style=context.style,
            trajectory_styles=styles,
        )
        _apply_temporal_axis(ax, expected_years)
        _add_inference_status(ax, q=q, alpha=alpha, style=context.style)
        ax.set_title(spec.label)
        fig.tight_layout()
        return export_figure(fig, context.style)


def render_rq2_five_acz_comparison(
    frame: pd.DataFrame | None,
    *,
    spec: PresentationExportSpecificationContract,
    context: RenderContextLike,
) -> RenderedFigure:
    """Render the approved five-panel comparison without defining a pooled estimand."""
    if frame is None:
        raise FigureRenderError("RQ2 five-ACZ comparison requires the governed annual trend source")
    _require_columns(frame, _RQ2_COLUMNS, context=spec.export_id)
    expected_years = _configured_years(context)
    f4 = _f4_spec(context)
    configured_order = tuple(str(value) for value in spec.category_order.get("values", ()))
    f4_order = tuple(str(value) for value in f4.renderer_options.get("panel_order", ()))
    if not configured_order or configured_order != f4_order or len(configured_order) != 5:
        raise FigureRenderError("RQ2 comparison panel order is not concordant with the governed F4 contract")
    expected_rows = len(configured_order) * len(expected_years)
    if len(frame) != expected_rows:
        raise FigureRenderError(f"{spec.export_id} requires exactly {expected_rows} governed rows; got {len(frame)}")

    groups: dict[str, pd.DataFrame] = {}
    observed_codes: list[str] = []
    for name in configured_order:
        selected = frame.loc[frame["parent_name"].astype(str).eq(name)].copy()
        work, code, observed_name, _slope, _raw_p, _q = _normalise_group(
            selected, expected_years=expected_years, context=f"{spec.export_id}:{name}",
        )
        if observed_name != name:
            raise FigureRenderError("RQ2 comparison source has a parent-name mismatch")
        groups[name] = work
        observed_codes.append(code)
    if len(set(observed_codes)) != 5:
        raise FigureRenderError("RQ2 comparison duplicates or omits an ACZ")
    if set(frame["parent_name"].astype(str)) != set(configured_order):
        raise FigureRenderError("RQ2 comparison source contains an unconfigured ACZ")

    layout = context.style.grid_for(f4.layout_role)
    trajectory_styles = _trajectory_styles(f4)
    y_limits = common_trajectory_y_limits(frame, group="parent_name", x="year", y="annual_rate", slope="sen_slope")
    with plt.rc_context(matplotlib.RcParams(context.style.rc_params())):
        grid = build_grid_figure(layout, figure_size=context.style.single_panel)
        apply_grid_spacing(grid.figure, layout, style=context.style)
        title_band = (2.0 * context.style.base_font) / (72.0 * grid.figure.get_figheight())
        grid.figure.subplots_adjust(top=grid.figure.subplotpars.top - title_band)
        statistics = []
        for idx, (ax, name) in enumerate(zip(grid.data_axes, configured_order, strict=True)):
            values = draw_trajectory_panel(
                ax,
                groups[name],
                x="year",
                y="annual_rate",
                slope="sen_slope",
                annotation_fields=("sen_slope", "raw_p", "bh_q"),
                group_label=name,
                xlabel=str(f4.panel_xlabels[idx] or ""),
                ylabel=str(f4.panel_ylabels[idx] or ""),
                style=context.style,
                trajectory_styles=trajectory_styles,
                common_y_limits=y_limits,
                show_group_title=False,
            )
            statistics.append((name, values))
            _apply_temporal_axis(ax, expected_years)
        auxiliary = f4.renderer_options.get("auxiliary_key")
        if not isinstance(auxiliary, Mapping):
            raise FigureRenderError("Governed F4 shared graphical key is unavailable")
        cell_id = str(auxiliary.get("cell_id", ""))
        if cell_id not in grid.auxiliary_axes:
            raise FigureRenderError("Governed F4 shared graphical key cell is unavailable")
        draw_shared_trajectory_key(
            grid.auxiliary_axes[cell_id],
            entries=auxiliary["entries"],
            style=context.style,
            trajectory_styles=trajectory_styles,
            statistics=statistics,
        )
        if f4.ylabel:
            grid.figure.text(
                float(f4.renderer_options.get("shared_ylabel_x_fraction", 0.018)),
                0.5,
                str(f4.ylabel),
                rotation=90,
                ha="center",
                va="center",
                fontsize=context.style.axis_label_font,
                gid="rq2-shared-ylabel",
            )
        grid.figure.suptitle(spec.label)
        add_panel_labels(grid.data_axes, style=context.style)
        apply_axis_label_padding(grid.data_axes, style=context.style)
        return export_figure(grid.figure, context.style)


RQ2_PRESENTATION_RENDERERS = {
    "single_trajectory_with_sen": render_rq2_single_trend,
    "grid_trajectory_with_sen": render_rq2_five_acz_comparison,
}
