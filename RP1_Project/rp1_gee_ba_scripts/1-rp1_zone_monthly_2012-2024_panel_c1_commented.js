// =============================================================================
// RP1 — Canonical ACZ Monthly Burned-Area Panel (c1 clean baseline)
// Google Earth Engine (JavaScript API)
//
// OVERVIEW
// --------
// This script is the first clean, analysis-ready ACZ extractor for the RP1
// MODIS burned-area workflow in Ghana. It produces a tidy, publication-ready
// MONTHLY burned-area panel for exactly ONE canonical Stage 1 Agro-Climatic
// Zone (ACZ). Internally, the analytical backbone still spans the overlap-era
// window January 2012 through December 2024 (START inclusive; END exclusive)
// so the fixed UNION denominator and year-specific annual denominators remain
// unchanged. The dedicated RP1 export family is then clipped to January 2012
// through December 2024 so downstream BA/AF merger-ready panels share one
// aligned monthly window.
//
// The burned-area numerator is derived from MODIS MCD64A1 Collection 6.1
// BurnDate and is defined per month as the pixel-wise OR across all MCD64A1
// images overlapping that month (burned = BurnDate > 0 in any overlapping
// month image).
//
// Burned area (ba_km2) is computed as the summed per-pixel surface area (km²)
// of burned pixels within the selected ACZ after:
//   (i) enforcing a LAND-ONLY AOI (canonical ACZ intersected with the canonical
//       Ghana land-only boundary),
//   (ii) applying the frozen c1 permanent-water exclusion, and
//   (iii) restricting numerator pixels to a stable burnable-land denominator.
//
// The c1 baseline is fully MODIS-based. It uses MCD12Q1 only for denominator
// support and excludes pixels where:
//   • LW != 2, or
//   • LC_Type1 == 17
// i.e. the baseline keep rule is:
//   • LW == 2 AND LC_Type1 != 17
//
// In addition to the fixed UNION denominator used for numerator masking and the
// primary burned fraction, the script also computes a year-specific ANNUAL
// denominator table for 2012–2024 and carries the relevant annual fields onto
// monthly rows. Explicit denominator QA, drift, provenance, and identity fields
// are exported to support defensibility and reproducibility.
//
// WHAT MAKES c1 THE CLEAN BASELINE
// --------------------------------
// This script intentionally freezes the analytical method by combining:
//   • the stricter analytical / identifier backbone of the v3 line; and
//   • the fixed LW_OR_LC17 permanent-water union chosen after the v4
//     sensitivity review.
//
// The analytical method is fixed in this script. It does NOT expose run-time
// mask switching. Exploratory mask comparison belongs in the dedicated viewer
// script.
//
// CRITICAL STANDARDISATION (c1 ANALYTICAL CONTRACT)
// ------------------------------------------------
// • SINGLE ANALYSIS GRID (MODIS-native):
//   ALL area computations (numerator + denominators) and ALL pixel counts are
//   executed on the MODIS MCD64A1 BurnDate grid:
//     – IMPACT_PROJ = MCD64A1 BurnDate projection
//     – PIXEL_AREA_KM2_IMPACT = pixelArea() reprojected to IMPACT_PROJ and
//       converted to km²
//   This prevents scale / CRS drift and keeps results directly comparable.
//
// • TRUE-MASK SEMANTICS:
//   Every mask passed to updateMask(...) is a TRUE MASK (self-masked), so
//   zero-valued pixels are excluded cleanly and cannot leak into reductions.
//
// • FIXED c1 BASELINE WATER RULE:
//   Exclude pixel if (LW != 2) OR (LC_Type1 == 17)
//   Keep pixel only if (LW == 2) AND (LC_Type1 != 17)
//
// • EXACT-YEAR DENOMINATOR SUPPORT:
//   The script requires exact annual MCD12Q1 support for each denominator year
//   2012–2024. Nearest-year fallback is not allowed anywhere in this script.
//
// • EXPLICIT NUMERATOR MASK ORDER (export definition):
//     (1) monthly burned-any mask (OR across overlapping images),
//     (2) fixed union burnable denominator support under the frozen c1 rule.
//   The annual excluded mask and annual burnable support are still computed and
//   exposed for QA / interpretation, but the primary numerator is masked by the
//   fixed UNION denominator.
//
// WHAT THIS SCRIPT DOES (STEP-BY-STEP)
// ------------------------------------
// 1) INPUT AOI (ONE CANONICAL ACZ)
//    • Reads a canonical Stage 1 ACZ FeatureCollection, by default from the
//      combined ACZ asset and filtered to one canonical zone_id.
//    • The AOI must resolve to exactly one canonical Stage 1 ACZ record with:
//        – one zone_id
//        – one zone_name
//        – one zone_code
//    • Any unresolved or multiply-resolved canonical identity is treated as a
//      hard failure.
//    • For the merger-ready RP1 export contract, the canonical ACZ fields are
//      remapped into the generic Stage 1 identity block so exported headers do
//      not hard-code ACZ-specific names.
//
// 2) GEOMETRY HYGIENE + LAND-ONLY ENFORCEMENT
//    • Repairs the AOI geometry using buffer(0, 1) style cleaning.
//    • Intersects the AOI with the canonical Ghana land-only boundary so all
//      reductions are performed on land-only geometry.
//    • Computes AOI diagnostics including:
//        – raw area,
//        – land-only area,
//        – outside-land area / fraction,
//        – outside-land warning flag.
//
// 3) STABLE UNIT IDENTIFIERS (ACZ; LOCKED OUTPUT CONTRACT)
//    • Locks the exported identifiers to the canonical Stage 1 ACZ fields,
//      remapped into the generic Stage 1-aligned RP1 export schema:
//        – level        = configured zone-level label ("acz" in this project)
//        – unit_id      = canonical zone_id
//        – unit_code    = canonical zone_code
//        – unit_name    = canonical zone_name
//        – parent_*     = blank for all zonal rows
//    • Legacy fields may be used only as compatibility inputs for canonical
//      resolution; unresolved identity is not permitted.
//
// 4) PROJECTION / GRID ALIGNMENT
//    • Reads the native projection of MCD64A1 BurnDate.
//    • Defines a MODIS-aligned pixel-area image and uses it as the single
//      source of truth for all numerator and denominator area computations.
//    • All reductions specify the MODIS CRS and use a consistent target scale.
//
// 5) LAND-COVER YEAR SUPPORT
//    • Builds a list of distinct available years in MCD12Q1.
//    • Requires exact annual support for every denominator year from 2012 to
//      2024 inclusive.
//    • If any required denominator year is missing, the script fails rather
//      than silently substituting another year.
//
// 6) BASELINE EXCLUDED MASK, ANNUAL KEEP MASK, AND BURNABLE DENOMINATORS
//    Burnable land is defined using MCD12Q1 LC_Type1 classes in LC_INCLUDE:
//      forests (1–5), shrublands (6–7), woody savannas / savannas (8–9),
//      grasslands (10), croplands (12), and cropland / natural mosaic (14).
//
//    6a) Annual excluded mask
//      • For each year, pixels are excluded when:
//          – LW != 2, or
//          – LC_Type1 == 17
//      • This is the frozen c1 permanent-water / non-land exclusion rule.
//
//    6b) Annual keep mask
//      • For each year, the baseline keep mask is the complement:
//          – LW == 2 AND LC_Type1 != 17
//
//    6c) Annual burnable denominator
//      • For each year 2012–2024, annual burnable support is:
//          – LC_Type1 in LC_INCLUDE
//          – AND LW == 2
//          – AND LC_Type1 != 17
//      • Annual burnable area and annual burnable pixel count are computed and
//        stored in an annual denominator table.
//
//    6d) Fixed UNION denominator
//      • The annual burnable masks for 2012–2024 are combined by pixel-wise OR
//        to form one fixed UNION denominator.
//      • This UNION denominator is used for numerator masking and the primary
//        burned fraction throughout the monthly panel.
//
// 7) ZERO-DENOMINATOR FLAGS (EXPLICIT; NOT DROPPED)
//    • The selected ACZ can have zero burnable denominator under the frozen
//      burnable definition.
//    • The script exports explicit flags rather than silently dropping the unit:
//        – zero_union_den_flag
//        – zero_annual_den_flag
//    • Burned fractions are set to null when the relevant denominator is <= 0.
//
// 8) QA AUDITS (GRID-CONSISTENT DRIFT CHECKS)
//    • UNION denominator audit:
//        – compares the reported UNION area from updateMask(...) against an
//          independent algebraic path using mask01 * pixelArea on the same
//          MODIS grid,
//        – flags drift if the difference exceeds the configured absolute /
//          relative tolerance rule.
//    • ANNUAL denominator audit:
//        – applies the same two-path check to each annual denominator year.
//    • The row-level field denom_any_drift_flag carries the OR of union and
//      annual drift conditions.
//
// 9) MONTHLY BURNED-AREA NUMERATOR (2012–2024)
//    • Iterates over all calendar months from START (inclusive) to END
//      (exclusive), yielding one internal analytical row per month for the
//      selected ACZ.
//    • For each month:
//        – filters MCD64A1 to the month window,
//        – defines burned pixels as BurnDate > 0 in ANY overlapping image,
//        – restricts the numerator to the fixed UNION denominator,
//        – computes ba_km2, burned_pixel_count, ba_any,
//        – computes burned_frac_union and burned_frac_annual,
//        – attaches year-specific annual denominator and QA fields.
//    • Also computes a national monthly Ghana burned-area reference and flags
//      months where local ba_km2 == 0 but national BA > 0.
//
// 10) LIGHT QA PREVIEW (MAP UI)
//    • Provides a fixed-method QA interface, not an exploratory method viewer.
//    • Includes preview controls for:
//        – year,
//        – month,
//        – layer visibility.
//    • Displays, for the selected month / year:
//        – ACZ boundary,
//        – LC_Type1 preview,
//        – excluded mask,
//        – UNION burnable denominator,
//        – selected-year annual burnable denominator,
//        – monthly burned-area mask,
//        – monthly BurnDate max.
//    • Includes a top-right legend with LC_Type1 class labels and a concise
//      preview summary panel.
//
// 11) BUTTON-TRIGGERED CSV EXPORTS
//    • Export panel queues Google Drive CSV tasks rather than auto-scheduling
//      them on script load.
//    • Two export bundles are supported under the same frozen c1 method:
//        – current canonical ACZ export bundle,
//        – one combined all-zones export bundle.
//    • Both export bundles are clipped to the dedicated RP1 merger-ready
//      window 201201 through 202412.
//    • Each bundle writes:
//        – a lean analytical CSV,
//        – an ext CSV carrying diagnostics, provenance, and audit fields.
//
// INPUT DATASETS
// --------------
// • Burned-area numerator:  MODIS/061/MCD64A1 — BurnDate
// • Burnable denominator:   MODIS/061/MCD12Q1 — LC_Type1 + LW
// • Ghana land-only mask:   Canonical Ghana land-only FeatureCollection (asset)
// • Canonical ACZ source:   Stage 1 ACZ FeatureCollection(s)
//
// HOW TO USE
// ----------
// 1) Set or confirm the canonical Stage 1 ACZ source assets.
// 2) Set DEFAULT_ZONE_ID to the desired canonical zone_id.
// 3) Set GHANA_LAND_FC to the canonical Ghana land-only asset.
// 4) Confirm START / END (END is exclusive; END = 2025-01-01 covers Dec 2024).
// 5) Set EXPORT_FOLDER and FILE_PREFIX; toggle ENABLE_EXPORTS if needed.
// 6) Run the script.
// 7) Use the Controls tab for fixed-method QA preview.
// 8) Use the Exports tab to queue either:
//      – current-zone analytical + ext CSVs, or
//      – one combined all-zones analytical + ext CSV bundle.
// 9) Run the queued tasks from the Tasks tab.
//
// CONVENTIONS / OUTPUTS
// ---------------------
// • Areas are computed from a MODIS-aligned pixel-area image and reported in km².
// • Raster reductions are executed on the MODIS BA grid with explicit MODIS CRS.
// • The numerator uses the fixed UNION burnable denominator.
// • Annual denominator fields are retained for robustness / interpretation.
// • The script exports two method-stable CSV products:
//      – rp1_ba_*.csv     = lean merger-ready analytical base export,
//      – rp1_ba_*_ext.csv = base columns plus diagnostics / provenance.
// • Exported RP1 rows are clipped to 2012-01 through 2024-12, while the
//   internal analytical backbone and denominator support still span 2012-01
//   through 2024-12.
// • Invariant method metadata such as script release and mask labels are kept
//   in the ext product rather than the lean merger-ready base contract.
// =============================================================================


// ============================= USER CONFIG ===================================

// Preferred Stage 1 canonical ACZ source. The default AOI below filters this
// combined source to one canonical zone.
var STAGE1_ZONES_COMBINED = ee.FeatureCollection('projects/afd-data-cube-project/assets/RP1_Project/acz');

// Optional single-zone Stage 1 split assets kept as explicit alternates.
var STAGE1_ZONE_CZ = ee.FeatureCollection('projects/afd-data-cube-project/assets/RP1_Project/acz__zone_coastal_zone');
var STAGE1_ZONE_FZ = ee.FeatureCollection('projects/afd-data-cube-project/assets/RP1_Project/acz__zone_forest_zone');
var STAGE1_ZONE_GS = ee.FeatureCollection('projects/afd-data-cube-project/assets/RP1_Project/acz__zone_guinea_savannah');
var STAGE1_ZONE_SS = ee.FeatureCollection('projects/afd-data-cube-project/assets/RP1_Project/acz__zone_sudan_savannah');
var STAGE1_ZONE_TZ = ee.FeatureCollection('projects/afd-data-cube-project/assets/RP1_Project/acz__zone_transition_zone');

// Canonical Ghana land-only boundary.
var GHANA_LAND_FC = ee.FeatureCollection('projects/afd-data-cube-project/assets/RP1_Project/gha_admin0');

// Overlap-era study window. START inclusive; END exclusive.
var START = '2012-01-01';
var END   = '2025-01-01';
var DENOM_START_YEAR = 2012;
var DENOM_END_YEAR   = 2024;

// Default AOI selection from the combined canonical ACZ asset.
var DEFAULT_ZONE_ID = 'transition_zone';
var AOI_FC = STAGE1_ZONES_COMBINED.filter(ee.Filter.eq('zone_id', DEFAULT_ZONE_ID));

// Export settings.
var EXPORT_FOLDER  = 'RP1_Project_MODIS_BA_c1_2012';
var FILE_PREFIX    = 'rp1_ba_acz_monthly_c1';
var ENABLE_EXPORTS = true;

// Provenance labels.
var SRC_MODIS_VERSION = 'MCD64A1 v6.1';

var SRC_LC_VERSION    = 'MCD12Q1 v6.1';
var LEVEL_VALUE       = 'acz';

// Dedicated RP1 export-family contract controls. The analytical backbone still
// runs across the full overlap-era window, but the exported merger-ready RP1
// rows are clipped to the BA/AF shared monthly window below.
var RP1_SCHEMA_VERSION = 'rp1_ba_monthly_stage1_generic_v1';
var RP1_EXPORT_START_YYYYMM = 201201;
var RP1_EXPORT_END_YYYYMM   = 202412;
var RP1_EXPORT_START_LABEL  = '2012-01';
var RP1_EXPORT_END_LABEL    = '2024-12';

// Frozen c1 method / provenance labels.
var SCRIPT_RELEASE = 'c1';
var SCRIPT_LINEAGE = 'v3_strict_backbone_plus_fixed_v4_LW_OR_LC17_baseline';
var BA_MASK_MODE = 'LW_OR_LC17';
var BA_MASK_SHORT_CODE = 'LW_OR_LC17';
var BA_MASK_LAYER_LABEL = 'LW != 2 OR LC_Type1 == 17';
var BA_MASK_KEEP_SUMMARY = 'Keep pixels where LW == 2 and LC_Type1 != 17';
var BA_MASK_EXCLUDED_SUMMARY = 'Exclude pixels where LW != 2 or LC_Type1 == 17';

// Light preview defaults for the fixed-method QA panel.
var PREVIEW_YEAR = 2024;
var PREVIEW_MONTH = 1;
var MAP_CENTER_ZOOM = 7;


// =========================== DATASETS & BANDS ================================

var IMPACT_PRODUCT_ID = 'MODIS/061/MCD64A1';
var DENOM_PRODUCT_ID  = 'MODIS/061/MCD12Q1';

var IMPACT_BAND_BURNDATE     = 'BurnDate';
var IMPACT_BANDS_RECOGNIZED  = ee.List(['BurnDate', 'QA', 'FirstDay', 'LastDay']);
var DENOM_BAND_LC_TYPE1      = 'LC_Type1';
var DENOM_BAND_LW            = 'LW';

var MCD64A1 = ee.ImageCollection(IMPACT_PRODUCT_ID).select(IMPACT_BAND_BURNDATE);
var MCD12Q1 = ee.ImageCollection(DENOM_PRODUCT_ID).select([DENOM_BAND_LC_TYPE1, DENOM_BAND_LW]);


// ============================== CONSTANTS ====================================

// Burnable MODIS LC_Type1 classes (IGBP scheme).
var LC_INCLUDE = ee.List([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14]);

// Drift tolerance for denominator self-audits.
var DENOM_DRIFT_TOL_ABS_KM2  = 1;
var DENOM_DRIFT_TOL_REL_FRAC = 0.001;

// Reduction parameters.
var SCALE_BA   = 500;
var MAX_PIXELS = 1e13;

var TILE_SCALE = 4;

