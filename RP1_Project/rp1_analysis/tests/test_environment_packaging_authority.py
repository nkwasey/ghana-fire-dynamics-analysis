from __future__ import annotations

import importlib
import importlib.metadata
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
ENVIRONMENT = ROOT / "environment.yml"
ROOT_PYPROJECT = ROOT / "pyproject.toml"
ANALYSIS_PYPROJECT = ROOT / "RP1_Project/rp1_analysis/pyproject.toml"
FIRMS_PYPROJECT = ROOT / "RP1_Project/rp1_mv_firms_panels/pyproject.toml"
GEO_PYPROJECT = ROOT / "geo_data_prep/pyproject.toml"


def load_toml(path: Path) -> dict[str, object]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def dependency_names(values: list[str]) -> set[str]:
    names: set[str] = set()
    for value in values:
        token = value.split(";", 1)[0].strip()
        for marker in ("<", ">", "=", "!", "~", "[", " "):
            token = token.split(marker, 1)[0]
        names.add(token.lower())
    return names


def test_environment_name_python_and_required_tools() -> None:
    data = yaml.safe_load(ENVIRONMENT.read_text(encoding="utf-8"))
    assert data["name"] == "rp_ghana_fire"
    deps = data["dependencies"]
    conda_deps = [item for item in deps if isinstance(item, str)]
    names = dependency_names(conda_deps)
    assert "python" in names
    assert "python>=3.13,<3.14" in conda_deps
    for required in {
        "pytest",
        "pypdf",
        "pillow",
        "pydantic",
        "jsonschema",
        "typer",
        "rich",
        "python-build",
        "setuptools",
        "wheel",
        "jupyterlab",
        "ipykernel",
        "ipython",
        "nbformat",
        "nbclient",
    }:
        assert required in names
    assert {"black", "ruff", "mypy", "types-pyyaml"}.isdisjoint(names)


def test_retained_test_dependencies_are_declared_consistently() -> None:
    data = yaml.safe_load(ENVIRONMENT.read_text(encoding="utf-8"))
    environment_names = dependency_names(
        [item for item in data["dependencies"] if isinstance(item, str)]
    )
    assert {"pytest", "pypdf", "pillow"} <= environment_names

    root_project = load_toml(ROOT_PYPROJECT)["project"]["optional-dependencies"]
    analysis_project = load_toml(ANALYSIS_PYPROJECT)["project"]["optional-dependencies"]
    firms_project = load_toml(FIRMS_PYPROJECT)["project"]["optional-dependencies"]
    geo_project = load_toml(GEO_PYPROJECT)["project"]["optional-dependencies"]
    assert {"pytest", "pypdf", "pillow"} <= dependency_names(root_project["test"])
    assert {"pytest", "pypdf", "pillow"} <= dependency_names(analysis_project["test"])
    assert {"pytest"} <= dependency_names(firms_project["test"])
    assert {"pytest"} <= dependency_names(geo_project["test"])


def test_development_tools_are_not_operational_environment_dependencies() -> None:
    data = yaml.safe_load(ENVIRONMENT.read_text(encoding="utf-8"))
    conda_names = dependency_names(
        [item for item in data["dependencies"] if isinstance(item, str)]
    )
    pip_entries = next(
        item["pip"] for item in data["dependencies"] if isinstance(item, dict) and "pip" in item
    )
    forbidden = {
        "black",
        "ruff",
        "mypy",
        "types-pyyaml",
        "pandas-stubs",
        "types-geopandas",
        "scipy-stubs",
    }
    assert forbidden.isdisjoint(conda_names)
    assert not any(
        entry.lower().split("=", 1)[0] in forbidden
        for entry in pip_entries
        if not entry.startswith("-e ")
    )


def test_environment_covers_no_isolation_build_requirements() -> None:
    data = yaml.safe_load(ENVIRONMENT.read_text(encoding="utf-8"))
    conda_deps = [item for item in data["dependencies"] if isinstance(item, str)]
    environment_names = dependency_names(conda_deps)

    for path in (
        ROOT_PYPROJECT,
        ANALYSIS_PYPROJECT,
        FIRMS_PYPROJECT,
        GEO_PYPROJECT,
    ):
        build_requires = load_toml(path)["build-system"]["requires"]
        missing = dependency_names(build_requires) - environment_names
        assert not missing, (path, sorted(missing))


def test_environment_covers_all_package_runtime_dependencies() -> None:
    data = yaml.safe_load(ENVIRONMENT.read_text(encoding="utf-8"))
    environment_names = dependency_names(
        [item for item in data["dependencies"] if isinstance(item, str)]
    )
    for path in (ANALYSIS_PYPROJECT, FIRMS_PYPROJECT, GEO_PYPROJECT):
        runtime = dependency_names(load_toml(path)["project"]["dependencies"])
        missing = runtime - environment_names
        assert not missing, (path, sorted(missing))


