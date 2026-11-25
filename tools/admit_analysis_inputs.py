"""Admit the checked analysis data and the source evidence cited by its manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile


ANALYSIS = Path("RP1_Project/rp1_analysis")
INVENTORY = ANALYSIS / "data/input_sha256.json"
PANEL_MANIFEST = ANALYSIS / "data/raw/fire_panel_manifest.json"
EVIDENCE_LISTS = ("evidence_files", "viirs_preparation_evidence", "source_preparation_evidence")


def contained(root: Path, relative: Path) -> Path:
    if relative.anchor or ".." in relative.parts or not relative.parts:
        raise ValueError(f"Invalid input relative path: {relative}")
    path = (root / relative).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"Input path escapes the root: {relative}")
    return path


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(root: Path, relative: Path) -> dict:
    return json.loads(contained(root, relative).read_text(encoding="utf-8-sig"))


def input_records(root: Path) -> dict[Path, tuple[str, int | None]]:
    inventory = read_json(root, INVENTORY)
    panel = read_json(root, PANEL_MANIFEST)
    files: dict[Path, tuple[str, int | None]] = {}

    def add(relative: Path, digest: str, size: int | None = None) -> None:
        contained(root, relative)
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError(f"Invalid input hash: {relative}")
        old = files.get(relative)
        if old is not None and (old[0] != digest or (old[1] is not None and size is not None and old[1] != size)):
            raise ValueError(f"Conflicting input records: {relative}")
        if old is None or size is not None:
            files[relative] = (digest, size)

    for record in inventory["files"]:
        staged = Path(record["staged_path"])
        contained(root / ANALYSIS, staged)
        add(ANALYSIS / staged, record["sha256"], int(record["size_bytes"]))
    if PANEL_MANIFEST not in files or sha256(contained(root, PANEL_MANIFEST)) != files[PANEL_MANIFEST][0]:
        raise ValueError("The panel manifest does not match the staged-input inventory.")
    add(INVENTORY, sha256(contained(root, INVENTORY)))
    handoff = panel["analysis_handoff"]
    original = Path(handoff["original_manifest_file"])
    if len(original.parts) != 1 or original.anchor:
        raise ValueError(f"Invalid original manifest filename: {original}")
    add(PANEL_MANIFEST.parent / original, handoff["original_manifest_sha256"])
    method = panel["active_fire_method"]
    evidence = [record for key in EVIDENCE_LISTS for record in method[key]]
    evidence.append(method["combine_receipt"])
    for record in evidence:
        add(Path(record["path"]), record["sha256"], record.get("size_bytes"))
    return files


def admit(source: Path, destination: Path) -> dict[str, object]:
    source, destination = source.resolve(), destination.resolve()
    if source == destination:
        raise ValueError("Select distinct source and destination roots.")
    records = input_records(source)
    copied = reused = total_bytes = 0
    for relative, (expected_hash, expected_size) in records.items():
        original = contained(source, relative)
        target = contained(destination, relative)
        size = original.stat().st_size
        if expected_size is not None and size != expected_size:
            raise ValueError(f"Source byte count differs from the inventory: {relative}")
        if target.exists():
            if target.stat().st_size != size or sha256(target) != expected_hash:
                raise ValueError(f"Existing destination differs from the inventory: {relative}")
            reused += 1
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".admit-", delete=False) as stream:
                work = Path(stream.name)
            try:
                shutil.copyfile(original, work)
                if work.stat().st_size != size or sha256(work) != expected_hash:
                    raise ValueError(f"Copied source differs from the inventory: {relative}")
                # Publish the complete file without replacing a concurrent writer.
                if os.name == "nt":
                    work.rename(target)
                else:
                    os.link(work, target)
            finally:
                work.unlink(missing_ok=True)
            copied += 1
        total_bytes += size
    return {
        "input_inventory_sha256": records[INVENTORY][0],
        "count": len(records),
        "copied": copied,
        "verified_existing": reused,
        "bytes": total_bytes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--destination-root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()
    try:
        summary = admit(args.source_root, args.destination_root)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f"Input admission failed: {exc}\n")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
