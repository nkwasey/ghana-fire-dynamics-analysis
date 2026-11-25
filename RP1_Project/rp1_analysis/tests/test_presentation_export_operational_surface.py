from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
import pytest

import rp1_analysis_v1.presentation_export as pe
from generated_run_reference import selected_run_base
from rp1_analysis_v1.paths import ProjectPaths
from rp1_analysis_v1.presentation import load_presentation_export_registry

ROOT = Path(__file__).resolve().parents[1]
RUN_BASE = "synthetic_presentation_test"
RUN_CLOSE = ROOT / "out" / "runs" / f"{RUN_BASE}_close"
SCRIPT = ROOT / "scripts" / "export_presentation_figures.py"


def test_generated_run_requires_explicit_selection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for suffix in ("pub", "sec", "close"):
        (tmp_path / "out/runs" / f"unselected_{suffix}").mkdir(parents=True)
    monkeypatch.delenv("RP1_ANALYSIS_TEST_RUN", raising=False)
    assert selected_run_base(tmp_path) == "generated_integration_selection_required"
    monkeypatch.setenv("RP1_ANALYSIS_TEST_RUN", "chosen_run")
    assert selected_run_base(tmp_path) == "chosen_run"
    monkeypatch.setenv("RP1_ANALYSIS_TEST_RUN", "../invalid")
    with pytest.raises(ValueError, match="portable"):
        selected_run_base(tmp_path)


def _validation(state: str = "RESULTS_VALIDATED") -> pe.RunValidationResult:
    return pe.RunValidationResult(
        run_id=RUN_BASE,
        status="PASS",
        publication_files=1,
        secondary_files=1,
        closeout_files=1,
        publication_tables=1,
        publication_figures=1,
        secondary_external_state=state,
        output_inventory=pd.DataFrame(columns=["path", "sha256", "size_bytes"]),
        checks=(),
    )


