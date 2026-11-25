#!/usr/bin/env python3
"""Stage and archive source, original inputs, and self-contained test fixtures.

Generated workflow products are excluded by configs/clean_source_package.json.
The operational checkout is read only throughout packaging.
"""
from __future__ import annotations

import argparse
import ast
from fnmatch import fnmatchcase
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_MANIFEST = "PACKAGE_MANIFEST.sha256"
INPUT_MANIFEST = "SOURCE_INPUT_MANIFEST.json"


def sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def load_policy(root: Path) -> dict:
    policy = json.loads((root / "configs/clean_source_package.json").read_text(encoding="utf-8"))
    if policy.get("schema") != "rp1-clean-source-package-v1":
        raise ValueError("Unknown clean-source package policy")
    for group in ("include_roots", "exclude_paths", "source_input_roots", "retained_download_roots"):
        for value in policy[group]:
            safe_relative(value)
    for marker in policy.get("generated_directory_markers", []):
        if len(safe_relative(marker).parts) != 1:
            raise ValueError("Generated directory markers must be file names")
    for item in policy.get("embedded_source_allowlists", []):
        if set(item) != {"project_root", "path", "assignment"} or not item["assignment"].isidentifier():
            raise ValueError("Invalid embedded source allowlist policy")
        safe_relative(item["project_root"])
        safe_relative(item["path"])
    declared_empty_directories(policy)
    return policy


def embedded_allowlists(root: Path, policy: dict) -> dict[str, set[str]]:
    """Read reviewed literal member lists without executing embedded scripts."""
    result = {}
    for item in policy.get("embedded_source_allowlists", []):
        project = root / item["project_root"]
        if not project.exists():
            continue
        authority = project / item["path"]
        if authority.is_symlink() or not authority.is_file() or not authority.resolve().is_relative_to(root):
            raise ValueError("Missing or linked embedded source allowlist: " + str(authority))
        tree = ast.parse(authority.read_text(encoding="utf-8"))
        nodes = [node.value for node in tree.body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == item["assignment"] for target in node.targets)]
        if len(nodes) != 1:
            raise ValueError("Embedded source allowlist requires one literal assignment")
        try:
            values = ast.literal_eval(nodes[0])
        except (ValueError, TypeError, SyntaxError) as exc:
            raise ValueError("Embedded source allowlist must be literal data") from exc
        if not isinstance(values, (tuple, list)) or not values or any(not isinstance(name, str) for name in values):
            raise ValueError("Embedded source allowlist must contain file paths")
        if len(set(values)) != len(values):
            raise ValueError("Duplicate embedded source allowlist member")
        for name in values:
            safe_relative(name)
            # Runtime state and credentials can never become release inputs.
            if (name.startswith(("data/raw/", "data/metadata/", "private/"))
                    and name not in {"data/raw/README.md", "data/metadata/README.md", "private/README.md"}):
                raise ValueError("Runtime data or private file in embedded source allowlist")
            candidate = project / name
            if candidate.is_symlink() or not candidate.resolve().is_relative_to(project.resolve()) or not candidate.is_file():
                raise ValueError("Missing or unsafe embedded source member: " + name)
        result[item["project_root"]] = {item["project_root"] + "/" + name for name in values}
    return result


def unlisted_embedded(relative: str, allowlists: dict[str, set[str]]) -> bool:
    for project, allowed in allowlists.items():
        if relative == project or relative.startswith(project + "/"):
            return not (relative in allowed or any(name.startswith(relative + "/") for name in allowed))
    return False


def safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (not value or "\\" in value or ":" in value or path.is_absolute()
            or ".." in path.parts or path.as_posix() != value):
        raise ValueError("Unsafe release member: " + str(value))
    return path


def excluded(relative: str, policy: dict) -> bool:
    path = safe_relative(relative.lower())
    name = path.as_posix()
    retained = any(name == root.lower() or name.startswith(root.lower() + "/") or root.lower().startswith(name + "/")
                   for root in policy.get("retained_download_roots", []))
    directory_names = {item.lower() for item in policy["exclude_directory_names"]}
    if any(part in directory_names and not (part == "downloads" and retained)
           for part in path.parts):
        return True
    if any(part.endswith(suffix.lower()) for part in path.parts for suffix in policy["exclude_directory_suffixes"]):
        return True
    if any(name == excluded_root.lower() or name.startswith(excluded_root.lower() + "/") for excluded_root in policy["exclude_paths"]):
        return True
    return any(fnmatchcase(path.name, pattern.lower()) for pattern in policy["exclude_file_patterns"])


def is_generated_directory(path: Path, policy: dict) -> bool:
    return path.is_dir() and any(
        (path / marker).is_file() for marker in policy.get("generated_directory_markers", [])
    )


def in_roots(relative: str, roots: list[str]) -> bool:
    return any(relative == root or relative.startswith(root + "/") for root in roots)


