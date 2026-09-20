"""Portable, fail-closed path handling for RP1 Analysis v1."""

from __future__ import annotations

import importlib.metadata
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

_ROOT_ENV = "RP1_ANALYSIS_V1_ROOT"
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_ROOT_MARKERS = (
    Path("pyproject.toml"),
    Path("config/analysis_contract.yml"),
    Path("config/data_schema_contract.yml"),
    Path("config/method_authorities.yml"),
    Path("config/output_contract.yml"),
    Path("config/figure_contract.yml"),
    Path("config/execution_contract.yml"),
    Path("src/rp1_analysis_v1/__init__.py"),
)


class PathIsolationError(ValueError):
    """Raised when a path would escape the governed subproject."""


def _is_subproject_root(candidate: Path) -> bool:
    return all((candidate / marker).is_file() for marker in _ROOT_MARKERS)


def _installed_source_origin() -> Path | None:
    """Return a verified local source root recorded by PEP 610, when available."""

    try:
        distribution = importlib.metadata.distribution("rp1-analysis-v1")
        raw = distribution.read_text("direct_url.json")
        if not raw:
            return None
        url = json.loads(raw).get("url")
        if not isinstance(url, str):
            return None
        parsed = urlparse(url)
        if parsed.scheme != "file":
            return None
        candidate = Path(url2pathname(unquote(parsed.path))).resolve()
    except (importlib.metadata.PackageNotFoundError, OSError, ValueError, json.JSONDecodeError):
        return None
    return candidate if _is_subproject_root(candidate) else None


def discover_subproject_root(start: str | Path | None = None) -> Path:
    """Find the extracted subproject root without consulting the current working directory."""

    env_root = os.environ.get(_ROOT_ENV)
    if env_root:
        candidate = Path(env_root).expanduser().resolve()
        if not _is_subproject_root(candidate):
            raise PathIsolationError(
                f"{_ROOT_ENV} does not identify an RP1 Analysis v1 root: {candidate}"
            )
        return candidate

    anchor = Path(start).expanduser().resolve() if start is not None else Path(__file__).resolve()
    search = anchor.parents if anchor.is_file() else (anchor, *anchor.parents)
    for candidate in search:
        if _is_subproject_root(candidate):
            return candidate
    if start is None:
        installed_origin = _installed_source_origin()
        if installed_origin is not None:
            return installed_origin
    raise PathIsolationError(
        "Unable to discover the RP1 Analysis v1 subproject root from package location or "
        "verified local-install metadata. "
        f"Set {_ROOT_ENV} to the extracted subproject root when the installation has no local source origin."
    )


