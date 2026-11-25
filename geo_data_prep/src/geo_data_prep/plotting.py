"""Numbered reporting-zone maps, district-name keys and measured label QA."""
from __future__ import annotations

from pathlib import Path
import math
import textwrap

import geopandas as gpd
import pandas as pd
from shapely import union_all
from shapely.affinity import affine_transform
from shapely.geometry import Point, box
from shapely.ops import polylabel

LABEL_COLUMNS = ["dist_id", "dist_name", "zone_id", "anchor_lon", "anchor_lat",
                 "label_number", "label_text"]


def label_layout(districts: gpd.GeoDataFrame) -> pd.DataFrame:
    """Return stable alphabetical district numbers and interior reference points.

    Rendering chooses readable number positions separately for each map panel.
    The reference points and all rendered position/bounding-box coordinates use
    EPSG:4326. Numeric map identifiers are local to a zone, not administrative IDs.
    """
    required = {"dist_id", "dist_name", "zone_id", "geometry"}
    if not required.issubset(districts.columns) or districts.crs is None:
        raise ValueError("Numbered plots require district IDs, names, zones, geometry and CRS")
    if districts.empty or districts.dist_id.isna().any() or not districts.dist_id.is_unique:
        raise ValueError("Numbered plots require nonempty unique district IDs")
    if districts.dist_name.isna().any() or not districts.dist_name.astype(str).str.strip().all():
        raise ValueError("Numbered plots require nonempty district names")
    display = districts.to_crs(4326)
    rows = []
    for _, district in display.iterrows():
        anchor = district.geometry.representative_point()
        if anchor.is_empty or not all(math.isfinite(v) for v in (anchor.x, anchor.y)) or not district.geometry.covers(anchor):
            raise ValueError("District reference point must be finite and inside its polygon")
        rows.append({"dist_id": str(district.dist_id), "dist_name": str(district.dist_name),
                     "zone_id": str(district.zone_id), "anchor_lon": anchor.x,
                     "anchor_lat": anchor.y, "label_text": str(district.dist_name)})
    ordered = sorted(rows, key=lambda r: (r["dist_name"].casefold(), r["dist_id"]))
    for number, row in enumerate(ordered, start=1):
        row["label_number"] = number
    return pd.DataFrame(ordered, columns=LABEL_COLUMNS).sort_values("dist_id").reset_index(drop=True)


def _check_label_boxes(fig, artists):
    """Check the final district-name key for clipping and text collisions."""
    fig.canvas.draw()
    renderer, bounds = fig.canvas.get_renderer(), fig.bbox
    boxes = [artist.get_window_extent(renderer) for artist in artists]
    for b in boxes:
        if b.x0 < bounds.x0 + 2 or b.x1 > bounds.x1 - 2 or b.y0 < bounds.y0 + 2 or b.y1 > bounds.y1 - 2:
            raise ValueError("District key text extends outside the figure")
    if any(a.overlaps(b) for i, a in enumerate(boxes) for b in boxes[i + 1:]):
        raise ValueError("District names overlap in the key")
    return {"district_label_count": len(boxes), "label_bbox_overlap_count": 0,
            "label_bbox_clipped_count": 0}


def _overview(districts, zones, root, colors):
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    fig, ax = plt.subplots(figsize=(10, 10))
    d, z = districts.to_crs(4326), zones.to_crs(4326)
    d.plot(ax=ax, color=[colors[x] for x in d.zone_id], edgecolor="#ffffff", linewidth=.25)
    z.boundary.plot(ax=ax, color="#253449", linewidth=.8)
    ax.set_title("District-based reporting zones", pad=16)
    ax.set_xlabel("Longitude (degrees)"); ax.set_ylabel("Latitude (degrees)")
    ax.legend(handles=[Patch(facecolor=colors[row.zone_id], label=row.zone_name) for _, row in z.iterrows()],
              loc="center left", bbox_to_anchor=(1.02, .5), fontsize=8, frameon=False)
    ax.grid(alpha=.2)
    fig.text(.5, .02, "Whole districts assigned by maximum overlap with the supplied reference zones.", ha="center", fontsize=8)
    fig.tight_layout(rect=(0, .04, 1, 1))
    fig.savefig(root / "combined_zones_districts.png", dpi=150)
    plt.close(fig)


def _polygon_parts(geometry):
    if geometry.geom_type == "Polygon":
        return [geometry]
    parts = []
    for child in getattr(geometry, "geoms", []):
        parts.extend(_polygon_parts(child))
    return parts


