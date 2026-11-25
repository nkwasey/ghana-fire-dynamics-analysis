/* =============================================================================
 RP1 — Monthly Burned-Area CSV Exporter (c3)
 Google Earth Engine JavaScript / Code Editor

 PURPOSE
   Export one monthly table per reporting scope and year for Ghana's
   agro-climatic zones (ACZs) or districts. Each analytical CSV contains the
   69-column extended record, including primary measurements, evidence-state
   diagnostics, status flags and provenance. All-ACZ tables combine zones;
   district tables are exported separately for each parent ACZ.

 STUDY PERIODS AND METHOD
   BA2001 uses the 2001–2024 eligibility union; BA2012 uses the separately
   constructed 2012–2024 union. Both the accepted burned-area numerator and
   primary denominator use the selected period's fixed union. Output year
   selection does not alter that union. MCD64A1 Collection 6.1 supplies
   monthly BurnDate and QA; MCD12Q1 Collection 6.1 supplies annual LC_Type1
   and LW. Reductions use the configured native MCD64A1 grid and unweighted
   pixel-centre rule.

   Valid positive burns with shortened mapping remain accepted and are
   flagged. Missing or unsupported evidence contributes zero under the agreed
   analytical scenario but does not establish physical absence of fire.
   Source anomalies in the known union, unresolved union membership and
   source or reduction failures are handled by the relevant withholding
   guards. Read ba_status and evidence diagnostics alongside primary fields.
   A blank fraction is undefined or withheld, not an automatic zero. The
   annual ratio uses the union numerator and annual denominator and may exceed 1.

 INPUTS
   - Ghana, ACZ and district Earth Engine assets specified in C3 settings.
   - MODIS/061/MCD64A1 and MODIS/061/MCD12Q1.
   - A Google Drive destination for the selected output domain.

 CONFIGURATION AND OPERATION
   1. Review asset IDs and domain destination folders. Set union, level,
      selected ACZ or all ACZs, and year or range in Controls.
   2. Inspect a selected month when needed. A district filter applies to the
      selected ACZ; an empty filter includes that ACZ's districts.
   3. Inspect the export plan and verify the scope, filenames and task count.
   4. Create annual extended CSV tasks and run intended tasks manually in Tasks.
   5. Inspect status, source and diagnostic fields, task receipts, row keys,
      expected months and units before using results.
   Optional unit-inventory receipts and boundary exception records are
   operational records, not alternative analytical BA tables.

 OUTPUT NAMING
   ACZ: rp1_ba_acz_monthly_c3_<ZONE>_<DOMAIN>_<YEAR>_ext.csv
   District: rp1_ba_district_monthly_c3_<ZONE>_<DOMAIN>_<YEAR>_ext.csv
   Filtered district names include a sanitized ID tag and hash. Generated
   task names and filename prefixes use an internal maximum of 80 characters;
   this is a project safeguard, not a stated Earth Engine maximum.
   A selected-month inspection is separately identified. Combined ACZ output
   is a table of the five ACZs, not an additional Ghana national unit.

 SOURCE AND SCOPE NOTES
   Preflight requires exactly one BA image for each requested month and one
   annual land-cover image for each union year. A source/grid failure may block task creation;
   it does not create a zero-burn row. Full-period plans can require hundreds
   of sequential metadata checks. Begin with bounded year ranges as appropriate.
   Asset IDs are references rather than immutable geometry hashes. Record task
   receipts and document the final asset handoff and verification separately.
 ============================================================================= */

