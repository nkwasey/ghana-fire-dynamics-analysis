import json
from pathlib import Path
from types import SimpleNamespace
import pytest
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import merge_af_ba_panels as m

@pytest.fixture
def case(tmp_path):
    firms=tmp_path/'RP1_Project/rp1_mv_firms_panels'; af=firms/'out/runs/local_test/rp1_af_exports'; af.mkdir(parents=True)
    qa=af.parent/'qa';qa.mkdir()
    evidence=[]
    for i in range(6):
        p=qa/f'e{i}.json'; p.write_text(str(i)); evidence.append({'path':p.relative_to(firms).as_posix(),'sha256':m.sha256_file(p)})
    exp=af/'acz/modis/export.csv';exp.parent.mkdir(parents=True);exp.write_text('data')
    receipt={'active_fire_method':{'status':'VERIFIED_AGGREGATION_INPUTS','frp_confidence_categories':['n','h'],'frp_aggregation':'mean_of_daily_maxima_over_eligible_utc_days','evidence_files':evidence},'rp1_af_exports':{'files':[{'path':exp.relative_to(firms).as_posix(),'sha256':m.sha256_file(exp)}]}}
    receipt['active_fire_method'].update(method_version='viirs_frp_dual_stream_v1', frp_selection_stage='before_independent_deduplication', frp_population_viirs='nominal_high_independently_deduplicated', frp_deduplication_independent=True, frp_finite_values_rank_first=True, viirs_preparation_evidence=evidence[:5])
    receipt['active_fire_method'].update(config_sha256='a'*64, frp_min_mw=0., deduplication={'tie_break':['stable_first'], 'latlon_round_decimals':6, 'include_satellite_in_key':True})
    rec=qa/'combine_panels_manifest.json'; rec.write_text(json.dumps(receipt))
    paths=m.PathsConfig(tmp_path,tmp_path/'uu.csv',af,tmp_path/'ba',tmp_path/'ba',tmp_path/'out')
    family=SimpleNamespace(spec=SimpleNamespace(source_kind='modis_af'),file_inventory_rows=[{'origin_path':exp.relative_to(tmp_path).as_posix()}])
    return paths, family, receipt, rec, exp

def test_nested_receipt_and_export(case):
    paths,family,receipt,rec,exp=case
    got=m.verified_active_fire_method(paths,[family])
    assert all(e['path'].startswith('RP1_Project/rp1_mv_firms_panels/') for e in got['evidence_files'])
    assert got['combine_receipt']['sha256']==m.sha256_file(rec)


def test_merger_receipt_is_checked_by_rq3_guard(case):
    from rp1_analysis_v1.rq3_guard import RQ3InputsUnverified, require_rq3_inputs_acknowledged
    paths, family, receipt, rec, exp = case
    method = m.verified_active_fire_method(paths, [family])
    require_rq3_inputs_acknowledged({"active_fire_method": method}, evidence_root=paths.repo_root)
    rec.write_text(rec.read_text() + " ")
    with pytest.raises(RQ3InputsUnverified, match="hash mismatch"):
        require_rq3_inputs_acknowledged({"active_fire_method": method}, evidence_root=paths.repo_root)

def test_mutated_evidence_rejected(case):
    paths,family,receipt,rec,exp=case
    p=paths.repo_root/'RP1_Project/rp1_mv_firms_panels'/receipt['active_fire_method']['evidence_files'][0]['path'];p.write_text('changed')
    with pytest.raises(m.ValidationError):m.verified_active_fire_method(paths,[family])

def test_mutated_export_rejected(case):
    paths,family,receipt,rec,exp=case;exp.write_text('changed')
    with pytest.raises(m.ValidationError):m.verified_active_fire_method(paths,[family])

@pytest.mark.parametrize('bad',['../../outside', '/etc/passwd'])
def test_unsafe_path_rejected(case,bad):
    paths,family,receipt,rec,exp=case;receipt['active_fire_method']['evidence_files'][0]['path']=bad;rec.write_text(json.dumps(receipt))
    with pytest.raises(m.ValidationError):m.verified_active_fire_method(paths,[family])

