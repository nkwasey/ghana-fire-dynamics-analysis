"""Annual upload layout, data preservation and transactional publishing contracts."""
import csv
import io
import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

import pytest
import yaml

from ghana_fire_archive import cli, core, exports
from test_archive import config, fixture_source, row


def prepared(tmp_path, source='MODIS_SP', records=None):
    c=config(tmp_path)
    c['sources']=[source]
    satellite={'MODIS_SP':'Terra','VIIRS_SNPP_SP':'N','VIIRS_NOAA20_SP':'N20','VIIRS_NOAA21_SP':'N21'}[source]
    observation=row(satellite=satellite, instrument='MODIS' if source=='MODIS_SP' else 'VIIRS',
                    confidence='80' if source=='MODIS_SP' else 'h', version='61.03' if source=='MODIS_SP' else '2')
    plan=fixture_source(c,[observation] if records is None else records)
    if source!='MODIS_SP':
        # Real VIIRS exports use I4/I5 columns; the receipt must describe the
        # same source and bytes as its selected acquisition-plan item.
        item=plan['items'][0]
        path=Path(c['downloads'])/item['filename']
        with path.open(newline='') as stream:
            rows=list(csv.DictReader(stream))
        renamed={'brightness':'bright_ti4','bright_t31':'bright_ti5'}
        fields=[renamed.get(name,name) for name in observation]
        with path.open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=fields)
            writer.writeheader()
            writer.writerows({renamed.get(name,name):value for name,value in record.items()} for record in rows)
        item['source']=source
        core.write_json(path.with_suffix('.receipt.json'),{**item,'sha256':core.sha(path)})
    return c,plan,core.prepare(c,plan)


@pytest.mark.parametrize('source,folder',list(core.SENSOR_FOLDERS.items()))
def test_readable_sensor_layout_and_single_gee_family(tmp_path,source,folder):
    c,plan,m=prepared(tmp_path,source)
    manifest=Path(c['output'])/'archive-manifest.json'
    result=exports.export_annual(manifest,c['output'])
    stem=f'Ghana_{source}_2024'
    upload=Path(c['output'])/'annual'/folder/(stem+'.zip')
    assert result['gee_upload_ready']==1
    assert Path(m['partitions'][0]['shapefile_path']).name==stem+'.zip'
    assert m['partitions'][0]['shapefile_path'].startswith('artifacts/')
    with ZipFile(upload) as archive:
        assert set(archive.namelist())=={stem+ext for ext in exports.EXTENSIONS}
    assert exports.verify_annual(c['output'],manifest)['passed']
    meta=upload.parent.parent/'metadata'/folder
    assert (meta/(stem+'_fields.json')).is_file()
    assert json.loads((meta/(stem+'_provenance.json')).read_text())['accepted_partition']==m['partitions'][0]


def make_saved_archive(c,m):
    """A saved accepted archive may contain metadata inside fingerprinted ZIPs."""
    root=Path(c['output']);part=m['partitions'][0]
    original=root/part['shapefile_path']
    old_stem='Ghana_MODIS_SP_2024_abc123'
    path=root/'annual'/(old_stem+'.zip');path.parent.mkdir()
    with ZipFile(original) as archive:
        files={old_stem+ext:archive.read('Ghana_MODIS_SP_2024'+ext) for ext in exports.EXTENSIONS}
    files.update({'fields.json':b'{}','provenance.json':b'{}'})
    core.zip_files(path,files)
    m.pop('annual_zip_contract')
    part.update(shapefile_path=path.relative_to(root).as_posix(),shapefile_sha256=core.sha(path))
    manifest=root/'archive-manifest.json';core.write_json(manifest,m)
    return manifest,path


def test_saved_archive_export_and_collection_preserve_inputs(tmp_path):
    c,_,m=prepared(tmp_path)
    manifest,source=make_saved_archive(c,m)
    root=Path(c['output'])
    before={p:p.read_bytes() for p in [manifest,source,root/'verification.json',root/m['partitions'][0]['path']]}
    destination=tmp_path/'exports'
    exports.export_annual(manifest,destination)
    collection=tmp_path/'annual-collection.zip'
    assert exports.package_collection(manifest,collection)['annual_partitions']==1
    with ZipFile(collection) as bundle:
        name='MODIS/Ghana_MODIS_SP_2024.zip'
        assert name in bundle.namelist()
        assert not any(n.endswith('.shp') for n in bundle.namelist())
        with ZipFile(io.BytesIO(bundle.read(name))) as annual:
            assert len(annual.namelist())==5
            with ZipFile(source) as original:
                assert annual.read('Ghana_MODIS_SP_2024.dbf')==original.read('Ghana_MODIS_SP_2024_abc123.dbf')
    assert all(p.read_bytes()==value for p,value in before.items())
    with pytest.raises(core.ArchiveError,match='overlaps'):
        exports.export_annual(manifest,root)
    with pytest.raises(core.ArchiveError,match='replace an accepted'):
        exports.package_collection(manifest,source)