// Light preview / map styling constants. These are intentionally modest: the
// analytical method is fixed, so the UI exists only for verification rather
// than exploratory method switching.
var BOUNDARY_WIDTH = 2;
var BOUNDARY_OPACITY = 1.00;
var EXCLUDED_OPACITY = 0.55;
var UNION_OPACITY = 0.45;
var ANNUAL_OPACITY = 0.45;
var LC_OPACITY = 0.80;
var BA_OPACITY = 1.00;
var EXCLUDED_VIS = {palette: ['2b83ba']};
var UNION_VIS = {palette: ['ffd92f']};
var ANNUAL_BURNABLE_VIS = {palette: ['1a9850']};
var BURNMASK_VIS = {palette: ['000000']};
var BURNDATE_VIS = {min: 1, max: 366, palette: ['f2f2f2', '000000']};
var ZONE_BOUNDARY_VIS = {palette: ['ff0000']};
var IGBP = [
  {value:  1, color: '05450a', name: 'Evergreen Needleleaf Forests'},
  {value:  2, color: '086a10', name: 'Evergreen Broadleaf Forests'},
  {value:  3, color: '54a708', name: 'Deciduous Needleleaf Forests'},
  {value:  4, color: '78d203', name: 'Deciduous Broadleaf Forests'},
  {value:  5, color: '009900', name: 'Mixed Forests'},
  {value:  6, color: 'c6b044', name: 'Closed Shrublands'},
  {value:  7, color: 'dcd159', name: 'Open Shrublands'},
  {value:  8, color: 'dade48', name: 'Woody Savannas'},
  {value:  9, color: 'fbff13', name: 'Savannas'},
  {value: 10, color: 'b6ff05', name: 'Grasslands'},
  {value: 11, color: '27ff87', name: 'Permanent Wetlands'},
  {value: 12, color: 'c24f44', name: 'Croplands'},
  {value: 13, color: 'a5a5a5', name: 'Urban and Built-up Lands'},
  {value: 14, color: 'ff6d4c', name: 'Cropland/Natural Vegetation Mosaics'},
  {value: 15, color: '69fff8', name: 'Permanent Snow and Ice'},
  {value: 16, color: 'f9ffa4', name: 'Barren'},
  {value: 17, color: '1c0dff', name: 'Water Bodies'}
];
var LC_VIS = {min: 1, max: 17, palette: IGBP.map(function(d) { return d.color; })};

// QA thresholds.

var SMALL_DEN_THRESHOLD_KM2 = 50;
var OUTSIDE_LAND_WARN_FRAC  = 1e-4;

// Overlap-era flag month derives from START.
var PARTIAL_VIIRS_OVERLAP_YYYYMM = Number(START.slice(0, 4) + START.slice(5, 7));

// Run stamps for traceability.
var NOW_JS = new Date();
var RUN_STAMP_STR = NOW_JS.toISOString().replace(/[-:]/g, '').replace(/\..*/, 'Z');
var CREATED_ISO_STR = NOW_JS.toISOString();
var RUN_STAMP   = ee.String(RUN_STAMP_STR);
var CREATED_ISO = ee.String(CREATED_ISO_STR);
var RUN_DATE_ISO = CREATED_ISO;

var REDUCER_TYPE      = 'sum';
var REDUCER_WEIGHTING = 'unweighted';
var DENOM_EXACT_YEAR_REQUIRED_FLAG = 1;
var DENOM_UNION_ROLE  = 'primary_fixed_union_exposure';
var DENOM_ANNUAL_ROLE = 'secondary_year_specific_exposure';


// ============================ TEXTUAL METADATA ===============================

// -----------------------------------------------------------------------------
// Small formatting helper used anywhere month numbers need to be rendered as
// two-digit strings (e.g. 1 -> "01"). This is used for filenames, preview
// labels, and date-window text.
// -----------------------------------------------------------------------------
function pad2(n) { return (n < 10 ? '0' : '') + n; }

// -----------------------------------------------------------------------------
// Converts an END-exclusive YYYY-MM-DD string into the final included
// YYYY-MM label. Example: END=2025-01-01 becomes 2024-12.
// This keeps human-readable labels aligned with the analytical window.
// -----------------------------------------------------------------------------
function monthBeforeExclusiveEnd(endStr) {
  var y = Number(endStr.slice(0, 4));
  var m = Number(endStr.slice(5, 7));
  m = m - 1;
  if (m === 0) {
    y = y - 1;
    m = 12;
  }
  return String(y) + '-' + pad2(m);
}


var STUDY_WINDOW_TEXT = START.slice(0, 7) + ' to ' + monthBeforeExclusiveEnd(END);
var RP1_EXPORT_WINDOW_TEXT = RP1_EXPORT_START_LABEL + ' to ' + RP1_EXPORT_END_LABEL;
var DENOM_YEAR_RANGE_TEXT = String(DENOM_START_YEAR) + ' to ' + String(DENOM_END_YEAR);
var LC_INCLUDE_TEXT = LC_INCLUDE.getInfo().join(', ');

var DENOMINATOR_DEFINITION = ee.String(
  'Burnable UNION denominator: OR across annual burnable masks for ' + DENOM_YEAR_RANGE_TEXT +
  ', where annual burnable = (LC_Type1 in [' + LC_INCLUDE_TEXT + ']) AND (' + BA_MASK_KEEP_SUMMARY + ').'
);

var ANNUAL_DENOMINATOR_DEFINITION = ee.String(
  'Burnable ANNUAL denominator: for each month, use the exact matching MCD12Q1 year; annual burnable = ' +
  '(LC_Type1 in [' + LC_INCLUDE_TEXT + ']) AND (' + BA_MASK_KEEP_SUMMARY + '). No nearest-year fallback is allowed.'
);

var ANNUAL_LAND_DEFINITION = ee.String(
  'Annual baseline keep-mask support: exact-year MCD12Q1 pixels where ' + BA_MASK_KEEP_SUMMARY + '.'
);

var MONTHLY_BA_DEFINITION = ee.String(
  'Monthly burned pixels: for each month, burned = BurnDate > 0 in ANY MCD64A1 image overlapping the month ' +
  '(pixel-wise OR via max over per-image burned masks), then restricted to the fixed union burnable denominator.'
);

var WATER_MASK_DEFINITION = ee.String(
  'Frozen c1 BA mask mode = ' + BA_MASK_MODE + '; ' + BA_MASK_EXCLUDED_SUMMARY + '.'
);

var DATE_WINDOW_METHOD_NOTE = ee.String(
  'Analytical backbone window: ' + STUDY_WINDOW_TEXT +
  ' (START inclusive, END exclusive). RP1 export window: ' + RP1_EXPORT_WINDOW_TEXT +
  '. Denominator year range: ' + DENOM_YEAR_RANGE_TEXT + '.'
);



// =========================== CLIENT-SIDE VALIDATION ==========================

// -----------------------------------------------------------------------------
// Client-side sanity check for required FeatureCollection assets.
// Forces an early, readable failure if an asset path is invalid or empty
// before the heavier EE computations are constructed.
// -----------------------------------------------------------------------------
function validateFeatureCollectionAsset(name, fc) {
  try {
    var n = ee.Number(fc.limit(1).size()).getInfo();
    if (n === null || n <= 0) {
      throw new Error('asset resolved to zero features');
    }
  } catch (err) {
    throw new Error(name + ' is invalid or inaccessible: ' + err.message);
  }
}

// -----------------------------------------------------------------------------
// Reads MCD12Q1 year availability on the client so config validation can
// confirm exact-year support before the analytical workflow is allowed to run.
// -----------------------------------------------------------------------------
function clientMcd12YearCounts() {
  var years = ee.List(MCD12Q1.aggregate_array('system:time_start')).map(function(t) {
    return ee.Date(ee.Number(t)).get('year');
  }).getInfo() || [];

  var counts = {};
  for (var i = 0; i < years.length; i++) {
    var y = String(years[i]);
    counts[y] = (counts[y] || 0) + 1;
  }
  return counts;
}

// -----------------------------------------------------------------------------
// Hard-locks the script to the agreed c1 analytical contract.
// This protects against accidental edits to the year window or denominator policy
// and fails early if exact annual land-cover support is missing.
// -----------------------------------------------------------------------------
function validateConfig() {
  if (START !== '2012-01-01' || END !== '2025-01-01') {
    throw new Error('This overlap-era ACZ script is locked to START=2012-01-01 and END=2025-01-01.');
  }
  if (DENOM_START_YEAR !== 2012 || DENOM_END_YEAR !== 2024) {
    throw new Error('This overlap-era ACZ script is locked to DENOM_START_YEAR=2012 and DENOM_END_YEAR=2024.');
  }
  if (typeof START !== 'string' || typeof END !== 'string') {
    throw new Error('START and END must be YYYY-MM-DD strings.');
  }
  if (START >= END) {
    throw new Error('START must be strictly earlier than END.');
  }
  if (DENOM_START_YEAR > DENOM_END_YEAR) {
  throw new Error('DENOM_START_YEAR must be <= DENOM_END_YEAR.');
  }
  if (!DEFAULT_ZONE_ID) {
    throw new Error('DEFAULT_ZONE_ID must be set to a canonical Stage 1 zone_id.');
  }

  validateFeatureCollectionAsset('GHANA_LAND_FC', GHANA_LAND_FC);
  validateFeatureCollectionAsset('AOI_FC', AOI_FC);

  var counts = clientMcd12YearCounts();
  var missing = [];
  var duplicated = [];
  for (var y = DENOM_START_YEAR; y <= DENOM_END_YEAR; y++) {
    var key = String(y);
    var c = counts[key] || 0;
    if (c === 0) missing.push(y);
    if (c > 1) duplicated.push(y + ' (count=' + c + ')');
  }
  if (missing.length > 0) {
    throw new Error('MCD12Q1 is missing required exact denominator year(s): ' + missing.join(', '));
  }
  if (duplicated.length > 0) {
    throw new Error('MCD12Q1 has duplicated denominator year records where exactly one is expected: ' + duplicated.join(', '));
  }
}

validateConfig();


// ============================== EE HELPERS ===================================

// -----------------------------------------------------------------------------
// Geometry hygiene helper. The buffer(0, 1) pattern is used repeatedly to
// stabilise geometries before intersections or reductions.
// -----------------------------------------------------------------------------
function cleanGeom(g) {
  return ee.Geometry(g).buffer(0, 1);
}

// -----------------------------------------------------------------------------
// Normalises possibly-null EE reduction outputs into numbers with a fallback.
// This prevents null propagation from sparse reductions.
// -----------------------------------------------------------------------------
function safeNumber(x, fallback) {
  return ee.Number(ee.Algorithms.If(ee.Algorithms.IsEqual(x, null), fallback, x));
}

// -----------------------------------------------------------------------------
// Safe division helper for ratios/fractions. Returns null rather than
// throwing or producing meaningless values when the denominator is zero.
// -----------------------------------------------------------------------------
function safeFrac(num, den) {
  num = ee.Number(num);
  den = ee.Number(den);
  return ee.Algorithms.If(den.gt(0), num.divide(den), null);
}

// -----------------------------------------------------------------------------
// Convenience helper for threshold flags when a value may be null.
// -----------------------------------------------------------------------------
function safeGt(x, thresh) {
  return ee.Number(ee.Algorithms.If(ee.Algorithms.IsEqual(x, null), 0, ee.Number(x).gt(thresh))).int();
}

// -----------------------------------------------------------------------------
// Normalises text fields for robust canonical matching:
// trim whitespace, collapse repeated spaces, and treat common null-like strings as empty.
// -----------------------------------------------------------------------------
function normText(s) {
  s = ee.String(ee.Algorithms.If(ee.Algorithms.IsEqual(s, null), '', s));
  s = s.trim().replace('\\s+', ' ');
  var lower = s.toLowerCase();
  var nullLike = s.length().eq(0)
    .or(lower.compareTo('null').eq(0))
    .or(lower.compareTo('none').eq(0))
    .or(lower.compareTo('na').eq(0))
    .or(lower.compareTo('n/a').eq(0))
    .or(lower.compareTo('nan').eq(0))
    .or(lower.compareTo('undefined').eq(0));
  return ee.String(ee.Algorithms.If(nullLike, '', s));
}

// -----------------------------------------------------------------------------
// Builds an upper-case, punctuation-stripped lookup key for matching names
// against the canonical Stage 1 ACZ dictionaries.
// -----------------------------------------------------------------------------
function normKey(s) {
  return normText(s).toUpperCase().replace('[^A-Z0-9]+', ' ').replace('\\s+', ' ').trim();
}

// -----------------------------------------------------------------------------
// Searches a feature for the first usable value across a prioritised list
// of candidate property names. This allows compatibility with alternate schema variants.
// -----------------------------------------------------------------------------
function pickProp(f, keys) {
  f = ee.Feature(f);
  keys = ee.List(keys);
  var names = f.propertyNames();
  var out = keys.iterate(function(k, acc) {
    acc = ee.String(acc);
    var val = ee.String(ee.Algorithms.If(names.contains(k), f.get(k), ''));
    val = normText(val);
    return ee.String(ee.Algorithms.If(acc.length().gt(0), acc, val));
  }, ee.String(''));
  return ee.String(out);
}

// -----------------------------------------------------------------------------
// Converts any truthy mask-like image into a strict 0/1 image.
// This is the base mask representation used before selfMask() is applied.
// -----------------------------------------------------------------------------
function mask01(img) {
  return ee.Image(img).unmask(0).gt(0).toUint8();
}

// -----------------------------------------------------------------------------
// Converts a 0/1 image into a TRUE MASK suitable for updateMask(...).
// This enforces the script-wide true-mask convention.
// -----------------------------------------------------------------------------
function asTrueMask(img) {
  return mask01(img).selfMask();
}

// -----------------------------------------------------------------------------
// Builds the month-by-month analysis calendar from START to END (exclusive).
// Each list element is a dictionary containing the month start and end dates.
// -----------------------------------------------------------------------------
function monthSequence(start, end) {
  var s = ee.Date(start);
  var e = ee.Date(end);
  var n = e.difference(s, 'month').toInt();
  return ee.List.sequence(0, n.subtract(1)).map(function(i) {
    var d = s.advance(ee.Number(i), 'month');
    return ee.Dictionary({start: d, end: d.advance(1, 'month')});
  });
}


// -----------------------------------------------------------------------------
// Packages common date-derived fields used in row construction:
// YYYYMM integer, calendar year, and calendar month.
// -----------------------------------------------------------------------------
function dateParts(d) {
  d = ee.Date(d);
  return ee.Dictionary({
    yyyymm: ee.Number.parse(d.format('yyyyMM')),
    year: d.get('year'),
    month: d.get('month')
  });
}

// -----------------------------------------------------------------------------
// Clips any row collection to the dedicated merger-ready RP1 export window.
// The analytical backbone remains wider (2012–2024), but exported RP1 rows are
// restricted to 201201 through 202412 so BA and AF outputs share one merge key.
// -----------------------------------------------------------------------------
function filterToRp1ExportWindow(fc) {
  return ee.FeatureCollection(fc)
    .filter(ee.Filter.gte('yyyymm', RP1_EXPORT_START_YYYYMM))
    .filter(ee.Filter.lte('yyyymm', RP1_EXPORT_END_YYYYMM));
}

// -----------------------------------------------------------------------------
// Returns a month start/end pair for preview functions using a year and month input.
// -----------------------------------------------------------------------------
function monthWindow(year, month) {
  var start = ee.Date.fromYMD(year, month, 1);
  var end = start.advance(1, 'month');
  return {start: start, end: end};
}

// -----------------------------------------------------------------------------
// Utility for serialising lists into pipe-delimited provenance strings.
// -----------------------------------------------------------------------------
function joinPipe(listLike) {

  return ee.List(listLike).map(function(v) { return ee.String(v); }).join('|');
}


// ===================== CANONICAL ACZ LOOKUP (STAGE 1) ========================

var ZONE_BY_ID = ee.Dictionary({
  'coastal_zone':    ee.Dictionary({zone_id: 'coastal_zone',    zone_name: 'COASTAL ZONE',    zone_code: 'CZ'}),
  'forest_zone':     ee.Dictionary({zone_id: 'forest_zone',     zone_name: 'FOREST ZONE',     zone_code: 'FZ'}),
  'guinea_savannah': ee.Dictionary({zone_id: 'guinea_savannah', zone_name: 'GUINEA SAVANNAH', zone_code: 'GS'}),
  'sudan_savannah':  ee.Dictionary({zone_id: 'sudan_savannah',  zone_name: 'SUDAN SAVANNAH',  zone_code: 'SS'}),
  'transition_zone': ee.Dictionary({zone_id: 'transition_zone', zone_name: 'TRANSITION ZONE', zone_code: 'TZ'})
});

var ZONE_BY_CODE = ee.Dictionary({
  'CZ': ee.Dictionary({zone_id: 'coastal_zone',    zone_name: 'COASTAL ZONE',    zone_code: 'CZ'}),
  'FZ': ee.Dictionary({zone_id: 'forest_zone',     zone_name: 'FOREST ZONE',     zone_code: 'FZ'}),
  'GS': ee.Dictionary({zone_id: 'guinea_savannah', zone_name: 'GUINEA SAVANNAH', zone_code: 'GS'}),
  'SS': ee.Dictionary({zone_id: 'sudan_savannah',  zone_name: 'SUDAN SAVANNAH',  zone_code: 'SS'}),
  'TZ': ee.Dictionary({zone_id: 'transition_zone', zone_name: 'TRANSITION ZONE', zone_code: 'TZ'})
});