def test_export_path_escape_rejected(case):
    paths,family,receipt,rec,exp=case;receipt['rp1_af_exports']['files'][0]['path']='../../outside';rec.write_text(json.dumps(receipt))
    with pytest.raises(m.ValidationError):m.verified_active_fire_method(paths,[family])


def archive_evidence(case):
    paths, family, receipt, rec, exp = case
    firms = paths.repo_root / 'RP1_Project/rp1_mv_firms_panels'
    source = firms / 'data/raw/source_provenance/admission.json'
    source.parent.mkdir(parents=True)
    source.write_text('{"input_release":"fixture"}')
    method = receipt['active_fire_method']
    method['input_profiles'] = {'modis':'ghana_firms_archive_sp_v1', 'viirs':'ghana_firms_archive_sp_v1'}
    method['source_preparation_evidence'] = [{'path':source.relative_to(firms).as_posix(), 'sha256':m.sha256_file(source)}]
    rec.write_text(json.dumps(receipt))
    return source


def test_archive_evidence_survives_merger_and_rq3_guard(case):
    from rp1_analysis_v1.rq3_guard import require_rq3_inputs_acknowledged
    source = archive_evidence(case)
    paths, family, _, _, _ = case
    method = m.verified_active_fire_method(paths, [family])
    assert method['source_preparation_evidence'][0]['path'] == source.relative_to(paths.repo_root).as_posix()
    require_rq3_inputs_acknowledged({'active_fire_method':method}, evidence_root=paths.repo_root)


def test_changed_archive_evidence_rejected_at_merger_and_analysis(case):
    from rp1_analysis_v1.rq3_guard import RQ3InputsUnverified, require_rq3_inputs_acknowledged
    source = archive_evidence(case)
    paths, family, _, _, _ = case
    method = m.verified_active_fire_method(paths, [family])
    source.write_text('changed after combine')
    with pytest.raises(m.ValidationError, match='source preparation evidence'):
        m.verified_active_fire_method(paths, [family])
    with pytest.raises(RQ3InputsUnverified, match='hash mismatch'):
        require_rq3_inputs_acknowledged({'active_fire_method':method}, evidence_root=paths.repo_root)


@pytest.mark.parametrize('change', ['missing', 'path_escape', 'unknown_profile', 'invalid_profile_type'])
def test_archive_declarations_fail_closed(case, change):
    from rp1_analysis_v1.rq3_guard import RQ3InputsUnverified, require_rq3_inputs_acknowledged
    archive_evidence(case)
    paths, family, receipt, rec, _ = case
    original = m.verified_active_fire_method(paths, [family])
    if change == 'missing':
        receipt['active_fire_method']['source_preparation_evidence'] = []
        original['source_preparation_evidence'] = []
    elif change == 'path_escape':
        receipt['active_fire_method']['source_preparation_evidence'][0]['path'] = '../../../outside'
        original['source_preparation_evidence'][0]['path'] = '../outside'
    else:
        value = ['unexpected'] if change == 'invalid_profile_type' else 'unknown_profile'
        receipt['active_fire_method']['input_profiles']['viirs'] = value
        original['input_profiles'] = dict(receipt['active_fire_method']['input_profiles'])
    rec.write_text(json.dumps(receipt))
    with pytest.raises(m.ValidationError):
        m.verified_active_fire_method(paths, [family])
    with pytest.raises(RQ3InputsUnverified):
        require_rq3_inputs_acknowledged({'active_fire_method':original}, evidence_root=paths.repo_root)


def test_analysis_rejects_dropped_archive_source_evidence(case):
    from rp1_analysis_v1.rq3_guard import RQ3InputsUnverified, require_rq3_inputs_acknowledged
    archive_evidence(case)
    paths, family, _, _, _ = case
    method = m.verified_active_fire_method(paths, [family])
    method.pop('source_preparation_evidence')
    with pytest.raises(RQ3InputsUnverified, match='source preparation/profile evidence'):
        require_rq3_inputs_acknowledged({'active_fire_method':method}, evidence_root=paths.repo_root)