def test_tampering_is_detected_and_failed_export_preserves_view(tmp_path):
    c,_,m=prepared(tmp_path)
    root=Path(c['output']);manifest=root/'archive-manifest.json'
    exports.export_annual(manifest,root)
    upload=root/'annual/MODIS/Ghana_MODIS_SP_2024.zip'
    upload.write_bytes(upload.read_bytes()+b'tamper')
    with pytest.raises(core.ArchiveError,match='checksum'):
        exports.verify_annual(root,manifest)
    exports.export_annual(manifest,root)
    before={p:p.read_bytes() for p in (root/'annual').rglob('*') if p.is_file()}
    input_zip=root/m['partitions'][0]['shapefile_path']
    input_zip.write_bytes(input_zip.read_bytes()+b'tamper')
    with pytest.raises(core.ArchiveError,match='checksum'):
        exports.export_annual(manifest,root)
    assert all(p.read_bytes()==value for p,value in before.items())
    assert not (root/'.annual-export.lock').exists()


def test_failed_publication_restores_manifest_report_and_exports(tmp_path,monkeypatch):
    c,plan,m=prepared(tmp_path)
    root=Path(c['output']);manifest=root/'archive-manifest.json'
    exports.export_annual(manifest,root)
    before={p:p.read_bytes() for p in [manifest,root/'verification.json',root/'annual-current.csv']}
    before.update({p:p.read_bytes() for p in (root/'annual').rglob('*') if p.is_file()})
    real_replace=exports.os.replace
    def fail_index(source,dest):
        if Path(dest)==root/'annual-current.csv':raise OSError('simulated index publication failure')
        return real_replace(source,dest)
    monkeypatch.setattr(exports.os,'replace',fail_index)
    plan=fixture_source(c,[row(frp='10')])
    with pytest.raises(OSError,match='simulated'):
        cli.prepare_and_export(c,plan)
    assert all(p.read_bytes()==value for p,value in before.items())
    assert core.verify(manifest,write_report=False)['passed']
    assert exports.verify_annual(root,manifest)['passed']


def test_empty_year_is_explicitly_not_an_upload_asset(tmp_path):
    c,_,m=prepared(tmp_path,records=[])
    manifest=Path(c['output'])/'archive-manifest.json'
    result=exports.export_annual(manifest,c['output'])
    assert result['empty_partitions']==1 and result['gee_upload_ready']==0
    assert exports.verify_annual(c['output'],manifest)['records']==0


def test_concurrent_export_lock_is_respected(tmp_path):
    c,_,m=prepared(tmp_path)
    root=Path(c['output']);lock=root/'.annual-export.lock';lock.write_text('other process')
    with pytest.raises(core.ArchiveError,match='holds the lock'):
        exports.export_annual(root/'archive-manifest.json',root)
    assert lock.read_text()=='other process'


def test_cli_build_year_override_publishes_and_verifies_exports(tmp_path,monkeypatch,capsys):
    c=config(tmp_path)
    path=tmp_path/'config.yaml'
    path.write_text(yaml.safe_dump({**c,'schema_version':1,'years':{'start':2023,'end':2024}}))
    def downloaded(selection,refresh):
        assert selection['selected_years']==[2024]
        return fixture_source(selection,[row(),row(),row(frp='5')])
    monkeypatch.setattr(cli,'download',downloaded)
    monkeypatch.setattr(sys,'argv',['ghana-fire-archive','build','--config',str(path),'--year','2024'])
    cli.main()
    result=json.loads(capsys.readouterr().out.splitlines()[-1])
    assert result['records']==2 and Path(result['annual_directory'])==Path(c['output'])/'annual'
    launcher=Path(__file__).resolve().parents[1]/'archive.py'
    checked=subprocess.run([sys.executable,str(launcher),'verify','--config',str(path)],
                           cwd=tmp_path,capture_output=True,text=True)
    assert checked.returncode==0,checked.stderr
    assert json.loads(checked.stdout)['annual_exports']['passed']


@pytest.mark.parametrize('extra',['fields.json','second.shp','nested/another.dbf'])
def test_gee_upload_contract_rejects_extra_members(tmp_path,extra):
    c,_,m=prepared(tmp_path)
    source=Path(c['output'])/m['partitions'][0]['shapefile_path']
    with ZipFile(source) as archive:
        members={name:archive.read(name) for name in archive.namelist()}
    members[extra]=b'not part of the upload shapefile'
    bad=tmp_path/'bad.zip';core.zip_files(bad,members)
    with pytest.raises(core.ArchiveError,match='exactly one'):
        exports.validate_upload_zip(bad,'MODIS_SP',2024,1)
