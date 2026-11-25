#!/usr/bin/env python3
"""Positive and negative c3 CSV contract fixtures (not live EE output)."""
import csv, io, pathlib, subprocess, sys, tempfile, json, zipfile
root=pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/'tools'))
import check_extended_csv as c
# Protect hard-coded offline schema against drift from the actual generated core.
js="const fs=require('fs'),vm=require('vm');let c={};vm.createContext(c);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),c);console.log(JSON.stringify(c.C3_SELECTORS));"
actual=json.loads(subprocess.check_output(['node','-e',js,str(root/'src/ee_core.js')],text=True))
assert list(c.REQUIRED)==actual
base={k:('' if k in c.TEXT else '0') for k in c.REQUIRED}
base.update({'run_id':'fixture','schema_version':'rp1_ba_c3_extended_v2','ba_domain':'BA2001','level':'district',
 'unit_id':'test','unit_name':'TEST','parent_level':'acz','parent_id':'forest_zone','year':'2024','month':'1','yyyymm':'202401',
 'ba_domain_start_year':'2001','ba_domain_end_year':'2024',
 'ba_source_status':'ADMITTED','ba_source_count':'1','ba_source_index':'2024_01_01',
 'ba_lc_source_indexes':'|'.join(str(x) for x in range(2001,2025)),
 'ba_product':'MODIS/061/MCD64A1','ba_lc_product':'MODIS/061/MCD12Q1',
 'ba_boundary_asset':'project/district','ba_ghana_asset':'project/ghana','ba_grid_crs':'SR-ORG:6974',
 'ba_grid_transform':','.join(str(x) for x in c.GRID),'ba_reducer':'sum_unweighted_centroid',
 'ba_status':'ADMITTED','ba_coverage_status':'PARTIAL_EVIDENCE','ba_sampled_pixel_count':'4',
 'ba_known_union_area_km2':'4','ba_known_union_burned_km2':'1','ba_domain_unresolved_km2':'0','ba_annual_unknown_km2':'0',
 'ba_state_closure_km2':'0','ba_state_qa_missing_km2':'1','ba_state_burndate_masked_km2':'1',
 'ba_state_unsupported_km2':'0','ba_state_explicit_zero_km2':'1','ba_state_accepted_km2':'1',
 'ba_reason_qa_missing_km2':'1','ba_reason_burndate_masked_km2':'1','ba_reason_shortened_km2':'1',
 'ba_shortened_km2':'1','ba_full_period_only_km2':'0','ba_supported_area_km2':'2','ba_supported_fraction':'0.5',
 'modis_ba_km2':'1','modis_burned_pixel_count':'1','modis_ba_any':'1','modis_burnable_km2_union':'4',
 'modis_burnable_km2_annual':'2','modis_burned_frac_union':'0.25','modis_burned_frac_annual':'0.5',
 'modis_aoi_area_land_km2':'4','modis_zero_union_den_flag':'0','modis_zero_annual_den_flag':'0'})
key=('BA2001','district','test',202401)
def errors(row):return c.validate({key:row},1e-8,1e-10)
assert not errors(base),errors(base)
future=dict(base,year='2025',yyyymm='202501',ba_source_index='2025_01_01',ba_annual_lc_source_index='2025_01_01')
future_windows={'BA2001':(2001,2025),'BA2012':(2012,2025)}
assert c.validate({key:future},1e-8,1e-10), 'future observations require a declared calendar'
assert not c.validate({key:future},1e-8,1e-10,future_windows)
missing_annual=dict(future,ba_annual_lc_source_index='')
assert any('annual LC source index required' in e for e in c.validate({key:missing_annual},1e-8,1e-10,future_windows))
stale_annual=dict(future,ba_annual_lc_source_index='2024_01_01')
assert any('does not match observation year' in e for e in c.validate({key:stale_annual},1e-8,1e-10,future_windows))
future_wider=dict(future,ba_domain_excluded_km2='4',modis_burnable_km2_annual='6',modis_burned_frac_annual=str(1/6))
assert not c.validate({key:future_wider},1e-8,1e-10,future_windows)
mutated_union=dict(future,ba_domain_end_year='2025')
assert any('year/domain' in e for e in c.validate({key:mutated_union},1e-8,1e-10,future_windows))
# This ratio has a fixed-union numerator and an annual
# denominator. It is a ratio, not an annual-domain fraction, and may exceed 1.
greater_than_one=base.copy();greater_than_one.update({
 'modis_burnable_km2_annual':'0.5','modis_burned_frac_annual':'2'})
