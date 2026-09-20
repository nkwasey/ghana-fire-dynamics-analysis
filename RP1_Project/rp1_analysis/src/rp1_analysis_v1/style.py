"""Governed publication styling for RP1 Analysis v1.

Visual constants are centralised here and realised from ``figure_contract.yml``.
Plotting modules consume :class:`PublicationStyle`; notebook cells do not carry
independent styling decisions.  Renderers consume this authority directly for governed map and multi-panel layout.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from types import MappingProxyType
from typing import Any, Mapping

from .config import FigureContract
from .contracts import GridLayoutContract
from .presentation import LayoutRole


def _dimension_pair(value: Any, context: str) -> tuple[float, float]:
    """Validate and realise one governed width/height pair."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{context} must contain exactly width and height")
    try:
        width = float(value[0])
        height = float(value[1])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{context} width and height must be numeric") from exc
    return width, height


def cm_to_inches(value_cm: float) -> float:
    """Convert governed centimetres to inches using the exact 2.54 cm/in relation."""
    return float(Decimal(str(value_cm)) / Decimal("2.54"))


def round_pixels_half_up(inches: float, dpi: int) -> int:
    """Deterministically round a physical raster dimension to whole pixels."""
    value = Decimal(str(inches)) * Decimal(int(dpi))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass(frozen=True, slots=True)
class NorthArrowStyle:
    enabled: bool
    position: str


@dataclass(frozen=True, slots=True)
class ScaleBarStyle:
    enabled: bool
    length_km: float
    unit: str
    label: str
    position: str
    horizontal_margin_fraction: float
    vertical_margin_fraction: float


@dataclass(frozen=True, slots=True)
class ColorbarStyle:
    position: str
    orientation: str
    label_required: bool


@dataclass(frozen=True, slots=True)
class MapPresentationStyle:
    shared_extent_for_comparable_maps: bool
    distinguish_excluded_from_valid_zero: bool
    north_arrow: NorthArrowStyle
    scale_bar: ScaleBarStyle
    colorbar: ColorbarStyle
    legend_position: str
    embedded_notes: bool


@dataclass(frozen=True, slots=True)
class PanelPresentationStyle:
    orientation: str
    panel_titles: bool
    panel_descriptions: bool
    label_convention: str
    sequence_start: str
    label_weight: str


@dataclass(frozen=True, slots=True)
class PublicationGeometryStyle:
    canvas_width_cm: float
    canvas_height_cm: float
    orientation: str
    outer_left_fraction: float
    outer_right_fraction: float
    outer_top_fraction: float
    outer_bottom_fraction: float
    inter_column: float
    inter_row: float
    xlabel_padding_pt: float
    ylabel_padding_pt: float
    panel_label_offset_x: float
    panel_label_offset_y: float
    map_height_ratio: float
    map_legend_band_height: float
    map_colourbar_band_height: float
    map_inter_band_spacing: float
    heatmap_colorbar_band_fraction: float
    heatmap_colorbar_gap_fraction: float
    effect_vertical_padding_rows: float


@dataclass(frozen=True, slots=True)
class SemanticStateStyle:
    face: str
    edge: str
    hatch: str


@dataclass(frozen=True, slots=True)
class SemanticStyles:
    valid_zero: SemanticStateStyle
    not_significant: SemanticStateStyle
    excluded: SemanticStateStyle
    local_moran: Mapping[str, SemanticStateStyle]


