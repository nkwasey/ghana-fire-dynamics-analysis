"""Governed cartographic preparation and rendering for Ghana RP1 maps."""

from __future__ import annotations

import io
import textwrap
from dataclasses import dataclass

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import colors as mcolors
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Patch
from pyproj import CRS

from .figures import RenderedFigure, export_figure
from .grid_rendering import (
    add_panel_labels,
    apply_axis_label_padding,
    apply_grid_spacing,
    build_grid_figure,
)
from .contracts import GridLayoutContract
from .style import PublicationStyle


class MappingError(ValueError):
    """Raised when governed map preparation or rendering cannot be satisfied."""


@dataclass(frozen=True, slots=True)
class GhanaMapAuthority:
    districts: gpd.GeoDataFrame
    acz: gpd.GeoDataFrame
    extent: tuple[float, float, float, float]
    crs: str


@dataclass(frozen=True, slots=True)
class MapPanelAxes:
    """One scientific map viewport plus two independently reserved ancillary bands."""

    map_ax: Axes
    support_or_status_legend_ax: Axes
    colorbar_or_categorical_key_ax: Axes
    original_cell_bounds: tuple[float, float, float, float]


def build_map_panel_axes(
    fig: Figure,
    map_ax: Axes,
    *,
    style: PublicationStyle,
) -> MapPanelAxes:
    """Split a configured grid cell without allowing ancillary content to resize the map."""

    bounds = map_ax.get_position().bounds
    x0, y0, width, height = (float(value) for value in bounds)
    geometry = style.geometry
    total = (
        geometry.map_height_ratio
        + geometry.map_legend_band_height
        + geometry.map_colourbar_band_height
        + 2.0 * geometry.map_inter_band_spacing
    )
    if total <= 0 or width <= 0 or height <= 0:
        raise MappingError("Configured map-panel geometry cannot realise a positive viewport")
    unit = height / total
    colorbar_h = unit * geometry.map_colourbar_band_height
    gap_h = unit * geometry.map_inter_band_spacing
    legend_h = unit * geometry.map_legend_band_height
    map_h = unit * geometry.map_height_ratio

    colorbar_y = y0
    legend_y = colorbar_y + colorbar_h + gap_h
    map_y = legend_y + legend_h + gap_h
    map_ax.set_position((x0, map_y, width, map_h))
    map_ax.set_gid(f"{map_ax.get_gid() or 'data-panel'}-map-viewport")

    legend_ax = fig.add_axes((x0, legend_y, width, legend_h))
    legend_ax.set_gid("map-support-status-band")
    legend_ax.set_axis_off()
    key_ax = fig.add_axes((x0, colorbar_y, width, colorbar_h))
    key_ax.set_gid("map-colourbar-or-categorical-key-band")
    key_ax.set_axis_off()
    return MapPanelAxes(
        map_ax=map_ax,
        support_or_status_legend_ax=legend_ax,
        colorbar_or_categorical_key_ax=key_ax,
        original_cell_bounds=(x0, y0, width, height),
    )


def _draw_legend_band(
    ax: Axes,
    handles: list[Patch],
    *,
    style: PublicationStyle,
    gid: str = "map-categorical-legend",
) -> None:
    ax.clear()
    ax.set_axis_off()
    if not handles:
        return
    legend = ax.legend(
        handles=handles,
        loc="center",
        ncol=max(1, min(len(handles), 4)),
        frameon=False,
        fontsize=style.legend_font,
        handlelength=1.8,
        columnspacing=1.0,
        borderaxespad=0.0,
    )
    legend.set_gid(gid)


def _draw_colorbar_band(
    fig: Figure,
    ax: Axes,
    *,
    cmap: str,
    norm: mcolors.Normalize,
    label: str | None,
    style: PublicationStyle,
    gid: str,
    labelpad_pt: float | None = None,
) -> Axes:
    clean_label = "" if label is None else str(label).strip()
    if style.map.colorbar.position != "below" or style.map.colorbar.orientation != "horizontal":
        raise MappingError("Map colourbars require the governed below/horizontal policy")
    if style.map.colorbar.label_required and not clean_label:
        raise MappingError("Continuous publication maps require a scientific colourbar label")
    if clean_label.casefold() == "value":
        raise MappingError("Generic colourbar label 'Value' is prohibited for publication maps")
    ax.clear()
    ax.set_axis_on()
    ax.set_gid(gid)
    mappable = matplotlib.cm.ScalarMappable(norm=norm, cmap=plt.get_cmap(cmap))
    mappable.set_array([])
    colorbar = fig.colorbar(mappable, cax=ax, orientation="horizontal")
    if clean_label:
        colorbar.set_label(
            textwrap.fill(clean_label, width=58),
            labelpad=(style.geometry.xlabel_padding_pt if labelpad_pt is None else float(labelpad_pt)),
        )
    colorbar.ax.tick_params(labelsize=style.tick_font)
    return colorbar.ax


def prepare_geography(districts: gpd.GeoDataFrame, acz: gpd.GeoDataFrame) -> GhanaMapAuthority:
    if districts.crs is None or acz.crs is None:
        raise MappingError("Map geometries require explicit CRS")
    if districts.crs != acz.crs:
        raise MappingError("District and ACZ geometries must share the same CRS")
    if (
        districts["dist_id"].astype(str).duplicated().any()
        or acz["zone_id"].astype(str).duplicated().any()
    ):
        raise MappingError("Map authority contains duplicate geographic keys")
    if (
        districts.geometry.isna().any()
        or districts.geometry.is_empty.any()
        or acz.geometry.isna().any()
        or acz.geometry.is_empty.any()
    ):
        raise MappingError("Map authority contains missing/empty geometry")
    bounds = districts.total_bounds
    if bounds.shape != (4,):
        raise MappingError("Map extent must contain exactly four coordinates")
    extent = (
        float(bounds[0]),
        float(bounds[1]),
        float(bounds[2]),
        float(bounds[3]),
    )
    return GhanaMapAuthority(districts.copy(), acz.copy(), extent, str(districts.crs))


