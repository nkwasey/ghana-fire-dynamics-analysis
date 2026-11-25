/* Shared Earth Engine implementation: all generated programs contain this code. */
// ==================== CONFIGURATION AND PRODUCT IDS ====================
var C3 = {
  version: 'c3_methods_v1_schema_v2',
  baId: 'MODIS/061/MCD64A1', lcId: 'MODIS/061/MCD12Q1',
  lstId: 'MODIS/061/MOD11A1',
  zoneAsset: 'projects/afd-cube/assets/RP_Ghana_GEE-Assets/ghana_aoi/acz',
  districtAsset: 'projects/afd-cube/assets/RP_Ghana_GEE-Assets/ghana_aoi/districts_within_acz',
  ghanaAsset: 'projects/afd-cube/assets/RP_Ghana_GEE-Assets/ghana_aoi/gha_admin0',
  driveFolder: 'RP1_C3_Viewer',
  crs: 'SR-ORG:6974',
  transform: [463.3127165279165, 0, -20015109.354, 0, -463.3127165279167, 7783653.6376640005],
  classes: [1,2,3,4,5,6,7,8,9,10,12,14],
  maxPixels: 1e9, tileScale: 4,
  projectionTolerance: 1e-6,
  // Observation years are independent of the fixed land-cover unions below.
  observationStartYear: 2001, observationEndYear: 2024
};
var C3_OPS = {
  and: function(a, b) { return ee.Image(a).and(b); },
  or: function(a, b) { return ee.Image(a).or(b); },
  not: function(a) { return ee.Image(a).not(); }
};
// ==================== CSV SCHEMA AND FIELD ORDER ====================
var C3_ID_FIELDS = ['run_id','schema_version','level','unit_id','unit_code','unit_name',
  'parent_level','parent_id','parent_code','parent_name','yyyymm','year','month'];
var C3_METRIC_FIELDS = ['modis_ba_km2','modis_burned_pixel_count','modis_ba_any',
  'modis_burnable_km2_union','modis_burnable_km2_annual','modis_burned_frac_union',
  'modis_burned_frac_annual','modis_aoi_area_land_km2','modis_zero_union_den_flag',
  'modis_zero_annual_den_flag'];
var C3_EXTRA_FIELDS = ['ba_domain','ba_domain_start_year','ba_domain_end_year','ba_status','ba_coverage_status',
  'ba_source_status','ba_source_count','ba_source_index','ba_lc_source_indexes',
  'ba_product','ba_lc_product','ba_boundary_asset','ba_ghana_asset',
  'ba_grid_crs','ba_grid_transform','ba_reducer','ba_sampled_pixel_count',
  'ba_known_union_area_km2','ba_known_union_burned_km2','ba_domain_unresolved_km2',
  'ba_domain_excluded_km2','ba_any_lc_missing_year_km2','ba_any_lw_missing_year_km2',
  'ba_any_lc_invalid_year_km2','ba_any_lw_invalid_year_km2',
  'ba_annual_unknown_km2','ba_state_qa_missing_km2','ba_state_burndate_masked_km2',
  'ba_state_unsupported_km2','ba_state_explicit_zero_km2','ba_state_accepted_km2',
  'ba_reason_qa_missing_km2','ba_reason_burndate_masked_km2','ba_reason_qa_nonland_km2',
  'ba_reason_qa_invalid_km2','ba_reason_shortened_km2','ba_reason_special_km2',
  'ba_reason_positive_special_km2','ba_reason_unexpected_burndate_km2',
  'ba_anomaly_area_km2','ba_anomaly_pixel_count',
  'ba_shortened_km2','ba_full_period_only_km2','ba_supported_area_km2',
  'ba_supported_fraction','ba_state_closure_km2'];