@dataclass(frozen=True, slots=True)
class CircularMeanMonthDisplayStyle:
    axis_label: str
    legend_title: str
    axis_min: float
    axis_max: float
    ticks: tuple[float, ...]
    tick_labels: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PublicationStyle:
    dpi: int
    title_inside_figure: bool
    raster_formats: tuple[str, ...]
    vector_formats: tuple[str, ...]
    layout_dimensions: Mapping[str, tuple[float, float]]
    physical_size_roles_cm: Mapping[str, tuple[float, float]]
    grid_layouts: Mapping[str, GridLayoutContract]
    pixel_rounding_method: str
    single_panel: tuple[float, float]
    wide_single_panel: tuple[float, float]
    full_width_map: tuple[float, float]
    base_font: float
    axis_label_font: float
    tick_font: float
    legend_font: float
    panel_label_font: float
    map: MapPresentationStyle
    panels: PanelPresentationStyle
    geometry: PublicationGeometryStyle
    semantic: SemanticStyles
    circular_mean_month_display: CircularMeanMonthDisplayStyle
    boundary_colour: str = "0.35"
    acz_boundary_colour: str = "0.08"
    line_width: float = 1.1
    boundary_width: float = 0.35
    acz_boundary_width: float = 0.9
    grid_alpha: float = 0.25

    @classmethod
    def from_contract(cls, contract: FigureContract) -> PublicationStyle:
        dims = contract.dimensions_inches
        fonts = contract.font_sizes_pt
        map_layout = contract.map_layout
        north = map_layout["north_arrow"]
        scale = map_layout["scale_bar"]
        colorbar = map_layout["colorbar"]
        legend = map_layout["legend"]
        panels = contract.panel_layout
        labels = contract.panel_labels
        realised_dimensions = {
            str(name): _dimension_pair(value, f"figure.dimensions_inches.{name}")
            for name, value in dims.items()
        }
        physical_size_roles_cm = {
            str(name): (float(value["width_cm"]), float(value["height_cm"]))
            for name, value in contract.physical_size_roles.items()
        }
        governed_geometry = contract.publication_geometry
        semantic = contract.semantic_styles
        circular_display = contract.display_conventions.circular_mean_month
        return cls(
            dpi=int(contract.resolution_dpi),
            title_inside_figure=bool(contract.text_policy["title_inside_figure"]),
            raster_formats=tuple(str(x) for x in contract.formats["raster"]),
            vector_formats=tuple(str(x) for x in contract.formats["vector"]),
            layout_dimensions=realised_dimensions,
            physical_size_roles_cm=physical_size_roles_cm,
            grid_layouts=contract.grid_layouts,
            pixel_rounding_method=str(contract.pixel_rounding["method"]),
            single_panel=_dimension_pair(
                dims["single_panel"], "figure.dimensions_inches.single_panel"
            ),
            wide_single_panel=_dimension_pair(
                dims["wide_single_panel"], "figure.dimensions_inches.wide_single_panel"
            ),
            full_width_map=_dimension_pair(
                dims["full_width_map"], "figure.dimensions_inches.full_width_map"
            ),
            base_font=float(fonts["base"]),
            axis_label_font=float(fonts["axis_label"]),
            tick_font=float(fonts["tick_label"]),
            legend_font=float(fonts["legend"]),
            panel_label_font=float(fonts["panel_label"]),
            map=MapPresentationStyle(
                shared_extent_for_comparable_maps=bool(
                    map_layout["shared_extent_for_comparable_maps"]
                ),
                distinguish_excluded_from_valid_zero=bool(
                    map_layout["distinguish_excluded_from_valid_zero"]
                ),
                north_arrow=NorthArrowStyle(
                    enabled=bool(north["enabled"]), position=str(north["position"])
                ),
                scale_bar=ScaleBarStyle(
                    enabled=bool(scale["enabled"]),
                    length_km=float(scale["length_km"]),
                    unit=str(scale["unit"]),
                    label=str(scale["label"]),
                    position=str(scale["position"]),
                    horizontal_margin_fraction=float(scale["horizontal_margin_fraction"]),
                    vertical_margin_fraction=float(scale["vertical_margin_fraction"]),
                ),
                colorbar=ColorbarStyle(
                    position=str(colorbar["position"]),
                    orientation=str(colorbar["orientation"]),
                    label_required=bool(colorbar["label_required"]),
                ),
                legend_position=str(legend["position"]),
                embedded_notes=bool(contract.text_policy["embedded_notes"]),
            ),
            panels=PanelPresentationStyle(
                orientation=str(panels["orientation"]),
                panel_titles=bool(panels["panel_titles"]),
                panel_descriptions=bool(panels["panel_descriptions"]),
                label_convention=str(labels["convention"]),
                sequence_start=str(labels["sequence_start"]),
                label_weight=str(labels["font_weight"]),
            ),
            geometry=PublicationGeometryStyle(
                canvas_width_cm=governed_geometry.canvas.width_cm,
                canvas_height_cm=governed_geometry.canvas.height_cm,
                orientation=governed_geometry.canvas.orientation,
                outer_left_fraction=governed_geometry.outer_left_fraction,
                outer_right_fraction=governed_geometry.outer_right_fraction,
                outer_top_fraction=governed_geometry.outer_top_fraction,
                outer_bottom_fraction=governed_geometry.outer_bottom_fraction,
                inter_column=governed_geometry.inter_column,
                inter_row=governed_geometry.inter_row,
                xlabel_padding_pt=governed_geometry.xlabel_padding_pt,
                ylabel_padding_pt=governed_geometry.ylabel_padding_pt,
                panel_label_offset_x=governed_geometry.panel_label_offset_x,
                panel_label_offset_y=governed_geometry.panel_label_offset_y,
                map_height_ratio=governed_geometry.map_height_ratio,
                map_legend_band_height=governed_geometry.map_legend_band_height,
                map_colourbar_band_height=governed_geometry.map_colourbar_band_height,
                map_inter_band_spacing=governed_geometry.map_inter_band_spacing,
                heatmap_colorbar_band_fraction=governed_geometry.heatmap_colorbar_band_fraction,
                heatmap_colorbar_gap_fraction=governed_geometry.heatmap_colorbar_gap_fraction,
                effect_vertical_padding_rows=governed_geometry.effect_vertical_padding_rows,
            ),
            semantic=SemanticStyles(
                valid_zero=SemanticStateStyle(
                    face=semantic.valid_zero.face, edge=semantic.valid_zero.edge, hatch=semantic.valid_zero.hatch
                ),
                not_significant=SemanticStateStyle(
                    face=semantic.not_significant.face, edge=semantic.not_significant.edge, hatch=semantic.not_significant.hatch
                ),
                excluded=SemanticStateStyle(
                    face=semantic.excluded.face, edge=semantic.excluded.edge, hatch=semantic.excluded.hatch
                ),
                local_moran=MappingProxyType({
                    key: SemanticStateStyle(face=value.face, edge=value.edge, hatch=value.hatch)
                    for key, value in semantic.local_moran.items()
                }),
            ),
            circular_mean_month_display=CircularMeanMonthDisplayStyle(
                axis_label=circular_display.axis_label,
                legend_title=circular_display.legend_title,
                axis_min=circular_display.axis_min,
                axis_max=circular_display.axis_max,
                ticks=tuple(circular_display.ticks),
                tick_labels=tuple(circular_display.tick_labels),
            ),
        )

    @property
    def excluded_face(self) -> str:
        return self.semantic.excluded.face

    @property
    def excluded_edge(self) -> str:
        return self.semantic.excluded.edge

    @property
    def excluded_hatch(self) -> str:
        return self.semantic.excluded.hatch

    @property
    def zero_face(self) -> str:
        return self.semantic.valid_zero.face

    @property
    def zero_edge(self) -> str:
        return self.semantic.valid_zero.edge

    @property
    def panel_label_weight(self) -> str:
        """Return the governed panel-label font weight."""
        return self.panels.label_weight

    def dimensions_for(self, role: LayoutRole) -> tuple[float, float]:
        """Return dimensions for a grid layout via its single configured size role."""
        layout = self.grid_for(role)
        size_role = layout.size_role
        if size_role in self.layout_dimensions:
            return self.layout_dimensions[size_role]
        if size_role in self.physical_size_roles_cm:
            return self.physical_inches_for(size_role)
        raise ValueError(f"Unknown configured figure size role: {size_role!r}")

    def grid_for(self, role: LayoutRole) -> GridLayoutContract:
        """Return the governed GridSpec layout for a presentation role."""
        try:
            return self.grid_layouts[str(role)]
        except KeyError as exc:
            raise ValueError(f"Unknown configured grid layout role: {role!r}") from exc

    def physical_inches_for(self, role: str) -> tuple[float, float]:
        """Return exact physical size in inches for one centimetre-defined role."""
        try:
            width_cm, height_cm = self.physical_size_roles_cm[role]
        except KeyError as exc:
            raise ValueError(f"Unknown physical figure-size role: {role!r}") from exc
        return cm_to_inches(width_cm), cm_to_inches(height_cm)

    def raster_pixels_for_inches(self, size: tuple[float, float]) -> tuple[int, int]:
        """Return governed raster dimensions using the configured deterministic policy."""
        if self.pixel_rounding_method != "half_up":
            raise ValueError(f"Unsupported pixel rounding policy: {self.pixel_rounding_method!r}")
        return (round_pixels_half_up(size[0], self.dpi), round_pixels_half_up(size[1], self.dpi))

    def raster_pixels_for_physical_role(self, role: str) -> tuple[int, int]:
        return self.raster_pixels_for_inches(self.physical_inches_for(role))

    def rc_params(self) -> dict[str, Any]:
        """Matplotlib rc parameters used by all governed renderers."""
        return {
            "font.size": self.base_font,
            "axes.labelsize": self.axis_label_font,
            "xtick.labelsize": self.tick_font,
            "ytick.labelsize": self.tick_font,
            "legend.fontsize": self.legend_font,
            "axes.linewidth": 0.7,
            "savefig.dpi": self.dpi,
            "figure.dpi": self.dpi,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }


def panel_label(index: int) -> str:
    if index < 0 or index >= 26:
        raise ValueError("Panel-label index must be in [0, 25]")
    return f"({chr(ord('a') + index)})"