def join_district_figure_data(
    authority: GhanaMapAuthority, frame: pd.DataFrame, *, data_key: str = "unit_id"
) -> gpd.GeoDataFrame:
    if data_key not in frame.columns:
        raise MappingError(f"Figure data missing join key {data_key!r}")
    if frame[data_key].astype(str).duplicated().any():
        raise MappingError("Figure-data district join key must be unique")
    left = authority.districts.copy()
    left["_join_key"] = left["dist_id"].astype(str)
    right = frame.copy()
    right["_join_key"] = right[data_key].astype(str)
    merged = left.merge(
        right.drop(columns=[data_key]), on="_join_key", how="left", validate="one_to_one"
    )
    if len(merged) != len(left):
        raise MappingError("District map join changed the geographic universe")
    return gpd.GeoDataFrame(merged, geometry="geometry", crs=authority.districts.crs)


def _require_metric_projected_crs(authority: GhanaMapAuthority) -> CRS:
    """Return a projected metre CRS or fail before drawing a kilometre scale bar."""

    try:
        crs = CRS.from_user_input(authority.crs)
    except Exception as exc:  # pragma: no cover - pyproj owns parser details
        raise MappingError(f"Unable to interpret map CRS {authority.crs!r}") from exc
    if not crs.is_projected:
        raise MappingError(
            "A kilometre scale bar requires a projected metric CRS; geographic CRS is unsuitable"
        )
    axis_info = tuple(crs.axis_info[:2])
    if len(axis_info) != 2:
        raise MappingError("Projected map CRS does not expose two horizontal axes")
    conversion_factors = [float(axis.unit_conversion_factor or np.nan) for axis in axis_info]
    if not all(np.isfinite(factor) and np.isclose(factor, 1.0) for factor in conversion_factors):
        raise MappingError(
            "A kilometre scale bar requires projected coordinates expressed in metres"
        )
    return crs


def _map_axes(fig: Figure, *, style: PublicationStyle) -> Axes:
    """Create a configuration-owned interior cell for a standalone map."""

    geometry = style.geometry
    return fig.add_axes(
        (
            geometry.outer_left_fraction,
            geometry.outer_bottom_fraction,
            1.0 - geometry.outer_left_fraction - geometry.outer_right_fraction,
            1.0 - geometry.outer_top_fraction - geometry.outer_bottom_fraction,
        )
    )


def _add_scale_bar(ax: Axes, authority: GhanaMapAuthority, style: PublicationStyle) -> None:
    scale = style.map.scale_bar
    if not scale.enabled:
        return
    _require_metric_projected_crs(authority)
    if scale.position != "lower_right":
        raise MappingError(f"Unsupported governed scale-bar position: {scale.position!r}")
    if scale.unit != "km":
        raise MappingError(f"Unsupported governed scale-bar unit: {scale.unit!r}")
    if scale.length_km <= 0:
        raise MappingError("Governed scale-bar length must be positive")

    xmin, ymin, xmax, ymax = authority.extent
    width = xmax - xmin
    height = ymax - ymin
    length_m = float(scale.length_km) * 1000.0
    x1 = xmax - float(scale.horizontal_margin_fraction) * width
    x0 = x1 - length_m
    y0 = ymin + float(scale.vertical_margin_fraction) * height
    if x0 <= xmin:
        raise MappingError(
            "Governed scale bar does not fit inside the map extent at the configured margin"
        )

    (line,) = ax.plot(
        [x0, x1],
        [y0, y0],
        linewidth=2.0,
        solid_capstyle="butt",
        color="black",
        zorder=20,
    )
    line.set_gid("map-scale-bar")
    label = ax.text(
        (x0 + x1) / 2.0,
        y0 + 0.012 * height,
        scale.label,
        ha="center",
        va="bottom",
        fontsize=7,
        zorder=20,
    )
    label.set_gid("map-scale-bar-label")


def _add_north_arrow(ax: Axes, authority: GhanaMapAuthority, style: PublicationStyle) -> None:
    north = style.map.north_arrow
    if not north.enabled:
        return
    if north.position != "upper_right":
        raise MappingError(f"Unsupported governed north-arrow position: {north.position!r}")
    xmin, ymin, xmax, ymax = authority.extent
    width = xmax - xmin
    height = ymax - ymin
    x = xmax - 0.07 * width
    tail_y = ymax - 0.14 * height
    head_y = ymax - 0.05 * height
    annotation = ax.annotate(
        "N",
        xy=(x, head_y),
        xytext=(x, tail_y),
        ha="center",
        va="center",
        arrowprops={"arrowstyle": "-|>", "linewidth": 1.0, "color": "black"},
        fontsize=8,
        color="black",
        zorder=20,
    )
    annotation.set_gid("map-north-arrow")


def _validate_support_status(merged: gpd.GeoDataFrame) -> None:
    if merged["support_status"].isna().any():
        raise MappingError("Every district must have an explicit support_status")
    allowed = {"valid_nonzero", "valid_zero", "excluded"}
    if not set(merged["support_status"].astype(str)).issubset(allowed):
        raise MappingError("Unsupported map support_status")