var ZONE_BY_NAME = ee.Dictionary({
  'COASTAL ZONE':         ee.Dictionary({zone_id: 'coastal_zone',    zone_name: 'COASTAL ZONE',    zone_code: 'CZ'}),
  'COASTAL':              ee.Dictionary({zone_id: 'coastal_zone',    zone_name: 'COASTAL ZONE',    zone_code: 'CZ'}),
  'COASTAL SAVANNAH':     ee.Dictionary({zone_id: 'coastal_zone',    zone_name: 'COASTAL ZONE',    zone_code: 'CZ'}),
  'COASTAL SAVANNA':      ee.Dictionary({zone_id: 'coastal_zone',    zone_name: 'COASTAL ZONE',    zone_code: 'CZ'}),

  'FOREST ZONE':          ee.Dictionary({zone_id: 'forest_zone',     zone_name: 'FOREST ZONE',     zone_code: 'FZ'}),
  'FOREST':               ee.Dictionary({zone_id: 'forest_zone',     zone_name: 'FOREST ZONE',     zone_code: 'FZ'}),
  'FOREST BELT':          ee.Dictionary({zone_id: 'forest_zone',     zone_name: 'FOREST ZONE',     zone_code: 'FZ'}),

  'GUINEA SAVANNAH':      ee.Dictionary({zone_id: 'guinea_savannah', zone_name: 'GUINEA SAVANNAH', zone_code: 'GS'}),
  'GUINEA SAVANNA':       ee.Dictionary({zone_id: 'guinea_savannah', zone_name: 'GUINEA SAVANNAH', zone_code: 'GS'}),
  'GUINEA SAVANNAH ZONE': ee.Dictionary({zone_id: 'guinea_savannah', zone_name: 'GUINEA SAVANNAH', zone_code: 'GS'}),
  'GUINEA SAVANNA ZONE':  ee.Dictionary({zone_id: 'guinea_savannah', zone_name: 'GUINEA SAVANNAH', zone_code: 'GS'}),

  'SUDAN SAVANNAH':       ee.Dictionary({zone_id: 'sudan_savannah',  zone_name: 'SUDAN SAVANNAH',  zone_code: 'SS'}),
  'SUDAN SAVANNA':        ee.Dictionary({zone_id: 'sudan_savannah',  zone_name: 'SUDAN SAVANNAH',  zone_code: 'SS'}),
  'SUDAN SAVANNAH ZONE':  ee.Dictionary({zone_id: 'sudan_savannah',  zone_name: 'SUDAN SAVANNAH',  zone_code: 'SS'}),
  'SUDAN SAVANNA ZONE':   ee.Dictionary({zone_id: 'sudan_savannah',  zone_name: 'SUDAN SAVANNAH',  zone_code: 'SS'}),

  'TRANSITION ZONE':      ee.Dictionary({zone_id: 'transition_zone', zone_name: 'TRANSITION ZONE', zone_code: 'TZ'}),
  'TRANSITION':           ee.Dictionary({zone_id: 'transition_zone', zone_name: 'TRANSITION ZONE', zone_code: 'TZ'})
});

// -----------------------------------------------------------------------------
// Primary canonical lookup using zone_id.
// -----------------------------------------------------------------------------
function canonicalFieldFromId(zoneId, fieldName) {
  zoneId = normText(zoneId).toLowerCase();
  return ee.String(ee.Algorithms.If(
    ZONE_BY_ID.contains(zoneId),
    ee.Dictionary(ZONE_BY_ID.get(zoneId)).get(fieldName),
    ''
  ));
}

// -----------------------------------------------------------------------------
// Secondary canonical lookup using zone_code.
// -----------------------------------------------------------------------------
function canonicalFieldFromCode(zoneCode, fieldName) {
  zoneCode = normText(zoneCode).toUpperCase();
  return ee.String(ee.Algorithms.If(
    ZONE_BY_CODE.contains(zoneCode),
    ee.Dictionary(ZONE_BY_CODE.get(zoneCode)).get(fieldName),
    ''
  ));
}

// -----------------------------------------------------------------------------
// Fallback canonical lookup using normalised zone_name text.
// -----------------------------------------------------------------------------
function canonicalFieldFromName(zoneName, fieldName) {
  var key = normKey(zoneName);
  return ee.String(ee.Algorithms.If(
    ZONE_BY_NAME.contains(key),
    ee.Dictionary(ZONE_BY_NAME.get(key)).get(fieldName),
    ''
  ));
}

// -----------------------------------------------------------------------------
// Resolves canonical identifiers using the strict priority order:
// zone_id -> zone_code -> zone_name.
// -----------------------------------------------------------------------------
function resolveCanonicalField(rawZoneId, rawZoneCode, rawZoneName, fieldName) {
  var fromId = canonicalFieldFromId(rawZoneId, fieldName);
  var fromCode = canonicalFieldFromCode(rawZoneCode, fieldName);
  var fromName = canonicalFieldFromName(rawZoneName, fieldName);
  return ee.String(ee.Algorithms.If(
    fromId.length().gt(0),
    fromId,
    ee.Algorithms.If(fromCode.length().gt(0), fromCode, fromName)
  ));
}


// ============================== AOI PREP =====================================

var GHANA_LAND = cleanGeom(GHANA_LAND_FC.geometry());
var AOI_RAW_FC = ee.FeatureCollection(AOI_FC);
var aoiGeom_raw  = cleanGeom(AOI_RAW_FC.geometry());
var aoiGeom_land = cleanGeom(aoiGeom_raw.intersection(GHANA_LAND, 1));

var AOI_AREA_KM2_RAW  = ee.Number(aoiGeom_raw.area({maxError: 1})).divide(1e6);
var AOI_AREA_KM2_LAND = ee.Number(aoiGeom_land.area({maxError: 1})).divide(1e6);
var AOI_OUTSIDE_LAND_KM2 = ee.Number(ee.Algorithms.If(
  AOI_AREA_KM2_RAW.subtract(AOI_AREA_KM2_LAND).lt(0),
  0,
  AOI_AREA_KM2_RAW.subtract(AOI_AREA_KM2_LAND)
));
var AOI_OUTSIDE_LAND_FRAC = safeFrac(AOI_OUTSIDE_LAND_KM2, AOI_AREA_KM2_RAW);
var OUTSIDE_LAND_WARN_FLAG = ee.Number(ee.Algorithms.If(
  AOI_AREA_KM2_RAW.gt(0).and(safeGt(AOI_OUTSIDE_LAND_FRAC, OUTSIDE_LAND_WARN_FRAC).eq(1)),
  1,
  0
)).int();
var RECORDS_OUTSIDE_LAND = AOI_AREA_KM2_LAND.lte(0).int();
var RECORDS_JOINED_LAND  = RECORDS_OUTSIDE_LAND.eq(0).int();

var ZONE_ID_KEYS = ['zone_id', 'ZONE_ID', 'aczid_can', 'ACZID_CAN', 'acz_id', 'ACZ_ID'];
var ZONE_NAME_KEYS = ['zone_name', 'ZONE_NAME', 'acz_name', 'ACZ_NAME'];
var ZONE_CODE_KEYS = ['zone_code', 'ZONE_CODE', 'aczid_code', 'ACZID_CODE'];

// -----------------------------------------------------------------------------
// Annotates each raw AOI feature with resolved canonical Stage 1 ACZ fields
// plus diagnostics on whether the binding succeeded and which field drove it.
// -----------------------------------------------------------------------------
function attachCanonicalZone(f) {
  f = ee.Feature(f);
  var rawId = pickProp(f, ZONE_ID_KEYS);
  var rawName = pickProp(f, ZONE_NAME_KEYS);
  var rawCode = pickProp(f, ZONE_CODE_KEYS);

  var resolvedId = resolveCanonicalField(rawId, rawCode, rawName, 'zone_id');
  var resolvedName = resolveCanonicalField(rawId, rawCode, rawName, 'zone_name');
  var resolvedCode = resolveCanonicalField(rawId, rawCode, rawName, 'zone_code');

  var bindingOk = resolvedId.length().gt(0)
    .and(resolvedName.length().gt(0))
    .and(resolvedCode.length().gt(0));

  var bindingSource = ee.String(ee.Algorithms.If(
    bindingOk.not(),
    'unresolved',
    ee.Algorithms.If(
      canonicalFieldFromId(rawId, 'zone_id').length().gt(0),
      'zone_id',
      ee.Algorithms.If(
        canonicalFieldFromCode(rawCode, 'zone_id').length().gt(0),
        'zone_code',
        'zone_name'
      )
    )
  ));

  return f.set({
    raw_zone_id: rawId,
    raw_zone_name: rawName,
    raw_zone_code: rawCode,
    resolved_zone_id: resolvedId,
    resolved_zone_name: resolvedName,
    resolved_zone_code: resolvedCode,
    canonical_binding_ok_flag: ee.Number(bindingOk).int(),
    canonical_binding_source: bindingSource,
    canonical_binding_fallback_flag: ee.Number(ee.Algorithms.If(
      bindingOk,
      ee.Algorithms.If(ee.Algorithms.IsEqual(bindingSource, 'zone_id'), 0, 1),
      0
    )).int()
  });
}

var AOI_CANONICAL_FC = AOI_RAW_FC.map(attachCanonicalZone);

var DISTINCT_RESOLVED_ZONE_IDS = ee.List(AOI_CANONICAL_FC
  .filter(ee.Filter.eq('canonical_binding_ok_flag', 1))
  .aggregate_array('resolved_zone_id')).distinct().sort();

var DISTINCT_RESOLVED_ZONE_NAMES = ee.List(AOI_CANONICAL_FC
  .filter(ee.Filter.eq('canonical_binding_ok_flag', 1))
  .aggregate_array('resolved_zone_name')).distinct().sort();

var DISTINCT_RESOLVED_ZONE_CODES = ee.List(AOI_CANONICAL_FC
  .filter(ee.Filter.eq('canonical_binding_ok_flag', 1))
  .aggregate_array('resolved_zone_code')).distinct().sort();

var DISTINCT_BINDING_SOURCES = ee.List(AOI_CANONICAL_FC
  .aggregate_array('canonical_binding_source')).distinct().sort();

var UNRESOLVED_FEATURE_COUNT = AOI_CANONICAL_FC
  .filter(ee.Filter.eq('canonical_binding_ok_flag', 0)).size();

var BINDING_FALLBACK_FEATURE_COUNT = AOI_CANONICAL_FC
  .filter(ee.Filter.eq('canonical_binding_fallback_flag', 1)).size();

var canonicalIdentityInfo = ee.Dictionary({
  zone_ids: DISTINCT_RESOLVED_ZONE_IDS,
  zone_names: DISTINCT_RESOLVED_ZONE_NAMES,
  zone_codes: DISTINCT_RESOLVED_ZONE_CODES,
  binding_sources: DISTINCT_BINDING_SOURCES,
  unresolved_count: UNRESOLVED_FEATURE_COUNT,
  fallback_feature_count: BINDING_FALLBACK_FEATURE_COUNT,
  land_area_km2: AOI_AREA_KM2_LAND,
  feature_count: AOI_CANONICAL_FC.size()
}).getInfo();

if ((canonicalIdentityInfo.land_area_km2 || 0) <= 0) {
  throw new Error('AOI has zero land intersection with the Ghana land-only boundary.');
}
if ((canonicalIdentityInfo.unresolved_count || 0) > 0) {
  throw new Error('AOI contains feature(s) that do not resolve to a canonical Stage 1 ACZ.');
}
if (!canonicalIdentityInfo.zone_ids || canonicalIdentityInfo.zone_ids.length !== 1) {
  throw new Error('AOI must resolve to exactly one canonical zone_id.');
}
if (!canonicalIdentityInfo.zone_names || canonicalIdentityInfo.zone_names.length !== 1) {
  throw new Error('AOI must resolve to exactly one canonical zone_name.');
}
if (!canonicalIdentityInfo.zone_codes || canonicalIdentityInfo.zone_codes.length !== 1) {
  throw new Error('AOI must resolve to exactly one canonical zone_code.');
}

var CANONICAL_ZONE_ID   = ee.String(canonicalIdentityInfo.zone_ids[0]);
var CANONICAL_ZONE_NAME = ee.String(canonicalIdentityInfo.zone_names[0]);
var CANONICAL_ZONE_CODE = ee.String(canonicalIdentityInfo.zone_codes[0]);
var CANONICAL_BINDING_SOURCE = ee.String((canonicalIdentityInfo.binding_sources || []).join('|'));
var CANONICAL_BINDING_OK = ee.Number(1).int();

print('AOI feature count ->', AOI_CANONICAL_FC.size());
print('Raw AOI canonical prep preview ->', AOI_CANONICAL_FC.limit(5));
print('Canonical zone_id ->', CANONICAL_ZONE_ID);
print('Canonical zone_name ->', CANONICAL_ZONE_NAME);
print('Canonical zone_code ->', CANONICAL_ZONE_CODE);
print('Canonical binding sources ->', CANONICAL_BINDING_SOURCE);
print('Fallback-bound feature count ->', BINDING_FALLBACK_FEATURE_COUNT);
print('AOI land-only area (km²) ->', AOI_AREA_KM2_LAND);

// The single ACZ unit feature created here is the metadata carrier for every
// exported month row. All AOI diagnostics and canonical identifiers are attached
// once at this stage so later row construction can simply copy them through.
var UNIT_FEATURE = ee.Feature(aoiGeom_land, {
  schema_version: RP1_SCHEMA_VERSION,
  level: LEVEL_VALUE,
  unit_id: CANONICAL_ZONE_ID,
  unit_code: CANONICAL_ZONE_CODE,
  unit_name: CANONICAL_ZONE_NAME,
  parent_level: '',
  parent_id: '',
  parent_code: '',
  parent_name: '',

  aoi_area_km2: AOI_AREA_KM2_RAW,
  aoi_area_land_km2: AOI_AREA_KM2_LAND,
  aoi_outside_land_km2: AOI_OUTSIDE_LAND_KM2,
  aoi_outside_land_frac: AOI_OUTSIDE_LAND_FRAC,
  outside_land_warn_flag: OUTSIDE_LAND_WARN_FLAG,
  records_joined_land: RECORDS_JOINED_LAND,
  records_outside_land: RECORDS_OUTSIDE_LAND,

  canonical_binding_ok_flag: CANONICAL_BINDING_OK,
  canonical_binding_source: CANONICAL_BINDING_SOURCE,
  canonical_binding_fallback_feature_count: BINDING_FALLBACK_FEATURE_COUNT,
  raw_zone_id: joinPipe(ee.List(AOI_CANONICAL_FC.aggregate_array('raw_zone_id')).distinct().sort()),
  raw_zone_name: joinPipe(ee.List(AOI_CANONICAL_FC.aggregate_array('raw_zone_name')).distinct().sort()),
  raw_zone_code: joinPipe(ee.List(AOI_CANONICAL_FC.aggregate_array('raw_zone_code')).distinct().sort())
});


var UNITS_PREP = ee.FeatureCollection([UNIT_FEATURE]);

// -----------------------------------------------------------------------------
// Renders the AOI/ACZ boundary into an image layer for the lightweight QA map.
// -----------------------------------------------------------------------------
function getZoneBoundaryImage(fc, width) {
  return ee.Image().byte().paint(fc, 1, width || BOUNDARY_WIDTH);
}


// ============================ PROJECTION / CRS ===============================

var IMPACT_PROJ = ee.Image(MCD64A1.first()).select(IMPACT_BAND_BURNDATE).projection();
var IMPACT_CRS = IMPACT_PROJ.crs();
var IMPACT_NOMINAL_SCALE_M = IMPACT_PROJ.nominalScale();

var PIXEL_AREA_KM2_IMPACT = ee.Image.pixelArea()
  .reproject({crs: IMPACT_PROJ})
  .divide(1e6);


// ===================== AREA / COUNT REDUCTION HELPERS ========================

// -----------------------------------------------------------------------------
// Computes km² by summing a MODIS-grid pixel-area image under a TRUE MASK.
// This is the main area-computation path used for analytical outputs.
// -----------------------------------------------------------------------------
function areaMaskedKm2(maskImg, geom) {
  var img = PIXEL_AREA_KM2_IMPACT.updateMask(ee.Image(maskImg)).rename('area');
  var dict = img.reduceRegion({
    reducer: ee.Reducer.sum().unweighted(),
    geometry: geom,
    scale: SCALE_BA,
    crs: IMPACT_CRS,
    maxPixels: MAX_PIXELS,
    tileScale: TILE_SCALE
  });
  return safeNumber(dict.get('area'), 0);
}

// -----------------------------------------------------------------------------
// Independent algebraic area path used for drift audits.
// Instead of updateMask(...), it multiplies pixel area by a 0/1 mask.
// -----------------------------------------------------------------------------
function areaMaskedKm2Audit(maskImg, geom) {
  var img = PIXEL_AREA_KM2_IMPACT.multiply(mask01(maskImg)).rename('area');
  var dict = img.reduceRegion({
    reducer: ee.Reducer.sum().unweighted(),
    geometry: geom,
    scale: SCALE_BA,
    crs: IMPACT_CRS,
    maxPixels: MAX_PIXELS,
    tileScale: TILE_SCALE
  });
  return safeNumber(dict.get('area'), 0);
}

// -----------------------------------------------------------------------------
// Counts masked pixels on the MODIS analysis grid.
// Useful for denominator size diagnostics and burned-pixel counts.
// -----------------------------------------------------------------------------
function pixelCount(maskImg, geom) {
  var img = mask01(maskImg).rename('pc');
  var dict = img.reduceRegion({
    reducer: ee.Reducer.sum().unweighted(),
    geometry: geom,
    scale: SCALE_BA,
    crs: IMPACT_CRS,
    maxPixels: MAX_PIXELS,
    tileScale: TILE_SCALE
  });
  return safeNumber(dict.get('pc'), 0);
}

// -----------------------------------------------------------------------------
// Compares two denominator-area estimates and applies the configured
// absolute/relative tolerance rule to flag suspicious divergence.
// -----------------------------------------------------------------------------
function driftAudit(reportedKm2, checkKm2) {
  reportedKm2 = ee.Number(reportedKm2);
  checkKm2 = ee.Number(checkKm2);

  var absDiff = checkKm2.subtract(reportedKm2).abs();
  var relDiff = ee.Algorithms.If(reportedKm2.gt(0), absDiff.divide(reportedKm2), null);
  var thresh = ee.Number(DENOM_DRIFT_TOL_ABS_KM2)
    .max(reportedKm2.multiply(DENOM_DRIFT_TOL_REL_FRAC));
  var flag = absDiff.gt(thresh).int();

  return ee.Dictionary({
    abs_diff_km2: absDiff,
    rel_diff: relDiff,
    thresh_km2: thresh,
    flag: flag
  });
}


