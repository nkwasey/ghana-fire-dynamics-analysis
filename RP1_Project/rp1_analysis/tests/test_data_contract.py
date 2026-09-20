from __future__ import annotations

from pathlib import Path
from dataclasses import replace
import copy

import numpy as np
import pandas as pd
import pytest
from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.data_io import load_data_authorities
from rp1_analysis_v1.paths import ProjectPaths
from rp1_analysis_v1.validation import (
    DataContractError,
    complete_year_overlap_temporal_mask,
    long_run_temporal_mask,
    overlap_monthly_temporal_mask,
    reconcile_district_to_acz,
    validate_data_authorities,
    validate_geometry,
    validate_geometry_panel_reconciliation,
    validate_manifest,
    validate_panel,
)

SUBPROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def paths() -> ProjectPaths:
    return ProjectPaths.discover(SUBPROJECT)


@pytest.fixture(scope="module")
def config(paths: ProjectPaths):
    return load_configuration_bundle(paths.root / "config")


@pytest.fixture(scope="module")
def authorities(paths: ProjectPaths, config):
    return load_data_authorities(paths, config.data_schema)


def _validate_acz(frame: pd.DataFrame, authorities, config) -> None:
    validate_panel(
        frame,
        level="acz",
        manifest=authorities.manifest,
        merge_summary=authorities.merge_summary,
        analysis=config.analysis,
        data_schema=config.data_schema,
    )


def test_governed_file_loading(authorities) -> None:
    assert authorities.acz_panel.shape == (1440, 111)
    assert authorities.district_panel.shape == (74880, 111)
    assert len(authorities.acz_geometry) == 5
    assert len(authorities.district_geometry) == 260
    assert authorities.manifest["merge_schema_version"] == "rp1_fire_panel_consolidated_v2"


def test_real_schema_fixture_preserves_zero_and_missing(authorities) -> None:
    sample = authorities.district_panel.loc[
        authorities.district_panel["unit_id"].eq("Ablekuma_Central_Municipal"),
        ["yyyymm", "viirs_supported_flag", "viirs_det_primary", "viirs_structural_missing_flag"],
    ]
    unsupported = sample.loc[sample["yyyymm"].eq(201112)].iloc[0]
    supported = sample.loc[sample["yyyymm"].eq(201202)].iloc[0]
    assert int(unsupported["viirs_supported_flag"]) == 0
    assert pd.isna(unsupported["viirs_det_primary"])
    assert int(unsupported["viirs_structural_missing_flag"]) == 1
    assert int(supported["viirs_supported_flag"]) == 1
    assert not pd.isna(supported["viirs_det_primary"])
    assert int(supported["viirs_structural_missing_flag"]) == 0


def test_missing_required_column_fails(authorities, config) -> None:
    broken = authorities.acz_panel.drop(columns=["viirs_det_primary"])
    with pytest.raises(DataContractError, match="data-schema order; missing"):
        _validate_acz(broken, authorities, config)


def test_unexpected_column_fails(authorities, config) -> None:
    broken = authorities.acz_panel.copy()
    broken["unexpected_runtime_column"] = 0
    with pytest.raises(DataContractError, match="data-schema order;.*extra"):
        _validate_acz(broken, authorities, config)


def test_wrong_datatype_fails(authorities, config) -> None:
    broken = authorities.acz_panel.copy()
    broken["yyyymm"] = broken["yyyymm"].astype(str)
    with pytest.raises(DataContractError, match="Dtype violations"):
        _validate_acz(broken, authorities, config)


def test_duplicate_key_fails(authorities, config) -> None:
    broken = authorities.acz_panel.copy()
    broken.loc[1, ["unit_id", "yyyymm"]] = broken.loc[0, ["unit_id", "yyyymm"]].to_numpy()
    with pytest.raises(DataContractError, match="duplicate primary-key"):
        _validate_acz(broken, authorities, config)


def test_invalid_yyyymm_fails(authorities, config) -> None:
    broken = authorities.acz_panel.copy()
    broken.loc[0, "yyyymm"] = 200113
    broken.loc[0, "year"] = 2001
    broken.loc[0, "month"] = 13
    with pytest.raises(DataContractError, match="categorical domain month|yyyymm"):
        _validate_acz(broken, authorities, config)


def test_incomplete_time_spine_fails(authorities, config) -> None:
    broken = authorities.acz_panel.drop(index=0).reset_index(drop=True)
    with pytest.raises(DataContractError, match="incomplete monthly spine|temporal range"):
        _validate_acz(broken, authorities, config)


def test_expected_temporal_range_fails(authorities, config) -> None:
    broken = authorities.acz_panel.copy()
    first = broken.index[broken["unit_id"].eq("coastal_zone")][0]
    broken.loc[first, "yyyymm"] = 200012
    broken.loc[first, "year"] = 2000
    broken.loc[first, "month"] = 12
    with pytest.raises(DataContractError, match="below minimum|temporal range|incomplete monthly spine"):
        _validate_acz(broken, authorities, config)


def test_structural_missingness_population_outside_support_fails(authorities, config) -> None:
    broken = authorities.acz_panel.copy()
    idx = broken.index[broken["yyyymm"].eq(201112)][0]
    broken.loc[idx, "viirs_det_primary"] = 0.0
    with pytest.raises(DataContractError, match="outside governed source support"):
        _validate_acz(broken, authorities, config)