def _inside(base: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(base)
    except ValueError:
        return False
    return True


def _atomic_pointer_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


@dataclass(frozen=True, slots=True)
class ProjectPaths:
    root: Path

    @classmethod
    def discover(cls, start: str | Path | None = None) -> ProjectPaths:
        return cls(discover_subproject_root(start))

    def resolve_inside(self, relative: str | Path) -> Path:
        rel = Path(relative)
        if rel.is_absolute():
            raise PathIsolationError(
                f"Absolute paths are not governed subproject paths: {relative}"
            )
        candidate = (self.root / rel).resolve()
        root = self.root.resolve()
        if not _inside(root, candidate):
            raise PathIsolationError(f"Path escapes subproject root: {relative}")
        return candidate

    @property
    def analysis_contract(self) -> Path:
        return self.resolve_inside("config/analysis_contract.yml")

    @property
    def figure_contract(self) -> Path:
        return self.resolve_inside("config/figure_contract.yml")

    @property
    def data_schema_contract(self) -> Path:
        return self.resolve_inside("config/data_schema_contract.yml")

    @property
    def method_authorities(self) -> Path:
        return self.resolve_inside("config/method_authorities.yml")

    @property
    def reference_fixture_root(self) -> Path:
        return self.resolve_inside("tests/fixtures/reference_methods")

    @property
    def output_contract(self) -> Path:
        return self.resolve_inside("config/output_contract.yml")

    @property
    def execution_contract(self) -> Path:
        return self.resolve_inside("config/execution_contract.yml")

    @property
    def raw_data_dir(self) -> Path:
        return self.resolve_inside("data/raw")

    @property
    def geo_data_dir(self) -> Path:
        return self.resolve_inside("data/geo")

    @property
    def input_hash_inventory(self) -> Path:
        return self.resolve_inside("data/input_sha256.json")

    @property
    def governed_inputs(self) -> dict[str, Path]:
        return {
            "acz_panel": self.resolve_inside(
                "data/raw/fire_panel_acz_monthly_consolidated_2001_2024.csv"
            ),
            "district_panel": self.resolve_inside(
                "data/raw/fire_panel_district_monthly_consolidated_2001_2024.csv"
            ),
            "key_audit": self.resolve_inside("data/raw/fire_panel_key_audit.csv"),
            "panel_manifest": self.resolve_inside("data/raw/fire_panel_manifest.json"),
            "merge_summary": self.resolve_inside("data/raw/fire_panel_merge_summary.json"),
            "acz_geometry": self.resolve_inside("data/geo/acz.shp"),
            "district_geometry": self.resolve_inside("data/geo/districts_within_acz.shp"),
        }

    @property
    def all_hashed_inputs(self) -> tuple[Path, ...]:
        """Return every input path governed by ``data/input_sha256.json``."""

        raw = json.loads(self.input_hash_inventory.read_text(encoding="utf-8"))
        if (
            not isinstance(raw.get("schema_version"), str)
            or raw.get("provenance_schema_version") != "rp1-input-provenance-v2"
            or not isinstance(raw.get("files"), list)
        ):
            raise PathIsolationError("Invalid data/input_sha256.json structure")
        paths: list[Path] = []
        for item in raw["files"]:
            if not isinstance(item, dict) or not isinstance(item.get("staged_path"), str):
                raise PathIsolationError("Invalid staged_path entry in data/input_sha256.json")
            resolved = self.resolve_inside(item["staged_path"])
            if not resolved.is_file():
                raise FileNotFoundError(resolved)
            paths.append(resolved)
        return tuple(paths)

    def create_run(self, run_id: str | None = None) -> Path:
        from .config import load_output_contract

        contract = load_output_contract(self.output_contract)
        if run_id is None:
            run_id = datetime.now(UTC).strftime("run_%Y%m%dT%H%M%S_%fZ")
        if not _RUN_ID_RE.fullmatch(run_id):
            raise PathIsolationError(f"Invalid run_id: {run_id!r}")
        run_root = self.resolve_inside(contract.run_root)
        run_dir = (run_root / run_id).resolve()
        if not _inside(run_root.resolve(), run_dir):
            raise PathIsolationError(f"Run path escapes governed run root: {run_id}")
        try:
            run_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            raise FileExistsError(f"Run already exists: {run_id}") from None
        for section in contract.sections:
            (run_dir / section).mkdir()
        pointer = self.resolve_inside(contract.latest_run_pointer)
        relative_pointer = run_dir.relative_to(self.root.resolve()).as_posix()
        _atomic_pointer_write(pointer, relative_pointer + "\n")
        return run_dir

    def read_latest_run(self) -> Path | None:
        from .config import load_output_contract

        contract = load_output_contract(self.output_contract)
        pointer = self.resolve_inside(contract.latest_run_pointer)
        if not pointer.exists():
            return None
        rel = pointer.read_text(encoding="utf-8").strip()
        if not rel:
            raise PathIsolationError("latest_run pointer is empty")
        latest = self.resolve_inside(rel)
        run_root = self.resolve_inside(contract.run_root).resolve()
        if not _inside(run_root, latest):
            raise PathIsolationError("latest_run pointer escapes the governed run root")
        return latest