def _continuous_norm(values: pd.Series) -> mcolors.Normalize:
    numeric = pd.to_numeric(values, errors="coerce").dropna().to_numpy(dtype=float)
    numeric = numeric[np.isfinite(numeric)]
    if numeric.size == 0:
        return mcolors.Normalize(vmin=0.0, vmax=1.0)
    vmin = float(np.min(numeric))
    vmax = float(np.max(numeric))
    if np.isclose(vmin, vmax):
        pad = max(abs(vmin) * 0.01, 1.0e-12)
        vmin -= pad
        vmax += pad
    return mcolors.Normalize(vmin=vmin, vmax=vmax)


def _finalise_map_axes(ax: Axes, authority: GhanaMapAuthority, *, title: str) -> None:
    xmin, ymin, xmax, ymax = authority.extent
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ax.set_aspect("equal")
    ax.set_axis_off()
    ax.set_title(title)


def _build_choropleth_figure(
    authority: GhanaMapAuthority,
    figure_data: pd.DataFrame,
    *,
    value: str,
    title: str,
    colorbar_label: str | None,
    style: PublicationStyle,
    cmap: str = "viridis",
    zero_tolerance: float = 0.0,
    norm: mcolors.Normalize | None = None,
) -> tuple[Figure, Axes]:
    """Build a continuous map figure while retaining Matplotlib objects for tests."""

    if "support_status" not in figure_data.columns or value not in figure_data.columns:
        raise MappingError("Map figure data require support_status and value")
    if zero_tolerance < 0:
        raise MappingError("zero_tolerance must be non-negative")
    merged = join_district_figure_data(authority, figure_data)
    _validate_support_status(merged)
    if zero_tolerance > 0:
        governed_zero = merged["support_status"].eq("valid_zero")
        numeric = pd.to_numeric(merged[value], errors="coerce")
        inconsistent = governed_zero & numeric.notna() & numeric.abs().gt(zero_tolerance)
        if inconsistent.any():
            raise MappingError("Governed valid-zero status conflicts with zero_tolerance")

    fig = plt.figure(figsize=style.full_width_map)
    container_ax = _map_axes(fig, style=style)
    realised = draw_choropleth_axis(
        fig,
        container_ax,
        authority,
        figure_data,
        value=value,
        colorbar_label=colorbar_label,
        style=style,
        cmap=cmap,
        norm=norm,
    )
    realised.map_ax.set_title(title)
    realised.colorbar_or_categorical_key_ax.set_gid("map-colorbar")
    return fig, realised.map_ax


def _build_support_map_figure(
    authority: GhanaMapAuthority,
    figure_data: pd.DataFrame,
    *,
    title: str,
    style: PublicationStyle,
) -> tuple[Figure, Axes]:
    """Build the categorical analytical-support map for structural inspection."""

    if "support_status" not in figure_data.columns:
        raise MappingError("Support map requires support_status")
    merged = join_district_figure_data(authority, figure_data)
    _validate_support_status(merged)
    retained = merged.loc[~merged["support_status"].eq("excluded")]
    excluded = merged.loc[merged["support_status"].eq("excluded")]

    fig = plt.figure(figsize=style.full_width_map)
    container_ax = _map_axes(fig, style=style)
    panel_axes = build_map_panel_axes(fig, container_ax, style=style)
    ax = panel_axes.map_ax
    retained.plot(
        ax=ax,
        facecolor="0.96",
        edgecolor=style.boundary_colour,
        linewidth=style.boundary_width,
        rasterized=False,
    )
    if not excluded.empty:
        excluded.plot(
            ax=ax,
            facecolor=style.semantic.excluded.face,
            edgecolor=style.semantic.excluded.edge,
            hatch=style.semantic.excluded.hatch,
            linewidth=style.boundary_width,
            rasterized=False,
        )
    authority.acz.boundary.plot(
        ax=ax, color=style.acz_boundary_colour, linewidth=style.acz_boundary_width
    )
    _finalise_map_axes(ax, authority, title=title)
    _add_scale_bar(ax, authority, style)
    _add_north_arrow(ax, authority, style)
    _draw_legend_band(
        panel_axes.support_or_status_legend_ax,
        [
            Patch(
                facecolor="0.96",
                edgecolor=style.boundary_colour,
                label="Retained analytical support",
            ),
            Patch(
                facecolor=style.semantic.excluded.face,
                edgecolor=style.semantic.excluded.edge,
                hatch=style.semantic.excluded.hatch,
                label="Excluded analytical support",
            ),
        ],
        style=style,
    )
    return fig, ax


def _export_map_figure(fig: Figure, style: PublicationStyle) -> RenderedFigure:
    """Export a map through the common exact-canvas publication exporter."""
    return export_figure(fig, style)