def declared_empty_directories(policy: dict) -> tuple[str, ...]:
    """Empty release slots are explicit, never copied from operational data."""
    names = policy.get("empty_directories", [])
    if not isinstance(names, list) or any(not isinstance(name, str) for name in names):
        raise ValueError("Empty release directories must be a list of relative paths")
    if len(names) != len(set(names)):
        raise ValueError("Duplicate empty release directory")
    for name in names:
        safe_relative(name)
        if not any(name.startswith(root + "/") for root in policy["include_roots"]):
            raise ValueError("Empty release directory must be inside an included source root")
        if not excluded(name, policy):
            raise ValueError("Empty release directory must exclude its operational source contents")
        if any(other.startswith(name + "/") for other in names):
            raise ValueError("Empty release directories cannot contain another declared directory")
    return tuple(names)


def verify_empty_directories(root: Path, names: tuple[str, ...]) -> None:
    for name in names:
        path = root / name
        if path.is_symlink() or path.is_junction() or not path.is_dir() or any(path.iterdir()):
            raise ValueError("Declared release directory is missing, linked or not empty: " + name)


def source_files(root: Path, policy: dict):
    """Walk allowed roots without descending into generated directories."""
    allowlists = embedded_allowlists(root, policy)
    def walk(path: Path):
        relative = path.relative_to(root).as_posix()
        if excluded(relative, policy) or unlisted_embedded(relative, allowlists):
            return
        if path.is_symlink() or path.is_junction():
            raise ValueError("Symbolic links and junctions are not packaged: " + relative)
        if is_generated_directory(path, policy):
            return
        if path.is_dir():
            for child in sorted(path.iterdir()):
                yield from walk(child)
        elif path.is_file():
            yield relative, path
        else:
            raise ValueError("Unsupported source member: " + relative)
    for name in policy["include_roots"]:
        path = root / name
        if not path.exists():
            raise ValueError("Missing source root: " + name)
        yield from walk(path)


