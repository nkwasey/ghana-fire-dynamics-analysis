from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

import rp1_analysis_v1.presentation_export as pe
from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.contracts import freeze
from rp1_analysis_v1.integration import RunValidationResult
from rp1_analysis_v1.paths import ProjectPaths
from rp1_analysis_v1.presentation import get_presentation_export_spec, load_presentation_export_registry

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "export_presentation_figures.py"
RUN_BASE = "qualified_presentation_fixture"
RUN_CLOSE = ROOT / "out" / "runs" / f"{RUN_BASE}_close"


def _not_run_authority() -> pe.RunFamilyAuthority:
    return pe.resolve_run_family(RUN_CLOSE, paths=ProjectPaths(ROOT), validate=False)


def _validation(state: str = "RESULTS_VALIDATED") -> RunValidationResult:
    return RunValidationResult(
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


def test_cli_help_smoke() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "--run-dir" in completed.stdout
    assert "--output-dir" in completed.stdout
    assert "--list" in completed.stdout
    assert "--figure" in completed.stdout


def test_cli_list_is_config_driven() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--list"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["schema"] == "rp1-presentation-export-list-v1"
    assert len(payload["exports"]) == 24
    by_id = {row["export_id"]: row for row in payload["exports"]}
    assert by_id["rq1_acz_seasonality"]["implementation_status"] == "IMPLEMENTED"
    assert by_id["rq1_district_departure"]["implementation_status"] == "IMPLEMENTED"
    assert by_id["rq4_mcd64a1_clusters"]["implementation_status"] == "IMPLEMENTED"
    assert by_id["rq4_viirs_recurrence"]["implementation_status"] == "IMPLEMENTED"


def test_list_catalogue_matches_governed_registry() -> None:
    paths = ProjectPaths(ROOT)
    registry = load_presentation_export_registry(paths=paths)
    listed = pe.list_presentation_exports(paths=paths)
    assert tuple(row["export_id"] for row in listed) == registry.export_ids
    assert tuple(row["group"] for row in listed) == tuple(item.group for item in registry.exports)


def test_valid_run_resolution_delegates_to_complete_run_validator(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    def fake_validate(*, paths: ProjectPaths, run_id: str) -> RunValidationResult:
        called["paths"] = paths
        called["run_id"] = run_id
        return _validation()

    monkeypatch.setattr(pe, "validate_run_authority", fake_validate)
    run = pe.resolve_run_family(RUN_CLOSE, paths=ProjectPaths(ROOT), validate=True)
    assert run.run_base == RUN_BASE
    assert run.publication_run.name == f"{RUN_BASE}_pub"
    assert run.secondary_run.name == f"{RUN_BASE}_sec"
    assert run.closeout_run.name == f"{RUN_BASE}_close"
    assert run.validation.status == "PASS"
    assert called["run_id"] == RUN_BASE


def test_invalid_run_rejection_missing_and_wrong_member() -> None:
    paths = ProjectPaths(ROOT)
    with pytest.raises(pe.RunAuthorityError, match="does not exist"):
        pe.resolve_run_family(ROOT / "out" / "runs" / "missing_close", paths=paths)
    with pytest.raises(pe.RunAuthorityError, match="closeout member"):
        pe.resolve_run_family(ROOT / "out" / "runs" / f"{RUN_BASE}_pub", paths=paths, validate=False)


def test_run_configuration_compatibility_accepts_only_presentation_registry_extension() -> None:
    run = _not_run_authority()
    pe.validate_run_configuration_compatibility(run, paths=ProjectPaths(ROOT))


def test_run_configuration_compatibility_accepts_realised_presentation_registry_symmetrically(
    tmp_path: Path,
) -> None:
    run = _not_run_authority()
    copied = tmp_path / run.closeout_run.name
    shutil.copytree(run.closeout_run, copied)
    realised_path = copied / "00_scaffold/realised_configuration.json"
    realised = json.loads(realised_path.read_text(encoding="utf-8"))
    current = load_configuration_bundle(ROOT / "config")
    realised["contracts"]["figure_contract.yml"] = current.figure.to_dict()
    realised_path.write_text(
        json.dumps(realised, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    mirrored = replace(run, closeout_run=copied)
    pe.validate_run_configuration_compatibility(mirrored, paths=ProjectPaths(ROOT))


def test_source_resolution_and_selector_are_governed() -> None:
    paths = ProjectPaths(ROOT)
    run = _not_run_authority()
    spec = get_presentation_export_spec("rq1_acz_seasonality", paths=paths)
    source = pe.resolve_source(spec, run, paths=paths)
    assert source.source_identity == "seasonality_spatial_organisation_presentation_source"
    assert source.project_relative_path.endswith("01_rq1_spatial_scale/figure_data/FD_F3.csv")
    assert source.frame is not None
    assert source.selected_rows == len(source.frame) > 0
    assert set(source.frame["panel"].astype(str)) == {"acz_seasonality"}
    assert len(source.sha256) == 64


def test_source_selector_missing_column_fails_closed() -> None:
    paths = ProjectPaths(ROOT)
    run = _not_run_authority()
    spec = get_presentation_export_spec("rq1_acz_seasonality", paths=paths)
    mutated = replace(spec, selector=freeze({"column": "not_a_column", "equals": "x"}))
    with pytest.raises(pe.SourceResolutionError, match="selector column"):
        pe.resolve_source(mutated, run, paths=paths)


def test_malformed_csv_source_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    paths = ProjectPaths(ROOT)
    run = _not_run_authority()
    spec = get_presentation_export_spec("rq1_acz_seasonality", paths=paths)

    def boom(*args: object, **kwargs: object) -> pd.DataFrame:
        raise ValueError("malformed")

    monkeypatch.setattr(pe.pd, "read_csv", boom)
    with pytest.raises(pe.SourceResolutionError, match="Unable to read configured CSV source"):
        pe.resolve_source(spec, run, paths=paths)


def test_geometry_resolution_uses_data_schema_required_members() -> None:
    paths = ProjectPaths(ROOT)
    geometry = pe.resolve_geometry_dependency("district+acz", paths=paths)
    assert set(geometry.members) == {"district", "acz"}
    assert len(geometry.members["district"]) == 5
    assert len(geometry.members["acz"]) == 5
    assert all(len(value) == 64 for hashes in geometry.hashes.values() for value in hashes)


def test_renderer_registry_lookup_and_unknown_rejection() -> None:
    registry = pe.build_core_renderer_registry()
    expected = {
        "acz_categorical_context_map",
        "support_acz_map",
        "acz_choropleth",
        "district_choropleth",
        "seasonality_lines",
        "local_moran_categorical_map",
        "district_seasonal_heatmap",
        "district_circular_mean_timing",
        "resultant_length_boxplot",
        "single_trajectory_with_sen",
        "grid_trajectory_with_sen",
        "stacked_proportions",
        "coefficient_or_plot",
        "standardised_probability_pairs",
        "cluster_membership_map",
        "cluster_recurrence_map",
    }
    assert set(registry.identities) == expected
    assert callable(registry.resolve("seasonality_lines"))
    assert callable(registry.resolve("single_trajectory_with_sen"))
    assert callable(registry.resolve("grid_trajectory_with_sen"))
    assert callable(registry.resolve("stacked_proportions"))
    assert callable(registry.resolve("coefficient_or_plot"))
    assert callable(registry.resolve("standardised_probability_pairs"))


def test_renderer_registry_rejects_duplicate_registration() -> None:
    registry = pe.RendererRegistry()
    renderer = pe.build_core_renderer_registry().resolve("seasonality_lines")
    registry.register("x", renderer)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("x", renderer)


def test_deterministic_file_naming_and_format_rejection() -> None:
    spec = get_presentation_export_spec("rq1_acz_seasonality", paths=ProjectPaths(ROOT))
    assert pe.deterministic_output_name(spec, "png") == "rq1_acz_seasonality.png"
    assert pe.deterministic_output_name(spec, "pdf") == "rq1_acz_seasonality.pdf"
    with pytest.raises(pe.PresentationOutputError, match="not configured"):
        pe.deterministic_output_name(spec, "svg")


def test_output_destination_collision_and_run_nesting_fail_closed(tmp_path: Path) -> None:
    run = _not_run_authority()
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(pe.PresentationOutputError, match="already exists"):
        pe.validate_output_destination(existing, run=run)
    nested = run.closeout_run / "presentation"
    with pytest.raises(pe.PresentationOutputError, match="outside the governed run root"):
        pe.validate_output_destination(nested, run=run)


def test_manifest_record_contains_required_provenance_fields(tmp_path: Path) -> None:
    paths = ProjectPaths(ROOT)
    bundle = load_configuration_bundle(ROOT / "config")
    run = _not_run_authority()
    spec = get_presentation_export_spec("rq1_acz_seasonality", bundle.figure)
    source = pe.resolve_source(spec, run, paths=paths)
    generated = tmp_path / "rq1_acz_seasonality.png"
    generated.write_bytes(b"\x89PNG\r\n\x1a\nabc")
    record = pe.construct_manifest_record(
        spec=spec,
        run=run,
        source=source,
        bundle=bundle,
        generated_path=generated,
        fmt="png",
    ).as_dict()
    assert set(record) == {
        "export_id", "group", "renderer", "run_identity", "semantic_source_identity",
        "exact_source_path", "source_sha256", "configuration_sha256", "generated_path",
        "generated_sha256", "format", "dimensions", "status",
    }
    assert record["dimensions"]["width_cm"] == 20.0
    assert record["dimensions"]["height_cm"] == 15.0
    assert record["dimensions"]["raster_dpi"] == 300


def test_run_tree_pre_post_immutability_snapshot() -> None:
    run = _not_run_authority()
    before = pe.snapshot_run_tree(run, project_root=ROOT)
    after = pe.snapshot_run_tree(run, project_root=ROOT)
    pe.assert_run_tree_unchanged(before, after)
    assert before


def test_run_tree_mutation_is_detected(tmp_path: Path) -> None:
    pub = tmp_path / "x_pub"; sec = tmp_path / "x_sec"; close = tmp_path / "x_close"
    for member in (pub, sec, close):
        member.mkdir()
    target = pub / "a.txt"; target.write_text("a", encoding="utf-8")
    run = pe.RunFamilyAuthority("x", pub, sec, close, _validation())
    before = pe.snapshot_run_tree(run, project_root=tmp_path)
    target.write_text("b", encoding="utf-8")
    after = pe.snapshot_run_tree(run, project_root=tmp_path)
    with pytest.raises(pe.RunAuthorityError, match="modified during export"):
        pe.assert_run_tree_unchanged(before, after)


def test_required_satscan_state_never_treats_external_required_as_zero() -> None:
    spec = get_presentation_export_spec("rq4_mcd64a1_clusters", paths=ProjectPaths(ROOT))
    base = _not_run_authority()
    blocked = replace(base, validation=_validation("EXTERNAL_RESULTS_REQUIRED"))
    with pytest.raises(pe.RunAuthorityError, match="RESULTS_VALIDATED"):
        pe.validate_required_result_state(spec, blocked)
    allowed = replace(base, validation=_validation("RESULTS_VALIDATED"))
    pe.validate_required_result_state(spec, allowed)

def test_rq4_secondary_authority_rejects_scenario_product_mismatch() -> None:
    paths = ProjectPaths(ROOT)
    run = replace(_not_run_authority(), validation=_validation("RESULTS_VALIDATED"))
    spec = replace(get_presentation_export_spec("rq4_mcd64a1_clusters", paths=paths), scenario="VIIRS_STP_PRIMARY")
    source = pe.resolve_source(get_presentation_export_spec("rq4_mcd64a1_clusters", paths=paths), run, paths=paths)
    with pytest.raises(pe.SourceResolutionError, match="scenario/product linkage"):
        pe.resolve_secondary_export_authority(spec, run, source, paths=paths)


def test_full_core_export_seasonality_is_external_deterministic_and_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = ProjectPaths(ROOT)
    run = _not_run_authority()
    monkeypatch.setattr(pe, "resolve_run_family", lambda *args, **kwargs: run)
    destination = tmp_path / "presentation"
    before = pe.snapshot_run_tree(run, project_root=ROOT)
    report = pe.export_one_presentation_figure(
        run_dir=RUN_CLOSE,
        output_dir=destination,
        export_id="rq1_acz_seasonality",
        paths=paths,
    )
    after = pe.snapshot_run_tree(run, project_root=ROOT)
    pe.assert_run_tree_unchanged(before, after)
    assert report["status"] == "PASS"
    assert report["source_run_unchanged"] is True
    assert (destination / "rq1_acz_seasonality.png").read_bytes().startswith(b"\x89PNG")
    assert (destination / "rq1_acz_seasonality.pdf").read_bytes().startswith(b"%PDF")
    for manifest in (
        "presentation_export_manifest.json",
        "presentation_export_source_inventory.csv",
        "presentation_export_output_inventory.csv",
    ):
        assert (destination / manifest).is_file()
    payload = json.loads((destination / "presentation_export_manifest.json").read_text(encoding="utf-8"))
    assert payload["source_run_read_only"] is True
    assert payload["exports"][0]["dimensions"]["width_cm"] == 20.0


def test_full_core_export_rq4_cluster_is_manifest_bound_and_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = ProjectPaths(ROOT)
    run = replace(_not_run_authority(), validation=_validation("RESULTS_VALIDATED"))
    monkeypatch.setattr(pe, "resolve_run_family", lambda *args, **kwargs: run)
    destination = tmp_path / "presentation"
    before = pe.snapshot_run_tree(run, project_root=ROOT)
    report = pe.export_one_presentation_figure(
        run_dir=RUN_CLOSE,
        output_dir=destination,
        export_id="rq4_mcd64a1_clusters",
        paths=paths,
    )
    after = pe.snapshot_run_tree(run, project_root=ROOT)
    pe.assert_run_tree_unchanged(before, after)
    assert report["status"] == "PASS"
    manifest = json.loads((destination / "presentation_export_manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_run_read_only"] is True
    inventory = pd.read_csv(destination / "presentation_export_source_inventory.csv")
    assert {"secondary_status", "secondary_publication_source_manifest", "secondary_run_registry", "secondary_input_audit", "secondary_result_report", "secondary_result_cluster", "secondary_result_membership"}.issubset(set(inventory["kind"].astype(str)))
    assert (destination / "rq4_mcd64a1_clusters.png").read_bytes().startswith(b"\x89PNG")
    assert (destination / "rq4_mcd64a1_clusters.pdf").read_bytes().startswith(b"%PDF")


def test_output_writer_rejects_collision(tmp_path: Path) -> None:
    writer = pe.PresentationOutputWriter(tmp_path)
    writer.write_bytes("x.png", b"one")
    with pytest.raises(pe.PresentationOutputError, match="collision"):
        writer.write_bytes("x.png", b"two")



def test_selection_architecture_supports_future_group_and_all_modes() -> None:
    registry = load_presentation_export_registry(paths=ProjectPaths(ROOT))
    one = pe.select_presentation_exports(registry=registry, export_id="rq1_acz_seasonality")
    assert tuple(item.export_id for item in one) == ("rq1_acz_seasonality",)
    rq4 = pe.select_presentation_exports(registry=registry, group="rq4")
    assert len(rq4) == 4 and all(item.group == "rq4" for item in rq4)
    assert pe.select_presentation_exports(registry=registry, all_exports=True) == registry.exports
    with pytest.raises(pe.PresentationExportError, match="exactly one"):
        pe.select_presentation_exports(registry=registry, export_id="rq1_acz_seasonality", all_exports=True)


def test_generated_output_validator_fails_closed_on_bad_signature(tmp_path: Path) -> None:
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not-a-png")
    with pytest.raises(pe.PresentationOutputError, match="signature"):
        pe.validate_generated_output(bad, "png")

def test_cli_figure_requires_run_and_output() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--figure", "rq1_acz_seasonality"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 2
    assert "requires both --run-dir and --output-dir" in completed.stderr