def acz_categorical_context_map(
    acz: gpd.GeoDataFrame,
    *,
    category: str,
    category_order: tuple[str, ...],
    category_colours: Mapping[str, str],
    category_labels: Mapping[str, str],
    title: str,
    style: PublicationStyle,
) -> RenderedFigure:
    """Render a governed ACZ-only context map from the geometry authority."""

    required = {"zone_id", category, "geometry"}
    missing = sorted(required.difference(acz.columns))
    if missing:
        raise MappingError(f"ACZ context geometry missing columns: {missing!r}")
    if acz.crs is None:
        raise MappingError("ACZ context geometry requires explicit CRS")
    if acz["zone_id"].astype(str).duplicated().any():
        raise MappingError("ACZ context geometry contains duplicate zone_id values")
    if acz.geometry.isna().any() or acz.geometry.is_empty.any():
        raise MappingError("ACZ context geometry contains missing/empty geometry")
    observed = tuple(dict.fromkeys(acz[category].astype(str).tolist()))
    if set(observed) != set(category_order):
        raise MappingError(
            f"ACZ context categories do not match configured order: observed={sorted(observed)!r}"
        )
    missing_colours = sorted(set(category_order).difference(category_colours))
    if missing_colours:
        raise MappingError(f"ACZ context map lacks configured colours: {missing_colours!r}")
    bounds = acz.total_bounds
    extent = (float(bounds[0]), float(bounds[1]), float(bounds[2]), float(bounds[3]))
    authority = GhanaMapAuthority(acz.copy(), acz.copy(), extent, str(acz.crs))
    with plt.rc_context(matplotlib.RcParams(style.rc_params())):
        fig = plt.figure(figsize=style.full_width_map)
        container_ax = _map_axes(fig, style=style)
        panel_axes = build_map_panel_axes(fig, container_ax, style=style)
        map_ax = panel_axes.map_ax
        handles: list[Patch] = []
        for code in category_order:
            group = acz.loc[acz[category].astype(str).eq(code)]
            group.plot(
                ax=map_ax,
                facecolor=category_colours[code],
                edgecolor=style.acz_boundary_colour,
                linewidth=style.acz_boundary_width,
                rasterized=False,
            )
            handles.append(
                Patch(
                    facecolor=category_colours[code],
                    edgecolor=style.acz_boundary_colour,
                    label=category_labels.get(code, code),
                )
            )
        _finalise_map_axes(map_ax, authority, title=title)
        _add_scale_bar(map_ax, authority, style)
        _add_north_arrow(map_ax, authority, style)
        _draw_legend_band(panel_axes.support_or_status_legend_ax, handles, style=style)
        _draw_legend_band(panel_axes.colorbar_or_categorical_key_ax, [], style=style)
        return _export_map_figure(fig, style)


def choropleth(
    authority: GhanaMapAuthority,
    figure_data: pd.DataFrame,
    *,
    value: str,
    title: str,
    colorbar_label: str | None,
    style: PublicationStyle,
    cmap: str = "viridis",
    zero_tolerance: float = 0.0,
    norm: mcolors.Normalize | None = None,
) -> RenderedFigure:
    """Render a governed continuous district map with explicit support semantics."""

    with plt.rc_context(matplotlib.RcParams(style.rc_params())):
        fig, _ = _build_choropleth_figure(
            authority,
            figure_data,
            value=value,
            title=title,
            colorbar_label=colorbar_label,
            style=style,
            cmap=cmap,
            zero_tolerance=zero_tolerance,
            norm=norm,
        )
        return _export_map_figure(fig, style)


def support_map(
    authority: GhanaMapAuthority, figure_data: pd.DataFrame, *, title: str, style: PublicationStyle
) -> RenderedFigure:
    """Render analytical eligibility categorically with a governed below-map legend."""

    with plt.rc_context(matplotlib.RcParams(style.rc_params())):
        fig, _ = _build_support_map_figure(authority, figure_data, title=title, style=style)
        return _export_map_figure(fig, style)


def support_acz_map(
    authority: GhanaMapAuthority,
    figure_data: pd.DataFrame,
    *,
    title: str,
    style: PublicationStyle,
    category_order: tuple[str, ...] | None = None,
    category_colours: Mapping[str, str] | None = None,
    category_labels: Mapping[str, str] | None = None,
) -> RenderedFigure:
    """Render district support coloured by governed parent ACZ, with exclusions distinct."""

    with plt.rc_context(matplotlib.RcParams(style.rc_params())):
        fig = plt.figure(figsize=style.full_width_map)
        container_ax = _map_axes(fig, style=style)
        realised = draw_support_acz_axis(
            fig,
            container_ax,
            authority,
            figure_data,
            style=style,
            category_order=category_order,
            category_colours=category_colours,
            category_labels=category_labels,
        )
        realised.map_ax.set_title(title)
        return _export_map_figure(fig, style)


def acz_choropleth(
    authority: GhanaMapAuthority,
    figure_data: pd.DataFrame,
    *,
    value: str,
    title: str,
    colorbar_label: str,
    style: PublicationStyle,
    cmap: str = "viridis",
) -> RenderedFigure:
    """Render a governed continuous ACZ-level map from qualified values."""

    with plt.rc_context(matplotlib.RcParams(style.rc_params())):
        fig = plt.figure(figsize=style.full_width_map)
        container_ax = _map_axes(fig, style=style)
        realised = draw_acz_choropleth_axis(
            fig,
            container_ax,
            authority,
            figure_data,
            value=value,
            colorbar_label=colorbar_label,
            style=style,
            cmap=cmap,
        )
        realised.map_ax.set_title(title)
        return _export_map_figure(fig, style)


def categorical_map(
    authority: GhanaMapAuthority,
    figure_data: pd.DataFrame,
    *,
    category: str,
    title: str,
    style: PublicationStyle,
    class_order: tuple[str, ...] | None = None,
) -> RenderedFigure:
    """Render configured Local Moran classes with explicit support semantics."""

    with plt.rc_context(matplotlib.RcParams(style.rc_params())):
        fig = plt.figure(figsize=style.full_width_map)
        container_ax = _map_axes(fig, style=style)
        realised = draw_categorical_axis(
            fig,
            container_ax,
            authority,
            figure_data,
            category=category,
            style=style,
            class_order=class_order,
        )
        realised.map_ax.set_title(title)
        return _export_map_figure(fig, style)


# ---------------------------------------------------------------------------
# Grid-capable axis-level map drawing primitives.
# Parent grid cells are split deterministically into a scientific map viewport,
# a support/status legend band, and a colourbar/categorical-key band.  The two
# ancillary bands are always reserved, including when one is unused.
# ---------------------------------------------------------------------------