def _candidates(pixel_geometry):
    """Candidate centres favour wide interiors rather than polygon centroids."""
    result = []
    for polygon in sorted(_polygon_parts(pixel_geometry), key=lambda g: -g.area)[:6]:
        centre = polylabel(polygon, tolerance=.6)
        result.extend([centre, polygon.representative_point()])
        if polygon.covers(polygon.centroid):
            result.append(polygon.centroid)
        # A rectangular text box can fit where the widest inscribed circle is
        # not the best centre. Add a small deterministic local candidate grid.
        radius = centre.distance(polygon.boundary)
        for dx, dy in ((-.35, 0), (.35, 0), (0, -.35), (0, .35)):
            point = Point(centre.x + radius * dx, centre.y + radius * dy)
            if polygon.covers(point):
                result.append(point)
    return result


def _try_number(fig, ax, district, number, panel, occupied):
    """Place one measured number box entirely inside its visible district."""
    import matplotlib.patheffects as pe
    visible = district.geometry.intersection(
        box(ax.get_xlim()[0], ax.get_ylim()[0], ax.get_xlim()[1], ax.get_ylim()[1]))
    if visible.is_empty or visible.area <= 0:
        return None, {"lon": district.geometry.representative_point().x,
                      "lat": district.geometry.representative_point().y}
    matrix = ax.transData.get_affine().get_matrix()
    transform = [matrix[0, 0], matrix[0, 1], matrix[1, 0], matrix[1, 1], matrix[0, 2], matrix[1, 2]]
    pixel_geometry = affine_transform(visible, transform)
    candidates = _candidates(pixel_geometry)
    inverse = ax.transData.inverted()
    focus = inverse.transform((candidates[0].x, candidates[0].y)) if candidates else inverse.transform((pixel_geometry.centroid.x, pixel_geometry.centroid.y))
    artist = ax.text(focus[0], focus[1], str(number), ha="center", va="center",
                     fontsize=9.5, fontweight="bold", color="#142533", zorder=5,
                     path_effects=[pe.withStroke(linewidth=.8, foreground="white")])
    renderer = fig.canvas.get_renderer()
    for size in (9.5, 8.5, 7.5, 6.5, 6.0):
        artist.set_fontsize(size)
        for point in candidates:
            longitude, latitude = inverse.transform((point.x, point.y))
            artist.set_position((longitude, latitude))
            b = artist.get_window_extent(renderer).padded(1.0)
            number_box = box(b.x0, b.y0, b.x1, b.y1)
            if pixel_geometry.covers(number_box) and not any(number_box.intersects(previous) for previous in occupied):
                occupied.append(number_box)
                lo = inverse.transform((b.x0, b.y0)); hi = inverse.transform((b.x1, b.y1))
                result = {"panel": panel, "number_lon": float(longitude), "number_lat": float(latitude),
                          "font_size_pt": size, "number_inside": True,
                          "bbox_min_lon": float(lo[0]), "bbox_min_lat": float(lo[1]),
                          "bbox_max_lon": float(hi[0]), "bbox_max_lat": float(hi[1]),
                          "bbox_overlap_count": 0}
                return result, {"lon": float(longitude), "lat": float(latitude)}
    artist.remove()
    return None, {"lon": float(focus[0]), "lat": float(focus[1])}


def _group_failures(failures, main_ax):
    """Nearby unresolved number locations share a detail panel."""
    ids = sorted(failures)
    positions = {i: main_ax.transData.transform((failures[i]["lon"], failures[i]["lat"])) for i in ids}
    groups = []
    unseen = set(ids)
    for first in ids:
        if first not in unseen:
            continue
        members, pending = [], [first]; unseen.remove(first)
        while pending:
            current = pending.pop(); members.append(current)
            near = [i for i in sorted(unseen) if math.dist(positions[current], positions[i]) <= 100]
            unseen.difference_update(near); pending.extend(near)
        groups.append(sorted(members))
    return groups


def _focus_extent(ids, failures, global_bounds, factor=1.0):
    xs = [failures[i]["lon"] for i in ids]; ys = [failures[i]["lat"] for i in ids]
    dx, dy = global_bounds[2] - global_bounds[0], global_bounds[3] - global_bounds[1]
    width = max(max(xs) - min(xs), dx * .014 * factor)
    height = max(max(ys) - min(ys), dy * .014 * factor)
    # A focus panel may show partial district geometry. Its labelled number is
    # still tested against the complete district, not a simplified substitute.
    px, py = width * .30, height * .30
    return [min(xs) - px, min(ys) - py, max(xs) + px, max(ys) + py]


