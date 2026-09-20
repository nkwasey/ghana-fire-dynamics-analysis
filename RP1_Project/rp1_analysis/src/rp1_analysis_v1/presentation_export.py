"""Read-only presentation-figure export infrastructure for completed RP1 runs.

This module owns operational mechanics only.  Scientific quantities, source
identities, selectors, renderer identities, dimensions and result-state
requirements remain governed by ``config/figure_contract.yml`` and the
existing analysis/data/output contracts.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import tempfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

import pandas as pd

from .config import ConfigurationBundle, load_configuration_bundle
from .contracts import PresentationExportRegistryContract, PresentationExportSpecificationContract
from .figures import RenderedFigure
from .integration import IntegrationError, RunValidationResult, validate_run_authority
from .outputs import sha256_file, stable_filename
from .paths import ProjectPaths
from .presentation import load_presentation_export_registry
from .presentation_rq1 import RQ1_PRESENTATION_RENDERERS
from .presentation_rq2 import RQ2_PRESENTATION_RENDERERS
from .presentation_rq3 import RQ3_PRESENTATION_RENDERERS
from .presentation_rq4 import RQ4_PRESENTATION_RENDERERS
from .satscan_integration import OptionalSaTScanIntegrationError, inspect_satscan_results
from .style import PublicationStyle, cm_to_inches


class PresentationExportError(RuntimeError):
    """Base class for fail-closed presentation-export errors."""


class RunAuthorityError(PresentationExportError):
    """Raised when a supplied completed run is missing, malformed or incompatible."""


class SourceResolutionError(PresentationExportError):
    """Raised when a configured scientific source cannot be resolved exactly."""


class RendererUnavailableError(PresentationExportError):
    """Raised when a configured renderer has not yet been implemented for export."""


class PresentationOutputError(PresentationExportError):
    """Raised when derived output violates the presentation-output policy."""


@dataclass(frozen=True, slots=True)
class RunFamilyAuthority:
    run_base: str
    publication_run: Path
    secondary_run: Path
    closeout_run: Path
    validation: RunValidationResult

    @property
    def members(self) -> tuple[Path, Path, Path]:
        return (self.publication_run, self.secondary_run, self.closeout_run)


@dataclass(frozen=True, slots=True)
class SourceAuthority:
    source_identity: str
    path: Path
    project_relative_path: str
    sha256: str
    size_bytes: int
    frame: pd.DataFrame | None
    selected_rows: int | None


@dataclass(frozen=True, slots=True)
class GeometryAuthority:
    dependency_id: str
    members: Mapping[str, tuple[Path, ...]]
    hashes: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class RunTreeRecord:
    path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class ExportManifestRecord:
    export_id: str
    group: str
    renderer: str
    run_identity: str
    semantic_source_identity: str
    exact_source_path: str
    source_sha256: str
    configuration_sha256: str
    generated_path: str
    generated_sha256: str
    format: str
    dimensions: Mapping[str, float | int | str]
    status: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "export_id": self.export_id,
            "group": self.group,
            "renderer": self.renderer,
            "run_identity": self.run_identity,
            "semantic_source_identity": self.semantic_source_identity,
            "exact_source_path": self.exact_source_path,
            "source_sha256": self.source_sha256,
            "configuration_sha256": self.configuration_sha256,
            "generated_path": self.generated_path,
            "generated_sha256": self.generated_sha256,
            "format": self.format,
            "dimensions": dict(self.dimensions),
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class RenderContext:
    paths: ProjectPaths
    bundle: ConfigurationBundle
    registry: PresentationExportRegistryContract
    run: RunFamilyAuthority
    source: SourceAuthority
    geometry: GeometryAuthority
    style: PublicationStyle


class PresentationRenderer(Protocol):
    def __call__(
        self,
        frame: pd.DataFrame | None,
        *,
        spec: PresentationExportSpecificationContract,
        context: RenderContext,
    ) -> RenderedFigure: ...


class RendererRegistry:
    """Explicit renderer dispatch with no implicit fallback."""

    def __init__(self, renderers: Mapping[str, PresentationRenderer] | None = None):
        self._renderers: dict[str, PresentationRenderer] = dict(renderers or {})

    @property
    def identities(self) -> tuple[str, ...]:
        return tuple(sorted(self._renderers))

    def register(self, renderer_id: str, renderer: PresentationRenderer) -> None:
        if not renderer_id or renderer_id in self._renderers:
            raise ValueError(f"Renderer identity is empty or already registered: {renderer_id!r}")
        self._renderers[renderer_id] = renderer

    def resolve(self, renderer_id: str) -> PresentationRenderer:
        try:
            return self._renderers[renderer_id]
        except KeyError as exc:
            raise RendererUnavailableError(
                f"Configured presentation renderer {renderer_id!r} is not yet implemented"
            ) from exc

    def dispatch(
        self,
        renderer_id: str,
        frame: pd.DataFrame | None,
        *,
        spec: PresentationExportSpecificationContract,
        context: RenderContext,
    ) -> RenderedFigure:
        return self.resolve(renderer_id)(frame, spec=spec, context=context)


def _presentation_style(bundle: ConfigurationBundle, spec: PresentationExportSpecificationContract) -> PublicationStyle:
    style = PublicationStyle.from_contract(bundle.figure)
    role = bundle.figure.physical_size_roles[spec.size_role]
    width_in = cm_to_inches(float(role["width_cm"]))
    height_in = cm_to_inches(float(role["height_cm"]))
    # Existing generic single-panel renderers consume one of these size slots.
    return replace(
        style,
        dpi=spec.raster_dpi,
        single_panel=(width_in, height_in),
        wide_single_panel=(width_in, height_in),
        full_width_map=(width_in, height_in),
    )


def build_core_renderer_registry() -> RendererRegistry:
    """Return presentation renderers currently qualified for operational export.

    Renderer identities absent from this explicit registry continue to fail
    closed until their scientific family is implemented and qualified.
    """

    return RendererRegistry({**RQ1_PRESENTATION_RENDERERS, **RQ2_PRESENTATION_RENDERERS, **RQ3_PRESENTATION_RENDERERS, **RQ4_PRESENTATION_RENDERERS})


def _require_under(path: Path, parent: Path, *, context: str) -> None:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError as exc:
        raise RunAuthorityError(f"{context} escapes the governed run root: {path}") from exc


def resolve_run_family(
    run_dir: str | Path,
    *,
    paths: ProjectPaths | None = None,
    registry: PresentationExportRegistryContract | None = None,
    validate: bool = True,
) -> RunFamilyAuthority:
    """Resolve and validate a completed ``_pub/_sec/_close`` run family.

    ``run_dir`` must name the configured closeout member.  This keeps run
    identity unambiguous and prevents heuristic binding to stale siblings.
    """

    governed = paths or ProjectPaths.discover()
    configured = registry or load_presentation_export_registry(paths=governed)
    supplied = Path(run_dir).expanduser().resolve()
    if not supplied.is_dir():
        raise RunAuthorityError(f"Run directory does not exist: {supplied}")

    run_root = governed.resolve_inside("out/runs").resolve()
    _require_under(supplied, run_root, context="Supplied run directory")
    if supplied.parent != run_root:
        raise RunAuthorityError("Supplied run directory must be a direct member of out/runs")

    close_suffix = configured.run_family.required_member_suffix
    if not supplied.name.endswith(close_suffix):
        raise RunAuthorityError(
            f"Supplied run directory must be the configured closeout member ending {close_suffix!r}"
        )
    run_base = supplied.name[: -len(close_suffix)]
    if not run_base:
        raise RunAuthorityError("Unable to derive run identity from supplied closeout directory")

    publication = run_root / f"{run_base}{configured.run_family.publication_member_suffix}"
    secondary = run_root / f"{run_base}{configured.run_family.secondary_member_suffix}"
    closeout = run_root / f"{run_base}{close_suffix}"
    for member in (publication, secondary, closeout):
        if not member.is_dir():
            raise RunAuthorityError(f"Completed run family is missing member: {member.name}")

    validation: RunValidationResult
    if validate and configured.run_family.require_closeout_validation:
        try:
            validation = validate_run_authority(paths=governed, run_id=run_base)
        except (IntegrationError, OSError, ValueError, KeyError) as exc:
            raise RunAuthorityError(f"Completed run validation failed for {run_base}: {exc}") from exc
        if validation.status != "PASS":
            raise RunAuthorityError(f"Completed run validation did not PASS for {run_base}")
    else:
        validation = RunValidationResult(
            run_id=run_base,
            status="NOT_RUN",
            publication_files=0,
            secondary_files=0,
            closeout_files=0,
            publication_tables=0,
            publication_figures=0,
            secondary_external_state="NOT_CHECKED",
            output_inventory=pd.DataFrame(columns=["path", "sha256", "size_bytes"]),
            checks=(),
        )

    authority = RunFamilyAuthority(
        run_base=run_base,
        publication_run=publication.resolve(),
        secondary_run=secondary.resolve(),
        closeout_run=closeout.resolve(),
        validation=validation,
    )
    validate_run_configuration_compatibility(authority, paths=governed)
    return authority


def validate_run_configuration_compatibility(
    run: RunFamilyAuthority,
    *,
    paths: ProjectPaths | None = None,
    bundle: ConfigurationBundle | None = None,
) -> None:
    """Reject scientific contract mismatches while allowing the new export registry.

    The completed run records the realised five-contract configuration.  The
    scientific contracts must remain byte-identical.  The historic figure
    contract is compared semantically after removing the new
    ``presentation_export`` extension, which did not exist when the run was
    created.
    """

    governed = paths or ProjectPaths.discover()
    current = bundle or load_configuration_bundle(governed.root / "config")
    realised_path = run.closeout_run / "00_scaffold" / "realised_configuration.json"
    if not realised_path.is_file():
        raise RunAuthorityError("Completed run is missing realised_configuration.json")
    try:
        realised = json.loads(realised_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunAuthorityError("Completed run realised configuration is malformed") from exc

    if realised.get("analysis_schema_version") != current.analysis.schema_version:
        raise RunAuthorityError("Completed run analysis schema is incompatible with the exporter")
    if realised.get("data_schema_version") != current.data_schema.data_schema_version:
        raise RunAuthorityError("Completed run data schema is incompatible with the exporter")

    recorded_hashes = realised.get("config_file_sha256")
    if not isinstance(recorded_hashes, Mapping):
        raise RunAuthorityError("Completed run does not record per-contract SHA-256 identities")
    for filename in (
        "analysis_contract.yml",
        "data_schema_contract.yml",
        "method_authorities.yml",
        "output_contract.yml",
    ):
        if recorded_hashes.get(filename) != current.file_hashes.get(filename):
            raise RunAuthorityError(f"Completed run scientific contract differs from current authority: {filename}")

    contracts = realised.get("contracts")
    if not isinstance(contracts, Mapping) or not isinstance(contracts.get("figure_contract.yml"), Mapping):
        raise RunAuthorityError("Completed run does not contain a realised figure contract")
    # ``presentation_export`` is an operational rendering registry rather than
    # a scientific/publication figure authority.  Older completed runs may not
    # record it, while newer completed runs may.  Remove it symmetrically from
    # both realised and current contracts before compatibility comparison so
    # the result cannot depend on which side of the extension boundary created
    # the run.  All remaining figure-contract content must still match exactly.
    recorded_figure = dict(contracts["figure_contract.yml"])
    recorded_figure.pop("presentation_export", None)
    current_figure = current.figure.to_dict()
    current_figure.pop("presentation_export", None)
    if recorded_figure != current_figure:
        raise RunAuthorityError(
            "Completed run publication figure contract differs from the current pre-export figure authority"
        )

    provenance_path = (
        run.closeout_run
        / current.execution.closeout_section
        / current.execution.artifact_roles["reproducibility_manifest"]
    )
    if not provenance_path.is_file():
        raise RunAuthorityError("Completed run is missing its reproducibility manifest")
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RunAuthorityError("Completed run reproducibility manifest is malformed") from exc
    recorded_inputs = provenance.get("inputs")
    if not isinstance(recorded_inputs, list):
        raise RunAuthorityError("Completed run reproducibility manifest does not record input identities")
    recorded_by_path = {
        str(item.get("path")): str(item.get("sha256"))
        for item in recorded_inputs
        if isinstance(item, Mapping) and isinstance(item.get("path"), str)
    }
    for geometry in current.data_schema.geometries.values():
        for relative in geometry.required_members:
            path = governed.resolve_inside(relative)
            expected = recorded_by_path.get(relative)
            if expected is None:
                raise RunAuthorityError(f"Completed run does not record governed geometry input: {relative}")
            if sha256_file(path) != expected:
                raise RunAuthorityError(f"Governed geometry differs from completed-run input authority: {relative}")


def snapshot_run_tree(run: RunFamilyAuthority, *, project_root: Path) -> tuple[RunTreeRecord, ...]:
    """Return an exact immutable inventory of all files in a run family."""

    rows: list[RunTreeRecord] = []
    root = project_root.resolve()
    for member in run.members:
        for path in sorted(member.rglob("*")):
            if path.is_symlink():
                raise RunAuthorityError(f"Run authority contains a symbolic link: {path}")
            if not path.is_file():
                continue
            rows.append(
                RunTreeRecord(
                    path=path.resolve().relative_to(root).as_posix(),
                    sha256=sha256_file(path),
                    size_bytes=int(path.stat().st_size),
                )
            )
    return tuple(rows)


def assert_run_tree_unchanged(before: tuple[RunTreeRecord, ...], after: tuple[RunTreeRecord, ...]) -> None:
    if before != after:
        before_map = {item.path: (item.sha256, item.size_bytes) for item in before}
        after_map = {item.path: (item.sha256, item.size_bytes) for item in after}
        missing = sorted(set(before_map) - set(after_map))
        added = sorted(set(after_map) - set(before_map))
        changed = sorted(
            path for path in set(before_map).intersection(after_map) if before_map[path] != after_map[path]
        )
        raise RunAuthorityError(
            f"Source run was modified during export; missing={missing!r}, added={added!r}, changed={changed!r}"
        )


def _resolve_project_relative(pattern: str, *, paths: ProjectPaths, run_base: str) -> Path:
    try:
        rendered = pattern.format(run_base=run_base)
    except (KeyError, ValueError) as exc:
        raise SourceResolutionError(f"Invalid configured source path pattern: {pattern!r}") from exc
    if "{" in rendered or "}" in rendered:
        raise SourceResolutionError(f"Unresolved configured source path pattern: {pattern!r}")
    try:
        return paths.resolve_inside(rendered)
    except Exception as exc:
        raise SourceResolutionError(f"Configured source path escapes project authority: {rendered!r}") from exc


def _apply_selector(frame: pd.DataFrame, selector: Mapping[str, Any], *, export_id: str) -> pd.DataFrame:
    if selector.get("all_rows") is True:
        selected = frame.copy()
    else:
        column = str(selector.get("column"))
        if column not in frame.columns:
            raise SourceResolutionError(f"{export_id} selector column is absent from source: {column!r}")
        expected = selector.get("equals")
        if isinstance(expected, str):
            mask = frame[column].astype(str).eq(expected)
        else:
            mask = frame[column].eq(expected)
        selected = frame.loc[mask].copy()
    if selected.empty:
        raise SourceResolutionError(f"{export_id} selector resolved zero source rows")
    return selected.reset_index(drop=True)


def resolve_source(
    spec: PresentationExportSpecificationContract,
    run: RunFamilyAuthority,
    *,
    paths: ProjectPaths | None = None,
) -> SourceAuthority:
    governed = paths or ProjectPaths.discover()
    path = _resolve_project_relative(spec.source_path_pattern, paths=governed, run_base=run.run_base)
    if not path.is_file():
        raise SourceResolutionError(f"Configured scientific source is missing: {path}")
    if path.is_symlink():
        raise SourceResolutionError(f"Configured scientific source must not be a symbolic link: {path}")

    frame: pd.DataFrame | None = None
    selected_rows: int | None = None
    if path.suffix.casefold() == ".csv":
        try:
            raw = pd.read_csv(path)
        except Exception as exc:
            raise SourceResolutionError(f"Unable to read configured CSV source: {path}") from exc
        frame = _apply_selector(raw, spec.selector, export_id=spec.export_id)
        selected_rows = int(len(frame))
    elif spec.selector.get("all_rows") is not True:
        raise SourceResolutionError(
            f"Non-tabular source {path.name} only supports the configured all_rows selector"
        )

    return SourceAuthority(
        source_identity=spec.source_identity,
        path=path.resolve(),
        project_relative_path=path.resolve().relative_to(governed.root.resolve()).as_posix(),
        sha256=sha256_file(path),
        size_bytes=int(path.stat().st_size),
        frame=frame,
        selected_rows=selected_rows,
    )


def resolve_geometry_dependency(
    dependency_id: str,
    *,
    paths: ProjectPaths | None = None,
    bundle: ConfigurationBundle | None = None,
    registry: PresentationExportRegistryContract | None = None,
) -> GeometryAuthority:
    governed = paths or ProjectPaths.discover()
    current = bundle or load_configuration_bundle(governed.root / "config")
    configured = registry or load_presentation_export_registry(current.figure)
    try:
        dependency = configured.geometry_dependencies[dependency_id]
    except KeyError as exc:
        raise SourceResolutionError(f"Unknown configured geometry dependency: {dependency_id!r}") from exc

    members: dict[str, tuple[Path, ...]] = {}
    hashes: dict[str, tuple[str, ...]] = {}
    for geometry_id in dependency.geometries:
        try:
            geometry = current.data_schema.geometry(geometry_id)
        except KeyError as exc:
            raise SourceResolutionError(f"Unknown governed geometry identity: {geometry_id!r}") from exc
        resolved: list[Path] = []
        digests: list[str] = []
        for relative in geometry.required_members:
            path = governed.resolve_inside(relative)
            if not path.is_file() or path.is_symlink():
                raise SourceResolutionError(f"Governed geometry member is missing or invalid: {path}")
            resolved.append(path.resolve())
            digests.append(sha256_file(path))
        members[geometry_id] = tuple(resolved)
        hashes[geometry_id] = tuple(digests)
    return GeometryAuthority(
        dependency_id=dependency_id,
        members=MappingProxyType(members),
        hashes=MappingProxyType(hashes),
    )


def validate_required_result_state(spec: PresentationExportSpecificationContract, run: RunFamilyAuthority) -> None:
    if spec.required_result_state == "NONE":
        return
    if spec.required_result_state != "RESULTS_VALIDATED":
        raise RunAuthorityError(
            f"Unsupported configured result-state requirement: {spec.required_result_state!r}"
        )
    if run.validation.secondary_external_state != "RESULTS_VALIDATED":
        raise RunAuthorityError(
            f"{spec.export_id} requires genuine RESULTS_VALIDATED secondary output; "
            f"observed {run.validation.secondary_external_state!r}"
        )


def _result_path(run: RunFamilyAuthority, relative: str, *, label: str) -> Path:
    rel = Path(str(relative))
    if rel.is_absolute():
        raise RunAuthorityError(f"{label} must be run-relative, not absolute")
    candidate = (run.secondary_run / rel).resolve()
    try:
        candidate.relative_to(run.secondary_run.resolve())
    except ValueError as exc:
        raise RunAuthorityError(f"{label} escapes the governed secondary run") from exc
    if not candidate.is_file() or candidate.is_symlink():
        raise RunAuthorityError(f"Required secondary authority is missing or invalid: {candidate}")
    return candidate


def _read_secondary_run_registry(run: RunFamilyAuthority) -> pd.DataFrame:
    path = run.secondary_run / "04_secondary_concentration" / "tables" / "secondary_run_registry.csv"
    if not path.is_file() or path.is_symlink():
        raise RunAuthorityError("Secondary run registry is missing")
    try:
        frame = pd.read_csv(path, keep_default_na=False)
    except Exception as exc:
        raise RunAuthorityError("Secondary run registry is unreadable") from exc
    required = {
        "model_id", "scenario_id", "product", "model", "execution_state",
        "prm_path", "case_path", "coordinate_path", "population_path",
        "results_prefix", "required_report_path", "required_cluster_path",
        "required_membership_path", "parameter_linkage_validated",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise RunAuthorityError(f"Secondary run registry is missing required columns: {missing!r}")
    return frame


def resolve_secondary_export_authority(
    spec: PresentationExportSpecificationContract,
    run: RunFamilyAuthority,
    source: SourceAuthority,
    *,
    paths: ProjectPaths | None = None,
) -> tuple[dict[str, Any], ...]:
    if spec.group != "rq4":
        return ()
    governed = paths or ProjectPaths.discover()
    try:
        inspection = inspect_satscan_results(paths=governed, secondary_run_id=run.secondary_run.name)
    except OptionalSaTScanIntegrationError as exc:
        raise RunAuthorityError(f"RQ4 SaTScan authority inspection failed: {exc}") from exc
    if inspection.external_execution_state != "RESULTS_VALIDATED":
        raise RunAuthorityError(f"{spec.export_id} requires RESULTS_VALIDATED SaTScan authorities")

    registry = _read_secondary_run_registry(run)
    matched = registry.loc[registry["model_id"].astype(str).eq(str(spec.scenario))].copy()
    if len(matched) != 1:
        raise SourceResolutionError(
            f"{spec.export_id} could not resolve exactly one governed secondary scenario for {spec.scenario!r}"
        )
    row = matched.iloc[0]
    expected_product = str(spec.selector.get("equals", ""))
    if str(row["scenario_id"]) != str(spec.scenario):
        raise SourceResolutionError(f"{spec.export_id} scenario registry is not concordant with the export authority")
    if str(row["product"]) != expected_product:
        raise SourceResolutionError(f"{spec.export_id} scenario/product linkage is not concordant with the export authority")
    if str(row["execution_state"]) != "RESULTS_VALIDATED":
        raise RunAuthorityError(f"{spec.export_id} scenario is not in RESULTS_VALIDATED state")
    if not bool(row["parameter_linkage_validated"]):
        raise RunAuthorityError(f"{spec.export_id} scenario lacks parameter-linkage validation")
    model = str(row["model"])
    if expected_product == "mcd64a1":
        if model != "discrete_poisson":
            raise SourceResolutionError("MCD64A1 RQ4 export must bind the discrete-Poisson scenario")
        if not str(row["population_path"]):
            raise SourceResolutionError("MCD64A1 RQ4 export must preserve the governed exposure authority")
    elif expected_product == "viirs":
        if model != "space_time_permutation":
            raise SourceResolutionError("VIIRS RQ4 export must bind the space-time permutation scenario")
        if str(row["population_path"]):
            raise SourceResolutionError("VIIRS STP export must not contain an exposure authority")

    if source.frame is not None and "product" in source.frame.columns:
        observed_products = set(source.frame["product"].astype(str))
        if observed_products != {expected_product}:
            raise SourceResolutionError(f"{spec.export_id} selected source rows do not match the configured product")

    inventory_rows: list[dict[str, Any]] = []

    def add(path: Path, identity: str, kind: str) -> None:
        if not path.is_file() or path.is_symlink():
            raise RunAuthorityError(f"Required secondary authority is missing or invalid: {path}")
        inventory_rows.append(
            {
                "identity": identity,
                "path": path.relative_to(governed.root.resolve()).as_posix(),
                "sha256": sha256_file(path),
                "size_bytes": int(path.stat().st_size),
                "kind": kind,
            }
        )

    add(run.secondary_run / "04_secondary_concentration" / "secondary_external_execution_status.json", str(spec.scenario), "secondary_status")
    add(run.secondary_run / "04_secondary_concentration" / "publication_sources" / "M_SATSCAN_PUBLICATION_SOURCE_MANIFEST.json", str(spec.scenario), "secondary_publication_source_manifest")
    add(run.secondary_run / "04_secondary_concentration" / "tables" / "secondary_run_registry.csv", str(spec.scenario), "secondary_run_registry")
    add(run.secondary_run / "04_secondary_concentration" / "tables" / "secondary_input_audit.csv", str(spec.scenario), "secondary_input_audit")

    for label, key in (("parameter", "prm_path"), ("case", "case_path"), ("coordinate", "coordinate_path")):
        add(_result_path(run, str(row[key]), label=key), str(spec.scenario), f"secondary_interface_{label}")
    population = str(row.get("population_path", ""))
    if population:
        add(_result_path(run, population, label="population_path"), str(spec.scenario), "secondary_interface_population")

    for label, key in (("report", "required_report_path"), ("cluster", "required_cluster_path"), ("membership", "required_membership_path")):
        add(_result_path(run, str(row[key]), label=key), str(spec.scenario), f"secondary_result_{label}")

    prov = inspection.provenance_summary.get(str(spec.scenario), {})
    for field, key in (("report_sha256", "required_report_path"), ("cluster_sha256", "required_cluster_path"), ("membership_sha256", "required_membership_path")):
        expected = str(prov.get(field, ""))
        if expected:
            path = _result_path(run, str(row[key]), label=key)
            observed = sha256_file(path)
            if observed != expected:
                raise RunAuthorityError(f"{spec.export_id} {field} does not match validated SaTScan provenance")

    return tuple(inventory_rows)


def _dimensions(
    bundle: ConfigurationBundle,
    spec: PresentationExportSpecificationContract,
) -> Mapping[str, float | int | str]:
    role = bundle.figure.physical_size_roles[spec.size_role]
    width_cm = float(role["width_cm"])
    height_cm = float(role["height_cm"])
    return MappingProxyType(
        {
            "size_role": spec.size_role,
            "width_cm": width_cm,
            "height_cm": height_cm,
            "width_in": cm_to_inches(width_cm),
            "height_in": cm_to_inches(height_cm),
            "raster_dpi": int(spec.raster_dpi),
        }
    )


def deterministic_output_name(spec: PresentationExportSpecificationContract, fmt: str) -> str:
    if fmt not in spec.formats:
        raise PresentationOutputError(f"Format {fmt!r} is not configured for {spec.export_id}")
    name = spec.output_filename.format(format=fmt)
    stable_filename(name)
    expected = f"{spec.export_id}.{fmt}"
    if name != expected:
        raise PresentationOutputError(
            f"Configured deterministic filename mismatch for {spec.export_id}: {name!r}"
        )
    return name


def validate_output_destination(output_dir: str | Path, *, run: RunFamilyAuthority) -> Path:
    destination = Path(output_dir).expanduser().resolve()
    if destination.exists():
        raise PresentationOutputError(f"Presentation output destination already exists: {destination}")
    run_root = run.closeout_run.parent.resolve()
    try:
        destination.relative_to(run_root)
    except ValueError:
        pass
    else:
        raise PresentationOutputError("Presentation output destination must be outside the governed run root")
    if not destination.name or destination.name in {".", ".."}:
        raise PresentationOutputError("Presentation output destination has no stable directory name")
    return destination


class PresentationOutputWriter:
    """Collision-on-error writer for a newly created staging directory."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        if not self.root.is_dir():
            raise PresentationOutputError(f"Staging directory does not exist: {self.root}")

    def write_bytes(self, name: str, payload: bytes) -> Path:
        stable_filename(name)
        if not isinstance(payload, (bytes, bytearray)) or not payload:
            raise PresentationOutputError(f"Generated payload is empty or invalid for {name}")
        destination = self.root / name
        if destination.exists():
            raise PresentationOutputError(f"Presentation output collision: {destination.name}")
        fd, tmp_name = tempfile.mkstemp(prefix=f".{name}.", suffix=".tmp", dir=self.root)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(bytes(payload))
                handle.flush()
                os.fsync(handle.fileno())
            os.link(tmp, destination)
            tmp.unlink()
        finally:
            if tmp.exists():
                tmp.unlink()
        return destination

    def write_text(self, name: str, text: str) -> Path:
        return self.write_bytes(name, text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8"))

    def write_json(self, name: str, payload: Any) -> Path:
        return self.write_text(
            name,
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        )

    def write_csv(self, name: str, rows: Iterable[Mapping[str, Any]], columns: tuple[str, ...]) -> Path:
        stable_filename(name)
        materialised = [dict(row) for row in rows]
        import io

        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=list(columns), lineterminator="\n")
        writer.writeheader()
        for index, row in enumerate(materialised):
            if set(row) != set(columns):
                raise PresentationOutputError(f"Manifest CSV row {index} does not match required columns")
            writer.writerow({column: row[column] for column in columns})
        return self.write_text(name, stream.getvalue())


