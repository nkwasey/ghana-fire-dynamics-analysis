from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from rp1_analysis_v1.config import load_qualification_contract
from rp1_analysis_v1.source_projection import (
    project_governed_source,
    projected_import_environment,
)

SUBPROJECT = Path(__file__).resolve().parents[1]
REPOSITORY = SUBPROJECT.parents[1]
CONTRACT = load_qualification_contract(SUBPROJECT / "config/qualification_contract.yml")


def _load_qualifier_module():
    path = REPOSITORY / "tools/qualify_environment.py"
    spec = importlib.util.spec_from_file_location("rp1_test_qualify_environment", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _copy_release_tree(source: Path, destination: Path) -> None:
    ignored_names = {
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".ipynb_checkpoints",
        "build",
        "dist",
        "out",
        "htmlcov",
        ".git",
        ".tox",
        ".nox",
        ".venv",
    }

    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {
            name
            for name in names
            if name in ignored_names
            or name.endswith(".egg-info")
            or name.endswith(".pyc")
            or name.endswith(".pyo")
        }

    shutil.copytree(source, destination, ignore=ignore)


def _source_pythonpath(root: Path) -> str:
    return os.pathsep.join(str((root / item.source_root).resolve()) for item in CONTRACT.packages)


def test_native_environment_identity_is_never_faked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    qualifier = _load_qualifier_module()
    monkeypatch.delenv("CONDA_DEFAULT_ENV", raising=False)
    strict = qualifier._environment_identity(defer_native_environment=False)
    hosted = qualifier._environment_identity(defer_native_environment=True)
    assert strict["status"] == "FAIL"
    assert hosted["status"] == "DEFERRED"
    assert os.environ.get("CONDA_DEFAULT_ENV") is None
    assert strict["expected_python"] == "3.13"


def test_external_workspace_rerun_clears_stale_qualifier_state(tmp_path: Path) -> None:
    qualifier = _load_qualifier_module()
    evidence = tmp_path / "evidence"
    for name in ("clean_projection", "wheels", "isolated_install", "logs", "runtime"):
        path = evidence / name
        path.mkdir(parents=True, exist_ok=True)
        (path / "stale.txt").write_text("stale\n", encoding="utf-8")

    paths = qualifier._prepare_external_workspace(REPOSITORY, evidence, CONTRACT)
    assert set(paths) == {"clean_projection", "wheels", "isolated_install", "logs", "runtime"}
    for path in paths.values():
        assert path.is_dir()
        assert list(path.iterdir()) == []


def test_external_workspace_rejects_evidence_inside_or_above_repository(tmp_path: Path) -> None:
    qualifier = _load_qualifier_module()
    with pytest.raises(ValueError, match="external"):
        qualifier._prepare_external_workspace(
            REPOSITORY,
            REPOSITORY / "qualification-evidence",
            CONTRACT,
        )
    with pytest.raises(ValueError, match="external"):
        qualifier._prepare_external_workspace(
            REPOSITORY,
            REPOSITORY.parent,
            CONTRACT,
        )


def test_exact_editable_metadata_defect_is_closed_by_clean_projection(tmp_path: Path) -> None:
    """Model the v1.2.1 contradiction without requiring an old checkout.

    The same strict hygiene test fails on an installation-mutated operational
    tree and passes unchanged on the governed projection built from that tree.
    """

    operational = tmp_path / "operational" / "repo"
    _copy_release_tree(REPOSITORY, operational)
    residue = operational / "RP1_Project/rp1_analysis/src/rp1_analysis_v1.egg-info"
    residue.mkdir(parents=True)
    (residue / "PKG-INFO").write_text("generated editable metadata\n", encoding="utf-8")

    base_env = os.environ.copy()
    base_env.update(
        {
            "PYTHONPATH": _source_pythonpath(operational),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPYCACHEPREFIX": str(tmp_path / "operational-pycache"),
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        }
    )
    target = "tests/test_repository_hygiene.py::test_repository_inventory_contains_no_persistent_release_contaminants"
    old_lifecycle = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", target],
        cwd=operational / "RP1_Project/rp1_analysis",
        env=base_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert old_lifecycle.returncode != 0
    assert "rp1_analysis_v1.egg-info" in old_lifecycle.stdout

    projection = tmp_path / "external" / CONTRACT.projection.clean_projection_subdirectory
    result = project_governed_source(operational, projection, CONTRACT)
    assert any(item.path.endswith("rp1_analysis_v1.egg-info") for item in result.source_inventory.exclusions)
    assert not (projection / "RP1_Project/rp1_analysis/src/rp1_analysis_v1.egg-info").exists()

    projected_env = projected_import_environment(projection, CONTRACT, base_environment=base_env)
    projected_env["PYTHONPYCACHEPREFIX"] = str(tmp_path / "projected-pycache")
    corrected_lifecycle = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", target],
        cwd=projection / "RP1_Project/rp1_analysis",
        env=projected_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert corrected_lifecycle.returncode == 0, corrected_lifecycle.stdout


def test_canonical_qualifier_routes_full_pytest_and_wheel_sources_to_projection() -> None:
    source = (REPOSITORY / "tools/qualify_environment.py").read_text(encoding="utf-8")
    assert 'source_steps["full_pytest"] = run_step(' in source
    assert '[sys.executable, "-m", "pytest", "-o", "addopts=", "-p", "no:cacheprovider", "-q"]' in source
    assert 'cwd=projection_root' in source
    assert 'project_root = (projection_root / item.project_root).resolve()' in source
    assert '"source_authority": "clean_projection"' in source
    assert 'remove_generated_artifacts_from_projection' in source
    hygiene = (SUBPROJECT / "tests/test_repository_hygiene.py").read_text(encoding="utf-8")
    assert "def test_repository_inventory_contains_no_persistent_release_contaminants" in hygiene
    assert "skip" not in hygiene[hygiene.index("def test_repository_inventory_contains_no_persistent_release_contaminants"):]
    assert "xfail" not in hygiene[hygiene.index("def test_repository_inventory_contains_no_persistent_release_contaminants"):]


def test_isolated_import_probe_requires_target_origins_and_versions(tmp_path: Path) -> None:
    qualifier = _load_qualifier_module()
    target = tmp_path / "isolated_install"
    target.mkdir()
    expected = qualifier.expected_package_versions(REPOSITORY, qualifier._bootstrap_package_specs(REPOSITORY))
    for module, (distribution, version) in expected.items():
        package = target / module
        package.mkdir()
        (package / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
        dist_info_name = distribution.replace("-", "_") + "-" + version + ".dist-info"
        dist_info = target / dist_info_name
        dist_info.mkdir()
        (dist_info / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: {distribution}\nVersion: {version}\n",
            encoding="utf-8",
        )

    env = os.environ.copy()
    env["PYTHONPATH"] = str(target)
    env["PYTHONNOUSERSITE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-c", qualifier._isolated_import_command(target, expected)],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout


def test_qualification_runtime_hash_evidence_is_json_serialisable() -> None:
    import json

    qualifier = _load_qualifier_module()
    runtime = qualifier._load_runtime_authorities(REPOSITORY)
    assert isinstance(runtime["qualification_config_hashes"], dict)
    json.dumps({
        "file_hashes": runtime["qualification_config_hashes"],
        "aggregate_sha256": runtime["qualification_config_sha256"],
    })


def test_hosted_pip_check_failure_is_recorded_as_deferred_not_passed() -> None:
    qualifier = _load_qualifier_module()
    step = {
        "status": "FAIL",
        "returncode": 1,
        "command": [sys.executable, "-m", "pip", "check"],
        "log": "/tmp/pip_check.log",
    }
    classified, deferred = qualifier._apply_pip_check_policy(
        step,
        environment_identity={"status": "DEFERRED"},
    )
    assert deferred is True
    assert classified["status"] == "DEFERRED"
    assert classified["raw_status"] == "FAIL"
    assert classified["returncode"] == 1
    assert "non-canonical hosted environment" in classified["reason"]


def test_canonical_pip_check_failure_remains_hard_failure() -> None:
    qualifier = _load_qualifier_module()
    step = {"status": "FAIL", "returncode": 1}
    classified, deferred = qualifier._apply_pip_check_policy(
        step,
        environment_identity={"status": "PASS"},
    )
    assert deferred is False
    assert classified["status"] == "FAIL"
    assert "raw_status" not in classified


def test_isolated_version_probe_needs_no_governed_source_root(tmp_path: Path) -> None:
    qualifier = _load_qualifier_module()
    target = tmp_path / "isolated_install"
    package = target / "rp1_analysis_v1"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("__version__ = '9.8.7'\n", encoding="utf-8")
    (package / "config.py").write_text(
        "SCHEMA_VERSION = 'rp1-analysis-v1.1'\n"
        "DATA_SCHEMA_VERSION = 'rp1-data-schema-v1.1'\n",
        encoding="utf-8",
    )
    dist_info = target / "rp1_analysis_v1-9.8.7.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: rp1-analysis-v1\nVersion: 9.8.7\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str(target)
    env["PYTHONNOUSERSITE"] = "1"
    env.pop("RP1_ANALYSIS_V1_ROOT", None)
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            qualifier._isolated_version_command(
                target,
                expected_version="9.8.7",
                expected_analysis_schema="rp1-analysis-v1.1",
                expected_data_schema="rp1-data-schema-v1.1",
            ),
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout
    assert "9.8.7" in completed.stdout
    assert "rp1-analysis-v1.1" in completed.stdout
