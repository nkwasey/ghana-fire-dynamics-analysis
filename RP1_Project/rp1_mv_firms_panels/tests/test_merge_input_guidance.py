from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_merge_module():
    repo_root = Path(__file__).resolve().parents[3]
    module_path = repo_root / "RP1_Project" / "merge_af_ba_panels.py"
    spec = importlib.util.spec_from_file_location("merge_af_ba_panels", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_merge_missing_unit_universe_reports_access_guidance(tmp_path: Path) -> None:
    merge = _load_merge_module()
    paths = merge.PathsConfig(
        repo_root=tmp_path,
        unit_universe_path=tmp_path / "missing_unit_universe.csv",
        af_root=tmp_path / "af_root",
        ba2001_root=tmp_path / "ba2001_root",
        ba2012_root=tmp_path / "ba2012_root",
        output_dir=tmp_path / "output",
    )

    with pytest.raises(merge.ValidationError) as excinfo:
        merge.load_unit_universe(paths)

    msg = str(excinfo.value)
    assert "Missing required Stage 3 input `unit_universe`" in msg
    assert "docs/data_access.md" in msg
    assert "README.md" in msg
    assert "Required by stage: merge_af_ba_panels.py (Stage 3)." in msg


def test_merge_missing_af_family_root_reports_access_guidance(tmp_path: Path) -> None:
    merge = _load_merge_module()
    paths = merge.PathsConfig(
        repo_root=tmp_path,
        unit_universe_path=tmp_path / "unit_universe.csv",
        af_root=tmp_path / "missing_af_root",
        ba2001_root=tmp_path / "ba2001_root",
        ba2012_root=tmp_path / "ba2012_root",
        output_dir=tmp_path / "output",
    )
    spec = merge.build_family_specs(paths)[0]

    with pytest.raises(merge.ValidationError) as excinfo:
        merge.discover_family_files(spec, partition_codes=["CZ"], repo_root=tmp_path)

    msg = str(excinfo.value)
    assert f"Missing required Stage 3 input `{spec.family_name}`" in msg
    assert "docs/data_access.md" in msg
    assert "README.md" in msg
    assert "Stage 2 RP1 active-fire export regeneration" in msg
