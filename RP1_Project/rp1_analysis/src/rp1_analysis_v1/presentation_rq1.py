"""Standalone study-context and RQ1 presentation renderers.

The renderers in this module consume already-governed presentation source
records and geometries.  They do not calculate RQ1 estimands, spatial
statistics, permutation p-values or multiple-testing decisions.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .contracts import FigureContract, PresentationExportSpecificationContract
from .figures import (
    FigureRenderError,
    RenderedFigure,
    draw_circular_mean_timing,
    draw_district_seasonal_heatmap,
    draw_resultant_length_by_group,
    export_figure,
    label_district_share_colorbar,
    seasonality_lines,
)
from .mapping import (
    GhanaMapAuthority,
    MappingError,
    acz_categorical_context_map,
    acz_choropleth,
    bounded_map_norm,
    categorical_map,
    choropleth,
    prepare_geography,
    support_acz_map,
)
from .presentation import get_figure_spec
from .style import PublicationStyle


class _GeometryAuthorityLike(Protocol):
    members: Mapping[str, tuple[Path, ...]]


class _RegistryLike(Protocol):
    semantic_styles: Mapping[str, Any]


class _BundleLike(Protocol):
    figure: FigureContract


class RenderContextLike(Protocol):
    geometry: _GeometryAuthorityLike
    registry: _RegistryLike
    bundle: _BundleLike
    style: PublicationStyle


def _require_columns(frame: pd.DataFrame, required: Sequence[str], *, context: str) -> None:
    missing = sorted(set(required).difference(frame.columns))
    if missing:
        raise FigureRenderError(f"{context} source missing columns: {missing!r}")
    if frame.empty:
        raise FigureRenderError(f"{context} source is empty")


def _shapefile(context: RenderContextLike, geometry_id: str) -> Path:
    try:
        members = context.geometry.members[geometry_id]
    except KeyError as exc:
        raise FigureRenderError(
            f"Renderer requires governed geometry {geometry_id!r}, but it is not configured"
        ) from exc
    shp = tuple(path for path in members if path.suffix.casefold() == ".shp")
    if len(shp) != 1:
        raise FigureRenderError(
            f"Governed geometry {geometry_id!r} must resolve exactly one shapefile; observed {len(shp)}"
        )
    return shp[0]


def _load_geometry(context: RenderContextLike, geometry_id: str) -> gpd.GeoDataFrame:
    path = _shapefile(context, geometry_id)
    try:
        frame = gpd.read_file(path)
    except Exception as exc:  # pragma: no cover - backend owns parser details
        raise FigureRenderError(f"Unable to read governed geometry {path}") from exc
    if frame.crs is None:
        raise FigureRenderError(f"Governed geometry has no CRS: {path}")
    return frame


def _map_authority(context: RenderContextLike) -> GhanaMapAuthority:
    districts = _load_geometry(context, "district")
    acz = _load_geometry(context, "acz")
    try:
        return prepare_geography(districts, acz)
    except MappingError as exc:
        raise FigureRenderError(f"Governed map authority is invalid: {exc}") from exc


def _explicit_values(spec: PresentationExportSpecificationContract) -> tuple[str, ...]:
    mode = str(spec.category_order.get("mode", ""))
    values = tuple(str(value) for value in spec.category_order.get("values", ()))
    if mode != "explicit" or not values:
        raise FigureRenderError(
            f"{spec.export_id} requires an explicit configured category order"
        )
    return values


def _acz_palette(context: RenderContextLike) -> Mapping[str, str]:
    raw = context.registry.semantic_styles.get("acz_categories")
    if not isinstance(raw, Mapping) or not raw:
        raise FigureRenderError("Presentation registry lacks governed ACZ colour semantics")
    return {str(key): str(value) for key, value in raw.items()}


def _acz_order(context: RenderContextLike) -> tuple[str, ...]:
    return tuple(_acz_palette(context).keys())


def _acz_labels(acz: gpd.GeoDataFrame) -> Mapping[str, str]:
    _require_columns(acz, ["zone_code", "zone_name"], context="ACZ geometry")
    pairs = acz[["zone_code", "zone_name"]].astype(str).drop_duplicates()
    if pairs["zone_code"].duplicated().any():
        raise FigureRenderError("Governed ACZ geometry has non-unique zone_code labels")
    return dict(zip(pairs["zone_code"], pairs["zone_name"], strict=True))


def _configured_colourbar_label(spec: PresentationExportSpecificationContract) -> str:
    prefix = "horizontal colourbar:"
    for annotation in spec.annotation_policy:
        text = str(annotation).strip()
        if text.casefold().startswith(prefix):
            label = text[len(prefix) :].strip()
            if label:
                return label
    raise FigureRenderError(f"{spec.export_id} lacks its configured scientific colourbar label")


def _normalise_s1(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Validate the canonical district-seasonal table and return ordered rows/summary.

    This function only checks and reshapes governed records.  It does not
    estimate circular summaries or replace missing values.
    """

    required = [
        "record_type",
        "unit_id",
        "unit_name",
        "parent_code",
        "month",
        "monthly_share",
        "circular_mean_month",
        "mean_resultant_length",
    ]
    _require_columns(frame, required, context="District seasonal")
    work = frame.loc[frame["record_type"].astype(str).eq("monthly_share")].copy()
    if work.empty:
        raise FigureRenderError("District seasonal source contains no monthly-share rows")
    if work.duplicated(["unit_id", "month"]).any():
        raise FigureRenderError("District seasonal source duplicates unit-month records")
    months = tuple(sorted(pd.to_numeric(work["month"], errors="raise").astype(int).unique()))
    if months != tuple(range(1, 13)):
        raise FigureRenderError(f"District seasonal source has invalid month support: {months!r}")
    per_unit = work.groupby("unit_id", observed=True)["month"].nunique()
    if not per_unit.eq(12).all():
        raise FigureRenderError("Every governed district seasonal record must contain months 1-12")

    summary_fields = [
        "unit_id",
        "unit_name",
        "parent_code",
        "circular_mean_month",
        "mean_resultant_length",
    ]
    summaries: list[dict[str, Any]] = []
    for unit_id, group in work.groupby("unit_id", sort=False, observed=True):
        record: dict[str, Any] = {"unit_id": str(unit_id)}
        for field in summary_fields[1:]:
            values = group[field]
            if field in {"circular_mean_month", "mean_resultant_length"}:
                numeric = pd.to_numeric(values, errors="coerce")
                finite = numeric.dropna().to_numpy(float)
                if finite.size and not np.allclose(finite, finite[0]):
                    raise FigureRenderError(
                        f"District seasonal source changes governed {field} within {unit_id!r}"
                    )
                record[field] = float(finite[0]) if finite.size else np.nan
            else:
                unique = tuple(dict.fromkeys(values.astype(str).tolist()))
                if len(unique) != 1:
                    raise FigureRenderError(
                        f"District seasonal source changes governed {field} within {unit_id!r}"
                    )
                record[field] = unique[0]
        summaries.append(record)
    summary = pd.DataFrame.from_records(summaries)
    return work, summary