def draw_choropleth_axis(
    fig: Figure,
    ax: Axes,
    authority: GhanaMapAuthority,
    figure_data: pd.DataFrame,
    *,
    value: str,
    colorbar_label: str | None,
    style: PublicationStyle,
    cmap: str = "viridis",
    norm: mcolors.Normalize | None = None,
    draw_colorbar: bool = True,
) -> MapPanelAxes:
    """Draw one district continuous map without ancillary-driven viewport resizing."""

    if "support_status" not in figure_data.columns or value not in figure_data.columns:
        raise MappingError("Map figure data require support_status and configured value")
    panel_axes = build_map_panel_axes(fig, ax, style=style)
    map_ax = panel_axes.map_ax
    merged = join_district_figure_data(authority, figure_data)
    _validate_support_status(merged)
    excluded = merged[merged["support_status"].eq("excluded")]
    zeros = merged[merged["support_status"].eq("valid_zero")]
    valid = merged[merged["support_status"].eq("valid_nonzero")]
    realised_norm = norm if norm is not None else _continuous_norm(valid[value])
    if not valid.empty:
        valid.plot(
            column=value,
            ax=map_ax,
            cmap=cmap,
            norm=realised_norm,
            linewidth=style.boundary_width,
            edgecolor=style.boundary_colour,
            rasterized=False,
        )
    if not zeros.empty:
        zeros.plot(
            ax=map_ax,
            facecolor=style.semantic.valid_zero.face,
            edgecolor=style.semantic.valid_zero.edge,
            linewidth=style.boundary_width,
            rasterized=False,
        )
    if not excluded.empty:
        excluded.plot(
            ax=map_ax,
            facecolor=style.semantic.excluded.face,
            edgecolor=style.semantic.excluded.edge,
            hatch=style.semantic.excluded.hatch,
            linewidth=style.boundary_width,
            rasterized=False,
        )
    authority.acz.boundary.plot(
        ax=map_ax,
        color=style.acz_boundary_colour,
        linewidth=style.acz_boundary_width,
    )
    _finalise_map_axes(map_ax, authority, title="")
    _add_scale_bar(map_ax, authority, style)
    _add_north_arrow(map_ax, authority, style)

    handles: list[Patch] = []
    if style.map.distinguish_excluded_from_valid_zero:
        if not zeros.empty:
            handles.append(
                Patch(
                    facecolor=style.semantic.valid_zero.face,
                    edgecolor=style.semantic.valid_zero.edge,
                    label="Valid zero",
                )
            )
        if not excluded.empty:
            handles.append(
                Patch(
                    facecolor=style.semantic.excluded.face,
                    edgecolor=style.semantic.excluded.edge,
                    hatch=style.semantic.excluded.hatch,
                    label="Excluded / unsupported",
                )
            )
    _draw_legend_band(panel_axes.support_or_status_legend_ax, handles, style=style)
    if draw_colorbar:
        _draw_colorbar_band(
            fig,
            panel_axes.colorbar_or_categorical_key_ax,
            norm=realised_norm,
            cmap=cmap,
            label=colorbar_label,
            style=style,
            gid="map-colorbar-grid",
        )
    else:
        panel_axes.colorbar_or_categorical_key_ax.clear()
        panel_axes.colorbar_or_categorical_key_ax.set_axis_off()
    return panel_axes


def draw_acz_choropleth_axis(
    fig: Figure,
    ax: Axes,
    authority: GhanaMapAuthority,
    figure_data: pd.DataFrame,
    *,
    value: str,
    colorbar_label: str,
    style: PublicationStyle,
    cmap: str = "viridis",
) -> MapPanelAxes:
    """Draw one continuous ACZ map with the same reserved bands as district maps."""

    required = {"unit_id", value}
    missing = sorted(required.difference(figure_data.columns))
    if missing:
        raise MappingError(f"ACZ choropleth source missing columns: {missing!r}")
    if figure_data["unit_id"].astype(str).duplicated().any():
        raise MappingError("ACZ choropleth source has duplicate unit IDs")
    panel_axes = build_map_panel_axes(fig, ax, style=style)
    map_ax = panel_axes.map_ax
    left = authority.acz.copy()
    left["_join_key"] = left["zone_id"].astype(str)
    right = figure_data[["unit_id", value]].copy()
    right["_join_key"] = right["unit_id"].astype(str)
    merged = left.merge(
        right.drop(columns=["unit_id"]),
        on="_join_key",
        how="left",
        validate="one_to_one",
    )
    if merged[value].isna().any():
        raise MappingError("ACZ choropleth is missing a governed value")
    norm = _continuous_norm(merged[value])
    merged.plot(
        column=value,
        ax=map_ax,
        cmap=cmap,
        norm=norm,
        edgecolor=style.acz_boundary_colour,
        linewidth=style.acz_boundary_width,
        rasterized=False,
    )
    authority.districts.boundary.plot(
        ax=map_ax,
        color=style.boundary_colour,
        linewidth=0.15,
        alpha=0.35,
    )
    _finalise_map_axes(map_ax, authority, title="")
    _add_scale_bar(map_ax, authority, style)
    _add_north_arrow(map_ax, authority, style)
    _draw_legend_band(panel_axes.support_or_status_legend_ax, [], style=style)
    _draw_colorbar_band(
        fig,
        panel_axes.colorbar_or_categorical_key_ax,
        norm=norm,
        cmap=cmap,
        label=colorbar_label,
        style=style,
        gid="map-colorbar-grid",
    )
    return panel_axes


