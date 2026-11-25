"""c3 source semantics and independent merger durability contracts."""
from pathlib import Path
import sys,json
import pandas as pd
import pytest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'RP1_Project'))
sys.path.insert(0,str(ROOT/'tests'))
import merge_af_ba_panels as m
from rp1_ba_contracts import c3
from c3_fixture import make_row

def project(rows):
    raw=pd.DataFrame(rows)
    return m.apply_ba_profile(raw,profile=c3.PROFILE,family='ba2001',context='independent fixture')

@pytest.mark.parametrize('state',['partial','none','zero_union','anomaly','unresolved','annual_unknown','no_pixels'])
def test_c3_source_values_and_withheld_cells_are_preserved(state):
    original=make_row(state=state)
    out,evidence=project([original])
    for field in m.BA_ANALYTICAL_COLUMNS:
        actual=out[field].iloc[0]
        if original[field]=='':assert pd.isna(actual)
        else:assert actual==float(original[field])
    for field in c3.FIELDS:assert evidence[field].iloc[0]==original[field]

def test_admitted_no_supported_zero_is_not_c2_null_fill():
    out,evidence=project([make_row(state='none')])
    assert out.modis_ba_km2.iloc[0]==0
    assert evidence.ba_status.iloc[0]=='ADMITTED'
    assert evidence.ba_coverage_status.iloc[0]=='NO_SUPPORTED_EVIDENCE'
    assert evidence.ba_supported_fraction.iloc[0]==''

def test_annual_ratio_above_one_and_independent_anomaly_flags():
    row=make_row(state='partial')
    row.update(modis_burnable_km2_annual='0.5',modis_burned_frac_annual='2')
    out,_=project([row]);assert out.modis_burned_frac_annual.iloc[0]==2
    out,_=project([make_row(state='anomaly')])
    assert pd.isna(out.modis_burnable_km2_union.iloc[0])
    assert out.modis_zero_union_den_flag.iloc[0]==0
    assert out.modis_burnable_km2_annual.iloc[0]==2

@pytest.mark.parametrize('field,value',[('schema_version','old'),('ba_product','wrong'),('ba_grid_crs','EPSG:4326'),('ba_status','invented'),('modis_ba_km2','-1'),('ba_state_closure_km2','5')])
def test_invalid_c3_source_is_rejected(field,value):
    row=make_row();row[field]=value
    with pytest.raises((m.ValidationError,c3.C3ValidationError)):project([row])

def test_legacy_policy_and_paired_sources_are_rejected():
    raw=pd.DataFrame([make_row()])
    with pytest.raises(m.ValidationError,match='only the c3'):
        m.apply_ba_profile(raw,profile={'quality_policy':'strict_support_zero_unknown'},family='ba2001')
    with pytest.raises(m.ValidationError,match='not paired'):
        m.apply_ba_profile(raw,ext=raw,profile=c3.PROFILE,family='ba2001')

def test_non_c3_configuration_cannot_bypass_admission(tmp_path):
    from argparse import Namespace
    config=tmp_path/'config.json'
    config.write_text(json.dumps({'version':2,'default_profile':'c1','profiles':{'c1':{}},'paths':{}}))
    args=Namespace(config=str(config),repo_root=str(tmp_path),profile='c1')
    with pytest.raises(m.ValidationError,match='Only the c3'):m.build_paths_config(args)


def test_configuration_change_after_resolution_cannot_be_recorded_as_current(tmp_path):
    config = tmp_path / 'config.json'
    config.write_text('{"source":"original"}')
    digest = m.sha256_file(config)
    paths = m.PathsConfig(tmp_path, tmp_path/'universe', tmp_path/'af', tmp_path/'ba',
        tmp_path/'ba', tmp_path/'out', config_path=config, config_sha256=digest,
        bundle_manifest_path=tmp_path/'manifest.json', bundle_handoff_path=tmp_path/'handoff.json',
        source_lock_path=tmp_path/'lock.json', admission_verified=True)
    config.write_text('{"source":"changed"}')
    with pytest.raises(m.ValidationError, match='configuration changed'):
        m.verify_c3_admission(paths)