def validate_generated_output(path: str | Path, fmt: str) -> tuple[str, int]:
    """Validate one written derived presentation file and return hash/size."""

    target = Path(path)
    if not target.is_file() or target.is_symlink():
        raise PresentationOutputError(f"Generated presentation output is missing or invalid: {target}")
    payload = target.read_bytes()
    if not payload:
        raise PresentationOutputError(f"Generated presentation output is empty: {target}")
    if fmt == "png" and not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise PresentationOutputError(f"Generated PNG signature is invalid: {target.name}")
    if fmt == "pdf" and not payload.startswith(b"%PDF"):
        raise PresentationOutputError(f"Generated PDF signature is invalid: {target.name}")
    if fmt not in {"png", "pdf"}:
        raise PresentationOutputError(f"Unsupported generated format: {fmt!r}")
    return sha256_file(target), int(target.stat().st_size)


def _payload_for_format(rendered: RenderedFigure, fmt: str) -> bytes:
    if fmt == "png":
        payload = rendered.png
        if not payload.startswith(b"\x89PNG\r\n\x1a\n"):
            raise PresentationOutputError("Renderer returned malformed PNG bytes")
        return payload
    if fmt == "pdf":
        payload = rendered.pdf
        if not payload.startswith(b"%PDF"):
            raise PresentationOutputError("Renderer returned malformed PDF bytes")
        return payload
    raise PresentationOutputError(f"Unsupported generated format: {fmt!r}")