// =========================== DENOM YEAR SUPPORT ==============================

// -----------------------------------------------------------------------------
// Builds the server-side list of distinct MCD12Q1 calendar years.
// -----------------------------------------------------------------------------
function availableYearsMcd12() {
  return ee.List(MCD12Q1.aggregate_array('system:time_start')).map(function(t) {
    return ee.Date(ee.Number(t)).get('year');
  }).distinct().sort();
}

var MCD12_AVAILABLE_YEARS = availableYearsMcd12();
var TARGET_YEARS = ee.List.sequence(DENOM_START_YEAR, DENOM_END_YEAR);
var MISSING_TARGET_YEARS = ee.List(TARGET_YEARS.iterate(function(y, acc) {
  acc = ee.List(acc);
  y = ee.Number(y).int();
  return ee.List(ee.Algorithms.If(MCD12_AVAILABLE_YEARS.contains(y), acc, acc.add(y)));
}, ee.List([])));
var denom_missing_years_count = ee.Number(MISSING_TARGET_YEARS.length());
var denom_years_used_pipe = ee.List(TARGET_YEARS).map(function(y) { return ee.Number(y).format('%d'); }).join('|');
var denom_missing_years_pipe = ee.List(MISSING_TARGET_YEARS).map(function(y) { return ee.Number(y).format('%d'); }).join('|');

print('MCD12 available years ->', MCD12_AVAILABLE_YEARS);
print('Target denominator years ->', TARGET_YEARS);
print('Missing target years count ->', denom_missing_years_count);


// ============================= MASK BUILDERS =================================


// -----------------------------------------------------------------------------
// Core numerator definition: BurnDate > 0 in ANY overlapping image within a month,
// collapsed by max over per-image burned masks.
// -----------------------------------------------------------------------------
function monthlyBurnedMaskOr(start, end) {
  start = ee.Date(start);
  end = ee.Date(end);
  var monthCol = MCD64A1.filterDate(start, end);
  var burnedAny01 = ee.ImageCollection(monthCol.map(function(img) {
    return ee.Image(img).gt(0);
  })).max().unmask(0);
  return asTrueMask(burnedAny01);
}

// -----------------------------------------------------------------------------
// Diagnostic BurnDate mosaic for the preview UI. This is not the analytical
// numerator definition; it is only for visual inspection.
// -----------------------------------------------------------------------------
function monthlyBurnDateMax(start, end) {
  start = ee.Date(start);
  end = ee.Date(end);
  var monthCol = MCD64A1.filterDate(start, end);
  return ee.Image(monthCol.max()).select(IMPACT_BAND_BURNDATE).unmask(0);
}

// -----------------------------------------------------------------------------
// Fetches the exact annual MCD12Q1 image for a required year.
// Because c1 forbids fallback, this function is intentionally exact-year only.
// -----------------------------------------------------------------------------
function mcd12ImageForYearExact(year) {
  year = ee.Number(year).int();
  var colYear = MCD12Q1.filter(ee.Filter.calendarRange(year, year, 'year'));
  return ee.Image(colYear.first()).select([DENOM_BAND_LC_TYPE1, DENOM_BAND_LW]);
}

// -----------------------------------------------------------------------------
// Builds the frozen c1 exclusion mask for a given year:
// exclude where LW != 2 OR LC_Type1 == 17.
// -----------------------------------------------------------------------------
function annualBaExcludedMaskForYear(year) {
  // Frozen c1 baseline exclusion: water if LW != 2 OR LC_Type1 == 17.
  var img = mcd12ImageForYearExact(year);
  var lc = img.select(DENOM_BAND_LC_TYPE1).unmask(0);
  var lwIsLand = img.select(DENOM_BAND_LW).eq(2).unmask(0);
  var excluded01 = lwIsLand.not().or(lc.eq(17));
  return asTrueMask(excluded01).rename('ba_excluded_annual');
}

// -----------------------------------------------------------------------------
// Builds the complement of the c1 exclusion mask.
// This is the annual keep-mask: LW == 2 AND LC_Type1 != 17.
// -----------------------------------------------------------------------------
function annualBaKeepMaskForYear(year) {
  var excluded = annualBaExcludedMaskForYear(year).unmask(0);
  return asTrueMask(excluded.not()).rename('ba_keep_annual');
}

// -----------------------------------------------------------------------------
// Defines annual "land support" under the frozen c1 keep-mask.
// This is intentionally narrower than an LW-only definition.
// -----------------------------------------------------------------------------
function annualLandMaskForYear(year) {
  // In c1, annual land support follows the frozen baseline keep-mask rather than
  // the broader LW-only support used in raw v3.
  return annualBaKeepMaskForYear(year).rename('land_annual');
}

// -----------------------------------------------------------------------------
// Builds the exact-year annual burnable denominator by intersecting
// LC_INCLUDE with the c1 keep-mask.
// -----------------------------------------------------------------------------
function annualBurnableMaskForYear(year) {
  var img = mcd12ImageForYearExact(year);
  var lc01 = img.select(DENOM_BAND_LC_TYPE1)
    .remap(LC_INCLUDE, ee.List.repeat(1, LC_INCLUDE.length()), 0)
    .unmask(0)
    .toUint8();
  var keep01 = annualBaKeepMaskForYear(year).unmask(0).toUint8();
  return asTrueMask(lc01.and(keep01)).rename('burnable_annual');
}

// -----------------------------------------------------------------------------
// Combines annual burnable masks across all target years using pixel-wise OR.
// The result is the fixed union denominator used by the main numerator path.
// -----------------------------------------------------------------------------
function buildBurnableUnionExact(targetYears) {
  var stack = ee.ImageCollection(ee.List(targetYears).map(function(y) {
    return annualBurnableMaskForYear(ee.Number(y).int()).unmask(0).rename('burn');
  }));
  return asTrueMask(stack.max()).rename('burnable_union');
}


// ============================== BURNABLE UNION ===============================

var BURN_UNION = buildBurnableUnionExact(TARGET_YEARS);
var BURNABLE_KM2_UNION = areaMaskedKm2(BURN_UNION, aoiGeom_land);
var BURNABLE_PIXEL_COUNT_UNION = pixelCount(BURN_UNION, aoiGeom_land);
var ZERO_UNION_DEN_FLAG = BURNABLE_KM2_UNION.lte(0).int();
var SMALL_DEN = BURNABLE_KM2_UNION.lt(SMALL_DEN_THRESHOLD_KM2).int();

print('Burnable union km² ->', BURNABLE_KM2_UNION);
print('Union burnable pixel count ->', BURNABLE_PIXEL_COUNT_UNION);
print('Zero union denominator flag ->', ZERO_UNION_DEN_FLAG);


// ========================= QA: UNION DENOM AUDIT =============================

var DENOM_KM2_CHECK_ONCE = areaMaskedKm2Audit(BURN_UNION, aoiGeom_land);
var unionAudit = driftAudit(BURNABLE_KM2_UNION, DENOM_KM2_CHECK_ONCE);

var DENOM_ABS_DIFF_ONCE = ee.Number(unionAudit.get('abs_diff_km2'));
var DENOM_REL_DIFF_ONCE = unionAudit.get('rel_diff');
var DENOM_DRIFT_THRESH_KM2_ONCE = ee.Number(unionAudit.get('thresh_km2'));
var DENOM_DRIFT_FLAG_ONCE = ee.Number(unionAudit.get('flag')).int();

print('Union denominator audit: reported ->', BURNABLE_KM2_UNION);
print('Union denominator audit: check    ->', DENOM_KM2_CHECK_ONCE);
print('Union denominator audit: flag     ->', DENOM_DRIFT_FLAG_ONCE);


// =========================== ANNUAL DENOM TABLE ==============================

var ANNUAL_DENOM_TABLE = ee.FeatureCollection(TARGET_YEARS.map(function(y) {
  y = ee.Number(y).int();

  var annualLand = annualLandMaskForYear(y).clip(aoiGeom_land);
  var annualBurnable = annualBurnableMaskForYear(y).clip(aoiGeom_land);

  var annual_land_km2 = areaMaskedKm2(annualLand, aoiGeom_land);
  var annual_land_pixel_count = pixelCount(annualLand, aoiGeom_land);
  var burnable_km2_annual = areaMaskedKm2(annualBurnable, aoiGeom_land);
  var burnable_pixel_count_annual = pixelCount(annualBurnable, aoiGeom_land);
  var zero_annual_den_flag = burnable_km2_annual.lte(0).int();

  var denom_annual_km2_check = areaMaskedKm2Audit(annualBurnable, aoiGeom_land);
  var annualAudit = driftAudit(burnable_km2_annual, denom_annual_km2_check);

  return ee.Feature(null, {
    year: y,
    denom_year_target: y,
    denom_year_used: y,
    denom_year_fallback_flag: 0,
    annual_land_km2: annual_land_km2,
    annual_land_pixel_count: annual_land_pixel_count,
    burnable_km2_annual: burnable_km2_annual,
    burnable_pixel_count_annual: burnable_pixel_count_annual,
    zero_annual_den_flag: zero_annual_den_flag,
    denom_annual_km2_check: denom_annual_km2_check,
    denom_annual_abs_diff_km2: ee.Number(annualAudit.get('abs_diff_km2')),
    denom_annual_rel_diff: annualAudit.get('rel_diff'),
    denom_annual_drift_thresh_km2: ee.Number(annualAudit.get('thresh_km2')),
    denom_annual_drift_flag: ee.Number(annualAudit.get('flag')).int()
  });
}));

var annual_zero_years = ANNUAL_DENOM_TABLE
  .filter(ee.Filter.eq('zero_annual_den_flag', 1))
  .aggregate_array('year');

var annual_zero_years_count = ee.Number(ee.List(annual_zero_years).length());
var annual_zero_years_pipe = ee.List(annual_zero_years)
  .map(function(v) { return ee.Number(v).format('%d'); })
  .join('|');
var annual_used_years_pipe = ee.List(ANNUAL_DENOM_TABLE.aggregate_array('denom_year_used'))
  .map(function(v) { return ee.Number(v).format('%d'); })
  .join('|');

print('Annual denominator table preview ->', ANNUAL_DENOM_TABLE.limit(5));


// ========================= NATIONAL MONTHLY BA REFERENCE =====================

// -----------------------------------------------------------------------------
// Computes a Ghana-wide monthly burned-area reference under the same union mask.
// This supports the zero_local_but_national_ba QA flag.
// -----------------------------------------------------------------------------
function nationalBaKm2(start, end) {
  var burnedAny = monthlyBurnedMaskOr(start, end)
    .updateMask(BURN_UNION)
    .clip(GHANA_LAND);
  return areaMaskedKm2(burnedAny, GHANA_LAND);
}


// ============================== MONTHLY PANEL ================================

var MONTHS_ALL = monthSequence(START, END);

// Main monthly row constructor for the selected current zone.
// Each month is processed independently but under the same frozen union denominator,
// and year-specific annual denominator fields are attached by calendar year.
var rows_pre = ee.FeatureCollection(MONTHS_ALL.map(function(md) {
  md = ee.Dictionary(md);
  var start = ee.Date(md.get('start'));
  var end = ee.Date(md.get('end'));
  var parts = dateParts(start);
  var monthYear = ee.Number(parts.get('year')).int();
  var monthYYYYMM = ee.Number(parts.get('yyyymm')).int();

  var burnedAny = monthlyBurnedMaskOr(start, end)
    .updateMask(BURN_UNION)
    .clip(aoiGeom_land);

  var ba_km2 = areaMaskedKm2(burnedAny, aoiGeom_land);
  var burned_pixel_count = pixelCount(burnedAny, aoiGeom_land);
  var ba_any = ba_km2.gt(0).int();

  var burned_frac_union = ee.Algorithms.If(
    BURNABLE_KM2_UNION.gt(0),
    ba_km2.divide(BURNABLE_KM2_UNION),
    null
  );

  var annualRow = ee.Feature(ANNUAL_DENOM_TABLE.filter(ee.Filter.eq('year', monthYear)).first());

  var annual_land_km2 = ee.Number(annualRow.get('annual_land_km2'));
  var annual_land_pixel_count = ee.Number(annualRow.get('annual_land_pixel_count'));
  var burnable_km2_annual = ee.Number(annualRow.get('burnable_km2_annual'));
  var burnable_pixel_count_annual = ee.Number(annualRow.get('burnable_pixel_count_annual'));
  var zero_annual_den_flag = ee.Number(annualRow.get('zero_annual_den_flag')).int();
  var denom_year_target = ee.Number(annualRow.get('denom_year_target')).int();
  var denom_year_used = ee.Number(annualRow.get('denom_year_used')).int();
  var denom_year_fallback_flag = ee.Number(annualRow.get('denom_year_fallback_flag')).int();
  var denom_annual_km2_check = ee.Number(annualRow.get('denom_annual_km2_check'));
  var denom_annual_abs_diff_km2 = ee.Number(annualRow.get('denom_annual_abs_diff_km2'));
  var denom_annual_rel_diff = annualRow.get('denom_annual_rel_diff');
  var denom_annual_drift_thresh_km2 = ee.Number(annualRow.get('denom_annual_drift_thresh_km2'));
  var denom_annual_drift_flag = ee.Number(annualRow.get('denom_annual_drift_flag')).int();

  var burned_frac_annual = ee.Algorithms.If(
    burnable_km2_annual.gt(0),
    ba_km2.divide(burnable_km2_annual),
    null
  );

  var denom_any_drift_flag = ee.Number(DENOM_DRIFT_FLAG_ONCE).max(ee.Number(denom_annual_drift_flag)).int();
  var nat_ba_km2 = nationalBaKm2(start, end);
  var zero_local_but_national_ba = ee.Number(ee.Algorithms.If(ba_km2.eq(0).and(nat_ba_km2.gt(0)), 1, 0)).int();
  var partial_viirs_overlap_flag = ee.Number(monthYYYYMM.eq(PARTIAL_VIIRS_OVERLAP_YYYYMM)).int();

  var unit = ee.Feature(UNITS_PREP.first());
  var runId = RUN_STAMP.cat('_').cat(LEVEL_VALUE).cat('_').cat(CANONICAL_ZONE_CODE).cat('_').cat(BA_MASK_SHORT_CODE);

  return ee.Feature(null, {
    // Shared Stage 1-aligned identity block for the merger-ready RP1 exports.
    run_id: runId,
    schema_version: unit.get('schema_version'),
    level: unit.get('level'),
    unit_id: unit.get('unit_id'),
    unit_code: unit.get('unit_code'),
    unit_name: unit.get('unit_name'),
    parent_level: unit.get('parent_level'),
    parent_id: unit.get('parent_id'),
    parent_code: unit.get('parent_code'),
    parent_name: unit.get('parent_name'),
    yyyymm: parts.get('yyyymm'),
    year: parts.get('year'),
    month: parts.get('month'),

    // Lean merger-ready MODIS BA base fields.
    modis_ba_km2: ba_km2,
    modis_burned_pixel_count: burned_pixel_count,
    modis_ba_any: ba_any,
    modis_burnable_km2_union: BURNABLE_KM2_UNION,
    modis_burnable_km2_annual: burnable_km2_annual,
    modis_burned_frac_union: burned_frac_union,
    modis_burned_frac_annual: burned_frac_annual,
    modis_aoi_area_land_km2: unit.get('aoi_area_land_km2'),
    modis_zero_union_den_flag: ZERO_UNION_DEN_FLAG,
    modis_zero_annual_den_flag: zero_annual_den_flag,

    // Ext diagnostics / provenance.
    annual_land_km2: annual_land_km2,
    annual_land_pixel_count: annual_land_pixel_count,
    burnable_pixel_count_union: BURNABLE_PIXEL_COUNT_UNION,
    burnable_pixel_count_annual: burnable_pixel_count_annual,

    aoi_area_km2: unit.get('aoi_area_km2'),
    aoi_outside_land_km2: unit.get('aoi_outside_land_km2'),
    aoi_outside_land_frac: unit.get('aoi_outside_land_frac'),
    outside_land_warn_flag: unit.get('outside_land_warn_flag'),
    records_joined_land: unit.get('records_joined_land'),
    records_outside_land: unit.get('records_outside_land'),

    canonical_binding_ok_flag: unit.get('canonical_binding_ok_flag'),
    canonical_binding_source: unit.get('canonical_binding_source'),
    canonical_binding_fallback_feature_count: unit.get('canonical_binding_fallback_feature_count'),
    raw_zone_id: unit.get('raw_zone_id'),
    raw_zone_name: unit.get('raw_zone_name'),
    raw_zone_code: unit.get('raw_zone_code'),

    small_den: SMALL_DEN,

    denom_year_target: denom_year_target,
    denom_year_used: denom_year_used,
    denom_year_fallback_flag: denom_year_fallback_flag,
    denom_years_used_pipe: denom_years_used_pipe,
    denom_missing_years_count: denom_missing_years_count,
    denom_missing_years_pipe: denom_missing_years_pipe,
    annual_zero_den_years_count: annual_zero_years_count,
    annual_zero_den_years_pipe: annual_zero_years_pipe,
    annual_denom_years_used_pipe: annual_used_years_pipe,

    zero_local_but_national_ba: zero_local_but_national_ba,
    partial_viirs_overlap_flag: partial_viirs_overlap_flag,
    denom_km2_check: DENOM_KM2_CHECK_ONCE,
    denom_abs_diff_km2: DENOM_ABS_DIFF_ONCE,
    denom_rel_diff: DENOM_REL_DIFF_ONCE,
    denom_drift_thresh_km2: DENOM_DRIFT_THRESH_KM2_ONCE,
    denom_drift_tol_abs_km2: DENOM_DRIFT_TOL_ABS_KM2,
    denom_drift_tol_rel_frac: DENOM_DRIFT_TOL_REL_FRAC,
    denom_drift_flag: DENOM_DRIFT_FLAG_ONCE,
    denom_annual_km2_check: denom_annual_km2_check,
    denom_annual_abs_diff_km2: denom_annual_abs_diff_km2,
    denom_annual_rel_diff: denom_annual_rel_diff,
    denom_annual_drift_thresh_km2: denom_annual_drift_thresh_km2,
    denom_annual_drift_flag: denom_annual_drift_flag,
    denom_any_drift_flag: denom_any_drift_flag,

    impact_product_id: IMPACT_PRODUCT_ID,
    impact_band_used_for_ba: IMPACT_BAND_BURNDATE,
    impact_bands_recognized_pipe: IMPACT_BANDS_RECOGNIZED.join('|'),
    denom_product_id: DENOM_PRODUCT_ID,
    denom_band_lc_type1: DENOM_BAND_LC_TYPE1,
    denom_band_lw: DENOM_BAND_LW,
    denom_exact_year_required_flag: DENOM_EXACT_YEAR_REQUIRED_FLAG,
    denom_union_role: DENOM_UNION_ROLE,
    denom_annual_role: DENOM_ANNUAL_ROLE,
    src_modis_version: SRC_MODIS_VERSION,
    src_landcover_version: SRC_LC_VERSION,

    script_release: SCRIPT_RELEASE,
    script_lineage: SCRIPT_LINEAGE,
    ba_mask_mode: BA_MASK_MODE,
    ba_mask_short_code: BA_MASK_SHORT_CODE,
    ba_mask_layer_label: BA_MASK_LAYER_LABEL,
    ba_mask_keep_summary: BA_MASK_KEEP_SUMMARY,
    ba_mask_excluded_summary: BA_MASK_EXCLUDED_SUMMARY,
    water_mask_definition: WATER_MASK_DEFINITION,
    lc_include_pipe: LC_INCLUDE_TEXT,

    reducer_type: REDUCER_TYPE,
    reducer_weighting: REDUCER_WEIGHTING,
    reducer_scale_m: SCALE_BA,
    reducer_tileScale: TILE_SCALE,
    reducer_maxPixels: MAX_PIXELS,
    reduction_crs: IMPACT_CRS,
    reduction_nominal_scale_m: IMPACT_NOMINAL_SCALE_M,

    denominator_definition: DENOMINATOR_DEFINITION,
    annual_denominator_definition: ANNUAL_DENOMINATOR_DEFINITION,
    annual_land_definition: ANNUAL_LAND_DEFINITION,
    monthly_ba_definition: MONTHLY_BA_DEFINITION,
    date_window_method_note: DATE_WINDOW_METHOD_NOTE,

    created_utc: CREATED_ISO,
    run_date: RUN_DATE_ISO,
    start: START,
    end_exclusive: END,
    months_count: ee.Number(MONTHS_ALL.length())
  });
}));

