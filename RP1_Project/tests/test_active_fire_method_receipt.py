from pathlib import Path
import json
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import merge_af_ba_panels as m


def test_study_contract_controls_temporal_spine_and_rejects_bad_month():
    try:
        m.configure_study({'start_yyyymm':200101,'end_yyyymm':202612,'viirs_support_start_yyyymm':201201,'ba2012_support_start_yyyymm':201201,'expected_units':{'acz':5,'district':260}})
        assert m.END_YYYYMM == 202612
        with pytest.raises(m.ValidationError):
            m.configure_study({'end_yyyymm':202613})
    finally:
        m.configure_study({})


def test_cross_stream_ratio_is_missing_at_zero_count():
    import pandas as pd
    result = m.safe_divide(pd.Series([4.0, 4.0]), pd.Series([0.0, 2.0]))
    assert pd.isna(result.iloc[0])
    assert result.iloc[1] == 2.0


def test_merger_accepts_frp_support_with_zero_nominal_high_count():
    import pandas as pd
    row = {"unit_id":"A", "yyyymm":202003, "viirs_det_low":1,
        "viirs_det_nominal":0, "viirs_det_high":0, "viirs_det_all":1, "viirs_det_nh":0,
        "viirs_days_active_nh":0, "viirs_streak_max_nh":0, "viirs_frp_active_days":1,
        "viirs_pct_high_conf":0., "viirs_frp_sum_daily_max_mw":4.,
        "viirs_frp_mean_mw":4., "viirs_frp_p95_daily_max_mw":4.}
    accepted = m.validate_af_content(pd.DataFrame([row]), "viirs", "test")
    assert accepted.loc[0, "viirs_det_nh"] == 0
    assert accepted.loc[0, "viirs_frp_mean_mw"] == 4.


def test_method_receipt_rejects_missing_and_changed_evidence(tmp_path):
    firms = tmp_path/'RP1_Project/rp1_mv_firms_panels'
    af = firms/'run/rp1_af_exports'; af.mkdir(parents=True)
    paths=m.PathsConfig(tmp_path,tmp_path/'uu.csv',af,tmp_path/'ba',tmp_path/'ba',tmp_path/'out')
    with pytest.raises(m.ValidationError): m.verified_active_fire_method(paths,[])
    qa=af.parent/'qa';qa.mkdir()
    evidence=[]
    for i in range(6):
        p=firms/f'e{i}';p.write_text('data');evidence.append({'path':p.name,'sha256':m.sha256_file(p)})
    method={'status':'VERIFIED_AGGREGATION_INPUTS','frp_confidence_categories':['n','h'],'frp_aggregation':'mean_of_daily_maxima_over_eligible_utc_days','evidence_files':evidence}
    (qa/'combine_panels_manifest.json').write_text(json.dumps({'active_fire_method':method,'rp1_af_exports':{}}))
    with pytest.raises(m.ValidationError): m.verified_active_fire_method(paths,[])
    method.update(method_version='viirs_frp_dual_stream_v1', frp_selection_stage='before_independent_deduplication', frp_population_viirs='nominal_high_independently_deduplicated', frp_deduplication_independent=True, frp_finite_values_rank_first=True, viirs_preparation_evidence=evidence[:5])
    method.update(config_sha256='a'*64, frp_min_mw=0., deduplication={'tie_break':['stable_first'], 'latlon_round_decimals':6, 'include_satellite_in_key':True})
    (qa/'combine_panels_manifest.json').write_text(json.dumps({'active_fire_method':method,'rp1_af_exports':{}}))
    assert m.verified_active_fire_method(paths,[])['status']=='VERIFIED_AGGREGATION_INPUTS'
    (firms/'e0').write_text('changed')
    with pytest.raises(m.ValidationError): m.verified_active_fire_method(paths,[])
