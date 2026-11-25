"""Validate the study geography and stage any missing inputs from an authorised local copy."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
GEO_DATA = "geo_data_prep/data"
ARCHIVE_GEO = "RP1_Project/rp1_firms_archive/data/reference/geography"
ARCHIVE_NAMES = {"acz.geojson", "districts.geojson", "ghana.geojson", "units.json"}


def _safe_path(root: Path, name: str) -> Path:
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != name or any(
        char in name for char in ("\\", ":")
    ):
        raise ValueError(f"Invalid geography inventory path: {name}")
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink() or path.is_junction():
            raise ValueError(f"Linked geography paths are unsupported: {name}")
    return path


def _check(data: bytes, name: str, expected: str, size: int | None = None) -> None:
    if (size is not None and len(data) != size) or hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"Geography input differs from its inventory: {name}")


def _expected(root: Path, *, include_ecological: bool) -> dict[str, tuple[str, int | None]]:
    source = json.loads(_safe_path(root, f"{GEO_DATA}/inputs_manifest.json").read_text(encoding="utf-8"))
    records = {}
    for row in source["files"]:
        name = row["path"]
        if not name.startswith("raw/") or f"{GEO_DATA}/{name}" in records:
            raise ValueError(f"Unexpected or duplicate source geography path: {name}")
        if include_ecological or not name.startswith("raw/zones/Agro_ecological_zone."):
            records[f"{GEO_DATA}/{name}"] = (row["sha256"], row["bytes"])
    checksum_path = _safe_path(root, f"{ARCHIVE_GEO}/checksums.sha256")
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        digest, name = line.split()
        relative = f"{ARCHIVE_GEO}/{name}"
        if name == "geography-manifest.json":
            _check(_safe_path(root, relative).read_bytes(), relative, digest)
        elif name in ARCHIVE_NAMES and relative not in records:
            records[relative] = (digest, None)
        else:
            raise ValueError(f"Unexpected or duplicate Archive geography path: {name}")
    if not all(f"{ARCHIVE_GEO}/{name}" in records for name in ARCHIVE_NAMES):
        raise ValueError("Incomplete Archive geography checksum inventory")
    return records


def admit(
    source_root: Path, destination_root: Path, *, verify_only: bool = False,
    include_ecological: bool = False,
) -> dict:
    source_root = source_root.resolve()
    destination_root = destination_root.resolve()
    to_copy = {}
    records = _expected(destination_root, include_ecological=include_ecological)
    for name, (digest, size) in records.items():
        destination = _safe_path(destination_root, name)
        if destination.exists():
            if not destination.is_file():
                raise ValueError(f"Destination geography path is not a file: {name}")
            _check(destination.read_bytes(), name, digest, size)
            continue
        source = _safe_path(source_root, name)
        if not source.is_file():
            raise ValueError(f"Missing source geography file: {name}")
        data = source.read_bytes()
        _check(data, name, digest, size)
        if not verify_only:
            to_copy[destination] = data

    created = []
    try:
        for destination, data in to_copy.items():
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                created.append(destination)
                stream.write(data)
    except OSError:
        for destination in reversed(created):
            destination.unlink()
        raise
    return {"status": "PASS", "verified_files": len(records), "copied_files": len(created)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True, help="local copy with the repository input paths")
    parser.add_argument("--verify-only", action="store_true", help="check the available inputs without copying files")
    parser.add_argument("--include-ecological", action="store_true", help="also admit the optional agro-ecological zones")
    args = parser.parse_args()
    try:
        result = admit(args.source_root, ROOT, verify_only=args.verify_only,
                       include_ecological=args.include_ecological)
        print(json.dumps(result, indent=2))
    except (KeyError, OSError, ValueError) as exc:
        parser.exit(2, f"Source geography admission failed: {exc}\n")


if __name__ == "__main__":
    main()