assert not errors(greater_than_one),errors(greater_than_one)
# An anomalous unit is a structurally valid withheld result; reason areas overlap.
anomaly=base.copy();anomaly.update({'ba_status':'SOURCE_PIXEL_ANOMALY',
 'ba_anomaly_area_km2':'1','ba_anomaly_pixel_count':'1','ba_state_unsupported_km2':'1',
 'ba_state_explicit_zero_km2':'0','ba_reason_unexpected_burndate_km2':'1',
 'ba_reason_positive_special_km2':'1','ba_reason_special_km2':'1',
 'ba_supported_area_km2':'1','ba_supported_fraction':'1',
 'modis_ba_km2':'','modis_burned_pixel_count':'','modis_ba_any':'','modis_burnable_km2_union':'',
 'modis_burned_frac_union':'','modis_burned_frac_annual':''})
assert not errors(anomaly),errors(anomaly)
for field, val in [('modis_ba_km2','0'),('ba_anomaly_area_km2','0'),('ba_anomaly_pixel_count','0'),
                   ('ba_status','ADMITTED')]:
 bad=anomaly.copy();bad[field]=val;assert errors(bad),(field,errors(bad))
anomaly_unresolved=anomaly.copy();anomaly_unresolved.update({'ba_status':'DOMAIN_UNRESOLVED',
 'ba_domain_unresolved_km2':'1','modis_zero_union_den_flag':''})
assert not errors(anomaly_unresolved),errors(anomaly_unresolved)
# Primary domain unresolved is structurally valid but its complete-domain metrics must be blank.
unresolved=base.copy();unresolved.update({'ba_status':'DOMAIN_UNRESOLVED','ba_domain_unresolved_km2':'1',
 'modis_ba_km2':'','modis_burned_pixel_count':'','modis_ba_any':'','modis_burnable_km2_union':'',
 'modis_burned_frac_union':'','modis_zero_union_den_flag':'','modis_burned_frac_annual':''})
assert not errors(unresolved),errors(unresolved)
zero=base.copy();zero.update({k:'0' for k in c.STATES+c.REASONS});zero.update({
 'ba_status':'ZERO_UNION_DENOMINATOR','ba_coverage_status':'NO_KNOWN_UNION_PIXELS',
 'ba_known_union_area_km2':'0','ba_known_union_burned_km2':'0','ba_shortened_km2':'0',
 'ba_full_period_only_km2':'0','ba_supported_area_km2':'0','ba_supported_fraction':'',
 'modis_ba_km2':'0','modis_burned_pixel_count':'0','modis_ba_any':'0',
 'modis_burnable_km2_union':'0','modis_burned_frac_union':'','modis_zero_union_den_flag':'1',
 'modis_burnable_km2_annual':'0','modis_zero_annual_den_flag':'1','modis_burned_frac_annual':''})
assert not errors(zero),errors(zero)
# The independent code checks that area and count agree on zero/positive,
# including both directions. All other fields remain valid in these mutants.
positive_area_zero_count=base.copy();positive_area_zero_count['modis_burned_pixel_count']='0'
assert any('burned pixel count and burned area disagree' in e for e in errors(positive_area_zero_count))
zero_area_positive_count=zero.copy();zero_area_positive_count['modis_burned_pixel_count']='1'
assert any('burned pixel count and burned area disagree' in e for e in errors(zero_area_positive_count))
# Annual eligibility must be inside the fixed union even when its denominator
# and the derived annual ratio are internally consistent in isolation.
annual_outside_union=base.copy();annual_outside_union.update({'modis_burnable_km2_annual':'5',
 'modis_burned_frac_annual':'0.2'})
