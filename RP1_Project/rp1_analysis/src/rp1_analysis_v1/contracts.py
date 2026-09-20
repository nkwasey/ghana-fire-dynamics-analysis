"""Immutable typed configuration contracts for RP1 Analysis.

The models in this module are deliberately passive.  They carry validated,
immutable study configuration but do not implement scientific algorithms.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, cast

FrozenValue = Any


def freeze(value: Any) -> FrozenValue:
    """Deep-freeze YAML/JSON-compatible values."""

    if isinstance(value, Mapping):
        return MappingProxyType({str(k): freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(freeze(v) for v in value)
    if isinstance(value, tuple):
        return tuple(freeze(v) for v in value)
    if isinstance(value, set):
        return frozenset(freeze(v) for v in value)
    return value


def thaw(value: Any) -> Any:
    """Return a mutable JSON/YAML-compatible representation."""

    if isinstance(value, Mapping):
        return {str(k): thaw(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [thaw(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((thaw(v) for v in value), key=repr)
    return value


@dataclass(frozen=True, slots=True)
class ContractFileHash:
    filename: str
    sha256: str


@dataclass(frozen=True, slots=True)
class DataFieldSpec:
    name: str
    dtype: str
    semantic_type: str
    unit: str
    nullable: bool
    structural_support: str
    required_when_supported: bool
    source_family: str
    additive: bool
    minimum: float | int | None = None
    maximum: float | int | None = None
    categorical_domain: str | None = None
    relationship_role: str | None = None


@dataclass(frozen=True, slots=True)
class PanelSpecification:
    panel_id: str
    path: str
    level_value: str
    primary_key: tuple[str, ...]
    expected_rows: int
    expected_units: int
    column_count: int
    temporal_frequency: str
    start: str
    end: str
    metadata: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class GeometrySpecification:
    geometry_id: str
    path: str
    expected_features: int
    crs_epsg: int
    geometry_types: tuple[str, ...]
    identifier_field: str
    required_columns: tuple[str, ...]
    required_members: tuple[str, ...]
    parent_field: str | None = None
    unit_identities: Mapping[str, Any] | None = None
    panel_identity_map: Mapping[str, str] | None = None


@dataclass(frozen=True, slots=True)
class RelationshipSpecification:
    relationship_id: str
    from_object: str
    from_field: str
    to_object: str
    to_field: str
    cardinality: str


@dataclass(frozen=True, slots=True)
class DataSchemaContract:
    schema_version: str
    data_schema_version: str
    panel_schema_version: str
    field_count: int
    panels: Mapping[str, PanelSpecification]
    auxiliary_inputs: Mapping[str, Mapping[str, Any]]
    source_supports: Mapping[str, Mapping[str, Any]]
    fields: tuple[DataFieldSpec, ...]
    categorical_domains: Mapping[str, tuple[Any, ...]]
    geometries: Mapping[str, GeometrySpecification]
    relationships: tuple[RelationshipSpecification, ...]
    additive_reconciliation: Mapping[str, Any]
    provenance: Mapping[str, Any]
    validation_rules: Mapping[str, Any]

    @property
    def field_names(self) -> frozenset[str]:
        return frozenset(field.name for field in self.fields)

    @property
    def field_order(self) -> tuple[str, ...]:
        return tuple(field.name for field in self.fields)

    def field(self, name: str) -> DataFieldSpec:
        for field in self.fields:
            if field.name == name:
                return field
        raise KeyError(name)

    def panel(self, panel_id: str) -> PanelSpecification:
        try:
            return self.panels[panel_id]
        except KeyError as exc:
            raise KeyError(panel_id) from exc

    def geometry(self, geometry_id: str) -> GeometrySpecification:
        try:
            return self.geometries[geometry_id]
        except KeyError as exc:
            raise KeyError(geometry_id) from exc

    @property
    def additive_fields(self) -> tuple[str, ...]:
        raw = self.additive_reconciliation["district_to_acz"]["fields"]
        return tuple(str(x) for x in raw)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "data_schema_version": self.data_schema_version,
            "panel_schema_version": self.panel_schema_version,
            "field_count": self.field_count,
            "panels": {
                key: {
                    "path": value.path,
                    "level_value": value.level_value,
                    "primary_key": list(value.primary_key),
                    "expected_rows": value.expected_rows,
                    "expected_units": value.expected_units,
                    "column_count": value.column_count,
                    "temporal_frequency": value.temporal_frequency,
                    "start": value.start,
                    "end": value.end,
                    **thaw(value.metadata),
                }
                for key, value in self.panels.items()
            },
            "auxiliary_inputs": thaw(self.auxiliary_inputs),
            "source_supports": thaw(self.source_supports),
            "categorical_domains": thaw(self.categorical_domains),
            "fields": [
                {
                    "name": f.name, "dtype": f.dtype, "semantic_type": f.semantic_type,
                    "unit": f.unit, "nullable": f.nullable,
                    "structural_support": f.structural_support,
                    "required_when_supported": f.required_when_supported,
                    "source_family": f.source_family, "additive": f.additive,
                    **({"minimum": f.minimum} if f.minimum is not None else {}),
                    **({"maximum": f.maximum} if f.maximum is not None else {}),
                    **({"categorical_domain": f.categorical_domain} if f.categorical_domain is not None else {}),
                    **({"relationship_role": f.relationship_role} if f.relationship_role is not None else {}),
                } for f in self.fields
            ],
            "geometries": {
                key: {
                    "path": value.path, "expected_features": value.expected_features,
                    "crs_epsg": value.crs_epsg, "geometry_types": list(value.geometry_types),
                    "identifier_field": value.identifier_field,
                    "required_columns": list(value.required_columns),
                    "required_members": list(value.required_members),
                    **({"parent_field": value.parent_field} if value.parent_field is not None else {}),
                    **({"unit_identities": thaw(value.unit_identities)} if value.unit_identities is not None else {}),
                    **({"panel_identity_map": thaw(value.panel_identity_map)} if value.panel_identity_map is not None else {}),
                } for key, value in self.geometries.items()
            },
            "relationships": [
                {"relationship_id": r.relationship_id, "from_object": r.from_object,
                 "from_field": r.from_field, "to_object": r.to_object,
                 "to_field": r.to_field, "cardinality": r.cardinality}
                for r in self.relationships
            ],
            "additive_reconciliation": thaw(self.additive_reconciliation),
            "provenance": thaw(self.provenance),
            "validation_rules": thaw(self.validation_rules),
        }


@dataclass(frozen=True, slots=True)
class RQ1SpatialParameters:
    global_permutations: int
    local_permutations: int
    random_seed: int
    local_p_value_method: str
    local_permutation_scheme: str
    local_upper_tail_comparison: str
    local_tie_allocation: str
    local_multiply_smaller_tail_by_two: bool
    multiplicity_method: str
    alpha: float
    weight_method: str
    weight_order: str
    weight_transform: str
    island_policy: str


@dataclass(frozen=True, slots=True)
class RQ2TrendParameters:
    effect_estimator: str
    inferential_test: str
    empirical_cdf: str
    rank_tie_contribution: str
    requires_distinct_observations: bool
    on_ties: str
    bandwidth_rule: str
    variance_floor: float
    studentisation: str
    permutations: int
    random_seed: int
    alternative: str
    p_value_method: str
    multiple_testing_method: str
    family_size: int
    alpha: float


@dataclass(frozen=True, slots=True)
class RQ3ModelParameters:
    estimator: str
    family: str
    link: str
    cluster_unit: str
    cluster_field: str
    working_correlation: str
    covariance: str
    reference_distribution: str
    predictors: tuple[Mapping[str, Any], ...]
    factors: tuple[Mapping[str, Any], ...]
    vif_enabled: bool
    predictive_standardisation_method: str
    predictive_quantiles: tuple[float, ...]
    tolerance: float
    max_iterations: int
    max_step_halvings: int


@dataclass(frozen=True, slots=True)
class SaTScanParameters:
    engine: str
    engine_version_authority: str
    analysis_type: str
    cluster_type: str
    max_spatial_percent: float
    max_temporal_months: int
    monte_carlo_replicates: int
    alpha: float
    reporting_method: str
    geographical_overlap: bool
    gini_optimised_reporting: bool
    coordinate_crs: str
    coordinate_anchor_method: str
    spatial_window_shape: str
    report_cluster_rank: bool
    scientific_seed: int
    user_defined_random_seed_supported: bool
    user_defined_random_seed_parameter: str | None
    rng_authority: str
    engine_rng_behaviour: str


@dataclass(frozen=True, slots=True)
class RealisedRunMetadata:
    schema_version: str
    config_sha256: str
    methods_spec_sha256: str
    data_sha256: str
    realised_sample_sizes: Mapping[str, int]
    rq2_realised_bandwidth: int | None
    realised_permutation_counts: Mapping[str, int]
    rq3_design_columns: tuple[str, ...]
    factor_references: Mapping[str, Any]
    rq3_transformations: Mapping[str, str]
    rq3_reporting_roles: Mapping[str, str]
    spatial_weight_parameters: Mapping[str, Any]
    satscan_parameter_hashes: Mapping[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "config_sha256": self.config_sha256,
            "methods_spec_sha256": self.methods_spec_sha256,
            "data_sha256": self.data_sha256,
            "realised_sample_sizes": thaw(self.realised_sample_sizes),
            "rq2_realised_bandwidth": self.rq2_realised_bandwidth,
            "realised_permutation_counts": thaw(self.realised_permutation_counts),
            "rq3_design_columns": list(self.rq3_design_columns),
            "factor_references": thaw(self.factor_references),
            "rq3_transformations": thaw(self.rq3_transformations),
            "rq3_reporting_roles": thaw(self.rq3_reporting_roles),
            "spatial_weight_parameters": thaw(self.spatial_weight_parameters),
            "satscan_parameter_hashes": thaw(self.satscan_parameter_hashes),
        }


@dataclass(frozen=True, slots=True)
class MethodAuthoritySpec:
    method_id: str
    implementation_id: str
    family: str
    status: str
    qualification_status: str
    authority_scope: str
    protocol_reference: str
    authoritative_reference: str
    doi: str | None
    governed_variant: str
    parameter_provenance: Mapping[str, str]
    outcome_tuning_allowed: bool


@dataclass(frozen=True, slots=True)
class OutputSpecification:
    output_id: str
    rq: str
    title: str
    role: str
    family_id: str
    evidence_class: str
    builder: str
    source_attribute: str | None = None
    required_columns: tuple[str, ...] = ()
    requires_results_validated: bool = False
    builder_options: Mapping[str, Any] = MappingProxyType({})




@dataclass(frozen=True, slots=True)
class SecondaryOutputSpecification:
    output_id: str
    output_type: str
    role: str
    builder: str
    source_attribute: str
    requires_results_validated: bool



@dataclass(frozen=True, slots=True)
class GridCellContract:
    kind: str
    row: int
    column: int
    row_span: int
    column_span: int
    panel_index: int | None = None
    auxiliary_id: str | None = None


@dataclass(frozen=True, slots=True)
class GridLayoutContract:
    layout_id: str
    size_role: str
    rows: int
    columns: int
    width_ratios: tuple[float, ...]
    height_ratios: tuple[float, ...]
    cells: tuple[GridCellContract, ...]

    @property
    def data_cells(self) -> tuple[GridCellContract, ...]:
        return tuple(sorted((cell for cell in self.cells if cell.kind == "data"), key=lambda c: int(c.panel_index if c.panel_index is not None else -1)))

    @property
    def auxiliary_cells(self) -> tuple[GridCellContract, ...]:
        return tuple(cell for cell in self.cells if cell.kind == "auxiliary")


@dataclass(frozen=True, slots=True)
class FigureSpecificationContract:
    figure_id: str
    rq: str
    title: str
    role: str
    evidence_class: str
    layout_role: str
    renderer: str
    data_builder: str
    source_attribute: str
    requires_results_validated: bool = False
    data_builder_options: Mapping[str, Any] = MappingProxyType({})
    renderer_options: Mapping[str, Any] = MappingProxyType({})
    xlabel: str | None = None
    ylabel: str | None = None
    colorbar_label: str | None = None
    panel_count: int = 1
    panel_xlabels: tuple[str | None, ...] = ()
    panel_ylabels: tuple[str | None, ...] = ()
    required_columns: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AnalysisContract:
    schema_version: str
    project: Mapping[str, Any]
    reproducibility: Mapping[str, Any]
    study: Mapping[str, Any]
    field_roles: Mapping[str, Any]
    product_semantics: Mapping[str, Any]
    research_questions: Mapping[str, Any]
    secondary_analysis: Mapping[str, Any]

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema_version": self.schema_version,
                "project": self.project,
                "reproducibility": self.reproducibility,
                "study": self.study,
                "field_roles": self.field_roles,
                "product_semantics": self.product_semantics,
                "research_questions": self.research_questions,
                "secondary_analysis": self.secondary_analysis,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], thaw(self.as_mapping()))


@dataclass(frozen=True, slots=True)
class MethodAuthorityContract:
    schema_version: str
    authorities: tuple[MethodAuthoritySpec, ...]

    @property
    def method_ids(self) -> frozenset[str]:
        return frozenset(item.method_id for item in self.authorities)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "authorities": [
                {
                    "method_id": item.method_id,
                    "implementation_id": item.implementation_id,
                    "family": item.family,
                    "status": item.status,
                    "qualification_status": item.qualification_status,
                    "authority_scope": item.authority_scope,
                    "protocol_reference": item.protocol_reference,
                    "authoritative_reference": item.authoritative_reference,
                    "doi": item.doi,
                    "governed_variant": item.governed_variant,
                    "parameter_provenance": thaw(item.parameter_provenance),
                    "outcome_tuning_allowed": item.outcome_tuning_allowed,
                }
                for item in self.authorities
            ],
        }


@dataclass(frozen=True, slots=True)
class OutputContract:
    schema_version: str
    run_root: str
    latest_run_pointer: str
    sections: tuple[str, ...]
    output_families: tuple[str, ...]
    filename_policy: Mapping[str, Any]
    write_policy: Mapping[str, Any]
    hashing: Mapping[str, Any]
    csv_column_orders: Mapping[str, Any]
    tables: tuple[OutputSpecification, ...]
    secondary_outputs: tuple[SecondaryOutputSpecification, ...]
    registries: tuple[str, ...]
    figure_formats: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_root": self.run_root,
            "latest_run_pointer": self.latest_run_pointer,
            "sections": list(self.sections),
            "output_families": list(self.output_families),
            "filename_policy": thaw(self.filename_policy),
            "write_policy": thaw(self.write_policy),
            "hashing": thaw(self.hashing),
            "csv_column_orders": thaw(self.csv_column_orders),
            "publication_outputs": {
                "tables": [
                    {
                        "id": item.output_id,
                        "rq": item.rq,
                        "title": item.title,
                        "role": item.role,
                        "family_id": item.family_id,
                        "evidence_class": item.evidence_class,
                        "builder": item.builder,
                        "source_attribute": item.source_attribute,
                        "required_columns": list(item.required_columns),
                        "requires_results_validated": item.requires_results_validated,
                        "builder_options": thaw(item.builder_options),
                    }
                    for item in self.tables
                ],
                "figure_formats": list(self.figure_formats),
                "registries": list(self.registries),
            },
            "secondary_outputs": [
                {
                    "id": item.output_id,
                    "output_type": item.output_type,
                    "role": item.role,
                    "builder": item.builder,
                    "source_attribute": item.source_attribute,
                    "requires_results_validated": item.requires_results_validated,
                }
                for item in self.secondary_outputs
            ],
        }


@dataclass(frozen=True, slots=True)
class PublicationCanvasContract:
    width_cm: float
    height_cm: float
    orientation: str


@dataclass(frozen=True, slots=True)
class PublicationGeometryContract:
    canvas: PublicationCanvasContract
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
class SemanticStateStyleContract:
    face: str
    edge: str
    hatch: str = ""


@dataclass(frozen=True, slots=True)
class SemanticStylesContract:
    valid_zero: SemanticStateStyleContract
    not_significant: SemanticStateStyleContract
    excluded: SemanticStateStyleContract
    local_moran: Mapping[str, SemanticStateStyleContract]


@dataclass(frozen=True, slots=True)
class CircularMeanMonthDisplayContract:
    axis_label: str
    legend_title: str
    axis_min: float
    axis_max: float
    ticks: tuple[float, ...]
    tick_labels: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DisplayConventionsContract:
    circular_mean_month: CircularMeanMonthDisplayContract


@dataclass(frozen=True, slots=True)
class PresentationSourceContract:
    source_identity: str
    path_pattern: str


@dataclass(frozen=True, slots=True)
class PresentationGeometryDependencyContract:
    dependency_id: str
    geometries: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PresentationOutputPolicyContract:
    formats: tuple[str, ...]
    size_role: str
    raster_dpi: int
    collision_policy: str
    deterministic_names: bool
    source_run_read_only: bool
    staging_policy: str


@dataclass(frozen=True, slots=True)
class PresentationRunFamilyContract:
    required_member_suffix: str
    publication_member_suffix: str
    secondary_member_suffix: str
    require_closeout_validation: bool


@dataclass(frozen=True, slots=True)
class PresentationManifestContract:
    export_manifest: str
    source_inventory: str
    output_inventory: str


@dataclass(frozen=True, slots=True)
class PresentationExportSpecificationContract:
    export_id: str
    group: str
    label: str
    source_identity: str
    source_path_pattern: str
    selector: Mapping[str, Any]
    geometry_dependency: str
    renderer_identity: str
    scenario: str | None
    required_result_state: str
    output_filename: str
    size_role: str
    formats: tuple[str, ...]
    raster_dpi: int
    units: str
    category_order: Mapping[str, Any]
    colour_semantic: str
    legend_policy: Mapping[str, Any]
    annotation_policy: tuple[str, ...]
    interpretation_boundary: str


@dataclass(frozen=True, slots=True)
class PresentationExportRegistryContract:
    schema: str
    groups: tuple[str, ...]
    renderer_identities: tuple[str, ...]
    sources: Mapping[str, PresentationSourceContract]
    geometry_dependencies: Mapping[str, PresentationGeometryDependencyContract]
    output: PresentationOutputPolicyContract
    run_family: PresentationRunFamilyContract
    manifests: PresentationManifestContract
    semantic_styles: Mapping[str, Any]
    exports: tuple[PresentationExportSpecificationContract, ...]

    @property
    def export_ids(self) -> tuple[str, ...]:
        return tuple(item.export_id for item in self.exports)

    def export_by_id(self, export_id: str) -> PresentationExportSpecificationContract:
        for item in self.exports:
            if item.export_id == export_id:
                return item
        raise KeyError(export_id)

    def exports_for_group(self, group: str) -> tuple[PresentationExportSpecificationContract, ...]:
        if group not in self.groups:
            raise KeyError(group)
        return tuple(item for item in self.exports if item.group == group)


@dataclass(frozen=True, slots=True)
class FigureContract:
    schema_version: str
    formats: Mapping[str, Any]
    resolution_dpi: int
    dimensions_inches: Mapping[str, Any]
    physical_size_roles: Mapping[str, Any]
    pixel_rounding: Mapping[str, Any]
    grid_layouts: Mapping[str, GridLayoutContract]
    font_sizes_pt: Mapping[str, Any]
    map_layout: Mapping[str, Any]
    publication_geometry: PublicationGeometryContract
    semantic_styles: SemanticStylesContract
    display_conventions: DisplayConventionsContract
    panel_layout: Mapping[str, Any]
    panel_labels: Mapping[str, Any]
    source_data_policy: Mapping[str, Any]
    text_policy: Mapping[str, Any]
    figures: tuple[FigureSpecificationContract, ...]
    presentation_export: PresentationExportRegistryContract | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "formats": thaw(self.formats),
            "resolution_dpi": self.resolution_dpi,
            "dimensions_inches": thaw(self.dimensions_inches),
            "physical_size_roles": thaw(self.physical_size_roles),
            "pixel_rounding": thaw(self.pixel_rounding),
            "grid_layouts": {
                name: {
                    "size_role": layout.size_role,
                    "rows": layout.rows,
                    "columns": layout.columns,
                    "width_ratios": list(layout.width_ratios),
                    "height_ratios": list(layout.height_ratios),
                    "cells": [
                        {
                            "kind": cell.kind,
                            "row": cell.row,
                            "column": cell.column,
                            "row_span": cell.row_span,
                            "column_span": cell.column_span,
                            **({"panel_index": cell.panel_index} if cell.panel_index is not None else {}),
                            **({"auxiliary_id": cell.auxiliary_id} if cell.auxiliary_id is not None else {}),
                        }
                        for cell in layout.cells
                    ],
                }
                for name, layout in self.grid_layouts.items()
            },
            "font_sizes_pt": thaw(self.font_sizes_pt),
            "map_layout": thaw(self.map_layout),
            "publication_geometry": {
                "canvas": {
                    "width_cm": self.publication_geometry.canvas.width_cm,
                    "height_cm": self.publication_geometry.canvas.height_cm,
                    "orientation": self.publication_geometry.canvas.orientation,
                },
                "outer_margins": {
                    "left_fraction": self.publication_geometry.outer_left_fraction,
                    "right_fraction": self.publication_geometry.outer_right_fraction,
                    "top_fraction": self.publication_geometry.outer_top_fraction,
                    "bottom_fraction": self.publication_geometry.outer_bottom_fraction,
                },
                "spacing": {
                    "inter_column": self.publication_geometry.inter_column,
                    "inter_row": self.publication_geometry.inter_row,
                },
                "axis_label_padding_pt": {
                    "x": self.publication_geometry.xlabel_padding_pt,
                    "y": self.publication_geometry.ylabel_padding_pt,
                },
                "panel_label_offset_axes": {
                    "x": self.publication_geometry.panel_label_offset_x,
                    "y": self.publication_geometry.panel_label_offset_y,
                },
                "map_panel": {
                    "map_height_ratio": self.publication_geometry.map_height_ratio,
                    "legend_band_height": self.publication_geometry.map_legend_band_height,
                    "colourbar_band_height": self.publication_geometry.map_colourbar_band_height,
                    "inter_band_spacing": self.publication_geometry.map_inter_band_spacing,
                },
                "heatmap_colorbar_band_fraction": self.publication_geometry.heatmap_colorbar_band_fraction,
                "heatmap_colorbar_gap_fraction": self.publication_geometry.heatmap_colorbar_gap_fraction,
                "effect_vertical_padding_rows": self.publication_geometry.effect_vertical_padding_rows,
            },
            "semantic_styles": {
                "valid_zero": {
                    "face": self.semantic_styles.valid_zero.face,
                    "edge": self.semantic_styles.valid_zero.edge,
                },
                "not_significant": {
                    "face": self.semantic_styles.not_significant.face,
                    "edge": self.semantic_styles.not_significant.edge,
                },
                "excluded": {
                    "face": self.semantic_styles.excluded.face,
                    "edge": self.semantic_styles.excluded.edge,
                    "hatch": self.semantic_styles.excluded.hatch,
                },
                "local_moran": {
                    name: {"face": value.face, "edge": value.edge, "hatch": value.hatch}
                    for name, value in self.semantic_styles.local_moran.items()
                },
            },
            "display_conventions": {
                "circular_mean_month": {
                    "axis_label": self.display_conventions.circular_mean_month.axis_label,
                    "legend_title": self.display_conventions.circular_mean_month.legend_title,
                    "axis_min": self.display_conventions.circular_mean_month.axis_min,
                    "axis_max": self.display_conventions.circular_mean_month.axis_max,
                    "ticks": list(self.display_conventions.circular_mean_month.ticks),
                    "tick_labels": list(self.display_conventions.circular_mean_month.tick_labels),
                }
            },
            "panel_layout": thaw(self.panel_layout),
            "panel_labels": thaw(self.panel_labels),
            "source_data_policy": thaw(self.source_data_policy),
            "text_policy": thaw(self.text_policy),
            **(
                {
                    "presentation_export": {
                        "schema": self.presentation_export.schema,
                        "groups": list(self.presentation_export.groups),
                        "renderer_identities": list(self.presentation_export.renderer_identities),
                        "sources": {
                            name: {"path_pattern": item.path_pattern}
                            for name, item in self.presentation_export.sources.items()
                        },
                        "geometry_dependencies": {
                            name: {"geometries": list(item.geometries)}
                            for name, item in self.presentation_export.geometry_dependencies.items()
                        },
                        "output": {
                            "formats": list(self.presentation_export.output.formats),
                            "size_role": self.presentation_export.output.size_role,
                            "raster_dpi": self.presentation_export.output.raster_dpi,
                            "collision_policy": self.presentation_export.output.collision_policy,
                            "deterministic_names": self.presentation_export.output.deterministic_names,
                            "source_run_read_only": self.presentation_export.output.source_run_read_only,
                            "staging_policy": self.presentation_export.output.staging_policy,
                        },
                        "run_family": {
                            "required_member_suffix": self.presentation_export.run_family.required_member_suffix,
                            "publication_member_suffix": self.presentation_export.run_family.publication_member_suffix,
                            "secondary_member_suffix": self.presentation_export.run_family.secondary_member_suffix,
                            "require_closeout_validation": self.presentation_export.run_family.require_closeout_validation,
                        },
                        "manifests": {
                            "export_manifest": self.presentation_export.manifests.export_manifest,
                            "source_inventory": self.presentation_export.manifests.source_inventory,
                            "output_inventory": self.presentation_export.manifests.output_inventory,
                        },
                        "semantic_styles": thaw(self.presentation_export.semantic_styles),
                        "exports": [
                            {
                                "export_id": item.export_id,
                                "group": item.group,
                                "label": item.label,
                                "source_identity": item.source_identity,
                                "source_path_pattern": item.source_path_pattern,
                                "selector": thaw(item.selector),
                                "geometry_dependency": item.geometry_dependency,
                                "renderer_identity": item.renderer_identity,
                                "scenario": item.scenario,
                                "required_result_state": item.required_result_state,
                                "output_filename": item.output_filename,
                                "size_role": item.size_role,
                                "formats": list(item.formats),
                                "raster_dpi": item.raster_dpi,
                                "units": item.units,
                                "category_order": thaw(item.category_order),
                                "colour_semantic": item.colour_semantic,
                                "legend_policy": thaw(item.legend_policy),
                                "annotation_policy": list(item.annotation_policy),
                                "interpretation_boundary": item.interpretation_boundary,
                            }
                            for item in self.presentation_export.exports
                        ],
                    }
                }
                if self.presentation_export is not None
                else {}
            ),
            "figures": [
                {
                    "id": item.figure_id,
                    "rq": item.rq,
                    "title": item.title,
                    "role": item.role,
                    "evidence_class": item.evidence_class,
                    "layout_role": item.layout_role,
                    "renderer": item.renderer,
                    "data_builder": item.data_builder,
                    "source_attribute": item.source_attribute,
                    "requires_results_validated": item.requires_results_validated,
                    "data_builder_options": thaw(item.data_builder_options),
                    "renderer_options": thaw(item.renderer_options),
                    "xlabel": item.xlabel,
                    "ylabel": item.ylabel,
                    "colorbar_label": item.colorbar_label,
                    "panel_count": item.panel_count,
                    "panel_xlabels": list(item.panel_xlabels),
                    "panel_ylabels": list(item.panel_ylabels),
                    "required_columns": list(item.required_columns),
                }
                for item in self.figures
            ],
        }




@dataclass(frozen=True, slots=True)
class QualificationRepositoryContract:
    include_roots: tuple[str, ...]
    paths_must_be_repository_relative: bool
    forbid_parent_traversal: bool
    forbid_symlinks: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "include_roots": list(self.include_roots),
            "paths_must_be_repository_relative": self.paths_must_be_repository_relative,
            "forbid_parent_traversal": self.forbid_parent_traversal,
            "forbid_symlinks": self.forbid_symlinks,
        }


@dataclass(frozen=True, slots=True)
class QualificationPackageContract:
    module: str
    distribution: str
    project_root: str
    source_root: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "distribution": self.distribution,
            "project_root": self.project_root,
            "source_root": self.source_root,
        }


@dataclass(frozen=True, slots=True)
class GeneratedArtifactContract:
    directory_names: tuple[str, ...]
    directory_suffixes: tuple[str, ...]
    file_suffixes: tuple[str, ...]
    file_names: tuple[str, ...]
    policy: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "directory_names": list(self.directory_names),
            "directory_suffixes": list(self.directory_suffixes),
            "file_suffixes": list(self.file_suffixes),
            "file_names": list(self.file_names),
            "policy": self.policy,
        }


@dataclass(frozen=True, slots=True)
class QualificationProjectionContract:
    root_policy: str
    fresh_recreate_each_run: bool
    governed_set: str
    pre_copy_inventory: str
    post_copy_exact_inventory_comparison: bool
    unexpected_omission: str
    hash_or_size_mismatch: str
    clean_projection_subdirectory: str
    allowed_temporary_subdirectories: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_policy": self.root_policy,
            "fresh_recreate_each_run": self.fresh_recreate_each_run,
            "governed_set": self.governed_set,
            "pre_copy_inventory": self.pre_copy_inventory,
            "post_copy_exact_inventory_comparison": self.post_copy_exact_inventory_comparison,
            "unexpected_omission": self.unexpected_omission,
            "hash_or_size_mismatch": self.hash_or_size_mismatch,
            "clean_projection_subdirectory": self.clean_projection_subdirectory,
            "allowed_temporary_subdirectories": list(self.allowed_temporary_subdirectories),
        }


@dataclass(frozen=True, slots=True)
class QualificationImportContract:
    operational_mode: str
    projected_mode: str
    isolated_mode: str
    wrong_origin: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "operational_mode": self.operational_mode,
            "projected_mode": self.projected_mode,
            "isolated_mode": self.isolated_mode,
            "wrong_origin": self.wrong_origin,
        }


@dataclass(frozen=True, slots=True)
class QualificationEvidenceContract:
    must_be_external_to_operational_repository: bool
    logs_must_be_outside_clean_projection: bool
    stale_runtime_removed_before_run: bool
    evidence_subdirectory: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "must_be_external_to_operational_repository": self.must_be_external_to_operational_repository,
            "logs_must_be_outside_clean_projection": self.logs_must_be_outside_clean_projection,
            "stale_runtime_removed_before_run": self.stale_runtime_removed_before_run,
            "evidence_subdirectory": self.evidence_subdirectory,
        }


@dataclass(frozen=True, slots=True)
class QualificationBuildContract:
    wheel_sources: str
    build_isolation_policy: str
    isolated_install_target: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "wheel_sources": self.wheel_sources,
            "build_isolation_policy": self.build_isolation_policy,
            "isolated_install_target": self.isolated_install_target,
        }


@dataclass(frozen=True, slots=True)
class QualificationContract:
    schema_version: str
    contract_id: str
    repository: QualificationRepositoryContract
    packages: tuple[QualificationPackageContract, ...]
    generated_artifacts: GeneratedArtifactContract
    projection: QualificationProjectionContract
    imports: QualificationImportContract
    evidence: QualificationEvidenceContract
    build: QualificationBuildContract

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "contract_id": self.contract_id,
            "repository": self.repository.to_dict(),
            "packages": [item.to_dict() for item in self.packages],
            "generated_artifacts": self.generated_artifacts.to_dict(),
            "projection": self.projection.to_dict(),
            "imports": self.imports.to_dict(),
            "evidence": self.evidence.to_dict(),
            "build": self.build.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ExecutionModeContract:
    mode_id: str
    required_artifact_roles: tuple[str, ...]
    optional_artifact_roles: tuple[str, ...]
    required_record_fields: tuple[str, ...]
    notebook_snapshot_required: bool
    notebook_snapshot_sha256_required: bool
    code_cell_completion_rule: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode_id": self.mode_id,
            "required_artifact_roles": list(self.required_artifact_roles),
            "optional_artifact_roles": list(self.optional_artifact_roles),
            "required_record_fields": list(self.required_record_fields),
            "notebook_snapshot_required": self.notebook_snapshot_required,
            "notebook_snapshot_sha256_required": self.notebook_snapshot_sha256_required,
            "code_cell_completion_rule": self.code_cell_completion_rule,
        }


@dataclass(frozen=True, slots=True)
class ExecutionCloseoutContract:
    schema_version: str
    contract_id: str
    closeout_section: str
    artifact_roles: Mapping[str, str]
    required_final_gate: str
    execution_record_schema: str
    allowed_secondary_completion_states: tuple[str, ...]
    results_validated_required_integration_state: str
    unknown_mode_policy: str
    missing_mode_policy: str
    modes: Mapping[str, ExecutionModeContract]

    def mode(self, mode_id: str) -> ExecutionModeContract:
        try:
            return self.modes[mode_id]
        except KeyError as exc:
            raise KeyError(f"Unsupported execution mode: {mode_id}") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "contract_id": self.contract_id,
            "closeout": {
                "section": self.closeout_section,
                "artifact_roles": thaw(self.artifact_roles),
                "required_final_gate": self.required_final_gate,
                "execution_record_schema": self.execution_record_schema,
            },
            "secondary_completion": {
                "allowed_states": list(self.allowed_secondary_completion_states),
                "results_validated_required_integration_state": self.results_validated_required_integration_state,
            },
            "validation": {
                "unknown_mode_policy": self.unknown_mode_policy,
                "missing_mode_policy": self.missing_mode_policy,
            },
            "modes": {name: mode.to_dict() for name, mode in self.modes.items()},
        }


@dataclass(frozen=True, slots=True)
class ConfigurationBundle:
    analysis: AnalysisContract
    data_schema: DataSchemaContract
    methods: MethodAuthorityContract
    output: OutputContract
    figure: FigureContract
    execution: ExecutionCloseoutContract
    file_hashes: Mapping[str, str]
    configuration_sha256: str
    operational_file_hashes: Mapping[str, str]
    operational_configuration_sha256: str
    package_version: str

    @property
    def aggregate_config_sha256(self) -> str:
        return self.configuration_sha256

    def realised_dict(self) -> dict[str, Any]:
        return {
            "analysis_schema_version": self.analysis.schema_version,
            "data_schema_version": self.data_schema.data_schema_version,
            "package_version": self.package_version,
            "configuration_sha256": self.configuration_sha256,
            "config_file_sha256": dict(self.file_hashes),
            "operational_config_file_sha256": dict(self.operational_file_hashes),
            "operational_configuration_sha256": self.operational_configuration_sha256,
            "contracts": {
                "analysis_contract.yml": self.analysis.to_dict(),
                "data_schema_contract.yml": self.data_schema.to_dict(),
                "method_authorities.yml": self.methods.to_dict(),
                "output_contract.yml": self.output.to_dict(),
                "figure_contract.yml": self.figure.to_dict(),
            },
            "operational_contracts": {
                "execution_contract.yml": self.execution.to_dict(),
            },
        }


def ensure_unique(values: Sequence[str], context: str) -> None:
    seen: set[str] = set()
    duplicate: set[str] = set()
    for value in values:
        if value in seen:
            duplicate.add(value)
        seen.add(value)
    if duplicate:
        raise ValueError(f"Duplicate values in {context}: {sorted(duplicate)!r}")
