"""geo_data_prep.plots.combined

Deterministic plotting for Stage 1 boundary products.

Plot contract:
- Provide a combined zones + districts overview map.

Notes on determinism
--------------------
Plot outputs are designed to be *content-deterministic* given identical inputs
(same geometries/attributes). Full byte-for-byte determinism across platforms
cannot be guaranteed because font rendering and matplotlib backends may differ.
We nevertheless enforce stable ordering, fixed figure geometry, and fixed colour
assignment.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


class PlotError(RuntimeError):
    """Raised when plotting fails or required plotting deps are unavailable."""


def _require_deps() -> tuple[object, object]:
    try:
        import geopandas as gpd  # type: ignore
    except Exception as e:  # pragma: no cover
        raise PlotError(
            "geopandas is required for plotting. Install via conda env (environment.yml)."
        ) from e

    try:
        import matplotlib

        matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt  # type: ignore
    except Exception as e:  # pragma: no cover
        raise PlotError(
            "matplotlib is required for plotting. Install via conda env (environment.yml)."
        ) from e

    return gpd, plt


def _require_cols(gdf: object, cols: Sequence[str], *, obj_name: str) -> None:
    missing = [c for c in cols if c not in getattr(gdf, "columns", [])]
    if missing:
        raise PlotError(f"{obj_name} missing required columns: {missing}")


def _crs_equal(src_crs: object, dst_crs: str) -> bool:
    try:
        from pyproj import CRS  # type: ignore

        return CRS.from_user_input(src_crs) == CRS.from_user_input(dst_crs)
    except Exception:
        return str(src_crs) == str(dst_crs)


def _nice_step(span_deg: float) -> float:
    """Choose a human-friendly lat/lon grid step size in degrees."""
    if span_deg <= 1:
        return 0.2
    if span_deg <= 2:
        return 0.5
    if span_deg <= 5:
        return 1.0
    if span_deg <= 10:
        return 2.0
    if span_deg <= 20:
        return 5.0
    return 10.0


def _add_latlon_grid(ax: object) -> None:
    try:
        x0, x1 = ax.get_xlim()
        y0, y1 = ax.get_ylim()
    except Exception as e:  # pragma: no cover
        raise PlotError(f"Failed to read axis limits for grid: {e}") from e

    span_x = abs(float(x1) - float(x0))
    span_y = abs(float(y1) - float(y0))
    step = _nice_step(max(span_x, span_y))

    import numpy as np  # type: ignore

    # Round to step grid.
    x_min = step * np.floor(min(x0, x1) / step)
    x_max = step * np.ceil(max(x0, x1) / step)
    y_min = step * np.floor(min(y0, y1) / step)
    y_max = step * np.ceil(max(y0, y1) / step)

    xticks = np.arange(x_min, x_max + step * 0.5, step)
    yticks = np.arange(y_min, y_max + step * 0.5, step)

    ax.set_xticks(xticks)
    ax.set_yticks(yticks)
    ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.5)
    ax.set_xlabel("Longitude (deg)")
    ax.set_ylabel("Latitude (deg)")


def _add_north_arrow(ax: object) -> None:
    """Add a simple north arrow in axis-fraction coordinates."""
    ax.annotate(
        "N",
        xy=(0.95, 0.92),
        xytext=(0.95, 0.80),
        xycoords="axes fraction",
        textcoords="axes fraction",
        ha="center",
        va="center",
        fontsize=12,
        arrowprops=dict(arrowstyle="-|>", lw=1.2),
    )


_ZONE_PALETTE_HEX: tuple[str, ...] = (
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
)


def _zone_colour_map(values: Iterable[str]) -> Mapping[str, str]:
    cats = sorted({str(v) for v in values})
    if not cats:
        return {}
    return {c: _ZONE_PALETTE_HEX[i % len(_ZONE_PALETTE_HEX)] for i, c in enumerate(cats)}


@dataclass(frozen=True)
class CombinedPlotOutputs:
    png_path: Path


def plot_combined_zones_districts(
    zones: object,
    districts: object,
    *,
    out_dir: Path | None = None,
    out_path: Path | None = None,
    title: str,
    zone_fill_col: str = "zone_name",
    plot_crs: str = "EPSG:4326",
    dpi: int = 200,
    figsize: tuple[float, float] = (12.0, 8.0),
) -> CombinedPlotOutputs:
    """Create a combined zones + districts overview map and save to PNG.

    Requirements implemented
    ------------------------
    - Title
    - Zones filled by a categorical attribute (default: zone_name)
    - District outlines overlaid
    - Legend outside top-right (dedicated legend pane)
    - Lat–lon grid (plot_crs must be geographic for a true graticule)
    - North arrow
    """

    gpd, plt = _require_deps()

    if out_path is None:
        if out_dir is None:
            raise PlotError("Provide either out_dir (preferred) or out_path")
        out_path = Path(out_dir) / "plots" / "combined_zones_districts.png"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    _require_cols(zones, [zone_fill_col, "geometry"], obj_name="zones")
    _require_cols(districts, ["geometry"], obj_name="districts")

    if getattr(zones, "crs", None) is None:
        raise PlotError("zones CRS is missing")
    if getattr(districts, "crs", None) is None:
        raise PlotError("districts CRS is missing")

    z = zones
    d = districts
    if not _crs_equal(z.crs, plot_crs):
        z = z.to_crs(plot_crs)
    if not _crs_equal(d.crs, plot_crs):
        d = d.to_crs(plot_crs)

    # Deterministic plotting order.
    z = z.copy()
    z["_fill"] = z[zone_fill_col].astype(str)
    z = z.sort_values(["_fill"], kind="mergesort")
    d = d.copy()

    cmap = _zone_colour_map(z["_fill"].tolist())

    fig = plt.figure(figsize=figsize, dpi=int(dpi))
    ax = fig.add_axes([0.05, 0.07, 0.65, 0.88])
    ax_leg = fig.add_axes([0.72, 0.07, 0.26, 0.88])
    ax_leg.axis("off")

    # Plot zones grouped by category for stable colours.
    for cat in sorted(cmap.keys()):
        sub = z.loc[z["_fill"] == cat]
        if len(sub) == 0:
            continue
        sub.plot(ax=ax, color=cmap[cat], edgecolor="black", linewidth=0.6)

    # District outlines.
    try:
        d.boundary.plot(ax=ax, color="black", linewidth=0.4)
    except Exception as e:
        raise PlotError(f"Failed to plot district boundaries: {e}") from e

    ax.set_title(title)
    ax.set_aspect("equal")

    _add_latlon_grid(ax)
    _add_north_arrow(ax)

    # Legend outside top-right (in the legend pane).
    try:
        from matplotlib.patches import Patch  # type: ignore
    except Exception as e:  # pragma: no cover
        raise PlotError(f"matplotlib patches unavailable: {e}") from e

    handles = [
        Patch(facecolor=cmap[k], edgecolor="black", label=str(k)) for k in sorted(cmap.keys())
    ]
    ax_leg.legend(handles=handles, title=zone_fill_col, loc="upper left", frameon=True)

    try:
        fig.savefig(out_path, format="png", dpi=int(dpi), facecolor="white")
    except Exception as e:
        raise PlotError(f"Failed to save combined plot PNG: {out_path}: {e}") from e
    finally:
        plt.close(fig)

    return CombinedPlotOutputs(png_path=out_path)
