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
from matplotlib.lines import Line2D

from .contracts import FigureSpecificationContract, PresentationExportSpecificationContract
from .figures import FigureRenderError, RenderedFigure, draw_trajectory_panel, export_figure
from .grid_rendering import apply_axis_label_padding, apply_grid_spacing, build_grid_figure
from .style import PublicationStyle


class _RegistryLike(Protocol):
    semantic_styles: Mapping[str, Any]


class _BundleLike(Protocol):
    figure: Any
    analysis: Any


class RenderContextLike(Protocol):
    registry: _RegistryLike
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
_EXPECTED_YEARS = tuple(range(2001, 2025))


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


def _acz_palette(context: RenderContextLike) -> dict[str, str]:
    raw = context.registry.semantic_styles.get("acz_categories")
    if not isinstance(raw, Mapping) or not raw:
        raise FigureRenderError("Presentation registry lacks governed ACZ colour semantics")
    return {str(key): str(value) for key, value in raw.items()}


def _trajectory_styles(context: RenderContextLike, code: str) -> dict[str, dict[str, object]]:
    f4 = _f4_spec(context)
    raw = f4.renderer_options.get("trajectory_styles", {})
    if not isinstance(raw, Mapping):
        raise FigureRenderError("Governed F4 trajectory styles are malformed")
    observed = dict(raw.get("observed_series", {}))
    slope = dict(raw.get("sen_slope", {}))
    palette = _acz_palette(context)
    if code not in palette:
        raise FigureRenderError(f"No configured ACZ colour is available for {code!r}")
    # The phase requires ACZ identity to be carried by the observed series.
    # The Sen line keeps its separate governed presentation style so direction
    # is not confused with the BH inferential decision.
    observed["color"] = palette[code]
    return {"observed_series": observed, "sen_slope": slope}


def _normalise_group(frame: pd.DataFrame, *, context: str) -> tuple[pd.DataFrame, str, str, float, float, float]:
    _require_columns(frame, _RQ2_COLUMNS, context=context)
    work = frame.loc[:, _RQ2_COLUMNS].copy()
    if len(work) != 24:
        raise FigureRenderError(f"{context} requires exactly 24 annual rows; got {len(work)}")
    codes = tuple(dict.fromkeys(work["parent_code"].astype(str)))
    names = tuple(dict.fromkeys(work["parent_name"].astype(str)))
    if len(codes) != 1 or len(names) != 1:
        raise FigureRenderError(f"{context} must contain exactly one ACZ")
    years = pd.to_numeric(work["year"], errors="raise").astype(int)
    if tuple(sorted(years.tolist())) != _EXPECTED_YEARS or years.nunique() != 24:
        raise FigureRenderError(f"{context} must contain each governed year 2001-2024 exactly once")
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
            raise FigureRenderError(f"{context} must carry one governed {column} value across all 24 years")
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


def _apply_temporal_axis(ax: Any) -> None:
    ax.set_xlim(2001.0, 2024.0)
    ax.set_xticks([2001, 2005, 2010, 2015, 2020, 2024])


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
    work, code, name, _slope, _raw_p, q = _normalise_group(frame, context=spec.export_id)
    selector_column = str(spec.selector.get("column", ""))
    selector_value = str(spec.selector.get("equals", ""))
    if selector_column != "parent_code" or selector_value != code:
        raise FigureRenderError(
            f"{spec.export_id} selected ACZ {code!r} does not match its configured selector"
        )
    f4 = _f4_spec(context)
    styles = _trajectory_styles(context, code)
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
        _apply_temporal_axis(ax)
        _add_inference_status(ax, q=q, alpha=alpha, style=context.style)
        ax.set_title(spec.label)
        fig.tight_layout()
        return export_figure(fig, context.style)