def test_source_lock_rejects_tampering_even_with_same_schema_and_filename(tmp_path):
    import hashlib
    path=tmp_path/'synthetic_source.csv'
    original='unit_id,yyyymm,value\nsynthetic,202401,3\n'
    path.write_bytes(original.encode('utf-8'))
    entry={'filename':path.name,'sha256':hashlib.sha256(original.encode()).hexdigest()}
    m.verify_locked_file(path,entry,'fixture')
    path.write_bytes(original.replace(',3\n',',4\n').encode('utf-8'))
    with pytest.raises(m.ValidationError,match='SHA-256'):m.verify_locked_file(path,entry,'fixture')
    wrong=tmp_path/'other.csv';wrong.write_bytes(original.encode('utf-8'))
    with pytest.raises(m.ValidationError,match='source lock'):m.verify_locked_file(wrong,entry,'fixture')

def test_atomic_publish_and_reject_existing_directory(tmp_path):
    staging=tmp_path/'stage';staging.mkdir();(staging/'a').write_text('new')
    target=tmp_path/'target';m.publish_directory_no_replace(staging,target)
    assert (target/'a').read_text()=='new' and not staging.exists()
    second=tmp_path/'stage2';second.mkdir();(second/'a').write_text('other')
    with pytest.raises(m.ValidationError):m.publish_directory_no_replace(second,target)
    assert (target/'a').read_text()=='new' and (second/'a').read_text()=='other'

def test_publication_preflight_rejects_replacing_rename(tmp_path, monkeypatch):
    target=tmp_path/'runs'/'new-run'
    def unsafe_rename(source, destination):
        if destination.exists():
            destination.rmdir()
        source.rename(destination)
    monkeypatch.setattr(m,'publish_directory_no_replace',unsafe_rename)
    with pytest.raises(m.ValidationError,match='existing destination was not protected'):
        m.preflight_directory_publication(target)
    assert list(target.parent.iterdir()) == []


def test_publication_preflight_uses_output_filesystem_and_cleans_up(tmp_path):
    target=tmp_path/'runs'/'new-run'
    m.preflight_directory_publication(target)
    assert target.parent.exists() and list(target.parent.iterdir()) == []
    assert not target.exists()


def test_unsupported_publication_fails_before_loading_inputs(tmp_path, monkeypatch):
    target=tmp_path/'runs'/'new-run'
    paths=m.PathsConfig(tmp_path,tmp_path/'universe.csv',tmp_path/'af',tmp_path/'ba1',tmp_path/'ba2',target)
    def reject(source, destination):
        assert source.parent.parent == target.parent
        raise m.ValidationError('RENAME_NOREPLACE unsupported')
    def unexpected_load(_):
        pytest.fail('inputs loaded before publication preflight')
    monkeypatch.setattr(m,'publish_directory_no_replace',reject)
    monkeypatch.setattr(m,'load_unit_universe',unexpected_load)
    with pytest.raises(m.ValidationError,match='preflight failed.*RENAME_NOREPLACE unsupported'):
        m.run(paths,'test')
    assert not target.exists() and list(target.parent.iterdir()) == []


def test_run_fails_before_touching_existing_output(tmp_path):
    dest=tmp_path/'output';dest.mkdir();(dest/'keep').write_text('unmodified')
    p=m.PathsConfig(tmp_path,tmp_path/'none',tmp_path/'none',tmp_path/'none',tmp_path/'none',dest)
    with pytest.raises(m.ValidationError,match='already exists'):m.run(p,'test')
    assert sorted(x.name for x in dest.iterdir())==['keep'] and (dest/'keep').read_text()=='unmodified'