var rows_rp1_pre = filterToRp1ExportWindow(rows_pre);

print('Monthly rows preview ->', rows_pre.limit(5));
print('Monthly row count ->', rows_pre.size());
print('RP1 export rows preview ->', rows_rp1_pre.limit(5));
print('RP1 export row count ->', rows_rp1_pre.size());
print('Denominator drift count ->', rows_pre.filter(ee.Filter.eq('denom_any_drift_flag', 1)).size());
print('Rows with partial VIIRS overlap flag ->', rows_pre.filter(ee.Filter.eq('partial_viirs_overlap_flag', 1)).size());

// ============================== LIGHT QA UI ==================================
// The c1 analytical script keeps a deliberately light QA interface. It allows
// the operator to inspect the frozen baseline outputs for a chosen year/month
// without exposing any run-time method switching.

var ZONE_BOUNDARY_IMAGE = getZoneBoundaryImage(AOI_FC, BOUNDARY_WIDTH).clip(aoiGeom_land);

// -----------------------------------------------------------------------------
// Preview-only helper for annual LC_Type1 display.
// -----------------------------------------------------------------------------
function getLcPreviewImage(year) {
  return mcd12ImageForYearExact(year)
    .select(DENOM_BAND_LC_TYPE1)
    .clip(aoiGeom_land);
}

// -----------------------------------------------------------------------------
// Preview-only helper for the annual c1 excluded mask.
// -----------------------------------------------------------------------------
function getExcludedPreviewImage(year) {
  return annualBaExcludedMaskForYear(year).clip(aoiGeom_land);
}

// -----------------------------------------------------------------------------
// Preview-only helper for the fixed union denominator.
// -----------------------------------------------------------------------------
function getUnionPreviewImage() {
  return BURN_UNION.clip(aoiGeom_land);
}

// -----------------------------------------------------------------------------
// Preview-only helper for the selected year annual burnable denominator.
// -----------------------------------------------------------------------------
function getAnnualBurnablePreviewImage(year) {
  return annualBurnableMaskForYear(year).clip(aoiGeom_land);
}

// -----------------------------------------------------------------------------
// Preview-only helper for the monthly burned-area mask after union masking.
// -----------------------------------------------------------------------------
function getMonthlyBurnMaskPreviewImage(year, month) {
  var w = monthWindow(year, month);
  return monthlyBurnedMaskOr(w.start, w.end)
    .updateMask(BURN_UNION)
    .clip(aoiGeom_land);
}

// -----------------------------------------------------------------------------
// Preview-only helper for the diagnostic monthly BurnDate max layer.
// -----------------------------------------------------------------------------
function getMonthlyBurnDatePreviewImage(year, month) {
  var w = monthWindow(year, month);
  return monthlyBurnDateMax(w.start, w.end)
    .updateMask(BURN_UNION)
    .clip(aoiGeom_land);
}

// -----------------------------------------------------------------------------
// Builds a simple legend row with a colour swatch and label.
// -----------------------------------------------------------------------------
function legendRow(color, label) {
  var colorBox = ui.Label('', {
    backgroundColor: '#' + color,
    padding: '8px',
    margin: '0 6px 4px 0'
  });
  var desc = ui.Label(label, {fontSize: '11px', margin: '0 0 4px 0'});
  return ui.Panel([colorBox, desc], ui.Panel.Layout.Flow('horizontal'));
}

var previewState = {
  zoneId: DEFAULT_ZONE_ID,
  year: PREVIEW_YEAR,
  month: PREVIEW_MONTH,
  showBoundary: true,
  showLc: false,
  showExcluded: true,
  showUnion: true,
  showAnnualBurnable: false,
  showBurnMask: true,
  showBurnDate: false,
  showLegend: true
};

var PREVIEW_ZONE_ID_LIST_CLIENT = [
  'coastal_zone',
  'forest_zone',
  'transition_zone',
  'guinea_savannah',
  'sudan_savannah'
];

var PREVIEW_ZONE_LABEL_BY_ID = {
  coastal_zone: 'Coastal Zone (coastal_zone)',
  forest_zone: 'Forest Zone (forest_zone)',
  transition_zone: 'Transition Zone (transition_zone)',
  guinea_savannah: 'Guinea Savannah (guinea_savannah)',
  sudan_savannah: 'Sudan Savannah (sudan_savannah)'
};

var PREVIEW_ZONE_CODE_BY_ID = {
  coastal_zone: 'CZ',
  forest_zone: 'FZ',
  transition_zone: 'TZ',
  guinea_savannah: 'GS',
  sudan_savannah: 'SS'
};

// -----------------------------------------------------------------------------
// Human-readable label used by the zone selector and status text.
// -----------------------------------------------------------------------------
function previewZoneLabel(zoneId) {
  zoneId = String(zoneId || DEFAULT_ZONE_ID);
  return PREVIEW_ZONE_LABEL_BY_ID[zoneId] || (zoneId + ' (' + zoneId + ')');
}

var PREVIEW_ZONE_LABEL_TO_ID = {};
PREVIEW_ZONE_ID_LIST_CLIENT.forEach(function(zoneId) {
  PREVIEW_ZONE_LABEL_TO_ID[previewZoneLabel(zoneId)] = zoneId;
});

var zonePreviewContextCache = {};

// -----------------------------------------------------------------------------
// Builds the current preview/export geography for a selected canonical ACZ.
// This changes the active unit geography only; it does not alter the frozen c1
// analytical method.
// -----------------------------------------------------------------------------
function buildZonePreviewContext(zoneId) {
  zoneId = String(zoneId || DEFAULT_ZONE_ID);
  var zoneFc = STAGE1_ZONES_COMBINED.filter(ee.Filter.eq('zone_id', zoneId));
  var zoneGeomRaw = zoneFc.geometry();
  var zoneGeomLand = cleanGeom(zoneGeomRaw.intersection(GHANA_LAND, 1));
  var zoneMeta = ee.Dictionary(ZONE_BY_ID.get(zoneId));
  var zoneName = ee.String(zoneMeta.get('zone_name'));
  var zoneCode = ee.String(zoneMeta.get('zone_code'));

  return {
    zoneId: zoneId,
    zoneFc: zoneFc,
    zoneGeom: zoneGeomLand,
    zoneName: zoneName,
    zoneCode: zoneCode,
    boundaryImage: getZoneBoundaryImage(zoneFc, BOUNDARY_WIDTH).clip(zoneGeomLand),
    unionMask: BURN_UNION.clip(zoneGeomLand)
  };
}

// -----------------------------------------------------------------------------
// Returns a cached preview context for the currently selected ACZ so redraws
// remain responsive when only the year/month or layer toggles change.
// -----------------------------------------------------------------------------
function getZonePreviewContext(zoneId) {
  zoneId = String(zoneId || DEFAULT_ZONE_ID);
  if (!zonePreviewContextCache[zoneId]) {
    zonePreviewContextCache[zoneId] = buildZonePreviewContext(zoneId);
  }
  return zonePreviewContextCache[zoneId];
}

function getActiveZonePreviewContext() {
  return getZonePreviewContext(previewState.zoneId || DEFAULT_ZONE_ID);
}

// -----------------------------------------------------------------------------
// Preview-only helper for annual LC_Type1 display within the active selected ACZ.
// -----------------------------------------------------------------------------
function getLcPreviewImageForContext(year, ctx) {
  ctx = ctx || getActiveZonePreviewContext();
  return mcd12ImageForYearExact(year)
    .select(DENOM_BAND_LC_TYPE1)
    .clip(ctx.zoneGeom);
}

// -----------------------------------------------------------------------------
// Preview-only helper for the annual c1 excluded mask within the active ACZ.
// -----------------------------------------------------------------------------
function getExcludedPreviewImageForContext(year, ctx) {
  ctx = ctx || getActiveZonePreviewContext();
  return annualBaExcludedMaskForYear(year).clip(ctx.zoneGeom);
}

// -----------------------------------------------------------------------------
// Preview-only helper for the fixed union denominator within the active ACZ.
// -----------------------------------------------------------------------------
function getUnionPreviewImageForContext(ctx) {
  ctx = ctx || getActiveZonePreviewContext();
  return ctx.unionMask;
}

// -----------------------------------------------------------------------------
// Preview-only helper for the selected-year annual burnable denominator inside
// the active ACZ.
// -----------------------------------------------------------------------------
function getAnnualBurnablePreviewImageForContext(year, ctx) {
  ctx = ctx || getActiveZonePreviewContext();
  return annualBurnableMaskForYear(year).clip(ctx.zoneGeom);
}

// -----------------------------------------------------------------------------
// Preview-only helper for the monthly burned-area mask after union masking inside
// the active ACZ.
// -----------------------------------------------------------------------------
function getMonthlyBurnMaskPreviewImageForContext(year, month, ctx) {
  ctx = ctx || getActiveZonePreviewContext();
  var w = monthWindow(year, month);
  return monthlyBurnedMaskOr(w.start, w.end)
    .updateMask(ctx.unionMask)
    .clip(ctx.zoneGeom);
}

// -----------------------------------------------------------------------------
// Preview-only helper for the diagnostic monthly BurnDate max layer inside the
// active ACZ.
// -----------------------------------------------------------------------------
function getMonthlyBurnDatePreviewImageForContext(year, month, ctx) {
  ctx = ctx || getActiveZonePreviewContext();
  var w = monthWindow(year, month);
  return monthlyBurnDateMax(w.start, w.end)
    .updateMask(ctx.unionMask)
    .clip(ctx.zoneGeom);
}

var selectedZoneInfoLabel = ui.Label('', {
  fontSize: '11px',
  color: '#4a4a4a',
  margin: '0 0 6px 0',
  whiteSpace: 'pre'
});

var initialZoneContext = getActiveZonePreviewContext();

var boundaryLayer = ui.Map.Layer(initialZoneContext.boundaryImage, ZONE_BOUNDARY_VIS, 'Selected ACZ boundary', true, BOUNDARY_OPACITY);
var lcLayer = ui.Map.Layer(getLcPreviewImageForContext(previewState.year, initialZoneContext), LC_VIS, 'LC_Type1 preview', false, LC_OPACITY);
var excludedLayer = ui.Map.Layer(getExcludedPreviewImageForContext(previewState.year, initialZoneContext), EXCLUDED_VIS, 'Excluded by LW_OR_LC17', true, EXCLUDED_OPACITY);
var unionLayer = ui.Map.Layer(getUnionPreviewImageForContext(initialZoneContext), UNION_VIS, 'Union burnable denominator', true, UNION_OPACITY);
var annualBurnableLayer = ui.Map.Layer(getAnnualBurnablePreviewImageForContext(previewState.year, initialZoneContext), ANNUAL_BURNABLE_VIS, 'Annual burnable denominator', false, ANNUAL_OPACITY);
var burnMaskLayer = ui.Map.Layer(getMonthlyBurnMaskPreviewImageForContext(previewState.year, previewState.month, initialZoneContext), BURNMASK_VIS, 'Monthly BA mask', true, BA_OPACITY);
var burnDateLayer = ui.Map.Layer(getMonthlyBurnDatePreviewImageForContext(previewState.year, previewState.month, initialZoneContext), BURNDATE_VIS, 'Monthly BurnDate max', false, BA_OPACITY);

Map.layers().reset([boundaryLayer, lcLayer, excludedLayer, unionLayer, annualBurnableLayer, burnMaskLayer, burnDateLayer]);
Map.centerObject(initialZoneContext.zoneGeom, MAP_CENTER_ZOOM);
Map.setOptions('SATELLITE');


// Left-panel container for the light QA interface.
// This is intentionally compact and fixed-method: it supports verification, not exploration.
var controlPanel = ui.Panel({
  style: {
    position: 'top-left',
    width: '350px',
    maxHeight: '680px',
    padding: '0px',
    backgroundColor: 'rgba(255,255,255,0.96)',
    border: '1px solid #cfd8dc'
  }
});

var legendPanel = ui.Panel({
  style: {
    position: 'top-right',
    width: '360px',
    maxHeight: '520px',
    padding: '8px',
    backgroundColor: 'rgba(255,255,255,0.92)',
    border: '1px solid #cfd8dc'
  }
});

var summaryLabel = ui.Label('', {
  whiteSpace: 'pre',
  fontSize: '11px',
  margin: '8px 0 0 0'
});

// -----------------------------------------------------------------------------
// Rebuilds the top-right legend so it reflects the current fixed-method preview state.
// -----------------------------------------------------------------------------
function refreshLegend() {
  legendPanel.clear();
  if (!previewState.showLegend) {
    legendPanel.style().set('shown', false);
    return;
  }
  legendPanel.style().set('shown', true);
  legendPanel.add(ui.Label('Legend', {fontWeight: 'bold', fontSize: '13px', margin: '0 0 6px 0'}));
  legendPanel.add(ui.Label('Fixed baseline: ' + BA_MASK_MODE, {fontSize: '11px', margin: '0 0 4px 0'}));
  legendPanel.add(ui.Label('Rule: ' + BA_MASK_LAYER_LABEL, {fontSize: '11px', margin: '0 0 8px 0'}));

  legendPanel.add(ui.Label('Analysis layers', {fontWeight: 'bold', fontSize: '11px', margin: '0 0 4px 0'}));
  legendPanel.add(legendRow('ff0000', 'Selected ACZ boundary'));
  legendPanel.add(legendRow('2b83ba', 'Excluded by frozen LW_OR_LC17 mask'));
  legendPanel.add(legendRow('ffd92f', 'Union burnable denominator'));
  legendPanel.add(legendRow('1a9850', 'Selected-year annual burnable denominator'));
  legendPanel.add(legendRow('000000', 'Monthly burned-area mask'));

  legendPanel.add(ui.Label('LC_Type1 classes', {fontWeight: 'bold', fontSize: '11px', margin: '8px 0 4px 0'}));
  IGBP.forEach(function(d) {
    legendPanel.add(legendRow(d.color, String(d.value) + ' — ' + d.name));
  });
}