def _ordered_s1(
    frame: pd.DataFrame, context: RenderContextLike
) -> tuple[pd.DataFrame, pd.DataFrame, tuple[str, ...]]:
    work, summary = _normalise_s1(frame)
    acz_order = _acz_order(context)
    observed = set(summary["parent_code"].astype(str))
    if not observed.issubset(acz_order):
        raise FigureRenderError(
            f"District seasonal source contains unknown ACZ codes: {sorted(observed.difference(acz_order))!r}"
        )
    summary["_acz_order"] = pd.Categorical(
        summary["parent_code"].astype(str), categories=list(acz_order), ordered=True
    )
    summary = summary.sort_values(
        ["_acz_order", "circular_mean_month", "unit_name"],
        na_position="last",
        kind="mergesort",
    ).drop(columns="_acz_order")
    order = tuple(summary["unit_id"].astype(str))
    return work, summary.reset_index(drop=True), order


def render_study_ghana_acz(
    frame: pd.DataFrame | None,
    *,
    spec: PresentationExportSpecificationContract,
    context: RenderContextLike,
) -> RenderedFigure:
    if frame is not None:
        raise FigureRenderError("ACZ context renderer expects governed geometry, not tabular values")
    acz = _load_geometry(context, "acz")
    order = _explicit_values(spec)
    palette = _acz_palette(context)
    labels = _acz_labels(acz)
    return acz_categorical_context_map(
        acz,
        category="zone_code",
        category_order=order,
        category_colours=palette,
        category_labels=labels,
        title=spec.label,
        style=context.style,
    )