def test_analysis_runtime_and_test_dependency_roles_are_separated() -> None:
    analysis = load_toml(ANALYSIS_PYPROJECT)["project"]
    runtime_names = dependency_names(analysis["dependencies"])
    test_names = dependency_names(analysis["optional-dependencies"]["test"])
    assert {
        "numpy",
        "pyyaml",
        "pandas",
        "geopandas",
        "pyproj",
        "scipy",
        "statsmodels",
        "matplotlib",
        "nbformat",
        "nbclient",
        "ipykernel",
    } <= runtime_names
    assert {"pytest", "pypdf", "pillow"} <= test_names
    assert {"pypdf", "pillow"}.isdisjoint(runtime_names)


def test_environment_exact_editable_projects() -> None:
    data = yaml.safe_load(ENVIRONMENT.read_text(encoding="utf-8"))
    pip_sections = [
        item["pip"] for item in data["dependencies"] if isinstance(item, dict) and "pip" in item
    ]
    assert len(pip_sections) == 1
    pip_entries = pip_sections[0]

    assert all(isinstance(item, str) for item in pip_entries)

    editable_projects = [item for item in pip_entries if item.startswith("-e ")]

    assert editable_projects == [
        "-e ./geo_data_prep",
        "-e ./RP1_Project/rp1_mv_firms_panels",
        "-e ./RP1_Project/rp1_analysis",
    ]


def test_package_metadata_identities_and_readmes() -> None:
    analysis = load_toml(ANALYSIS_PYPROJECT)["project"]
    firms = load_toml(FIRMS_PYPROJECT)["project"]
    geo = load_toml(GEO_PYPROJECT)["project"]
    assert analysis["name"] == "rp1-analysis-v1"
    assert analysis["version"] == "1.2.3"
    assert firms["name"] == "mv-firms-panels"
    assert firms["readme"] == "MV-FIRMS_README.md"
    assert (FIRMS_PYPROJECT.parent / firms["readme"]).is_file()
    assert geo["name"] == "geo_data_prep_stage1"
    assert geo["version"] == "0.1.1"
    assert load_toml(ANALYSIS_PYPROJECT)["project"]["scripts"] == {
        "rp1-analysis": "rp1_analysis_v1.cli:main"
    }
    assert load_toml(FIRMS_PYPROJECT)["project"]["scripts"] == {
        "mv-firms-panels": "mv_firms_panels.cli.main:main"
    }
    assert load_toml(GEO_PYPROJECT)["project"]["scripts"] == {
        "geo-prep": "geo_data_prep.cli.app:app"
    }


def test_supporting_runtime_dependencies_are_declared() -> None:
    firms = load_toml(FIRMS_PYPROJECT)["project"]
    geo = load_toml(GEO_PYPROJECT)["project"]
    firms_names = dependency_names(firms["dependencies"])
    geo_names = dependency_names(geo["dependencies"])
    assert {"numpy", "geopandas", "matplotlib", "shapely", "pyproj", "pyogrio"} <= firms_names
    assert {"numpy", "pandas", "geopandas", "matplotlib", "pyproj"} <= geo_names


def test_root_development_tool_configuration_has_no_broad_suppression_or_pythonpath() -> None:
    root = load_toml(ROOT_PYPROJECT)
    assert root["tool"]["black"]["target-version"] == ["py313"]
    assert root["tool"]["ruff"]["target-version"] == "py313"
    assert root["tool"]["mypy"]["python_version"] == "3.13"
    assert "ignore_missing_imports" not in root["tool"]["mypy"]
    assert "ignore_errors" not in root["tool"]["mypy"]
    assert "pythonpath" not in root["tool"]["pytest"]["ini_options"]


def test_yaml_stub_metadata_is_declared_for_development() -> None:
    root = load_toml(ROOT_PYPROJECT)["project"]["optional-dependencies"]["dev"]
    analysis = load_toml(ANALYSIS_PYPROJECT)["project"]["optional-dependencies"]["dev"]
    firms = load_toml(FIRMS_PYPROJECT)["project"]["optional-dependencies"]["dev"]
    assert "types-pyyaml" in dependency_names(root)
    assert "types-pyyaml" in dependency_names(analysis)
    assert "types-pyyaml" in dependency_names(firms)


def test_root_is_only_development_tool_configuration_authority() -> None:
    root = load_toml(ROOT_PYPROJECT)
    assert "black" in root["tool"]
    assert "ruff" in root["tool"]
    assert "mypy" in root["tool"]
    for path in (ANALYSIS_PYPROJECT, FIRMS_PYPROJECT, GEO_PYPROJECT):
        nested = load_toml(path).get("tool", {})
        assert "black" not in nested
        assert "ruff" not in nested
        assert "mypy" not in nested