def _patch_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, state: str = "RESULTS_VALIDATED") -> pe.RunFamilyAuthority:
    """Isolate export mechanics from empirical sources and scientific renderers.

    The renderer/source doubles are explicitly synthetic. Real renderer and
    authority validation have their own integration suites. These tests exercise
    orchestration, result-state guards, hashing, immutability and collisions.
    """
    root = tmp_path / "synthetic_project"
    shutil.copytree(ROOT / "config", root / "config")
    shutil.copy2(ROOT / "pyproject.toml", root / "pyproject.toml")
    members = tuple(root / "out/runs" / f"{RUN_BASE}_{suffix}" for suffix in ("pub", "sec", "close"))
    for member in members:
        member.mkdir(parents=True)
        (member / "SYNTHETIC_TEST_ONLY.txt").write_text("No empirical results or engine execution.\n")
    source_path = members[0] / "synthetic_source.csv"
    source_path.write_text("value\n1\n2\n", encoding="utf-8")
    run = pe.RunFamilyAuthority(RUN_BASE, *members, _validation(state))
    monkeypatch.setitem(globals(), "ROOT", root)
    monkeypatch.setitem(globals(), "RUN_CLOSE", members[2])
    monkeypatch.setattr(pe, "resolve_run_family", lambda *args, **kwargs: run)
    monkeypatch.setattr(pe, "resolve_source", lambda spec, *args, **kwargs: pe.SourceAuthority(
        "synthetic_test_only", source_path, source_path.relative_to(root).as_posix(),
        _sha(source_path), source_path.stat().st_size, pd.read_csv(source_path), 2,
    ))
    monkeypatch.setattr(pe, "resolve_geometry_dependency", lambda dependency_id, **kwargs: pe.GeometryAuthority(dependency_id, {}, {}))
    monkeypatch.setattr(pe, "resolve_secondary_export_authority", lambda *args, **kwargs: ())
    from rp1_analysis_v1.figures import RenderedFigure
    # Valid format signatures with deterministic test payloads. Pixel/figure
    # correctness belongs to the separately tested scientific renderers.
    def render(frame, *, spec, context):
        return RenderedFigure(b"\x89PNG\r\n\x1a\nSYNTHETIC_TEST_ONLY", b"%PDF-1.4\nSYNTHETIC_TEST_ONLY", 1, 1, 72)
    registry = load_presentation_export_registry(paths=ProjectPaths(root))
    monkeypatch.setattr(pe, "build_core_renderer_registry", lambda: pe.RendererRegistry({spec.renderer_identity: render for spec in registry.exports}))
    return run


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_script_module():
    scripts_dir = str(SCRIPT.parent)
    sys.path.insert(0, scripts_dir)
    try:
        spec = importlib.util.spec_from_file_location("rp1_presentation_export_script", SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(scripts_dir)


def test_configured_selection_routes_complete_estate_and_each_group() -> None:
    registry = load_presentation_export_registry(paths=ProjectPaths(ROOT))
    assert len(pe.select_presentation_exports(registry=registry, all_exports=True)) == 26
    expected = {"study": 2, "rq1": 9, "rq2": 7, "rq3": 4, "rq4": 4}
    for group, count in expected.items():
        selected = pe.select_presentation_exports(registry=registry, group=group)
        assert len(selected) == count
        assert all(item.group == group for item in selected)


def test_invalid_export_and_group_messages_list_valid_values() -> None:
    registry = load_presentation_export_registry(paths=ProjectPaths(ROOT))
    with pytest.raises(pe.PresentationExportError, match="Valid export IDs"):
        pe.select_presentation_exports(registry=registry, export_id="not-an-export")
    with pytest.raises(pe.PresentationExportError, match="Valid groups"):
        pe.select_presentation_exports(registry=registry, group="not-a-group")


@pytest.mark.parametrize("group", ["study", "rq1", "rq2", "rq3", "rq4"])
def test_public_script_routes_every_group_without_scientific_cli_flags(
    group: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script_module()
    monkeypatch.setattr(module, "require_operational_preflight", lambda **kwargs: None)
    captured: dict[str, object] = {}

    def fake_export(**kwargs):
        captured.update(kwargs)
        return {
            "status": "PASS",
            "failed_exports": 0,
            "manifest": "manifest.json",
            "report": "report.md",
        }

    monkeypatch.setattr(pe, "export_presentation_figure_estate", fake_export)
    rc = module.main(
        [
            "--run-dir",
            str(RUN_CLOSE),
            "--output-dir",
            str(tmp_path / group),
            "--group",
            group,
        ]
    )
    assert rc == 0
    assert captured["group"] == group
    assert captured["export_id"] is None
    assert captured["all_exports"] is False


def test_public_script_routes_selected_figure_and_all(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_script_module()
    monkeypatch.setattr(module, "require_operational_preflight", lambda **kwargs: None)
    calls: list[dict[str, object]] = []

    def fake_export(**kwargs):
        calls.append(kwargs)
        return {"status": "PASS", "failed_exports": 0, "manifest": "m", "report": "r"}

    monkeypatch.setattr(pe, "export_presentation_figure_estate", fake_export)
    assert module.main(["--run-dir", str(RUN_CLOSE), "--output-dir", str(tmp_path / "one"), "--figure", "rq2_coastal_trend"]) == 0
    assert calls[-1]["export_id"] == "rq2_coastal_trend"
    assert calls[-1]["all_exports"] is False
    assert module.main(["--run-dir", str(RUN_CLOSE), "--output-dir", str(tmp_path / "all"), "--all", "--format", "png"]) == 0
    assert calls[-1]["all_exports"] is True
    assert calls[-1]["formats"] == ["png"]


def test_selected_export_png_only_and_collision_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = _patch_run(monkeypatch, tmp_path)
    before = pe.snapshot_run_tree(run, project_root=ROOT)
    destination = tmp_path / "selected"
    report = pe.export_presentation_figure_estate(
        run_dir=RUN_CLOSE,
        output_dir=destination,
        export_id="rq2_coastal_trend",
        formats=("png",),
        paths=ProjectPaths(ROOT),
    )
    assert report["status"] == "PASS"
    assert report["generated_figure_files"] == 1
    assert (destination / "rq2" / "rq2_coastal_trend.png").is_file()
    assert not (destination / "rq2" / "rq2_coastal_trend.pdf").exists()
    with pytest.raises(pe.PresentationOutputError, match="already exists"):
        pe.export_presentation_figure_estate(
            run_dir=RUN_CLOSE,
            output_dir=destination,
            export_id="rq2_coastal_trend",
            paths=ProjectPaths(ROOT),
        )
    after = pe.snapshot_run_tree(run, project_root=ROOT)
    pe.assert_run_tree_unchanged(before, after)


def test_unvalidated_satscan_group_fails_closed_without_zero_cluster_graphics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _patch_run(monkeypatch, tmp_path, "EXTERNAL_RESULTS_REQUIRED")
    before = pe.snapshot_run_tree(run, project_root=ROOT)
    destination = tmp_path / "rq4-blocked"
    report = pe.export_presentation_figure_estate(
        run_dir=RUN_CLOSE,
        output_dir=destination,
        group="rq4",
        paths=ProjectPaths(ROOT),
    )
    assert report["status"] == "FAIL"
    assert report["failed_exports"] == 4
    manifest = json.loads((destination / pe.AGGREGATE_MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["summary"]["generated_figure_files"] == 0
    assert all(row["status"] == "FAIL" for row in manifest["records"])
    assert all("RESULTS_VALIDATED" in row["error"] for row in manifest["records"])
    assert not any((destination / "rq4").iterdir())
    after = pe.snapshot_run_tree(run, project_root=ROOT)
    pe.assert_run_tree_unchanged(before, after)


def test_missing_source_and_geometry_become_explicit_failed_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_run(monkeypatch, tmp_path)
    original_source = pe.resolve_source
    monkeypatch.setattr(pe, "resolve_source", lambda *args, **kwargs: (_ for _ in ()).throw(pe.SourceResolutionError("missing source witness")))
    source_dest = tmp_path / "missing-source"
    source_report = pe.export_presentation_figure_estate(
        run_dir=RUN_CLOSE,
        output_dir=source_dest,
        export_id="rq2_coastal_trend",
        paths=ProjectPaths(ROOT),
    )
    assert source_report["status"] == "FAIL"
    source_manifest = json.loads((source_dest / pe.AGGREGATE_MANIFEST_NAME).read_text())
    assert "missing source witness" in source_manifest["records"][0]["error"]

    monkeypatch.setattr(pe, "resolve_source", original_source)
    monkeypatch.setattr(pe, "resolve_geometry_dependency", lambda *args, **kwargs: (_ for _ in ()).throw(pe.SourceResolutionError("missing geometry witness")))
    geometry_dest = tmp_path / "missing-geometry"
    geometry_report = pe.export_presentation_figure_estate(
        run_dir=RUN_CLOSE,
        output_dir=geometry_dest,
        export_id="rq1_district_long_run_rate",
        paths=ProjectPaths(ROOT),
    )
    assert geometry_report["status"] == "FAIL"
    geometry_manifest = json.loads((geometry_dest / pe.AGGREGATE_MANIFEST_NAME).read_text())
    assert "missing geometry witness" in geometry_manifest["records"][0]["error"]


def test_complete_all_export_has_full_manifest_hashes_inventory_and_immutable_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = _patch_run(monkeypatch, tmp_path)
    before = pe.snapshot_run_tree(run, project_root=ROOT)
    destination = tmp_path / "all"
    report = pe.export_presentation_figure_estate(
        run_dir=RUN_CLOSE,
        output_dir=destination,
        all_exports=True,
        paths=ProjectPaths(ROOT),
    )
    assert report["status"] == "PASS"
    assert report["requested_exports"] == 26
    assert report["successful_exports"] == 26
    assert report["failed_exports"] == 0
    assert report["generated_figure_files"] == 52

    manifest_path = destination / pe.AGGREGATE_MANIFEST_NAME
    report_path = destination / pe.AGGREGATE_REPORT_NAME
    inventory_path = destination / pe.AGGREGATE_OUTPUT_INVENTORY_NAME
    assert manifest_path.is_file() and report_path.is_file() and inventory_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema"] == pe.AGGREGATE_MANIFEST_SCHEMA
    assert manifest["source_run"]["run_identity"] == RUN_BASE
    assert manifest["analysis_schema"] == "rp1-analysis-v1.1"
    assert manifest["data_schema"] == "rp1-data-schema-v1.2"
    assert len(manifest["requested_export_ids"]) == 26
    assert len(manifest["records"]) == 52
    required_record_fields = {
        "export_id", "group", "renderer_identity", "run_identity", "analysis_schema",
        "data_schema", "source_semantic_identity", "source_path", "source_sha256",
        "geometry", "configuration_sha256", "result_state_requirement", "output_path",
        "output_sha256", "output_format", "dimensions", "status", "error",
    }
    for row in manifest["records"]:
        assert required_record_fields.issubset(row)
        assert row["status"] == "PASS"
        output = destination / row["output_path"]
        assert output.is_file()
        assert _sha(output) == row["output_sha256"]

    group_files = Counter(path.parent.name for path in destination.glob("*/*") if path.is_file())
    assert group_files == {"study": 4, "rq1": 18, "rq2": 14, "rq3": 8, "rq4": 8}
    inventory = pd.read_csv(inventory_path)
    assert len(inventory) == 54
    for row in inventory.itertuples(index=False):
        path = destination / row.path
        assert path.is_file()
        assert _sha(path) == row.sha256

    after = pe.snapshot_run_tree(run, project_root=ROOT)
    pe.assert_run_tree_unchanged(before, after)


def test_selected_export_estate_is_byte_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_run(monkeypatch, tmp_path)
    first = tmp_path / "one-a"
    second = tmp_path / "one-b"
    for destination in (first, second):
        result = pe.export_presentation_figure_estate(
            run_dir=RUN_CLOSE,
            output_dir=destination,
            export_id="rq2_coastal_trend",
            paths=ProjectPaths(ROOT),
        )
        assert result["status"] == "PASS"
    first_files = sorted(path.relative_to(first).as_posix() for path in first.rglob("*") if path.is_file())
    second_files = sorted(path.relative_to(second).as_posix() for path in second.rglob("*") if path.is_file())
    assert first_files == second_files
    assert all((first / rel).read_bytes() == (second / rel).read_bytes() for rel in first_files)