def _key_layout(layout, width, columns, font=10.5):
    per_column = math.ceil(len(layout) / columns)
    ordered = layout.sort_values("label_number")
    usable = (width - 1.4) / columns
    wrap_width = max(20, int(usable * 72 / (font * .56)))
    groups = []
    for start in range(0, len(ordered), per_column):
        group = []
        for row in ordered.iloc[start:start + per_column].itertuples(index=False):
            label = textwrap.fill(f"{row.label_number:>3d}  {row.dist_name}", width=wrap_width,
                                  subsequent_indent="     ", break_long_words=True, break_on_hyphens=False)
            group.append((label, max(1, len(label.splitlines())) * font * 1.2 / 72 + .045))
        groups.append(group)
    key_height = max(sum(height for _, height in group) for group in groups) + .40
    return groups, key_height


def _draw_panel(ax, districts, color, extent=None, selected_ids=None):
    import matplotlib.colors as mcolors
    rgba = mcolors.to_rgba(color)
    light = tuple(.86 + .14 * x for x in rgba[:3])
    districts.plot(ax=ax, facecolor=light, edgecolor="#435869", linewidth=.55, zorder=1)
    if extent:
        ax.set_xlim(extent[0], extent[2]); ax.set_ylim(extent[1], extent[3])
    ax.set_xlabel("Longitude (degrees)", fontsize=9); ax.set_ylabel("Latitude (degrees)", fontsize=9)
    ax.tick_params(labelsize=8); ax.grid(alpha=.16, zorder=0)


def _empty_inset_rectangle(ax, districts, width_inches=5.6, height_inches=3.2):
    """Find a corner whose complete inset footprint avoids all district areas."""
    matrix = ax.transData.get_affine().get_matrix()
    transform = [matrix[0, 0], matrix[0, 1], matrix[1, 0], matrix[1, 1], matrix[0, 2], matrix[1, 2]]
    geometry = affine_transform(union_all(districts.geometry.values), transform)
    dpi = ax.figure.dpi
    # Footprint includes tick labels, axis labels and the detail-panel title.
    outer_width = (width_inches + .8) * dpi
    outer_height = (height_inches + .85) * dpi
    bounds = ax.bbox
    positions = [(bounds.x0 + .12*dpi, bounds.y1 - outer_height - .12*dpi),
                 (bounds.x1 - outer_width - .12*dpi, bounds.y1 - outer_height - .12*dpi),
                 (bounds.x0 + .12*dpi, bounds.y0 + .12*dpi),
                 (bounds.x1 - outer_width - .12*dpi, bounds.y0 + .12*dpi)]
    for x, y in positions:
        footprint = box(x, y, x + outer_width, y + outer_height)
        if x >= bounds.x0 and y >= bounds.y0 and x + outer_width <= bounds.x1 and y + outer_height <= bounds.y1 and not geometry.intersects(footprint):
            return (x + .55*dpi, y + .37*dpi, width_inches*dpi, height_inches*dpi), geometry
    return None, geometry