def construct_manifest_record(
    *,
    spec: PresentationExportSpecificationContract,
    run: RunFamilyAuthority,
    source: SourceAuthority,
    bundle: ConfigurationBundle,
    generated_path: Path,
    fmt: str,
) -> ExportManifestRecord:
    generated_sha256, _ = validate_generated_output(generated_path, fmt)
    return ExportManifestRecord(
        export_id=spec.export_id,
        group=spec.group,
        renderer=spec.renderer_identity,
        run_identity=run.run_base,
        semantic_source_identity=source.source_identity,
        exact_source_path=source.project_relative_path,
        source_sha256=source.sha256,
        configuration_sha256=bundle.configuration_sha256,
        generated_path=generated_path.name,
        generated_sha256=generated_sha256,
        format=fmt,
        dimensions=_dimensions(bundle, spec),
        status="PASS",
    )


def _write_foundation_manifests(
    writer: PresentationOutputWriter,
    *,
    registry: PresentationExportRegistryContract,
    run: RunFamilyAuthority,
    source: SourceAuthority,
    geometry: GeometryAuthority,
    records: tuple[ExportManifestRecord, ...],
    extra_source_rows: tuple[dict[str, Any], ...] = (),
) -> None:
    export_payload = {
        "schema": "rp1-presentation-export-manifest-v1",
        "run_identity": run.run_base,
        "source_run_read_only": True,
        "status": "PASS",
        "exports": [record.as_dict() for record in records],
    }
    writer.write_json(registry.manifests.export_manifest, export_payload)

    source_rows: list[dict[str, Any]] = [
        {
            "identity": source.source_identity,
            "path": source.project_relative_path,
            "sha256": source.sha256,
            "size_bytes": source.size_bytes,
            "kind": "semantic_source",
        }
    ]
    for geometry_id, paths in geometry.members.items():
        for path, digest in zip(paths, geometry.hashes[geometry_id], strict=True):
            source_rows.append(
                {
                    "identity": geometry_id,
                    "path": path.relative_to(run.closeout_run.parents[2]).as_posix(),
                    "sha256": digest,
                    "size_bytes": int(path.stat().st_size),
                    "kind": "geometry_member",
                }
            )
    source_rows.extend(dict(row) for row in extra_source_rows)
    writer.write_csv(
        registry.manifests.source_inventory,
        source_rows,
        ("identity", "path", "sha256", "size_bytes", "kind"),
    )
    writer.write_csv(
        registry.manifests.output_inventory,
        (
            {
                "export_id": record.export_id,
                "format": record.format,
                "path": record.generated_path,
                "sha256": record.generated_sha256,
                "status": record.status,
            }
            for record in records
        ),
        ("export_id", "format", "path", "sha256", "status"),
    )


