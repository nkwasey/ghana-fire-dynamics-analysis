"""Run provenance capture isolated from deterministic scientific result tables."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sha256_file(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def inventory_file(path: str | Path, *, relative_to: str | Path | None = None) -> dict[str, Any]:
    source = Path(path).resolve()
    stat = source.stat()
    if relative_to is None:
        display = source.name
    else:
        base = Path(relative_to).resolve()
        display = source.relative_to(base).as_posix()
    return {
        "path": display,
        "sha256": sha256_file(source),
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def inventory_inputs(
    paths: Sequence[str | Path], *, relative_to: str | Path
) -> list[dict[str, Any]]:
    records = [inventory_file(path, relative_to=relative_to) for path in paths]
    return sorted(records, key=lambda item: item["path"])


def capture_package_versions() -> dict[str, str]:
    """Capture installed distributions deterministically by normalised package name."""

    packages: dict[str, str] = {}
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata["Name"]
        if not name:
            continue
        key = str(name).lower().replace("_", "-")
        packages[key] = distribution.version
    return dict(sorted(packages.items()))


def capture_platform() -> dict[str, str]:
    return {
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python_implementation": platform.python_implementation(),
    }


def capture_python() -> dict[str, str]:
    return {
        "version": platform.python_version(),
        "version_info": ".".join(map(str, sys.version_info[:3])),
        "executable_name": Path(sys.executable).name,
    }


def capture_git_commit(project_root: str | Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(Path(project_root).resolve()), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    commit = result.stdout.strip()
    return commit if result.returncode == 0 and len(commit) == 40 else None


@dataclass(slots=True)
class RunProvenance:
    run_id: str
    project_root: Path
    configuration_sha256: str
    input_paths: list[Path]
    input_validation_status: str | None = None
    canonical_input_identity: str | None = None
    started_at_utc: str = field(default_factory=utc_now_iso)
    ended_at_utc: str | None = None

    def finish(self) -> None:
        if self.ended_at_utc is not None:
            raise RuntimeError("Run provenance is already finalised")
        self.ended_at_utc = utc_now_iso()

    def manifest(self) -> dict[str, Any]:
        from .config import load_analysis_contract

        schema_version = load_analysis_contract(
            self.project_root / "config" / "analysis_contract.yml"
        ).schema_version
        payload = {
            "schema_version": schema_version,
            "run_id": self.run_id,
            "started_at_utc": self.started_at_utc,
            "ended_at_utc": self.ended_at_utc,
            "configuration_sha256": self.configuration_sha256,
            "inputs": inventory_inputs(self.input_paths, relative_to=self.project_root),
            "environment": {
                "python": capture_python(),
                "platform": capture_platform(),
                "packages": capture_package_versions(),
                "git_commit": capture_git_commit(self.project_root),
            },
            "determinism_note": (
                "Run timestamps and environment metadata are provenance only and must not be "
                "inserted into scientific result tables or deterministic scientific filenames."
            ),
        }
        if self.input_validation_status is not None:
            if self.input_validation_status not in {"PASS", "FAIL"}:
                raise ValueError("input_validation_status must be PASS or FAIL")
            payload["input_validation_status"] = self.input_validation_status
        if self.canonical_input_identity is not None:
            if self.canonical_input_identity not in {"MATCH", "DIFFERENT"}:
                raise ValueError("canonical_input_identity must be MATCH or DIFFERENT")
            payload["canonical_input_identity"] = self.canonical_input_identity
        return payload

    def write_manifest(self, destination: str | Path) -> Path:
        if self.ended_at_utc is None:
            raise RuntimeError("Finish provenance before writing the final run manifest")
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise FileExistsError(path)
        text = (
            json.dumps(
                self.manifest(), sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False
            )
            + "\n"
        )
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(tmp, path)
            except FileExistsError:
                raise FileExistsError(path) from None
            tmp.unlink()
        finally:
            if tmp.exists():
                tmp.unlink()
        return path