/* RP1 c3: pure logical expressions shared by Earth Engine and synthetic tests. */
// ==================== EXCLUSIVE EVIDENCE STATES AND OVERLAPPING FLAGS ====================
function c3ClassifyEvidence(O, p) {
  // Missingness is retained separately from filled numeric values. One source
  // image has already been admitted; this function does not mosaic images.
  var qaMissing = O.not(p.qaAvailable);
  var burnMissing = O.and(p.qaAvailable, O.not(p.burnAvailable));
  var supported = O.and(O.and(p.qaAvailable, p.burnAvailable), O.and(p.land, p.valid));
  // A positive anomaly is evaluated even when the QA land/valid bits fail.
  // outOfRange includes negatives as a reason; the positive condition here
  // restricts anomalies to positive values above 366 or conflicting codes.
  var anomaly = O.and(O.and(p.qaAvailable, p.burnAvailable),
    O.and(p.positive, O.or(p.outOfRange, p.special)));
  var accepted = O.and(O.and(supported, p.positive), O.not(anomaly));
  var explicitZero = O.and(O.and(supported, p.zero), O.not(p.special));
  var unsupported = O.and(O.and(p.qaAvailable, p.burnAvailable),
    O.not(O.or(accepted, explicitZero)));
  return {
    qa_missing: qaMissing,
    burndate_missing: burnMissing,
    unsupported: unsupported,
    explicit_zero: explicitZero,
    accepted: accepted,
    anomaly: anomaly,
    flag_qa_missing: O.not(p.qaAvailable),
    flag_burndate_masked: O.not(p.burnAvailable),
    flag_qa_nonland: O.and(p.qaAvailable, O.not(p.land)),
    flag_qa_invalid: O.and(p.qaAvailable, O.not(p.valid)),
    flag_shortened: O.and(p.qaAvailable, p.shortened),
    flag_special: O.and(p.qaAvailable, p.special),
    flag_positive_special: O.and(O.and(p.qaAvailable, p.burnAvailable), O.and(p.positive, p.special)),
    flag_unexpected_burndate: O.and(p.burnAvailable, p.outOfRange)
  };
}
// ==================== PERIOD UNION ELIGIBILITY ====================
function c3DomainLogic(O, years) {
  if (!years.length) throw new Error('At least one land-cover year is required.');
  var eligible = years[0].eligible;
  var unknown = years[0].unknown;
  for (var i = 1; i < years.length; i++) {
    eligible = O.or(eligible, years[i].eligible);
    unknown = O.or(unknown, years[i].unknown);
  }
  return {
    eligible: eligible,
    unresolved: O.and(O.not(eligible), unknown),
    excluded: O.and(O.not(eligible), O.not(unknown)),
    any_unknown_year: unknown
  };
}
// ==================== SOURCE COUNT ADMISSION ====================
function c3Admission(counts) {
  var out = [];
  for (var i = 0; i < counts.length; i++) {
    if (counts[i] === 0) out.push('MISSING');
    else if (counts[i] === 1) out.push('ADMITTED');
    else out.push('AMBIGUOUS_MULTIPLE');
  }
  return out;
}

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

// =============================================================================
// RP1 — Monthly Burned-Area CSV Exporter
// Earth Engine Code Editor: ACZ and district monthly extended CSVs
//
// The selected BA2001 or BA2012 fixed union is used for both the accepted
// burned-area numerator and primary denominator.  Each annual task exports
// all 69 analytical, evidence-state, quality and provenance fields.  Export
// year selection never changes the fixed union's period.  The shared c3 core
// provides source admission, native-grid reduction, anomaly withholding and
// accounting rules.  Selected-month exports support focused inspection.
//
// Choose reporting level, zone scope, fixed union and years in Controls; use
// Exports to inspect the task plan and create the requested tasks.  Tasks are
// created but never started by the script.  Optional district QA and boundary
// exception records are operational records, not alternative BA tables.
// =============================================================================

// ========================== 01. EXPORT CONFIGURATION ==========================
var C3X_ZONES=[{id:'coastal_zone',code:'CZ',name:'Coastal Zone'},
  {id:'forest_zone',code:'FZ',name:'Forest Zone'},
  {id:'guinea_savannah',code:'GS',name:'Guinea Savannah'},
  {id:'sudan_savannah',code:'SS',name:'Sudan Savannah'},
  {id:'transition_zone',code:'TZ',name:'Transition Zone'}];