var C3_SELECTORS = C3_ID_FIELDS.concat(C3_METRIC_FIELDS).concat(C3_EXTRA_FIELDS);
// ==================== STUDY WINDOWS AND DATE VALIDATION ====================
function c3Profile(id) {
  var start=id==='BA2001'?2001:(id==='BA2012'?2012:null);
  if (start===null) throw new Error('Choose BA2001 or BA2012.');
  var a=C3.observationStartYear,b=C3.observationEndYear;
  if (!isFinite(a)||!isFinite(b)||Math.floor(a)!==a||Math.floor(b)!==b||a<2001||a>b||b>9999||b<start)
    throw new Error('Declare a valid complete observation period in C3 configuration.');
  return {id:id,start:start,end:2024,observationStart:Math.max(start,a),observationEnd:b};
}
function c3ObservationWindow(profile) {
  return {start:profile.observationStart===undefined?profile.start:profile.observationStart,
    end:profile.observationEnd===undefined?profile.end:profile.observationEnd};
}
function c3Selectors(profile,year) {
  return year<profile.start||year>profile.end?C3_SELECTORS.concat(['ba_annual_lc_source_index']):C3_SELECTORS;
}
function c3RequiredLcYears(profile,months) {
  var years=[],i;
  for(i=profile.start;i<=profile.end;i++)years.push(i);
  for(i=0;i<months.length;i++){
    c3ParseDate(profile,months[i].year,months[i].month);
    if(years.indexOf(months[i].year)<0)years.push(months[i].year);
  }
  return years.sort(function(a,b){return a-b;});
}
function c3Month(year, month) {
  var d = ee.Date.fromYMD(year, month, 1);
  return {start:d, end:d.advance(1, 'month')};
}
function c3ParseDate(profile, yearValue, monthValue) {
  var y = Number(yearValue), m = Number(monthValue);
  var window=c3ObservationWindow(profile);
  if (!isFinite(y) || Math.floor(y) !== y || !isFinite(m) || Math.floor(m) !== m || y < window.start || y > window.end || m < 1 || m > 12) {
    throw new Error('Month must be 1–12 and year must be inside configured observation period (' + window.start + '–' + window.end + ').');
  }
  return {year:y, month:m};
}
function c3Pad(x) { return x < 10 ? '0' + x : String(x); }
// ==================== DATA SOURCES AND ADMISSION PREFLIGHT ====================
function c3BaCollection(year, month) {
  var w = c3Month(year, month);
  return ee.ImageCollection(C3.baId).filterDate(w.start, w.end)
    .filterBounds(ee.FeatureCollection(C3.ghanaAsset).geometry());
}
function c3LcCollection(year) {
  var start = ee.Date.fromYMD(year, 1, 1);
  return ee.ImageCollection(C3.lcId).filterDate(start, start.advance(1,'year'));
}
function c3SourcePreflight(profile, months, units, level) {
  // Metadata only. Called on each action; missing, multiple, inaccessible, or a
  // BA projection mismatch blocks task creation and ordinary output.
  var years = c3RequiredLcYears(profile,months), lcCounts = [], lcIds = [], baCounts = [], baIds = [];
  var i;
  for (i = 0; i < years.length; i++) {
    var annualSource=c3LcCollection(years[i]); lcCounts.push(annualSource.size());
    lcIds.push(annualSource.aggregate_array('system:index'));
  }
  for (i = 0; i < months.length; i++) {
    var bc = c3BaCollection(months[i].year, months[i].month);
    baCounts.push(bc.size()); baIds.push(bc.aggregate_array('system:index'));
  }
  var receipt = ee.Dictionary({unit_count:units.size(),
    unit_ids:units.aggregate_array('unit_id'),
    unit_names:units.aggregate_array('unit_name'),
    parent_ids:units.aggregate_array('parent_id'),
    lc_counts:ee.List(lcCounts), lc_ids:ee.List(lcIds), ba_counts:ee.List(baCounts), ba_indexes:ee.List(baIds)}).getInfo();
  if (!receipt || !receipt.unit_count) throw new Error('No selected boundary units or inaccessible asset.');
  if (receipt.unit_ids.length !== receipt.unit_count || receipt.unit_names.length !== receipt.unit_count ||
      (level === 'district' && receipt.parent_ids.length !== receipt.unit_count)) {
    throw new Error('A required boundary identity field is missing; inspect the selected asset schema.');
  }
  var seen = {};
  for (i = 0; i < receipt.unit_ids.length; i++) {
    var id = receipt.unit_ids[i];
    if (id === null || id === undefined || String(id).trim() === '') throw new Error('Missing unit_id; check boundary field names.');
    if (seen[String(id)]) throw new Error('Duplicate unit_id in selected units: ' + id);
    seen[String(id)] = true;
    if (receipt.unit_names[i] === null || receipt.unit_names[i] === undefined || String(receipt.unit_names[i]).trim() === '') {
      throw new Error('Missing unit_name for ' + id + '.');
    }
    if (level === 'district' && (!receipt.parent_ids[i] || String(receipt.parent_ids[i]).trim() === '')) {
      throw new Error('Missing parent zone ID for district ' + id + '.');
    }
  }
  var lcStates = c3Admission(receipt.lc_counts), baStates = c3Admission(receipt.ba_counts);
  print('c3 source inventory (collection level; no pixel-support claim)',
    {years:years, lc_counts:receipt.lc_counts, lc_status:lcStates,
     months:months, ba_counts:receipt.ba_counts, ba_status:baStates, ba_indexes:receipt.ba_indexes});
  if (lcStates.indexOf('MISSING') >= 0 || lcStates.indexOf('AMBIGUOUS_MULTIPLE') >= 0) {
    throw new Error('Annual MCD12Q1 source missing or ambiguous; no results or tasks created.');
  }
  if (baStates.indexOf('MISSING') >= 0 || baStates.indexOf('AMBIGUOUS_MULTIPLE') >= 0) {
    throw new Error('A monthly MCD64A1 source is missing or ambiguous; no results or tasks created.');
  }
  if (receipt.ba_indexes.length !== months.length || receipt.ba_indexes.some(function(ids){
    return !ids || ids.length !== 1 || !c3SafeIndex(ids[0]);
  })) throw new Error('An admitted BA source lacks a unique system:index; no results or tasks created.');
  if (!receipt.lc_ids || receipt.lc_ids.length !== years.length || receipt.lc_ids.some(function(ids){
    return !ids || ids.length !== 1 || !c3SafeIndex(ids[0]);
  })) throw new Error('An admitted land-cover source lacks a unique system:index; no results or tasks created.');
  receipt.annual_lc_indexes={};
  for (i=0;i<years.length;i++) {
    receipt.annual_lc_indexes[years[i]]=receipt.lc_ids[i][0];
    if((years[i]<profile.start||years[i]>profile.end)&&receipt.annual_lc_indexes[years[i]]!==String(years[i])+'_01_01')
      throw new Error('Annual LC source index does not match observation year; no results or tasks created.');
  }
  receipt.lc_indexes=[];
  for (i=profile.start;i<=profile.end;i++) receipt.lc_indexes.push(receipt.annual_lc_indexes[i]);
  // Explicitly check each admitted monthly pair, not merely one representative.
  for (i = 0; i < months.length; i++) {
    var image = c3BaImage(receipt.ba_indexes[i][0]);
    var burnProj = image.select('BurnDate').projection().getInfo();
    var qaProj = image.select('QA').projection().getInfo();
    if (!c3ProjectionMatches(burnProj) || !c3ProjectionMatches(qaProj)) {
      print('Unexpected BA source projection', months[i], burnProj, qaProj);
      throw new Error('Admitted BA grid differs from the configured native grid; no results or tasks created.');
    }
  }
  var lcProjections = [];
  for (i = 0; i < years.length; i++) {
    var lcImage=c3LcImage(receipt.annual_lc_indexes[years[i]]);
    var lcProjection=lcImage.select('LC_Type1').projection(), lwProjection=lcImage.select('LW').projection();
    lcProjections.push(ee.Dictionary({year:years[i],lc_crs:lcProjection.crs(),lc_transform_wkt:lcProjection.transform(),
      lw_crs:lwProjection.crs(),lw_transform_wkt:lwProjection.transform()}));
  }
  var lcInfo=ee.List(lcProjections).getInfo();
  if (lcInfo.length !== years.length || lcInfo.some(function(v){
    return !v.lc_crs || !v.lc_transform_wkt || !v.lw_crs || !v.lw_transform_wkt;
  })) throw new Error('A land-cover source projection is unavailable.');
  print('c3 source grid check: BA BurnDate and QA checked for each admitted month; all annual LC/LW projections reported', lcInfo);
  print('c3 output grid and reducer', {crs:C3.crs, transform:C3.transform,
    reducer:'sum.unweighted; centroid-in-polygon', categorical_resampling:'nearest neighbour (Earth Engine default)'});
  return receipt;
}
// Use the admitted image ID in every BA graph. Collection IDs do not freeze
// the underlying catalogue version; record a source/version receipt externally.
function c3SafeIndex(index) {
  return typeof index === 'string' && /^[A-Za-z0-9_-]+$/.test(index);
}
function c3BaImage(index) {
  if (!c3SafeIndex(index)) throw new Error('Invalid admitted BA source index.');
  return ee.Image(C3.baId+'/'+index);
}
function c3LcImage(index) {
  if (!c3SafeIndex(index)) throw new Error('Invalid admitted land-cover source index.');
  return ee.Image(C3.lcId+'/'+index);
}
function c3ProjectionMatches(p) {
  if (!p || p.crs !== C3.crs || !p.transform || p.transform.length !== 6) return false;
  for (var i=0; i<6; i++) {
    if (typeof p.transform[i] !== 'number' || !isFinite(p.transform[i]) ||
        Math.abs(p.transform[i]-C3.transform[i]) > C3.projectionTolerance) return false;
  }
  return true;
}
// ==================== REPORTING UNITS AND GHANA CLIPPING ====================
function c3Units(level, zoneId, districtId) {
  var ghana = ee.FeatureCollection(C3.ghanaAsset).geometry();
  var fc = ee.FeatureCollection(level === 'acz' ? C3.zoneAsset : C3.districtAsset)
    .filter(ee.Filter.eq('zone_id', zoneId));
  if (level === 'district' && districtId) fc = fc.filter(ee.Filter.eq('dist_id', districtId));
  fc = fc.map(function(f) {
    f = ee.Feature(f);
    var geom = f.geometry().buffer(0,1).intersection(ghana.buffer(0,1), 1);
    var isZone = level === 'acz';
    var code = ee.Algorithms.If(isZone, f.get('zone_code'),
      ee.Algorithms.If(f.propertyNames().contains('dist_code'), f.get('dist_code'), ''));
    return ee.Feature(geom).set({level:level,
      unit_id:f.get(isZone ? 'zone_id' : 'dist_id'),
      unit_code:code, unit_name:f.get(isZone ? 'zone_name' : 'dist_name'),
      parent_level:isZone ? '' : 'acz', parent_id:isZone ? '' : f.get('zone_id'),
      parent_code:isZone ? '' : f.get('zone_code'), parent_name:isZone ? '' : f.get('zone_name')});
  });
  return fc;
}
function c3FlagAvailable(band) { return band.mask().unmask(0, false).gt(0); }
// ==================== LAND COVER ELIGIBILITY AND FIXED UNIONS ====================
function c3Annual(year, sourceIndex) {
  var img = c3LcImage(sourceIndex);
  var lcRaw = img.select('LC_Type1'), lwRaw = img.select('LW');
  var lcAvailable = c3FlagAvailable(lcRaw), lwAvailable = c3FlagAvailable(lwRaw);
  var lc = lcRaw.unmask(0, false), lw = lwRaw.unmask(0, false);
  var included = lc.remap(C3.classes, C3.classes.map(function(){return 1;}), 0).eq(1);
  var lcInvalid=lcAvailable.and(lc.lt(1).or(lc.gt(17)));
  var lwInvalid=lwAvailable.and(lw.neq(1)).and(lw.neq(2));
  var known = lcAvailable.and(lwAvailable).and(lcInvalid.not()).and(lwInvalid.not());
  return {eligible:known.and(included).and(lw.eq(2)), unknown:known.not(),
    lcMissing:lcAvailable.not(), lwMissing:lwAvailable.not(), lcInvalid:lcInvalid,
    lwInvalid:lwInvalid, lc:lcRaw, lw:lwRaw};
}
function c3Domain(profile,receipt) {
  if (!receipt || !receipt.lc_indexes || receipt.lc_indexes.length !== profile.end-profile.start+1) throw new Error('Missing admitted annual source IDs.');
  var yrs = [], annual = {}, lcMissing = ee.Image.constant(0), lwMissing = ee.Image.constant(0),
    lcInvalid=ee.Image.constant(0), lwInvalid=ee.Image.constant(0);
  for (var y=profile.start; y<=profile.end; y++) {
    var a = c3Annual(y,receipt.lc_indexes[y-profile.start]); annual[y] = a; yrs.push(a);
    lcMissing = lcMissing.or(a.lcMissing); lwMissing = lwMissing.or(a.lwMissing);
    lcInvalid = lcInvalid.or(a.lcInvalid); lwInvalid = lwInvalid.or(a.lwInvalid);
  }
  var d = c3DomainLogic(C3_OPS, yrs);
  d.annualSourceIndexes=receipt.annual_lc_indexes||{};
  Object.keys(d.annualSourceIndexes).forEach(function(key){
    var year=Number(key);
    if(year<profile.start||year>profile.end) annual[year]=c3Annual(year,d.annualSourceIndexes[key]);
  });
  d.annual = annual; d.anyLcMissing = lcMissing; d.anyLwMissing = lwMissing;
  d.anyLcInvalid = lcInvalid; d.anyLwInvalid = lwInvalid;
  return d;
}
// ==================== MONTHLY BURNED AREA EVIDENCE AND QA ====================
function c3Evidence(image) {
  var raw = image.select('BurnDate'), rawQa = image.select('QA');
  var b = raw.unmask(0, false), q = rawQa.unmask(0, false).toInt();
  var p = {qaAvailable:c3FlagAvailable(rawQa), burnAvailable:c3FlagAvailable(raw),
    positive:b.gt(0), zero:b.eq(0), land:q.bitwiseAnd(1).neq(0),
    valid:q.bitwiseAnd(2).neq(0), shortened:q.bitwiseAnd(4).neq(0),
    special:q.rightShift(5).bitwiseAnd(7).neq(0), outOfRange:b.lt(0).or(b.gt(366))};
  var result = c3ClassifyEvidence(C3_OPS, p);
  result.raw = raw; result.qa = rawQa; result.p = p;
  return result;
}
// ==================== NATIVE GRID AREA BANDS AND REDUCTION SUPPORT ====================
function c3AreaBand(mask, name) {
  return ee.Image.pixelArea().divide(1e6).multiply(ee.Image(mask).unmask(0,false)).rename(name);
}
function c3Stack(domain, evidence, year) {
  var u = domain.eligible, e = evidence, a = domain.annual[year];
  function inU(flag) { return u.and(flag); }
  var bands = [
    ee.Image.constant(1).rename('samples'),
    ee.Image(u).multiply(e.accepted).rename('burn_pixels'),
    ee.Image(u).multiply(e.anomaly).rename('anomaly_pixels'),
    c3AreaBand(u,'union'), c3AreaBand(domain.unresolved,'domain_unresolved'),
    c3AreaBand(domain.excluded,'domain_excluded'),
    c3AreaBand(domain.anyLcMissing,'any_lc_missing'), c3AreaBand(domain.anyLwMissing,'any_lw_missing'),
    c3AreaBand(domain.anyLcInvalid,'any_lc_invalid'), c3AreaBand(domain.anyLwInvalid,'any_lw_invalid'),
    c3AreaBand(a.eligible,'annual'), c3AreaBand(a.unknown,'annual_unknown'),
    c3AreaBand(inU(e.qa_missing),'state_qa_missing'),
    c3AreaBand(inU(e.burndate_missing),'state_burndate_masked'),
    c3AreaBand(inU(e.unsupported),'state_unsupported'),
    c3AreaBand(inU(e.explicit_zero),'state_explicit_zero'),
    c3AreaBand(inU(e.accepted),'state_accepted'),
    c3AreaBand(inU(e.flag_qa_missing),'reason_qa_missing'),
    c3AreaBand(inU(e.flag_burndate_masked),'reason_burndate_masked'),
    c3AreaBand(inU(e.flag_qa_nonland),'reason_qa_nonland'),
    c3AreaBand(inU(e.flag_qa_invalid),'reason_qa_invalid'),
    c3AreaBand(inU(e.flag_shortened),'reason_shortened'),
    c3AreaBand(inU(e.flag_special),'reason_special'),
    c3AreaBand(inU(e.flag_positive_special),'reason_positive_special'),
    c3AreaBand(inU(e.flag_unexpected_burndate),'reason_unexpected_burndate'),
    c3AreaBand(inU(e.anomaly),'anomaly_area'),
    c3AreaBand(inU(e.accepted).and(e.flag_shortened),'ba_shortened'),
    c3AreaBand(inU(e.accepted).and(e.flag_shortened.not()),'ba_full'),
    c3AreaBand(inU(e.accepted.or(e.explicit_zero)),'supported')
  ];
  return ee.Image.cat(bands).toDouble();
}
// A non-null default is essential: Earth Engine may raise on an absent key
// when Dictionary.get has no default. Null and absent remain missing evidence.
var C3_MISSING_REDUCTION = '__c3_missing_reduction_value__';
function c3MissingNumber(d, key) {
  var v = ee.Dictionary(d).get(key, C3_MISSING_REDUCTION);
  return ee.Number(ee.Algorithms.If(ee.Algorithms.IsEqual(v,null),1,
    ee.Algorithms.If(ee.Algorithms.IsEqual(v,C3_MISSING_REDUCTION),1,0)));
}
function c3Number(d, key) {
  var v = ee.Dictionary(d).get(key, C3_MISSING_REDUCTION);
  return ee.Number(ee.Algorithms.If(c3MissingNumber(d,key).eq(1), 0, v));
}
// ==================== UNIT MONTH ROWS, DIAGNOSTICS AND WITHHOLDING ====================
function c3Row(unit, profile, date, domain, evidence, sourceIndex, lcIndexes, runId) {
  unit = ee.Feature(unit);
  // Each derived metric is intended to be valid at every sampled pixel centre.
  // An all-masked band can reduce to numeric zero, so dictionary null checks
  // alone cannot establish that its values were actually available.
  var requiredBands=['samples','burn_pixels','anomaly_pixels','union','domain_unresolved','domain_excluded',
    'any_lc_missing','any_lw_missing','any_lc_invalid','any_lw_invalid','annual','annual_unknown',
    'state_qa_missing','state_burndate_masked','state_unsupported','state_explicit_zero','state_accepted',
    'reason_qa_missing','reason_burndate_masked','reason_qa_nonland','reason_qa_invalid',
    'reason_shortened','reason_special','reason_positive_special','reason_unexpected_burndate','anomaly_area',
    'ba_shortened','ba_full','supported'];
  var metrics = c3Stack(domain,evidence,date.year);
  var gridCentres = ee.Image.constant(1).toDouble().rename('c3_grid_centres');
  var gridArea = ee.Image.pixelArea().divide(1e6).rename('c3_grid_area');
  // Reduce all metric masks to one validity indicator per pixel. These are
  // derived-band masks, not the raw MCD64 QA or BurnDate evidence masks.
  var allValid = metrics.mask().unmask(0,false).gt(0).reduce(ee.Reducer.min())
    .and(gridArea.mask().unmask(0,false).gt(0)).toDouble().rename('c3_all_valid_count');
  var values = metrics.addBands(ee.Image.cat([gridCentres,gridArea,allValid])).reduceRegion({
    reducer:ee.Reducer.sum().unweighted(), geometry:unit.geometry(),
    crs:C3.crs, crsTransform:C3.transform, maxPixels:C3.maxPixels, tileScale:C3.tileScale
  });
  var missingBands=ee.Number(0);
  requiredBands.forEach(function(key){
    missingBands=missingBands.add(c3MissingNumber(values,key));
  });
  var referenceMissing=c3MissingNumber(values,'c3_grid_centres');
  var n=c3Number(values,'c3_grid_centres');
  var countInvalid=n.lt(0).or(n.neq(n.round()));
  var extraMissing=c3MissingNumber(values,'c3_grid_area').add(c3MissingNumber(values,'c3_all_valid_count'));
  var validCount=c3Number(values,'c3_all_valid_count');
  // A reported zero reference cannot coexist with a positive independent area,
  // validity count, or source-stack centre count; treat it as a failed guard.
  var zeroReferenceConflict=n.eq(0).and(validCount.neq(0)
    .or(c3Number(values,'c3_grid_area').neq(0)).or(c3Number(values,'samples').neq(0)));
  var incomplete=referenceMissing.eq(0).and(countInvalid.or(zeroReferenceConflict).or(n.gt(0).and(
    missingBands.add(extraMissing).gt(0).or(validCount.neq(n)))));
  var reductionOK=referenceMissing.eq(0).and(incomplete.eq(0));
  var union = c3Number(values,'union');
  var unresolved = c3Number(values,'domain_unresolved');
  var annual = c3Number(values,'annual'), annualUnknown = c3Number(values,'annual_unknown');
  var ba = c3Number(values,'state_accepted'), burnedN = c3Number(values,'burn_pixels');
  var anomalyN=c3Number(values,'anomaly_pixels'), anomalyArea=c3Number(values,'anomaly_area');
  var s1=c3Number(values,'state_qa_missing'), s2=c3Number(values,'state_burndate_masked');
  var s3=c3Number(values,'state_unsupported'), s4=c3Number(values,'state_explicit_zero');
  var closure = s1.add(s2).add(s3).add(s4).add(ba).subtract(union);
  var supported = c3Number(values,'supported');
  var gridKm2=c3Number(values,'c3_grid_area');
  // Numerical accounting tolerance is for floating-point summation only, not
  // the vector boundary-equivalence tolerance or a validation of source truth.
  var tol=ee.Number(1e-8).max(gridKm2.abs().multiply(1e-10));
  var accountingBad=gridKm2.lte(0).or(c3Number(values,'samples').neq(n))
    .or(burnedN.lt(0)).or(burnedN.gt(n)).or(burnedN.neq(burnedN.round()))
    .or(anomalyN.lt(0)).or(anomalyN.gt(n)).or(anomalyN.neq(anomalyN.round()))
    .or(anomalyN.gt(0).neq(anomalyArea.gt(0))).or(anomalyArea.gt(s3.add(tol)))
    .or(burnedN.gt(0).neq(ba.gt(0)))
    .or(ba.gt(union.add(tol))).or(closure.abs().gt(tol))
    .or(c3Number(values,'domain_excluded').add(unresolved).add(union).subtract(gridKm2).abs().gt(tol))
    .or(annual.add(annualUnknown).gt(gridKm2.add(tol)))
    .or(c3Number(values,'ba_shortened').add(c3Number(values,'ba_full')).subtract(ba).abs().gt(tol))
    .or(supported.subtract(ba.add(s4)).abs().gt(tol)).or(supported.gt(union.add(tol)));
  // All remaining bands except the two counts represent nonnegative areas.
  requiredBands.slice(3).forEach(function(key){
    var a=c3Number(values,key);
    accountingBad=accountingBad.or(a.lt(tol.multiply(-1))).or(a.gt(gridKm2.add(tol)));
    if (key.indexOf('state_')===0 || key.indexOf('reason_')===0 ||
        key==='ba_shortened' || key==='ba_full' || key==='supported' || key==='anomaly_area') {
      accountingBad=accountingBad.or(a.gt(union.add(tol)));
    }
  });
  var accountingFailure=reductionOK.and(n.gt(0)).and(accountingBad);
  var dataOK=reductionOK.and(accountingFailure.eq(0));
  var domainUsable = dataOK.and(n.gt(0)).and(unresolved.eq(0));
  var areaUsable = domainUsable.and(anomalyN.eq(0));
  var annualUsable = dataOK.and(n.gt(0)).and(annualUnknown.eq(0));
  var goodFraction = areaUsable.and(union.gt(0));
  var status = ee.String(ee.Algorithms.If(referenceMissing,'EMPTY_REDUCTION_UNRESOLVED',
    ee.Algorithms.If(incomplete,'REDUCTION_INCOMPLETE',ee.Algorithms.If(n.eq(0),'NO_PIXEL_CENTRES',
      ee.Algorithms.If(accountingFailure,'ACCOUNTING_INCONSISTENCY',ee.Algorithms.If(unresolved.gt(0),'DOMAIN_UNRESOLVED',
        ee.Algorithms.If(anomalyN.gt(0),'SOURCE_PIXEL_ANOMALY',
          ee.Algorithms.If(union.eq(0),'ZERO_UNION_DENOMINATOR','ADMITTED'))))))));
  var coverage = ee.String(ee.Algorithms.If(referenceMissing,'EMPTY_REDUCTION_UNRESOLVED',
    ee.Algorithms.If(incomplete,'REDUCTION_INCOMPLETE',ee.Algorithms.If(n.eq(0),'NO_PIXEL_CENTRES',
    ee.Algorithms.If(accountingFailure,'ACCOUNTING_INCONSISTENCY',
    ee.Algorithms.If(union.eq(0),'NO_KNOWN_UNION_PIXELS',
      ee.Algorithms.If(supported.eq(0),'NO_SUPPORTED_EVIDENCE',
        ee.Algorithms.If(s1.add(s2).add(s3).gt(0),'PARTIAL_EVIDENCE',
          ee.Algorithms.If(c3Number(values,'reason_shortened').gt(0),
            'FULL_EVIDENCE_WITH_SHORTENING','FULL_EVIDENCE_NO_SHORTENING')))))))));
  function numeric(key) { return ee.Algorithms.If(dataOK.and(n.gt(0)), c3Number(values,key), null); }
  var properties = {
    run_id:runId, schema_version:'rp1_ba_c3_extended_v2',
    level:unit.get('level'), unit_id:unit.get('unit_id'), unit_code:unit.get('unit_code'),
    unit_name:unit.get('unit_name'), parent_level:unit.get('parent_level'),
    parent_id:unit.get('parent_id'), parent_code:unit.get('parent_code'), parent_name:unit.get('parent_name'),
    yyyymm:date.year*100+date.month, year:date.year, month:date.month,
    modis_ba_km2:ee.Algorithms.If(areaUsable,ba,null),
    modis_burned_pixel_count:ee.Algorithms.If(areaUsable,burnedN,null),
    modis_ba_any:ee.Algorithms.If(areaUsable,ba.gt(0).int(),null),
    modis_burnable_km2_union:ee.Algorithms.If(areaUsable,union,null),
    modis_burnable_km2_annual:ee.Algorithms.If(annualUsable,annual,null),
    modis_burned_frac_union:ee.Algorithms.If(goodFraction,ba.divide(union),null),
    // Fixed-union numerator divided by annual eligible denominator.
    modis_burned_frac_annual:ee.Algorithms.If(areaUsable.and(annualUsable).and(annual.gt(0)),ba.divide(annual),null),
    modis_aoi_area_land_km2:unit.geometry().area(1).divide(1e6),
    modis_zero_union_den_flag:ee.Algorithms.If(domainUsable,union.eq(0).int(),null),
    modis_zero_annual_den_flag:ee.Algorithms.If(annualUsable,annual.eq(0).int(),null),
    ba_domain:profile.id, ba_domain_start_year:profile.start, ba_domain_end_year:profile.end,
    ba_status:status, ba_coverage_status:coverage, ba_source_status:'ADMITTED', ba_source_count:1,
    ba_source_index:sourceIndex, ba_lc_source_indexes:lcIndexes.join('|'),
    ba_product:C3.baId, ba_lc_product:C3.lcId,
    ba_boundary_asset:ee.Algorithms.If(ee.Algorithms.IsEqual(unit.get('level'),'acz'),C3.zoneAsset,C3.districtAsset),
    ba_ghana_asset:C3.ghanaAsset,
    ba_grid_crs:C3.crs, ba_grid_transform:C3.transform.join(','),
    ba_reducer:'sum_unweighted_centroid', ba_sampled_pixel_count:ee.Algorithms.If(dataOK,n,null),
    ba_known_union_area_km2:numeric('union'), ba_known_union_burned_km2:numeric('state_accepted'),
    ba_domain_unresolved_km2:numeric('domain_unresolved'), ba_domain_excluded_km2:numeric('domain_excluded'),
    ba_any_lc_missing_year_km2:numeric('any_lc_missing'), ba_any_lw_missing_year_km2:numeric('any_lw_missing'),
    ba_any_lc_invalid_year_km2:numeric('any_lc_invalid'), ba_any_lw_invalid_year_km2:numeric('any_lw_invalid'),
    ba_annual_unknown_km2:numeric('annual_unknown'),
    ba_state_qa_missing_km2:numeric('state_qa_missing'), ba_state_burndate_masked_km2:numeric('state_burndate_masked'),
    ba_state_unsupported_km2:numeric('state_unsupported'), ba_state_explicit_zero_km2:numeric('state_explicit_zero'),
    ba_state_accepted_km2:numeric('state_accepted'),
    ba_reason_qa_missing_km2:numeric('reason_qa_missing'), ba_reason_burndate_masked_km2:numeric('reason_burndate_masked'),
    ba_reason_qa_nonland_km2:numeric('reason_qa_nonland'), ba_reason_qa_invalid_km2:numeric('reason_qa_invalid'),
    ba_reason_shortened_km2:numeric('reason_shortened'), ba_reason_special_km2:numeric('reason_special'),
    ba_reason_positive_special_km2:numeric('reason_positive_special'), ba_reason_unexpected_burndate_km2:numeric('reason_unexpected_burndate'),
    ba_anomaly_area_km2:numeric('anomaly_area'), ba_anomaly_pixel_count:numeric('anomaly_pixels'),
    ba_shortened_km2:numeric('ba_shortened'), ba_full_period_only_km2:numeric('ba_full'),
    ba_supported_area_km2:numeric('supported'),
    ba_supported_fraction:ee.Algorithms.If(dataOK.and(n.gt(0)).and(supported.gt(0)),ba.divide(supported),null),
    ba_state_closure_km2:ee.Algorithms.If(dataOK.and(n.gt(0)),closure,null)
  };
  if(date.year<profile.start||date.year>profile.end) {
    var annualIndex=domain.annualSourceIndexes[date.year];
    if(!annualIndex||!c3SafeIndex(annualIndex))throw new Error('Missing admitted annual LC source index for observation year.');
    if(annualIndex!==String(date.year)+'_01_01')throw new Error('Annual LC source index does not match observation year.');
    properties.ba_annual_lc_source_index=annualIndex;
  }
  return ee.Feature(null, properties);
}
// ==================== MONTHLY ROW COLLECTION ====================
function c3Rows(units, profile, dates, receipt) {
  var domain = c3Domain(profile,receipt), rows = ee.FeatureCollection([]);
  var runId = 'c3_' + new Date().toISOString().replace(/[-:.]/g,'');
  for (var i=0; i<dates.length; i++) {
    var d=dates[i], image=c3BaImage(receipt.ba_indexes[i][0]);
    var evidence=c3Evidence(image), sourceIndex=receipt.ba_indexes[i][0];
    var part=units.map((function(date, ev, idx){return function(unit){
      return c3Row(unit,profile,date,domain,ev,idx,receipt.lc_indexes,runId);
    };})(d,evidence,sourceIndex));
    rows=rows.merge(part);
  }
  return rows;
}
