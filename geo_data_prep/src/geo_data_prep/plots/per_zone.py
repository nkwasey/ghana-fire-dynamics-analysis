"""geo_data_prep.plots.per_zone

Deterministic per-zone district maps.

Plot contract:
- For each zone, render its districts with index numbers printed on polygons.
- Include a legend mapping index → district name.
- Legend outside top-right, lat–lon grid, north arrow.

This module expects *enriched* districts (i.e., districts already assigned to a
zone via Stage 1 overlay logic), so that each district belongs to exactly one
zone.
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


def _format_index_name_lines(
    pairs: Sequence[tuple[int, str]], *, max_rows_per_col: int = 35
) -> list[str]:
    """Format a deterministic multi-column text legend."""
    if not pairs:
        return ["<no districts>"]

    n = len(pairs)
    cols = (n + max_rows_per_col - 1) // max_rows_per_col
    cols = max(1, min(int(cols), 4))
    rows = (n + cols - 1) // cols

    # Split into columns.
    columns: list[list[str]] = []
    for c in range(cols):
        start = c * rows
        end = min((c + 1) * rows, n)
        col_pairs = pairs[start:end]
        columns.append([f"{i:02d}  {name}" for i, name in col_pairs])

    # Pad columns to equal length.
    max_len = max(len(col) for col in columns)
    for col in columns:
        while len(col) < max_len:
            col.append("")

    # Row-wise merge with fixed spacing.
    merged: list[str] = []
    for r in range(max_len):
        parts = [columns[c][r].ljust(34) for c in range(cols)]
        merged.append(" ".join(parts).rstrip())
    return merged


@dataclass(frozen=True)
class PerZonePlotOutputs:
    zone_id: str
    png_path: Path


def plot_per_zone_maps(
    zones: object,
    districts_enriched: object,
    *,
    out_dir: Path,
    title_prefix: str = "Zone",
    zone_id_col: str = "zone_id",
    zone_name_col: str = "zone_name",
    district_id_col: str = "district_id",
    district_name_col: str = "district_name",
    plot_crs: str = "EPSG:4326",
    dpi: int = 200,
    figsize: tuple[float, float] = (14.0, 8.0),
) -> list[PerZonePlotOutputs]:
    """Render one per-zone map per zone and save PNGs.

    Parameters
    ----------
    zones:
        Zones GeoDataFrame containing at least `zone_id_col`, `zone_name_col` and geometry.
    districts_enriched:
        Districts GeoDataFrame containing at least `district_id_col`, `district_name_col`,
        `zone_id_col`, and geometry. Each district must belong to exactly one zone.
    out_dir:
        Output directory. Files are written under `<out_dir>/plots/per_zone/`.
    """

    gpd, plt = _require_deps()
    out_dir = Path(out_dir)
    pdir = out_dir / "plots" / "per_zone"
    pdir.mkdir(parents=True, exist_ok=True)

    _require_cols(zones, [zone_id_col, zone_name_col, "geometry"], obj_name="zones")
    _require_cols(
        districts_enriched,
        [district_id_col, district_name_col, zone_id_col, "geometry"],
        obj_name="districts_enriched",
    )

    if getattr(zones, "crs", None) is None:
        raise PlotError("zones CRS is missing")
    if getattr(districts_enriched, "crs", None) is None:
        raise PlotError("districts_enriched CRS is missing")

    z = zones
    d = districts_enriched
    if not _crs_equal(z.crs, plot_crs):
        z = z.to_crs(plot_crs)
    if not _crs_equal(d.crs, plot_crs):
        d = d.to_crs(plot_crs)

    z = z.copy()
    z["_zid"] = z[zone_id_col].astype(str)
    z["_zname"] = z[zone_name_col].astype(str)
    z = z.sort_values(["_zid", "_zname"], kind="mergesort")

    # Stable zone colours by sorted zone name (consistent with combined map).
    zone_colours = _zone_colour_map(z["_zname"].tolist())

    outputs: list[PerZonePlotOutputs] = []

    for _, zr in z.iterrows():
        zid = str(zr["_zid"])
        zname = str(zr["_zname"])

        dz = d.loc[d[zone_id_col].astype(str) == zid].copy()
        dz[district_name_col] = dz[district_name_col].astype(str)
        dz[district_id_col] = dz[district_id_col].astype(str)
        dz = dz.sort_values([district_name_col, district_id_col], kind="mergesort")

        # Deterministic index assignment (1..N).
        idx_map = {did: i + 1 for i, did in enumerate(dz[district_id_col].tolist())}
        dz["_idx"] = dz[district_id_col].map(idx_map)

        # Label positions: representative point (more stable than centroid for polygons).
        try:
            reps = dz.representative_point()
        except Exception as e:
            raise PlotError(f"Failed to compute representative points for {zid}: {e}") from e
        dz["_rx"] = reps.x
        dz["_ry"] = reps.y

        fig = plt.figure(figsize=figsize, dpi=int(dpi))
        ax = fig.add_axes([0.05, 0.07, 0.65, 0.88])
        ax_leg = fig.add_axes([0.72, 0.07, 0.26, 0.88])
        ax_leg.axis("off")

        # Zone background (filled) and outline.
        try:
            zrow = gpd.GeoDataFrame({"_zname": [zname]}, geometry=[zr.geometry], crs=plot_crs)
            fill = zone_colours.get(zname, "#dddddd")
            zrow.plot(ax=ax, color=fill, edgecolor="black", linewidth=0.8)
        except Exception as e:
            raise PlotError(f"Failed to plot zone geometry for {zid}: {e}") from e

        # District outlines.
        try:
            if len(dz) > 0:
                dz.plot(ax=ax, facecolor="none", edgecolor="black", linewidth=0.6)
        except Exception as e:
            raise PlotError(f"Failed to plot districts for {zid}: {e}") from e

        # District index labels.
        for i, x, y in zip(
            dz["_idx"].tolist(), dz["_rx"].tolist(), dz["_ry"].tolist(), strict=False
        ):
            ax.text(float(x), float(y), str(int(i)), ha="center", va="center", fontsize=8)

        ax.set_title(f"{title_prefix}: {zname}")
        ax.set_aspect("equal")
        _add_latlon_grid(ax)
        _add_north_arrow(ax)

        # Legend: index -> district name (outside top-right pane).
        pairs = [
            (int(i), str(n))
            for i, n in zip(dz["_idx"].tolist(), dz[district_name_col].tolist(), strict=False)
        ]
        lines = _format_index_name_lines(pairs, max_rows_per_col=35)
        ax_leg.text(
            0.0,
            1.0,
            "District index → name\n" + "\n".join(lines),
            ha="left",
            va="top",
            fontsize=8,
            family="DejaVu Sans Mono",
        )

        out_path = pdir / f"zone_{zid}.png"
        try:
            fig.savefig(out_path, format="png", dpi=int(dpi), facecolor="white")
        except Exception as e:
            raise PlotError(f"Failed to save per-zone plot PNG: {out_path}: {e}") from e
        finally:
            plt.close(fig)

        outputs.append(PerZonePlotOutputs(zone_id=zid, png_path=out_path))

    return outputs
