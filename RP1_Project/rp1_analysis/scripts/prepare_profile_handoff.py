#!/usr/bin/env python3
"""Create a verified analysis-input staging bundle for Stage 5."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path

from rp1_analysis_v1.ba_support import profile_output_filenames, validate_c3_manifest, validate_profile_output_hashes


def prepare(source: Path, destination: Path) -> None:
    source = source.resolve()
    destination = destination.resolve()
    if destination.exists():
        raise ValueError("Destination must not exist; existing inputs are never overwritten")
    manifest_path = source / "fire_panel_manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    validate_c3_manifest(manifest)
    if manifest.get('ba_bundle', {}).get('scope') != 'full':
        raise ValueError('Pilot c3 bundles cannot stage full analysis inputs')
    # The hash checker operates on its fixed data/raw layout. Copy first to a
    # fresh sibling staging directory, then verify before publishing it.
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".rp1-handoff-", dir=destination.parent) as temp:
        temp_root = Path(temp)
        raw = temp_root / "data/raw"
        raw.mkdir(parents=True)
        for filename in profile_output_filenames(manifest).values():
            shutil.copyfile(source / filename, raw / filename)
        validate_profile_output_hashes(temp_root, manifest)
        (raw / "original_merger_manifest.json").write_bytes(manifest_bytes)
        relocated = json.loads(manifest_bytes)
        for record in relocated["outputs"].values():
            if isinstance(record, dict) and "staged_path" in record:
                name = Path(str(record["staged_path"]).replace("\\", "/")).name
                record["staged_path"] = f"RP1_Project/rp1_analysis/data/raw/{name}"
        relocated["analysis_handoff"] = {
            "original_manifest_file": "original_merger_manifest.json",
            "original_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "note": "Output paths describe the Stage 5 analysis input location; source provenance and output hashes are unchanged.",
        }
        (raw / "fire_panel_manifest.json").write_text(json.dumps(relocated, indent=2) + "\n", encoding="utf-8")
        raw.rename(destination)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Completed merger output directory")
    parser.add_argument("destination", type=Path, help="New staging directory (must not exist)")
    args = parser.parse_args()
    prepare(args.source, args.destination)
    print(f"Verified bundle created at {args.destination}; copy its files to rp1_analysis/data/raw after reviewing existing inputs.")


if __name__ == "__main__":
    main()