def clean_notebook(source: Path, destination: Path) -> None:
    notebook = json.loads(source.read_text(encoding="utf-8"))
    for cell in notebook.get("cells", []):
        if cell.get("cell_type") == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
        for key in ("execution", "ExecuteTime", "collapsed", "scrolled", "trusted"):
            cell.get("metadata", {}).pop(key, None)
    notebook.get("metadata", {}).pop("widgets", None)
    destination.write_text(json.dumps(notebook, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def stage_source(root: Path, destination: Path, *, policy: dict | None = None) -> dict:
    root, destination = root.resolve(), destination.resolve()
    policy = policy or load_policy(root)
    empty_directories = declared_empty_directories(policy)
    if destination == root or root.is_relative_to(destination):
        raise ValueError("Release staging must not replace or contain the operational source tree")
    if destination.is_relative_to(root) and not excluded(destination.relative_to(root).as_posix(), policy):
        raise ValueError("Staging inside the checkout must use an excluded output directory")
    if destination.exists() or destination.is_symlink():
        raise ValueError("Release staging already exists; choose a new directory")
    members = list(source_files(root, policy))
    destination.mkdir(parents=True)
    for index, (relative, source) in enumerate(members, 1):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix == ".ipynb":
            clean_notebook(source, target)
        else:
            shutil.copyfile(source, target)
        if index % 100 == 0:
            print(f"Staged {index}/{len(members)} files", flush=True)
    for name in empty_directories:
        (destination / name).mkdir(parents=True, exist_ok=False)
    inputs = {}
    for path in sorted(destination.rglob("*")):
        if path.is_file():
            relative = path.relative_to(destination).as_posix()
            if in_roots(relative, policy["source_input_roots"]):
                inputs[relative] = {"sha256": sha(path), "bytes": path.stat().st_size}
    (destination / INPUT_MANIFEST).write_text(json.dumps(
        {"schema": "rp1-source-input-inventory-v1", "files": inputs}, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    checksums = []
    for path in sorted(destination.rglob("*")):
        if path.is_file():
            checksums.append(f"{sha(path)}  {path.relative_to(destination).as_posix()}")
    (destination / PACKAGE_MANIFEST).write_text("\n".join(checksums) + "\n", encoding="utf-8", newline="\n")
    return audit_tree(destination, policy=policy)


def audit_tree(stage: Path, *, policy: dict | None = None) -> dict:
    stage = stage.resolve()
    policy = policy or load_policy(stage)
    empty_directories = declared_empty_directories(policy)
    verify_empty_directories(stage, empty_directories)
    allowlists = embedded_allowlists(stage, policy)
    manifest = {}
    for line in (stage / PACKAGE_MANIFEST).read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        safe_relative(name)
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest) or name in manifest:
            raise ValueError("Invalid package checksum inventory")
        manifest[name] = digest
    actual = set()
    total_bytes = 0
    for path in stage.rglob("*"):
        relative = path.relative_to(stage).as_posix()
        if relative in empty_directories:
            continue
        if (excluded(relative, policy) or unlisted_embedded(relative, allowlists)
                or path.is_symlink() or path.is_junction() or is_generated_directory(path, policy)):
            raise ValueError("Generated or linked member in release: " + relative)
        if relative not in {PACKAGE_MANIFEST, INPUT_MANIFEST} and not in_roots(relative, policy["include_roots"]):
            raise ValueError("Member outside declared source roots: " + relative)
        if not path.is_file():
            continue
        actual.add(relative)
        total_bytes += path.stat().st_size
        if relative != PACKAGE_MANIFEST and (relative not in manifest or sha(path) != manifest[relative]):
            raise ValueError("Release file differs from its inventory: " + relative)
        if path.suffix == ".ipynb":
            notebook = json.loads(path.read_text(encoding="utf-8"))
            if any(cell.get("outputs") or cell.get("execution_count") is not None
                   for cell in notebook.get("cells", []) if cell.get("cell_type") == "code"):
                raise ValueError("Executed notebook in release: " + relative)
    if actual != set(manifest) | {PACKAGE_MANIFEST}:
        raise ValueError("Release inventory contains missing or unexpected members")
    input_manifest = json.loads((stage / INPUT_MANIFEST).read_text(encoding="utf-8"))
    inputs = input_manifest["files"]
    expected_inputs = {name for name in actual if in_roots(name, policy["source_input_roots"])}
    if input_manifest.get("schema") != "rp1-source-input-inventory-v1" or set(inputs) != expected_inputs:
        raise ValueError("Source input inventory does not fully cover the retained input files")
    for name, record in inputs.items():
        if name not in manifest or manifest[name] != record["sha256"] or (stage / name).stat().st_size != record["bytes"]:
            raise ValueError("Source input inventory differs: " + name)
    return {"status": "PASS", "files": len(actual), "bytes": total_bytes,
            "source_input_files": len(inputs), "generated_outputs": 0, "executed_notebooks": 0,
            "empty_directories": list(empty_directories)}


def archive_source(stage: Path, output: Path) -> dict:
    stage, output = stage.resolve(), output.resolve()
    if output.is_relative_to(stage):
        raise ValueError("Archive must be outside the staged tree")
    result = audit_tree(stage)
    empty_directories = declared_empty_directories(load_policy(stage))
    output.parent.mkdir(parents=True, exist_ok=True)
    members = sorted(path for path in stage.rglob("*") if path.is_file())
    with output.open("xb") as stream:
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
            for name in empty_directories:
                archive.write(stage / name, stage.name + "/" + name + "/")
            for index, path in enumerate(members, 1):
                archive.write(path, stage.name + "/" + path.relative_to(stage).as_posix())
                if index % 100 == 0:
                    print(f"Archived {index}/{len(members)} files", flush=True)
    audit_tree(stage)
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        expected_directories = {stage.name + "/" + name + "/" for name in empty_directories}
        expected = {stage.name + "/" + path.relative_to(stage).as_posix() for path in members} | expected_directories
        if len(names) != len(set(names)) or set(names) != expected:
            raise ValueError("Archive inventory differs from clean staging")
        for name in names:
            if name in expected_directories:
                if not archive.getinfo(name).is_dir() or archive.read(name) != b"":
                    raise ValueError("Archive empty-directory entry differs: " + name)
                continue
            with archive.open(name) as stream:
                digest = hashlib.sha256()
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != sha(stage / name.removeprefix(stage.name + "/")):
                raise ValueError("Archive member content differs: " + name)
    result.update(zip_sha256=sha(output), zip_bytes=output.stat().st_size, archive=output.name,
                  zip_entries=len(members) + len(empty_directories))
    output.with_suffix(output.suffix + ".sha256").write_text(result["zip_sha256"] + "  " + output.name + "\n", encoding="ascii")
    output.with_suffix(output.suffix + ".audit.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    staging = commands.add_parser("stage", help="Copy clean source and original inputs to a fresh directory")
    staging.add_argument("--source", type=Path, default=ROOT)
    staging.add_argument("--destination", type=Path, required=True)
    audit = commands.add_parser("audit", help="Verify a staged tree against its checksums and exclusion policy")
    audit.add_argument("--staged", type=Path, required=True)
    archive = commands.add_parser("zip", help="Archive and verify an already audited staged tree")
    archive.add_argument("--staged", type=Path, required=True)
    archive.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "stage":
            result = stage_source(args.source, args.destination)
        elif args.command == "audit":
            result = audit_tree(args.staged)
        else:
            result = archive_source(args.staged, args.output)
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as exc:
        parser.exit(2, "Clean source packaging failed: " + str(exc) + "\n")
    print(json.dumps(result, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
