# file: src/mv_firms_panels/core/hashing.py
"""SHA-256 hashing helpers (deterministic).

These helpers are used for:
- input provenance (hashing downloaded files),
- config identity (stable JSON representation),
- manifests and audit logs.

All functions return lowercase hex strings.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def sha256_text(text: str, *, encoding: str = "utf-8") -> str:
    return sha256_bytes(text.encode(encoding))


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    p = Path(path)
    h = hashlib.sha256()
    with p.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def stable_json_dumps(obj: Any) -> str:
    """Deterministic JSON serialisation suitable for hashing."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_mapping(mapping: Mapping[str, Any]) -> str:
    """Hash a mapping via deterministic JSON serialisation."""
    return sha256_text(stable_json_dumps(mapping))


def short_hash8(hex_digest: str) -> str:
    """Return first 8 chars of a hex digest (for run_id strategies)."""
    if not isinstance(hex_digest, str) or len(hex_digest) < 8:
        raise ValueError("hex_digest must be a hex string with length >= 8")
    return hex_digest[:8].lower()