def draw_support_acz_axis(
    fig: Figure,
    ax: Axes,
    authority: GhanaMapAuthority,
    figure_data: pd.DataFrame,
    *,
    style: PublicationStyle,
    category_order: tuple[str, ...] | None = None,
    category_colours: Mapping[str, str] | None = None,
    category_labels: Mapping[str, str] | None = None,
) -> MapPanelAxes:
    """Draw retained district support coloured by parent ACZ in a reserved-band panel."""

    required = {"unit_id", "parent_code", "support_status"}
    missing = sorted(required.difference(figure_data.columns))
    if missing:
        raise MappingError(f"ACZ support map source missing columns: {missing!r}")
    panel_axes = build_map_panel_axes(fig, ax, style=style)
    map_ax = panel_axes.map_ax
    merged = join_district_figure_data(authority, figure_data)
    _validate_support_status(merged)
    retained = merged.loc[~merged["support_status"].eq("excluded")]
    excluded = merged.loc[merged["support_status"].eq("excluded")]
    observed_codes = tuple(dict.fromkeys(retained["parent_code"].dropna().astype(str).tolist()))
    if category_order is None:
        codes = observed_codes
    else:
        unexpected = sorted(set(observed_codes).difference(category_order))
        if unexpected:
            raise MappingError(f"ACZ support map contains categories outside configured order: {unexpected!r}")
        codes = tuple(code for code in category_order if code in set(observed_codes))
    cmap = plt.get_cmap("tab20")
    handles: list[Patch] = []
    for idx, code in enumerate(codes):
        group = retained.loc[retained["parent_code"].astype(str).eq(code)]
        if category_colours is not None:
            if code not in category_colours:
                raise MappingError(f"ACZ support map lacks configured colour for {code!r}")
            colour = category_colours[code]
        else:
            colour = cmap(idx / max(1, len(codes) - 1))
        group.plot(
            ax=map_ax,
            facecolor=colour,
            edgecolor=style.boundary_colour,
            linewidth=style.boundary_width,
            rasterized=False,
        )
        label = category_labels.get(code, code) if category_labels is not None else code
        handles.append(Patch(facecolor=colour, edgecolor=style.boundary_colour, label=label))
    if not excluded.empty:
        excluded.plot(
            ax=map_ax,
            facecolor=style.semantic.excluded.face,
            edgecolor=style.semantic.excluded.edge,
            hatch=style.semantic.excluded.hatch,
            linewidth=style.boundary_width,
            rasterized=False,
        )
        handles.append(
            Patch(
                facecolor=style.semantic.excluded.face,
                edgecolor=style.semantic.excluded.edge,
                hatch=style.semantic.excluded.hatch,
                label="Excluded",
            )
        )
    authority.acz.boundary.plot(
        ax=map_ax,
        color=style.acz_boundary_colour,
        linewidth=style.acz_boundary_width,
    )
    _finalise_map_axes(map_ax, authority, title="")
    _add_scale_bar(map_ax, authority, style)
    _add_north_arrow(map_ax, authority, style)
    _draw_legend_band(panel_axes.support_or_status_legend_ax, handles, style=style)
    return panel_axes


def draw_categorical_axis(
    fig: Figure,
    ax: Axes,
    authority: GhanaMapAuthority,
    figure_data: pd.DataFrame,
    *,
    category: str,
    style: PublicationStyle,
    class_order: tuple[str, ...] | None = None,
) -> MapPanelAxes:
    """Draw the configured Local Moran semantic classes without automatic palettes."""

    required = {"unit_id", category, "support_status"}
    missing = sorted(required.difference(figure_data.columns))
    if missing:
        raise MappingError(f"Categorical map source missing columns: {missing!r}")
    panel_axes = build_map_panel_axes(fig, ax, style=style)
    map_ax = panel_axes.map_ax
    merged = join_district_figure_data(authority, figure_data)
    _validate_support_status(merged)
    allowed = class_order or ("HH", "LL", "HL", "LH", "NS", "ISLAND")
    unexpected = sorted(
        set(merged.loc[~merged["support_status"].eq("excluded"), category].dropna().astype(str))
        .difference(allowed)
    )
    if unexpected:
        raise MappingError(f"Categorical map contains classes outside configured order: {unexpected!r}")
    class_handles: list[Patch] = []
    for cat in allowed:
        group = merged.loc[
            (~merged["support_status"].eq("excluded"))
            & merged[category].astype(str).eq(cat)
        ]
        if group.empty:
            continue
        state = style.semantic.local_moran[cat]
        hatch = state.hatch or None
        group.plot(
            ax=map_ax,
            facecolor=state.face,
            edgecolor=state.edge,
            hatch=hatch,
            linewidth=style.boundary_width,
            rasterized=False,
        )
        class_handles.append(
            Patch(facecolor=state.face, edgecolor=state.edge, hatch=hatch, label=cat)
        )
    excluded = merged.loc[merged["support_status"].eq("excluded")]
    support_handles: list[Patch] = []
    if not excluded.empty:
        excluded.plot(
            ax=map_ax,
            facecolor=style.semantic.excluded.face,
            edgecolor=style.semantic.excluded.edge,
            hatch=style.semantic.excluded.hatch,
            linewidth=style.boundary_width,
            rasterized=False,
        )
        support_handles.append(
            Patch(
                facecolor=style.semantic.excluded.face,
                edgecolor=style.semantic.excluded.edge,
                hatch=style.semantic.excluded.hatch,
                label="Excluded / unsupported",
            )
        )
    authority.acz.boundary.plot(
        ax=map_ax,
        color=style.acz_boundary_colour,
        linewidth=style.acz_boundary_width,
    )
    _finalise_map_axes(map_ax, authority, title="")
    _add_scale_bar(map_ax, authority, style)
    _add_north_arrow(map_ax, authority, style)
    _draw_legend_band(panel_axes.support_or_status_legend_ax, support_handles, style=style)
    _draw_legend_band(
        panel_axes.colorbar_or_categorical_key_ax,
        class_handles,
        style=style,
        gid="map-local-moran-key",
    )
    return panel_axes