function c3xZone(id) {
  for(var i=0;i<C3X_ZONES.length;i++) if(C3X_ZONES[i].id===id) return C3X_ZONES[i];
  throw new Error('Unrecognised ACZ: '+id);
}
function c3xIdTag(id) {
  var hash=2166136261;
  for(var i=0;i<id.length;i++){var v=hash^id.charCodeAt(i);hash=(v+(v<<1)+(v<<4)+(v<<7)+(v<<8)+(v<<24))|0;}
  return id.replace(/[^A-Za-z0-9_-]/g,'_').slice(0,12)+'_'+('00000000'+(hash>>>0).toString(16)).slice(-8);
}
function c3xFolder(profile) { return profile.id==='BA2001'?'RP1_Project_MODIS_BA_c3_2001':'RP1_Project_MODIS_BA_c3_2012'; }
function c3xDates(year) {var dates=[];for(var m=1;m<=12;m++)dates.push({year:year,month:m});return dates;}
function c3xMonthList(start,end){var dates=[];for(var y=start;y<=end;y++)dates=dates.concat(c3xDates(y));return dates;}
// 80 characters is a conservative project rule for the generated prefix,
// not a published Earth Engine maximum. It excludes the added .csv extension.
function c3xValidateName(name) {
  if(typeof name!=='string'||name.length<1||name.length>80||!/^[A-Za-z0-9_-]+$/.test(name))
    throw new Error('Generated task/CSV prefix violates the project naming rule (1–80 ASCII letters, numbers, hyphens or underscores): '+name);
  return name;
}
function c3xPrefix(spec,zone) {
  var zoneCode=zone==='ALL_ACZ'?'ALL_ACZ':c3xZone(zone).code;
  var prefix='rp1_ba_'+spec.level+'_monthly_c3_'+zoneCode+'_'+spec.profile.id;
  if(spec.district) prefix+='_D_'+c3xIdTag(spec.district);
  return prefix;
}
function c3xNames(spec,zone,year) {
  var p=c3xPrefix(spec,zone);
  var ext=c3xValidateName(p+'_'+year+'_ext');
  if(spec.level==='acz')return {ext:ext};
  return {ext:ext,qa:c3xValidateName(p+'_'+spec.yearStart+'-'+spec.yearEnd+'_qa_by_acz')};
}
function c3xBoundaryName(spec,zone) {
  var p=c3xPrefix(spec,zone);
  if(spec.level==='district') return c3xValidateName(p+'_'+spec.yearStart+'-'+spec.yearEnd+'_boundary');
  var n=p+'_boundary_issue_log';
  if(spec.yearStart!==spec.profile.start||spec.yearEnd!==spec.profile.end)n+='_'+spec.yearStart+'_to_'+spec.yearEnd;
  return c3xValidateName(n);
}
/* Pure plan. ACZ all is one combined table/year; district all is per-zone/year. */
function c3xPlan(spec) {
  var groups=spec.level==='acz'&&spec.scope==='all'?['ALL_ACZ']:spec.zones.slice();
  var out=[],i,y,n;
  for(i=0;i<groups.length;i++){
    for(y=spec.yearStart;y<=spec.yearEnd;y++){
      n=c3xNames(spec,groups[i],y);
      out.push({kind:'ext',zone:groups[i],year:y,name:n.ext});
    }
    if(spec.level==='district'&&spec.includeInventory)out.push({kind:'qa',zone:groups[i],year:null,name:c3xNames(spec,groups[i],spec.yearStart).qa});
  }
  return out;
}
function c3xUnits(level,zones,district) {
  var fc=ee.FeatureCollection([]);
  zones.forEach(function(zone){fc=fc.merge(c3Units(level,zone,district));});
  return fc;
}
/* Validate the full asset BEFORE zone filtering; unassigned units cannot vanish silently.
 * Geometry checks below block zero-area units without dropping them. */