def _draw_comparison_key(
    ax: Any,
    *,
    order: Sequence[str],
    code_by_name: Mapping[str, str],
    palette: Mapping[str, str],
    slope_style: Mapping[str, object],
    style: PublicationStyle,
) -> None:
    handles: list[Line2D] = []
    labels: list[str] = []
    for name in order:
        code = code_by_name[name]
        handles.append(Line2D([], [], color=palette[code], marker="o", markersize=3.0, linewidth=0.9))
        labels.append(name.title())
    slope_kwargs = dict(slope_style)
    slope_kwargs.setdefault("linewidth", 1.2)
    handles.append(Line2D([], [], **slope_kwargs))
    labels.append("Governed Sen slope")
    ax.set_axis_off()
    ax.legend(handles, labels, loc="center", frameon=False, fontsize=style.legend_font, ncol=1)


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
    if len(frame) != 120:
        raise FigureRenderError(f"{spec.export_id} requires exactly 120 governed rows; got {len(frame)}")
    f4 = _f4_spec(context)
    configured_order = tuple(str(value) for value in spec.category_order.get("values", ()))
    f4_order = tuple(str(value) for value in f4.renderer_options.get("panel_order", ()))
    if not configured_order or configured_order != f4_order or len(configured_order) != 5:
        raise FigureRenderError("RQ2 comparison panel order is not concordant with the governed F4 contract")

    groups: dict[str, tuple[pd.DataFrame, str, float]] = {}
    code_by_name: dict[str, str] = {}
    observed_codes: list[str] = []
    alpha = _configured_alpha(context)
    for name in configured_order:
        selected = frame.loc[frame["parent_name"].astype(str).eq(name)].copy()
        work, code, observed_name, _slope, _raw_p, q = _normalise_group(selected, context=f"{spec.export_id}:{name}")
        if observed_name != name:
            raise FigureRenderError("RQ2 comparison source has a parent-name mismatch")
        groups[name] = (work, code, q)
        code_by_name[name] = code
        observed_codes.append(code)
    if len(set(observed_codes)) != 5:
        raise FigureRenderError("RQ2 comparison duplicates or omits an ACZ")
    if set(frame["parent_name"].astype(str)) != set(configured_order):
        raise FigureRenderError("RQ2 comparison source contains an unconfigured ACZ")

    palette = _acz_palette(context)
    layout = context.style.grid_for(f4.layout_role)
    raw_trajectory_styles = f4.renderer_options.get("trajectory_styles", {})
    slope_style = dict(raw_trajectory_styles.get("sen_slope", {})) if isinstance(raw_trajectory_styles, Mapping) else {}
    with plt.rc_context(matplotlib.RcParams(context.style.rc_params())):
        grid = build_grid_figure(layout, figure_size=context.style.single_panel)
        apply_grid_spacing(grid.figure, layout, style=context.style)
        for idx, (ax, name) in enumerate(zip(grid.data_axes, configured_order, strict=True)):
            work, code, q = groups[name]
            draw_trajectory_panel(
                ax,
                work,
                x="year",
                y="annual_rate",
                slope="sen_slope",
                annotation_fields=("sen_slope", "raw_p", "bh_q"),
                group_label=name,
                xlabel=str(f4.panel_xlabels[idx] or f4.xlabel or "Year"),
                ylabel=str(f4.panel_ylabels[idx] or ""),
                style=context.style,
                trajectory_styles=_trajectory_styles(context, code),
            )
            _apply_temporal_axis(ax)
            _add_inference_status(ax, q=q, alpha=alpha, style=context.style)
        auxiliary = f4.renderer_options.get("auxiliary_key")
        if not isinstance(auxiliary, Mapping):
            raise FigureRenderError("Governed F4 shared graphical key is unavailable")
        cell_id = str(auxiliary.get("cell_id", ""))
        if cell_id not in grid.auxiliary_axes:
            raise FigureRenderError("Governed F4 shared graphical key cell is unavailable")
        _draw_comparison_key(
            grid.auxiliary_axes[cell_id],
            order=configured_order,
            code_by_name=code_by_name,
            palette=palette,
            slope_style=slope_style,
            style=context.style,
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
        # Standalone comparison panels are identified by their ACZ annotations;
        # panel letters are intentionally omitted because the presentation-export
        # contract does not require them and they would compete with the shared title.
        apply_axis_label_padding(grid.data_axes, style=context.style)
        return export_figure(grid.figure, context.style)


RQ2_PRESENTATION_RENDERERS = {
    "single_trajectory_with_sen": render_rq2_single_trend,
    "grid_trajectory_with_sen": render_rq2_five_acz_comparison,
}
