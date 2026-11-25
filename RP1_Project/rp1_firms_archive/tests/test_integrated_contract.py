"""Offline pipeline contracts: scope, cache lineage and non-destructive QA."""
import copy
import json
from pathlib import Path
import sys

import pytest

from ghana_fire_archive import cli, core, api
from test_archive import config, fixture_source, row


def accepted(c):
    return Path(c['output'])/'archive-manifest.json'


def test_plan_cannot_extend_acquired_scope(tmp_path):
    c=config(tmp_path)
    plan=fixture_source(c,[row()])
    core.prepare(c,plan)
    before=accepted(c).read_bytes()
    forged=copy.deepcopy(plan)
    forged['items'][0]['checked_start']='2024-01-02'
    with pytest.raises(core.ArchiveError,match='checked_start'):
        core.prepare(c,forged)
    assert accepted(c).read_bytes()==before


def test_verified_empty_scope_extension_refreshes_metadata_not_observations(tmp_path):
    c=config(tmp_path)
    plan=fixture_source(c,[])
    plan['items'][0]['checked_end']='2024-01-31'
    raw=Path(c['downloads'])/plan['items'][0]['filename']
    receipt=raw.with_suffix('.receipt.json')
    core.write_json(receipt,{**plan['items'][0],'sha256':core.sha(raw)})
    first=core.prepare(c,plan)
    assert not first['complete_requested_scope']
    plan['items'][0]['checked_end']='2024-12-31'
    core.write_json(receipt,{**plan['items'][0],'sha256':core.sha(raw)})
    second=core.prepare(c,plan)
    a,b=first['partitions'][0],second['partitions'][0]
    assert second['complete_requested_scope']
    assert a['path']!=b['path']
    assert a['sha256']==b['sha256'] and a['shapefile_sha256']==b['shapefile_sha256']
    assert b['coverage_end']=='2024-12-31' and b['record_count']==0
    assert b['acquisition_receipt_sha256']==core.sha(receipt)


def test_refreshed_receipt_keeps_exact_lineage_and_identical_science(tmp_path):
    c=config(tmp_path)
    plan=fixture_source(c,[row()])
    first=core.prepare(c,plan)['partitions'][0]
    receipt=(Path(c['downloads'])/plan['items'][0]['filename']).with_suffix('.receipt.json')
    body=json.loads(receipt.read_text())
    body['retrieved_utc']='2026-11-10T12:00:00+00:00'
    core.write_json(receipt,body)
    second=core.prepare(c,plan)['partitions'][0]
    assert first['acquisition']==second['acquisition']
    assert first['path']!=second['path']
    assert first['sha256']==second['sha256']
    assert first['shapefile_sha256']==second['shapefile_sha256']
    assert second['acquisition_receipt_sha256']==core.sha(receipt)
    assert set(second['preparation_code_sha256'])=={
        'core.py','acquisition.py','scientific.py','semantic.py','configuration.py','exports.py'}


def test_available_partition_cannot_disappear_after_rehash(tmp_path):
    c=config(tmp_path)
    manifest=core.prepare(c,fixture_source(c,[]))
    manifest['partitions']=[]
    manifest['total_records']=0
    core.write_json(accepted(c),manifest)
    with pytest.raises(core.ArchiveError,match='missing.*partition'):
        core.verify(accepted(c),write_report=False)


@pytest.mark.parametrize('change',[{'scan':'0'},{'track':'-1'},
                                 {'brightness':'-1'},{'type':'9'}])
def test_invalid_scientific_values_stop_preparation_without_acceptance(tmp_path,change):
    c=config(tmp_path)
    core.prepare(c,fixture_source(c,[row()]))
    before=accepted(c).read_bytes()
    with pytest.raises(core.ArchiveError):
        core.prepare(c,fixture_source(c,[row(**change)]))
    assert accepted(c).read_bytes()==before


def test_empty_source_missing_required_channel_is_rejected(tmp_path):
    c=config(tmp_path)
    plan=fixture_source(c,[])
    raw=Path(c['downloads'])/plan['items'][0]['filename']
    raw.write_text('latitude,longitude,version\n',encoding='utf-8')
    core.write_json(raw.with_suffix('.receipt.json'),{**plan['items'][0],'sha256':core.sha(raw)})
    with pytest.raises(core.ArchiveError,match='missing fields'):
        core.prepare(c,plan)
    assert not accepted(c).exists()


def test_build_publishes_sparse_qa_and_qa_cli_preserves_accepted_files(tmp_path,monkeypatch,capsys):
    c=config(tmp_path)
    result,exported=cli.prepare_and_export(c,fixture_source(c,[row(),row(frp='0'),row(brightness='0')]))
    assert result['total_records']==3
    assert exported['quality_assurance']['flagged_records']==2
    root=Path(c['output'])
    before={p.relative_to(root):core.sha(p) for p in root.rglob('*') if p.is_file() and 'qa' not in p.relative_to(root).parts}
    monkeypatch.setattr(cli,'load_config',lambda *a,**kw:c)
    monkeypatch.setattr(sys,'argv',['ghana-fire-archive','qa'])
    cli.main()
    report=json.loads((root/'qa/qa-manifest.json').read_text())
    assert report['flag_counts']=={'brightness_zero_unresolved':1,'frp_zero_source_reported':1}
    assert report['research_manifest_sha256']==core.sha(accepted(c))
    assert all(core.sha(root/p)==digest for p,digest in before.items())


def test_qa_failure_does_not_unaccept_a_verified_archive(tmp_path,monkeypatch):
    c=config(tmp_path)
    plan=fixture_source(c,[row()])
    def fail(*args,**kwargs):
        raise ValueError('synthetic QA publication failure')
    monkeypatch.setattr(api,'write_quality_sidecars',fail)
    with pytest.raises(ValueError,match='QA publication'):
        cli.prepare_and_export(c,plan)
    assert core.verify(accepted(c),write_report=False)['passed']
    assert cli.verify_annual(c['output'],accepted(c))['passed']