// ========================= 02. BOUNDARY VALIDATION =========================
function c3xBoundaryInventory(level, districtFilter, filterZone) {
  c3xBoundaryIssues=[];c3xBoundaryIssueSettings=null;
  var raw=ee.FeatureCollection(level==='acz'?C3.zoneAsset:C3.districtAsset);
  var ids=level==='acz'?'zone_id':'dist_id',names=level==='acz'?'zone_name':'dist_name';
  var annotated=raw.map(function(f){f=ee.Feature(f);return f.set('c3x_inventory_row',ee.Dictionary({
    id:f.get(ids),name:f.get(names),zone:f.get('zone_id'),code:f.get('zone_code'),zoneName:f.get('zone_name')}));});
  var x=ee.Dictionary({count:raw.size(),rows:annotated.aggregate_array('c3x_inventory_row')}).getInfo();
  if(!x||!x.count)throw new Error('Boundary asset is empty or inaccessible.');
  if(!x.rows||x.rows.length!==x.count)throw new Error('Could not inventory every boundary feature.');
  var seen=Object.create(null),counts={}; C3X_ZONES.forEach(function(z){counts[z.id]=0;});
  // A compact district tag is not globally unique. When filtering one
  // district, reject a colliding tag within its zone using this same asset
  // inventory; this cannot discover earlier tasks or files in other sessions.
  var filterTag=level==='district'&&districtFilter?c3xIdTag(String(districtFilter)):null;
  for(var i=0;i<x.count;i++){
    var row=x.rows[i]||{},id=row.id,name=row.name,z=row.zone,code=row.code,zn=row.zoneName;
    if(id===null||id===undefined||String(id).trim()===''||name===null||name===undefined||String(name).trim()===''||
       zn===null||zn===undefined||String(zn).trim()==='')throw new Error('Blank boundary identity or name at row '+i+'.');
    var key=String(id);if(seen[key])throw new Error('Duplicate unit ID in boundary asset: '+key);seen[key]=true;
    var zone=c3xZone(String(z));if(String(code)!==zone.code)throw new Error('Incorrect zone_code for '+key+': '+code);
    if(filterTag&&zone.id===filterZone&&key!==String(districtFilter)&&c3xIdTag(key)===filterTag)
      throw new Error('District filename tag collision in selected zone between '+districtFilter+' and '+key+'; no data tasks created.');
    counts[zone.id]++;
  }
  if(level==='acz')C3X_ZONES.forEach(function(z){if(counts[z.id]!==1)throw new Error('ACZ asset must contain exactly one feature for '+z.id);});
  print('c3 exporter unfiltered boundary ID/parent inventory (not a geometry equivalence check)',{asset:level==='acz'?C3.zoneAsset:C3.districtAsset,count:x.count,counts_by_zone:counts});
  return {total:x.count,counts:counts};
}
var c3xBoundaryIssues=[],c3xBoundaryIssueSettings=null;
/* Check the same Ghana-clipped geometries the core will reduce. Zero-area units
 * block the batch; they are never silently removed. This is not an equivalence test. */