def render_study_district_support(
    frame: pd.DataFrame | None,
    *,
    spec: PresentationExportSpecificationContract,
    context: RenderContextLike,
) -> RenderedFigure:
    if frame is None:
        raise FigureRenderError("District support renderer requires the governed tabular source")
    _require_columns(
        frame, ["unit_id", "parent_code", "support_status"], context="District support"
    )
    authority = _map_authority(context)
    order = _explicit_values(spec)
    palette = _acz_palette(context)
    labels = _acz_labels(authority.acz)
    return support_acz_map(
        authority,
        frame,
        title=spec.label,
        style=context.style,
        category_order=order,
        category_colours=palette,
        category_labels=labels,
    )


def render_rq1_acz_long_run_rate(
    frame: pd.DataFrame | None,
    *,
    spec: PresentationExportSpecificationContract,
    context: RenderContextLike,
) -> RenderedFigure:
    if frame is None:
        raise FigureRenderError("ACZ long-run renderer requires the governed tabular source")
    _require_columns(frame, ["unit_id", "support_status", "value"], context="ACZ long-run")
    order = _explicit_values(spec)
    if len(frame) != len(order):
        raise FigureRenderError("ACZ long-run source does not contain the configured category count")
    authority = _map_authority(context)
    opts = get_figure_spec("F2", context.bundle.figure).renderer_options
    return acz_choropleth(
        authority,
        frame,
        value="value",
        title=spec.label,
        colorbar_label=_configured_colourbar_label(spec),
        style=context.style,
        cmap=str(opts["panel_colormaps"][0]),
        norm=bounded_map_norm(float(opts["rate_scale_max"])),
        colorbar_ticks=tuple(opts["rate_scale_ticks"]),
    )


def render_rq1_district_choropleth(
    frame: pd.DataFrame | None,
    *,
    spec: PresentationExportSpecificationContract,
    context: RenderContextLike,
) -> RenderedFigure:
    if frame is None:
        raise FigureRenderError("District choropleth renderer requires the governed tabular source")
    _require_columns(
        frame, ["unit_id", "support_status", "value"], context="District choropleth"
    )
    authority = _map_authority(context)
    figure = context.bundle.figure
    signed = spec.export_id == "rq1_district_departure"
    show_percent = spec.export_id == "rq3_district_mismatch"
    if spec.export_id == "rq1_district_long_run_rate":
        opts = get_figure_spec("F2", figure).renderer_options
        cmap = str(opts["panel_colormaps"][1])
        norm = bounded_map_norm(float(opts["rate_scale_max"]))
        ticks = tuple(opts["rate_scale_ticks"])
    elif signed:
        opts = get_figure_spec("F3", figure).renderer_options
        cmap = str(opts["panel_colormaps"][0])
        norm = bounded_map_norm(float(opts["departure_scale_limit"]), symmetric=True)
        ticks = tuple(opts["departure_scale_ticks"])
    elif show_percent:
        opts = get_figure_spec("F5", figure).renderer_options
        cmap = str(opts["panel_colormaps"][0])
        norm = ticks = None
    else:
        raise FigureRenderError(
            f"{spec.export_id} has no supported configured continuous colour semantic"
        )
    return choropleth(
        authority,
        frame,
        value="value",
        title=spec.label,
        colorbar_label=_configured_colourbar_label(spec),
        style=context.style,
        cmap=cmap,
        norm=norm,
        symmetric_about_zero=signed,
        show_percent=show_percent,
        colorbar_ticks=ticks,
    )


def render_rq1_acz_seasonality(
    frame: pd.DataFrame | None,
    *,
    spec: PresentationExportSpecificationContract,
    context: RenderContextLike,
) -> RenderedFigure:
    if frame is None:
        raise FigureRenderError("ACZ seasonality renderer requires the governed tabular source")
    return seasonality_lines(
        frame,
        title=spec.label,
        xlabel="Month",
        ylabel=spec.units.split(";", 1)[0].strip(),
        style=context.style,
        zone_order=_explicit_values(spec),
        zone_colours=_acz_palette(context),
    )


