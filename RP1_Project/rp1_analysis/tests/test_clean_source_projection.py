from __future__ import annotations

import hashlib
import ast
import json
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
    for project, member, assignment in CONTRACT.repository.embedded_source_allowlists:
        path = root / project / member
        path.parent.mkdir(parents=True, exist_ok=True)
        source = next(p for p in CONTRACT.packages if p.project_root == project)
        module = Path(source.source_root).relative_to(project) / source.module / "__init__.py"
        path.write_text(f"{assignment} = {('pyproject.toml', module.as_posix(), member)!r}\n", encoding="utf-8")
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
    assert scientific.configuration_sha256 == load_configuration_bundle(SUBPROJECT / "config").configuration_sha256
    assert len(scientific.configuration_sha256) == 64
    assert scientific.configuration_sha256 != aggregate_qualification_configuration_sha256(hashes_a)


def test_clean_projection_from_pristine_repository(tmp_path: Path) -> None:
    repository = _minimal_repository(tmp_path)
    result = project_governed_source(repository, _projection_path(tmp_path), CONTRACT)
    assert result.source_inventory.entries == result.projected_inventory.entries
    assert result.source_inventory.exclusions == ()
    assert (Path(result.projection_root) / "README.md").read_bytes() == (repository / "README.md").read_bytes()


@pytest.mark.skipif(os.name != "nt", reason="Exercises native Windows MAX_PATH behavior")
def test_windows_projection_retains_deep_governed_authority_and_exact_inventory(tmp_path: Path) -> None:
    repository = _minimal_repository(tmp_path)
    relative = ("geo_data_prep/docs/source_provenance/"
                + "/".join(["deep_governed_authority_" + "x" * 35] * 3)
                + "/Ghana_MODIS_SP_2024_provenance.json")
    source = repository / relative
    projection = _projection_path(tmp_path, "deep provenance with spaces")
    assert len(str(source)) > 260 and len(str(projection / relative)) > 260

    # Build the real long-path fixture independently of production helpers.
    # Neither a shortened temporary root nor a registry setting is required.
    def native(path: Path) -> Path:
        return Path("\\\\?\\" + str(path.absolute()))

    content = b'{"governed_lineage": "synthetic immutable authority"}\n'
    native(source.parent).mkdir(parents=True, exist_ok=True)
    native(source).write_bytes(content)
    expected = inventory_governed_source(repository, CONTRACT)
    entry = expected.by_path[relative]
    assert entry.size_bytes == len(content)
    assert entry.sha256 == hashlib.sha256(content).hexdigest()

    result = project_governed_source(repository, projection, CONTRACT, expected_inventory=expected)
    assert result.source_inventory.entries == result.projected_inventory.entries
    assert native(projection / relative).read_bytes() == content
    assert not result.projection_root.startswith("\\\\?\\")
    assert all(not item.path.startswith("\\\\?\\") for item in result.projected_inventory.entries)

    native(projection / relative).write_bytes(b"changed authority")
    with pytest.raises(QualificationProjectionError, match="size/SHA-256 mismatch"):
        verify_projected_inventory(projection, expected)
    regenerated = project_governed_source(repository, projection, CONTRACT, expected_inventory=expected)
    assert regenerated.projected_inventory.entries == expected.entries
    assert native(source).read_bytes() == content

    generated = (projection / relative).parent / "__pycache__" / "cached.pyc"
    native(generated.parent).mkdir(parents=True)
    native(generated).write_bytes(b"runtime cache")
    removed = remove_generated_artifacts_from_projection(projection, CONTRACT)
    assert removed == (str(Path(relative).parent / "__pycache__").replace("\\", "/"),)
    assert verify_projected_inventory(projection, expected).entries == expected.entries


def test_projection_excludes_generated_handoffs_but_preserves_source_inputs(tmp_path: Path) -> None:
    repository = _minimal_repository(tmp_path)
    generated = [
        "RP1_Project/rp1_analysis/data/raw/fire_panel_manifest.json",
        "RP1_Project/rp1_analysis/data/input_sha256.json",
        "RP1_Project/rp1_mv_firms_panels/data/metadata/unit_universe.csv",
        "RP1_Project/rp1_mv_firms_panels/data/raw/boundaries/boundary.shp",
        "RP1_Project/rp1_mv_firms_panels/data/raw/modis/original.csv",
        "RP1_Project/rp1_mv_firms_panels/data/raw/viirs/original.csv",
        "RP1_Project/rp1_mv_firms_panels/data/raw/source_provenance/authority.json",
        "RP1_Project/rp1_mv_firms_panels/data/raw/unknown/private_key.txt",
        "RP1_Project/geo_handoff_manifest.json",
    ]
    approved_inputs = ["geo_data_prep/data/inputs_manifest.json", "geo_data_prep/data/raw/original.shp"]
    for relative in generated + approved_inputs:
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic test data")
    projection = _projection_path(tmp_path)
    result = project_governed_source(repository, projection, CONTRACT)
    excluded = generated
    assert all(not (projection / relative).exists() for relative in excluded)
    assert all((repository / relative).read_bytes() == b"synthetic test data" for relative in excluded)
    assert all((projection / relative).read_bytes() == b"synthetic test data" for relative in approved_inputs)
    assert any(item.path == "RP1_Project/rp1_analysis/data" and item.rule.startswith("relative_path:")
               for item in result.source_inventory.exclusions)
    assert any(item.path == "RP1_Project/rp1_mv_firms_panels/data/raw" and item.rule.startswith("relative_path:")
               for item in result.source_inventory.exclusions)
    assert not any(entry.path.startswith("RP1_Project/rp1_mv_firms_panels/data/raw/")
                   for entry in result.projected_inventory.entries)


