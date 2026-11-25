"""Explicit NASA SP intake, annual research outputs and versioned website handoff."""
from __future__ import annotations
import csv
from datetime import date, datetime, timezone, timedelta
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
from zipfile import ZipFile, ZIP_DEFLATED, ZipInfo

import numpy as np
import requests
import shapefile
import shapely
from shapely.geometry import shape
from shapely.strtree import STRtree
import yaml

from .configuration import ConfigurationError, filesystem_setting, runtime_options
from .scientific import (ScientificRecordError, validate_raw_csv_header, validate_raw_field_presence,
                         validate_scientific_record)

HOST = 'https://firms.modaps.eosdis.nasa.gov'
CATALOGUE = HOST + '/data/country/yearly_summary_files.txt'
COUNTRY_NOTE = HOST + '/content/country/'
README = HOST + '/data/country/AttributesReadme.txt'
SOURCES = {
    'MODIS_SP': {'aliases': ['modis'], 'start': '2000-11-01', 'platforms': ['Terra','Aqua'], 'versions': ['6.03','61.03','6','6.0','6.1','6.2','61'], 'instrument':'MODIS'},
    'VIIRS_SNPP_SP': {'aliases': ['viirs-snpp'], 'start': '2012-01-20', 'platforms': ['Suomi-NPP'], 'versions': ['2'], 'instrument':'VIIRS'},
    'VIIRS_NOAA20_SP': {'aliases': ['viirs-jpss1','viirs-noaa20'], 'start': '2018-04-01', 'platforms': ['NOAA-20'], 'versions': ['2'], 'instrument':'VIIRS'},
    'VIIRS_NOAA21_SP': {'aliases': ['viirs-jpss2','viirs-noaa21'], 'start': '2023-03-01', 'platforms': ['NOAA-21'], 'versions': ['2'], 'instrument':'VIIRS'},
}
PUBLIC_FIELDS = ['id','acq_date','time_utc','instrument','platform','confidence','frp_mw','brightness_k','daynight','district_id','zone_id','latitude','longitude','scan_km','track_km']
FIELDS = PUBLIC_FIELDS + ['source_product','processing_status','source_version','confidence_raw','fire_type','source_file_sha256','brightness_aux_k']
PLATFORM = {'T':'Terra','Terra':'Terra','A':'Aqua','Aqua':'Aqua','N':'Suomi-NPP','NPP':'Suomi-NPP','Suomi-NPP':'Suomi-NPP','S-NPP':'Suomi-NPP','N20':'NOAA-20','NOAA-20':'NOAA-20','N21':'NOAA-21','NOAA-21':'NOAA-21'}
PRJ = 'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]'


class ArchiveError(ValueError):
    pass


SENSOR_FOLDERS = {'MODIS_SP': 'MODIS', 'VIIRS_SNPP_SP': 'VIIRS',
                  'VIIRS_NOAA20_SP': 'NOAA20', 'VIIRS_NOAA21_SP': 'NOAA21'}


def annual_stem(source, year):
    if source not in SENSOR_FOLDERS or isinstance(year, bool) or not isinstance(year, int) or not 2000 <= year <= 9999:
        raise ArchiveError('Invalid source/year for annual export')
    return f'Ghana_{source}_{year}'


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()


