/* =============================================================================
 RP1 — Ghana MODIS Viewer (c3)
 Google Earth Engine JavaScript / Code Editor

 PURPOSE
   Inspect the agreed burned-area method across Ghana and optionally focus on
   an agro-climatic zone (ACZ) or district. The viewer creates diagnostic maps,
   raster exports and a selected unit-month extended CSV. It uses Ghana as the
   opening map extent and does not create a national reporting-unit CSV row.

 STUDY PERIODS AND BURNED-AREA METHOD
   BA2001 uses the fixed 2001–2024 land-cover eligibility union; BA2012 uses
   the separately constructed 2012–2024 union. The primary numerator and union
   denominator use the selected fixed union. Exporting or viewing a single year
   does not shorten that union period. MCD64A1 Collection 6.1 BurnDate and QA
   provide monthly evidence; annual MCD12Q1 Collection 6.1 LC_Type1 and LW
   provide land-cover eligibility. The configured native MCD64A1 grid and
   unweighted pixel-centre reducer apply to burned-area summaries.

   A qualifying positive with shortened mapping remains accepted and is
   flagged separately. Missing or unsupported evidence contributes zero under
   the agreed analytical scenario, but is not proof of unburned land. A
   conflicting positive BurnDate within the known union can withhold primary
   unit-month output; unresolved eligibility and source/reduction failures
   follow their own guards. Evidence maps do not certify a reporting-unit row.
   Status, reason areas and other diagnostic columns explain the output.

 CONTEXT PRODUCTS
   MOD11A1 Collection 6.1 supplies monthly land surface temperature (LST).
   LST uses its own product QA and grid; it is not part of the burned-area
   denominator. LC_Type1 and LW can be exported as annual context on the BA
   grid. Collection-level LST image counts and a first-image projection do not
   establish complete daily or per-pixel support.

 INPUTS
   - Ghana, ACZ and district Earth Engine table assets in the C3 configuration.
   - MODIS/061/MCD64A1, MODIS/061/MCD12Q1 and MODIS/061/MOD11A1.
   - A Google Drive folder for exported products.

 OUTPUTS AND OPERATION
   1. Choose a domain, date and map scope. Select an ACZ or district for a
      reporting-unit row; Ghana is a map and raster scope only.
   2. Inspect the selected month and view the status and evidence layers.
   3. Use Exports to inspect product bundles and create requested tasks.
   4. Review and run intended tasks manually in the Earth Engine Tasks tab.
   5. Read the extended CSV status and diagnostics; a blank primary field is
      withheld or undefined, not an automatic zero.

   BA and LST yearly actions create one raster task per month. The standard
   yearly bundle adds an annual LC/LW context task. Fixed-union diagnostics and
   selected unit-month CSV tasks are separate. Raster bands use their documented
   names; the CSV uses the versioned 69-field extended schema.

 EDITING AND MAINTENANCE
   Set the three boundary asset paths and viewer Drive folder in C3 below. Keep
   the shared scientific core synchronized between the viewer and CSV exporter.
   Edit source fragments and rebuild both standalone scripts rather than
   modifying generated copies independently.
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
// VIEWER 01 — CONTROLS, STATE AND REPORTING SCOPE
// =============================================================================
// Shared scientific functions and configuration are generated above this section.
var appTitle='RP1 c3 | Ghana MODIS viewer';
var panel=ui.Panel({style:{width:'430px',padding:'8px'}});
panel.add(ui.Label(appTitle,{fontWeight:'bold',fontSize:'17px'}));
panel.add(ui.Label('Pixel layers are evidence; consult reporting-unit status for results.',{color:'#8b4d00',fontSize:'11px',whiteSpace:'normal'}));
var status=ui.Label('Ready. Select settings and inspect a month.',{whiteSpace:'normal',color:'#245672'});
panel.add(status);
var controlsPanel=ui.Panel(),layersPanel=ui.Panel(),exportsPanel=ui.Panel(),aboutPanel=ui.Panel();
var nav=ui.Panel({layout:ui.Panel.Layout.flow('horizontal')});
function c3Tab(which){
  controlsPanel.style().set('shown',which==='controls'); layersPanel.style().set('shown',which==='layers');
  exportsPanel.style().set('shown',which==='exports'); aboutPanel.style().set('shown',which==='about');
}
['controls','layers','exports','about'].forEach(function(name){nav.add(ui.Button({label:name.charAt(0).toUpperCase()+name.slice(1),onClick:function(){c3Tab(name);}}));});
panel.add(nav);panel.add(controlsPanel);panel.add(layersPanel);panel.add(exportsPanel);panel.add(aboutPanel);
var profileSelect=ui.Select({items:['BA2001','BA2012'],value:'BA2001'});
var levelSelect=ui.Select({items:['ghana','acz','district'],value:'ghana'});
var zoneSelect=ui.Select({items:['coastal_zone','forest_zone','guinea_savannah','sudan_savannah','transition_zone'],value:'forest_zone'});
var districtBox=ui.Textbox({placeholder:'Exact dist_id (required for district)',value:''});
var yearOptions=[];for(var yi=C3.observationStartYear;yi<=C3.observationEndYear;yi++)yearOptions.push(String(yi));
var monthOptions=[];for(var mi=1;mi<=12;mi++)monthOptions.push(String(mi));
var yearBox=ui.Select({items:yearOptions,value:String(C3.observationEndYear)}),monthBox=ui.Select({items:monthOptions,value:'1'});
var districtChoices=ui.Select({items:[],placeholder:'Load district list for this ACZ',onChange:function(label){
  if(label&&districtLookup[label])districtBox.setValue(districtLookup[label]);
}});
var districtLookup={},districtLoadGeneration=0;
function c3FocusWidgets(){
  var mode=levelSelect.getValue();zoneSelect.setDisabled(mode==='ghana');
  districtBox.setDisabled(mode!=='district');districtChoices.setDisabled(mode!=='district'||Object.keys(districtLookup).length===0);
}
function c3LoadDistricts(){
  var zone=zoneSelect.getValue(),generation=++districtLoadGeneration;
  status.setValue('Loading district names and IDs for '+zone+'...');
  var units=c3Units('district',zone,'');
  ee.Dictionary({ids:units.aggregate_array('unit_id'),names:units.aggregate_array('unit_name'),count:units.size()}).evaluate(function(obj,err){
    if(generation!==districtLoadGeneration||zone!==zoneSelect.getValue())return;
    districtLookup={};districtChoices.items().reset([]);districtChoices.setDisabled(true);
    if(err||!obj||!obj.count||!obj.ids||!obj.names||obj.ids.length!==obj.count||obj.names.length!==obj.count){
      status.setValue('District list unavailable or incomplete. Enter exact dist_id manually; inspect the asset.');return;
    }
    var labels=[];
    for(var i=0;i<obj.ids.length;i++){
      var id=String(obj.ids[i]||''),name=String(obj.names[i]||'');
      if(!id||!name){status.setValue('District list has an empty ID/name. Enter an exact dist_id manually.');return;}
      var label=name+' | '+id;if(districtLookup[label]){status.setValue('Duplicate district label/ID. Check the asset.');return;}
      districtLookup[label]=id;labels.push(label);
    }
    labels.sort();districtChoices.items().reset(labels);c3FocusWidgets();
    status.setValue('Loaded '+labels.length+' district names and IDs.');
  });
}
levelSelect.onChange(c3FocusWidgets);
zoneSelect.onChange(function(){districtLoadGeneration++;districtLookup={};districtChoices.items().reset([]);districtBox.setValue('');c3FocusWidgets();});
profileSelect.onChange(function(value){
  var window=c3ObservationWindow(c3Profile(value)),start=window.start,opts=[];
  for(var y=start;y<=window.end;y++)opts.push(String(y));
  var current=Number(yearBox.getValue());yearBox.items().reset(opts);
  yearBox.setValue(String(current>=start&&current<=window.end?current:start));
});
function addControl(label,widget){controlsPanel.add(ui.Label(label,{fontWeight:'bold',margin:'4px 0 1px 0'}));controlsPanel.add(widget);}
addControl('Fixed union domain: BA2001 (2001–2024) or BA2012 (2012–2024)',profileSelect);
addControl('Map / raster scope',levelSelect);addControl('Agro-climatic zone for ACZ or district focus',zoneSelect);
addControl('District ID for district focus',districtBox);addControl('District name and ID',districtChoices);
controlsPanel.add(ui.Button({label:'Load district names for selected ACZ',onClick:c3LoadDistricts,style:{stretch:'horizontal'}}));
addControl('Year',yearBox);addControl('Month, 1–12',monthBox);c3FocusWidgets();
controlsPanel.add(ui.Label('Ghana is the initial visual AOI. The union period is independent of the selected export year.',{fontSize:'11px',whiteSpace:'normal'}));
function c3Settings(){
  var profile=c3Profile(profileSelect.getValue()),date=c3ParseDate(profile,yearBox.getValue(),monthBox.getValue());
  var level=levelSelect.getValue(),zone=zoneSelect.getValue(),district=(districtBox.getValue()||'').trim(), units;
  if(level==='ghana') {
    /* A named feature serves only as a source-preflight footprint. No national CSV row is calculated. */
    units=ee.FeatureCollection([ee.Feature(ee.FeatureCollection(C3.ghanaAsset).geometry(),{unit_id:'GHA',unit_name:'Ghana'})]);
  } else {
    if(level==='district'&&!district) throw new Error('Enter an exact dist_id for district focus.');
    units=c3Units(level,zone,district);
  }
  return {profile:profile,date:date,level:level,zone:zone,district:district,units:units};
}
function c3DatesForYear(year){var out=[];for(var m=1;m<=12;m++)out.push({year:year,month:m});return out;}
function c3ScopeTag(s){
  if(s.level==='ghana')return 'GHA';
  var tag=s.zone;
  if(s.level==='district'){
    var id=s.district,hash=2166136261;
    for(var i=0;i<id.length;i++){var v=hash^id.charCodeAt(i);hash=(v+(v<<1)+(v<<4)+(v<<7)+(v<<8)+(v<<24))|0;}
    tag+='_'+id.replace(/[^A-Za-z0-9_-]/g,'_').slice(0,24)+'_'+(hash>>>0).toString(16);
  }
  return tag;
}
// =============================================================================
// VIEWER 02 — MAP LAYERS AND VISIBILITY
// =============================================================================
var previewLayers={},previewReady=false;
var c3CreatedRasterPrefixes={};
function c3WarnDuplicate(name){if(c3CreatedRasterPrefixes[name])print('WARNING: this session already created a task with prefix',name);}
function c3RememberRaster(name){c3CreatedRasterPrefixes[name]=true;}
var boundaryGroup=ui.Panel(),domainGroup=ui.Panel(),evidenceGroup=ui.Panel(),reasonGroup=ui.Panel();
var groupPanels={Boundaries:boundaryGroup,Domain:domainGroup,Evidence:evidenceGroup,Reasons:reasonGroup};
var layerGroup=ui.Select({items:['Boundaries','Domain','Evidence','Reasons'],value:'Boundaries',onChange:function(v){
  Object.keys(groupPanels).forEach(function(k){groupPanels[k].style().set('shown',k===v);});
}});
layersPanel.add(ui.Label('Layer group',{fontWeight:'bold'}));layersPanel.add(layerGroup);
layersPanel.add(boundaryGroup);layersPanel.add(domainGroup);layersPanel.add(evidenceGroup);layersPanel.add(reasonGroup);
Object.keys(groupPanels).forEach(function(k){groupPanels[k].style().set('shown',k==='Boundaries');});
function viewerToggle(key,label,initial){
  var target=(key==='ghana'||key==='acz'||key==='districts'||key==='selected')?boundaryGroup:
    (key==='lc'||key==='annual'||key==='union'||key==='excluded'||key==='unresolved')?domainGroup:
    (key==='short'||key==='special'||key==='anomaly')?reasonGroup:evidenceGroup;
  target.add(ui.Checkbox({label:label,value:initial,onChange:function(value){
    show[key]=value;if(previewReady&&previewLayers[key])previewLayers[key].setShown(value);
  }}));
  return initial;
}
var show={
  ghana:viewerToggle('ghana','Ghana boundary',true),
  acz:viewerToggle('acz','ACZ boundaries',false),
  districts:viewerToggle('districts','District boundaries',false),
  selected:viewerToggle('selected','Selected focus boundary',true),
  lc:viewerToggle('lc','Selected-year IGBP land cover (context)',false),
  annual:viewerToggle('annual','Selected-year eligible area',false),
  union:viewerToggle('union','Selected period fixed union',false),
  excluded:viewerToggle('excluded','Definitely excluded from union',false),
  unresolved:viewerToggle('unresolved','Unresolved union membership',true),
  accepted:viewerToggle('accepted','Accepted positive pixel evidence',true),
  raw:viewerToggle('raw','Raw positive BurnDate (context)',false),
  zero:viewerToggle('zero','Explicit qualifying zero evidence',false),
  unsupported:viewerToggle('unsupported','Unsupported evidence',false),
  bmissing:viewerToggle('bmissing','BurnDate masked with QA present',false),
  qmissing:viewerToggle('qmissing','QA unavailable',false),
  anomaly:viewerToggle('anomaly','Source-pixel anomaly in known union',true),
  short:viewerToggle('short','Shortened mapping reason',false),
  special:viewerToggle('special','Special-condition reason',false)
};
function c3AddLayer(key,obj,vis,name){
  Map.addLayer(obj,vis,name,show[key]);
  previewLayers[key]=Map.layers().get(Map.layers().length()-1);
}
function c3ShowMap(s,domain,e){
  var geom=s.units.geometry(),u=domain.eligible;Map.layers().reset();previewLayers={};
  c3AddLayer('lc',domain.annual[s.date.year].lc.clip(geom),{min:1,max:17,palette:['05450a','086a10','54a708','78d203','009900','c6b044','dcd159','dade48','fbff13','b6ff05','27ff87','c24f44','a5a5a5','ff6d4c','69fff8','f9ffa4','1c0dff']},'Annual IGBP (context)');
  c3AddLayer('annual',domain.annual[s.date.year].eligible.selfMask().clip(geom),{palette:['1a9850']},'Selected-year eligible land');
  c3AddLayer('union',u.selfMask().clip(geom),{palette:['ffd92f']},'Fixed union eligible');
  c3AddLayer('excluded',domain.excluded.selfMask().clip(geom),{palette:['909090']},'Definitely outside union');
  c3AddLayer('unresolved',domain.unresolved.selfMask().clip(geom),{palette:['d02fc0']},'Unresolved union');
  c3AddLayer('raw',e.raw.updateMask(e.raw.gt(0)).clip(geom),{min:1,max:366,palette:['ffd2a6','b45900']},'Raw BurnDate positive — context');
  c3AddLayer('zero',u.and(e.explicit_zero).selfMask().clip(geom),{palette:['79c879']},'Evidence: qualifying zero');
  c3AddLayer('unsupported',u.and(e.unsupported).selfMask().clip(geom),{palette:['886633']},'Evidence: unsupported');
  c3AddLayer('bmissing',u.and(e.burndate_missing).selfMask().clip(geom),{palette:['7138c7']},'Evidence: BurnDate masked');
  c3AddLayer('qmissing',u.and(e.qa_missing).selfMask().clip(geom),{palette:['219ebc']},'Evidence: QA unavailable');
  c3AddLayer('short',u.and(e.flag_shortened).selfMask().clip(geom),{palette:['ff9500']},'Reason: shortened mapping');
  c3AddLayer('special',u.and(e.flag_special).selfMask().clip(geom),{palette:['ffde80']},'Reason: special condition');
  c3AddLayer('accepted',u.and(e.accepted).selfMask().clip(geom),{palette:['d7191c']},'Accepted pixel evidence — consult unit status');
  c3AddLayer('anomaly',u.and(e.anomaly).selfMask().clip(geom),{palette:['00ffff']},'Anomalous positive — consult unit status');
  c3AddLayer('ghana',ee.Image().byte().paint(ee.FeatureCollection(C3.ghanaAsset),1,2),{palette:['ffffff']},'Ghana boundary');
  c3AddLayer('acz',ee.Image().byte().paint(ee.FeatureCollection(C3.zoneAsset),1,1).clip(geom),{palette:['111111']},'ACZ boundaries');
  c3AddLayer('districts',ee.Image().byte().paint(ee.FeatureCollection(C3.districtAsset),1,1).clip(geom),{palette:['888888']},'District boundaries');
  c3AddLayer('selected',ee.Image().byte().paint(s.units,1,2),{palette:['00ff00']},'Selected scope');
  previewReady=true;Map.centerObject(s.units,s.level==='district'?9:7);
}
// =============================================================================
// VIEWER 03 — BURNED-AREA RASTER EXPORTS
// =============================================================================
function c3State(domain,e){
  var u=domain.eligible;
  return ee.Image.constant(0).where(domain.unresolved,1)
    .where(u.and(e.qa_missing),2).where(u.and(e.burndate_missing),3)
    .where(u.and(e.unsupported),4).where(u.and(e.explicit_zero),5)
    .where(u.and(e.accepted),6).rename('c3_state');
}
function c3QueueBa(s,domain,date,sourceIndex){
  var e=c3Evidence(c3BaImage(sourceIndex)),geom=s.units.geometry(),u=domain.eligible;
  var raster=ee.Image.cat([
    u.rename('c3_union_eligible'),domain.unresolved.rename('c3_union_unresolved'),
    c3State(domain,e),u.and(e.accepted).rename('c3_accepted_pixel_evidence'),
    u.and(e.anomaly).rename('c3_source_pixel_anomaly'),
    u.and(e.accepted).and(e.flag_shortened.not()).rename('c3_full_period_only'),
    u.and(e.flag_shortened).rename('c3_reason_shortened'),
    u.and(e.flag_qa_missing).rename('c3_reason_qa_missing'),
    u.and(e.flag_burndate_masked).rename('c3_reason_burndate_masked'),
    u.and(e.flag_qa_nonland).rename('c3_reason_qa_nonland'),
    u.and(e.flag_qa_invalid).rename('c3_reason_qa_invalid'),
    u.and(e.flag_special).rename('c3_reason_special'),
    u.and(e.flag_positive_special).rename('c3_reason_positive_special'),
    u.and(e.flag_unexpected_burndate).rename('c3_reason_unexpected_burndate'),
    e.raw.rename('raw_BurnDate')
  ]).toFloat().clip(geom).unmask(-9999,false);
  var name='MCD64A1_061_Burn_c3_'+s.profile.id+'_'+c3ScopeTag(s)+'_'+date.year+'_'+c3Pad(date.month);
  c3WarnDuplicate(name);
  Export.image.toDrive({image:raster,description:name,folder:C3.driveFolder,fileNamePrefix:name,
    region:geom,crs:C3.crs,crsTransform:C3.transform,maxPixels:C3.maxPixels,
    fileFormat:'GeoTIFF',formatOptions:{noData:-9999}});
  c3RememberRaster(name);return name;
}
function c3QueueDomain(s,domain){
  var geom=s.units.geometry(),ann=domain.annual[s.date.year];
  var img=ee.Image.cat([domain.eligible.rename('c3_union_eligible'),
    domain.excluded.rename('c3_union_excluded'),domain.unresolved.rename('c3_union_unresolved'),
    ann.eligible.rename('c3_annual_eligible'),ann.unknown.rename('c3_annual_unknown')]).toFloat().clip(geom).unmask(-9999,false);
  var name='MCD12Q1_061_Union_c3_'+s.profile.id+'_'+c3ScopeTag(s)+'_'+s.date.year;
  c3WarnDuplicate(name);
  Export.image.toDrive({image:img,description:name,folder:C3.driveFolder,fileNamePrefix:name,
    region:geom,crs:C3.crs,crsTransform:C3.transform,maxPixels:C3.maxPixels,
    fileFormat:'GeoTIFF',formatOptions:{noData:-9999}});
  c3RememberRaster(name);return name;
}
// =============================================================================
// VIEWER 04 — SOURCE CHECKS, MAP ACTIONS AND SELECTED-MONTH CSV
// =============================================================================
function c3Do(action){
  var created=[];
  try{
    var s=c3Settings();
    if(action==='csv_month'&&s.level==='ghana')throw new Error('National reporting rows are not defined; select an ACZ or district for a preview CSV.');
    var yearly=action==='ba_year'||action==='ba_stack';
    var dates=yearly?c3DatesForYear(s.date.year):[s.date];
    status.setValue('Checking source inventory, identities and native-grid metadata...');
    var receipt=c3SourcePreflight(s.profile,dates,s.units,s.level);
    if(action==='inspect'){
      var domain=c3Domain(s.profile,receipt),ev=c3Evidence(c3BaImage(receipt.ba_indexes[0][0]));
      c3ShowMap(s,domain,ev);
      if(s.level!=='ghana')print('Selected c3 unit-month result — consult status',c3Rows(s.units,s.profile,[s.date],receipt));
      else print('Ghana visual scope only: no national reporting row. Select an ACZ or district to inspect a reporting row.');
      status.setValue('Source preflight admitted. Inspect evidence; pixel layers do not certify unit-month results.');
    } else if(action==='ba_month'||action==='ba_year'){
      var dom=c3Domain(s.profile,receipt);
      for(var i=0;i<dates.length;i++)created.push(c3QueueBa(s,dom,dates[i],receipt.ba_indexes[i][0]));
      status.setValue(dates.length+' BA raster task(s) created; inspect and run intended tasks manually.');
    } else if(action==='domain'){
      c3QueueDomain(s,c3Domain(s.profile,receipt));
      status.setValue('Union / annual eligibility raster task created; run manually.');
    } else if(action==='ba_stack'){
      var stackDomain=c3Domain(s.profile,receipt);Map.layers().reset();previewReady=false;
      Map.addLayer(ee.Image().byte().paint(s.units,1,2),{palette:['151515']},'Selected scope',true);
      for(var j=0;j<dates.length;j++){
        var d=dates[j],e=c3Evidence(c3BaImage(receipt.ba_indexes[j][0]));
        Map.addLayer(stackDomain.eligible.and(e.accepted).selfMask().clip(s.units.geometry()),
          {palette:['d7191c']},'Accepted pixel evidence '+d.year+'-'+c3Pad(d.month),j===s.date.month-1);
      }
      Map.centerObject(s.units,s.level==='district'?9:7);
      status.setValue('12 diagnostic monthly layers added. Selected month shown. These do not certify reporting rows.');
    } else if(action==='csv_month'){
      if(s.level==='ghana')throw new Error('National reporting rows are not defined; select an ACZ or district for a preview CSV.');
      var name='rp1_ba_viewer_inspection_c3_'+s.profile.id+'_'+s.level+'_'+c3ScopeTag(s)+'_'+s.date.year+c3Pad(s.date.month)+'_ext';
      Export.table.toDrive({collection:c3Rows(s.units,s.profile,[s.date],receipt),description:name,folder:C3.driveFolder,
        fileNamePrefix:name,fileFormat:'CSV',selectors:c3Selectors(s.profile,s.date.year)});
      status.setValue('One diagnostic preview CSV task created; run manually.');
    }
  }catch(e){var msg=String((e&&e.message)||e);status.setValue((created.length?'PARTIAL: '+created.length+' task(s) created before error. ':'BLOCKED: ')+msg);print('Viewer action blocked: '+msg,'action='+action,'created_prefixes',created);}
}
// =============================================================================
// VIEWER 05 — CONTROLS, EXPORT BUTTONS AND ABOUT PANEL
// =============================================================================
controlsPanel.add(ui.Button({label:'Inspect selected month',onClick:function(){c3Do('inspect');},style:{stretch:'horizontal'}}));
controlsPanel.add(ui.Button({label:'Reset map to Ghana',onClick:function(){levelSelect.setValue('ghana');Map.layers().reset();previewReady=false;previewLayers={};Map.addLayer(ee.Image().byte().paint(ee.FeatureCollection(C3.ghanaAsset),1,2),{palette:['ffffff']},'Ghana boundary',true);Map.centerObject(ee.FeatureCollection(C3.ghanaAsset),7);status.setValue('Ghana focus selected; inspect a month to refresh evidence layers.');},style:{stretch:'horizontal'}}));
controlsPanel.add(ui.Button({label:'Open Layers',onClick:function(){c3Tab('layers');}}));
controlsPanel.add(ui.Button({label:'Open Exports',onClick:function(){c3Tab('exports');}}));
layersPanel.add(ui.Button({label:'Add 12 monthly BA evidence layers',onClick:function(){c3Do('ba_stack');},style:{stretch:'horizontal'}}));
layersPanel.add(ui.Button({label:'Restore selected-month view',onClick:function(){c3Do('inspect');},style:{stretch:'horizontal'}}));
exportsPanel.add(ui.Label('BA bands: fixed union, unresolved, state codes 0–6 (including five evidence states), accepted, anomaly, reason masks and raw BurnDate. Tasks are not submitted automatically.',{whiteSpace:'normal',fontSize:'11px'}));
exportsPanel.add(ui.Button({label:'Create selected-month BA evidence raster (1)',onClick:function(){c3Do('ba_month');},style:{stretch:'horizontal'}}));
exportsPanel.add(ui.Button({label:'Create 12 selected-year monthly BA rasters',onClick:function(){c3Do('ba_year');},style:{stretch:'horizontal'}}));
exportsPanel.add(ui.Button({label:'Create union / annual eligibility raster (1)',onClick:function(){c3Do('domain');},style:{stretch:'horizontal'}}));
exportsPanel.add(ui.Button({label:'Create selected unit-month CSV (1)',onClick:function(){c3Do('csv_month');},style:{stretch:'horizontal'}}));
aboutPanel.add(ui.Label('BA2001 and BA2012 use separately constructed fixed period unions. Unknown monthly evidence contributes zero under the study scenario; this is not proof of unburned land. A qualifying positive with shortened mapping remains accepted.',{fontSize:'11px',whiteSpace:'normal'}));
aboutPanel.add(ui.Label('A positive source anomaly in the known union or unresolved union membership can withhold a unit-month result. Pixel map evidence and diagnostics are not a substitute for the CSV status. Source mismatch blocks output.',{fontSize:'11px',whiteSpace:'normal'}));