def test_projection_retains_internal_ba_tool_configuration_and_tests(tmp_path: Path) -> None:
    repository = _minimal_repository(tmp_path)
    members = (
        "RP1_Project/rp1_ba_consolidator/core.py",
        "RP1_Project/rp1_ba_consolidator/handoff.py",
        "tools/consolidate_ba.py",
        "RP1_Project/rp1_analysis/src/rp1_ba_contracts/c3.py",
        "RP1_Project/rp1_gee_ba_scripts/c3/build.py",
        "RP1_Project/rp1_gee_ba_scripts/c3/tests/offline/test_logic.cjs",
        "configs/workflow.json",
        "configs/workflow_ba_preparation.example.json",
        "tests/test_ba_consolidator.py",
        "tests/test_ba_handoff.py",
        "tests/test_ba_workflow.py",
    )
    for relative in members:
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("governed BA integration:" + relative + "\n").encode("utf-8"))
    projection = _projection_path(tmp_path)
    result = project_governed_source(repository, projection, CONTRACT)
    for relative in members:
        assert relative in result.source_inventory.by_path
        assert (projection / relative).read_bytes() == (repository / relative).read_bytes()


def test_embedded_archive_projection_retains_reviewed_source_and_reference_only(tmp_path: Path) -> None:
    repository = _minimal_repository(tmp_path)
    project, member, assignment = CONTRACT.repository.embedded_source_allowlists[0]
    script = repository / project / member
    values = ast.literal_eval(ast.parse(script.read_text()).body[0].value)
    retained = ("data/raw/README.md", "data/metadata/README.md", "private/README.md",
                "data/reference/geography/units.json")
    script.write_text(f"{assignment} = {(*values, *retained)!r}\n", encoding="utf-8")
    unlisted = ("data/raw/source.csv", "data/metadata/archive-manifest.json", "private/map_key.txt",
                "unlisted-result.json", "out/result.csv")
    for name in (*retained, *unlisted):
        target = repository / project / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("synthetic source or runtime bytes", encoding="utf-8")
    projection = _projection_path(tmp_path)
    result = project_governed_source(repository, projection, CONTRACT)
    for name in retained:
        assert (projection / project / name).read_bytes() == (repository / project / name).read_bytes()
    for name in unlisted:
        assert (repository / project / name).is_file()
        assert not (projection / project / name).exists()
    assert any(item.rule.startswith("embedded_source_allowlist:") for item in result.source_inventory.exclusions)


def test_embedded_projection_allowlist_never_executes_code(tmp_path: Path) -> None:
    repository = _minimal_repository(tmp_path)
    project, member, assignment = CONTRACT.repository.embedded_source_allowlists[0]
    marker = tmp_path / "should-not-exist"
    (repository / project / member).write_text(f"{assignment} = (__import__('pathlib').Path({str(marker)!r}).touch(),)\n", encoding="utf-8")
    with pytest.raises(QualificationProjectionError, match="literal data"):
        inventory_governed_source(repository, CONTRACT)
    assert not marker.exists()


def test_clean_package_and_qualification_share_embedded_source_authority() -> None:
    policy = json.loads((REPOSITORY / "configs/clean_source_package.json").read_text(encoding="utf-8"))
    assert policy["embedded_source_allowlists"] == CONTRACT.repository.to_dict()["embedded_source_allowlists"]
    assert {item.module for item in CONTRACT.packages} == {
        "rp1_analysis_v1", "mv_firms_panels", "geo_data_prep", "ghana_fire_archive"}


def test_generated_presentation_exports_are_excluded_without_hiding_source_images(tmp_path: Path) -> None:
    repository = _minimal_repository(tmp_path)
    roots = ["RP1_Project/rp1_analysis/" + name
             for name in ("presentation_all", "presentation_one", "presentation_rq3")]
    generated = [root + "/F2.png" for root in roots]
    generated += [roots[0] + "/RP1_PRESENTATION_FIGURE_MANIFEST.json"]
    governed = ["RP1_Project/rp1_analysis/docs/presentation_all/example.png",
                "RP1_Project/rp1_analysis/presentation_all_examples/README.md"]
    for relative in generated + governed:
        path = repository / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture bytes")
    projection = _projection_path(tmp_path)
    result = project_governed_source(repository, projection, CONTRACT)
    assert all(not (projection / relative).exists() for relative in generated)
    assert all((repository / relative).read_bytes() == b"fixture bytes" for relative in generated)
    assert all((projection / relative).read_bytes() == b"fixture bytes" for relative in governed)
    assert {entry.path for entry in result.source_inventory.exclusions} == set(roots)
    assert all(entry.rule.startswith("relative_path:") for entry in result.source_inventory.exclusions)


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
        ("RP1_Project/rp1_gee_ba_scripts/downloads", True),
        ("RP1_Project/rp1_gee_ba_scripts/RP1_Project_MODIS_BA_c3_2001", True),
        ("RP1_Project/configs/ba_source_lock_c3.json", False),
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


@pytest.mark.parametrize("configured", ["/outside", "../outside", r"C:\\outside", r"\\server\share"])
def test_generated_exclusion_path_must_be_portable_and_relative(tmp_path: Path, configured: str) -> None:
    raw = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
    raw["generated_artifacts"]["relative_paths"][0] = configured
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


def test_software_version_and_panel_schema_identities() -> None:
    bundle = load_configuration_bundle(SUBPROJECT / "config")
    assert __version__ == "1.3.1"
    assert bundle.package_version == "1.3.1"
    assert bundle.analysis.schema_version == "rp1-analysis-v1.1"
    assert bundle.data_schema.data_schema_version == "rp1-data-schema-v1.2"
    assert bundle.data_schema.panel_schema_version == "rp1_fire_panel_consolidated_v3"


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