// -----------------------------------------------------------------------------
// Evaluates lightweight summary statistics for the current preview selections
// and writes them into the control-panel summary box.
// -----------------------------------------------------------------------------
function refreshSummary() {
  var ctx = getActiveZonePreviewContext();
  var selectedExcludedKm2 = areaMaskedKm2(getExcludedPreviewImageForContext(previewState.year, ctx), ctx.zoneGeom);
  var selectedAnnualBurnableKm2 = areaMaskedKm2(getAnnualBurnablePreviewImageForContext(previewState.year, ctx), ctx.zoneGeom);
  var monthlyBaKm2 = areaMaskedKm2(getMonthlyBurnMaskPreviewImageForContext(previewState.year, previewState.month, ctx), ctx.zoneGeom);
  var unionBurnableKm2 = areaMaskedKm2(ctx.unionMask, ctx.zoneGeom);

  ee.Dictionary({
    zone_id: ctx.zoneId,
    zone_name: ctx.zoneName,
    zone_code: ctx.zoneCode,
    year: previewState.year,
    month: previewState.month,
    union_burnable_km2: unionBurnableKm2,
    selected_excluded_km2: selectedExcludedKm2,
    selected_annual_burnable_km2: selectedAnnualBurnableKm2,
    monthly_ba_km2: monthlyBaKm2,
    months_count: ee.Number(MONTHS_ALL.length())
  }).evaluate(function(obj) {
    if (!obj) {
      summaryLabel.setValue('Unable to evaluate preview summary.');
      return;
    }
    selectedZoneInfoLabel.setValue(
      'Selected canonical ACZ: ' + previewZoneLabel(obj.zone_id) + '\n' +
      'Zone code: ' + obj.zone_code + '\n' +
      'Frozen method: ' + BA_MASK_MODE
    );
    summaryLabel.setValue(
      'Zone: ' + obj.zone_name + ' (' + obj.zone_code + ')\n' +
      'Zone ID: ' + obj.zone_id + '\n' +
      'Script release: ' + SCRIPT_RELEASE + '\n' +
      'Fixed BA mask: ' + BA_MASK_MODE + '\n' +
      'Preview month: ' + obj.year + '-' + pad2(obj.month) + '\n' +
      'Union burnable area (km²): ' + Number(obj.union_burnable_km2 || 0).toFixed(4) + '\n' +
      'Selected-year excluded area (km²): ' + Number(obj.selected_excluded_km2 || 0).toFixed(4) + '\n' +
      'Selected-year annual burnable (km²): ' + Number(obj.selected_annual_burnable_km2 || 0).toFixed(4) + '\n' +
      'Monthly BA area (km²): ' + Number(obj.monthly_ba_km2 || 0).toFixed(4) + '\n' +
      'Months in export window: ' + obj.months_count
    );
  });
}

// -----------------------------------------------------------------------------
// Central UI refresh function. Updates layer EE objects, visibility, legend, and summary
// when the year/month or checkbox state changes.
// -----------------------------------------------------------------------------
function refreshPreviewLayers() {
  var ctx = getActiveZonePreviewContext();

  boundaryLayer.setEeObject(ctx.boundaryImage);
  boundaryLayer.setShown(previewState.showBoundary);

  lcLayer.setEeObject(getLcPreviewImageForContext(previewState.year, ctx));
  lcLayer.setShown(previewState.showLc);
  lcLayer.setOpacity(LC_OPACITY);

  excludedLayer.setEeObject(getExcludedPreviewImageForContext(previewState.year, ctx));
  excludedLayer.setShown(previewState.showExcluded);
  excludedLayer.setOpacity(EXCLUDED_OPACITY);

  unionLayer.setEeObject(getUnionPreviewImageForContext(ctx));
  unionLayer.setShown(previewState.showUnion);
  unionLayer.setOpacity(UNION_OPACITY);

  annualBurnableLayer.setEeObject(getAnnualBurnablePreviewImageForContext(previewState.year, ctx));
  annualBurnableLayer.setShown(previewState.showAnnualBurnable);
  annualBurnableLayer.setOpacity(ANNUAL_OPACITY);

  burnMaskLayer.setEeObject(getMonthlyBurnMaskPreviewImageForContext(previewState.year, previewState.month, ctx));
  burnMaskLayer.setShown(previewState.showBurnMask);
  burnMaskLayer.setOpacity(BA_OPACITY);

  burnDateLayer.setEeObject(getMonthlyBurnDatePreviewImageForContext(previewState.year, previewState.month, ctx));
  burnDateLayer.setShown(previewState.showBurnDate);
  burnDateLayer.setOpacity(BA_OPACITY);

  refreshLegend();
  refreshSummary();
}

var zoneSelect = ui.Select({
  items: PREVIEW_ZONE_ID_LIST_CLIENT.map(function(zoneId) {
    return previewZoneLabel(zoneId);
  }),
  value: previewZoneLabel(previewState.zoneId),
  onChange: function(value) {
    previewState.zoneId = String(PREVIEW_ZONE_LABEL_TO_ID[value] || DEFAULT_ZONE_ID);
    var ctx = getActiveZonePreviewContext();
    Map.centerObject(ctx.zoneGeom, MAP_CENTER_ZOOM);
    refreshPreviewLayers();
  },
  style: {stretch: 'horizontal'}
});

var yearSelect = ui.Select({
  items: ee.List.sequence(DENOM_START_YEAR, DENOM_END_YEAR).getInfo().map(function(y) { return String(y); }),
  value: String(previewState.year),
  onChange: function(value) {
    previewState.year = Number(value);
    refreshPreviewLayers();
  },
  style: {stretch: 'horizontal'}
});

var monthItems = [];
for (var _m = 1; _m <= 12; _m++) monthItems.push(String(_m));
var monthSelect = ui.Select({
  items: monthItems,
  value: String(previewState.month),
  onChange: function(value) {
    previewState.month = Number(value);
    refreshPreviewLayers();
  },
  style: {stretch: 'horizontal'}
});

// -----------------------------------------------------------------------------
// Factory for preview-layer visibility toggles.
// -----------------------------------------------------------------------------
function layerCheckbox(label, key) {
  return ui.Checkbox({
    label: label,
    value: previewState[key],
    onChange: function(v) {
      previewState[key] = !!v;
      refreshPreviewLayers();
    }
  });
}

// -----------------------------------------------------------------------------
// Consistent small-section heading used throughout the left control panel.
// -----------------------------------------------------------------------------
function sectionTitle(text) {
  return ui.Label(text, {
    fontWeight: 'bold',
    fontSize: '11px',
    margin: '8px 0 4px 0',
    color: '#1f2d3d'
  });
}

// -----------------------------------------------------------------------------
// Creates a muted explanatory label for help/about content.
// -----------------------------------------------------------------------------
function subtleText(text) {
  return ui.Label(text, {
    fontSize: '11px',
    color: '#4a4a4a',
    margin: '0 0 6px 0'
  });
}

// -----------------------------------------------------------------------------
// Groups UI controls into visually distinct cards for readability.
// -----------------------------------------------------------------------------
function sectionCard(children) {
  return ui.Panel(children, null, {
    margin: '0 0 8px 0',
    padding: '8px',
    backgroundColor: '#f7f9fb',
    border: '1px solid #e2e8f0'
  });
}

// ============================ EXPORT SELECTORS ===============================

// Ordered selector lists used to keep the dedicated RP1 CSV schemas stable.
// RP1_BASE_SELECTORS is the lean merger-ready analytical extract. RP1_EXT_SELECTORS
// begins with the exact same base schema, then appends row-level diagnostics,
// QA flags, provenance, and implementation metadata.
var RP1_BASE_IDENTITY_COLS = [
  'run_id',
  'schema_version',
  'level',
  'unit_id',
  'unit_code',
  'unit_name',
  'parent_level',
  'parent_id',
  'parent_code',
  'parent_name',
  'yyyymm',
  'year',
  'month'
];

var RP1_BASE_ANALYTICAL_COLS = [
  'modis_ba_km2',
  'modis_burned_pixel_count',
  'modis_ba_any',
  'modis_burnable_km2_union',
  'modis_burnable_km2_annual',
  'modis_burned_frac_union',
  'modis_burned_frac_annual',
  'modis_aoi_area_land_km2',
  'modis_zero_union_den_flag',
  'modis_zero_annual_den_flag'
];

var RP1_EXT_EXTRA_COLS = [
  'annual_land_km2',
  'annual_land_pixel_count',
  'burnable_pixel_count_union',
  'burnable_pixel_count_annual',

  'aoi_area_km2',
  'aoi_outside_land_km2',
  'aoi_outside_land_frac',
  'outside_land_warn_flag',
  'records_joined_land',
  'records_outside_land',

  'canonical_binding_ok_flag',
  'canonical_binding_source',
  'canonical_binding_fallback_feature_count',
  'raw_zone_id',
  'raw_zone_name',
  'raw_zone_code',

  'small_den',

  'denom_year_target',
  'denom_year_used',
  'denom_year_fallback_flag',
  'denom_years_used_pipe',
  'denom_missing_years_count',
  'denom_missing_years_pipe',
  'annual_zero_den_years_count',
  'annual_zero_den_years_pipe',
  'annual_denom_years_used_pipe',

  'zero_local_but_national_ba',
  'partial_viirs_overlap_flag',
  'denom_km2_check',
  'denom_abs_diff_km2',
  'denom_rel_diff',
  'denom_drift_thresh_km2',
  'denom_drift_tol_abs_km2',
  'denom_drift_tol_rel_frac',
  'denom_drift_flag',
  'denom_annual_km2_check',
  'denom_annual_abs_diff_km2',
  'denom_annual_rel_diff',
  'denom_annual_drift_thresh_km2',
  'denom_annual_drift_flag',
  'denom_any_drift_flag',

  'impact_product_id',
  'impact_band_used_for_ba',
  'impact_bands_recognized_pipe',
  'denom_product_id',
  'denom_band_lc_type1',
  'denom_band_lw',
  'denom_exact_year_required_flag',
  'denom_union_role',
  'denom_annual_role',
  'src_modis_version',
  'src_landcover_version',

  'script_release',
  'script_lineage',
  'ba_mask_mode',
  'ba_mask_short_code',
  'ba_mask_layer_label',
  'ba_mask_keep_summary',
  'ba_mask_excluded_summary',
  'water_mask_definition',
  'lc_include_pipe',

  'reducer_type',
  'reducer_weighting',
  'reducer_scale_m',
  'reducer_tileScale',
  'reducer_maxPixels',
  'reduction_crs',
  'reduction_nominal_scale_m',

  'denominator_definition',
  'annual_denominator_definition',
  'annual_land_definition',
  'monthly_ba_definition',
  'date_window_method_note',

  'created_utc',
  'run_date',
  'start',
  'end_exclusive',
  'months_count'
];

var RP1_BASE_SELECTORS = RP1_BASE_IDENTITY_COLS.concat(RP1_BASE_ANALYTICAL_COLS);
var RP1_EXT_SELECTORS = RP1_BASE_SELECTORS.concat(RP1_EXT_EXTRA_COLS);

// Local aliases used by the export queue helpers below.
var MAIN_SELECTORS = RP1_BASE_SELECTORS;
var EXT_SELECTORS = RP1_EXT_SELECTORS;

// -----------------------------------------------------------------------------
// Original export helper path for row construction. In the final file this name
// JavaScript uses the final declaration of this function name; the active
// all-zones implementation is declared below.
// -----------------------------------------------------------------------------
function buildRowsForCanonicalZoneId(canonicalZoneId) {
  var unit = prepareSingleZoneUnit(canonicalZoneId);
  var zoneGeom = ee.Feature(unit).geometry();
  var zoneCode = ee.String(ee.Feature(unit).get('unit_code'));

  var annualDenomTable = buildAnnualDenominatorTable(zoneGeom);
  var annualZeroYearsPipe = ee.String(annualDenomTable.aggregate_array('year').iterate(function(y, acc) {
    y = ee.Number(y);
    var row = ee.Feature(annualDenomTable.filter(ee.Filter.eq('year', y)).first());
    var isZero = ee.Number(row.get('zero_annual_den_flag')).eq(1);
    return ee.String(acc).cat(ee.Algorithms.If(isZero, ee.Algorithms.If(ee.String(acc).length().gt(0), '|', '').cat(y.format('%d')), ''));
  }, ''));

  var annualUsedYearsPipe = ee.String(annualDenomTable.aggregate_array('denom_year_used').map(function(y) {
    return ee.Number(y).format('%d');
  }).join('|'));

  var annualZeroYearsCount = ee.Number(annualDenomTable.aggregate_sum('zero_annual_den_flag'));

  var denomYearsUsedPipe = ee.List.sequence(DENOM_START_YEAR, DENOM_END_YEAR).map(function(y) {
    return ee.Number(y).format('%d');
  }).join('|');

  var denomMissingYears = ee.List([]);
  var denomMissingYearsPipe = ee.String('');
  var denomMissingYearsCount = ee.Number(0);

  var driftCheck = unionDenominatorDriftCheck(zoneGeom, BURNABLE_MASK_UNION, BURNABLE_KM2_UNION);
  var denomKm2CheckOnce = ee.Number(driftCheck.get('km2_check'));
  var denomAbsDiffOnce = ee.Number(driftCheck.get('abs_diff_km2'));
  var denomRelDiffOnce = driftCheck.get('rel_diff');
  var denomDriftThreshKm2Once = ee.Number(driftCheck.get('drift_thresh_km2'));
  var denomDriftFlagOnce = ee.Number(driftCheck.get('drift_flag')).int();

  return ee.FeatureCollection(MONTHS_ALL.map(function(d) {
    d = ee.Date(d);
    var parts = dateParts(d);
    var monthYear = ee.Number(parts.get('year')).int();
    var monthYYYYMM = ee.Number(parts.get('yyyymm')).int();
    var start = ee.Date(parts.get('start'));
    var end = ee.Date(parts.get('end'));

    var burnMask = monthlyBurnMask(start, end);
    var baAreaImage = pixelAreaKm2Masked(burnMask);
    var baStats = ee.Dictionary(baAreaImage.addBands(ee.Image.constant(1).rename('ones').updateMask(burnMask)).reduceRegion({
      reducer: ee.Reducer.sum().repeat(2),
      geometry: zoneGeom,
      crs: IMPACT_CRS,
      scale: SCALE_BA,
      maxPixels: MAX_PIXELS,
      tileScale: TILE_SCALE
    }));

    var baKm2 = toNumber0(baStats.get('area_km2_sum'));
    var burnedPixelCount = toNumber0(baStats.get('ones_sum')).round();
    var baAny = ee.Number(baKm2.gt(0)).int();
    var burnableKm2Union = ee.Number(BURNABLE_KM2_UNION);
    var burnablePixelCountUnion = ee.Number(BURNABLE_PIXEL_COUNT_UNION);
    var zeroUnionDenFlag = ee.Number(ee.Algorithms.If(burnableKm2Union.eq(0), 1, 0)).int();
    var smallDen = ee.Number(ee.Algorithms.If(burnableKm2Union.lt(SMALL_DEN_KM2_THRESHOLD), 1, 0)).int();

    var burnedFracUnion = ee.Algorithms.If(
      burnableKm2Union.gt(0),
      baKm2.divide(burnableKm2Union),
      null
    );

    var annualRow = ee.Feature(annualDenomTable.filter(ee.Filter.eq('year', monthYear)).first());

    var annualLandKm2 = ee.Number(annualRow.get('annual_land_km2'));
    var annualLandPixelCount = ee.Number(annualRow.get('annual_land_pixel_count'));
    var burnableKm2Annual = ee.Number(annualRow.get('burnable_km2_annual'));
    var burnablePixelCountAnnual = ee.Number(annualRow.get('burnable_pixel_count_annual'));
    var zeroAnnualDenFlag = ee.Number(annualRow.get('zero_annual_den_flag')).int();
    var denomYearTarget = ee.Number(annualRow.get('denom_year_target')).int();
    var denomYearUsed = ee.Number(annualRow.get('denom_year_used')).int();
    var denomYearFallbackFlag = ee.Number(annualRow.get('denom_year_fallback_flag')).int();
    var denomAnnualKm2Check = ee.Number(annualRow.get('denom_annual_km2_check'));
    var denomAnnualAbsDiffKm2 = ee.Number(annualRow.get('denom_annual_abs_diff_km2'));
    var denomAnnualRelDiff = annualRow.get('denom_annual_rel_diff');
    var denomAnnualDriftThreshKm2 = ee.Number(annualRow.get('denom_annual_drift_thresh_km2'));
    var denomAnnualDriftFlag = ee.Number(annualRow.get('denom_annual_drift_flag')).int();

    var burnedFracAnnual = ee.Algorithms.If(
      burnableKm2Annual.gt(0),
      baKm2.divide(burnableKm2Annual),
      null
    );

    var denomAnyDriftFlag = ee.Number(denomDriftFlagOnce).max(ee.Number(denomAnnualDriftFlag)).int();
    var natBaKm2 = nationalBaKm2(start, end);
    var zeroLocalButNationalBa = ee.Number(ee.Algorithms.If(baKm2.eq(0).and(natBaKm2.gt(0)), 1, 0)).int();
    var partialViirsOverlapFlag = ee.Number(monthYYYYMM.eq(PARTIAL_VIIRS_OVERLAP_YYYYMM)).int();

    var runId = RUN_STAMP.cat('_').cat(LEVEL_VALUE).cat('_').cat(zoneCode).cat('_').cat(BA_MASK_SHORT_CODE);

    return ee.Feature(null, {
      run_id: runId,
      schema_version: unit.get('schema_version'),
      level: unit.get('level'),
      unit_id: unit.get('unit_id'),
      unit_code: unit.get('unit_code'),
      unit_name: unit.get('unit_name'),
      parent_level: unit.get('parent_level'),
      parent_id: unit.get('parent_id'),
      parent_code: unit.get('parent_code'),
      parent_name: unit.get('parent_name'),
      yyyymm: parts.get('yyyymm'),
      year: parts.get('year'),
      month: parts.get('month'),

      modis_ba_km2: baKm2,
      modis_burned_pixel_count: burnedPixelCount,
      modis_ba_any: baAny,
      modis_burnable_km2_union: burnableKm2Union,
      modis_burnable_km2_annual: burnableKm2Annual,
      modis_burned_frac_union: burnedFracUnion,
      modis_burned_frac_annual: burnedFracAnnual,
      modis_aoi_area_land_km2: unit.get('aoi_area_land_km2'),
      modis_zero_union_den_flag: zeroUnionDenFlag,
      modis_zero_annual_den_flag: zeroAnnualDenFlag,

      annual_land_km2: annualLandKm2,
      annual_land_pixel_count: annualLandPixelCount,
      burnable_pixel_count_union: burnablePixelCountUnion,
      burnable_pixel_count_annual: burnablePixelCountAnnual,

      aoi_area_km2: unit.get('aoi_area_km2'),
      aoi_outside_land_km2: unit.get('aoi_outside_land_km2'),
      aoi_outside_land_frac: unit.get('aoi_outside_land_frac'),
      outside_land_warn_flag: unit.get('outside_land_warn_flag'),
      records_joined_land: unit.get('records_joined_land'),
      records_outside_land: unit.get('records_outside_land'),

      canonical_binding_ok_flag: unit.get('canonical_binding_ok_flag'),
      canonical_binding_source: unit.get('canonical_binding_source'),
      canonical_binding_fallback_feature_count: unit.get('canonical_binding_fallback_feature_count'),
      raw_zone_id: unit.get('raw_zone_id'),
      raw_zone_name: unit.get('raw_zone_name'),
      raw_zone_code: unit.get('raw_zone_code'),

      small_den: smallDen,

      denom_year_target: denomYearTarget,
      denom_year_used: denomYearUsed,
      denom_year_fallback_flag: denomYearFallbackFlag,
      denom_years_used_pipe: denomYearsUsedPipe,
      denom_missing_years_count: denomMissingYearsCount,
      denom_missing_years_pipe: denomMissingYearsPipe,
      annual_zero_den_years_count: annualZeroYearsCount,
      annual_zero_den_years_pipe: annualZeroYearsPipe,
      annual_denom_years_used_pipe: annualUsedYearsPipe,

      zero_local_but_national_ba: zeroLocalButNationalBa,
      partial_viirs_overlap_flag: partialViirsOverlapFlag,
      denom_km2_check: denomKm2CheckOnce,
      denom_abs_diff_km2: denomAbsDiffOnce,
      denom_rel_diff: denomRelDiffOnce,
      denom_drift_thresh_km2: denomDriftThreshKm2Once,
      denom_drift_tol_abs_km2: DENOM_DRIFT_TOL_ABS_KM2,
      denom_drift_tol_rel_frac: DENOM_DRIFT_TOL_REL_FRAC,
      denom_drift_flag: denomDriftFlagOnce,
      denom_annual_km2_check: denomAnnualKm2Check,
      denom_annual_abs_diff_km2: denomAnnualAbsDiffKm2,
      denom_annual_rel_diff: denomAnnualRelDiff,
      denom_annual_drift_thresh_km2: denomAnnualDriftThreshKm2,
      denom_annual_drift_flag: denomAnnualDriftFlag,
      denom_any_drift_flag: denomAnyDriftFlag,

      impact_product_id: IMPACT_PRODUCT_ID,
      impact_band_used_for_ba: IMPACT_BAND_BURNDATE,
      impact_bands_recognized_pipe: IMPACT_BANDS_RECOGNIZED.join('|'),
      denom_product_id: DENOM_PRODUCT_ID,
      denom_band_lc_type1: DENOM_BAND_LC_TYPE1,
      denom_band_lw: DENOM_BAND_LW,
      denom_exact_year_required_flag: DENOM_EXACT_YEAR_REQUIRED_FLAG,
      denom_union_role: DENOM_UNION_ROLE,
      denom_annual_role: DENOM_ANNUAL_ROLE,
      src_modis_version: SRC_MODIS_VERSION,
      src_landcover_version: SRC_LC_VERSION,

      script_release: SCRIPT_RELEASE,
      script_lineage: SCRIPT_LINEAGE,
      ba_mask_mode: BA_MASK_MODE,
      ba_mask_short_code: BA_MASK_SHORT_CODE,
      ba_mask_layer_label: BA_MASK_LAYER_LABEL,
      ba_mask_keep_summary: BA_MASK_KEEP_SUMMARY,
      ba_mask_excluded_summary: BA_MASK_EXCLUDED_SUMMARY,
      water_mask_definition: WATER_MASK_DEFINITION,
      lc_include_pipe: LC_INCLUDE_TEXT,

      reducer_type: REDUCER_TYPE,
      reducer_weighting: REDUCER_WEIGHTING,
      reducer_scale_m: SCALE_BA,
      reducer_tileScale: TILE_SCALE,
      reducer_maxPixels: MAX_PIXELS,
      reduction_crs: IMPACT_CRS,
      reduction_nominal_scale_m: IMPACT_NOMINAL_SCALE_M,

      denominator_definition: DENOMINATOR_DEFINITION,
      annual_denominator_definition: ANNUAL_DENOMINATOR_DEFINITION,
      annual_land_definition: ANNUAL_LAND_DEFINITION,
      monthly_ba_definition: MONTHLY_BA_DEFINITION,
      date_window_method_note: DATE_WINDOW_METHOD_NOTE,

      created_utc: CREATED_ISO,
      run_date: RUN_DATE_ISO,
      start: START,
      end_exclusive: END,
      months_count: ee.Number(MONTHS_ALL.length())
    });
  }));
}