def test_installed_package_identity_and_checkout_origin() -> None:
    expected = {
        "rp1_analysis_v1": ("rp1-analysis-v1", load_toml(ANALYSIS_PYPROJECT)["project"]["version"]),
        "mv_firms_panels": ("mv-firms-panels", "0.2.1"),
        "geo_data_prep": ("geo_data_prep_stage1", load_toml(GEO_PYPROJECT)["project"]["version"]),
    }
    root = ROOT.resolve()
    for module_name, (distribution, version) in expected.items():
        module = importlib.import_module(module_name)
        assert importlib.metadata.version(distribution) == version
        module_path = Path(module.__file__).resolve()
        assert module_path.is_relative_to(
            root
        ), f"{module_name} imported from {module_path}, not current checkout {root}"


def test_release_python_and_license_metadata_authorities() -> None:
    root_project = load_toml(ROOT_PYPROJECT)["project"]
    analysis = load_toml(ANALYSIS_PYPROJECT)["project"]
    firms = load_toml(FIRMS_PYPROJECT)["project"]
    geo = load_toml(GEO_PYPROJECT)["project"]

    assert root_project["version"] == "1.2.3"
    for project in (root_project, analysis, firms, geo):
        assert project["requires-python"] == ">=3.13,<3.14"
        assert project["license"] == {"text": "BSD-3-Clause"}

    assert analysis["version"] == "1.2.3"
    assert geo["version"] == "0.1.1"

    for project in (root_project, analysis, firms, geo):
        classifiers = set(project.get("classifiers", []))
        assert "Programming Language :: Python :: 3.13" in classifiers
        assert "License :: OSI Approved :: BSD License" in classifiers


def test_subproject_license_files_match_repository_authority() -> None:
    authority = (ROOT / "LICENSE").read_bytes()
    for path in (
        ANALYSIS_PYPROJECT.parent / "LICENSE",
        FIRMS_PYPROJECT.parent / "LICENSE",
        GEO_PYPROJECT.parent / "LICENSE",
    ):
        assert path.read_bytes() == authority


def test_no_stale_operational_release_selectors() -> None:
    operational_paths = (
        ROOT_PYPROJECT,
        ROOT / "README.md",
        ANALYSIS_PYPROJECT,
        ANALYSIS_PYPROJECT.parent / "README.md",
        ANALYSIS_PYPROJECT.parent / "docs/Reproducibility_Contract.md",
        ANALYSIS_PYPROJECT.parent / "config/analysis_contract.yml",
        ANALYSIS_PYPROJECT.parent / "src/rp1_analysis_v1/__init__.py",
        ANALYSIS_PYPROJECT.parent / "src/rp1_analysis_v1/config.py",
        ANALYSIS_PYPROJECT.parent / "scripts/_operational_preflight.py",
        ROOT / "tools/qualify_environment.py",
    )
    for path in operational_paths:
        assert "1.0.0" not in path.read_text(encoding="utf-8"), path


def test_operational_runtime_and_qualification_authorities_match_release() -> None:
    preflight = (ANALYSIS_PYPROJECT.parent / "scripts/_operational_preflight.py").read_text(
        encoding="utf-8"
    )
    qualifier = (ROOT / "tools/qualify_environment.py").read_text(encoding="utf-8")

    assert "EXPECTED_VERSION" not in preflight
    assert "_expected_version(project_root)" in preflight
    assert "EXPECTED_PYTHON = (3, 13)" in preflight
    assert 'SOURCE = "source"' in preflight
    assert 'DISTRIBUTION = "distribution"' in preflight
    assert "non-editable installation" in preflight
    assert "verified " in preflight and "current source tree" in preflight
    for script_name in ("validate_inputs.py", "execute_notebook.py", "validate_run.py"):
        script = (ANALYSIS_PYPROJECT.parent / "scripts" / script_name).read_text(encoding="utf-8")
        assert "mode=InstallationMode.SOURCE" in script

    assert 'EXPECTED_PYTHON = (3, 13)' in qualifier
    assert 'EXPECTED_ENVIRONMENT = "rp_ghana_fire"' in qualifier
    assert '"pytest": "HARD_GATE"' in qualifier
    assert '"black": "DEVELOPMENT_ONLY_NOT_EXECUTED"' in qualifier
    assert '"ruff": "DEVELOPMENT_ONLY_NOT_EXECUTED"' in qualifier
    assert '"mypy": "DEVELOPMENT_ONLY_NOT_EXECUTED"' in qualifier
    assert "load_qualification_contract" in qualifier
    assert "project_governed_source" in qualifier
    assert "probe_projected_imports" in qualifier
    assert 'source_steps["full_pytest"]' in qualifier
    assert 'cwd=projection_root' in qualifier
    assert 'source_steps["validate_inputs"]' in qualifier
    assert 'source_steps["reference_methods"]' in qualifier
    assert 'build_steps[f"build_{key}_wheel"]' in qualifier
    assert 'project_root = (projection_root / item.project_root).resolve()' in qualifier
    assert 'isolated_steps["isolated_install"]' in qualifier
    assert 'isolated_steps["isolated_import"]' in qualifier
    assert '"--defer-native-environment"' in qualifier
    assert 'os.environ["CONDA_DEFAULT_ENV"]' not in qualifier