def test_supported_zero_must_not_become_missing(authorities, config) -> None:
    broken = authorities.acz_panel.copy()
    candidates = broken.index[
        broken["viirs_supported_flag"].eq(1) & broken["viirs_det_primary"].eq(0)
    ]
    assert len(candidates) > 0
    broken.loc[candidates[0], "viirs_det_primary"] = np.nan
    with pytest.raises(DataContractError, match="missing despite governed source support"):
        _validate_acz(broken, authorities, config)


def test_denominator_zero_exclusion_and_mask_counts(authorities, config) -> None:
    summary = validate_data_authorities(authorities, config.analysis, config.data_schema)
    assert summary.acz_count == 5
    assert summary.district_spatial_universe_count == 260
    assert summary.long_run_eligible_count == 250
    assert summary.paired_eligible_count == 249
    long_excluded = summary.long_run_mask.units.loc[~summary.long_run_mask.units["eligible"]]
    paired_excluded = summary.paired_mask.units.loc[~summary.paired_mask.units["eligible"]]
    assert len(long_excluded) == 10
    assert len(paired_excluded) == 11
    assert long_excluded["exclusion_reasons"].eq("primary_denominator_zero_or_nonpositive").all()
    assert paired_excluded["exclusion_reasons"].eq("primary_denominator_zero_or_nonpositive").all()
    assert "Accra_Metropolis" not in set(long_excluded["unit_id"])
    assert "Accra_Metropolis" in set(paired_excluded["unit_id"])


def test_temporal_masks_use_frozen_windows(authorities, config) -> None:
    acz = authorities.acz_panel
    assert int(long_run_temporal_mask(acz, config.analysis).sum()) == 1440
    assert int(overlap_monthly_temporal_mask(acz, config.analysis).sum()) == 775
    assert int(complete_year_overlap_temporal_mask(acz, config.analysis).sum()) == 720
    district = authorities.district_panel
    assert int(overlap_monthly_temporal_mask(district, config.analysis).sum()) == 40300
    assert int(complete_year_overlap_temporal_mask(district, config.analysis).sum()) == 37440


def test_population_authority_preserves_exclusion_reasons(authorities, config) -> None:
    summary = validate_data_authorities(authorities, config.analysis, config.data_schema)
    row = summary.population_authority.set_index("population_name").loc["paired_ba_viirs_district"]
    assert int(row["candidate_units"]) == 260
    assert int(row["retained_units"]) == 249
    assert int(row["excluded_units"]) == 11
    assert row["exclusion_reasons"] == "primary_denominator_zero_or_nonpositive:11"
    assert row["temporal_start"] == "2012-02"
    assert row["temporal_end"] == "2024-12"


def test_analytical_population_mismatch_fails_closed(authorities, config) -> None:
    study = copy.deepcopy(config.analysis.to_dict()["study"])
    study["populations"]["rq3_model"]["rows"] = 22940
    mutated = replace(config.analysis, study=study)
    with pytest.raises(DataContractError, match="Analytical population rq3_model differs"):
        validate_data_authorities(authorities, mutated, config.data_schema)


def test_geometry_key_uniqueness_fails(authorities) -> None:
    broken = authorities.district_geometry.copy()
    broken.loc[1, "dist_id"] = broken.loc[0, "dist_id"]
    with pytest.raises(DataContractError, match="missing or non-unique"):
        validate_geometry(broken, level="district")


def test_crs_validation_fails(authorities) -> None:
    broken = authorities.acz_geometry.copy().set_crs(4326, allow_override=True)
    with pytest.raises(DataContractError, match="EPSG:32630"):
        validate_geometry(broken, level="acz")


def test_geometry_panel_reconciliation_fails_on_parent_mismatch(authorities) -> None:
    broken = authorities.district_geometry.copy()
    broken.loc[0, "zone_code"] = "FZ"
    with pytest.raises(DataContractError, match="zone_code mismatch"):
        validate_geometry_panel_reconciliation(
            authorities.acz_panel,
            authorities.district_panel,
            authorities.acz_geometry,
            broken,
        )


def test_district_to_acz_additive_reconciliation(authorities) -> None:
    result = reconcile_district_to_acz(authorities.district_panel, authorities.acz_panel)
    assert len(result) == 8
    assert result["passed"].all()
    assert result["max_absolute_difference"].max() < 1.0e-8


def test_material_reconciliation_disagreement_fails(authorities) -> None:
    broken = authorities.district_panel.copy()
    broken.loc[0, "modis_ba_km2_ba2001"] += 1.0
    with pytest.raises(DataContractError, match="Material district-to-ACZ"):
        reconcile_district_to_acz(broken, authorities.acz_panel)


def test_non_additive_metric_reconciliation_is_prohibited(authorities) -> None:
    with pytest.raises(ValueError, match="Non-additive"):
        reconcile_district_to_acz(
            authorities.district_panel,
            authorities.acz_panel,
            fields=["modis_ba_km2_per100km2_union_ba2001"],
        )


def test_manifest_source_family_consistency_fails(authorities) -> None:
    broken = dict(authorities.manifest)
    broken["families"] = [dict(x) for x in authorities.manifest["families"]]
    broken["families"][0]["support_start_yyyymm"] = 200102
    with pytest.raises(DataContractError, match="source-family support"):
        validate_manifest(broken)


def test_fixed_union_denominator_must_not_vary_within_unit(authorities, config) -> None:
    broken = authorities.acz_panel.copy()
    broken.loc[1, "modis_burnable_km2_union_ba2001"] += 1.0
    with pytest.raises(DataContractError, match="fixed field .* varies within units"):
        _validate_acz(broken, authorities, config)
