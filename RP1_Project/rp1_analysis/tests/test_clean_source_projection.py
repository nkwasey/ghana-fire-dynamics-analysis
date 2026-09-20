from __future__ import annotations

import os
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from rp1_analysis_v1 import __version__
from rp1_analysis_v1.config import (
    ConfigurationError,
    aggregate_qualification_configuration_sha256,
    load_configuration_bundle,
    load_qualification_contract,
    qualification_configuration_file_hashes,
)
from rp1_analysis_v1.source_projection import (
    QualificationProjectionError,
    inventory_governed_source,
    probe_projected_imports,
    project_governed_source,
    remove_generated_artifacts_from_projection,
    projected_import_environment,
    verify_projected_inventory,
    write_projection_evidence,
)

SUBPROJECT = Path(__file__).resolve().parents[1]
REPOSITORY = SUBPROJECT.parents[1]
CONTRACT_PATH = SUBPROJECT / "config/qualification_contract.yml"
CONTRACT = load_qualification_contract(CONTRACT_PATH)


def _minimal_repository(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    root.mkdir()
    for member in CONTRACT.repository.include_roots:
        target = root / member
        if Path(member).suffix or Path(member).name.startswith(".") or member in {
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

    # Minimal importable source trees for all governed modules.
    for package in CONTRACT.packages:
        source_root = root / package.source_root
        module_root = source_root / package.module
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


def _projection_path(tmp_path: Path, suffix: str = "projection") -> Path:
    return tmp_path / f"external_{suffix}" / CONTRACT.projection.clean_projection_subdirectory


def test_qualification_contract_is_separate_and_deterministically_hashed() -> None:
    hashes_a = qualification_configuration_file_hashes(SUBPROJECT / "config")
    hashes_b = qualification_configuration_file_hashes(SUBPROJECT / "config")
    assert hashes_a == hashes_b
    assert set(hashes_a) == {"qualification_contract.yml"}
    assert aggregate_qualification_configuration_sha256(hashes_a) == (
        aggregate_qualification_configuration_sha256(hashes_b)
    )
    scientific = load_configuration_bundle(SUBPROJECT / "config")
    assert scientific.configuration_sha256 == "19b683cd27d3593bdcca90f4980aad467fda8203d28a9fff6d5ad88d5211c332"


def test_clean_projection_from_pristine_repository(tmp_path: Path) -> None:
    repository = _minimal_repository(tmp_path)
    result = project_governed_source(repository, _projection_path(tmp_path), CONTRACT)
    assert result.source_inventory.entries == result.projected_inventory.entries
    assert result.source_inventory.exclusions == ()
    assert (Path(result.projection_root) / "README.md").read_bytes() == (repository / "README.md").read_bytes()


@pytest.mark.parametrize(
    ("relative", "is_directory"),
    [
        ("RP1_Project/rp1_analysis/src/rp1_analysis_v1.egg-info", True),
        ("RP1_Project/rp1_analysis/src/rp1_analysis_v1/__pycache__", True),
        ("RP1_Project/rp1_analysis/src/rp1_analysis_v1/cache.pyc", False),
        ("RP1_Project/rp1_analysis/.pytest_cache", True),
        ("RP1_Project/rp1_analysis/build", True),
        ("RP1_Project/rp1_analysis/dist", True),
        ("RP1_Project/rp1_analysis/out", True),
    ],
)
def test_generated_operational_residue_is_recorded_and_excluded(
    tmp_path: Path, relative: str, is_directory: bool
) -> None:
    repository = _minimal_repository(tmp_path)
    residue = repository / relative
    if is_directory:
        residue.mkdir(parents=True, exist_ok=True)
        (residue / "payload.bin").write_bytes(b"generated")
    else:
        residue.parent.mkdir(parents=True, exist_ok=True)
        residue.write_bytes(b"generated")

    projection = _projection_path(tmp_path)
    result = project_governed_source(repository, projection, CONTRACT)
    excluded = {item.path for item in result.source_inventory.exclusions}
    assert relative in excluded
    assert not (projection / relative).exists()
    assert (projection / "README.md").is_file()


def test_governed_files_are_retained_byte_for_byte(tmp_path: Path) -> None:
    repository = _minimal_repository(tmp_path)
    governed = repository / "RP1_Project/rp1_analysis/src/rp1_analysis_v1/payload.bin"
    governed.write_bytes(bytes(range(256)) * 4)
    projection = _projection_path(tmp_path)
    result = project_governed_source(repository, projection, CONTRACT)
    entry = result.source_inventory.by_path[
        "RP1_Project/rp1_analysis/src/rp1_analysis_v1/payload.bin"
    ]
    assert (projection / entry.path).read_bytes() == governed.read_bytes()


def test_missing_governed_source_fails_closed(tmp_path: Path) -> None:
    repository = _minimal_repository(tmp_path)
    expected = inventory_governed_source(repository, CONTRACT)
    (repository / "README.md").unlink()
    with pytest.raises(QualificationProjectionError, match="Missing governed source"):
        project_governed_source(
            repository, _projection_path(tmp_path), CONTRACT, expected_inventory=expected
        )


def test_governed_hash_change_fails_closed(tmp_path: Path) -> None:
    repository = _minimal_repository(tmp_path)
    expected = inventory_governed_source(repository, CONTRACT)
    (repository / "README.md").write_text("changed\n", encoding="utf-8")
    with pytest.raises(QualificationProjectionError, match="inventory changed"):
        project_governed_source(
            repository, _projection_path(tmp_path), CONTRACT, expected_inventory=expected
        )


def test_unexpected_projection_member_fails_closed(tmp_path: Path) -> None:
    repository = _minimal_repository(tmp_path)
    projection = _projection_path(tmp_path)
    result = project_governed_source(repository, projection, CONTRACT)
    (projection / "unexpected.txt").write_text("not governed\n", encoding="utf-8")
    with pytest.raises(QualificationProjectionError, match="Unexpected projection members"):
        verify_projected_inventory(projection, result.source_inventory)


def test_projection_rejects_destination_inside_or_above_repository(tmp_path: Path) -> None:
    repository = _minimal_repository(tmp_path)
    with pytest.raises(QualificationProjectionError, match="external"):
        project_governed_source(repository, repository / "projection", CONTRACT)
    with pytest.raises(QualificationProjectionError, match="external"):
        project_governed_source(repository, repository.parent, CONTRACT)


@pytest.mark.parametrize("configured", ["/home/example/repository", "../escape", r"C:\\Users\\example\\repository", r"\\server\\share\\repository"])
def test_absolute_or_traversal_configured_path_fails_closed(
    tmp_path: Path, configured: str
) -> None:
    raw = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    raw["repository"]["include_roots"][0] = configured
    target = tmp_path / "qualification_contract.yml"
    target.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="repository-relative"):
        load_qualification_contract(target)


def test_governed_symlink_fails_closed(tmp_path: Path) -> None:
    repository = _minimal_repository(tmp_path)
    target = repository / "RP1_Project/symlink_target.txt"
    target.write_text("target\n", encoding="utf-8")
    link = repository / "RP1_Project/symlinked.txt"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    with pytest.raises(QualificationProjectionError, match="symlink"):
        inventory_governed_source(repository, CONTRACT)


def test_projection_inventory_and_hashes_are_stable_across_runs(tmp_path: Path) -> None:
    repository = _minimal_repository(tmp_path)
    first = project_governed_source(repository, _projection_path(tmp_path, "one"), CONTRACT)
    second = project_governed_source(repository, _projection_path(tmp_path, "two"), CONTRACT)
    assert first.source_inventory.entries == second.source_inventory.entries
    assert first.source_inventory.inventory_sha256 == second.source_inventory.inventory_sha256
    assert first.projected_inventory.entries == second.projected_inventory.entries




def test_projection_rejects_unconfigured_or_overbroad_destination(tmp_path: Path) -> None:
    repository = _minimal_repository(tmp_path)
    with pytest.raises(QualificationProjectionError, match="configured clean projection subdirectory"):
        project_governed_source(repository, tmp_path / "external" / "arbitrary", CONTRACT)
    with pytest.raises(QualificationProjectionError, match="too broad"):
        project_governed_source(repository, Path(tmp_path.anchor) / CONTRACT.projection.clean_projection_subdirectory, CONTRACT)
    with pytest.raises(QualificationProjectionError, match="too broad"):
        project_governed_source(repository, Path.home() / CONTRACT.projection.clean_projection_subdirectory, CONTRACT)


def test_projection_evidence_must_be_external_to_operational_repository(tmp_path: Path) -> None:
    repository = _minimal_repository(tmp_path)
    result = project_governed_source(repository, _projection_path(tmp_path), CONTRACT)
    with pytest.raises(QualificationProjectionError, match="external to the operational repository"):
        write_projection_evidence(result, repository / "evidence.json")

def test_projected_imports_override_operational_pythonpath_and_are_cwd_independent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _minimal_repository(tmp_path)
    projection = _projection_path(tmp_path)
    project_governed_source(repository, projection, CONTRACT)

    operational = tmp_path / "operational_override"
    operational.mkdir()
    for package in CONTRACT.packages:
        module_root = operational / package.module
        module_root.mkdir()
        (module_root / "__init__.py").write_text("ORIGIN='operational'\n", encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(operational))

    unrelated_cwd = tmp_path / "unrelated_cwd"
    unrelated_cwd.mkdir()
    report = probe_projected_imports(projection, CONTRACT, cwd=unrelated_cwd)
    assert set(report) == {item.module for item in CONTRACT.packages}
    for package in CONTRACT.packages:
        assert Path(report[package.module]["origin"]).is_relative_to(
            projection / package.source_root
        )


def test_projected_import_environment_requires_no_user_specific_absolute_path(tmp_path: Path) -> None:
    repository = _minimal_repository(tmp_path)
    projection = _projection_path(tmp_path)
    project_governed_source(repository, projection, CONTRACT)
    env = projected_import_environment(projection, CONTRACT, base_environment={"PATH": os.environ.get("PATH", "")})
    entries = [Path(item).resolve() for item in env["PYTHONPATH"].split(os.pathsep)]
    assert entries
    assert all(item.is_relative_to(projection.resolve()) for item in entries)
    assert env["RP1_QUALIFICATION_IMPORT_MODE"] == "projected_source"
    analysis_package = next(item for item in CONTRACT.packages if item.module == "rp1_analysis_v1")
    assert Path(env["RP1_QUALIFICATION_PROJECT_ROOT"]) == (
        projection / analysis_package.project_root
    ).resolve()


def test_malformed_qualification_configuration_fails_closed(tmp_path: Path) -> None:
    raw = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    raw["projection"]["unexpected_field"] = True
    target = tmp_path / "qualification_contract.yml"
    target.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="Unknown fields"):
        load_qualification_contract(target)


