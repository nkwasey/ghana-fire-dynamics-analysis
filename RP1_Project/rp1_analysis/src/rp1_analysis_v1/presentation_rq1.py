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
from matplotlib import colors as mcolors

from .contracts import PresentationExportSpecificationContract
from .figures import FigureRenderError, RenderedFigure, export_figure
from .mapping import (
    GhanaMapAuthority,
    MappingError,
    acz_categorical_context_map,
    acz_choropleth,
    categorical_map,
    choropleth,
    prepare_geography,
    support_acz_map,
)
from .style import PublicationStyle


class _GeometryAuthorityLike(Protocol):
    members: Mapping[str, tuple[Path, ...]]


class _RegistryLike(Protocol):
    semantic_styles: Mapping[str, Any]


class RenderContextLike(Protocol):
    geometry: _GeometryAuthorityLike
    registry: _RegistryLike
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


def _signed_norm(frame: pd.DataFrame, *, value: str) -> mcolors.Normalize:
    valid = frame.loc[~frame["support_status"].astype(str).eq("excluded"), value]
    values = pd.to_numeric(valid, errors="raise").dropna().to_numpy(float)
    if values.size == 0 or not np.isfinite(values).all():
        raise FigureRenderError("Signed presentation map has no finite governed values")
    vmin, vmax = float(values.min()), float(values.max())
    if not (vmin < 0.0 < vmax):
        raise FigureRenderError(
            "Configured signed presentation map requires governed values on both sides of zero"
        )
    return mcolors.TwoSlopeNorm(vmin=vmin, vcenter=0.0, vmax=vmax)


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
    return acz_choropleth(
        authority,
        frame,
        value="value",
        title=spec.label,
        colorbar_label=_configured_colourbar_label(spec),
        style=context.style,
        cmap="viridis",
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
    semantic = spec.colour_semantic.casefold()
    norm: mcolors.Normalize | None = None
    if "coolwarm" in semantic and "signed" in semantic:
        cmap = "coolwarm"
        norm = _signed_norm(frame, value="value")
    elif "viridis" in semantic:
        cmap = "viridis"
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
    )


def render_rq1_acz_seasonality(
    frame: pd.DataFrame | None,
    *,
    spec: PresentationExportSpecificationContract,
    context: RenderContextLike,
) -> RenderedFigure:
    if frame is None:
        raise FigureRenderError("ACZ seasonality renderer requires the governed tabular source")
    required = [
        "parent_code",
        "unit_name",
        "month",
        "value",
        "circular_mean_month",
        "mean_resultant_length",
    ]
    _require_columns(frame, required, context="ACZ seasonality")
    order = _explicit_values(spec)
    palette = _acz_palette(context)
    if set(frame["parent_code"].astype(str)) != set(order):
        raise FigureRenderError("ACZ seasonality categories do not match configured order")
    ylabel = spec.units.split(";", 1)[0].strip()
    with plt.rc_context(matplotlib.RcParams(context.style.rc_params())):
        fig, ax = plt.subplots(figsize=context.style.wide_single_panel)
        for code in order:
            group = frame.loc[frame["parent_code"].astype(str).eq(code)].copy()
            if len(group) != 12 or group["month"].astype(int).nunique() != 12:
                raise FigureRenderError(f"ACZ seasonality {code!r} does not contain exactly 12 months")
            group = group.sort_values("month")
            months = tuple(pd.to_numeric(group["month"], errors="raise").astype(int))
            if months != tuple(range(1, 13)):
                raise FigureRenderError(f"ACZ seasonality {code!r} month ordering is not 1-12")
            mu = pd.to_numeric(group["circular_mean_month"], errors="raise").to_numpy(float)
            resultant = pd.to_numeric(group["mean_resultant_length"], errors="raise").to_numpy(float)
            if not (np.isfinite(mu).all() and np.isfinite(resultant).all()):
                raise FigureRenderError("ACZ seasonality circular summaries contain non-finite values")
            if not (np.allclose(mu, mu[0]) and np.allclose(resultant, resultant[0])):
                raise FigureRenderError("ACZ seasonality circular summaries vary within an ACZ")
            names = tuple(dict.fromkeys(group["unit_name"].astype(str)))
            if len(names) != 1:
                raise FigureRenderError("ACZ seasonality source has inconsistent zone names")
            values = pd.to_numeric(group["value"], errors="raise").to_numpy(float)
            if not np.isfinite(values).all():
                raise FigureRenderError("ACZ seasonality source contains non-finite monthly values")
            if code not in palette:
                raise FigureRenderError(f"ACZ seasonality lacks configured colour for {code!r}")
            ax.plot(
                months,
                values,
                marker="o",
                markersize=3.0,
                linewidth=max(1.0, context.style.line_width),
                color=palette[code],
                label=f"{names[0]} (μ={mu[0]:.2f}, R={resultant[0]:.3f})",
            )
        ax.set_xticks(range(1, 13))
        ax.set(xlabel="Month", ylabel=ylabel, title=spec.label)
        ax.grid(alpha=context.style.grid_alpha)
        ax.legend(
            frameon=False,
            fontsize=context.style.legend_font,
            ncol=1,
            loc="upper center",
            bbox_to_anchor=(0.5, -0.14),
        )
        fig.tight_layout()
        return export_figure(fig, context.style)


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
    values = pivot.to_numpy(float)
    with plt.rc_context(matplotlib.RcParams(context.style.rc_params())):
        fig, ax = plt.subplots(figsize=context.style.single_panel)
        image = ax.imshow(np.ma.masked_invalid(values), aspect="auto", interpolation="nearest", cmap="viridis")
        ax.set_xticks(np.arange(12), [str(month) for month in range(1, 13)])
        ax.set_yticks([])
        ax.set(xlabel="Month", ylabel="Districts", title=spec.label)
        colorbar = fig.colorbar(image, ax=ax, orientation="horizontal", fraction=0.06, pad=0.12)
        colorbar.set_label("Share of district long-run burned area")
        fig.tight_layout()
        return export_figure(fig, context.style)