def write_json(path, obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp')
    tmp.write_text(json.dumps(obj,indent=2,sort_keys=True,allow_nan=False)+'\n',encoding='utf-8')
    os.replace(tmp,path)


def years(value):
    if isinstance(value,bool): raise ArchiveError('years must be an integer or {start,end}')
    if isinstance(value,int): a=b=value
    elif isinstance(value,dict) and set(value)=={'start','end'}: a,b=value['start'],value['end']
    else: raise ArchiveError('years must be an integer or {start,end}')
    if not all(isinstance(x,int) and not isinstance(x,bool) for x in (a,b)) or a<2000 or b<a or b>datetime.now(timezone.utc).year:
        raise ArchiveError('Invalid year range')
    return list(range(a,b+1))


def load_config(path, year=None, start=None, end=None, run_id=None):
    path=Path(path).resolve();c=yaml.safe_load(path.read_text(encoding='utf-8'))
    if not isinstance(c,dict) or type(c.get('schema_version')) is not int or c['schema_version']!=1: raise ArchiveError('Config schema_version must be 1')
    if c.get('country','Ghana')!='Ghana': raise ArchiveError('This governed geography supports Ghana only')
    if year is not None: c['years']=year
    elif start is not None or end is not None:
        if start is None or end is None: raise ArchiveError('Both --start-year and --end-year are needed')
        c['years']={'start':start,'end':end}
    c['selected_years']=years(c['years'])
    if not isinstance(c.get('sources'),list) or not c['sources'] or any(not isinstance(s,str) or s not in SOURCES for s in c['sources']) or len(set(c['sources']))!=len(c['sources']): raise ArchiveError('Choose unique supported SP sources')
    try:
        c.update(runtime_options(c))
        for k,default in [('geography','../data/reference/geography'),('downloads','../data/raw')]: c[k]=str((path.parent/filesystem_setting(c.get(k,default),k)).resolve())
        if 'output' in c:
            if run_id is not None:
                raise ConfigurationError('--run-id requires output_root configuration; explicit output remains unchanged')
            c['output']=str((path.parent/filesystem_setting(c['output'],'output')).resolve())
        else:
            selected_run=run_id if run_id is not None else c.get('run_id','default')
            if not isinstance(selected_run,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}',selected_run) or selected_run in ('.','..'):
                raise ConfigurationError('run_id must be a safe single directory name of 1 to 128 characters')
            output_root=(path.parent/filesystem_setting(c.get('output_root','../out/runs'),'output_root')).resolve()
            c['run_id']=selected_run;c['output_root']=str(output_root);c['output']=str(output_root/selected_run)
        if c.get('key_file') is not None: c['key_file']=str((path.parent/filesystem_setting(c['key_file'],'key_file')).resolve())
    except ConfigurationError as exc:
        raise ArchiveError(str(exc)) from None
    c['config_path']=str(path)
    return c


def map_key(c):
    v=os.getenv('FIRMS_MAP_KEY','').strip()
    if not v and c.get('key_file') and Path(c['key_file']).is_file(): v=Path(c['key_file']).read_text().strip()
    if v and not re.fullmatch(r'[A-Za-z0-9_-]{10,200}',v): raise ArchiveError('Invalid local MAP_KEY format')
    return v


def get_bytes(url,c):
    # Never include URLs in errors: API paths can contain a MAP_KEY.
    try:options=runtime_options(c)
    except ConfigurationError as exc:raise ArchiveError(str(exc)) from None
    for attempt in range(options['retries']):
        try:
            r=requests.get(url,timeout=options['timeout_seconds'])
            r.raise_for_status();return r.content, {'etag':r.headers.get('ETag'),'last_modified':r.headers.get('Last-Modified')}
        except requests.RequestException:
            if attempt+1>=options['retries']: raise ArchiveError('NASA download failed after retries; accepted outputs are unchanged') from None
            time.sleep(min(2**attempt,10))


def catalogue(c, refresh=True):
    root=Path(c['downloads']);root.mkdir(parents=True,exist_ok=True)
    path=root/'yearly_summary_files.txt'
    if refresh or not path.is_file():
        raw,_=get_bytes(CATALOGUE,c);(root/'yearly_summary_files.txt.tmp').write_bytes(raw);os.replace(root/'yearly_summary_files.txt.tmp',path)
        for name,url in [('country-sp-declaration.html',COUNTRY_NOTE),('AttributesReadme.txt',README)]:
            raw,_=get_bytes(url,c);(root/name).write_bytes(raw)
    declaration=(root/'country-sp-declaration.html').read_text(encoding='utf-8')
    if 'Standard Processing (SP)' not in declaration: raise ArchiveError('NASA annual SP declaration is missing; intake stopped')
    rows=list(csv.DictReader(path.open(encoding='utf-8-sig',newline='')))
    return rows


def make_plan(c,refresh=True):
    rows=catalogue(c,refresh);items=[];availability={};key=map_key(c)
    if key:
        raw,_=get_bytes(f'{HOST}/api/data_availability/csv/{key}/ALL',c)
        try:
            a=list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
            availability={r['data_id']:r for r in a if r.get('data_id') in SOURCES}
            for r in availability.values():
                if date.fromisoformat(r['min_date'])>date.fromisoformat(r['max_date']):raise ValueError()
            if not availability:raise ValueError()
        except (KeyError,ValueError):raise ArchiveError('NASA SP availability response is invalid; verify the locally configured MAP_KEY') from None
        write_json(Path(c['downloads'])/'sp-availability.json',{'retrieved_utc':datetime.now(timezone.utc).isoformat(),'sources':availability,'endpoint':HOST+'/api/data_availability/csv/[MAP_KEY]/ALL','sha256':hashlib.sha256(raw).hexdigest()})
    for source in c['sources']:
        spec=SOURCES[source]
        for year in c['selected_years']:
            if str(year)+'-12-31'<spec['start']:
                items.append({'source':source,'year':year,'status':'structurally_unavailable','reason':'Before source temporal coverage'});continue
            matches=[]
            for alias in spec['aliases']:
                name=f'{alias}_{year}_Ghana.csv'
                matches.extend({**r,'alias':alias} for r in rows if r['filename']==name)
            if not matches:
                av=availability.get(source)
                if av:
                    a=max(f'{year}-01-01',spec['start'],av['min_date']);b=min(f'{year}-12-31',av['max_date'])
                    if a<=b:
                        items.append({'source':source,'year':year,'status':'available','filename':f'{source}_{year}_Ghana_api.csv','method':'api_sp','checked_start':a,'checked_end':b,'coverage_basis':'NASA SP API source availability and successfully retrieved explicit date batches','provider_updated':av['max_date'],'url':HOST+'/api/area/csv/[MAP_KEY]/'+source+'/GHA_BBOX/1/[DATE]','availability':av});continue
                items.append({'source':source,'year':year,'status':'unavailable','reason':'No Ghana annual SP file in NASA catalogue; absence is not zero detections'});continue
            m=matches[0]
            items.append({'source':source,'year':year,'status':'available','filename':m['filename'],'size_bytes':int(m['size']),'provider_updated':m['updated'],'url':f"{HOST}/data/country/{m['alias']}/{year}/{m['filename']}",'checked_start':max(f'{year}-01-01',spec['start']),'checked_end':f'{year}-12-31','coverage_basis':'NASA provider-declared annual country SP dataset','catalogue_sha256':sha(Path(c['downloads'])/'yearly_summary_files.txt')})
    obj={'contract':'ghana-firms-download-plan-v1','sources':c['sources'],'years':c['selected_years'],'items':items}
    write_json(Path(c['output'])/'download-plan.json',obj);return obj


def _valid_cached_raw_header(path, source):
    """A matching cache receipt cannot substitute for a usable source schema."""
    try:
        with path.open(encoding='utf-8-sig', newline='') as stream:
            validate_raw_csv_header(csv.DictReader(stream).fieldnames, source)
    except (ScientificRecordError, UnicodeError, csv.Error):
        return False
    return True


def download(c,refresh=True):
    from .acquisition import validate_acquisition_receipt
    plan=make_plan(c,refresh)
    for item in plan['items']:
        if item['status']!='available': continue
        dst=Path(c['downloads'])/item['filename'];receipt=dst.with_suffix('.receipt.json')
        if item.get('method')=='api_sp':
            download_api(c,item,dst,receipt);print(json.dumps({'downloaded_or_verified':item['source'],'year':item['year'],'method':'api_sp'}),flush=True);continue
        if dst.is_file() and receipt.is_file():
            old=json.loads(receipt.read_text())
            stable=('source','year','filename','checked_start','checked_end','provider_updated','size_bytes','coverage_basis')
            if (all(old.get(k)==item.get(k) for k in stable) and old.get('method','annual')=='annual'
                    and old.get('sha256')==sha(dst) and dst.stat().st_size==item['size_bytes']
                    and _valid_cached_raw_header(dst, item['source'])):
                if old.get('catalogue_sha256')!=item.get('catalogue_sha256'):
                    # A changed global catalogue alone does not change this
                    # selected file's bytes or checked interval. Record the
                    # revalidation explicitly without advancing coverage.
                    old={**old,**item,'previous_receipt_sha256':sha(receipt),'catalogue_revalidated_utc':datetime.now(timezone.utc).isoformat()}
                    write_json(receipt,old)
                try:validate_acquisition_receipt(item,old,dst,Path(c['downloads']))
                except ValueError as exc:raise ArchiveError(str(exc)) from None
                print(json.dumps({'verified_cached':item['source'],'year':item['year']}),flush=True);continue
        raw,headers=get_bytes(item['url'],c)
        if len(raw)!=item['size_bytes']: raise ArchiveError('Catalogue/file size mismatch; retry a fresh catalogue')
        try:
            with io.TextIOWrapper(io.BytesIO(raw), encoding='utf-8-sig', newline='') as stream:
                validate_raw_csv_header(csv.DictReader(stream).fieldnames, item['source'])
        except (ScientificRecordError, UnicodeError, csv.Error) as exc:
            raise ArchiveError('NASA response is not a valid FIRMS CSV: ' + str(exc)) from None
        tmp=dst.with_suffix('.partial');tmp.write_bytes(raw);os.replace(tmp,dst)
        write_json(receipt,{**item,'sha256':sha(dst),'retrieved_utc':datetime.now(timezone.utc).isoformat(),'response':headers,'declaration_url':COUNTRY_NOTE,'attributes_readme_url':README})
        try:validate_acquisition_receipt(item,json.loads(receipt.read_text()),dst,Path(c['downloads']))
        except ValueError as exc:raise ArchiveError(str(exc)) from None
        print(json.dumps({'downloaded':item['source'],'year':item['year'],'bytes':len(raw)}),flush=True)
    return plan


def download_api(c,item,dst,receipt):
    try:options=runtime_options(c)
    except ConfigurationError as exc:raise ArchiveError(str(exc)) from None
    key=map_key(c)
    if not key:raise ArchiveError('A locally configured FIRMS_MAP_KEY is required for API SP intake')
    batches=[];day=date.fromisoformat(item['checked_start']);end=date.fromisoformat(item['checked_end']);folder=Path(c['downloads'])/'api-batches'/item['source'];folder.mkdir(parents=True,exist_ok=True)
    while day<=end:
        stop=min(day+timedelta(days=4),end);n=(stop-day).days+1
        filename=folder/f'{day.isoformat()}_{stop.isoformat()}.csv';recpath=filename.with_suffix('.receipt.json')
        cached=None
        if filename.is_file() and recpath.is_file():
            cached=json.loads(recpath.read_text())
            try:age=(datetime.now(timezone.utc)-datetime.fromisoformat(cached['retrieved_utc'])).total_seconds()
            except (KeyError,ValueError,TypeError):age=-1
            max_age=options['api_batch_max_age_hours']*3600
            if (options['refresh_api_batches'] or age<0 or age>max_age or cached.get('sha256')!=sha(filename)
                    or cached.get('source')!=item['source'] or cached.get('processing_status')!='SP'
                    or cached.get('checked_start')!=day.isoformat() or cached.get('checked_end')!=stop.isoformat()
                    or not _valid_cached_raw_header(filename, item['source'])):cached=None
        if cached is None:
            raw,_=get_bytes(f"{HOST}/api/area/csv/{key}/{item['source']}/-3.6,4.4,1.6,11.5/{n}/{day.isoformat()}",c)
            try:
                reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
                validate_raw_csv_header(reader.fieldnames, item['source'])
                rows=list(reader)
                for row in rows:
                    if not isinstance(row['acq_date'], str) or not day.isoformat()<=row['acq_date']<=stop.isoformat():raise ValueError()
                    if normalize(row,item['source'],'unbound',item['year']) is None:raise ValueError()
            except (ValueError,KeyError,csv.Error):raise ArchiveError('NASA API batch is invalid, outside its date scope, or not SP; checkpoint not advanced') from None
            filename.write_bytes(raw);cached={'source':item['source'],'processing_status':'SP','checked_start':day.isoformat(),'checked_end':stop.isoformat(),'sha256':sha(filename),'retrieved_utc':datetime.now(timezone.utc).isoformat(),'rows':len(rows)};write_json(recpath,cached)
        batches.append((filename,cached));day=stop+timedelta(days=1)
    tmp=dst.with_suffix('.partial');writer=None
    with tmp.open('w',encoding='utf-8',newline='') as out:
        for filename,info in batches:
            with filename.open(encoding='utf-8-sig',newline='') as f:
                r=csv.DictReader(f)
                if writer is None:writer=csv.DictWriter(out,fieldnames=r.fieldnames,lineterminator='\n');writer.writeheader()
                if r.fieldnames!=writer.fieldnames:raise ArchiveError('NASA batch schema changed within source/year')
                writer.writerows(r)
    os.replace(tmp,dst);write_json(receipt,{**item,'sha256':sha(dst),'batches':[{'file':p.relative_to(Path(c['downloads'])).as_posix(),**r} for p,r in batches],'retrieved_utc':datetime.now(timezone.utc).isoformat()})
    from .acquisition import validate_acquisition_receipt
    try:validate_acquisition_receipt(item,json.loads(receipt.read_text()),dst,Path(c['downloads']))
    except ValueError as exc:raise ArchiveError(str(exc)) from None


def identity_number(value):
    """Stable numeric measurement encoding; missing remains distinct from zero."""
    if value in ('',None):return ''
    value=number(value)
    return '0' if value==0 else format(value,'.15g')


def identity_payload(source,platform,day,clock,lat,lon,record=None):
    record=record or {}
    raw_conf=identity_number(record.get('confidence_raw','')) if source=='MODIS_SP' else record.get('confidence','')
    fire_type=record.get('fire_type','')
    return [source,platform,day,clock,format(float(lat) or 0.,'.8f'),format(float(lon) or 0.,'.8f')]+[identity_number(record.get(k,'')) for k in ('frp_mw','brightness_k','brightness_aux_k','scan_km','track_km')]+[record.get('confidence',''),raw_conf,record.get('daynight',''),str('' if fire_type is None else fire_type).strip()]


def observation_id(source,platform,day,clock,lat,lon,record=None):
    # Source version and source-file hash describe lineage, not a measurement.
    data=identity_payload(source,platform,day,clock,lat,lon,record)
    return 'gfa2:'+hashlib.sha256(json.dumps(data,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()


def base_position_time_id(record):
    data=identity_payload(record['source_product'],record['platform'],record['acq_date'],record['time_utc'],record['latitude'],record['longitude'],record)[:6]
    return hashlib.sha256(json.dumps(data,separators=(',',':'),ensure_ascii=True).encode()).digest()


def number(value, optional=False):
    if value in ('',None) and optional:return ''
    try:v=float(value)
    except (TypeError,ValueError):raise ArchiveError('Invalid numeric value') from None
    if not math.isfinite(v):raise ArchiveError('Nonfinite numeric value')
    return v


def normalize(row,source,source_sha,year):
    try:validate_raw_field_presence(row,source)
    except ScientificRecordError as exc:raise ArchiveError(str(exc)) from None
    spec=SOURCES[source];version=str(row.get('version','')).strip()
    if 'nrt' in version.lower() or 'urt' in version.lower() or version.lower().endswith('rt'):return None
    if version not in spec['versions']:raise ArchiveError(f'Unrecognised SP version {version!r} for {source}; verify upstream version before admitting it')
    day=str(row.get('acq_date',''));date.fromisoformat(day)
    if int(day[:4])!=year:raise ArchiveError('Acquisition outside requested annual partition')
    rawtime=str(row.get('acq_time','')).strip().replace(':','')
    if not rawtime.isdigit() or len(rawtime)>4:raise ArchiveError('Invalid acquisition time')
    rawtime=rawtime.zfill(4);datetime.strptime(rawtime,'%H%M');clock=rawtime[:2]+':'+rawtime[2:]
    platform=PLATFORM.get(str(row.get('satellite','')).strip())
    if platform not in spec['platforms']:raise ArchiveError('Unexpected platform for source')
    if row.get('instrument','').strip().upper()!=spec['instrument']:raise ArchiveError('Unexpected instrument')
    lat,lon=number(row.get('latitude')),number(row.get('longitude'))
    if not -90<=lat<=90 or not -180<=lon<=180:raise ArchiveError('Coordinates outside WGS84 bounds')
    raw_conf=str(row.get('confidence','')).strip()
    if spec['instrument']=='MODIS':
        val=number(raw_conf)
        if not 0<=val<=100:raise ArchiveError('MODIS confidence outside 0–100')
        confidence='low' if val<30 else 'nominal' if val<80 else 'high'
    else:
        confidence={'l':'low','n':'nominal','h':'high','low':'low','nominal':'nominal','high':'high'}.get(raw_conf.lower())
        if confidence is None:raise ArchiveError('Invalid VIIRS confidence')
    dn=str(row.get('daynight','')).strip().upper()
    if dn not in ('D','N'):raise ArchiveError('Invalid daynight')
    primary=row['brightness'] if source=='MODIS_SP' else row.get('bright_ti4',row.get('brightness'))
    auxiliary=row['bright_t31'] if source=='MODIS_SP' else row.get('bright_ti5',row.get('brightness_2'))
    out={'id':'','acq_date':day,'time_utc':clock,'instrument':spec['instrument'],'platform':platform,'confidence':confidence,'frp_mw':number(row.get('frp'),True),'brightness_k':number(primary,True),'daynight':dn,'district_id':'','zone_id':'','latitude':lat,'longitude':lon,'scan_km':number(row.get('scan'),True),'track_km':number(row.get('track'),True),'source_product':source,'processing_status':'SP','source_version':version,'confidence_raw':raw_conf,'fire_type':row['type'],'source_file_sha256':source_sha,'brightness_aux_k':number(auxiliary,True)}
    for k in ('frp_mw','scan_km','track_km'):
        if out[k]!='' and out[k]<0:raise ArchiveError('Negative physical measurement')
    try:validate_scientific_record(out)
    except ScientificRecordError as exc:raise ArchiveError(str(exc)) from None
    out['id']=observation_id(source,platform,day,clock,lat,lon,out)
    return out


class Geography:
    def __init__(self,root,expected_hashes=None):
        root=Path(root);self.layers={};self.hashes={}
        sums=expected_hashes if expected_hashes is not None else {line.split()[1].lstrip('*'):line.split()[0] for line in (root/'checksums.sha256').read_text().splitlines() if line.strip()}
        if not {'ghana.geojson','acz.geojson','districts.geojson','units.json'}<=set(sums):raise ArchiveError('Governed geography checksum entries are incomplete')
        for filename,expected in sums.items():
            p=(root/filename).resolve()
            if not p.is_relative_to(root.resolve()) or not p.is_file() or sha(p)!=expected:raise ArchiveError('Governed geography checksum mismatch')
        for name in ('ghana','acz','districts'):
            p=root/(name+'.geojson');actual=sha(p)
            if p.name in sums and sums[p.name]!=actual:raise ArchiveError('Governed geography checksum mismatch')
            d=json.loads(p.read_text(encoding='utf-8'));features=sorted(d['features'],key=lambda f:str(f['properties'].get('district_id',f['properties'].get('zone_id',''))))
            geoms=np.array([shape(f['geometry']) for f in features],dtype=object)
            if not len(geoms) or any(g.is_empty or not g.is_valid or g.geom_type not in ('Polygon','MultiPolygon') for g in geoms):raise ArchiveError('Governed geography contains an empty, invalid or non-polygon geometry')
            self.layers[name]=(STRtree(geoms),features);self.hashes[name]=actual
        self.hashes['units']=sha(root/'units.json')
        units=json.loads((root/'units.json').read_text(encoding='utf-8'));mapping={d['district_id']:d['zone_id'] for d in units['districts']}
        if any(mapping.get(f['properties']['district_id'])!=f['properties']['zone_id'] for f in self.layers['districts'][1]):raise ArchiveError('District and unit zone assignments disagree')
        feature_ids=[f['properties']['district_id'] for f in self.layers['districts'][1]]
        zone_ids=[f['properties']['zone_id'] for f in self.layers['acz'][1]]
        if len(mapping)!=len(units['districts']) or len(set(feature_ids))!=len(feature_ids) or set(feature_ids)!=set(mapping) or len(set(zone_ids))!=len(zone_ids) or set(mapping.values())-set(zone_ids):raise ArchiveError('Governed geography contains duplicate, missing or unknown district/zone identities')
        self.root=root

    @classmethod
    def from_archive(cls,root,entries):
        """Load the accepted output's own pinned geography without modifying it."""
        root=Path(root).resolve();names={'ghana':'ghana.geojson','acz':'acz.geojson','districts':'districts.geojson','units':'units.json'}
        if not isinstance(entries,dict) or set(entries)!=set(names):raise ArchiveError('Archive geography entries are incomplete')
        files={}
        for key,name in names.items():
            entry=entries[key];relative=Path(entry['path']);path=(root/relative).resolve()
            if relative.is_absolute() or '..' in relative.parts or not path.is_relative_to(root) or path.name!=name or not path.is_file() or sha(path)!=entry['sha256']:raise ArchiveError('Output geography checksum/path mismatch')
            files[name]=path
        parents={path.parent for path in files.values()}
        if len(parents)!=1:raise ArchiveError('Archive geography files must share one pinned directory')
        return cls(next(iter(parents)),{name:entries[key]['sha256'] for key,name in names.items()})

    def assign(self,rows):
        pts=shapely.points([r['longitude'] for r in rows],[r['latitude'] for r in rows]);assignments={}
        for name,(tree,features) in self.layers.items():
            pairs=tree.query(pts,predicate='intersects');a={}
            interiors={}
            inside=shapely.contains(tree.geometries[pairs[1]],pts[pairs[0]]) if name=='districts' else np.zeros(len(pairs[0]),dtype=bool)
            for i,j,interior in zip(*pairs,inside):
                i=int(i);j=int(j)
                if i not in a or j<a[i]:a[i]=j
                if interior:interiors.setdefault(i,[]).append(j)
            if any(len(js)>1 for js in interiors.values()):raise ArchiveError('Multiple district interiors contain a detection')
            if name=='districts':a.update({i:js[0] for i,js in interiors.items()})
            assignments[name]=a
        accepted=[];outside=0;unassigned=0
        for i,row in enumerate(rows):
            if i not in assignments['ghana']:outside+=1;continue
            d=assignments['districts'].get(i)
            if d is None:raise ArchiveError('Detection inside governed Ghana has no district assignment')
            prop=self.layers['districts'][1][d]['properties'];row['district_id']=prop['district_id'];row['zone_id']=prop['zone_id']
            accepted.append(row)
        return accepted,outside,unassigned


def zip_files(path,files):
    with ZipFile(path,'w',compression=ZIP_DEFLATED,compresslevel=6) as z:
        for name,data in sorted(files.items()):
            zi=ZipInfo(name,(1980,1,1,0,0,0));zi.compress_type=ZIP_DEFLATED;zi.external_attr=0o644<<16;z.writestr(zi,data)


def shape_fields():
    # DBF names <=10 characters; full names/values remain in companion CSV.
    return [('id','obs_id','C',70,0),('acq_date','acq_date','C',10,0),('time_utc','time_utc','C',5,0),('platform','platform','C',12,0),('instrument','instrument','C',6,0),('confidence','confidence','C',8,0),('confidence_raw','conf_raw','C',12,0),('frp_mw','frp_mw','F',18,6),('brightness_k','bright_k','F',18,6),('brightness_aux_k','bright_aux','F',18,6),('daynight','daynight','C',1,0),('district_id','district','C',80,0),('zone_id','zone','C',40,0),('scan_km','scan_km','F',18,6),('track_km','track_km','F',18,6),('source_product','source','C',20,0),('processing_status','processing','C',3,0),('source_version','version','C',12,0),('fire_type','fire_type','C',8,0)]


def export_shape(csvpath,zippath,metadata):
    fields=shape_fields()
    with tempfile.TemporaryDirectory(dir=zippath.parent) as td:
        base=Path(td)/zippath.stem;w=shapefile.Writer(str(base),shapeType=shapefile.POINT,encoding='utf-8');w.autoBalance=1
        for _,name,t,size,decimal in fields:w.field(name,t,size=size,decimal=decimal)
        with csvpath.open(encoding='utf-8',newline='') as stream:
            for row in csv.DictReader(stream):
                w.point(float(row['longitude']),float(row['latitude']));w.record(*[None if row[k]=='' and typ=='F' else float(row[k]) if typ=='F' else row[k] for k,_,typ,_,_ in fields])
        w.close()
        # DBF's last-update date is packaging metadata, not acquisition time.
        # Fix it so repeated fresh builds do not change bytes with wall-clock day.
        dbf=base.with_suffix('.dbf');raw=bytearray(dbf.read_bytes());raw[1:4]=bytes([80,1,1]);dbf.write_bytes(raw)
        base.with_suffix('.prj').write_text(PRJ);base.with_suffix('.cpg').write_text('UTF-8')
        # Upload ZIPs contain one shapefile family only; metadata is published separately.
        files={p.name:p.read_bytes() for p in Path(td).iterdir()};zip_files(zippath,files)


def prepare(c,plan=None):
    from .acquisition import validate_acquisition_receipt, validate_archive_obligations
    plan=plan or json.loads((Path(c['output'])/'download-plan.json').read_text())
    # A cached broad download plan may serve a narrower preparation request,
    # but it must never override the configured year/source selection.
    expected={(source,year) for source in c['sources'] for year in c['selected_years']}
    indexed={}
    for item in plan['items']:
        key=(item.get('source'),item.get('year'))
        if key in indexed:raise ArchiveError('Duplicate source/year in download plan')
        indexed[key]=item
    if not expected<=set(indexed):raise ArchiveError('Download plan does not cover the configured year/source selection; run download with the same config or year options')
    plan={**plan,'items':[item for item in plan['items'] if (item['source'],item['year']) in expected]}
    output=Path(c['output']);output.mkdir(parents=True,exist_ok=True);geo=Geography(c['geography']);partitions=[];coverage=[]
    code_identity={name:sha(Path(__file__).with_name(name)) for name in
                   ('core.py','acquisition.py','scientific.py','semantic.py','configuration.py','exports.py')}
    for item in plan['items']:
        if item['status']!='available':coverage.append({**item,'checked_start':None,'checked_end':None});continue
        source,year=item['source'],item['year'];raw=Path(c['downloads'])/item['filename'];receipt=raw.with_suffix('.receipt.json')
        if not raw.is_file() or not receipt.is_file():raise ArchiveError('Run download before prepare; required source file missing')
        rec=json.loads(receipt.read_text());sourcehash=sha(raw)
        if rec['sha256']!=sourcehash:raise ArchiveError('Downloaded source checksum mismatch')
        try:acquisition=validate_acquisition_receipt(item,rec,raw,Path(c['downloads']))
        except ValueError as exc:raise ArchiveError(str(exc)) from None
        receipt_hash=sha(receipt)
        fingerprint=hashlib.sha256(json.dumps([sourcehash,geo.hashes,code_identity,acquisition['acquisition_sha256'],receipt_hash],sort_keys=True).encode()).hexdigest()[:20]
        dest=output/'canonical'/source/str(year)/f'{fingerprint}.csv'
        zippath=output/'artifacts'/SENSOR_FOLDERS[source]/str(year)/fingerprint/(annual_stem(source,year)+'.zip')
        dest.parent.mkdir(parents=True,exist_ok=True);zippath.parent.mkdir(parents=True,exist_ok=True)
        meta_path=dest.with_suffix('.partition.json')
        if dest.is_file() and zippath.is_file() and meta_path.is_file():
            old=json.loads(meta_path.read_text())
            if old.get('source_sha256')==sourcehash and old.get('sha256')==sha(dest) and old.get('shapefile_sha256')==sha(zippath) and old.get('geography_sha256')==geo.hashes and old.get('acquisition')==acquisition and old.get('acquisition_receipt_sha256')==receipt_hash and old.get('preparation_code_sha256')==code_identity:
                partitions.append(old);coverage.append(old['coverage']);continue
        qa={'source_rows':0,'retained':0,'nrt_excluded':0,'duplicates':0,'outside_governed_ghana':0,'unassigned_geography':0,'measurement_variants_retained':0,'position_time_groups_with_variants':0};seen=set();base_counts={};batch=[]
        tmp=dest.with_suffix('.partial');versions=set()
        def write_batch(writer):
            accepted,outside,unassigned=geo.assign(batch);qa['outside_governed_ghana']+=outside;qa['unassigned_geography']+=unassigned
            for record in accepted:
                base=base_position_time_id(record);previous=base_counts.get(base,0)
                if previous:qa['measurement_variants_retained']+=1
                if previous==1:qa['position_time_groups_with_variants']+=1
                base_counts[base]=previous+1
            writer.writerows(accepted);qa['retained']+=len(accepted);batch.clear()
        try:
            with raw.open(encoding='utf-8-sig',newline='') as f,tmp.open('w',encoding='utf-8',newline='') as target:
                reader=csv.DictReader(f)
                try:validate_raw_csv_header(reader.fieldnames,source)
                except ScientificRecordError as exc:raise ArchiveError(str(exc)) from None
                writer=csv.DictWriter(target,fieldnames=FIELDS,lineterminator='\n');writer.writeheader()
                for row in reader:
                    qa['source_rows']+=1;record=normalize(row,source,sourcehash,year)
                    if record is None:qa['nrt_excluded']+=1;continue
                    versions.add(record['source_version']);key=record['id']
                    if key in seen:
                        qa['duplicates']+=1;continue
                    seen.add(key);batch.append(record)
                    if len(batch)>=10000:write_batch(writer)
                if batch:write_batch(writer)
            if qa['nrt_excluded']:raise ArchiveError('Annual SP country artifact unexpectedly contains NRT rows; coverage cannot be admitted')
            os.replace(tmp,dest)
            coverage_status='verified_api_sp_interval' if item.get('method')=='api_sp' else 'provider_declared_annual_sp'
            cov={**item,'coverage_status':coverage_status,'processing_status':'SP','source_sha256':sourcehash,'partial_year':item['checked_start']!=f'{year}-01-01' or item['checked_end']!=f'{year}-12-31'}
            metadata={'source':source,'year':year,'path':dest.relative_to(output).as_posix(),'sha256':sha(dest),'record_count':qa['retained'],'coverage_start':item['checked_start'],'coverage_end':item['checked_end'],'coverage_status':coverage_status,'processing_status':'SP','source_sha256':sourcehash,'source_versions':sorted(versions),'geography_sha256':geo.hashes,'coverage':cov,'qa':qa,'acquisition':acquisition,'acquisition_receipt_sha256':receipt_hash,'preparation_core_sha256':code_identity['core.py'],'preparation_code_sha256':code_identity}
            export_shape(dest,zippath,metadata);metadata.update(shapefile_path=zippath.relative_to(output).as_posix(),shapefile_sha256=sha(zippath));write_json(meta_path,metadata);partitions.append(metadata);coverage.append(cov)
            print(json.dumps({'prepared':source,'year':year,'records':qa['retained']}),flush=True)
        finally:
            if tmp.is_file():tmp.unlink()
    geography={}
    geography_identity=hashlib.sha256(json.dumps(geo.hashes,sort_keys=True).encode()).hexdigest()[:20]
    for name in ('ghana.geojson','acz.geojson','districts.geojson','units.json'):
        p=output/'geography'/geography_identity/name;p.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(Path(c['geography'])/name,p);geography[name.split('.')[0]]={'path':p.relative_to(output).as_posix(),'sha256':sha(p)}
    manifest={'contract':'ghana-firms-research-archive-v1','schema_version':1,'generated_utc':datetime.now(timezone.utc).isoformat(),'years':c['selected_years'],'requested_sources':c['sources'],'processing_status':'SP','identity_contract':'gfa2: SHA256 compact JSON strings [source,platform,date,HH:MM,lat8,lon8,frp,brightness,auxbrightness,scan,track,confidence,rawconfidence,daynight,firetype]; numeric measurements .15g; missing empty; MODIS rawconfidence numeric, VIIRS confidence class','partitions':partitions,'source_coverage':coverage,'geography':geography,'total_records':sum(p['record_count'] for p in partitions),'complete_available_sp_scope':all(i['status']!='unavailable' for i in coverage),'complete_requested_scope':all(i['status']=='structurally_unavailable' or i['status']=='available' and i['checked_end']==f"{i['year']}-12-31" for i in coverage),'provider_declaration_url':COUNTRY_NOTE,'catalogue_url':CATALOGUE,'attributes_readme_url':README}
    manifest['annual_zip_contract']='gee-shapefile-v1'
    try:obligations=validate_archive_obligations(manifest,check_declared=False)
    except ValueError as exc:raise ArchiveError(str(exc)) from None
    manifest.update({k:obligations[k] for k in ('complete_available_sp_scope','complete_requested_scope')})
    candidate=output/'.candidate-archive-manifest.json';write_json(candidate,manifest);verify(candidate);os.replace(candidate,output/'archive-manifest.json');return manifest


def verify(path, write_report=True):
    from .acquisition import validate_archive_obligations, validate_embedded_acquisition
    from .semantic import verify_partition
    path=Path(path).resolve();root=path.parent;m=json.loads(path.read_text());count=0
    if m.get('contract')!='ghana-firms-research-archive-v1':raise ArchiveError('Unsupported archive handoff contract')
    try:obligations=validate_archive_obligations(m)
    except ValueError as exc:raise ArchiveError(str(exc)) from None
    geography=Geography.from_archive(root,m['geography'])
    for p in m['partitions']:
        start,end=p['coverage_start'],p['coverage_end'];date.fromisoformat(start);date.fromisoformat(end)
        for key,hashkey in [('path','sha256'),('shapefile_path','shapefile_sha256')]:
            f=(root/p[key]).resolve()
            if not f.is_relative_to(root) or not f.is_file() or sha(f)!=p[hashkey]:raise ArchiveError('Prepared artifact checksum mismatch')
        if 'acquisition' in p:
            try:validate_embedded_acquisition(p['acquisition'],p)
            except ValueError as exc:raise ArchiveError(str(exc)) from None
        checked=verify_partition(root/p['path'],root/p['shapefile_path'],p['record_count'],p['source'],p['year'],geography,
                                 coverage_start=start,coverage_end=end,source_sha256=p['source_sha256'],
                                 strict_family=m.get('annual_zip_contract')=='gee-shapefile-v1')
        count+=checked['records']
    if count!=m['total_records']:raise ArchiveError('Archive total mismatch')
    result={'passed':True,'partitions':len(m['partitions']),'records':count,
            'complete_requested_scope':obligations['complete_requested_scope'],
            'complete_available_sp_scope':obligations['complete_available_sp_scope'],
            'semantic_attributes_checked':True,'spatial_assignments_checked':True,
            'coverage_obligations_checked':True}
    if write_report:write_json(root/'verification.json',result)
    return result
