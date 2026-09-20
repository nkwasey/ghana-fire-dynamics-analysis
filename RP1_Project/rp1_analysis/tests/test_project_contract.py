from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import tomllib
import sys
from pathlib import Path

import nbformat
from rp1_analysis_v1.config import load_configuration_bundle

SUBPROJECT = Path(__file__).resolve().parents[1]
SRC = SUBPROJECT / "src"
RAW = SUBPROJECT / "data" / "raw"
GEO = SUBPROJECT / "data" / "geo"

REQUIRED_RAW = {
    "fire_panel_acz_monthly_consolidated_2001_2024.csv",
    "fire_panel_district_monthly_consolidated_2001_2024.csv",
    "fire_panel_key_audit.csv",
    "fire_panel_manifest.json",
    "fire_panel_merge_summary.json",
}

# Capture release-tree state during pytest collection, before any test workflow can
# legitimately create run output.  This keeps the release-hygiene assertion valid
# under a direct ``python -m pytest`` invocation without making it test-order dependent.
OUT_DIRECTORY_PRESENT_AT_COLLECTION = (SUBPROJECT / "out").exists()


def test_required_structure_exists() -> None:
    for rel in [
        "RP1_Analysis_v1.ipynb",
        "README.md",
        "pyproject.toml",
        "config/analysis_contract.yml",
        "config/figure_contract.yml",
        "config/output_contract.yml",
        "config/execution_contract.yml",
        "docs/Data_Contract.md",
        "docs/Analysis_Methods_Contract.md",
        "docs/RP1_Analysis_v1_Cell_Contract.md",
        "docs/Figure_Table_Contract.md",
        "docs/Reproducibility_Contract.md",
        "docs/Secondary_Analysis_Contract.md",
        "src/rp1_analysis_v1/__init__.py",
        "src/rp1_analysis_v1/data_io.py",
        "src/rp1_analysis_v1/validation.py",
        "src/rp1_analysis_v1/variables.py",
        "src/rp1_analysis_v1/temporal.py",
        "src/rp1_analysis_v1/seasonality.py",
        "src/rp1_analysis_v1/inference.py",
        "src/rp1_analysis_v1/integration.py",
        "src/rp1_analysis_v1/gee.py",
        "scripts/validate_inputs.py",
        "scripts/execute_notebook.py",
        "scripts/validate_run.py",
        "data/input_sha256.json",
    ]:
        assert (SUBPROJECT / rel).exists(), rel


def test_canonical_notebook_name_and_validity() -> None:
    notebooks = sorted(p.name for p in SUBPROJECT.glob("*.ipynb"))
    assert notebooks == ["RP1_Analysis_v1.ipynb"]
    nb = nbformat.read(SUBPROJECT / "RP1_Analysis_v1.ipynb", as_version=4)
    assert nb.cells
    assert "Ghana Fire RP1 Analysis v1" in nb.cells[0].source


def test_required_analytical_files_present() -> None:
    assert REQUIRED_RAW.issubset({p.name for p in RAW.iterdir() if p.is_file()})


def test_geometry_component_completeness() -> None:
    for stem in ["acz", "districts_within_acz"]:
        for suffix in [".shp", ".shx", ".dbf", ".prj", ".cpg"]:
            assert (GEO / f"{stem}{suffix}").is_file()


def test_input_sha256_inventory_matches_bytes() -> None:
    inv = json.loads((SUBPROJECT / "data" / "input_sha256.json").read_text())
    assert inv["schema_version"] == load_configuration_bundle(SUBPROJECT / "config").analysis.schema_version
    staged_paths = set()
    for item in inv["files"]:
        assert set(item) == {"origin_path", "staged_path", "sha256", "size_bytes"}
        assert item["origin_path"]
        p = SUBPROJECT / item["staged_path"]
        assert p.is_file()
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        assert digest == item["sha256"]
        assert p.stat().st_size == item["size_bytes"]
        staged_paths.add(item["staged_path"])
    assert {f"data/raw/{x}" for x in REQUIRED_RAW}.issubset(staged_paths)


def _python_files() -> list[Path]:
    return [p for p in SRC.rglob("*.py") if p.is_file()]


def test_v1_source_does_not_import_other_analysis_packages() -> None:
    forbidden = {"rp1_analysis_notebook", "rp1_analysis"}
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name.split(".")[0] for alias in node.names}
                assert not names.intersection(forbidden), (path, names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden, (path, node.module)


def test_no_developer_machine_absolute_paths_in_v1_source_or_config() -> None:
    candidates = list(SRC.rglob("*.py")) + list((SUBPROJECT / "config").glob("*.yml"))
    patterns = [
        re.compile(r"/mnt/[a-zA-Z]/"),
        re.compile(r"/home/[A-Za-z0-9_.-]+/"),
        re.compile(r"[A-Za-z]:\\\\Users\\\\"),
    ]
    for path in candidates:
        text = path.read_text(encoding="utf-8")
        for pattern in patterns:
            assert not pattern.search(text), (path, pattern.pattern)


def test_package_import_from_src_without_other_project_sources() -> None:
    with (SUBPROJECT / "pyproject.toml").open("rb") as handle:
        expected = tomllib.load(handle)["project"]["version"]
    code = f"import rp1_analysis_v1; assert rp1_analysis_v1.__version__ == {expected!r}"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_no_alternate_analysis_subproject_is_shipped() -> None:
    candidates = []
    for child in SUBPROJECT.parent.iterdir():
        pyproject = child / "pyproject.toml"
        if not child.is_dir() or not pyproject.is_file():
            continue
        with pyproject.open("rb") as handle:
            project = tomllib.load(handle).get("project", {})
        if project.get("name") == "rp1-analysis-v1":
            candidates.append(child.resolve())
    assert candidates == [SUBPROJECT.resolve()]


def test_release_out_directory_is_not_shipped_before_execution() -> None:
    assert not OUT_DIRECTORY_PRESENT_AT_COLLECTION
