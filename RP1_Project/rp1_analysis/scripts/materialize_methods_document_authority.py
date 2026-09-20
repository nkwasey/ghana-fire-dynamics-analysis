#!/usr/bin/env python3
"""Materialise the current methods-document identity without rewriting scientific run snapshots."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docx", type=Path, required=True)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "data/authorities/methods_document_authority.json",
    )
    args = parser.parse_args()
    docx = args.docx.resolve(); pdf = args.pdf.resolve()
    if not docx.is_file() or not pdf.is_file():
        parser.error("--docx and --pdf must identify existing files")
    payload = {
        "schema": "rp1-methods-document-authority-v1",
        "document_role": "current_methods_authority",
        "scientific_method_change": "NONE",
        "alignment_scope": ["scientific_documentation", "reference_scope", "method_provenance", "presentation_outputs", "optional_external_result_integration"],
        "docx": {"filename": docx.name, "sha256": sha256(docx), "size_bytes": docx.stat().st_size},
        "pdf": {"filename": pdf.name, "sha256": sha256(pdf), "size_bytes": pdf.stat().st_size},
        "scientific_run_provenance_policy": (
            "Existing RQ scientific run metadata remain immutable snapshots of the scientific authority used when "
            "those authorities were materialised; presentation-only document alignment does not rewrite them."
        ),
    }
    atomic_write_json(args.output.resolve(), payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
