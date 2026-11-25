"""Test prerequisites for source-only and generated-input integration checks."""
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
# These modules exercise real generated panels and/or presentation sources.
# The clean distribution deliberately contains neither. The named prerequisite
# is checked before execution, rather than treating missing data as a test pass.
PREREQUISITES = {
    "data/raw/fire_panel_manifest.json": {
        "test_optional_satscan_integration.py", "test_data_contract.py", "test_rq1_spatial_scale.py", "test_rq2_trend_robustness.py",
        "test_rq3_design_contract.py", "test_rq3_observability.py", "test_rq3_protocol_outputs.py",
        "test_rq3_mcd64a1_provenance.py", "test_secondary_clusters.py", "test_satscan_publication_fixture.py",
        "test_data_schema_contract.py", "test_runtime_input_validation_contract.py", "test_data_provenance.py",
        "test_map_renderer_policy.py", "test_cluster_recurrence_presentation.py",
    },
}


def pytest_addoption(parser):
    parser.addoption('--release-tree-checks', action='store_true', default=False,
                     help='Require this checkout to be a clean distribution with no generated outputs')


def pytest_collection_modifyitems(items):
    for item in items:
        if item.originalname in {
            'test_release_out_directory_is_not_shipped_before_execution',
            'test_repository_inventory_contains_no_persistent_release_contaminants',
        } and not item.config.getoption('--release-tree-checks'):
            item.add_marker(pytest.mark.skip(reason='Clean-distribution check: use --release-tree-checks on an isolated release tree; local run outputs are preserved'))
        for relative, modules in PREREQUISITES.items():
            if item.path.name in modules and not (ROOT / relative).exists():
                item.add_marker(pytest.mark.skip(reason=f"Requires generated integration prerequisite: {relative}; run the documented workflow first"))


# Individual data-bound checks inside otherwise synthetic/config-only modules.
ACTUAL_INPUT_TESTS = {
    "test_validate_inputs_script_is_cwd_independent",
    "test_governed_input_validation_report_is_complete",
    "test_admitted_manifest_staged_paths_are_portable",
    "test_current_rq2_series_check_admissibility_and_reference_parity",
    "test_rq3_governed_fields_exist_in_district_panel",
    "test_all_hashed_inputs_are_exposed_and_stay_within_root",
    "test_required_analytical_files_present", "test_geometry_component_completeness",
    "test_input_sha256_inventory_matches_bytes",
    "test_geometry_resolution_uses_data_schema_required_members",
    "test_paired_map_viewports_remain_equal_with_different_ancillary_content",
    "test_f3_maps_keep_sign_and_local_classes_distinct_without_colour",
}

def pytest_runtest_setup(item):
    if item.originalname in ACTUAL_INPUT_TESTS and not (ROOT / "data/raw/fire_panel_manifest.json").is_file():
        pytest.skip("Requires generated analysis panel inputs; run the documented workflow first")

