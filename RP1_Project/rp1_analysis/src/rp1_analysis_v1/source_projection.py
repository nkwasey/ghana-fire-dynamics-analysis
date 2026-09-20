"""Deterministic clean-source projection for RP1 qualification.

The operational checkout may contain installation/runtime residue.  This module
constructs a release-equivalent external tree from the governed repository
members defined by ``qualification_contract.yml`` without modifying the source
checkout.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .contracts import QualificationContract


class QualificationProjectionError(RuntimeError):
    """Raised when clean-source qualification cannot be proven safely."""


@dataclass(frozen=True, slots=True)
class SourceInventoryEntry:
    path: str
    size_bytes: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "size_bytes": self.size_bytes, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class ExcludedArtifact:
    path: str
    kind: str
    rule: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "kind": self.kind, "rule": self.rule}


@dataclass(frozen=True, slots=True)
class SourceInventory:
    entries: tuple[SourceInventoryEntry, ...]
    exclusions: tuple[ExcludedArtifact, ...]

    @property
    def by_path(self) -> dict[str, SourceInventoryEntry]:
        return {entry.path: entry for entry in self.entries}

    @property
    def inventory_sha256(self) -> str:
        payload = json.dumps(
            [entry.to_dict() for entry in self.entries],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_count": len(self.entries),
            "inventory_sha256": self.inventory_sha256,
            "files": [entry.to_dict() for entry in self.entries],
            "excluded_count": len(self.exclusions),
            "excluded": [entry.to_dict() for entry in self.exclusions],
        }


@dataclass(frozen=True, slots=True)
class ProjectionResult:
    repository_root: str
    projection_root: str
    source_inventory: SourceInventory
    projected_inventory: SourceInventory

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "rp1-clean-projection-result-v1",
            "repository_root": self.repository_root,
            "projection_root": self.projection_root,
            "source_inventory": self.source_inventory.to_dict(),
            "projected_inventory": self.projected_inventory.to_dict(),
            "exact_inventory_match": self.source_inventory.entries == self.projected_inventory.entries,
        }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _entry(path: Path, relative: str) -> SourceInventoryEntry:
    stat = path.stat()
    if not path.is_file():
        raise QualificationProjectionError(f"Governed member is not a regular file: {relative}")
    return SourceInventoryEntry(relative, stat.st_size, _sha256_file(path))


def _is_within(candidate: Path, root: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _safe_repository_member(repository_root: Path, relative: str) -> Path:
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts or str(rel) in {"", "."}:
        raise QualificationProjectionError(f"Unsafe governed repository path: {relative!r}")
    candidate = repository_root / rel
    # Resolve the parent only after lexical validation.  Symlinked members are
    # rejected separately; this guards accidental path escape through a parent.
    resolved_root = repository_root.resolve()
    resolved_candidate = candidate.resolve(strict=False)
    if not _is_within(resolved_candidate, resolved_root):
        raise QualificationProjectionError(f"Governed path escapes repository root: {relative!r}")
    return candidate


def _generated_directory_rule(name: str, contract: QualificationContract) -> str | None:
    policy = contract.generated_artifacts
    if name in policy.directory_names:
        return f"directory_name:{name}"
    for suffix in policy.directory_suffixes:
        if name.endswith(suffix):
            return f"directory_suffix:{suffix}"
    return None


def _generated_file_rule(name: str, contract: QualificationContract) -> str | None:
    policy = contract.generated_artifacts
    if name in policy.file_names:
        return f"file_name:{name}"
    for suffix in policy.file_suffixes:
        if name.endswith(suffix):
            return f"file_suffix:{suffix}"
    return None


def inventory_governed_source(
    repository_root: str | Path,
    contract: QualificationContract,
) -> SourceInventory:
    """Inventory governed regular files and record configured generated residue."""

    root = Path(repository_root).resolve()
    if not root.is_dir():
        raise QualificationProjectionError(f"Repository root does not exist: {root}")

    files: dict[str, SourceInventoryEntry] = {}
    exclusions: dict[str, ExcludedArtifact] = {}

    for configured in contract.repository.include_roots:
        member = _safe_repository_member(root, configured)
        if not member.exists() and not member.is_symlink():
            raise QualificationProjectionError(f"Missing governed source root/file: {configured}")
        if member.is_symlink():
            raise QualificationProjectionError(f"Governed symlink is not permitted: {configured}")

        if member.is_file():
            file_rule = _generated_file_rule(member.name, contract)
            if file_rule is not None:
                exclusions[configured] = ExcludedArtifact(configured, "file", file_rule)
                continue
            files[configured] = _entry(member, configured)
            continue
        if not member.is_dir():
            raise QualificationProjectionError(f"Unsupported governed member type: {configured}")

        for current, dirs, names in os.walk(member, topdown=True, followlinks=False):
            current_path = Path(current)
            kept_dirs: list[str] = []
            for dirname in sorted(dirs):
                candidate = current_path / dirname
                rel = candidate.relative_to(root).as_posix()
                if candidate.is_symlink():
                    raise QualificationProjectionError(f"Governed symlink is not permitted: {rel}")
                rule = _generated_directory_rule(dirname, contract)
                if rule is not None:
                    exclusions[rel] = ExcludedArtifact(rel, "directory", rule)
                else:
                    kept_dirs.append(dirname)
            dirs[:] = kept_dirs

            for filename in sorted(names):
                candidate = current_path / filename
                rel = candidate.relative_to(root).as_posix()
                if candidate.is_symlink():
                    raise QualificationProjectionError(f"Governed symlink is not permitted: {rel}")
                rule = _generated_file_rule(filename, contract)
                if rule is not None:
                    exclusions[rel] = ExcludedArtifact(rel, "file", rule)
                    continue
                if not candidate.is_file():
                    raise QualificationProjectionError(f"Unsupported governed member type: {rel}")
                if rel in files:
                    raise QualificationProjectionError(f"Governed file selected more than once: {rel}")
                files[rel] = _entry(candidate, rel)

    entries = tuple(files[key] for key in sorted(files))
    excluded = tuple(exclusions[key] for key in sorted(exclusions))
    if not entries:
        raise QualificationProjectionError("Governed source inventory is empty")
    return SourceInventory(entries=entries, exclusions=excluded)


def _inventory_projected_tree(projection_root: Path) -> SourceInventory:
    entries: list[SourceInventoryEntry] = []
    for current, dirs, names in os.walk(projection_root, topdown=True, followlinks=False):
        current_path = Path(current)
        for dirname in dirs:
            candidate = current_path / dirname
            if candidate.is_symlink():
                rel = candidate.relative_to(projection_root).as_posix()
                raise QualificationProjectionError(f"Unexpected symlink in clean projection: {rel}")
        for filename in names:
            candidate = current_path / filename
            rel = candidate.relative_to(projection_root).as_posix()
            if candidate.is_symlink():
                raise QualificationProjectionError(f"Unexpected symlink in clean projection: {rel}")
            if not candidate.is_file():
                raise QualificationProjectionError(f"Unexpected non-regular projection member: {rel}")
            entries.append(_entry(candidate, rel))
    return SourceInventory(entries=tuple(sorted(entries, key=lambda item: item.path)), exclusions=())


def verify_projected_inventory(
    projection_root: str | Path,
    expected: SourceInventory,
) -> SourceInventory:
    """Require an exact path/size/SHA-256 match with the expected governed set."""

    root = Path(projection_root).resolve()
    if not root.is_dir():
        raise QualificationProjectionError(f"Clean projection does not exist: {root}")
    actual = _inventory_projected_tree(root)
    expected_map = expected.by_path
    actual_map = actual.by_path
    missing = sorted(set(expected_map).difference(actual_map))
    unexpected = sorted(set(actual_map).difference(expected_map))
    if missing:
        raise QualificationProjectionError(f"Projection omitted governed files: {missing!r}")
    if unexpected:
        raise QualificationProjectionError(f"Unexpected projection members: {unexpected!r}")
    mismatched = [
        path
        for path in sorted(expected_map)
        if expected_map[path].size_bytes != actual_map[path].size_bytes
        or expected_map[path].sha256 != actual_map[path].sha256
    ]
    if mismatched:
        raise QualificationProjectionError(f"Projected size/SHA-256 mismatch: {mismatched!r}")
    return actual


def _copy_verified(source: Path, destination: Path, expected: SourceInventoryEntry) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    try:
        with source.open("rb") as src, destination.open("xb") as dst:
            for block in iter(lambda: src.read(1024 * 1024), b""):
                digest.update(block)
                size += len(block)
                dst.write(block)
    except (OSError, FileExistsError) as exc:
        raise QualificationProjectionError(f"Unable to project governed file {expected.path}: {exc}") from exc
    if size != expected.size_bytes or digest.hexdigest() != expected.sha256:
        raise QualificationProjectionError(
            f"Governed source changed during projection: {expected.path}"
        )


def project_governed_source(
    repository_root: str | Path,
    projection_root: str | Path,
    contract: QualificationContract,
    *,
    expected_inventory: SourceInventory | None = None,
) -> ProjectionResult:
    """Create a fresh external clean qualification projection.

    ``expected_inventory`` is optional for normal use and useful when a caller
    has already frozen the pre-copy authority.  Any source mutation between
    that inventory and copying is detected by byte-size/SHA-256 verification.
    """

    repository = Path(repository_root).resolve()
    destination = Path(projection_root).resolve()
    if not repository.is_dir():
        raise QualificationProjectionError(f"Repository root does not exist: {repository}")
    if _is_within(destination, repository) or _is_within(repository, destination):
        raise QualificationProjectionError(
            "Clean projection root must be external to and non-overlapping with the repository"
        )
    if destination.name != contract.projection.clean_projection_subdirectory:
        raise QualificationProjectionError(
            "Clean projection destination must use the configured clean projection subdirectory "
            f"{contract.projection.clean_projection_subdirectory!r}"
        )
    if destination.parent == Path(destination.anchor) or destination.parent == Path.home().resolve():
        raise QualificationProjectionError("Clean projection parent is too broad for safe recreation")

    source_inventory = expected_inventory or inventory_governed_source(repository, contract)
    # When the caller provides an authority, ensure the current configured set
    # has not silently changed before copying begins.
    if expected_inventory is not None:
        current = inventory_governed_source(repository, contract)
        if current.entries != expected_inventory.entries:
            raise QualificationProjectionError("Governed source inventory changed before projection")

    if destination.exists():
        if destination.is_symlink():
            raise QualificationProjectionError("Projection destination may not be a symlink")
        if destination.is_dir():
            shutil.rmtree(destination)
        else:
            destination.unlink()
    destination.mkdir(parents=True, exist_ok=False)

    try:
        for entry in source_inventory.entries:
            source = _safe_repository_member(repository, entry.path)
            if source.is_symlink():
                raise QualificationProjectionError(f"Governed symlink is not permitted: {entry.path}")
            if not source.is_file():
                raise QualificationProjectionError(f"Missing governed file during projection: {entry.path}")
            _copy_verified(source, destination / entry.path, entry)
        projected_inventory = verify_projected_inventory(destination, source_inventory)
    except Exception:
        # A failed projection is not a qualification authority.  Remove only
        # the external destination we created; never touch operational source.
        if destination.exists() and not destination.is_symlink():
            shutil.rmtree(destination, ignore_errors=True)
        raise

    return ProjectionResult(
        repository_root=str(repository),
        projection_root=str(destination),
        source_inventory=source_inventory,
        projected_inventory=projected_inventory,
    )



def remove_generated_artifacts_from_projection(
    projection_root: str | Path,
    contract: QualificationContract,
) -> tuple[str, ...]:
    """Remove only configured generated residue from an external projection.

    Qualification steps may legitimately create caches, ``out`` trees or
    build metadata in the disposable clean projection.  This helper restores
    that projection to its governed release-equivalent state without touching
    the operational checkout.  Unconfigured files, symlinks and special
    members are deliberately left for exact-inventory verification to reject.
    """

    root = Path(projection_root).resolve()
    if not root.is_dir():
        raise QualificationProjectionError(f"Clean projection does not exist: {root}")

    removed: list[str] = []
    for current, dirs, names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        kept_dirs: list[str] = []
        for dirname in sorted(dirs):
            candidate = current_path / dirname
            rel = candidate.relative_to(root).as_posix()
            if candidate.is_symlink():
                kept_dirs.append(dirname)
                continue
            rule = _generated_directory_rule(dirname, contract)
            if rule is None:
                kept_dirs.append(dirname)
                continue
            shutil.rmtree(candidate)
            removed.append(rel)
        dirs[:] = kept_dirs

        for filename in sorted(names):
            candidate = current_path / filename
            rel = candidate.relative_to(root).as_posix()
            if candidate.is_symlink():
                continue
            rule = _generated_file_rule(filename, contract)
            if rule is None:
                continue
            candidate.unlink()
            removed.append(rel)

    return tuple(sorted(removed))

def projected_source_roots(
    projection_root: str | Path,
    contract: QualificationContract,
) -> tuple[Path, ...]:
    root = Path(projection_root).resolve()
    return tuple((root / item.source_root).resolve() for item in contract.packages)


def projected_import_environment(
    projection_root: str | Path,
    contract: QualificationContract,
    *,
    base_environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return an environment that intentionally prioritises projected sources."""

    env = dict(os.environ if base_environment is None else base_environment)
    projection = Path(projection_root).resolve()
    roots = projected_source_roots(projection, contract)
    for source_root in roots:
        if not source_root.is_dir():
            raise QualificationProjectionError(
                f"Projected package source root is missing: {source_root}"
            )
    env["PYTHONPATH"] = os.pathsep.join(str(path) for path in roots)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # Operational scripts perform an import-safe preflight before importing the
    # package.  Mark this as an intentional projected-source context so that
    # stale editable-distribution metadata from the operational checkout is
    # treated as non-authoritative while the actual module origin remains
    # strictly verified against the projected source tree.
    analysis_project = next(
        (item for item in contract.packages if item.module == "rp1_analysis_v1"),
        None,
    )
    if analysis_project is None:
        raise QualificationProjectionError(
            "Qualification contract does not define the rp1_analysis_v1 package mapping"
        )
    projected_project_root = (projection / analysis_project.project_root).resolve()
    if not projected_project_root.is_dir():
        raise QualificationProjectionError(
            f"Projected analysis project root is missing: {projected_project_root}"
        )
    env["RP1_QUALIFICATION_IMPORT_MODE"] = "projected_source"
    env["RP1_QUALIFICATION_PROJECT_ROOT"] = str(projected_project_root)
    return env


