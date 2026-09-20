from __future__ import annotations

import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
ANALYSIS_PROJECT = ROOT / "RP1_Project" / "rp1_analysis"

TYPING_DEPENDENCIES = {
    "pandas-stubs==2.3.3.260113",
    "types-geopandas==1.1.4.20260807",
    "scipy-stubs==1.17.1.5",
}


def _toml(path: Path) -> dict[str, object]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def test_typing_dependencies_are_development_only() -> None:
    with (ROOT / "environment.yml").open("r", encoding="utf-8") as handle:
        environment = yaml.safe_load(handle)

    pip_sections = [
        entry["pip"]
        for entry in environment["dependencies"]
        if isinstance(entry, dict) and "pip" in entry
    ]
    assert len(pip_sections) == 1
    assert TYPING_DEPENDENCIES.isdisjoint(set(pip_sections[0]))

    conda_names = {
        str(entry).split("=", 1)[0].lower()
        for entry in environment["dependencies"]
        if isinstance(entry, str)
    }
    assert {"mypy", "black", "ruff", "types-pyyaml"}.isdisjoint(conda_names)

    root_project = _toml(ROOT / "pyproject.toml")
    analysis_project = _toml(ANALYSIS_PROJECT / "pyproject.toml")
    root_dev = set(root_project["project"]["optional-dependencies"]["dev"])
    analysis_dev = set(analysis_project["project"]["optional-dependencies"]["dev"])
    assert TYPING_DEPENDENCIES <= root_dev
    assert TYPING_DEPENDENCIES <= analysis_dev

    runtime_dependencies = set(analysis_project["project"]["dependencies"])
    assert not (TYPING_DEPENDENCIES & runtime_dependencies)


def test_statsmodels_missing_import_override_is_narrow() -> None:
    root_project = _toml(ROOT / "pyproject.toml")
    mypy = root_project["tool"]["mypy"]

    assert mypy.get("ignore_missing_imports", False) is False
    assert mypy.get("ignore_errors", False) is False

    overrides = mypy.get("overrides", [])

    statsmodels_overrides = [
        override
        for override in overrides
        if set(override.get("module", [])) == {"statsmodels", "statsmodels.*"}
    ]

    assert len(statsmodels_overrides) == 1

    override = statsmodels_overrides[0]

    assert override.get("ignore_missing_imports") is True
    assert override.get("ignore_errors", False) is False


def test_no_other_mypy_override_ignores_errors() -> None:
    root_project = _toml(ROOT / "pyproject.toml")
    overrides = root_project["tool"]["mypy"].get(
        "overrides",
        [],
    )

    assert all(override.get("ignore_errors", False) is False for override in overrides)