// =============================================================================
// VIEWER 06 — MOD11A1 MONTHLY LST AND ANNUAL LAND-COVER CONTEXT
// =============================================================================
// LST is independent of the burned-area domain and QA rules.
var lstBand = ui.Select({items:['LST_Day_C','LST_Night_C','Day_view_time_h','Night_view_time_h','n_day','n_night'],value:'LST_Day_C'});
layersPanel.add(ui.Label('LST layer (monthly MOD11A1)',{fontWeight:'bold'}));
layersPanel.add(lstBand);
function c3LstSource(date) {
  var w=c3Month(date.year,date.month);
  return ee.ImageCollection(C3.lstId).filterDate(w.start,w.end);
}
function c3MonthlyLst(date, geom) {
  var daily=c3LstSource(date).map(function(im) {
    im=ee.Image(im);
    var day=im.select('QC_Day').bitwiseAnd(3).eq(0), night=im.select('QC_Night').bitwiseAnd(3).eq(0);
    return im.select('LST_Day_1km').multiply(0.02).subtract(273.15).updateMask(day).rename('LST_Day_C')
      .addBands(im.select('LST_Night_1km').multiply(0.02).subtract(273.15).updateMask(night).rename('LST_Night_C'))
      .addBands(im.select('Day_view_time').multiply(0.1).updateMask(day).rename('Day_view_time_h'))
      .addBands(im.select('Night_view_time').multiply(0.1).updateMask(night).rename('Night_view_time_h'));
  });
  var means=daily.mean();
  var countDay=daily.select('LST_Day_C').count().rename('n_day');
  var countNight=daily.select('LST_Night_C').count().rename('n_night');
  return means.addBands(countDay).addBands(countNight).toFloat().clip(geom);
}
function c3LstAction(exportImage) {
  try {
    var s=c3Settings(), collection=c3LstSource(s.date);
    var counts=ee.Dictionary({units:s.units.size(),lst:collection.size()}).getInfo();
    if (!counts.units || !counts.lst) throw new Error('No selected boundary or no MOD11A1 images for this month.');
    var projection=ee.Image(collection.first()).select('LST_Day_1km').projection().getInfo();
    if (!projection || !projection.crs || !projection.transform || projection.transform.length!==6) {
      throw new Error('MOD11A1 native projection unavailable.');
    }
    var img=c3MonthlyLst(s.date,s.units.geometry());
    if (exportImage) {
      var name='MOD11A1_061_DN_c3_'+c3ScopeTag(s)+'_'+s.date.year+'_'+c3Pad(s.date.month);
      c3WarnDuplicate(name);
      Export.image.toDrive({image:img.unmask(-9999,false),description:name,folder:C3.driveFolder,
        fileNamePrefix:name,region:s.units.geometry(),crs:projection.crs,crsTransform:projection.transform,
        maxPixels:C3.maxPixels,fileFormat:'GeoTIFF',formatOptions:{noData:-9999}});
      c3RememberRaster(name);
      status.setValue('One monthly LST raster task created; start it manually.');
    } else {
      var band=lstBand.getValue(), vis={min:10,max:45,palette:['040274','2c7bb6','abd9e9','ffffbf','fdae61','d73027']};
      if (band.indexOf('view_time')>=0) vis={min:0,max:24,palette:['2c7bb6','ffffbf','d7191c']};
      if (band.indexOf('n_')===0) vis={min:0,max:31,palette:['ffffff','2c7bb6','08306b']};
      Map.addLayer(img.select(band),vis,'LST context: '+band,true);
      Map.centerObject(s.units,s.level==='district'?9:7);
      status.setValue('LST added. This layer uses its own product grid and QA.');
    }
    print('LST monthly source image count and first-image projection (not daily or pixel completeness)',counts.lst,projection);
  } catch(e) {status.setValue('BLOCKED: '+String(e.message||e));print('LST action blocked: '+String((e && e.message)||e));}
}
layersPanel.add(ui.Button({label:'Add selected LST layer',onClick:function(){c3LstAction(false);},style:{stretch:'horizontal'}}));
exportsPanel.add(ui.Button({label:'Create selected-month LST raster task',onClick:function(){c3LstAction(true);},style:{stretch:'horizontal'}}));
function c3LstYear(stackOnly) {
  var created=[];
  try {
    var s=c3Settings(), dates=c3DatesForYear(s.date.year), checks=[], i;
    for (i=0;i<dates.length;i++) checks.push(c3LstSource(dates[i]).size());
    var receipt=ee.Dictionary({units:s.units.size(),counts:ee.List(checks)}).getInfo();
    if (!receipt.units || receipt.counts.some(function(n){return n===0;})) {
      throw new Error('A boundary or one or more MOD11A1 months are unavailable; no LST tasks created.');
    }
    if (stackOnly) {
      var band=lstBand.getValue(), vis={min:10,max:45,palette:['040274','2c7bb6','abd9e9','ffffbf','fdae61','d73027']};
      if (band.indexOf('view_time')>=0) vis={min:0,max:24,palette:['2c7bb6','ffffbf','d7191c']};
      if (band.indexOf('n_')===0) vis={min:0,max:31,palette:['ffffff','2c7bb6','08306b']};
      for (i=0;i<dates.length;i++) Map.addLayer(c3MonthlyLst(dates[i],s.units.geometry()).select(band),vis,
        'LST '+band+' '+dates[i].year+'-'+c3Pad(dates[i].month),i===s.date.month-1);
      Map.centerObject(s.units,s.level==='district'?9:7);
      status.setValue('Twelve monthly LST layers added; the selected month is shown. Toggle months in Layers.');
      print('LST source counts',receipt.counts); return;
    }
    var projections=[];
    for (i=0;i<dates.length;i++) {
      var p=ee.Image(c3LstSource(dates[i]).first()).select('LST_Day_1km').projection().getInfo();
      if (!p || !p.crs || !p.transform || p.transform.length!==6) throw new Error('LST projection unavailable; no LST tasks created.');
      projections.push(p);
    }
    for (i=0;i<dates.length;i++) {
      var date=dates[i], name='MOD11A1_061_DN_c3_'+c3ScopeTag(s)+'_'+date.year+'_'+c3Pad(date.month);
      c3WarnDuplicate(name);
      Export.image.toDrive({image:c3MonthlyLst(date,s.units.geometry()).unmask(-9999,false),
        description:name,folder:C3.driveFolder,fileNamePrefix:name,region:s.units.geometry(),
        crs:projections[i].crs,crsTransform:projections[i].transform,maxPixels:C3.maxPixels,
        fileFormat:'GeoTIFF',formatOptions:{noData:-9999}});
      c3RememberRaster(name);created.push(name);
    }
    status.setValue('Twelve monthly LST tasks created; start only the tasks intended.');
    print('LST source counts',receipt.counts);
  } catch(e) {status.setValue((created.length?'PARTIAL: '+created.length+' task(s) created. ':'BLOCKED: ')+String(e.message||e));print('LST annual action blocked: '+String((e && e.message)||e),'created_prefixes',created);}
}
function c3LcExport() {
  try {
    var s=c3Settings(), col=c3LcCollection(s.date.year);
    var counts=ee.Dictionary({units:s.units.size(),lc:col.size(),indexes:col.aggregate_array('system:index')}).getInfo();
    if (!counts.units || counts.lc!==1 || !counts.indexes || counts.indexes.length!==1 || !c3SafeIndex(counts.indexes[0])) throw new Error('Boundary is empty or annual land-cover source is not uniquely identified.');
    var source=c3LcImage(counts.indexes[0]);
    print('Annual land-cover source projections',source.select('LC_Type1').projection(),source.select('LW').projection());
    var img=source.select(['LC_Type1','LW']).toFloat().clip(s.units.geometry()).unmask(-9999,false);
    var name='MCD12Q1_061_LCType1_LW_c3_'+c3ScopeTag(s)+'_'+s.date.year;
    c3WarnDuplicate(name);
    Export.image.toDrive({image:img,description:name,folder:C3.driveFolder,fileNamePrefix:name,
      region:s.units.geometry(),crs:C3.crs,crsTransform:C3.transform,maxPixels:C3.maxPixels,
      fileFormat:'GeoTIFF',formatOptions:{noData:-9999}});
    c3RememberRaster(name);
    status.setValue('Annual LC/LW context task created on the BA grid, using nearest-neighbour sampling.');
  } catch(e) {status.setValue('BLOCKED: '+String(e.message||e));print('LC action blocked: '+String((e && e.message)||e));}
}
exportsPanel.add(ui.Button({label:'Create selected-year LST tasks (12)',onClick:function(){c3LstYear(false);},style:{stretch:'horizontal'}}));
layersPanel.add(ui.Button({label:'Add yearly LST layer stack (12)',onClick:function(){c3LstYear(true);},style:{stretch:'horizontal'}}));
exportsPanel.add(ui.Button({label:'Create annual LC/LW context task',onClick:c3LcExport,style:{stretch:'horizontal'}}));