assert any('annual eligible area exceeds' in e for e in errors(annual_outside_union))
no_pixels=base.copy();no_pixels.update({k:'' for k in c.RASTER_FIELDS});no_pixels.update({
 'ba_sampled_pixel_count':'0','ba_status':'NO_PIXEL_CENTRES','ba_coverage_status':'NO_PIXEL_CENTRES'})
assert not errors(no_pixels),errors(no_pixels)
# A tiny union-area summation residual is evaluated against the approximate
# whole-grid area, not mistakenly against the much smaller eligible union.
large_grid=base.copy();large_grid.update({'ba_domain_excluded_km2':'99996',
 'ba_state_qa_missing_km2':'1.000001','ba_reason_qa_missing_km2':'1.000001',
 'ba_state_closure_km2':'0.000001'})
assert not errors(large_grid),errors(large_grid)
bad_ratio=large_grid.copy();bad_ratio['modis_burned_frac_union']='0.250001'
assert any('union fraction' in x for x in errors(bad_ratio))
for updates,expected in [
 ({'modis_burned_frac_union':'0'},'union fraction'),
 ({'ba_coverage_status':'BOGUS'},'invalid ba_coverage_status'),
 ({'ba_state_qa_missing_km2':'-1','ba_state_burndate_masked_km2':'3'},'negative area'),
 ({'year':'2010','yyyymm':'201013','month':'13'},'inconsistent'),
 ({'ba_domain':'BA2012','year':'2001','yyyymm':'200101'},'year/domain'),
 ({'ba_status':'BOGUS'},'invalid ba_status'),
 ({'ba_domain_excluded_km2':'NaN'},'non-finite'),
 ({'ba_source_count':'2'},'source admission'),
 ({'ba_grid_transform':'NaN,0,0,0,0,0'},'affine'),
 ({'ba_lc_source_indexes':'bad'},'LC source indexes'),
 ({'ba_lc_source_indexes':'|'.join(['same']*24)},'LC source indexes'),
 ({'modis_ba_any':'0'},'BA-any'),
 ({'ba_status':'REDUCTION_INCOMPLETE','ba_coverage_status':'REDUCTION_INCOMPLETE'},'incomplete Earth Engine reduction'),
 ({'ba_status':'ACCOUNTING_INCONSISTENCY','ba_coverage_status':'ACCOUNTING_INCONSISTENCY'},'accounting inconsistency'),
 ({'ba_status':'EMPTY_REDUCTION_UNRESOLVED','ba_coverage_status':'EMPTY_REDUCTION_UNRESOLVED'},'independent reference reduction')]:
 row=base.copy();row.update(updates);e=errors(row)
 assert any(expected in x for x in e),(updates,e)
# All failure states must remain non-passing with all raster-derived values,
# including the sample count, withheld.
for status,expected in [('REDUCTION_INCOMPLETE','incomplete Earth Engine reduction'),
                        ('ACCOUNTING_INCONSISTENCY','accounting inconsistency'),
                        ('EMPTY_REDUCTION_UNRESOLVED','independent reference reduction')]:
 failed=base.copy();failed.update({k:'' for k in c.RASTER_FIELDS});failed.update({
  'ba_status':status,'ba_coverage_status':status,'ba_sampled_pixel_count':''})
 e=errors(failed);assert len(e)==1 and expected in e[0],(status,e)
 failed['modis_ba_km2']='0';e=errors(failed)
 assert any('must be null' in x for x in e),(status,e)
 failed['modis_ba_km2']='';failed['ba_sampled_pixel_count']='4';e=errors(failed)
 assert any('sample count must be null' in x for x in e),(status,e)
