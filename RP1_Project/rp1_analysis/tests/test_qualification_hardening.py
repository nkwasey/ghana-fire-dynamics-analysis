from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

import pytest

from rp1_analysis_v1.config import load_qualification_contract
from rp1_analysis_v1.source_projection import (
    QualificationProjectionError,
    inventory_governed_source,
    probe_projected_imports,
    project_governed_source,
    remove_generated_artifacts_from_projection,
)

SUBPROJECT = Path(__file__).resolve().parents[1]
REPOSITORY = SUBPROJECT.parents[1]
CONTRACT = load_qualification_contract(SUBPROJECT / "config/qualification_contract.yml")


def _load_qualifier_module():
    path = REPOSITORY / "tools/qualify_environment.py"
    spec = importlib.util.spec_from_file_location("rp1_test_qualify_environment_hardening", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _copy_release_tree(source: Path, destination: Path) -> None:
    generated_names = set(CONTRACT.generated_artifacts.directory_names)
    generated_suffixes = tuple(CONTRACT.generated_artifacts.directory_suffixes)
    file_suffixes = tuple(CONTRACT.generated_artifacts.file_suffixes)
    file_names = set(CONTRACT.generated_artifacts.file_names)

    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {
            name
            for name in names
            if name in generated_names
            or name.endswith(generated_suffixes)
            or name in file_names
            or name.endswith(file_suffixes)
        }

    shutil.copytree(source, destination, ignore=ignore)


def _minimal_repository(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    root.mkdir()
    for member in CONTRACT.repository.include_roots:
        target = root / member
        name = Path(member).name
        if Path(member).suffix or name.startswith(".") or member in {
            "CONTRIBUTING.md",
            "LICENSE",
            "README.md",
            "environment.yml",
            "pyproject.toml",
        }:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"authority:{member}\n", encoding="utf-8")
        else:
            target.mkdir(parents=True, exist_ok=True)
            (target / "governed.txt").write_text(f"governed:{member}\n", encoding="utf-8")
    for package in CONTRACT.packages:
        module_root = root / package.source_root / package.module
        module_root.mkdir(parents=True, exist_ok=True)
        (module_root / "__init__.py").write_text(
            f"IDENTITY = {package.module!r}\n", encoding="utf-8"
        )
        project = root / package.project_root
        project.mkdir(parents=True, exist_ok=True)
        (project / "pyproject.toml").write_text(
            f"[project]\nname={package.distribution!r}\nversion='0.0.0'\n",
            encoding="utf-8",
        )
    return root


def _projection_path(tmp_path: Path, parent: str = "external") -> Path:
    return tmp_path / parent / CONTRACT.projection.clean_projection_subdirectory


def test_stale_root_evidence_is_cleared_without_touching_unrelated_files(tmp_path: Path) -> None:
    qualifier = _load_qualifier_module()
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    for name in qualifier.ROOT_EVIDENCE_FILES:
        (evidence / name).write_text("stale\n", encoding="utf-8")
    unrelated = evidence / "retain_me.txt"
    unrelated.write_text("authority outside qualifier runtime\n", encoding="utf-8")

    removed = qualifier._clear_stale_root_evidence(REPOSITORY, evidence)

    assert set(removed) == set(qualifier.ROOT_EVIDENCE_FILES)
    assert all(not (evidence / name).exists() for name in qualifier.ROOT_EVIDENCE_FILES)
    assert unrelated.read_text(encoding="utf-8") == "authority outside qualifier runtime\n"


def test_stale_root_evidence_symlink_is_unlinked_without_following_target(tmp_path: Path) -> None:
    qualifier = _load_qualifier_module()
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    target = tmp_path / "outside-authority.txt"
    target.write_text("must survive\n", encoding="utf-8")
    link = evidence / qualifier.ROOT_EVIDENCE_FILES[0]
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")

    removed = qualifier._clear_stale_root_evidence(REPOSITORY, evidence)

    assert link.name in removed
    assert not link.exists()
    assert target.read_text(encoding="utf-8") == "must survive\n"


def test_runtime_symlink_poisoning_fails_closed(tmp_path: Path) -> None:
    qualifier = _load_qualifier_module()
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    poisoned = evidence / "wheels"
    try:
        poisoned.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")

    with pytest.raises(ValueError, match="may not be a symlink"):
        qualifier._prepare_external_workspace(REPOSITORY, evidence, CONTRACT)
    assert outside.is_dir()


def test_repeated_projection_same_destination_recreates_stale_state_idempotently(tmp_path: Path) -> None:
    repository = _minimal_repository(tmp_path)
    projection = _projection_path(tmp_path)
    first = project_governed_source(repository, projection, CONTRACT)
    poison = projection / "stale-runtime.txt"
    poison.write_text("stale\n", encoding="utf-8")

    second = project_governed_source(repository, projection, CONTRACT)

    assert not poison.exists()
    assert first.source_inventory.entries == second.source_inventory.entries
    assert first.source_inventory.inventory_sha256 == second.source_inventory.inventory_sha256
    assert first.projected_inventory.inventory_sha256 == second.projected_inventory.inventory_sha256


def test_unexpected_governed_source_addition_after_frozen_inventory_fails_closed(tmp_path: Path) -> None:
    repository = _minimal_repository(tmp_path)
    expected = inventory_governed_source(repository, CONTRACT)
    unexpected = repository / "RP1_Project/rp1_analysis/src/rp1_analysis_v1/unexpected.py"
    unexpected.write_text("VALUE = 1\n", encoding="utf-8")

    with pytest.raises(QualificationProjectionError, match="inventory changed"):
        project_governed_source(
            repository,
            _projection_path(tmp_path),
            CONTRACT,
            expected_inventory=expected,
        )


def test_same_size_governed_source_hash_mutation_fails_closed(tmp_path: Path) -> None:
    repository = _minimal_repository(tmp_path)
    authority = repository / "README.md"
    original = authority.read_bytes()
    expected = inventory_governed_source(repository, CONTRACT)
    replacement = b"X" * len(original)
    assert replacement != original
    authority.write_bytes(replacement)

    with pytest.raises(QualificationProjectionError, match="inventory changed"):
        project_governed_source(
            repository,
            _projection_path(tmp_path),
            CONTRACT,
            expected_inventory=expected,
        )


def test_projection_and_cleanup_do_not_modify_operational_governed_source(tmp_path: Path) -> None:
    repository = _minimal_repository(tmp_path)
    operational_residue = repository / "RP1_Project/rp1_analysis/src/rp1_analysis_v1.egg-info"
    operational_residue.mkdir(parents=True)
    (operational_residue / "PKG-INFO").write_text("editable metadata\n", encoding="utf-8")
    before = inventory_governed_source(repository, CONTRACT)
    projection = _projection_path(tmp_path)
    result = project_governed_source(repository, projection, CONTRACT, expected_inventory=before)
    generated = projection / "RP1_Project/rp1_analysis/out/generated.txt"
    generated.parent.mkdir(parents=True)
    generated.write_text("runtime\n", encoding="utf-8")

    remove_generated_artifacts_from_projection(projection, CONTRACT)
    after = inventory_governed_source(repository, CONTRACT)

    assert after.entries == before.entries
    assert after.inventory_sha256 == before.inventory_sha256
    assert operational_residue.is_dir()
    assert (operational_residue / "PKG-INFO").is_file()
    assert result.source_inventory.entries == before.entries


def test_operational_import_authority_resolves_to_current_checkout() -> None:
    qualifier = _load_qualifier_module()
    specs = qualifier._bootstrap_package_specs(REPOSITORY)
    state = qualifier.operational_package_state(REPOSITORY, specs)

    assert set(state) == {item.module for item in CONTRACT.packages}
    assert all(item["status"] == "PASS" for item in state.values())
    for package in CONTRACT.packages:
        assert Path(state[package.module]["origin"]).is_relative_to(
            (REPOSITORY / package.source_root).resolve()
        )


def test_relocated_checkout_projection_is_cwd_independent_and_portable(tmp_path: Path) -> None:
    relocated = tmp_path / "portable checkout with spaces" / "repository"
    relocated.parent.mkdir(parents=True)
    _copy_release_tree(REPOSITORY, relocated)
    projection = tmp_path / "external evidence with spaces" / CONTRACT.projection.clean_projection_subdirectory
    project_governed_source(relocated, projection, CONTRACT)
    unrelated = tmp_path / "unrelated working directory"
    unrelated.mkdir()

    report = probe_projected_imports(projection, CONTRACT, cwd=unrelated)

    for package in CONTRACT.packages:
        origin = Path(report[package.module]["origin"])
        assert origin.is_relative_to((projection / package.source_root).resolve())
        assert not origin.is_relative_to(REPOSITORY.resolve())



def test_projection_and_projected_imports_are_independent_of_user_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _minimal_repository(tmp_path)
    changed_home = tmp_path / "different user home"
    changed_home.mkdir()
    monkeypatch.setenv("HOME", str(changed_home))
    projection = _projection_path(tmp_path, parent="external under changed home test")

    project_governed_source(repository, projection, CONTRACT)
    report = probe_projected_imports(projection, CONTRACT, cwd=tmp_path)

    assert projection.exists()
    assert not projection.is_relative_to(changed_home)
    for package in CONTRACT.packages:
        origin = Path(report[package.module]["origin"])
        assert origin.is_relative_to((projection / package.source_root).resolve())


def test_product_tests_do_not_require_packaged_archive_inputs() -> None:
    test_roots = (
        REPOSITORY / "geo_data_prep/tests",
        REPOSITORY / "RP1_Project/rp1_mv_firms_panels/tests",
        REPOSITORY / "RP1_Project/rp1_analysis/tests",
    )
    violations: list[tuple[str, str]] = []
    for root in test_roots:
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                    continue
                value = node.value.strip()
                if len(value) > 4 and value.casefold().endswith(".zip"):
                    violations.append((path.relative_to(REPOSITORY).as_posix(), value))
    assert violations == []


def test_production_qualification_code_has_no_user_specific_absolute_paths() -> None:
    patterns = (
        re.compile(r"/home/[^/\s]+/", flags=re.IGNORECASE),
        re.compile(r"/mnt/[A-Za-z]/(?:Users|home)/", flags=re.IGNORECASE),
        re.compile(r"[A-Za-z]:[\\/](?:Users|Documents and Settings)[\\/]", flags=re.IGNORECASE),
    )
    roots = (
        REPOSITORY / "tools",
        REPOSITORY / "geo_data_prep/src",
        REPOSITORY / "RP1_Project/rp1_mv_firms_panels/src",
        REPOSITORY / "RP1_Project/rp1_analysis/src",
        REPOSITORY / "RP1_Project/rp1_analysis/scripts",
    )
    violations: list[tuple[str, str]] = []
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            for pattern in patterns:
                match = pattern.search(source)
                if match:
                    violations.append((path.relative_to(REPOSITORY).as_posix(), match.group(0)))
    assert violations == []


def test_repeated_qualifier_lifecycle_recreates_state_and_emits_current_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise the canonical orchestration twice without duplicating its heavy subprocess estate."""

    qualifier = _load_qualifier_module()
    evidence = tmp_path / "same-external-evidence-parent"
    generation = {"value": "first"}

    def fake_run_step(
        name: str,
        command: list[str],
        logs_dir: Path,
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        del env
        logs_dir.mkdir(parents=True, exist_ok=True)
        log = logs_dir / f"{name}.log"
        if name == "full_pytest":
            log.write_text("1002 tests collected\n1001 passed, 1 skipped in 0.01s\n", encoding="utf-8")
        else:
            log.write_text(f"{generation['value']}:{name}\n", encoding="utf-8")
        if name.startswith("build_") and name.endswith("_wheel"):
            if "--outdir" in command:
                wheel_dir = Path(command[command.index("--outdir") + 1])
            else:
                wheel_dir = Path(command[command.index("--wheel-dir") + 1])
            wheel_dir.mkdir(parents=True, exist_ok=True)
            wheel = wheel_dir / f"{name[6:-6]}-0.0.0-py3-none-any.whl"
            wheel.write_text(generation["value"], encoding="utf-8")
        return {
            "command": command,
            "cwd": str(cwd.resolve()),
            "returncode": 0,
            "status": "PASS",
            "duration_seconds": 0.0,
            "log": str(log),
        }

    monkeypatch.setattr(qualifier, "run_step", fake_run_step)

    first, first_code = qualifier.qualify(
        repository_root=REPOSITORY,
        evidence_dir=evidence,
        defer_native_environment=True,
    )
    assert first_code == 0
    assert first["status"] == "PASS"
    first_inventory = first["projection_checks"]["source_inventory_sha256"]
    first_run_id = first["qualification_run_id"]
    assert {path.read_text(encoding="utf-8") for path in (evidence / "wheels").glob("*.whl")} == {"first"}

    for relative in (
        "clean_projection/stale.txt",
        "isolated_install/stale.txt",
        "logs/stale.log",
        "runtime/stale.txt",
    ):
        path = evidence / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("poison\n", encoding="utf-8")
    (evidence / "wheels/stale-from-prior-run.whl").write_text("poison\n", encoding="utf-8")
    (evidence / "projection_evidence.json").write_text('{"stale": true}\n', encoding="utf-8")
    (evidence / "qualification_report.json").write_text('{"stale": true}\n', encoding="utf-8")
    unrelated = evidence / "retain_unrelated.txt"
    unrelated.write_text("retain\n", encoding="utf-8")

    generation["value"] = "second"
    second, second_code = qualifier.qualify(
        repository_root=REPOSITORY,
        evidence_dir=evidence,
        defer_native_environment=True,
    )

    assert second_code == 0
    assert second["status"] == "PASS"
    assert second["qualification_run_id"] != first_run_id
    assert second["projection_checks"]["source_inventory_sha256"] == first_inventory
    assert set(second["stale_root_evidence_removed"]) == set(qualifier.ROOT_EVIDENCE_FILES)
    assert unrelated.read_text(encoding="utf-8") == "retain\n"
    assert not (evidence / "wheels/stale-from-prior-run.whl").exists()
    assert {path.read_text(encoding="utf-8") for path in (evidence / "wheels").glob("*.whl")} == {"second"}
    assert not any((evidence / relative).exists() for relative in (
        "clean_projection/stale.txt",
        "isolated_install/stale.txt",
        "logs/stale.log",
        "runtime/stale.txt",
    ))
    current_report = json.loads((evidence / "qualification_report.json").read_text(encoding="utf-8"))
    current_projection = json.loads((evidence / "projection_evidence.json").read_text(encoding="utf-8"))
    assert current_report["qualification_run_id"] == second["qualification_run_id"]
    assert current_projection["source_inventory"]["inventory_sha256"] == first_inventory


def test_pytest_summary_parser_records_actual_counts(tmp_path: Path) -> None:
    qualifier = _load_qualifier_module()
    log = tmp_path / "pytest.log"
    log.write_text(
        "1015 tests collected\n1014 passed, 1 skipped, 2 warnings in 1.00s\n",
        encoding="utf-8",
    )
    assert qualifier._parse_pytest_summary(log) == {
        "collected": 1015,
        "passed": 1014,
        "failed": None,
        "skipped": 1,
        "warnings": 2,
    }