def draw_cluster_membership_axis(
    fig: Figure,
    ax: Axes,
    authority: GhanaMapAuthority,
    figure_data: pd.DataFrame,
    *,
    style: PublicationStyle,
) -> tuple[MapPanelAxes, bool, bool]:
    """Draw current binary significant-cluster membership without redefining recurrence."""

    panel_axes = build_map_panel_axes(fig, ax, style=style)
    map_ax = panel_axes.map_ax
    merged = join_district_figure_data(authority, figure_data)
    _validate_support_status(merged)
    members = merged.loc[merged["support_status"].eq("valid_nonzero")]
    nonmembers = merged.loc[merged["support_status"].eq("valid_zero")]
    excluded = merged.loc[merged["support_status"].eq("excluded")]
    if not nonmembers.empty:
        nonmembers.plot(
            ax=map_ax,
            facecolor=style.semantic.valid_zero.face,
            edgecolor=style.semantic.valid_zero.edge,
            linewidth=style.boundary_width,
            rasterized=False,
        )
    if not members.empty:
        members.plot(
            ax=map_ax,
            facecolor="0.35",
            edgecolor=style.boundary_colour,
            linewidth=style.boundary_width,
            rasterized=False,
        )
    if not excluded.empty:
        excluded.plot(
            ax=map_ax,
            facecolor=style.semantic.excluded.face,
            edgecolor=style.semantic.excluded.edge,
            hatch=style.semantic.excluded.hatch,
            linewidth=style.boundary_width,
            rasterized=False,
        )
    authority.acz.boundary.plot(
        ax=map_ax,
        color=style.acz_boundary_colour,
        linewidth=style.acz_boundary_width,
    )
    _finalise_map_axes(map_ax, authority, title="")
    _add_scale_bar(map_ax, authority, style)
    _add_north_arrow(map_ax, authority, style)
    return panel_axes, (not members.empty), (not excluded.empty)



def build_cluster_recurrence_map_figure(
    authority: GhanaMapAuthority,
    figure_data: pd.DataFrame,
    *,
    product_column: str,
    panel_order: tuple[str, ...] | list[str],
    value_column: str,
    panel_titles: tuple[str, ...] | list[str],
    cmap: str,
    colorbar_label: str,
    colorbar_labelpad_pt: float | None,
    style: PublicationStyle,
    layout: GridLayoutContract,
    figure_size: tuple[float, float],
) -> tuple[Figure, tuple[MapPanelAxes, ...], Axes]:
    """Build the descriptive recurrence map pair with one common colour normalisation."""
    if len(panel_order) != len(layout.data_cells):
        raise MappingError("Cluster-recurrence panel order must match configured data cells")
    if len(panel_titles) != len(panel_order):
        raise MappingError("Cluster-recurrence panel titles must match configured products")
    required = {product_column, "unit_id", value_column, "support_status", "exclusion_reasons"}
    missing = sorted(required.difference(figure_data.columns))
    if missing:
        raise MappingError(f"Cluster recurrence source missing columns: {missing!r}")
    observed_products = set(figure_data[product_column].astype(str))
    if observed_products != set(str(x) for x in panel_order):
        raise MappingError("Cluster recurrence source products do not match configured panel order")

    non_excluded = figure_data.loc[~figure_data["support_status"].astype(str).eq("excluded"), value_column]
    numeric = pd.to_numeric(non_excluded, errors="coerce")
    if numeric.isna().any() or (numeric < 0).any() or not np.allclose(
        numeric.to_numpy(dtype=float), np.round(numeric.to_numpy(dtype=float)), atol=0.0, rtol=0.0
    ):
        raise MappingError("Cluster recurrence plotted values must be non-negative integers")
    positive = numeric.loc[numeric.gt(0)]
    common_norm = _continuous_norm(positive)

    grid = build_grid_figure(layout, figure_size=figure_size)
    apply_grid_spacing(grid.figure, layout, style=style)
    realised_panels: list[MapPanelAxes] = []
    any_excluded = False
    for idx, (product, title) in enumerate(zip(panel_order, panel_titles, strict=True)):
        panel = figure_data.loc[figure_data[product_column].astype(str).eq(str(product))].copy()
        realised = draw_choropleth_axis(
            grid.figure,
            grid.data_axes[idx],
            authority,
            panel,
            value=value_column,
            colorbar_label=colorbar_label,
            style=style,
            cmap=cmap,
            norm=common_norm,
            draw_colorbar=False,
        )
        realised.map_ax.set_title(str(title))
        any_excluded |= panel["support_status"].astype(str).eq("excluded").any()
        realised_panels.append(realised)

    status_handles = [
        Patch(
            facecolor=style.semantic.valid_zero.face,
            edgecolor=style.semantic.valid_zero.edge,
            label="Valid zero",
        )
    ]
    if any_excluded:
        status_handles.append(
            Patch(
                facecolor=style.semantic.excluded.face,
                edgecolor=style.semantic.excluded.edge,
                hatch=style.semantic.excluded.hatch,
                label="Excluded / unsupported",
            )
        )
    legend_bounds = [realised.support_or_status_legend_ax.get_position().bounds for realised in realised_panels]
    legend_left = min(float(b[0]) for b in legend_bounds)
    legend_bottom = min(float(b[1]) for b in legend_bounds)
    legend_right = max(float(b[0] + b[2]) for b in legend_bounds)
    legend_top = max(float(b[1] + b[3]) for b in legend_bounds)
    for realised in realised_panels:
        realised.support_or_status_legend_ax.set_visible(False)
    shared_legend_ax = grid.figure.add_axes(
        (legend_left, legend_bottom, legend_right - legend_left, legend_top - legend_bottom)
    )
    shared_legend_ax.set_gid("map-shared-cluster-recurrence-status-legend")
    _draw_legend_band(
        shared_legend_ax,
        status_handles,
        style=style,
        gid="map-shared-cluster-recurrence-status-legend",
    )

    key_bounds = [realised.colorbar_or_categorical_key_ax.get_position().bounds for realised in realised_panels]
    left = min(float(b[0]) for b in key_bounds)
    bottom = min(float(b[1]) for b in key_bounds)
    right = max(float(b[0] + b[2]) for b in key_bounds)
    top = max(float(b[1] + b[3]) for b in key_bounds)
    for realised in realised_panels:
        realised.colorbar_or_categorical_key_ax.set_visible(False)
    shared_colorbar_ax = grid.figure.add_axes((left, bottom, right - left, top - bottom))
    shared_colorbar_ax.set_gid("map-shared-cluster-recurrence-colorbar")
    _draw_colorbar_band(
        grid.figure,
        shared_colorbar_ax,
        norm=common_norm,
        cmap=cmap,
        label=colorbar_label,
        style=style,
        gid="map-shared-cluster-recurrence-colorbar",
        labelpad_pt=colorbar_labelpad_pt,
    )

    map_axes = tuple(realised.map_ax for realised in realised_panels)
    add_panel_labels(map_axes, style=style)
    apply_axis_label_padding(map_axes, style=style)
    return grid.figure, tuple(realised_panels), shared_colorbar_ax