// -----------------------------------------------------------------------------
// Base all-zones merge helper declaration; the active declaration is defined below.
// -----------------------------------------------------------------------------
function buildAllZonesRows() {
  var merged = ee.FeatureCollection([]);
  CANONICAL_ZONE_ID_LIST_CLIENT.forEach(function(zoneId) {
    merged = merged.merge(buildRowsForCanonicalZoneId(zoneId));
  });
  return merged;
}

// -----------------------------------------------------------------------------
// Thin wrapper around Export.table.toDrive(...) to keep export calls consistent.
// -----------------------------------------------------------------------------
function queueCsvExport(collection, descriptionBase, fileNamePrefixBase, selectors) {
  Export.table.toDrive({
    collection: collection.select(selectors),
    description: descriptionBase,
    folder: EXPORT_FOLDER,
    fileNamePrefix: fileNamePrefixBase,
    fileFormat: 'CSV',
    selectors: selectors
  });
}

var exportStatusLabel = ui.Label(
  'Export panel ready. Click a button to queue CSV tasks in the Tasks tab.',
  {fontSize: '11px', color: '#333333', whiteSpace: 'pre', margin: '6px 0 0 0'}
);

// -----------------------------------------------------------------------------
// Queues the current-zone analytical and ext CSV exports.
// -----------------------------------------------------------------------------
function queueCurrentZoneExportBundle() {
  var zoneId = String(previewState.zoneId || DEFAULT_ZONE_ID);
  var zoneCodeSlugCurrent = (PREVIEW_ZONE_CODE_BY_ID[zoneId] || 'ACZ').replace(/[^A-Za-z0-9]+/g, '_');
  var currentMainFilePrefix = FILE_PREFIX + '_' + zoneCodeSlugCurrent + '_' + BA_MASK_SHORT_CODE + '_' + startYM + '_to_' + endYM;
  var currentExtFilePrefix  = currentMainFilePrefix + '_ext';
  var currentRows = filterToRp1ExportWindow(buildRowsForCanonicalZoneId(zoneId));

  queueCsvExport(currentRows, currentMainFilePrefix, currentMainFilePrefix, MAIN_SELECTORS);
  queueCsvExport(currentRows, currentExtFilePrefix, currentExtFilePrefix, EXT_SELECTORS);
  exportStatusLabel.setValue(
    'Queued current-zone CSV tasks for ' + previewZoneLabel(zoneId) + '.\n' +
    'Tasks created: 2 (main + ext).\n' +
    'Open the Tasks tab to Run them.'
  );
}

// -----------------------------------------------------------------------------
// Base all-zones export queue declaration; the active declaration is defined below.
// -----------------------------------------------------------------------------
function queueAllZonesExportBundle() {
  var allRows = filterToRp1ExportWindow(buildAllZonesRows());
  var allMainPrefix = FILE_PREFIX + '_ALL_ACZ_' + BA_MASK_SHORT_CODE + '_' + startYM + '_to_' + endYM;
  var allExtPrefix = allMainPrefix + '_ext';

  queueCsvExport(allRows, allMainPrefix, allMainPrefix, MAIN_SELECTORS);
  queueCsvExport(allRows, allExtPrefix, allExtPrefix, EXT_SELECTORS);
  exportStatusLabel.setValue(
    'Queued combined all-zones CSV tasks.\n' +
    'Tasks created: 2 (main + ext).\n' +
    'Open the Tasks tab to Run them.'
  );
}

var panelHeader = ui.Panel([
  ui.Label('RP1 ACZ c1 — fixed-method QA preview', {
    fontWeight: 'bold',
    fontSize: '13px',
    margin: '0 0 4px 0',
    color: '#14213d'
  }),
  ui.Label(
    'Clean analytical script with a frozen LW_OR_LC17 baseline. Use the viewer script for mask sensitivity comparison and richer exploratory controls.',
    {fontSize: '11px', color: '#4a4a4a', margin: '0'}
  )
], null, {
  padding: '10px 10px 8px 10px',
  backgroundColor: '#eef3f8',
  border: '0 0 1px 0 solid #d7e3ef'
});

var tabButtonStyle = {
  stretch: 'horizontal',
  margin: '0 4px 0 0',
  fontSize: '11px'
};

var controlsTabButton = ui.Button({label: 'Controls', style: tabButtonStyle});
var exportsTabButton = ui.Button({label: 'Exports', style: tabButtonStyle});
var aboutTabButton = ui.Button({label: 'About', style: {stretch: 'horizontal', margin: '0', fontSize: '11px'}});

var tabBar = ui.Panel([
  controlsTabButton,
  exportsTabButton,
  aboutTabButton
], ui.Panel.Layout.Flow('horizontal'), {
  padding: '8px 10px 6px 10px',
  backgroundColor: '#ffffff'
});

var controlsContentPanel = ui.Panel([], null, {padding: '0 10px 10px 10px'});
var exportsContentPanel = ui.Panel([], null, {padding: '0 10px 10px 10px'});
var aboutContentPanel = ui.Panel([], null, {padding: '0 10px 10px 10px'});

controlsContentPanel.add(sectionCard([
  ui.Label('Preview ACZ', {fontWeight: 'bold', fontSize: '11px'}),
  zoneSelect,
  selectedZoneInfoLabel,
  ui.Label('Preview year', {fontWeight: 'bold', fontSize: '11px'}),
  yearSelect,
  ui.Label('Preview month', {fontWeight: 'bold', fontSize: '11px', margin: '6px 0 0 0'}),
  monthSelect
]));

controlsContentPanel.add(sectionCard([
  sectionTitle('Layer visibility'),
  layerCheckbox('Boundary', 'showBoundary'),
  layerCheckbox('LC_Type1 preview', 'showLc'),
  layerCheckbox('Excluded mask', 'showExcluded'),
  layerCheckbox('Union burnable', 'showUnion'),
  layerCheckbox('Annual burnable', 'showAnnualBurnable'),
  layerCheckbox('Monthly BA mask', 'showBurnMask'),
  layerCheckbox('Monthly BurnDate max', 'showBurnDate'),
  layerCheckbox('Legend', 'showLegend')
]));

controlsContentPanel.add(sectionCard([
  sectionTitle('Current preview summary'),
  summaryLabel
]));

exportsContentPanel.add(sectionCard([
  sectionTitle('CSV exports'),
  subtleText('Queue export tasks for the currently selected canonical ACZ or for one combined all-zones panel under the same frozen c1 method.')
]));

if (ENABLE_EXPORTS) {
  exportsContentPanel.add(sectionCard([
    ui.Button({
      label: 'Queue current zone CSV exports',
      onClick: queueCurrentZoneExportBundle,
      style: {stretch: 'horizontal', margin: '0 0 6px 0'}
    }),
    ui.Button({
      label: 'Queue all zones CSV exports',
      onClick: queueAllZonesExportBundle,
      style: {stretch: 'horizontal', margin: '0 0 4px 0'}
    }),
    exportStatusLabel
  ]));
} else {
  exportsContentPanel.add(sectionCard([
    subtleText('Exports are disabled because ENABLE_EXPORTS = false.'),
    exportStatusLabel
  ]));
  print('Export panel disabled because ENABLE_EXPORTS = false.');
}

aboutContentPanel.add(sectionCard([
  sectionTitle('Method lock'),
  subtleText('Numerator: monthly MCD64A1 BurnDate > 0, collapsed by OR/max across all images overlapping the month.'),
  subtleText('Baseline mask: keep only LW == 2 and LC_Type1 != 17 (LW_OR_LC17).'),
  subtleText('Denominator policy: exact MCD12Q1 year required; no nearest-year fallback.')
]));
aboutContentPanel.add(sectionCard([
  sectionTitle('UI behaviour'),
  subtleText('This left panel now uses tabs so controls remain accessible on smaller screens. The panel is also given a constrained height for better usability.'),
  subtleText('The Preview ACZ dropdown changes the current working geography for map QA and current-zone exports, but it does not change the frozen analytical method.'),
  subtleText('The legend remains in the top-right and can be toggled on/off from the Controls tab.')
]));

var contentStack = ui.Panel([
  controlsContentPanel,
  exportsContentPanel,
  aboutContentPanel
], null, {
  padding: '0',
  backgroundColor: '#ffffff'
});

// -----------------------------------------------------------------------------
// Applies simple active/inactive styling to the left-panel tab buttons.
// -----------------------------------------------------------------------------
function setTabButtonActive(button, isActive) {
  button.style().set('backgroundColor', isActive ? '#dceeff' : '#f4f6f8');
  button.style().set('fontWeight', isActive ? 'bold' : 'normal');
  button.style().set('color', isActive ? '#0b5394' : '#333333');
}

// -----------------------------------------------------------------------------
// Shows the requested tab content and hides the others.
// -----------------------------------------------------------------------------
function setActiveTab(tabName) {
  controlsContentPanel.style().set('shown', tabName === 'controls');
  exportsContentPanel.style().set('shown', tabName === 'exports');
  aboutContentPanel.style().set('shown', tabName === 'about');
  setTabButtonActive(controlsTabButton, tabName === 'controls');
  setTabButtonActive(exportsTabButton, tabName === 'exports');
  setTabButtonActive(aboutTabButton, tabName === 'about');
}

controlsTabButton.onClick(function() { setActiveTab('controls'); });
exportsTabButton.onClick(function() { setActiveTab('exports'); });
aboutTabButton.onClick(function() { setActiveTab('about'); });

controlPanel.add(panelHeader);
controlPanel.add(tabBar);
controlPanel.add(contentStack);
setActiveTab('controls');

Map.add(controlPanel);
Map.add(legendPanel);
refreshPreviewLayers();

// ============================== EXPORT NAMING ================================

var startYM = RP1_EXPORT_START_LABEL;
var endYM = RP1_EXPORT_END_LABEL;
var aczCodeSlug = (function() {
  try { return (CANONICAL_ZONE_CODE.getInfo() || 'ACZ'); }
  catch (e) { return 'ACZ_' + RUN_STAMP_STR; }
})();
aczCodeSlug = (aczCodeSlug + '').replace(/[^A-Za-z0-9]+/g, '_');

var mainFilePrefix = FILE_PREFIX + '_' + aczCodeSlug + '_' + BA_MASK_SHORT_CODE + '_' + startYM + '_to_' + endYM;
var extFilePrefix  = mainFilePrefix + '_ext';


// ================================= EXPORTS ==================================

// Export tasks are intentionally queued from the UI export panel so the operator
// can choose between the current zone and a combined all-zones export bundle.
// This avoids auto-populating the Tasks tab on every script load.
if (!ENABLE_EXPORTS) {
  print('Export panel disabled because ENABLE_EXPORTS = false.');
}


// ====================== ALL-ZONES EXPORT IMPLEMENTATION ======================
// The combined all-zones export uses the same frozen c1 analytical method as
// the current-zone path. It constructs each canonical ACZ row with complete
// helper definitions and deterministic export ordering.
//
// Scientific method:
// - numerator: monthly MCD64A1 BurnDate > 0, collapsed within month by OR/max
// - denominator: MCD12Q1 annual burnable support
// - baseline water exclusion: LW != 2 OR LC_Type1 == 17
// - union denominator window: 2012..2024 exact years only
// - no denominator fallback

// Canonical Stage 1 ACZ list used for the combined export helper. This is a
// client-side list on purpose because the button callback is triggered from the
// Code Editor UI and needs a deterministic export ordering.
var CANONICAL_ZONE_ID_LIST_CLIENT = [
  'coastal_zone',
  'forest_zone',
  'transition_zone',
  'guinea_savannah',
  'sudan_savannah'
];

// -----------------------------------------------------------------------------
// Helper: pull exactly one canonical ACZ subset from the combined Stage 1 source.
// -----------------------------------------------------------------------------
function getCanonicalZoneFeatureCollection(canonicalZoneId) {
  canonicalZoneId = ee.String(canonicalZoneId);
  return STAGE1_ZONES_COMBINED.filter(ee.Filter.eq('zone_id', canonicalZoneId));
}