def export_one_presentation_figure(
    *,
    run_dir: str | Path,
    output_dir: str | Path,
    export_id: str,
    paths: ProjectPaths | None = None,
    renderer_registry: RendererRegistry | None = None,
) -> dict[str, Any]:
    """Export one configured presentation figure from an immutable completed run."""

    governed = paths or ProjectPaths.discover()
    bundle = load_configuration_bundle(governed.root / "config")
    registry = load_presentation_export_registry(bundle.figure)
    try:
        spec = registry.export_by_id(export_id)
    except KeyError as exc:
        raise PresentationExportError(f"Unknown configured presentation export: {export_id!r}") from exc

    run = resolve_run_family(run_dir, paths=governed, registry=registry, validate=True)
    validate_required_result_state(spec, run)
    source = resolve_source(spec, run, paths=governed)
    geometry = resolve_geometry_dependency(
        spec.geometry_dependency,
        paths=governed,
        bundle=bundle,
        registry=registry,
    )
    secondary_authority_rows = resolve_secondary_export_authority(spec, run, source, paths=governed)
    renderers = renderer_registry or build_core_renderer_registry()
    style = _presentation_style(bundle, spec)
    context = RenderContext(
        paths=governed,
        bundle=bundle,
        registry=registry,
        run=run,
        source=source,
        geometry=geometry,
        style=style,
    )

    destination = validate_output_destination(output_dir, run=run)
    destination.parent.mkdir(parents=True, exist_ok=True)
    before = snapshot_run_tree(run, project_root=governed.root)
    staging: Path | None = Path(tempfile.mkdtemp(prefix=f".{destination.name}.staging-", dir=destination.parent)).resolve()
    try:
        assert staging is not None
        writer = PresentationOutputWriter(staging)
        rendered = renderers.dispatch(spec.renderer_identity, source.frame, spec=spec, context=context)
        records: list[ExportManifestRecord] = []
        for fmt in spec.formats:
            name = deterministic_output_name(spec, fmt)
            path = writer.write_bytes(name, _payload_for_format(rendered, fmt))
            records.append(
                construct_manifest_record(
                    spec=spec,
                    run=run,
                    source=source,
                    bundle=bundle,
                    generated_path=path,
                    fmt=fmt,
                )
            )
        _write_foundation_manifests(
            writer,
            registry=registry,
            run=run,
            source=source,
            geometry=geometry,
            records=tuple(records),
            extra_source_rows=secondary_authority_rows,
        )
        after = snapshot_run_tree(run, project_root=governed.root)
        assert_run_tree_unchanged(before, after)
        if destination.exists():
            raise PresentationOutputError(f"Presentation output destination appeared during export: {destination}")
        os.replace(staging, destination)
        staging = None
    except Exception:
        if staging is not None and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        after = snapshot_run_tree(run, project_root=governed.root)
        assert_run_tree_unchanged(before, after)
        raise

    return {
        "schema": "rp1-presentation-export-report-v1",
        "status": "PASS",
        "run_identity": run.run_base,
        "export_id": spec.export_id,
        "group": spec.group,
        "renderer": spec.renderer_identity,
        "output_dir": str(destination),
        "outputs": [record.as_dict() for record in records],
        "source_run_unchanged": True,
    }


