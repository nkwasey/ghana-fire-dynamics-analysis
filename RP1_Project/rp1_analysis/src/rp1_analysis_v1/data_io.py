"""Governed, data-schema-driven loading of panels and spatial authorities."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from .config import load_configuration_bundle
from .contracts import DataSchemaContract, GeometrySpecification, PanelSpecification
from .paths import ProjectPaths


class DataLoadError(RuntimeError):
    """Raised when a governed analytical authority cannot be loaded exactly."""


@dataclass(frozen=True, slots=True)
class DataAuthorities:
    acz_panel: pd.DataFrame
    district_panel: pd.DataFrame
    key_audit: pd.DataFrame
    manifest: dict[str, Any]
    merge_summary: dict[str, Any]
    acz_geometry: gpd.GeoDataFrame
    district_geometry: gpd.GeoDataFrame
    district_to_acz_crosswalk: pd.DataFrame
    district_to_acz_crosswalk_provenance: dict[str, Any]


def _schema(paths: ProjectPaths, schema: DataSchemaContract | None) -> DataSchemaContract:
    return schema or load_configuration_bundle(paths.root / "config").data_schema


def _load_panel(path: Path, panel: PanelSpecification, schema: DataSchemaContract) -> pd.DataFrame:
    if not path.is_file():
        raise DataLoadError(f"Missing governed panel: {path}")
    try:
        header = pd.read_csv(path, nrows=0).columns.tolist()
        if header != list(schema.field_order):
            raise DataLoadError(
                f"Panel header does not equal data-schema field order: {path.name}"
            )
        string_dtypes = {field.name: "string" for field in schema.fields if field.dtype == "string"}
        frame = pd.read_csv(path, dtype=string_dtypes, low_memory=False)
    except DataLoadError:
        raise
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        raise DataLoadError(f"Unable to load governed panel {path.name}: {exc}") from exc
    if list(frame.columns) != list(schema.field_order):
        raise DataLoadError(f"Loaded panel column order changed unexpectedly: {path.name}")
    return frame


def load_acz_panel(paths: ProjectPaths, schema: DataSchemaContract | None = None) -> pd.DataFrame:
    ds = _schema(paths, schema)
    panel = ds.panel("acz_monthly")
    return _load_panel(paths.resolve_inside(panel.path), panel, ds)


def load_district_panel(paths: ProjectPaths, schema: DataSchemaContract | None = None) -> pd.DataFrame:
    ds = _schema(paths, schema)
    panel = ds.panel("district_monthly")
    return _load_panel(paths.resolve_inside(panel.path), panel, ds)


def _aux_path(paths: ProjectPaths, schema: DataSchemaContract, key: str) -> Path:
    try:
        raw = schema.auxiliary_inputs[key]
        relative = raw["path"]
    except (KeyError, TypeError) as exc:
        raise DataLoadError(f"Missing auxiliary-input schema for {key!r}") from exc
    if not isinstance(relative, str):
        raise DataLoadError(f"Invalid auxiliary-input path for {key!r}")
    return paths.resolve_inside(relative)


def load_key_audit(paths: ProjectPaths, schema: DataSchemaContract | None = None) -> pd.DataFrame:
    ds = _schema(paths, schema)
    path = _aux_path(paths, ds, "key_audit")
    try:
        return pd.read_csv(path, low_memory=False)
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        raise DataLoadError(f"Unable to load key audit {path.name}: {exc}") from exc


def _load_json_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise DataLoadError(f"Missing governed JSON authority: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataLoadError(f"Unable to load governed JSON {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise DataLoadError(f"Governed JSON must contain an object: {path.name}")
    return value


def load_manifest(paths: ProjectPaths, schema: DataSchemaContract | None = None) -> dict[str, Any]:
    ds = _schema(paths, schema)
    return _load_json_mapping(_aux_path(paths, ds, "panel_manifest"))


def load_merge_summary(paths: ProjectPaths, schema: DataSchemaContract | None = None) -> dict[str, Any]:
    ds = _schema(paths, schema)
    return _load_json_mapping(_aux_path(paths, ds, "merge_summary"))


def _load_geometry(paths: ProjectPaths, spec: GeometrySpecification) -> gpd.GeoDataFrame:
    missing = [member for member in spec.required_members if not paths.resolve_inside(member).is_file()]
    if missing:
        raise DataLoadError(
            f"Governed geometry {spec.geometry_id!r} is missing required shapefile members: {missing!r}"
        )
    path = paths.resolve_inside(spec.path)
    if not path.is_file():
        raise DataLoadError(f"Missing governed geometry: {path}")
    try:
        return gpd.read_file(path)
    except Exception as exc:
        raise DataLoadError(f"Unable to load governed geometry {path.name}: {exc}") from exc


def load_acz_geometry(paths: ProjectPaths, schema: DataSchemaContract | None = None) -> gpd.GeoDataFrame:
    ds = _schema(paths, schema)
    return _load_geometry(paths, ds.geometry("acz"))


def load_district_geometry(paths: ProjectPaths, schema: DataSchemaContract | None = None) -> gpd.GeoDataFrame:
    ds = _schema(paths, schema)
    return _load_geometry(paths, ds.geometry("district"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_district_to_acz_crosswalk(
    paths: ProjectPaths, schema: DataSchemaContract | None = None
) -> pd.DataFrame:
    """Load and structurally validate the governed original-geometry crosswalk."""

    ds = _schema(paths, schema)
    path = _aux_path(paths, ds, "district_to_acz_crosswalk")
    try:
        frame = pd.read_csv(path, low_memory=False)
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        raise DataLoadError(f"Unable to load governed district-to-ACZ crosswalk {path.name}: {exc}") from exc
    required = {
        "district_id", "zone_id", "zone_code", "zone_name",
        "original_district_area_sq_km", "dominant_overlap_area_sq_km",
        "dominant_overlap_share", "assignment_method", "working_crs",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise DataLoadError(f"Governed district-to-ACZ crosswalk is missing fields: {missing!r}")
    if frame["district_id"].isna().any() or frame["district_id"].astype(str).duplicated().any():
        raise DataLoadError("Governed district-to-ACZ crosswalk district IDs must be unique and non-missing")
    share = pd.to_numeric(frame["dominant_overlap_share"], errors="coerce")
    if share.isna().any() or (~share.between(0.0, 1.0, inclusive="both")).any():
        raise DataLoadError("Governed dominant overlap shares must lie in [0,1]")
    return frame


def load_district_to_acz_crosswalk_provenance(
    paths: ProjectPaths, schema: DataSchemaContract | None = None
) -> dict[str, Any]:
    """Load crosswalk provenance and bind it cryptographically to the governed CSV."""

    ds = _schema(paths, schema)
    provenance = _load_json_mapping(_aux_path(paths, ds, "district_to_acz_crosswalk_provenance"))
    crosswalk_path = _aux_path(paths, ds, "district_to_acz_crosswalk")
    try:
        expected = str(provenance["crosswalk"]["sha256"])
    except (KeyError, TypeError) as exc:
        raise DataLoadError("Crosswalk provenance does not declare crosswalk.sha256") from exc
    actual = _sha256_file(crosswalk_path)
    if actual != expected:
        raise DataLoadError(
            f"Governed district-to-ACZ crosswalk SHA-256 mismatch: expected {expected}, got {actual}"
        )
    return provenance


def load_data_authorities(paths: ProjectPaths | None = None, schema: DataSchemaContract | None = None) -> DataAuthorities:
    governed = paths or ProjectPaths.discover()
    ds = _schema(governed, schema)
    return DataAuthorities(
        acz_panel=load_acz_panel(governed, ds),
        district_panel=load_district_panel(governed, ds),
        key_audit=load_key_audit(governed, ds),
        manifest=load_manifest(governed, ds),
        merge_summary=load_merge_summary(governed, ds),
        acz_geometry=load_acz_geometry(governed, ds),
        district_geometry=load_district_geometry(governed, ds),
        district_to_acz_crosswalk=load_district_to_acz_crosswalk(governed, ds),
        district_to_acz_crosswalk_provenance=load_district_to_acz_crosswalk_provenance(governed, ds),
    )
