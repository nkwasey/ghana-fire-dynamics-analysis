"""Typed publication-figure projections from an explicitly supplied contract.

No figure configuration is loaded at import time.  Callers must inject either
an already-loaded :class:`FigureContract` or explicit project paths.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, TypeAlias

from .config import FigureContract, load_figure_contract
from .contracts import PresentationExportRegistryContract, PresentationExportSpecificationContract
from .paths import ProjectPaths

LayoutRole: TypeAlias = str
RendererIdentity: TypeAlias = str


@dataclass(frozen=True, slots=True)
class FigureSpecification:
    figure_id: str
    rq: str
    title: str
    role: str
    evidence_class: str
    layout_role: str
    renderer: str
    data_builder: str
    source_attribute: str
    requires_results_validated: bool
    data_builder_options: Mapping[str, Any] = MappingProxyType({})
    renderer_options: Mapping[str, Any] = MappingProxyType({})
    xlabel: str | None = None
    ylabel: str | None = None
    colorbar_label: str | None = None
    panel_count: int = 1
    panel_xlabels: tuple[str | None, ...] = ()
    panel_ylabels: tuple[str | None, ...] = ()
    required_columns: tuple[str, ...] = ()


    def validate_panel_structure(self) -> None:
        """Validate the fixed-panel presentation structure carried by the contract."""
        if self.panel_count < 1:
            raise ValueError(f"{self.figure_id} panel_count must be positive")
        if self.panel_count > 1:
            if len(self.panel_xlabels) != self.panel_count or len(self.panel_ylabels) != self.panel_count:
                raise ValueError(f"{self.figure_id} configured panel label arrays do not match panel_count")

    @property
    def figure_data_identity(self) -> str:
        return f"FD_{self.figure_id}.csv"

    def registry_tuple(self) -> tuple[str, str, str, str, str]:
        return (self.figure_id, self.rq, self.title, self.role, self.evidence_class)


def _project(contract: FigureContract) -> tuple[FigureSpecification, ...]:
    specs = tuple(
        FigureSpecification(
            figure_id=item.figure_id, rq=item.rq, title=item.title, role=item.role,
            evidence_class=item.evidence_class, layout_role=item.layout_role,
            renderer=item.renderer, data_builder=item.data_builder,
            source_attribute=item.source_attribute,
            requires_results_validated=item.requires_results_validated,
            data_builder_options=item.data_builder_options,
            renderer_options=item.renderer_options,
            xlabel=item.xlabel, ylabel=item.ylabel, colorbar_label=item.colorbar_label,
            panel_count=item.panel_count, panel_xlabels=item.panel_xlabels,
            panel_ylabels=item.panel_ylabels, required_columns=item.required_columns,
        ) for item in contract.figures
    )
    ids = [item.figure_id for item in specs]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Duplicate configured publication figure identifier")
    for item in specs:
        item.validate_panel_structure()
    return specs


def load_figure_specs(
    contract: FigureContract | None = None,
    *,
    paths: ProjectPaths | None = None,
) -> tuple[FigureSpecification, ...]:
    if contract is None:
        governed = paths or ProjectPaths.discover()
        contract = load_figure_contract(governed.figure_contract)
    return _project(contract)


def get_figure_spec(
    figure_id: str,
    contract: FigureContract | None = None,
    *,
    paths: ProjectPaths | None = None,
) -> FigureSpecification:
    by_id = {item.figure_id: item for item in load_figure_specs(contract, paths=paths)}
    try:
        return by_id[figure_id]
    except KeyError as exc:
        raise KeyError(f"No configured publication figure specification for {figure_id}") from exc


def get_secondary_figure_spec(
    figure_id: str,
    contract: FigureContract | None = None,
    *,
    paths: ProjectPaths | None = None,
) -> FigureSpecification:
    spec = get_figure_spec(figure_id, contract, paths=paths)
    if spec.rq != "SECONDARY":
        raise KeyError(f"Configured figure {figure_id} is not a secondary-analysis figure")
    return spec


def load_presentation_export_registry(
    contract: FigureContract | None = None,
    *,
    paths: ProjectPaths | None = None,
) -> PresentationExportRegistryContract:
    """Return the validated standalone presentation-export registry."""

    if contract is None:
        governed = paths or ProjectPaths.discover()
        contract = load_figure_contract(governed.figure_contract)
    if contract.presentation_export is None:
        raise KeyError("No presentation-export registry is configured")
    return contract.presentation_export


def get_presentation_export_spec(
    export_id: str,
    contract: FigureContract | None = None,
    *,
    paths: ProjectPaths | None = None,
) -> PresentationExportSpecificationContract:
    """Resolve one configured presentation export deterministically by ID."""

    registry = load_presentation_export_registry(contract, paths=paths)
    try:
        return registry.export_by_id(export_id)
    except KeyError as exc:
        raise KeyError(f"No configured presentation export for {export_id!r}") from exc


def get_presentation_exports_for_group(
    group: str,
    contract: FigureContract | None = None,
    *,
    paths: ProjectPaths | None = None,
) -> tuple[PresentationExportSpecificationContract, ...]:
    """Resolve a configured presentation group in catalogue order."""

    registry = load_presentation_export_registry(contract, paths=paths)
    try:
        return registry.exports_for_group(group)
    except KeyError as exc:
        raise KeyError(f"Unknown presentation export group {group!r}") from exc