AGGREGATE_MANIFEST_NAME = "RP1_PRESENTATION_FIGURE_MANIFEST.json"
AGGREGATE_REPORT_NAME = "RP1_PRESENTATION_FIGURE_EXPORT_REPORT.md"
AGGREGATE_OUTPUT_INVENTORY_NAME = "RP1_PRESENTATION_FIGURE_OUTPUT_INVENTORY.csv"
AGGREGATE_MANIFEST_SCHEMA = "rp1-presentation-figure-manifest-v1"
AGGREGATE_REPORT_SCHEMA = "rp1-presentation-figure-export-report-v1"


def _relative_to_project(path: Path, *, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise PresentationOutputError(f"Authority path escapes project root: {path}") from exc


def _geometry_manifest_entries(
    geometry: GeometryAuthority, *, project_root: Path
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for geometry_id in sorted(geometry.members):
        members = geometry.members[geometry_id]
        hashes = geometry.hashes[geometry_id]
        for path, digest in zip(members, hashes, strict=True):
            entries.append(
                {
                    "identity": geometry_id,
                    "path": _relative_to_project(path, root=project_root),
                    "sha256": digest,
                    "size_bytes": int(path.stat().st_size),
                }
            )
    return entries


def _normalise_requested_formats(
    registry: PresentationExportRegistryContract,
    formats: Iterable[str] | None,
) -> tuple[str, ...] | None:
    if formats is None:
        return None
    requested = tuple(dict.fromkeys(str(fmt).strip().lower() for fmt in formats if str(fmt).strip()))
    if not requested:
        raise PresentationExportError("At least one output format must be supplied when --format is used")
    allowed = tuple(registry.output.formats)
    unsupported = tuple(fmt for fmt in requested if fmt not in allowed)
    if unsupported:
        raise PresentationExportError(
            "Unsupported presentation output format(s): "
            f"{', '.join(unsupported)}. Configured formats: {', '.join(allowed)}"
        )
    return requested


def _formats_for_spec(
    spec: PresentationExportSpecificationContract,
    requested: tuple[str, ...] | None,
) -> tuple[str, ...]:
    if requested is None:
        return tuple(spec.formats)
    unavailable = tuple(fmt for fmt in requested if fmt not in spec.formats)
    if unavailable:
        raise PresentationExportError(
            f"{spec.export_id} does not configure requested format(s): {', '.join(unavailable)}"
        )
    return requested


def _anticipated_source_path(spec: PresentationExportSpecificationContract, run: RunFamilyAuthority) -> str:
    try:
        return str(spec.source_path_pattern).format(run_base=run.run_base).replace("\\", "/")
    except Exception:
        return str(spec.source_path_pattern)


def _aggregate_record_base(
    *,
    spec: PresentationExportSpecificationContract,
    run: RunFamilyAuthority,
    bundle: ConfigurationBundle,
) -> dict[str, Any]:
    return {
        "export_id": spec.export_id,
        "group": spec.group,
        "renderer_identity": spec.renderer_identity,
        "run_identity": run.run_base,
        "analysis_schema": str(bundle.analysis.schema_version),
        "data_schema": str(bundle.data_schema.data_schema_version),
        "source_semantic_identity": spec.source_identity,
        "source_path": _anticipated_source_path(spec, run),
        "source_sha256": None,
        "geometry": [],
        "configuration_sha256": bundle.configuration_sha256,
        "scenario": spec.scenario,
        "result_state_requirement": spec.required_result_state,
        "observed_result_state": (
            run.validation.secondary_external_state
            if spec.required_result_state != "NONE"
            else "NOT_REQUIRED"
        ),
        "additional_source_authorities": [],
    }


def _aggregate_failure_record(
    *,
    base: Mapping[str, Any],
    error: Exception,
) -> dict[str, Any]:
    record = dict(base)
    record.update(
        {
            "output_path": None,
            "output_sha256": None,
            "output_format": None,
            "dimensions": None,
            "status": "FAIL",
            "error": f"{type(error).__name__}: {error}",
        }
    )
    return record


def _aggregate_success_record(
    *,
    base: Mapping[str, Any],
    output_path: Path,
    fmt: str,
    bundle: ConfigurationBundle,
    spec: PresentationExportSpecificationContract,
    staging_root: Path,
) -> dict[str, Any]:
    digest, _ = validate_generated_output(output_path, fmt)
    record = dict(base)
    record.update(
        {
            "output_path": output_path.relative_to(staging_root).as_posix(),
            "output_sha256": digest,
            "output_format": fmt,
            "dimensions": dict(_dimensions(bundle, spec)),
            "status": "PASS",
            "error": None,
        }
    )
    return record


def _human_export_report(
    *,
    manifest: Mapping[str, Any],
) -> str:
    summary = manifest["summary"]
    selection = manifest["selection"]
    lines = [
        "# RP1 Presentation Figure Export Report",
        "",
        f"- Schema: `{AGGREGATE_REPORT_SCHEMA}`",
        f"- Status: **{manifest['status']}**",
        f"- Source run identity: `{manifest['source_run']['run_identity']}`",
        f"- Analysis schema: `{manifest['analysis_schema']}`",
        f"- Data schema: `{manifest['data_schema']}`",
        f"- Selection mode: `{selection['mode']}`",
        f"- Selection value: `{selection['value']}`",
        f"- Requested formats: `{', '.join(selection['formats'])}`",
        f"- Requested exports: {summary['requested_exports']}",
        f"- Successful exports: {summary['successful_exports']}",
        f"- Failed exports: {summary['failed_exports']}",
        f"- Generated figure files: {summary['generated_figure_files']}",
        f"- Source run unchanged: `{str(manifest['source_run_read_only']).lower()}`",
        "",
        "## Export results",
        "",
        "| Export ID | Group | Status | Outputs | Error |",
        "|---|---|---|---:|---|",
    ]
    by_export: dict[str, list[Mapping[str, Any]]] = {}
    for record in manifest["records"]:
        by_export.setdefault(str(record["export_id"]), []).append(record)
    for export_id in manifest["requested_export_ids"]:
        rows = by_export[export_id]
        group = str(rows[0]["group"])
        failed = next((row for row in rows if row["status"] == "FAIL"), None)
        status = "FAIL" if failed is not None else "PASS"
        outputs = sum(row["status"] == "PASS" for row in rows)
        error = "" if failed is None else str(failed["error"]).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| `{export_id}` | `{group}` | {status} | {outputs} | {error} |")
    if summary["failed_exports"]:
        lines.extend(
            [
                "",
                "## Failure policy",
                "",
                "One or more requested exports failed. The command therefore has overall status FAIL and must return a non-zero exit code. Failed SaTScan-dependent exports are not interpreted as zero clusters.",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def _write_aggregate_output_inventory(staging: Path) -> None:
    rows: list[dict[str, Any]] = []
    for path in sorted(p for p in staging.rglob("*") if p.is_file()):
        if path.name == AGGREGATE_OUTPUT_INVENTORY_NAME:
            continue
        rel = path.relative_to(staging).as_posix()
        if rel == AGGREGATE_MANIFEST_NAME:
            kind = "aggregate_manifest"
        elif rel == AGGREGATE_REPORT_NAME:
            kind = "aggregate_report"
        else:
            kind = "figure_output"
        rows.append(
            {
                "path": rel,
                "sha256": sha256_file(path),
                "size_bytes": int(path.stat().st_size),
                "kind": kind,
            }
        )
    writer = PresentationOutputWriter(staging)
    writer.write_csv(
        AGGREGATE_OUTPUT_INVENTORY_NAME,
        rows,
        ("path", "sha256", "size_bytes", "kind"),
    )


def _validate_aggregate_estate(
    *,
    staging: Path,
    selected: tuple[PresentationExportSpecificationContract, ...],
    records: list[dict[str, Any]],
    overall_status: str,
) -> None:
    requested = {spec.export_id for spec in selected}
    represented = {str(record["export_id"]) for record in records}
    if represented != requested:
        raise PresentationOutputError(
            f"Aggregate manifest does not represent every requested export: requested={sorted(requested)!r}, represented={sorted(represented)!r}"
        )
    for record in records:
        if record["status"] == "PASS":
            rel = record["output_path"]
            if not rel:
                raise PresentationOutputError("PASS aggregate record is missing output_path")
            path = staging / str(rel)
            digest, _ = validate_generated_output(path, str(record["output_format"]))
            if digest != record["output_sha256"]:
                raise PresentationOutputError(f"Aggregate manifest output hash mismatch for {rel}")
        elif record["status"] == "FAIL":
            if not record["error"]:
                raise PresentationOutputError("FAIL aggregate record is missing its error message")
        else:
            raise PresentationOutputError(f"Unknown aggregate record status: {record['status']!r}")
    has_failure = any(record["status"] == "FAIL" for record in records)
    if (overall_status == "PASS") == has_failure:
        raise PresentationOutputError("Aggregate status is inconsistent with export-record failures")
    required_metadata = {
        AGGREGATE_MANIFEST_NAME,
        AGGREGATE_REPORT_NAME,
        AGGREGATE_OUTPUT_INVENTORY_NAME,
    }
    present_metadata = {path.name for path in staging.iterdir() if path.is_file()}
    missing = required_metadata.difference(present_metadata)
    if missing:
        raise PresentationOutputError(f"Aggregate export is missing metadata files: {sorted(missing)!r}")


def export_presentation_figure_estate(
    *,
    run_dir: str | Path,
    output_dir: str | Path,
    export_id: str | None = None,
    group: str | None = None,
    all_exports: bool = False,
    formats: Iterable[str] | None = None,
    paths: ProjectPaths | None = None,
    renderer_registry: RendererRegistry | None = None,
) -> dict[str, Any]:
    """Export a configured selection into one deterministic presentation estate.

    The completed source run is immutable. Individual requested exports are
    transactionally staged; failures are recorded explicitly in the aggregate
    manifest/report, while the overall status becomes FAIL. The function never
    substitutes absent SaTScan results with zero-cluster graphics.
    """

    governed = paths or ProjectPaths.discover()
    bundle = load_configuration_bundle(governed.root / "config")
    registry = load_presentation_export_registry(bundle.figure)
    selected = select_presentation_exports(
        registry=registry, export_id=export_id, group=group, all_exports=all_exports
    )
    requested_formats = _normalise_requested_formats(registry, formats)
    run = resolve_run_family(run_dir, paths=governed, registry=registry, validate=True)
    destination = validate_output_destination(output_dir, run=run)
    destination.parent.mkdir(parents=True, exist_ok=True)
    before = snapshot_run_tree(run, project_root=governed.root)
    renderers = renderer_registry or build_core_renderer_registry()

    staging: Path | None = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.staging-", dir=destination.parent)
    ).resolve()
    records: list[dict[str, Any]] = []
    per_export_status: dict[str, str] = {}
    try:
        assert staging is not None
        for spec in selected:
            (staging / spec.group).mkdir(parents=True, exist_ok=True)
            base = _aggregate_record_base(spec=spec, run=run, bundle=bundle)
            export_staging = staging / ".export-staging" / spec.export_id
            try:
                validate_required_result_state(spec, run)
                source = resolve_source(spec, run, paths=governed)
                base["source_semantic_identity"] = source.source_identity
                base["source_path"] = source.project_relative_path
                base["source_sha256"] = source.sha256
                geometry = resolve_geometry_dependency(
                    spec.geometry_dependency,
                    paths=governed,
                    bundle=bundle,
                    registry=registry,
                )
                base["geometry"] = _geometry_manifest_entries(
                    geometry, project_root=governed.root
                )
                secondary_rows = resolve_secondary_export_authority(
                    spec, run, source, paths=governed
                )
                base["additional_source_authorities"] = [dict(row) for row in secondary_rows]
                style = _presentation_style(bundle, spec)
                context = RenderContext(
                    paths=governed,
                    bundle=bundle,
                    registry=registry,
                    run=run,
                    source=source,
                    geometry=geometry,
                    style=style,
                )
                rendered = renderers.dispatch(
                    spec.renderer_identity, source.frame, spec=spec, context=context
                )
                export_staging.mkdir(parents=True, exist_ok=False)
                export_writer = PresentationOutputWriter(export_staging)
                local_paths: list[tuple[str, Path]] = []
                for fmt in _formats_for_spec(spec, requested_formats):
                    name = deterministic_output_name(spec, fmt)
                    path = export_writer.write_bytes(name, _payload_for_format(rendered, fmt))
                    validate_generated_output(path, fmt)
                    local_paths.append((fmt, path))
                for fmt, local_path in local_paths:
                    final_path = staging / spec.group / local_path.name
                    if final_path.exists():
                        raise PresentationOutputError(f"Aggregate output collision: {final_path.relative_to(staging)}")
                    os.replace(local_path, final_path)
                    records.append(
                        _aggregate_success_record(
                            base=base,
                            output_path=final_path,
                            fmt=fmt,
                            bundle=bundle,
                            spec=spec,
                            staging_root=staging,
                        )
                    )
                per_export_status[spec.export_id] = "PASS"
            except Exception as exc:
                records.append(_aggregate_failure_record(base=base, error=exc))
                per_export_status[spec.export_id] = "FAIL"
            finally:
                if export_staging.exists():
                    shutil.rmtree(export_staging, ignore_errors=True)
        transient = staging / ".export-staging"
        if transient.exists():
            shutil.rmtree(transient, ignore_errors=True)

        after = snapshot_run_tree(run, project_root=governed.root)
        assert_run_tree_unchanged(before, after)
        successful_exports = sum(status == "PASS" for status in per_export_status.values())
        failed_exports = sum(status == "FAIL" for status in per_export_status.values())
        overall_status = "PASS" if failed_exports == 0 else "FAIL"
        selection_mode = "all" if all_exports else ("group" if group is not None else "figure")
        selection_value: str | None = None if all_exports else (group if group is not None else export_id)
        effective_formats = (
            tuple(registry.output.formats) if requested_formats is None else requested_formats
        )
        manifest: dict[str, Any] = {
            "schema": AGGREGATE_MANIFEST_SCHEMA,
            "status": overall_status,
            "source_run": {
                "run_identity": run.run_base,
                "publication_run": _relative_to_project(run.publication_run, root=governed.root),
                "secondary_run": _relative_to_project(run.secondary_run, root=governed.root),
                "closeout_run": _relative_to_project(run.closeout_run, root=governed.root),
                "validation_status": run.validation.status,
                "secondary_external_state": run.validation.secondary_external_state,
            },
            "source_run_read_only": True,
            "analysis_schema": str(bundle.analysis.schema_version),
            "data_schema": str(bundle.data_schema.data_schema_version),
            "configuration_sha256": bundle.configuration_sha256,
            "selection": {
                "mode": selection_mode,
                "value": selection_value,
                "formats": list(effective_formats),
            },
            "requested_export_ids": [spec.export_id for spec in selected],
            "summary": {
                "requested_exports": len(selected),
                "successful_exports": successful_exports,
                "failed_exports": failed_exports,
                "generated_figure_files": sum(record["status"] == "PASS" for record in records),
            },
            "records": records,
        }
        root_writer = PresentationOutputWriter(staging)
        root_writer.write_json(AGGREGATE_MANIFEST_NAME, manifest)
        root_writer.write_text(AGGREGATE_REPORT_NAME, _human_export_report(manifest=manifest))
        _write_aggregate_output_inventory(staging)
        _validate_aggregate_estate(
            staging=staging, selected=selected, records=records, overall_status=overall_status
        )
        if destination.exists():
            raise PresentationOutputError(
                f"Presentation output destination appeared during export: {destination}"
            )
        os.replace(staging, destination)
        staging = None
    except Exception:
        if staging is not None and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        after = snapshot_run_tree(run, project_root=governed.root)
        assert_run_tree_unchanged(before, after)
        raise

    return {
        "schema": AGGREGATE_REPORT_SCHEMA,
        "status": overall_status,
        "run_identity": run.run_base,
        "selection": manifest["selection"],
        "requested_exports": len(selected),
        "successful_exports": successful_exports,
        "failed_exports": failed_exports,
        "generated_figure_files": manifest["summary"]["generated_figure_files"],
        "output_dir": str(destination),
        "manifest": str(destination / AGGREGATE_MANIFEST_NAME),
        "report": str(destination / AGGREGATE_REPORT_NAME),
        "source_run_unchanged": True,
    }


def select_presentation_exports(
    *,
    registry: PresentationExportRegistryContract,
    export_id: str | None = None,
    group: str | None = None,
    all_exports: bool = False,
) -> tuple[PresentationExportSpecificationContract, ...]:
    """Resolve one mutually exclusive operational selection deterministically."""

    selected_modes = int(export_id is not None) + int(group is not None) + int(all_exports)
    if selected_modes != 1:
        raise PresentationExportError("Select exactly one of export_id, group or all_exports")
    if all_exports:
        return registry.exports
    if group is not None:
        try:
            return registry.exports_for_group(group)
        except KeyError as exc:
            raise PresentationExportError(
                f"Unknown presentation export group: {group!r}. Valid groups: {', '.join(registry.groups)}"
            ) from exc
    assert export_id is not None
    try:
        return (registry.export_by_id(export_id),)
    except KeyError as exc:
        raise PresentationExportError(
            f"Unknown configured presentation export: {export_id!r}. Valid export IDs: {', '.join(registry.export_ids)}"
        ) from exc


def list_presentation_exports(
    *,
    paths: ProjectPaths | None = None,
    renderer_registry: RendererRegistry | None = None,
) -> tuple[dict[str, Any], ...]:
    governed = paths or ProjectPaths.discover()
    registry = load_presentation_export_registry(paths=governed)
    implemented = set((renderer_registry or build_core_renderer_registry()).identities)
    return tuple(
        {
            "export_id": spec.export_id,
            "group": spec.group,
            "label": spec.label,
            "renderer": spec.renderer_identity,
            "implementation_status": "IMPLEMENTED" if spec.renderer_identity in implemented else "NOT_YET_IMPLEMENTED",
        }
        for spec in registry.exports
    )