def test_software_version_promoted_without_schema_change() -> None:
    bundle = load_configuration_bundle(SUBPROJECT / "config")
    assert __version__ == "1.2.3"
    assert bundle.package_version == "1.2.3"
    assert bundle.analysis.schema_version == "rp1-analysis-v1.1"
    assert bundle.data_schema.data_schema_version == "rp1-data-schema-v1.1"


def test_projection_cleanup_removes_only_configured_generated_residue(tmp_path: Path) -> None:
    repository = _minimal_repository(tmp_path)
    projection = _projection_path(tmp_path)
    result = project_governed_source(repository, projection, CONTRACT)
    generated = projection / "RP1_Project/rp1_analysis/out/runtime.json"
    generated.parent.mkdir(parents=True)
    generated.write_text("generated\n", encoding="utf-8")
    unexpected = projection / "unexpected-governed-change.txt"
    unexpected.write_text("unexpected\n", encoding="utf-8")

    removed = remove_generated_artifacts_from_projection(projection, CONTRACT)
    assert "RP1_Project/rp1_analysis/out" in removed
    assert not generated.exists()
    assert unexpected.is_file()
    with pytest.raises(QualificationProjectionError, match="Unexpected projection members"):
        verify_projected_inventory(projection, result.source_inventory)


def test_projection_cleanup_restores_exact_inventory_after_generated_residue(tmp_path: Path) -> None:
    repository = _minimal_repository(tmp_path)
    projection = _projection_path(tmp_path)
    result = project_governed_source(repository, projection, CONTRACT)
    for relative in (
        "RP1_Project/rp1_analysis/build/a.txt",
        "RP1_Project/rp1_analysis/src/rp1_analysis_v1.egg-info/PKG-INFO",
        "geo_data_prep/out/example/result.txt",
    ):
        path = projection / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("generated\n", encoding="utf-8")
    remove_generated_artifacts_from_projection(projection, CONTRACT)
    actual = verify_projected_inventory(projection, result.source_inventory)
    assert actual.entries == result.source_inventory.entries
