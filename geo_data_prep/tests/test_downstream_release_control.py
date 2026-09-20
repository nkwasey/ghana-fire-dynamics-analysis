from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace

from geo_data_prep.exports.contract import write_stage1_contract_manifest


def _cfg() -> SimpleNamespace:
    return SimpleNamespace(
        schema_version="1.0",
        contract=SimpleNamespace(
            stage="stage_1",
            name="geo_data_prep_stage1",
            version="1.1.0",
            canonical_upstream=True,
            downstreams_adapt_later=True,
        ),
        crs=SimpleNamespace(working_crs="EPSG:32630", plot_crs="EPSG:4326"),
        area_policy=SimpleNamespace(
            method="projected",
            projected_crs="EPSG:32630",
            geodesic_ellipsoid="WGS84",
            units="sq_km",
            include_method_metadata=True,
        ),
        qa=SimpleNamespace(
            enabled=True,
            thresholds={
                "overlap_share": {"warn_below": 0.95, "fail_below": 0.8},
                "area_relative_difference": {"warn_above": 0.01, "fail_above": 0.05},
                "unassigned_units": {"warn_above": 0, "fail_above": 0},
                "legacy_assignment_disagreement": {"warn_above": 0, "fail_above": 0},
                "invalid_geometries": {"warn_above": 0, "fail_above": 0},
            },
        ),
    )


def _extract_stage3_unit_universe_expected_columns(script_path: Path) -> list[str]:
    tree = ast.parse(script_path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "load_unit_universe":
            for stmt in node.body:
                if not isinstance(stmt, ast.Assign):
                    continue
                for target in stmt.targets:
                    if isinstance(target, ast.Name) and target.id == "expected_columns":
                        value = ast.literal_eval(stmt.value)
                        if not isinstance(value, list) or not all(
                            isinstance(item, str) for item in value
                        ):
                            raise AssertionError(
                                "Stage 3 expected_columns must remain a string list"
                            )
                        return value
    raise AssertionError(
        "Could not extract expected_columns from RP1_Project/merge_af_ba_panels.py"
    )


def test_stage1_contract_unit_universe_schema_matches_stage3_consumer(tmp_path: Path) -> None:
    out = write_stage1_contract_manifest(
        out_dir=tmp_path,
        cfg=_cfg(),
        zone_level_label="acz",
        district_level_label="district",
        zones_basename="acz",
        districts_basename="districts_within_acz",
    )
    manifest = json.loads(out.manifest_path.read_text(encoding="utf-8"))

    repo_root = Path(__file__).resolve().parents[2]
    stage3_expected = _extract_stage3_unit_universe_expected_columns(
        repo_root / "RP1_Project" / "merge_af_ba_panels.py"
    )

    assert manifest["logical_schema"]["unit_universe_csv"] == stage3_expected
    assert manifest["notes"]["schema_governance"] == {
        "downstream_revalidation_required_before_schema_change": True,
        "known_stage3_contract_consumers": ["RP1_Project/merge_af_ba_panels.py"],
        "unit_universe_and_boundary_schemas_require_contract_versioning_when_changed": True,
    }