def probe_projected_imports(
    projection_root: str | Path,
    contract: QualificationContract,
    *,
    python_executable: str | Path | None = None,
    cwd: str | Path | None = None,
) -> dict[str, dict[str, str]]:
    """Import governed modules in a subprocess and prove projected origins."""

    root = Path(projection_root).resolve()
    env = projected_import_environment(root, contract)
    modules = [item.module for item in contract.packages]
    probe = (
        "import importlib, json; "
        f"mods={modules!r}; "
        "print(json.dumps({m:str(importlib.import_module(m).__file__) for m in mods}, sort_keys=True))"
    )
    completed = subprocess.run(
        [str(python_executable or sys.executable), "-c", probe],
        cwd=str(Path(cwd).resolve()) if cwd is not None else str(root),
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise QualificationProjectionError(
            f"Projected import probe failed ({completed.returncode}): {completed.stderr.strip()}"
        )
    try:
        origins = json.loads(completed.stdout.strip())
    except json.JSONDecodeError as exc:
        raise QualificationProjectionError("Projected import probe returned malformed JSON") from exc
    if not isinstance(origins, dict):
        raise QualificationProjectionError("Projected import probe returned invalid origin mapping")

    report: dict[str, dict[str, str]] = {}
    by_module = {item.module: item for item in contract.packages}
    for module, raw_origin in origins.items():
        if module not in by_module or not isinstance(raw_origin, str):
            raise QualificationProjectionError("Projected import probe returned unexpected module data")
        origin = Path(raw_origin).resolve()
        expected_root = (root / by_module[module].source_root).resolve()
        if not _is_within(origin, expected_root):
            raise QualificationProjectionError(
                f"Projected import resolved from wrong authority: {module} -> {origin}; expected under {expected_root}"
            )
        report[module] = {"origin": str(origin), "expected_source_root": str(expected_root)}
    if set(report) != set(by_module):
        raise QualificationProjectionError("Projected import probe did not return every governed module")
    return report


def write_projection_evidence(result: ProjectionResult, path: str | Path) -> Path:
    """Write deterministic JSON projection evidence outside the projection tree."""

    destination = Path(path).resolve()
    projection = Path(result.projection_root).resolve()
    repository = Path(result.repository_root).resolve()
    if _is_within(destination, projection):
        raise QualificationProjectionError("Projection evidence must be outside the clean projection")
    if _is_within(destination, repository):
        raise QualificationProjectionError("Projection evidence must be external to the operational repository")
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result.to_dict(), sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    destination.write_text(payload, encoding="utf-8", newline="\n")
    return destination


__all__ = [
    "ExcludedArtifact",
    "ProjectionResult",
    "QualificationProjectionError",
    "SourceInventory",
    "SourceInventoryEntry",
    "inventory_governed_source",
    "probe_projected_imports",
    "project_governed_source",
    "remove_generated_artifacts_from_projection",
    "projected_import_environment",
    "projected_source_roots",
    "verify_projected_inventory",
    "write_projection_evidence",
]