def render_rq1_district_circular_mean_timing(
    frame: pd.DataFrame | None,
    *,
    spec: PresentationExportSpecificationContract,
    context: RenderContextLike,
) -> RenderedFigure:
    if frame is None:
        raise FigureRenderError("District circular timing renderer requires the governed tabular source")
    _, summary, _ = _ordered_s1(frame, context)
    values = pd.to_numeric(summary["circular_mean_month"], errors="coerce")
    finite = values.notna() & np.isfinite(values.to_numpy(float, na_value=np.nan))
    y = np.arange(len(summary))
    display = context.style.circular_mean_month_display
    with plt.rc_context(matplotlib.RcParams(context.style.rc_params())):
        fig, ax = plt.subplots(figsize=context.style.single_panel)
        ax.scatter(values.loc[finite], y[finite.to_numpy()], s=10.0)
        ax.set_xlim(display.axis_min, display.axis_max)
        ax.set_xticks(display.ticks, display.tick_labels)
        ax.set_yticks([])
        ax.set(xlabel=display.axis_label, ylabel="Districts", title=spec.label)
        ax.grid(axis="x", alpha=context.style.grid_alpha)
        fig.tight_layout()
        return export_figure(fig, context.style)


def render_rq1_resultant_length_boxplot(
    frame: pd.DataFrame | None,
    *,
    spec: PresentationExportSpecificationContract,
    context: RenderContextLike,
) -> RenderedFigure:
    if frame is None:
        raise FigureRenderError("District resultant-length renderer requires the governed tabular source")
    _, summary, _ = _ordered_s1(frame, context)
    order = _acz_order(context)
    groups: list[np.ndarray] = []
    for code in order:
        values = pd.to_numeric(
            summary.loc[summary["parent_code"].astype(str).eq(code), "mean_resultant_length"],
            errors="coerce",
        ).dropna().to_numpy(float)
        if values.size == 0:
            raise FigureRenderError(f"No finite governed resultant-length values for ACZ {code!r}")
        if np.any((values < 0.0) | (values > 1.0)):
            raise FigureRenderError("Governed mean resultant length must remain within 0-1")
        groups.append(values)
    with plt.rc_context(matplotlib.RcParams(context.style.rc_params())):
        fig, ax = plt.subplots(figsize=context.style.single_panel)
        ax.boxplot(groups, tick_labels=list(order), showfliers=False)
        ax.set_ylim(0.0, 1.0)
        ax.set(xlabel="ACZ", ylabel="Mean resultant length", title=spec.label)
        ax.grid(axis="y", alpha=context.style.grid_alpha)
        fig.tight_layout()
        return export_figure(fig, context.style)


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