// =============================================================================
// VIEWER 07 — PRODUCT PLANS AND STANDARD EXPORT BUNDLES
// =============================================================================
function c3LstName(s,date){return 'MOD11A1_061_DN_c3_'+c3ScopeTag(s)+'_'+date.year+'_'+c3Pad(date.month);}
function c3LcName(s){return 'MCD12Q1_061_LCType1_LW_c3_'+c3ScopeTag(s)+'_'+s.date.year;}
function c3BaName(s,date){return 'MCD64A1_061_Burn_c3_'+s.profile.id+'_'+c3ScopeTag(s)+'_'+date.year+'_'+c3Pad(date.month);}
var c3LastViewPlan=null;
function c3ViewPlan(fullYear){
  try{
    var s=c3Settings(),dates=fullYear?c3DatesForYear(s.date.year):[s.date],names=[];
    for(var i=0;i<dates.length;i++){names.push(c3BaName(s,dates[i]));names.push(c3LstName(s,dates[i]));}
    if(fullYear)names.push(c3LcName(s));
    c3LastViewPlan=JSON.stringify({scope:s.level,scope_name:c3ScopeTag(s),domain:s.profile.id,folder:C3.driveFolder,prefixes:names});
    print('VIEWER PRODUCT PLAN — task descriptions and file prefixes; no source checks and no tasks created',
      {scope:s.level,scope_name:c3ScopeTag(s),domain:s.profile.id,folder:C3.driveFolder,count:names.length,prefixes:names,
       includes:fullYear?'12 monthly BA + 12 monthly LST + selected-year LC/LW':'one monthly BA + one monthly LST'});
    status.setValue('Plan: '+names.length+' tasks. Inspect exact names in Console. Source checks run on creation.');
  }catch(e){status.setValue('BLOCKED: '+String((e&&e.message)||e));}
}
function c3QueueLstKnown(s,date,projection){
  var name=c3LstName(s,date),geom=s.units.geometry();
  c3WarnDuplicate(name);
  Export.image.toDrive({image:c3MonthlyLst(date,geom).unmask(-9999,false),description:name,folder:C3.driveFolder,
    fileNamePrefix:name,region:geom,crs:projection.crs,crsTransform:projection.transform,maxPixels:C3.maxPixels,
    fileFormat:'GeoTIFF',formatOptions:{noData:-9999}});
  c3RememberRaster(name);return name;
}
function c3QueueLcKnown(s,receipt){
  var index=receipt.lc_indexes[s.date.year-s.profile.start],geom=s.units.geometry();
  var source=c3LcImage(index),name=c3LcName(s);
  var img=source.select(['LC_Type1','LW']).toFloat().clip(geom).unmask(-9999,false);
  c3WarnDuplicate(name);
  Export.image.toDrive({image:img,description:name,folder:C3.driveFolder,fileNamePrefix:name,region:geom,
    crs:C3.crs,crsTransform:C3.transform,maxPixels:C3.maxPixels,fileFormat:'GeoTIFF',formatOptions:{noData:-9999}});
  c3RememberRaster(name);return name;
}
function c3QueueStandard(fullYear){
  var created=[];
  try{
    var s=c3Settings(),dates=fullYear?c3DatesForYear(s.date.year):[s.date],counts=[],projections=[],i;
    var names=[];
    for(i=0;i<dates.length;i++){names.push(c3BaName(s,dates[i]));names.push(c3LstName(s,dates[i]));}
    if(fullYear)names.push(c3LcName(s));
    var signature=JSON.stringify({scope:s.level,scope_name:c3ScopeTag(s),domain:s.profile.id,folder:C3.driveFolder,prefixes:names});
    if(c3LastViewPlan!==signature)throw new Error('Inspect the current matching export plan before creating tasks.');
    status.setValue('Checking BA, land-cover and LST sources and projections before task creation...');
    var receipt=c3SourcePreflight(s.profile,dates,s.units,s.level);
    for(i=0;i<dates.length;i++)counts.push(c3LstSource(dates[i]).size());
    var n=ee.List(counts).getInfo();
    if(!n||n.length!==dates.length||n.some(function(v){return !v;}))throw new Error('One or more LST months are missing.');
    for(i=0;i<dates.length;i++){
      var p=ee.Image(c3LstSource(dates[i]).first()).select('LST_Day_1km').projection().getInfo();
      if(!p||!p.crs||!p.transform||p.transform.length!==6)throw new Error('An LST source projection is unavailable.');
      projections.push(p);
    }
    var domain=c3Domain(s.profile,receipt);
    for(i=0;i<dates.length;i++){created.push(c3QueueBa(s,domain,dates[i],receipt.ba_indexes[i][0]));created.push(c3QueueLstKnown(s,dates[i],projections[i]));}
    if(fullYear)created.push(c3QueueLcKnown(s,receipt));
    status.setValue((dates.length*2+(fullYear?1:0))+' tasks created; review and run them manually.');
    print('Standard product batch created',{count:dates.length*2+(fullYear?1:0),lst_monthly_source_image_counts:n,domain:s.profile.id,scope:c3ScopeTag(s)});
  }catch(e){
    var msg=String((e&&e.message)||e);
    status.setValue((created.length?'PARTIAL: '+created.length+' task(s) created; inspect Tasks. ':'BLOCKED: ')+msg);
    print('Standard product batch blocked',msg,'created_prefixes',created);
  }
}
exportsPanel.add(ui.Label('Standard bundles contain BA evidence and LST; the selected-year bundle also includes LC/LW. Domain diagnostics and the selected-month CSV are separate.',{fontSize:'11px',whiteSpace:'normal'}));
exportsPanel.add(ui.Button({label:'Inspect monthly BA + LST plan (2)',onClick:function(){c3ViewPlan(false);},style:{stretch:'horizontal'}}));
exportsPanel.add(ui.Button({label:'Create monthly BA + LST tasks (2)',onClick:function(){c3QueueStandard(false);},style:{stretch:'horizontal'}}));
exportsPanel.add(ui.Button({label:'Inspect annual standard-product plan (25)',onClick:function(){c3ViewPlan(true);},style:{stretch:'horizontal'}}));
exportsPanel.add(ui.Button({label:'Create annual standard-product tasks (25)',onClick:function(){c3QueueStandard(true);},style:{stretch:'horizontal'}}));
// =============================================================================
// VIEWER 08 — LEGEND AND INITIALIZATION
// =============================================================================
var legend=ui.Panel({style:{position:'top-right',width:'250px',padding:'8px'}});
legend.add(ui.Label('RP1 c3 legend',{fontWeight:'bold',fontSize:'13px'}));
legend.add(ui.Label('Red: accepted evidence | Cyan: anomaly | Magenta: unresolved union',{fontSize:'10px',whiteSpace:'normal'}));
legend.add(ui.Label('Purple: masked BurnDate | Blue: QA unavailable | Orange: shortened',{fontSize:'10px',whiteSpace:'normal'}));
legend.add(ui.Label('LST temperature: blue to red, 10–45 °C; other LST bands use their own scale.',{fontSize:'10px',whiteSpace:'normal'}));
legend.add(ui.Label('Evidence states are exclusive; reasons can overlap. Maps do not certify unit results.',{fontSize:'10px',whiteSpace:'normal'}));
var classLegend=ui.Panel();classLegend.style().set('shown',false);
var classLabels=['1 Evergreen Needleleaf Forest','2 Evergreen Broadleaf Forest','3 Deciduous Needleleaf Forest',
 '4 Deciduous Broadleaf Forest','5 Mixed Forest','6 Closed Shrublands','7 Open Shrublands',
 '8 Woody Savannas','9 Savannas','10 Grasslands','11 Permanent Wetlands','12 Croplands',
 '13 Urban and Built-up','14 Cropland/Natural Vegetation Mosaic','15 Snow and Ice','16 Barren','17 Water Bodies'];
var classColors=['05450a','086a10','54a708','78d203','009900','c6b044','dcd159','dade48','fbff13',
 'b6ff05','27ff87','c24f44','a5a5a5','ff6d4c','69fff8','f9ffa4','1c0dff'];
classLabels.forEach(function(label,i){classLegend.add(ui.Panel([
 ui.Label('',{backgroundColor:'#'+classColors[i],padding:'6px',margin:'1px 5px 1px 0'}),
 ui.Label(label,{fontSize:'10px',margin:'0'})],ui.Panel.Layout.flow('horizontal')));});
legend.add(ui.Checkbox({label:'Show 17 land-cover classes',value:false,onChange:function(v){classLegend.style().set('shown',v);}}));
legend.add(classLegend);
Map.add(legend);
layersPanel.add(ui.Checkbox({label:'Show map legend',value:true,onChange:function(v){legend.style().set('shown',v);}}));
c3Tab('controls');ui.root.insert(0,panel);Map.setOptions('SATELLITE');
Map.centerObject(ee.FeatureCollection(C3.ghanaAsset),7);
print(appTitle+' initialised. Ghana map focus. No source checks or export tasks run automatically.');
