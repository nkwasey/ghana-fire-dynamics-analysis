from __future__ import annotations
from scientific_input_reference import input_population_sizes, paired_input_reference, long_run_input_reference

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


def test_governed_file_loading(authorities, config) -> None:
    assert authorities.acz_panel.shape == (config.data_schema.panel("acz_monthly").expected_rows, config.data_schema.field_count)
    assert authorities.district_panel.shape == (config.data_schema.panel("district_monthly").expected_rows, config.data_schema.field_count)
    assert len(authorities.acz_geometry) == authorities.acz_panel.unit_id.nunique()
    assert len(authorities.district_geometry) == authorities.district_panel.unit_id.nunique()
    assert authorities.manifest["merge_schema_version"] == "rp1_fire_panel_consolidated_v3"


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
    assert summary.acz_count == authorities.acz_panel.unit_id.nunique()
    assert summary.district_spatial_universe_count == input_population_sizes()["DISTRICT_UNITS"]
    assert summary.long_run_eligible_count == input_population_sizes()["LONG_RUN_DISTRICTS"]
    assert summary.paired_eligible_count == input_population_sizes()["PAIRED_DISTRICTS"]
    long_excluded = summary.long_run_mask.units.loc[~summary.long_run_mask.units["eligible"]]
    paired_excluded = summary.paired_mask.units.loc[~summary.paired_mask.units["eligible"]]
    assert len(long_excluded) == authorities.district_panel.unit_id.nunique() - long_run_input_reference().unit_id.nunique()
    assert len(paired_excluded) == authorities.district_panel.unit_id.nunique() - paired_input_reference().unit_id.nunique()
    assert long_excluded["exclusion_reasons"].eq("primary_denominator_zero_or_nonpositive").all()
    assert paired_excluded["exclusion_reasons"].eq("primary_denominator_zero_or_nonpositive").all()
    # Excluded identities depend on the selected source profile. Check the source
    # denominators directly rather than prescribing a particular district name.
    for population, excluded in (("long_run_district", long_excluded), ("paired_overlap", paired_excluded)):
        specification = config.analysis.study["populations"][population]
        from rp1_analysis_v1.variables import resolve_field_role
        denominator = resolve_field_role(config.analysis, specification["denominator_role"])
        start, end = (int(str(specification[x]).replace("-", "")) for x in ("start", "end"))
        source = authorities.district_panel.loc[authorities.district_panel.yyyymm.between(start, end)]
        direct = set(source.loc[source[denominator].le(0), "unit_id"])
        assert set(excluded.unit_id) == direct


def test_temporal_masks_use_frozen_windows(authorities, config) -> None:
    windows = config.analysis.study["temporal_windows"]
    for frame in (authorities.acz_panel, authorities.district_panel):
        for name, function in (("long_run", long_run_temporal_mask), ("overlap_monthly", overlap_monthly_temporal_mask)):
            start, end = (int(str(windows[name][key]).replace("-", "")) for key in ("start", "end"))
            pd.testing.assert_series_equal(function(frame, config.analysis), frame.yyyymm.between(start, end), check_names=False)
        start, end = (int(windows["overlap_complete_years"][key]) for key in ("start", "end"))
        pd.testing.assert_series_equal(complete_year_overlap_temporal_mask(frame, config.analysis), frame.year.between(start, end), check_names=False)


def test_population_authority_preserves_exclusion_reasons(authorities, config) -> None:
    summary = validate_data_authorities(authorities, config.analysis, config.data_schema)
    row = summary.population_authority.set_index("population_name").loc["paired_ba_viirs_district"]
    candidates = authorities.district_panel.unit_id.nunique()
    retained = paired_input_reference().unit_id.nunique()
    assert int(row["candidate_units"]) == candidates
    assert int(row["retained_units"]) == retained
    assert int(row["excluded_units"]) == candidates - retained
    reasons = summary.paired_mask.units.loc[lambda x: ~x.eligible, "exclusion_reasons"].value_counts()
    assert row["exclusion_reasons"] == ("none" if reasons.empty else ";".join(f"{key}:{count}" for key, count in sorted(reasons.items())))
    spec = config.analysis.study["populations"]["paired_overlap"]
    assert row["temporal_start"] == spec["start"]
    assert row["temporal_end"] == spec["end"]


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
    assert ((result["max_absolute_difference"] <= result["absolute_tolerance"]) |
            (result["max_relative_difference"] <= result["relative_tolerance"])).all()


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