def render_rq1_local_moran(
    frame: pd.DataFrame | None,
    *,
    spec: PresentationExportSpecificationContract,
    context: RenderContextLike,
) -> RenderedFigure:
    if frame is None:
        raise FigureRenderError("Local Moran renderer requires the governed tabular source")
    _require_columns(
        frame, ["unit_id", "local_class", "support_status"], context="Local Moran"
    )
    classes = _explicit_values(spec)
    retained = frame.loc[~frame["support_status"].astype(str).eq("excluded")]
    observed = set(retained["local_class"].dropna().astype(str))
    if not observed.issubset(classes):
        raise FigureRenderError(
            f"Local Moran source contains classes outside configured identity: {sorted(observed.difference(classes))!r}"
        )
    authority = _map_authority(context)
    return categorical_map(
        authority,
        frame,
        category="local_class",
        title=spec.label,
        style=context.style,
        class_order=classes,
    )


def render_rq1_district_seasonal_heatmap(
    frame: pd.DataFrame | None,
    *,
    spec: PresentationExportSpecificationContract,
    context: RenderContextLike,
) -> RenderedFigure:
    if frame is None:
        raise FigureRenderError("District seasonal heatmap requires the governed tabular source")
    work, _, order = _ordered_s1(frame, context)
    pivot = work.pivot(index="unit_id", columns="month", values="monthly_share").reindex(order)
    pivot = pivot.reindex(columns=range(1, 13))
    style = context.style
    with plt.rc_context(matplotlib.RcParams(style.rc_params())):
        fig, ax = plt.subplots(figsize=style.single_panel)
        try:
            image = draw_district_seasonal_heatmap(ax, pivot, xlabel="Month", ylabel="Districts")
            ax.set_title(spec.label)
            colorbar = fig.colorbar(image, ax=ax, orientation="horizontal", fraction=0.06, pad=0.12)
            label_district_share_colorbar(colorbar, image)
            fig.tight_layout()
            return export_figure(fig, style)
        finally:
            plt.close(fig)


def render_rq1_district_circular_mean_timing(
    frame: pd.DataFrame | None,
    *,
    spec: PresentationExportSpecificationContract,
    context: RenderContextLike,
) -> RenderedFigure:
    if frame is None:
        raise FigureRenderError("District circular timing renderer requires the governed tabular source")
    _, summary, _ = _ordered_s1(frame, context)
    style = context.style
    with plt.rc_context(matplotlib.RcParams(style.rc_params())):
        fig, ax = plt.subplots(figsize=style.single_panel)
        draw_circular_mean_timing(
            ax, summary, xlabel=style.circular_mean_month_display.axis_label, ylabel="Districts", style=style,
        )
        ax.set_title(spec.label)
        ax.grid(axis="x", alpha=style.grid_alpha)
        fig.tight_layout()
        return export_figure(fig, style)


def render_rq1_resultant_length_boxplot(
    frame: pd.DataFrame | None,
    *,
    spec: PresentationExportSpecificationContract,
    context: RenderContextLike,
) -> RenderedFigure:
    if frame is None:
        raise FigureRenderError("District resultant-length renderer requires the governed tabular source")
    _, summary, _ = _ordered_s1(frame, context)
    style = context.style
    with plt.rc_context(matplotlib.RcParams(style.rc_params())):
        fig, ax = plt.subplots(figsize=style.single_panel)
        try:
            draw_resultant_length_by_group(
                ax, summary, xlabel="ACZ", ylabel="Mean resultant length", zone_order=_acz_order(context),
            )
            ax.set_title(spec.label)
            ax.grid(axis="y", alpha=style.grid_alpha)
            fig.tight_layout()
            return export_figure(fig, style)
        finally:
            plt.close(fig)


RQ1_PRESENTATION_RENDERERS = {
    "acz_categorical_context_map": render_study_ghana_acz,
    "support_acz_map": render_study_district_support,
    "acz_choropleth": render_rq1_acz_long_run_rate,
    "district_choropleth": render_rq1_district_choropleth,
    "seasonality_lines": render_rq1_acz_seasonality,
    "local_moran_categorical_map": render_rq1_local_moran,
    "district_seasonal_heatmap": render_rq1_district_seasonal_heatmap,
    "district_circular_mean_timing": render_rq1_district_circular_mean_timing,
    "resultant_length_boxplot": render_rq1_resultant_length_boxplot,
}
