#!/usr/bin/env python3
"""Regenerate RP1 governed path provenance and dependent input hashes.

This operation is intentionally metadata-only. It preserves scientific input bytes,
records source/original locations as ``origin_path``, records current release locations
as ``staged_path``, and rebuilds the exact staged-input hash inventory.
In a portable checkout, ``--check`` verifies the staged inputs and retains the
recorded producer geography identity if the producer handoff is absent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from rp1_analysis_v1.provenance_paths import valid_origin_path


PANEL_PROVENANCE_SCHEMA = "rp1-fire-panel-provenance-v2"
INPUT_PROVENANCE_SCHEMA = "rp1-input-provenance-v2"

PANEL_PATH_SEMANTICS = {
    "origin_path": (
        "Repository-relative source/original provenance path. It may refer to a historical "
        "or upstream intermediate location that is not distributed with the release."
    ),
    "staged_path": (
        "Repository-relative current durable location in the distributed repository; null only "
        "for upstream intermediate sources that are intentionally not distributed."
    ),
}

INPUT_PATH_SEMANTICS = {
    "origin_path": (
        "Repository-relative source/original path from which the governed input was staged; "
        "provenance only and never resolved as a runtime dependency."
    ),
    "staged_path": (
        "Path relative to RP1_Project/rp1_analysis used for runtime access in the release; "
        "it must resolve to a governed file inside that subproject."
    ),
}

CANONICAL_ANALYSIS_PREFIX = "RP1_Project/rp1_analysis/data/raw/"
GEOGRAPHY_HANDOFF_PATH = "RP1_Project/geo_handoff_manifest.json"
GEOGRAPHY_HANDOFF_NOTE = (
    "Geometry inventory origins identify staged files; source-run evidence is in this handoff manifest."
)


def _stable_json(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _valid_relative(path: str) -> bool:
    candidate = PurePosixPath(path)
    return bool(path) and not candidate.is_absolute() and ".." not in candidate.parts


def _require_relative(path: str, *, label: str) -> str:
    if not isinstance(path, str) or not _valid_relative(path):
        raise ValueError(f"{label} must be a non-empty relative POSIX path: {path!r}")
    return path


def _origin_path(record: dict[str, Any], *, label: str, allow_external: bool = False) -> str:
    origin = record.get("origin_path")
    if not isinstance(origin, str):
        raise ValueError(f"{label} lacks required origin_path: {record!r}")
    if allow_external:
        if not valid_origin_path(origin):
            raise ValueError(f"{label} origin_path is invalid: {origin!r}")
        return origin
    return _require_relative(origin, label=f"{label} origin_path")


def normalise_panel_manifest(manifest: dict[str, Any], *, repo_root: Path) -> dict[str, Any]:
    """Return an idempotently normalised fire-panel provenance manifest."""
    normalised = json.loads(json.dumps(manifest))

    # Preserve the original data-generation timestamp. This is a release metadata
    # operation and must not overwrite the recorded generation time with a volatile value.
    normalised["provenance_schema_version"] = PANEL_PROVENANCE_SCHEMA
    normalised["path_semantics"] = dict(PANEL_PATH_SEMANTICS)
    if isinstance(normalised.get("outputs"), dict) and any(isinstance(r, dict) and isinstance(r.get("origin_path"), str) and
           (PurePosixPath(r["origin_path"]).is_absolute() or PureWindowsPath(r["origin_path"]).is_absolute())
           for r in normalised.get("outputs", {}).values()):
        normalised["path_semantics"]["origin_path"] = (
            "Repository-relative or host-specific absolute external source/original provenance path; "
            "provenance only and never resolved as a runtime dependency."
        )

    source_roots = normalised.get("source_roots")
    if not isinstance(source_roots, dict):
        raise ValueError("Current fire-panel provenance requires source_roots")
    for name, record in source_roots.items():
        if not isinstance(record, dict):
            raise ValueError(f"source_roots[{name!r}] must be an object")
        _origin_path(record, label=f"source_roots[{name!r}]")
        staged = record.get("staged_path")
        if staged is not None:
            _require_relative(staged, label=f"source_roots[{name!r}] staged_path")

    for family in normalised.get("families", []):
        if not isinstance(family, dict):
            raise ValueError("Manifest family must be an object")
        root_record = family.get("root")
        if not isinstance(root_record, dict):
            raise ValueError("Manifest family requires current root provenance object")
        _origin_path(root_record, label="family root")
        root_staged = root_record.get("staged_path")
        if root_staged is not None:
            _require_relative(root_staged, label="family root staged_path")
        for record in family.get("files", []):
            if not isinstance(record, dict):
                raise ValueError("Manifest family file record must be an object")
            origin = _origin_path(record, label="family file")
            if "staged_path" not in record:
                raise ValueError("Manifest family file requires staged_path")
            staged = record.get("staged_path")
            record["origin_path"] = origin
            record["staged_path"] = staged
            if staged is not None:
                _require_relative(staged, label="family staged_path")

    outputs = normalised.get("outputs")
    if not isinstance(outputs, dict):
        raise ValueError("Manifest outputs must be an object")
    for name, record in outputs.items():
        if not isinstance(record, dict):
            raise ValueError(f"Manifest output {name!r} must be an object")
        origin = _origin_path(record, label=f"output {name}", allow_external=True)
        filename = PurePosixPath(origin).name
        canonical = f"{CANONICAL_ANALYSIS_PREFIX}{filename}"
        if not (repo_root / PurePosixPath(canonical)).is_file():
            raise FileNotFoundError(f"Current staged output missing: {canonical}")
        record["origin_path"] = origin
        record["staged_path"] = canonical
        # Preserve hashes of immutable output files. The manifest cannot self-hash.
        if name != "manifest":
            observed = _sha256(repo_root / PurePosixPath(canonical))
            existing = record.get("sha256")
            if existing is not None and existing != observed:
                raise ValueError(
                    f"Scientific/metadata output hash changed unexpectedly for {name}: "
                    f"expected={existing} observed={observed}"
                )
            record["sha256"] = observed
        else:
            record.pop("sha256", None)

    return normalised


def _origin_for_inventory_entry(staged_path: str, *, panel_manifest: dict[str, Any]) -> str:
    """Recover a grounded origin path for a governed staged input."""
    if staged_path.startswith("data/raw/"):
        filename = PurePosixPath(staged_path).name
        outputs = panel_manifest.get("outputs", {})
        for record in outputs.values():
            if (
                isinstance(record, dict)
                and PurePosixPath(str(record.get("staged_path", ""))).name == filename
            ):
                origin = record.get("origin_path")
                if isinstance(origin, str):
                    return origin
        raise ValueError(f"No manifest origin found for staged raw input: {staged_path}")
    if staged_path.startswith("data/geo/"):
        return "RP1_Project/rp1_analysis/" + staged_path
    if staged_path.startswith("data/reference/"):
        return "RP1_Project/rp1_analysis/" + staged_path
    raise ValueError(f"No grounded origin rule for governed input: {staged_path}")


def rebuild_input_inventory(
    inventory: dict[str, Any], *, subproject_root: Path, panel_manifest: dict[str, Any]
) -> dict[str, Any]:
    """Rebuild exact staged-input hashes and explicit path provenance."""
    from rp1_analysis_v1.config import governed_input_paths, load_configuration_bundle

    bundle = load_configuration_bundle(subproject_root / "config")
    analysis_schema = bundle.analysis.schema_version
    if inventory.get("schema_version") != analysis_schema:
        raise ValueError("Unexpected input inventory schema_version")
    files = inventory.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("Input inventory files must be a non-empty list")
    supplied = [record.get('staged_path') if isinstance(record, dict) else None for record in files]
    if (not all(isinstance(path, str) for path in supplied)
            or len(supplied) != len(set(supplied))
            or set(supplied) != set(governed_input_paths(bundle.data_schema))):
        raise ValueError('Input inventory does not equal the exact configured c3 input set')

    rebuilt: list[dict[str, Any]] = []
    for record in files:
        if not isinstance(record, dict):
            raise ValueError("Input inventory record must be an object")
        staged = record.get("staged_path")
        if not isinstance(staged, str):
            raise ValueError(f"Input inventory entry lacks required staged_path: {record!r}")
        _require_relative(staged, label="input staged_path")
        target = (subproject_root / PurePosixPath(staged)).resolve()
        try:
            target.relative_to(subproject_root.resolve())
        except ValueError as exc:
            raise ValueError(f"Input staged_path escapes subproject: {staged}") from exc
        if not target.is_file():
            raise FileNotFoundError(f"Governed staged input missing: {staged}")
        origin = record.get("origin_path")
        if not isinstance(origin, str):
            raise ValueError(f"Input inventory entry lacks required origin_path: {record!r}")
        if not valid_origin_path(origin):
            raise ValueError(f"input origin_path is invalid: {origin!r}")
        expected_origin = _origin_for_inventory_entry(staged, panel_manifest=panel_manifest)
        if origin != expected_origin:
            raise ValueError(
                f"Input origin_path disagrees with governed provenance for {staged}: "
                f"expected={expected_origin!r} observed={origin!r}"
            )
        rebuilt.append(
            {
                "origin_path": origin,
                "staged_path": staged,
                "sha256": _sha256(target),
                "size_bytes": target.stat().st_size,
            }
        )

    return {
        "schema_version": inventory["schema_version"],
        "provenance_schema_version": INPUT_PROVENANCE_SCHEMA,
        "path_semantics": {
            **INPUT_PATH_SEMANTICS,
            "origin_path": ("Repository-relative or host-specific absolute external source/original path; "
                            "provenance only and never resolved as a runtime dependency.")
            if any(PurePosixPath(r["origin_path"]).is_absolute() or PureWindowsPath(r["origin_path"]).is_absolute() for r in rebuilt)
            else INPUT_PATH_SEMANTICS["origin_path"],
        },
        "files": rebuilt,
    }


def _discover_subproject(start: Path) -> Path:
    candidate = start.resolve()
    for parent in (candidate, *candidate.parents):
        if (parent / "config/analysis_contract.yml").is_file() and (
            parent / "data/raw/fire_panel_manifest.json"
        ).is_file():
            return parent
    raise RuntimeError("Unable to discover RP1 analysis subproject")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subproject-root", type=Path, default=None)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify staged provenance and hash any producer geography handoff available locally.",
    )
    args = parser.parse_args()

    subproject = (
        args.subproject_root.expanduser().resolve()
        if args.subproject_root is not None
        else _discover_subproject(Path(__file__))
    )
    from rp1_analysis_v1.config import governed_input_paths, load_configuration_bundle

    bundle = load_configuration_bundle(subproject / "config")
    repo_root = subproject.parents[1]
    manifest_path = subproject / str(bundle.data_schema.auxiliary_inputs["panel_manifest"]["path"])
    inventory_path = subproject / str(bundle.data_schema.provenance["inventory_path"])

    current_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    normalised_manifest = normalise_panel_manifest(current_manifest, repo_root=repo_root)
    manifest_text = _stable_json(normalised_manifest)

    # The input inventory hashes the regenerated manifest, so derive its bytes first.
    if args.check and manifest_path.read_text(encoding="utf-8") != manifest_text:
        raise RuntimeError("fire_panel_manifest.json is not in regenerated canonical form")

    if inventory_path.is_file():
        current_inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    else:
        if args.check:
            raise FileNotFoundError("No generated input inventory exists; prepare analysis inputs first")
        relative_files = set(governed_input_paths(bundle.data_schema))
        current_inventory = {"schema_version": bundle.analysis.schema_version,
            "files": [{"staged_path": rel,
                "origin_path": _origin_for_inventory_entry(rel, panel_manifest=normalised_manifest)}
                for rel in sorted(relative_files)]}

    rebuilt_inventory = rebuild_input_inventory(
        current_inventory,
        subproject_root=subproject,
        panel_manifest=normalised_manifest,
    )
    # Hash the verified bytes about to be published, without mutating the
    # manifest before inventory/geography admission has completed.
    for record in rebuilt_inventory['files']:
        if record['staged_path'] == str(bundle.data_schema.auxiliary_inputs['panel_manifest']['path']):
            encoded = manifest_text.encode('utf-8')
            record['sha256'] = hashlib.sha256(encoded).hexdigest()
            record['size_bytes'] = len(encoded)
    geo_handoff = repo_root / GEOGRAPHY_HANDOFF_PATH
    if geo_handoff.is_file():
        geography_hash = _sha256(geo_handoff)
        geography_verification = "VERIFIED_FILE"
    elif args.check and not geo_handoff.exists():
        recorded = current_inventory.get("geography_handoff")
        geography_hash = recorded.get("sha256") if isinstance(recorded, dict) else None
        if (
            not isinstance(geography_hash, str)
            or len(geography_hash) != 64
            or any(char not in "0123456789abcdef" for char in geography_hash)
        ):
            raise ValueError("Portable input inventory lacks a valid producer geography handoff hash")
        geography_verification = "RECORDED_IDENTITY_ONLY"
    else:
        raise FileNotFoundError("Generated geography handoff manifest is required")
    rebuilt_inventory["geography_handoff"] = {
        "path": GEOGRAPHY_HANDOFF_PATH,
        "sha256": geography_hash,
        "note": GEOGRAPHY_HANDOFF_NOTE,
    }
    inventory_text = _stable_json(rebuilt_inventory)
    if not args.check:
        manifest_path.write_text(manifest_text, encoding="utf-8", newline="\n")
        inventory_path.write_text(inventory_text, encoding="utf-8", newline="\n")
    elif inventory_path.read_text(encoding="utf-8") != inventory_text:
        raise RuntimeError("input_sha256.json is not in regenerated canonical form")

    print(f"PANEL_PROVENANCE_SCHEMA={PANEL_PROVENANCE_SCHEMA}")
    print(f"INPUT_PROVENANCE_SCHEMA={INPUT_PROVENANCE_SCHEMA}")
    print(f"GOVERNED_INPUT_FILES={len(rebuilt_inventory['files'])}")
    print(f"GEOGRAPHY_HANDOFF_VERIFICATION={geography_verification}")
    print(f"FIRE_PANEL_MANIFEST_SHA256={_sha256(manifest_path)}")
    print(f"INPUT_INVENTORY_SHA256={_sha256(inventory_path)}")
    print("RP1_DATA_PROVENANCE_REGENERATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
