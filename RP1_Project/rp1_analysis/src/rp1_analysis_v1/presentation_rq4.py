"""Standalone RQ4 presentation renderers.

These renderers consume already validated SaTScan-derived presentation
sources and governed geometries. They never execute SaTScan, fabricate
missing result families, or recalculate significance. Cluster membership
is projected descriptively onto the governed analytical support, and
recurrence is rendered exactly from the governed recurrence source.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Patch

from .contracts import PresentationExportSpecificationContract
from .data_io import load_data_authorities
from .figures import FigureRenderError, RenderedFigure, export_figure
from .mapping import (
    GhanaMapAuthority,
    MappingError,
    _draw_legend_band,
    draw_choropleth_axis,
    draw_cluster_membership_axis,
    prepare_geography,
)
from .paths import ProjectPaths
from .style import PublicationStyle
from .validation import DataContractSummary, validate_data_authorities


class _GeometryAuthorityLike(Protocol):
    members: Mapping[str, tuple[Path, ...]]


class _RegistryLike(Protocol):
    semantic_styles: Mapping[str, Any]


class _BundleLike(Protocol):
    analysis: Any
    data_schema: Any


class _PathsLike(Protocol):
    root: Path


class RenderContextLike(Protocol):
    geometry: _GeometryAuthorityLike
    registry: _RegistryLike
    bundle: _BundleLike
    paths: _PathsLike
    style: PublicationStyle


_MEMBERSHIP_COLUMNS = ("product", "unit_id", "cluster_id")
_RECURRENCE_COLUMNS = (
    "product",
    "unit_id",
    "significant_cluster_count",
    "total_significant_clusters",
    "significant_cluster_fraction",
    "support_status",
    "exclusion_reasons",
)
_ALLOWED_SUPPORT = {"valid_nonzero", "valid_zero", "excluded"}
_EXPECTED_TOTALS = {"mcd64a1": 104, "viirs": 108}


@lru_cache(maxsize=8)
def _data_contract(project_root: Path) -> DataContractSummary:
    governed = ProjectPaths(project_root)
    from .config import load_configuration_bundle

    bundle = load_configuration_bundle(project_root / "config")
    authorities = load_data_authorities(governed, bundle.data_schema)
    return validate_data_authorities(authorities, bundle.analysis, bundle.data_schema)


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
    except Exception as exc:  # pragma: no cover
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


def _configured_colourbar_label(spec: PresentationExportSpecificationContract) -> str:
    prefix = "horizontal colourbar:"
    for annotation in spec.annotation_policy:
        text = str(annotation).strip()
        if text.casefold().startswith(prefix):
            label = text[len(prefix):].strip()
            if label:
                return label
    raise FigureRenderError(f"{spec.export_id} lacks its configured scientific colourbar label")


def _expected_product(spec: PresentationExportSpecificationContract) -> str:
    product = str(spec.selector.get("equals", "")).strip()
    if product not in {"mcd64a1", "viirs"}:
        raise FigureRenderError(f"{spec.export_id} lacks a supported configured product selector")
    return product


def _support_mask(context: RenderContextLike, *, product: str) -> pd.DataFrame:
    summary = _data_contract(context.paths.root)
    mask = summary.long_run_mask if product == "mcd64a1" else summary.paired_mask
    required = {"unit_id", "eligible", "exclusion_reasons"}
    if not required.issubset(mask.units.columns):
        raise FigureRenderError("Governed analytical support mask lacks required support columns")
    out = mask.units.loc[:, ["unit_id", "eligible", "exclusion_reasons"]].copy()
    if out["unit_id"].astype(str).duplicated().any():
        raise FigureRenderError("Governed analytical support mask contains duplicate unit IDs")
    return out


def _membership_map_source(
    frame: pd.DataFrame,
    *,
    spec: PresentationExportSpecificationContract,
    context: RenderContextLike,
) -> pd.DataFrame:
    _require_columns(frame, _MEMBERSHIP_COLUMNS, context=spec.export_id)
    product = _expected_product(spec)
    if set(frame["product"].astype(str)) != {product}:
        raise FigureRenderError(f"{spec.export_id} source rows do not match configured product {product!r}")
    if frame[["unit_id", "cluster_id"]].isna().any().any():
        raise FigureRenderError(f"{spec.export_id} contains missing membership identifiers")
    memberships = frame.loc[:, list(_MEMBERSHIP_COLUMNS)].copy()
    grouped = (
        memberships.groupby("unit_id", sort=True, observed=True)["cluster_id"]
        .agg(lambda values: "|".join(sorted({str(v) for v in values})))
        .rename("cluster_ids")
        .reset_index()
    )
    support = _support_mask(context, product=product)
    out = support.merge(grouped, on="unit_id", how="left", validate="one_to_one")
    eligible = out["eligible"].astype(bool)
    member = eligible & out["cluster_ids"].fillna("").astype(str).ne("")
    out["product"] = product
    out["support_status"] = np.where(~eligible, "excluded", np.where(member, "valid_nonzero", "valid_zero"))
    out["value"] = np.where(member, 1.0, np.where(eligible, 0.0, np.nan))
    out["cluster_ids"] = out["cluster_ids"].fillna("")
    return out[["product", "unit_id", "support_status", "value", "cluster_ids", "exclusion_reasons"]]


def _recurrence_map_source(
    frame: pd.DataFrame,
    *,
    spec: PresentationExportSpecificationContract,
) -> pd.DataFrame:
    _require_columns(frame, _RECURRENCE_COLUMNS, context=spec.export_id)
    product = _expected_product(spec)
    work = frame.loc[:, list(_RECURRENCE_COLUMNS)].copy()
    if set(work["product"].astype(str)) != {product}:
        raise FigureRenderError(f"{spec.export_id} source rows do not match configured product {product!r}")
    statuses = set(work["support_status"].astype(str))
    if not statuses.issubset(_ALLOWED_SUPPORT):
        raise FigureRenderError(f"{spec.export_id} contains invalid support-status values: {sorted(statuses)!r}")
    if work["unit_id"].astype(str).duplicated().any():
        raise FigureRenderError(f"{spec.export_id} recurrence source must contain unique unit IDs")

    totals = pd.to_numeric(work["total_significant_clusters"], errors="raise")
    if totals.nunique(dropna=False) != 1:
        raise FigureRenderError(f"{spec.export_id} must preserve a single total significant-cluster count")
    expected_total = _EXPECTED_TOTALS[product]
    observed_total = int(float(totals.iloc[0]))
    if observed_total != expected_total:
        raise FigureRenderError(
            f"{spec.export_id} total significant clusters must be {expected_total}; observed {observed_total}"
        )

    excluded = work["support_status"].astype(str).eq("excluded")
    valid = work.loc[~excluded].copy()
    valid_counts = pd.to_numeric(valid["significant_cluster_count"], errors="raise")
    if (valid_counts < 0).any() or not np.allclose(valid_counts.to_numpy(), np.round(valid_counts.to_numpy())):
        raise FigureRenderError(f"{spec.export_id} recurrence counts must be non-negative integers")
    valid["significant_cluster_count"] = valid_counts.astype(float)

    expected_fraction = valid_counts / float(expected_total)
    observed_fraction = pd.to_numeric(valid["significant_cluster_fraction"], errors="raise")
    if not np.allclose(observed_fraction.to_numpy(), expected_fraction.to_numpy(), atol=1e-12, rtol=0.0):
        raise FigureRenderError(f"{spec.export_id} recurrence fractions are not concordant with the cluster counts")

    if work.loc[excluded, ["significant_cluster_count", "significant_cluster_fraction"]].notna().any().any():
        raise FigureRenderError(f"{spec.export_id} excluded districts must not carry plotted recurrence values")
    return work


def render_rq4_cluster_membership(
    frame: pd.DataFrame | None,
    *,
    spec: PresentationExportSpecificationContract,
    context: RenderContextLike,
) -> RenderedFigure:
    if frame is None:
        raise FigureRenderError("RQ4 cluster-membership renderer requires the governed tabular source")
    authority = _map_authority(context)
    figure_data = _membership_map_source(frame, spec=spec, context=context)
    with plt.rc_context(matplotlib.RcParams(context.style.rc_params())):
        fig, ax = plt.subplots(figsize=context.style.full_width_map)
        panel_axes, any_members, any_excluded = draw_cluster_membership_axis(
            fig,
            ax,
            authority,
            figure_data,
            style=context.style,
        )
        panel_axes.map_ax.set_title(spec.label)
        handles = [
            Patch(
                facecolor=context.style.semantic.valid_zero.face,
                edgecolor=context.style.semantic.valid_zero.edge,
                label="No significant cluster membership",
            )
        ]
        if any_members:
            handles.insert(
                0,
                Patch(facecolor="0.35", edgecolor=context.style.boundary_colour, label="Significant cluster member"),
            )
        if any_excluded:
            handles.append(
                Patch(
                    facecolor=context.style.semantic.excluded.face,
                    edgecolor=context.style.semantic.excluded.edge,
                    hatch=context.style.semantic.excluded.hatch,
                    label="Excluded / unsupported",
                )
            )
        _draw_legend_band(panel_axes.support_or_status_legend_ax, handles, style=context.style)
        panel_axes.colorbar_or_categorical_key_ax.clear()
        panel_axes.colorbar_or_categorical_key_ax.set_axis_off()
        return export_figure(fig, context.style)


def render_rq4_cluster_recurrence(
    frame: pd.DataFrame | None,
    *,
    spec: PresentationExportSpecificationContract,
    context: RenderContextLike,
) -> RenderedFigure:
    if frame is None:
        raise FigureRenderError("RQ4 cluster-recurrence renderer requires the governed tabular source")
    authority = _map_authority(context)
    figure_data = _recurrence_map_source(frame, spec=spec)
    label = _configured_colourbar_label(spec)
    with plt.rc_context(matplotlib.RcParams(context.style.rc_params())):
        fig, ax = plt.subplots(figsize=context.style.full_width_map)
        panel_axes = draw_choropleth_axis(
            fig,
            ax,
            authority,
            figure_data,
            value="significant_cluster_count",
            colorbar_label=label,
            style=context.style,
            cmap="cividis",
            draw_colorbar=True,
        )
        panel_axes.map_ax.set_title(spec.label)
        return export_figure(fig, context.style)


RQ4_PRESENTATION_RENDERERS = {
    "cluster_membership_map": render_rq4_cluster_membership,
    "cluster_recurrence_map": render_rq4_cluster_recurrence,
}


__all__ = [
    "RQ4_PRESENTATION_RENDERERS",
    "render_rq4_cluster_membership",
    "render_rq4_cluster_recurrence",
]