def _compose_numbered(districts, zone, layout, panels, color, allow_embed=True):
    """Compose a main map, optional numbered detail row(s), and a name key."""
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    display = districts.to_crs(4326).sort_values("dist_id").reset_index(drop=True)
    display["dist_id"] = display.dist_id.astype(str)
    bounds = display.total_bounds
    latitude = (bounds[1] + bounds[3]) / 2
    aspect = (bounds[2] - bounds[0]) * math.cos(math.radians(latitude)) / max(1e-12, bounds[3] - bounds[1])
    title = str(zone.iloc[0].zone_name)
    force_four = str(zone.iloc[0].zone_id) in {"forest_zone", "coastal_zone"}
    width = 22. if aspect >= 1.25 or force_four else 16.
    columns = 4 if force_four or len(display) >= 28 else (3 if len(display) >= 15 else 2)
    key_groups, key_height = _key_layout(layout, width, columns)
    map_height = min(13., max(4.2, (width - 1.6) / max(aspect, .3)))
    detail_panels = panels[1:]
    detail_rows = math.ceil(len(detail_panels) / 2)
    embedding_requested = allow_embed and len(detail_panels) == 1
    row_height = 5.2
    details_height = 0. if embedding_requested else detail_rows * row_height
    height = 1.35 + map_height + details_height + key_height + .95
    fig = plt.figure(figsize=(width, height))
    fig.text(.5, 1 - .23 / height, title, ha="center", va="top", fontsize=19, fontweight="bold")
    fig.text(.5, 1 - .66 / height, "Numbered districts and district-name key", ha="center", va="top", fontsize=12)
    fig.text(.5, 1 - 1.00 / height, f"{len(display)} whole districts | WGS 84 (EPSG:4326) | Numbers are local to this zone",
             ha="center", va="top", fontsize=9, color="#435869")
    map_top = height - 1.35
    main = fig.add_axes((.8 / width, (map_top - map_height) / height, (width - 1.6) / width, map_height / height))
    _draw_panel(main, display, color)
    axes = {"main": main}
    fig.canvas.draw()
    inset_rectangle, pixel_source = (None, None)
    if embedding_requested:
        sizes = ((9.5, 4.25), (9.5, 3.8), (8.5, 3.5), (7.5, 3.5), (6.5, 3.3), (5.6, 3.2), (4.8, 2.7), (4.2, 2.5), (3.6, 2.4)) if aspect >= 2.0 else ((5.6, 3.2), (5.0, 3.0), (4.2, 2.5), (3.6, 2.4))
        for inset_width, inset_height in sizes:
            inset_rectangle, pixel_source = _empty_inset_rectangle(main, display, inset_width, inset_height)
            if inset_rectangle is not None:
                break
    if embedding_requested and inset_rectangle is None:
        plt.close(fig)
        return _compose_numbered(districts, zone, layout, panels, color, allow_embed=False)
    for i, panel in enumerate(detail_panels):
        row, column = divmod(i, 2)
        if inset_rectangle is not None:
            x, y, w, h = inset_rectangle
            ax = fig.add_axes((x / fig.bbox.width, y / fig.bbox.height, w / fig.bbox.width, h / fig.bbox.height))
        else:
            panel_width = (width - 2.3) / 2
            top = map_top - map_height - .80 - row * row_height
            if len(detail_panels) == 1:
                panel_width = min(10., width - 2.)
                left = (width - panel_width) / 2
            else:
                left = .8 + column * (panel_width + .7)
            ax = fig.add_axes((left / width, (top - 4.25) / height, panel_width / width, 4.25 / height))
        _draw_panel(ax, display, color, extent=panel["extent"])
        ax.set_title(f"Detail {i + 1}: enlarged district numbers", fontsize=10, pad=8)
        axes[panel["id"]] = ax
        x0, y0, x1, y1 = panel["extent"]
        main.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, edgecolor="#9b4a1b",
                                 linestyle="--", linewidth=.8, zorder=3))
        main.annotate(f"Detail {i + 1}", (x1, y1), xytext=(2, 4), textcoords="offset points",
                      fontsize=7.5, color="#8a3c14", ha="left", va="bottom")
    fig.canvas.draw()
    # Check the rendered inset's complete text/axes extent, not just its inner
    # map rectangle. A failed corner check switches to a compact external row.
    if inset_rectangle is not None:
        detail_ax = axes[detail_panels[0]["id"]]
        extent = detail_ax.get_tightbbox(fig.canvas.get_renderer()).padded(3)
        if pixel_source.intersects(box(extent.x0, extent.y0, extent.x1, extent.y1)):
            plt.close(fig)
            return _compose_numbered(districts, zone, layout, panels, color, allow_embed=False)
    key_top = map_top - map_height - details_height - .47
    fig.text(.8 / width, key_top / height, "District key", fontsize=11, fontweight="bold", va="top")
    key_artists = []
    for column, group in enumerate(key_groups):
        y = key_top - .33
        x = (.8 + column * (width - 1.4) / columns) / width
        for text, allocated_height in group:
            key_artists.append(fig.text(x, y / height, text, fontsize=10.5, ha="left", va="top", linespacing=1.2, color="#172a38"))
            y -= allocated_height
    fig.text(.5, .23 / height,
             "Whole districts assigned by maximum overlap with the reference zones. Detail panels enlarge crowded areas; boundaries are unchanged.",
             fontsize=8.2, color="#435869", ha="center", va="bottom")
    fig.canvas.draw()
    number_by_id = layout.set_index("dist_id").label_number.to_dict()
    district_by_id = display.set_index("dist_id", drop=False)
    placements, failures = {}, {}
    for panel in panels:
        ax = axes[panel["id"]]
        occupied = []
        for identifier in sorted(panel["ids"], key=lambda d: number_by_id[d]):
            placed, focus = _try_number(fig, ax, district_by_id.loc[identifier], int(number_by_id[identifier]), panel["id"], occupied)
            if placed is None:
                failures[identifier] = {**focus, "panel": panel["id"]}
            else:
                placements[identifier] = placed
    # A compact embedded view is optional: do not split a coherent city detail
    # into excessive panels merely because the inset is too small for its text.
    if inset_rectangle is not None and any(item["panel"] != "main" for item in failures.values()):
        plt.close(fig)
        return _compose_numbered(districts, zone, layout, panels, color, allow_embed=False)
    return fig, placements, failures, main, key_artists, columns, inset_rectangle is not None