with tempfile.TemporaryDirectory() as d:
 p=pathlib.Path(d)/'extended.csv';q=pathlib.Path(d)/'compare.csv'
 def write(path,row,fieldnames=None):
  with path.open('w',newline='') as f:
   w=csv.DictWriter(f,fieldnames=fieldnames or list(row),extrasaction='ignore');w.writeheader();w.writerow(row)
 def cli(*args):return subprocess.run([sys.executable,str(root/'tools/check_extended_csv.py'),*map(str,args)],capture_output=True,text=True)
 write(p,base);write(q,base)
 good=cli(p,'--compare',q);assert good.returncode==0,(good.stdout,good.stderr)
 # A reordered required schema must fail rather than silently masquerade as
 # the published 69-column contract. Optional GEE extras remain allowed.
 reordered=list(c.REQUIRED);reordered[0],reordered[1]=reordered[1],reordered[0]
 write(q,base,reordered);fail=cli(q);assert fail.returncode!=0 and 'documented order' in fail.stderr
 old=base.copy();old['c3_domain']=old.pop('ba_domain');write(q,old)
 fail=cli(q);assert fail.returncode!=0 and 'ba_domain' in fail.stderr
 unapproved=base.copy();unapproved['c3_domain']='BA2001';write(q,unapproved)
 fail=cli(q);assert fail.returncode!=0 and 'unexpected fields' in fail.stderr
 wrong_version=base.copy();wrong_version['schema_version']='rp1_ba_c3_methods_v1_candidate_1';write(q,wrong_version)
 fail=cli(q);assert fail.returncode!=0 and 'schema_version' in fail.stderr
 blank=base.copy();blank['modis_burned_frac_union']='';write(q,blank)
 fail=cli(p,'--compare',q);assert fail.returncode!=0 and 'null' in fail.stderr
 bad=base.copy();bad['modis_burned_frac_union']='0';write(q,bad)
 fail=cli(p,'--compare',q);assert fail.returncode!=0 and 'union fraction' in fail.stderr
 truncated={k:v for k,v in base.items() if k!='ba_boundary_asset'};write(q,truncated)
 fail=cli(q);assert fail.returncode!=0 and 'missing fields' in fail.stderr
 # DictReader represents short rows with None and extra cells under key None.
 with q.open('w',newline='') as f:f.write(','.join(c.REQUIRED)+'\n'+'one,two\n')
 fail=cli(q);assert fail.returncode!=0 and 'too many or too few cells' in fail.stderr
 with q.open('w',newline='') as f:
  w=csv.writer(f);w.writerow(c.REQUIRED);w.writerow(list(base.values())+['extra'])
 fail=cli(q);assert fail.returncode!=0 and 'too many or too few cells' in fail.stderr
 # Normal optional Earth Engine extras are harmless.
 extended=base.copy();extended['system:index']='0';extended['.geo']=''
 write(q,extended);assert cli(q).returncode==0
 selected=base.copy();selected.update({'ba_state_explicit_zero_km2':'0','ba_state_burndate_masked_km2':'2',
  'ba_reason_burndate_masked_km2':'2','ba_supported_area_km2':'1','ba_supported_fraction':'1'})
 write(q,selected);selection=cli(q);assert selection.returncode==0 and 'selection effect' in selection.stdout
 # A synthetic valid row must fail if annual eligible area exceeds its union,
 # even after recalculating the reported ratio consistently.
 sample=base.copy();write(q,sample);assert cli(q).returncode==0
 mutated=sample.copy();a=float(mutated['ba_known_union_area_km2'])+1000
 mutated.update({'modis_burnable_km2_annual':str(a),'modis_burned_frac_annual':str(float(mutated['modis_ba_km2'])/a)})
 write(q,mutated);fail=cli(q)
 assert fail.returncode!=0 and 'annual eligible area exceeds' in fail.stderr,(fail.stdout,fail.stderr)
print('PASS c3 CSV checker: full 69-column contract, valid resolved/unresolved/zero/no-centre fixtures')
print('PASS c3 CSV checker negative cases: schema, row width, status, domain/date, nonfinite/negative values, source/grid and flags')
print('PASS viewer/exporter comparison and optional EE extra columns')