def test_mid_write_failure_cleans_staging_and_never_publishes(tmp_path, monkeypatch):
    from types import SimpleNamespace
    dest=tmp_path/'runs'/'new-run'
    for name in ('universe.csv','manifest.json','handoff.json','source_lock.json'):
        (tmp_path/name).write_text('{}')
    paths=m.PathsConfig(tmp_path,tmp_path/'universe.csv',tmp_path/'af',tmp_path/'ba1',tmp_path/'ba2',dest,
        bundle_manifest_path=tmp_path/'manifest.json',bundle_handoff_path=tmp_path/'handoff.json',
        source_lock_path=tmp_path/'source_lock.json',admission_verified=True)
    monkeypatch.setattr(m,'verify_c3_admission',lambda _: None)
    monkeypatch.setattr(m,'load_unit_universe',lambda _: pd.DataFrame())
    monkeypatch.setattr(m,'canonical_partition_codes',lambda _: ['CZ'])
    monkeypatch.setattr(m,'build_canonical_spine',lambda *args: pd.DataFrame())
    spec=SimpleNamespace(level='acz',family_name='ba2001_acz_base')
    monkeypatch.setattr(m,'build_family_specs',lambda _: [spec])
    # Input loading is isolated here, but the evidence must still satisfy the
    # current sidecar schema so execution reaches the injected write failure.
    qa=pd.DataFrame([{**make_row(level='acz',year=2001,month=1),
        'family':'ba2001','source_path':'synthetic_source.csv',
        'source_sha256':'0'*64,'source_row':1}])
    monkeypatch.setattr(m,'load_family',lambda *args:SimpleNamespace(spec=spec,qa_sidecars=[qa]))
    monkeypatch.setattr(m,'build_level_panel',lambda *args:pd.DataFrame({'x':[1]}))
    calls=[]
    def fail_during_write(frame,path):
        calls.append(path);path.write_text('partial')
        if len(calls)==2:raise OSError('injected disk failure')
    monkeypatch.setattr(m,'write_csv',fail_during_write)
    with pytest.raises(OSError,match='injected disk failure'):m.run(paths,'synthetic')
    assert len(calls) == 2
    assert [path.name for path in calls] == [
        f'fire_panel_{level}_monthly_consolidated_{m.START_YYYYMM // 100}_{m.END_YYYYMM // 100}.csv'
        for level in ('acz','district')]
    assert calls[0].parent == calls[1].parent
    assert not calls[0].parent.exists()
    assert not dest.exists()
    assert list(dest.parent.iterdir()) == []

@pytest.mark.parametrize('field,value', [
    ('modis_burnable_km2_union', None),
    ('modis_burnable_km2_annual', None),
    ('modis_zero_union_den_flag', None),
    ('modis_zero_annual_den_flag', None),
    ('modis_zero_union_den_flag', '1'),
    ('modis_zero_annual_den_flag', '1'),
    ('modis_burnable_km2_union', 'inf'),
])
def test_reject_missing_nonfinite_or_inconsistent_denominator_flags(field,value):
    raw=pd.DataFrame([make_row()]);raw.loc[0,field]=value
    with pytest.raises(m.ValidationError):m.validate_ba_content(raw,'invalid')

@pytest.mark.parametrize('gzipped',[False,True])
def test_reject_duplicate_csv_headers_before_pandas_mangles_them(tmp_path,gzipped):
    import gzip
    path=tmp_path/('data.csv.gz' if gzipped else 'data.csv')
    opener=gzip.open if gzipped else open
    with opener(path,'wt',encoding='utf-8',newline='') as f:f.write('unit_id,yyyymm,unit_id\nU,200101,U\n')
    with pytest.raises(m.ValidationError,match='duplicate column names'):m.read_csv_strict(path)

@pytest.mark.parametrize('level,field', [('acz','unit_code'),('district','parent_code')])
def test_reject_swapped_partition(level,field):
    values={'unit_id':['unit-one'],'yyyymm':[200101],field:['CZ']}
    frame=pd.DataFrame(values)
    m.validate_file_partition(frame,level,'CZ','fixture')
    with pytest.raises(m.ValidationError,match='file partition FZ'):
        m.validate_file_partition(frame,level,'FZ','fixture')