def _labelled_zone(districts, zone, root, color):
    import matplotlib.pyplot as plt
    layout = label_layout(districts)
    display = districts.to_crs(4326)
    panels = [{"id": "main", "ids": sorted(layout.dist_id)}]
    fig = None
    for attempt in range(7):
        for number, panel in enumerate(panels[1:], start=1):
            panel["id"] = "detail_" + str(number)
        if fig is not None:
            plt.close(fig)
        fig, placements, failures, main, key_artists, columns, inset_in_main = _compose_numbered(districts, zone, layout, panels, color)
        if not failures:
            break
        groups = _group_failures(failures, main) if attempt == 0 else [[i] for i in sorted(failures)]
        for panel in panels:
            panel["ids"] = [i for i in panel["ids"] if i not in failures]
        panels = [panel for panel in panels if panel["id"] == "main" or panel["ids"]]
        for group in groups:
            identifier = "detail_" + str(max([int(p["id"].split("_")[-1]) for p in panels[1:]] or [0]) + 1)
            panels.append({"id": identifier, "ids": group,
                           "extent": _focus_extent(group, failures, display.total_bounds, factor=.25 ** attempt)})
    if failures:
        plt.close(fig)
        raise ValueError("Cannot fit readable district numbers inside polygons: " + ", ".join(sorted(failures)))
    diagnostics = _check_label_boxes(fig, key_artists)
    measured = pd.DataFrame([{"dist_id": identifier, **placement} for identifier, placement in placements.items()])
    result = layout.merge(measured, on="dist_id", validate="one_to_one").sort_values("dist_id")
    if len(result) != len(districts) or not result.number_inside.all() or result.font_size_pt.min() < 6:
        plt.close(fig); raise ValueError("Incomplete or unreadable district numbering")
    root.mkdir(parents=True, exist_ok=True)
    identifier = str(zone.iloc[0].zone_id)
    target = root / identifier
    fig.savefig(target.with_suffix(".png"), dpi=150)
    fig.savefig(target.with_suffix(".pdf"), metadata={"Title": f"{zone.iloc[0].zone_name}: numbered districts", "Author": "geo_data_prep"})
    result.to_csv(target.with_name(target.name + "_labels.csv"), index=False, float_format="%.17g")
    figure_size = tuple(fig.get_size_inches())
    plt.close(fig)
    return {"zone_id": identifier, "district_count": len(districts), **diagnostics,
            "number_inside_count": int(result.number_inside.sum()), "number_bbox_overlap_count": 0,
            "minimum_number_font_size_pt": float(result.font_size_pt.min()),
            "detail_panel_count": len(panels) - 1, "inset_in_main": inset_in_main, "inset_source_overlap_count": 0, "key_columns": columns,
            "anchor_crs": "EPSG:4326", "figure_width_inches": float(figure_size[0]), "figure_height_inches": float(figure_size[1])}


def render_plots(districts, zones, root):
    """Write a zone overview and numbered district PNG/PDF maps with name keys."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import json
    root = Path(root); root.mkdir(parents=True, exist_ok=True)
    ordered_zones = zones.sort_values("zone_id")
    cmap = plt.get_cmap("tab10")
    colors = {row.zone_id: cmap(i % 10) for i, (_, row) in enumerate(ordered_zones.iterrows())}
    _overview(districts, ordered_zones, root, colors)
    diagnostics = []
    for _, row in ordered_zones.iterrows():
        members = districts[districts.zone_id == row.zone_id]
        if members.empty:
            raise ValueError(f"Cannot plot zone without districts: {row.zone_id}")
        diagnostics.append(_labelled_zone(members, ordered_zones[ordered_zones.zone_id == row.zone_id], root / "per_zone", colors[row.zone_id]))
    (root / "district_label_checks.json").write_text(json.dumps({"zones": diagnostics,
        "label_placement": "Numbers inside district polygons; separate numbered district-name key",
        "anchor_method": "Interior candidate search with measured text-box containment; detail panels for small districts"}, indent=2) + "\n", encoding="utf-8")