function c3xGeometryPreflight(units,s) {
  c3xBoundaryIssues=[];c3xBoundaryIssueSettings=null;
  var annotated=units.map(function(f){f=ee.Feature(f);return f.set('c3x_geometry_row',ee.Dictionary({
    id:f.get('unit_id'),zone:f.get(s.level==='district'?'parent_id':'unit_id'),area:f.geometry().area(1)}));});
  var obj=ee.Dictionary({count:units.size(),rows:annotated.aggregate_array('c3x_geometry_row')}).getInfo();
  if(!obj||!obj.count||!obj.rows||obj.rows.length!==obj.count)
    throw new Error('Could not verify every selected Ghana-clipped unit geometry.');
  for(var i=0;i<obj.count;i++){
    var item=obj.rows[i]||{};
    if(typeof item.area!=='number'||!isFinite(item.area))throw new Error('Could not evaluate clipped unit area: '+item.id);
    if(item.area<=0)c3xBoundaryIssues.push({unit_id:item.id,zone_id:item.zone,reason:'ZERO_GHANA_CLIPPED_VECTOR_AREA',area_m2:item.area});
  }
  print('c3 selected-unit Ghana-clipped area preflight (not geometry-equivalence validation)',{count:obj.count,zero_area_count:c3xBoundaryIssues.length});
  if(c3xBoundaryIssues.length){c3xBoundaryIssueSettings=s;print('Blocked unit exceptions, no units dropped',c3xBoundaryIssues);
    throw new Error('Zero Ghana-clipped geometry area in '+c3xBoundaryIssues.length+' selected unit(s). No data tasks created; see Console and optional boundary exception log.');}
}
function c3xAnnualReceipt(receipt,offset) {
  return {lc_indexes:receipt.lc_indexes,annual_lc_indexes:receipt.annual_lc_indexes,ba_indexes:receipt.ba_indexes.slice(offset,offset+12)};
}
// ========================== 03. EXPORTER INTERFACE ==========================
var c3xPanel=ui.Panel({style:{width:'400px',padding:'9px'}});
c3xPanel.add(ui.Label('RP1 c3 | Monthly BA CSV exporter',{fontWeight:'bold',fontSize:'17px'}));
c3xPanel.add(ui.Label('No source checks or export tasks run on startup.',{fontSize:'11px',color:'#8b4d00'}));
var c3xStatus=ui.Label('Ready. Choose settings and inspect the export plan.',{whiteSpace:'normal',color:'#245672'});c3xPanel.add(c3xStatus);
var c3xControls=ui.Panel(),c3xLayers=ui.Panel(),c3xExports=ui.Panel(),c3xAbout=ui.Panel();
function c3xTab(t){c3xControls.style().set('shown',t==='controls');c3xLayers.style().set('shown',t==='layers');c3xExports.style().set('shown',t==='exports');c3xAbout.style().set('shown',t==='about');}
var c3xNav=ui.Panel({layout:ui.Panel.Layout.flow('horizontal')});
['controls','layers','exports','about'].forEach(function(t){c3xNav.add(ui.Button({label:t.charAt(0).toUpperCase()+t.slice(1),onClick:function(){c3xTab(t);}}));});
c3xPanel.add(c3xNav);c3xPanel.add(c3xControls);c3xPanel.add(c3xLayers);c3xPanel.add(c3xExports);c3xPanel.add(c3xAbout);
var c3xProfile=ui.Select({items:['BA2001','BA2012'],value:'BA2001'});
var c3xLevel=ui.Select({items:['acz','district'],value:'acz'});
var c3xScope=ui.Select({items:['Selected ACZ','All ACZs'],value:'Selected ACZ'});
var c3xZoneSelect=ui.Select({items:C3X_ZONES.map(function(z){return z.id;}),value:'forest_zone'});
var c3xDistrict=ui.Textbox({placeholder:'Optional exact dist_id; one ACZ only',value:''});
var c3xPreviewYear=ui.Textbox({value:String(C3.observationEndYear)}),c3xPreviewMonth=ui.Textbox({value:'1'});
var c3xRange=ui.Select({items:['Selected year','Year range','Full domain period'],value:'Selected year'});
var c3xStart=ui.Textbox({value:String(C3.observationEndYear)}),c3xEnd=ui.Textbox({value:String(C3.observationEndYear)});
var c3xInventory=ui.Checkbox({label:'Also create district unit-inventory QA receipt(s)',value:false});
function c3xControl(label,widget){c3xControls.add(ui.Label(label,{fontWeight:'bold',margin:'5px 0 1px 0'}));c3xControls.add(widget);}
c3xControl('Fixed union domain',c3xProfile);c3xControl('Reporting level',c3xLevel);
c3xControl('Export geography',c3xScope);c3xControl('Selected ACZ (also used for preview)',c3xZoneSelect);
c3xControl('District filter: export and preview (blank = all districts)',c3xDistrict);
c3xControl('Preview year',c3xPreviewYear);c3xControl('Preview month (1–12)',c3xPreviewMonth);
c3xControl('Export year mode',c3xRange);c3xControl('First year for range',c3xStart);c3xControl('Last year for range',c3xEnd);
c3xControls.add(c3xInventory);
function c3xSettings() {
  var profile=c3Profile(c3xProfile.getValue()),level=c3xLevel.getValue();
  var scope=c3xScope.getValue()==='All ACZs'?'all':'one',zone=c3xZoneSelect.getValue();
  var district=(c3xDistrict.getValue()||'').trim();
  if(level==='acz'&&district)throw new Error('Clear the district filter for ACZ exports.');
  if(scope==='all'&&district)throw new Error('A district filter requires Selected ACZ.');
  var date=c3ParseDate(profile,c3xPreviewYear.getValue(),c3xPreviewMonth.getValue());
  var mode=c3xRange.getValue(),a,b;
  var window=c3ObservationWindow(profile);
  if(mode==='Full domain period'){a=window.start;b=window.end;}
  else if(mode==='Selected year'){a=date.year;b=date.year;}
  else {a=Number(c3xStart.getValue());b=Number(c3xEnd.getValue());
    if(!isFinite(a)||!isFinite(b)||Math.floor(a)!==a||Math.floor(b)!==b||a<window.start||b>window.end||a>b)
      throw new Error('Year range must be ordered whole years inside configured observation coverage.');}
  return {profile:profile,level:level,scope:scope,zones:scope==='all'?C3X_ZONES.map(function(z){return z.id;}):[zone],
    previewZone:zone,district:district,date:date,yearStart:a,yearEnd:b,includeInventory:c3xInventory.getValue()};
}
var c3xPlanText=ui.Label('No plan inspected.',{whiteSpace:'normal',fontSize:'11px'});c3xExports.add(c3xPlanText);
function c3xDescribe(s,plan){
  return 'For full-period plans, source preflight checks every month and may be slow; use bounded year batches when needed. Prior Drive/Tasks names from other sessions cannot be detected.\nDomain: '+s.profile.id+' ('+s.profile.start+'–'+s.profile.end+' union)\nLevel: '+s.level+'; zones: '+s.zones.join(', ')+
    '\nDistrict filter: '+(s.district||'all selected-zone districts')+'\nExport years: '+s.yearStart+'–'+s.yearEnd+
    '\nFolder: '+c3xFolder(s.profile)+'\n'+plan.length+' tasks planned; none created by plan.\n'+
    plan.slice(0,15).map(function(x){return x.name+'.csv';}).join('\n')+
    (plan.length>15?'\n... '+(plan.length-15)+' more; full name list printed to Console.':'');
}
var c3xInspectedSignature='';
function c3xSignature(s,p){return JSON.stringify({folder:c3xFolder(s.profile),tasks:p});}
function c3xInspectPlan(){try{var s=c3xSettings(),p=c3xPlan(s);c3xInspectedSignature=c3xSignature(s,p);c3xPlanText.setValue(c3xDescribe(s,p));print('c3 CSV export plan (not tasks)',p);c3xStatus.setValue('Plan inspected. Source and boundary checks occur before task creation.');}catch(e){c3xFail(e);}}
function c3xFail(e){var msg=String((e&&e.message)||e);c3xStatus.setValue('BLOCKED: '+msg);print('c3 exporter blocked: '+msg);}
// ======================== 04. SELECTED-MONTH PREVIEW ========================
function c3xPreview(){try{
  var s=c3xSettings(),u=c3xUnits(s.level,[s.previewZone],s.district);
  c3xStatus.setValue('Checking identities and source metadata for selected-month preview...');
  c3xBoundaryInventory(s.level,s.district,s.previewZone);c3xGeometryPreflight(u,s);var receipt=c3SourcePreflight(s.profile,[s.date],u,s.level);
  var dom=c3Domain(s.profile,receipt),ev=c3Evidence(c3BaImage(receipt.ba_indexes[0][0]));
  Map.layers().reset();Map.addLayer(ee.Image().byte().paint(u,1,2),{palette:['111111']},'Selected reporting units',true);
  Map.addLayer(dom.eligible.selfMask().clip(u.geometry()),{palette:['e6c442']},'Fixed union eligible',false);
  Map.addLayer(dom.unresolved.selfMask().clip(u.geometry()),{palette:['a354d5']},'Unresolved union',true);
  Map.addLayer(dom.eligible.and(ev.accepted).selfMask().clip(u.geometry()),{palette:['d7191c']},'Accepted pixel evidence; inspect unit status',true);
  Map.addLayer(dom.eligible.and(ev.anomaly).selfMask().clip(u.geometry()),{palette:['00d0d0']},'Anomalous source pixels',true);
  Map.centerObject(u,s.level==='district'?9:7);
  print('c3 exporter selected-month preview; reporting status controls usability',c3Rows(u,s.profile,[s.date],receipt));
  c3xStatus.setValue('Preview source admitted. Inspect Console rows and status; pixel evidence is not a unit admission.');
}catch(e){c3xFail(e);}}
// ========================== 05. EXPORT TASK CREATION ==========================
var c3xCreatedPrefixes=Object.create(null);
function c3xCheckUnused(names){
  var seen=Object.create(null); names.forEach(function(n){
    if(seen[n]||c3xCreatedPrefixes[n])throw new Error('Task prefix already created in this session: '+n+'; inspect Tasks before retrying.');
    seen[n]=true;
  });
}
function c3xSelectedMonth(){try{
  var s=c3xSettings(),u=c3xUnits(s.level,[s.previewZone],s.district);
  c3xStatus.setValue('Checking selected-month inputs...');c3xBoundaryInventory(s.level,s.district,s.previewZone);c3xGeometryPreflight(u,s);
  var receipt=c3SourcePreflight(s.profile,[s.date],u,s.level);
  var name=c3xValidateName('rp1_ba_inspection_c3_'+s.level+'_'+c3xZone(s.previewZone).code+'_'+s.profile.id+'_'+s.date.year+c3Pad(s.date.month)+(s.district?'_D_'+c3xIdTag(s.district):'')+'_ext');
  c3xCheckUnused([c3xFolder(s.profile)+'/'+name]);
  Export.table.toDrive({collection:c3Rows(u,s.profile,[s.date],receipt),description:name,folder:c3xFolder(s.profile),fileNamePrefix:name,fileFormat:'CSV',selectors:c3Selectors(s.profile,s.date.year)});
  c3xCreatedPrefixes[c3xFolder(s.profile)+'/'+name]=true;
  c3xStatus.setValue('One selected-month CSV task created; run it manually in Tasks.');
}catch(e){c3xFail(e);}}
var c3xLastPlan='';
function c3xQueue(){
  var created=[],s,plan;
  try {
    s=c3xSettings();plan=c3xPlan(s);var signature=c3xSignature(s,plan);
    if(signature!==c3xInspectedSignature)throw new Error('Inspect the current export plan first; settings changed or plan has not been inspected.');
    if(signature===c3xLastPlan)throw new Error('This exact plan was already created in this session; change selection or reload after reviewing Tasks.');
    c3xCheckUnused(plan.map(function(t){return c3xFolder(s.profile)+'/'+t.name;}));
    if(plan.length>260)throw new Error('Plan exceeds the 260-task session cap; use a shorter year range.');
    c3xStatus.setValue('Checking full unfiltered boundary inventory and all requested source months. Full-period preflight may take time...');
    var inv=c3xBoundaryInventory(s.level,s.district,s.previewZone),units=c3xUnits(s.level,s.zones,s.district),dates=c3xMonthList(s.yearStart,s.yearEnd);
    c3xGeometryPreflight(units,s);
    var receipt=c3SourcePreflight(s.profile,dates,units,s.level);
    // Ensure every selected zone has units, before any task is created.
    for(var zi=0;zi<s.zones.length;zi++){
      if(!inv.counts[s.zones[zi]])throw new Error('Selected zone has no units: '+s.zones[zi]);
    }
    // Preflight above certifies all selected units and all selected months as one scope.
    var groups=s.level==='acz'&&s.scope==='all'?['ALL_ACZ']:s.zones;
    for(var i=0;i<groups.length;i++){
      var z=groups[i],groupZones=z==='ALL_ACZ'?s.zones:[z],groupUnits=c3xUnits(s.level,groupZones,s.district);
      for(var y=s.yearStart;y<=s.yearEnd;y++){
        var yr=c3xDates(y),yrReceipt=c3xAnnualReceipt(receipt,(y-s.yearStart)*12),rows=c3Rows(groupUnits,s.profile,yr,yrReceipt),names=c3xNames(s,z,y);
        Export.table.toDrive({collection:rows,description:names.ext,folder:c3xFolder(s.profile),fileNamePrefix:names.ext,fileFormat:'CSV',selectors:c3Selectors(s.profile,y)});created.push(names.ext);c3xCreatedPrefixes[c3xFolder(s.profile)+'/'+names.ext]=true;
      }
      if(s.level==='district'&&s.includeInventory){
        var qname=c3xNames(s,z,s.yearStart).qa;
        var q=ee.FeatureCollection([ee.Feature(null,{schema_version:'c3_unit_inventory_v1',domain:s.profile.id,zone_id:z,zone_code:c3xZone(z).code,
          district_filter:s.district||'',selected_unit_count:groupUnits.size(),raw_asset_zone_count:inv.counts[z],
          identity_preflight:'PASSED',geometry_preflight:'CLIPPED_NONZERO_AREA_ONLY',source_preflight:'PASSED',
          start_year:s.yearStart,end_year:s.yearEnd,boundary_asset:C3.districtAsset,ghana_asset:C3.ghanaAsset})]);
        Export.table.toDrive({collection:q,description:qname,folder:c3xFolder(s.profile),fileNamePrefix:qname,fileFormat:'CSV',
          selectors:['schema_version','domain','zone_id','zone_code','district_filter','selected_unit_count','raw_asset_zone_count','identity_preflight','geometry_preflight','source_preflight','start_year','end_year','boundary_asset','ghana_asset']});created.push(qname);c3xCreatedPrefixes[c3xFolder(s.profile)+'/'+qname]=true;
      }
    }
    c3xLastPlan=signature;print('c3 tasks created; manual Run required',created);
    c3xStatus.setValue(created.length+' tasks created. They have NOT been submitted; review and run them manually.');
  }catch(e){
    if(created.length){print('PARTIAL TASK CREATION; inspect and remove duplicates manually before retry',created);c3xStatus.setValue('PARTIAL: '+created.length+' tasks created before error. Review Tasks before retrying. '+String((e&&e.message)||e));}
    else c3xFail(e);
  }
}
function c3xExportBoundaryIssues(){
  var created=[];
  try {
    if(!c3xBoundaryIssueSettings||!c3xBoundaryIssues.length)throw new Error('No recorded zero-area boundary issues from the latest preflight.');
    var s=c3xBoundaryIssueSettings,zones=[];
    c3xBoundaryIssues.forEach(function(issue){if(zones.indexOf(String(issue.zone_id))<0)zones.push(String(issue.zone_id));});
    var names=zones.map(function(z){return c3xBoundaryName(s,z);});
    c3xCheckUnused(names.map(function(n){return c3xFolder(s.profile)+'/'+n;}));
    zones.forEach(function(z,i){var features=c3xBoundaryIssues.filter(function(x){return String(x.zone_id)===z;}).map(function(x){
      return ee.Feature(null,{domain:s.profile.id,level:s.level,unit_id:x.unit_id,zone_id:x.zone_id,
        reason:x.reason,clipped_area_m2:x.area_m2,disposition:'BLOCKED_NOT_DROPPED',boundary_asset:s.level==='acz'?C3.zoneAsset:C3.districtAsset,ghana_asset:C3.ghanaAsset});});
      var n=names[i];Export.table.toDrive({collection:ee.FeatureCollection(features),description:n,folder:c3xFolder(s.profile),fileNamePrefix:n,fileFormat:'CSV',
        selectors:['domain','level','unit_id','zone_id','reason','clipped_area_m2','disposition','boundary_asset','ghana_asset']});
      created.push(n);c3xCreatedPrefixes[c3xFolder(s.profile)+'/'+n]=true;
    });
    print('Boundary exception log tasks created; no units were dropped',created);
    c3xStatus.setValue(created.length+' exception log task(s) created; data exports remain blocked until resolved.');
  } catch(e){if(created.length){print('PARTIAL exception log tasks created',created);c3xStatus.setValue('PARTIAL: '+created.length+' log tasks created. Review Tasks: '+String((e&&e.message)||e));}else c3xFail(e);}
}
// ======================= 06. CONTROLS AND INITIALIZATION =======================
c3xControls.add(ui.Button({label:'Inspect selected-month preview',onClick:c3xPreview,style:{stretch:'horizontal'}}));
c3xLayers.add(ui.Label('Preview creates boundary, fixed-union, unresolved, accepted evidence and anomaly layers. Use the map Layers control for visibility.',{whiteSpace:'normal'}));
c3xLayers.add(ui.Button({label:'Refresh selected-month preview',onClick:c3xPreview,style:{stretch:'horizontal'}}));
c3xExports.add(ui.Button({label:'Inspect export plan (no tasks)',onClick:c3xInspectPlan,style:{stretch:'horizontal'}}));
c3xExports.add(ui.Button({label:'Create selected-month CSV task',onClick:c3xSelectedMonth,style:{stretch:'horizontal'}}));
c3xExports.add(ui.Button({label:'Create planned annual CSV tasks',onClick:c3xQueue,style:{stretch:'horizontal'}}));
c3xExports.add(ui.Button({label:'Create boundary exception log tasks (if blocked)',onClick:c3xExportBoundaryIssues,style:{stretch:'horizontal'}}));
c3xExports.add(ui.Label('Configure domain, geography and year mode in Controls. All ACZ tables are combined; district exports are separate per ACZ. Tasks are never started automatically. This session blocks repeated prefixes, but cannot detect previous Drive or task names. Full-period source preflight may be slow; bounded year batches are recommended.',{whiteSpace:'normal',fontSize:'11px'}));
c3xAbout.add(ui.Label('Fixed period unions, QA, evidence states, anomaly withholding, native grid, source admission and denominators are shared by both applications. A smaller export range does not change the union period.',{whiteSpace:'normal'}));
c3xAbout.add(ui.Label('QA checks identity and nonzero Ghana-clipped vector area; it does not establish geometry equivalence. Invalid IDs, assignments or zero-area geometries block data tasks; units are not silently dropped. A nonempty unit with no pixel centres remains NO_PIXEL_CENTRES.',{whiteSpace:'normal'}));
c3xAbout.add(ui.Label('Each analytical CSV contains the complete 69-field extended record. Blank withheld values are not zeros. Viewer/exporter agreement is not physical-fire accuracy validation.',{whiteSpace:'normal'}));
c3xTab('controls');ui.root.insert(0,c3xPanel);Map.setOptions('SATELLITE');
print('RP1 c3 consolidated exporter initialised. No checks or tasks run automatically.');