// -----------------------------------------------------------------------------
// Helper: build a clean single-zone unit feature for the combined all-zones export path,
// including the same area and provenance diagnostics used by the current-zone workflow.
// -----------------------------------------------------------------------------
function prepareSingleZoneUnit(canonicalZoneId) {
  canonicalZoneId = ee.String(canonicalZoneId);

  var zoneFc = getCanonicalZoneFeatureCollection(canonicalZoneId);
  var zoneGeomRaw = zoneFc.geometry();
  var zoneGeomLand = cleanGeom(zoneGeomRaw.intersection(GHANA_LAND, 1));

  var zoneMeta = ee.Dictionary(ZONE_BY_ID.get(canonicalZoneId));
  var zoneName = ee.String(zoneMeta.get('zone_name'));
  var zoneCode = ee.String(zoneMeta.get('zone_code'));

  var rawAreaKm2 = ee.Number(zoneGeomRaw.area({maxError: 1})).divide(1e6);
  var landAreaKm2 = ee.Number(zoneGeomLand.area({maxError: 1})).divide(1e6);
  var outsideLandKm2 = ee.Number(ee.Algorithms.If(
    rawAreaKm2.gt(0),
    rawAreaKm2.subtract(landAreaKm2).max(0),
    0
  ));
  var outsideLandFrac = safeFrac(outsideLandKm2, rawAreaKm2);
  var outsideLandWarnFlag = ee.Number(ee.Algorithms.If(
    rawAreaKm2.gt(0).and(safeGt(outsideLandFrac, OUTSIDE_LAND_WARN_FRAC).eq(1)),
    1,
    0
  )).int();
  var recordsOutsideLand = landAreaKm2.lte(0).int();
  var recordsJoinedLand = recordsOutsideLand.eq(0).int();

  return ee.Feature(zoneGeomLand, {
    schema_version: RP1_SCHEMA_VERSION,
    level: LEVEL_VALUE,
    unit_id: canonicalZoneId,
    unit_code: zoneCode,
    unit_name: zoneName,
    parent_level: '',
    parent_id: '',
    parent_code: '',
    parent_name: '',

    aoi_area_km2: rawAreaKm2,
    aoi_area_land_km2: landAreaKm2,
    aoi_outside_land_km2: outsideLandKm2,
    aoi_outside_land_frac: outsideLandFrac,
    outside_land_warn_flag: outsideLandWarnFlag,
    records_joined_land: recordsJoinedLand,
    records_outside_land: recordsOutsideLand,

    canonical_binding_ok_flag: 1,
    canonical_binding_source: 'zone_id',
    canonical_binding_fallback_feature_count: 0,
    raw_zone_id: canonicalZoneId,
    raw_zone_name: zoneName,
    raw_zone_code: zoneCode
  });
}

// -----------------------------------------------------------------------------
// Helper: compute an annual denominator table for an arbitrary zone geometry
// so the all-zones export path can reproduce the same c1 method zone by zone.
// -----------------------------------------------------------------------------
function buildAnnualDenominatorTable(zoneGeom) {
  zoneGeom = ee.Geometry(zoneGeom);
  return ee.FeatureCollection(TARGET_YEARS.map(function(y) {
    y = ee.Number(y).int();

    var annualLand = annualLandMaskForYear(y).clip(zoneGeom);
    var annualBurnable = annualBurnableMaskForYear(y).clip(zoneGeom);

    var annual_land_km2 = areaMaskedKm2(annualLand, zoneGeom);
    var annual_land_pixel_count = pixelCount(annualLand, zoneGeom);
    var burnable_km2_annual = areaMaskedKm2(annualBurnable, zoneGeom);
    var burnable_pixel_count_annual = pixelCount(annualBurnable, zoneGeom);
    var zero_annual_den_flag = burnable_km2_annual.lte(0).int();

    var denom_annual_km2_check = areaMaskedKm2Audit(annualBurnable, zoneGeom);
    var annualAudit = driftAudit(burnable_km2_annual, denom_annual_km2_check);

    return ee.Feature(null, {
      year: y,
      denom_year_target: y,
      denom_year_used: y,
      denom_year_fallback_flag: 0,
      annual_land_km2: annual_land_km2,
      annual_land_pixel_count: annual_land_pixel_count,
      burnable_km2_annual: burnable_km2_annual,
      burnable_pixel_count_annual: burnable_pixel_count_annual,
      zero_annual_den_flag: zero_annual_den_flag,
      denom_annual_km2_check: denom_annual_km2_check,
      denom_annual_abs_diff_km2: ee.Number(annualAudit.get('abs_diff_km2')),
      denom_annual_rel_diff: annualAudit.get('rel_diff'),
      denom_annual_drift_thresh_km2: ee.Number(annualAudit.get('thresh_km2')),
      denom_annual_drift_flag: ee.Number(annualAudit.get('flag')).int()
    });
  }));
}

// -----------------------------------------------------------------------------
// Helper: perform the zone-specific union-denominator audit for the all-zones path.
// -----------------------------------------------------------------------------
function unionDenominatorDriftCheck(zoneGeom, unionMask, reportedKm2) {
  var km2Check = areaMaskedKm2Audit(unionMask, zoneGeom);
  var audit = driftAudit(reportedKm2, km2Check);
  return ee.Dictionary({
    km2_check: km2Check,
    abs_diff_km2: ee.Number(audit.get('abs_diff_km2')),
    rel_diff: audit.get('rel_diff'),
    drift_thresh_km2: ee.Number(audit.get('thresh_km2')),
    drift_flag: ee.Number(audit.get('flag')).int()
  });
}

// -----------------------------------------------------------------------------
// Alias used by the all-zones helper path; it intentionally points to
// to the same monthly burned-mask definition used elsewhere.
// -----------------------------------------------------------------------------
function monthlyBurnMask(start, end) {
  return monthlyBurnedMaskOr(start, end);
}

var BURNABLE_MASK_UNION = BURN_UNION;

// -----------------------------------------------------------------------------
// Active all-zones helper used by the export workflow.
// This is the operative version used for the combined all-zones export bundle.
// -----------------------------------------------------------------------------
function buildRowsForCanonicalZoneId(canonicalZoneId) {
  canonicalZoneId = ee.String(canonicalZoneId);

  var unit = prepareSingleZoneUnit(canonicalZoneId);
  var zoneGeom = ee.Feature(unit).geometry();

  var burnableKm2Union = areaMaskedKm2(BURNABLE_MASK_UNION, zoneGeom);
  var burnablePixelCountUnion = pixelCount(BURNABLE_MASK_UNION, zoneGeom);
  var zeroUnionDenFlag = burnableKm2Union.lte(0).int();
  var smallDen = burnableKm2Union.lt(SMALL_DEN_THRESHOLD_KM2).int();

  var annualDenomTable = buildAnnualDenominatorTable(zoneGeom);
  var annualZeroYears = annualDenomTable
    .filter(ee.Filter.eq('zero_annual_den_flag', 1))
    .aggregate_array('year');
  var annualZeroYearsCount = ee.Number(ee.List(annualZeroYears).length());
  var annualZeroYearsPipe = ee.List(annualZeroYears)
    .map(function(v) { return ee.Number(v).format('%d'); })
    .join('|');
  var annualUsedYearsPipe = ee.List(annualDenomTable.aggregate_array('denom_year_used'))
    .map(function(v) { return ee.Number(v).format('%d'); })
    .join('|');

  var denomYearsUsedPipe = ee.List(TARGET_YEARS)
    .map(function(y) { return ee.Number(y).format('%d'); })
    .join('|');
  var denomMissingYearsCount = denom_missing_years_count;
  var denomMissingYearsPipe = denom_missing_years_pipe;

  var driftCheck = unionDenominatorDriftCheck(zoneGeom, BURNABLE_MASK_UNION, burnableKm2Union);
  var denomKm2CheckOnce = ee.Number(driftCheck.get('km2_check'));
  var denomAbsDiffOnce = ee.Number(driftCheck.get('abs_diff_km2'));
  var denomRelDiffOnce = driftCheck.get('rel_diff');
  var denomDriftThreshKm2Once = ee.Number(driftCheck.get('drift_thresh_km2'));
  var denomDriftFlagOnce = ee.Number(driftCheck.get('drift_flag')).int();

  return ee.FeatureCollection(MONTHS_ALL.map(function(md) {
    md = ee.Dictionary(md);
    var start = ee.Date(md.get('start'));
    var end = ee.Date(md.get('end'));
    var parts = dateParts(start);
    var monthYear = ee.Number(parts.get('year')).int();
    var monthYYYYMM = ee.Number(parts.get('yyyymm')).int();

    var burnMask = monthlyBurnMask(start, end)
      .updateMask(BURNABLE_MASK_UNION)
      .clip(zoneGeom);
    var ba_km2 = areaMaskedKm2(burnMask, zoneGeom);
    var burned_pixel_count = pixelCount(burnMask, zoneGeom);
    var ba_any = ba_km2.gt(0).int();

    var burned_frac_union = ee.Algorithms.If(
      burnableKm2Union.gt(0),
      ba_km2.divide(burnableKm2Union),
      null
    );

    var annualRow = ee.Feature(annualDenomTable.filter(ee.Filter.eq('year', monthYear)).first());
    var annual_land_km2 = ee.Number(annualRow.get('annual_land_km2'));
    var annual_land_pixel_count = ee.Number(annualRow.get('annual_land_pixel_count'));
    var burnable_km2_annual = ee.Number(annualRow.get('burnable_km2_annual'));
    var burnable_pixel_count_annual = ee.Number(annualRow.get('burnable_pixel_count_annual'));
    var zero_annual_den_flag = ee.Number(annualRow.get('zero_annual_den_flag')).int();
    var denom_year_target = ee.Number(annualRow.get('denom_year_target')).int();
    var denom_year_used = ee.Number(annualRow.get('denom_year_used')).int();
    var denom_year_fallback_flag = ee.Number(annualRow.get('denom_year_fallback_flag')).int();
    var denom_annual_km2_check = ee.Number(annualRow.get('denom_annual_km2_check'));
    var denom_annual_abs_diff_km2 = ee.Number(annualRow.get('denom_annual_abs_diff_km2'));
    var denom_annual_rel_diff = annualRow.get('denom_annual_rel_diff');
    var denom_annual_drift_thresh_km2 = ee.Number(annualRow.get('denom_annual_drift_thresh_km2'));
    var denom_annual_drift_flag = ee.Number(annualRow.get('denom_annual_drift_flag')).int();

    var burned_frac_annual = ee.Algorithms.If(
      burnable_km2_annual.gt(0),
      ba_km2.divide(burnable_km2_annual),
      null
    );

    var denom_any_drift_flag = ee.Number(denomDriftFlagOnce)
      .max(ee.Number(denom_annual_drift_flag))
      .int();
    var nat_ba_km2 = nationalBaKm2(start, end);
    var zero_local_but_national_ba = ee.Number(
      ee.Algorithms.If(ba_km2.eq(0).and(nat_ba_km2.gt(0)), 1, 0)
    ).int();
    var partial_viirs_overlap_flag = ee.Number(monthYYYYMM.eq(PARTIAL_VIIRS_OVERLAP_YYYYMM)).int();

    var runId = RUN_STAMP.cat('_').cat(LEVEL_VALUE).cat('_')
      .cat(ee.String(unit.get('unit_code'))).cat('_').cat(BA_MASK_SHORT_CODE);

    return ee.Feature(null, {
      run_id: runId,
      schema_version: unit.get('schema_version'),
      level: unit.get('level'),
      unit_id: unit.get('unit_id'),
      unit_code: unit.get('unit_code'),
      unit_name: unit.get('unit_name'),
      parent_level: unit.get('parent_level'),
      parent_id: unit.get('parent_id'),
      parent_code: unit.get('parent_code'),
      parent_name: unit.get('parent_name'),
      yyyymm: parts.get('yyyymm'),
      year: parts.get('year'),
      month: parts.get('month'),

      modis_ba_km2: ba_km2,
      modis_burned_pixel_count: burned_pixel_count,
      modis_ba_any: ba_any,
      modis_burnable_km2_union: burnableKm2Union,
      modis_burnable_km2_annual: burnable_km2_annual,
      modis_burned_frac_union: burned_frac_union,
      modis_burned_frac_annual: burned_frac_annual,
      modis_aoi_area_land_km2: unit.get('aoi_area_land_km2'),
      modis_zero_union_den_flag: zeroUnionDenFlag,
      modis_zero_annual_den_flag: zero_annual_den_flag,

      annual_land_km2: annual_land_km2,
      annual_land_pixel_count: annual_land_pixel_count,
      burnable_pixel_count_union: burnablePixelCountUnion,
      burnable_pixel_count_annual: burnable_pixel_count_annual,

      aoi_area_km2: unit.get('aoi_area_km2'),
      aoi_outside_land_km2: unit.get('aoi_outside_land_km2'),
      aoi_outside_land_frac: unit.get('aoi_outside_land_frac'),
      outside_land_warn_flag: unit.get('outside_land_warn_flag'),
      records_joined_land: unit.get('records_joined_land'),
      records_outside_land: unit.get('records_outside_land'),

      canonical_binding_ok_flag: unit.get('canonical_binding_ok_flag'),
      canonical_binding_source: unit.get('canonical_binding_source'),
      canonical_binding_fallback_feature_count: unit.get('canonical_binding_fallback_feature_count'),
      raw_zone_id: unit.get('raw_zone_id'),
      raw_zone_name: unit.get('raw_zone_name'),
      raw_zone_code: unit.get('raw_zone_code'),

      small_den: smallDen,

      denom_year_target: denom_year_target,
      denom_year_used: denom_year_used,
      denom_year_fallback_flag: denom_year_fallback_flag,
      denom_years_used_pipe: denomYearsUsedPipe,
      denom_missing_years_count: denomMissingYearsCount,
      denom_missing_years_pipe: denomMissingYearsPipe,
      annual_zero_den_years_count: annualZeroYearsCount,
      annual_zero_den_years_pipe: annualZeroYearsPipe,
      annual_denom_years_used_pipe: annualUsedYearsPipe,

      zero_local_but_national_ba: zero_local_but_national_ba,
      partial_viirs_overlap_flag: partial_viirs_overlap_flag,
      denom_km2_check: denomKm2CheckOnce,
      denom_abs_diff_km2: denomAbsDiffOnce,
      denom_rel_diff: denomRelDiffOnce,
      denom_drift_thresh_km2: denomDriftThreshKm2Once,
      denom_drift_tol_abs_km2: DENOM_DRIFT_TOL_ABS_KM2,
      denom_drift_tol_rel_frac: DENOM_DRIFT_TOL_REL_FRAC,
      denom_drift_flag: denomDriftFlagOnce,
      denom_annual_km2_check: denom_annual_km2_check,
      denom_annual_abs_diff_km2: denom_annual_abs_diff_km2,
      denom_annual_rel_diff: denom_annual_rel_diff,
      denom_annual_drift_thresh_km2: denom_annual_drift_thresh_km2,
      denom_annual_drift_flag: denom_annual_drift_flag,
      denom_any_drift_flag: denom_any_drift_flag,

      impact_product_id: IMPACT_PRODUCT_ID,
      impact_band_used_for_ba: IMPACT_BAND_BURNDATE,
      impact_bands_recognized_pipe: IMPACT_BANDS_RECOGNIZED.join('|'),
      denom_product_id: DENOM_PRODUCT_ID,
      denom_band_lc_type1: DENOM_BAND_LC_TYPE1,
      denom_band_lw: DENOM_BAND_LW,
      denom_exact_year_required_flag: DENOM_EXACT_YEAR_REQUIRED_FLAG,
      denom_union_role: DENOM_UNION_ROLE,
      denom_annual_role: DENOM_ANNUAL_ROLE,
      src_modis_version: SRC_MODIS_VERSION,
      src_landcover_version: SRC_LC_VERSION,

      script_release: SCRIPT_RELEASE,
      script_lineage: SCRIPT_LINEAGE,
      ba_mask_mode: BA_MASK_MODE,
      ba_mask_short_code: BA_MASK_SHORT_CODE,
      ba_mask_layer_label: BA_MASK_LAYER_LABEL,
      ba_mask_keep_summary: BA_MASK_KEEP_SUMMARY,
      ba_mask_excluded_summary: BA_MASK_EXCLUDED_SUMMARY,
      water_mask_definition: WATER_MASK_DEFINITION,
      lc_include_pipe: LC_INCLUDE_TEXT,

      reducer_type: REDUCER_TYPE,
      reducer_weighting: REDUCER_WEIGHTING,
      reducer_scale_m: SCALE_BA,
      reducer_tileScale: TILE_SCALE,
      reducer_maxPixels: MAX_PIXELS,
      reduction_crs: IMPACT_CRS,
      reduction_nominal_scale_m: IMPACT_NOMINAL_SCALE_M,

      denominator_definition: DENOMINATOR_DEFINITION,
      annual_denominator_definition: ANNUAL_DENOMINATOR_DEFINITION,
      annual_land_definition: ANNUAL_LAND_DEFINITION,
      monthly_ba_definition: MONTHLY_BA_DEFINITION,
      date_window_method_note: DATE_WINDOW_METHOD_NOTE,

      created_utc: CREATED_ISO,
      run_date: RUN_DATE_ISO,
      start: START,
      end_exclusive: END,
      months_count: ee.Number(MONTHS_ALL.length())
    });
  }));
}

// -----------------------------------------------------------------------------
// Active all-zones merge helper;
// is used by the final all-zones export button.
// -----------------------------------------------------------------------------
function buildAllZonesRows() {
  var merged = ee.FeatureCollection([]);
  CANONICAL_ZONE_ID_LIST_CLIENT.forEach(function(zoneId) {
    merged = merged.merge(buildRowsForCanonicalZoneId(zoneId));
  });
  return merged;
}

// -----------------------------------------------------------------------------
// Active export queue helper used by the UI button.
// It advertises the included canonical ACZ list and uses the all-zones builder.
// -----------------------------------------------------------------------------
function queueAllZonesExportBundle() {
  var allRows = filterToRp1ExportWindow(buildAllZonesRows());
  var allMainPrefix = FILE_PREFIX + '_ALL_ACZ_' + BA_MASK_SHORT_CODE + '_' + startYM + '_to_' + endYM;
  var allExtPrefix = allMainPrefix + '_ext';

  queueCsvExport(allRows, allMainPrefix, allMainPrefix, MAIN_SELECTORS);
  queueCsvExport(allRows, allExtPrefix, allExtPrefix, EXT_SELECTORS);

  exportStatusLabel.setValue(
    'Queued combined all-zones CSV tasks under the frozen c1 method.\n' +
    'Tasks created: 2 (main + ext).\n' +
    'Included ACZs: ' + CANONICAL_ZONE_ID_LIST_CLIENT.join(', ') + '\n' +
    'Open the Tasks tab to Run them.'
  );
}