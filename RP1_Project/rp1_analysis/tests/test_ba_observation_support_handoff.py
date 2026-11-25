"""Source-only regression tests for mandatory lossless c3 evidence."""
import hashlib
import pandas as pd
import pytest
from _c3_analysis_fixture import fixture
from rp1_analysis_v1.ba_support import (
    BAObservationSupportError, BASE, PROFILE_OUTPUTS, c3_evidence_summary,
    load_observation_support, validate_c3_manifest, validate_observation_support,
    validate_profile_output_hashes, reconcile_c3_evidence,
)


def test_c3_projection_preserves_scenario_zero_guarded_null_and_annual_uncertainty():
    side, manifest, acz, district = fixture()
    original = side.copy(deep=True)
    validate_observation_support(side, manifest, acz, district)
    assert district.loc[district.month.eq(1), "modis_ba_km2_ba2012"].iloc[0] == 0
    assert district.loc[district.month.eq(3), "modis_ba_km2_ba2012"].isna().all()
    assert district.loc[district.month.eq(3), "modis_burnable_km2_annual_ba2012"].iloc[0] == 5
    assert district.loc[district.month.eq(4), "modis_burnable_km2_annual_ba2012"].isna().all()
    pd.testing.assert_frame_equal(side, original)


@pytest.mark.parametrize("mutation", ["zero_fill","family","source_hash","source_row","source_schema","guard","duplicate","missing"])
def test_corrupted_c3_evidence_is_rejected(mutation):
    side, manifest, acz, district = fixture()
    if mutation == "zero_fill":
        district.loc[district.month.eq(3), "modis_ba_km2_ba2012"] = 0
    elif mutation == "family": side.loc[0, "family"] = "ba2012"
    elif mutation == "source_hash": side.loc[0, "source_sha256"] = "a"*64
    elif mutation == "source_row": side.loc[0, "source_row"] = 0
    elif mutation == "source_schema": side.loc[0, "schema_version"] = "old"
    elif mutation == "guard": side.loc[0, "modis_ba_km2"] = ""
    elif mutation == "duplicate": side = pd.concat([side, side.iloc[[0]]])
    elif mutation == "missing": side = side.iloc[1:]
    with pytest.raises(BAObservationSupportError):
        validate_observation_support(side, manifest, acz, district)


@pytest.mark.parametrize("kind", ["legacy","policy","method","missing"])
def test_c3_manifest_cannot_revert_to_old_support_policy(kind):
    _, manifest, _, _ = fixture()
    if kind == "legacy": manifest["profile_id"] = "c2"
    elif kind == "policy": manifest["profile_contract"]["quality_policy"] = "strict_support_zero_unknown"
    elif kind == "method": manifest["ba_observation_support"]["method_version"] = "old"
    else: manifest.pop("ba_observation_support")
    with pytest.raises(BAObservationSupportError):
        validate_c3_manifest(manifest)


def test_loader_preserves_all_source_text_and_checks_bytes(tmp_path):
    side, manifest, _, _ = fixture()
    raw = tmp_path/"data/raw"; raw.mkdir(parents=True)
    path = raw/"ba_observation_support.csv"
    side.to_csv(path,index=False)
    manifest["outputs"] = {"ba_observation_support":{"staged_path":path.name,
        "sha256":hashlib.sha256(path.read_bytes()).hexdigest()}}
    loaded = load_observation_support(tmp_path, manifest)
    assert list(loaded.columns) == BASE
    assert loaded.loc[loaded.ba_status.eq("SOURCE_PIXEL_ANOMALY"),"modis_ba_km2"].eq("").all()
    path.write_bytes(path.read_bytes()+b"\n")
    with pytest.raises(BAObservationSupportError,match="hash"):
        load_observation_support(tmp_path, manifest)


def test_c3_summary_counts_records_without_calling_supported_fraction_coverage():
    side, _, _, _ = fixture()
    summary = c3_evidence_summary(side)
    assert summary.rows.sum() == 20
    assert summary.scenario_zero_rows.sum() == 4
    assert summary.withheld_rows.sum() == 4
    assert "coverage_fraction" not in summary


def test_output_hashes_bind_af_columns_and_require_the_companion(tmp_path):
    raw=tmp_path/"data/raw";raw.mkdir(parents=True)
    outputs={}
    for role,name in PROFILE_OUTPUTS.items():
        path=raw/name;path.write_text("source")
        outputs[role]={"staged_path":name,"sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
    validate_profile_output_hashes(tmp_path,{"outputs":outputs})
    (raw/PROFILE_OUTPUTS["fire_panel_district"]).write_text("changed AF")
    with pytest.raises(BAObservationSupportError,match="fire_panel_district"):
        validate_profile_output_hashes(tmp_path,{"outputs":outputs})


def test_withheld_primary_does_not_hide_additive_evidence_disagreement():
    side, manifest, acz, district = fixture()
    district['parent_code']='CZ'
    diagnostics=reconcile_c3_evidence(side,district)
    assert diagnostics.rows_compared.gt(0).all()
    assert diagnostics.loc[diagnostics.field.eq('ba_sampled_pixel_count'),'absolute_tolerance'].eq(0).all()
    # Both anomaly primary results remain blank, and the altered ACZ record
    # remains internally consistent. Independent cross-level evidence must fail.
    selected=side.level.eq('acz') & side.family.eq('ba2012') & side.month.eq('3')
    side.loc[selected,'ba_known_union_area_km2']='11'
    side.loc[selected,'ba_state_unsupported_km2']='9'
    validate_observation_support(side,manifest,acz,district)
    with pytest.raises(BAObservationSupportError,match='diagnostic reconciliation disagreement'):
        reconcile_c3_evidence(side,district)


def test_source_inventory_binds_exact_files_row_counts_and_original_task_ids():
    side,manifest,acz,district=fixture()
    record=manifest['families'][0]['files'][0]
    record['row_count']=6
    with pytest.raises(BAObservationSupportError,match='row count'):
        validate_observation_support(side,manifest,acz,district)
    record['row_count']=5
    record['run_ids']=['unrelated_old_task']
    with pytest.raises(BAObservationSupportError,match='run identities'):
        validate_observation_support(side,manifest,acz,district)
    record.pop('run_ids')
    manifest['families'][0]['files'].append({'filename':'unexpected.csv','sha256':'a'*64})
    with pytest.raises(BAObservationSupportError,match='exact merger source file inventory'):
        validate_observation_support(side,manifest,acz,district)


def test_diagnostic_audit_separates_missing_members_from_withheld_values():
    side,_,_,district=fixture()
    district['parent_code']='CZ'
    selected=side.family.eq('ba2012') & side.month.eq('2')
    side.loc[selected,'ba_known_union_area_km2']=''
    result=reconcile_c3_evidence(side,district)
    row=result.loc[result.family.eq('ba2012') & result.field.eq('ba_known_union_area_km2')].iloc[0]
    assert row.missing_constituent_rows==0 and row.withheld_constituent_rows==1
    extra=district.iloc[[0]].copy();extra['unit_id']='missing_district'
    result=reconcile_c3_evidence(side,pd.concat([district,extra]))
    row=result.loc[result.family.eq('ba2012') & result.field.eq('ba_known_union_area_km2')].iloc[0]
    assert row.missing_constituent_rows==5 and row.withheld_constituent_rows==0