def cluster_recurrence_maps_grid(
    authority: GhanaMapAuthority,
    figure_data: pd.DataFrame,
    *,
    product_column: str,
    panel_order: tuple[str, ...] | list[str],
    value_column: str,
    panel_titles: tuple[str, ...] | list[str],
    cmap: str,
    colorbar_label: str,
    colorbar_labelpad_pt: float | None,
    style: PublicationStyle,
    layout: GridLayoutContract,
    figure_size: tuple[float, float],
) -> RenderedFigure:
    """Render validated significant-cluster recurrence as a descriptive paired map."""
    with plt.rc_context(matplotlib.RcParams(style.rc_params())):
        fig, _, _ = build_cluster_recurrence_map_figure(
            authority,
            figure_data,
            product_column=product_column,
            panel_order=panel_order,
            value_column=value_column,
            panel_titles=panel_titles,
            cmap=cmap,
            colorbar_label=colorbar_label,
            colorbar_labelpad_pt=colorbar_labelpad_pt,
            style=style,
            layout=layout,
            figure_size=figure_size,
        )
        return _export_map_figure(fig, style)


def cluster_maps_grid(
    authority: GhanaMapAuthority,
    figure_data: pd.DataFrame,
    *,
    product_column: str,
    panel_order: tuple[str, ...] | list[str],
    style: PublicationStyle,
    layout: GridLayoutContract,
    figure_size: tuple[float, float],
) -> RenderedFigure:
    """Render current cluster-membership maps through invariant paired viewports."""

    if len(panel_order) != len(layout.data_cells):
        raise MappingError("Cluster-map panel order must match configured data cells")
    if product_column not in figure_data.columns:
        raise MappingError(f"Cluster map source missing product column {product_column!r}")
    with plt.rc_context(matplotlib.RcParams(style.rc_params())):
        grid = build_grid_figure(layout, figure_size=figure_size)
        apply_grid_spacing(grid.figure, layout, style=style)
        any_members = False
        any_excluded = False
        panel_axes: list[MapPanelAxes] = []
        for idx, product in enumerate(panel_order):
            panel = figure_data.loc[
                figure_data[product_column].astype(str).eq(str(product))
            ].copy()
            if panel.empty:
                plt.close(grid.figure)
                raise MappingError(f"Configured cluster-map product has no rows: {product!r}")
            realised, members, excluded = draw_cluster_membership_axis(
                grid.figure,
                grid.data_axes[idx],
                authority,
                panel,
                style=style,
            )
            panel_axes.append(realised)
            any_members |= members
            any_excluded |= excluded
        handles = [
            Patch(
                facecolor=style.semantic.valid_zero.face,
                edgecolor=style.semantic.valid_zero.edge,
                label="No significant cluster membership",
            )
        ]
        if any_members:
            handles.insert(
                0,
                Patch(
                    facecolor="0.35",
                    edgecolor=style.boundary_colour,
                    label="Significant cluster member",
                ),
            )
        if any_excluded:
            handles.append(
                Patch(
                    facecolor=style.semantic.excluded.face,
                    edgecolor=style.semantic.excluded.edge,
                    hatch=style.semantic.excluded.hatch,
                    label="Excluded / unsupported",
                )
            )
        for realised in panel_axes:
            _draw_legend_band(
                realised.support_or_status_legend_ax,
                handles,
                style=style,
            )
        map_axes = tuple(realised.map_ax for realised in panel_axes)
        add_panel_labels(map_axes, style=style)
        apply_axis_label_padding(map_axes, style=style)
        return _export_map_figure(grid.figure, style)
