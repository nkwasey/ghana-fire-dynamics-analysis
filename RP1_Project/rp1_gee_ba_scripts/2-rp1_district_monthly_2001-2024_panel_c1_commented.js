// =============================================================================
// RP1 — Canonical District Monthly Burned-Area Panel (c1 clean baseline)
// Google Earth Engine (JavaScript API)
//
// OVERVIEW
// --------
// This script is the first clean, analysis-ready DISTRICT extractor for the RP1
// MODIS burned-area workflow in Ghana. It produces a tidy, publication-ready
// MONTHLY burned-area panel for districts nested within a selected canonical
// Stage 1 Agro-Climatic Zone (ACZ). Internally, the analytical backbone still
// spans the overlap-era window January 2001 through December 2024 (START
// inclusive; END exclusive) so the fixed UNION denominator and exact-year
// annual denominators remain unchanged. The dedicated RP1 export family is
// then clipped to January 2001 through December 2024 so downstream BA/AF
// merger-ready panels share one aligned monthly window.
//
// The burned-area numerator is derived from MODIS MCD64A1 Collection 6.1
// BurnDate and is defined per month as the pixel-wise OR across all MCD64A1
// images overlapping that month (burned = BurnDate > 0 in any overlapping
// month image).
//
// Burned area (ba_km2) is computed as the summed per-pixel surface area (km²)
// of burned pixels within each district after:
//   (i) enforcing LAND-ONLY district geometries (district geometry intersected
//       with the canonical Ghana land-only boundary),
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
// denominator table for 2001–2024 and carries the relevant annual fields onto
// monthly rows. Explicit denominator QA, drift, provenance, exclusion, and
// identifier fields are exported to support defensibility and reproducibility.
//
// WHAT MAKES c1 THE CLEAN BASELINE
// --------------------------------
// This script deliberately combines:
//   • the stricter analytical backbone of the v3 district extractor; and
//   • the fixed LW_OR_LC17 permanent-water union chosen after the v4
//     sensitivity review.
//
// The analytical method is fixed in this script. It does NOT expose run-time
// analytical mask switching. Exploratory mask comparison belongs in the
// dedicated viewer script.
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
//   2001–2024. Nearest-year fallback is not allowed anywhere in this script.
//
// • EXPLICIT NUMERATOR MASK ORDER (export definition):
//     (1) monthly burned-any mask (OR across overlapping images),
//     (2) fixed UNION burnable denominator under the frozen c1 rule.
//   Annual excluded and annual burnable masks are still computed and retained
//   for QA and interpretation, but the primary numerator uses the fixed UNION
//   denominator.
//
// WHAT THIS SCRIPT DOES (STEP-BY-STEP)
// ------------------------------------
// 1) INPUT DISTRICT GEOGRAPHY (DISTRICTS WITHIN ONE CANONICAL ACZ)
//    • Reads Stage 1 district FeatureCollections, either from:
//        – one combined national districts-within-ACZ asset filtered by
//          canonical zone_id, or
//        – one zone-specific district asset per ACZ.
//    • The selected ACZ controls which district universe is prepared and
//      exported.
//    • The district selected in the UI is a preview/highlight aid only; exports
//      remain ACZ-scoped district bundles.
//
// 2) GEOMETRY HYGIENE + LAND-ONLY ENFORCEMENT
//    • Repairs district geometries using buffer(0, 1) style cleaning.
//    • Intersects each district with the canonical Ghana land-only boundary so
//      all reductions are performed on land-only geometry.
//    • Computes district-level geometry diagnostics including:
//        – raw area,
//        – land-only area,
//        – outside-land area / fraction,
//        – outside-land warning flag,
//        – records_joined_land / records_outside_land.
//
// 3) STABLE UNIT IDENTIFIERS (DISTRICT + PARENT ACZ; LOCKED OUTPUT CONTRACT)
//    • Resolves district identifiers from prioritised Stage 1 district fields,
//      including:
//        – unit_id   = canonical dist_id
//        – unit_name = canonical dist_name
//    • Resolves parent ACZ identity canonically from zone_id / zone_name /
//      zone_code fields.
//    • Final exported identifiers are locked to:
//        – schema_version = explicit RP1 export-schema tag
//        – level          = configured district-level label ("district")
//        – unit_id        = canonical Stage 1 dist_id
//        – unit_code      = best available district code field if present;
//                           otherwise blank by design (the example Stage 1
//                           unit_universe carries blank district unit_code)
//        – unit_name      = canonical Stage 1 dist_name
//        – parent_level   = configured parent zone-level label ("acz")
//        – parent_id      = canonical Stage 1 zone_id
//        – parent_code    = canonical Stage 1 zone_code
//        – parent_name    = canonical Stage 1 zone_name
//
// 4) STRICT DISTRICT PREPARATION + EXCLUSION LOGGING
//    • Districts are prepared under strict rules before entering the analytical
//      export stream.
//    • Any district is excluded from the main analytical exports if it has:
//        – zero land intersection,
//        – unresolved canonical district identity, or
//        – unresolved canonical parent ACZ identity.
//    • Excluded districts are not dropped silently. They are captured in a
//      dedicated DROP-LOG export with exclusion reasons and diagnostic fields.
//
// 5) GROUPED QA + IDENTIFIER COLLISION CHECKS
//    • Builds grouped QA summaries by ACZ, including counts of:
//        – prepared districts,
//        – ready districts,
//        – excluded districts,
//        – zero-land districts,
//        – outside-land warning districts,
//        – unresolved district IDs,
//        – unresolved parent ACZs.
//    • Performs identifier collision checks so that one unit_id cannot map to
//      multiple unit_name, parent_id, parent_name, or parent_code values.
//    • Any collision is treated as a hard failure.
//
// 6) PROJECTION / GRID ALIGNMENT
//    • Reads the native projection of MCD64A1 BurnDate.
//    • Defines a MODIS-aligned pixel-area image and uses it as the single
//      source of truth for numerator and denominator area computations.
//    • All reductions specify MODIS CRS and execute on the MODIS BA grid.
//
// 7) LAND-COVER YEAR SUPPORT
//    • Builds a list of distinct available years in MCD12Q1.
//    • Requires exact support for every denominator year from 2001 to 2024.
//    • If any required denominator year is missing, the script fails rather
//      than silently substituting another year.
//
// 8) BASELINE EXCLUDED MASK, ANNUAL KEEP MASK, AND BURNABLE DENOMINATORS
//    Burnable land is defined using MCD12Q1 LC_Type1 classes in LC_INCLUDE:
//      forests (1–5), shrublands (6–7), woody savannas / savannas (8–9),
//      grasslands (10), croplands (12), and cropland / natural mosaic (14).
//
//    8a) Annual excluded mask
//      • For each year, pixels are excluded when:
//          – LW != 2, or
//          – LC_Type1 == 17
//      • This is the frozen c1 permanent-water / non-land exclusion rule.
//
//    8b) Annual keep mask
//      • For each year, the baseline keep mask is the complement:
//          – LW == 2 AND LC_Type1 != 17
//
//    8c) Annual burnable denominator
//      • For each year 2001–2024, annual burnable support is:
//          – LC_Type1 in LC_INCLUDE
//          – AND LW == 2
//          – AND LC_Type1 != 17
//      • Annual burnable area and annual burnable pixel count are computed for
//        each district and stored in an annual denominator table.
//
//    8d) Fixed UNION denominator
//      • Annual burnable masks for 2001–2024 are combined by pixel-wise OR to
//        form a fixed UNION denominator.
//      • This UNION denominator is used for primary monthly numerator masking
//        and the main burned fraction.
//
// 9) ZERO-DENOMINATOR FLAGS (EXPLICIT; NOT DROPPED)
//    • Districts can have zero burnable denominator under the frozen burnable
//      definition.
//    • The script exports explicit flags rather than silently removing them:
//        – zero_union_den_flag
//        – zero_annual_den_flag
//    • Burned fractions are set to null when the relevant denominator is <= 0.
//
// 10) QA AUDITS (GRID-CONSISTENT DRIFT CHECKS)
//    • UNION denominator audit:
//        – compares reported UNION area from updateMask(...) against an
//          independent algebraic path using mask01 * pixelArea on the same
//          MODIS grid,
//        – flags drift when the difference exceeds the configured tolerance.
//    • ANNUAL denominator audit:
//        – applies the same two-path audit for each district-year annual
//          denominator.
//    • denom_any_drift_flag is carried to monthly rows as the OR of union and
//      annual drift conditions.
//
// 11) MONTHLY BURNED-AREA NUMERATOR (2001–2024) + NATIONAL REFERENCE DIAGNOSTIC
//    • Iterates over all calendar months from START (inclusive) to END
//      (exclusive), yielding one row per month per ready district.
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
// 12) LIGHT QA PREVIEW (MAP UI)
//    • Provides a fixed-method QA interface, not an exploratory method viewer.
//    • Includes controls for:
//        – ACZ selection,
//        – district highlight selection,
//        – year,
//        – month,
//        – BurnMask / BurnDate preview,
//        – layer visibility.
//    • Displays, for the selected ACZ / year / month:
//        – ACZ boundary,
//        – district boundaries,
//        – selected district outline,
//        – LC_Type1 preview,
//        – excluded mask,
//        – UNION burnable denominator,
//        – selected-year annual burnable denominator,
//        – monthly burned-area mask or BurnDate max.
//    • Includes a top-right legend with LC_Type1 class labels and a concise
//      analytical summary.
//
// 13) BUTTON-TRIGGERED CSV EXPORTS
//    • Export tasks are button-triggered rather than auto-scheduled on script
//      load.
//    • Two export scopes are supported under the same frozen c1 method:
//        – selected ACZ district bundle,
//        – all-ACZ district export loop.
//    • The dedicated RP1 base/ext monthly exports are clipped to 200101
//      through 202412 so they align with the downstream BA/AF merger window.
//    • For each ACZ export bundle, the script can write:
//        – a lean analytical CSV,
//        – an ext CSV carrying diagnostics, provenance, and audit fields,
//        – a grouped QA-by-ACZ CSV,
//        – a drop-log CSV when exclusions occur.
//
// INPUT DATASETS
// --------------
// • Burned-area numerator:  MODIS/061/MCD64A1 — BurnDate
// • Burnable denominator:   MODIS/061/MCD12Q1 — LC_Type1 + LW
// • Ghana land-only mask:   Canonical Ghana land-only FeatureCollection (asset)
// • Canonical district inputs: Stage 1 districts-within-ACZ FeatureCollection(s)
//
// HOW TO USE
// ----------
// 1) Set or confirm the Stage 1 district source assets.
// 2) Set DISTRICT_SOURCE_MODE:
//      – 'combined_filtered', or
//      – 'split_asset'.
// 3) Set DEFAULT_ZONE_ID to the desired canonical zone_id.
// 4) Set GHANA_LAND_FC to the canonical Ghana land-only asset.
// 5) Confirm START / END (END is exclusive; END = 2025-01-01 covers Dec 2024).
// 6) Set EXPORT_FOLDER and FILE_PREFIX_BASE; toggle ENABLE_EXPORTS if needed.
// 7) Run the script.
// 8) Use the Controls tab for fixed-method QA preview.
// 9) Use the Exports tab to queue either:
//      – selected-ACZ district analytical + ext + QA + drop-log exports, or
//      – all-ACZ district export bundles.
// 10) Run the queued tasks from the Tasks tab.
//
// CONVENTIONS / OUTPUTS
// ---------------------
// • Areas are computed from a MODIS-aligned pixel-area image and reported in km².
// • Raster reductions are executed on the MODIS BA grid with explicit MODIS CRS.
// • The numerator uses the fixed UNION burnable denominator.
// • Annual denominator fields are retained for robustness / interpretation.
// • Excluded districts are logged explicitly rather than silently discarded.
// • The script exports method-stable analytical outputs plus QA/provenance
//   artefacts to support defensibility.
// • The merger-ready RP1 base export now uses the generic Stage 1 identity
//   contract rather than ACZ-specific headers. Parent ACZ metadata is carried
//   through parent_level / parent_id / parent_code / parent_name, and district
//   unit_code is populated only when a genuine source code field exists.
// • Exported RP1 base/ext monthly rows are clipped to 2001-01 through 2024-12.
// • Invariant method metadata such as script_release and BA mask labels are
//   retained in the ext export, not in the lean merger-ready base export.
// =============================================================================


// User-editable configuration: source assets, date window, default ACZ, export settings, and frozen c1 provenance labels.
// ============================= USER CONFIG ===================================

// Stage-1 district assets.
// Stage 1 district source assets: one combined asset plus one per-zone split asset for alternative routing modes.
var STAGE1_DISTRICTS_COMBINED = ee.FeatureCollection('projects/afd-data-cube-project/assets/RP1_Project/districts_within_acz');
var STAGE1_DISTRICTS_CZ = ee.FeatureCollection('projects/afd-data-cube-project/assets/RP1_Project/districts_within_acz__zone_coastal_zone');
var STAGE1_DISTRICTS_FZ = ee.FeatureCollection('projects/afd-data-cube-project/assets/RP1_Project/districts_within_acz__zone_forest_zone');
var STAGE1_DISTRICTS_GS = ee.FeatureCollection('projects/afd-data-cube-project/assets/RP1_Project/districts_within_acz__zone_guinea_savannah');
var STAGE1_DISTRICTS_SS = ee.FeatureCollection('projects/afd-data-cube-project/assets/RP1_Project/districts_within_acz__zone_sudan_savannah');
var STAGE1_DISTRICTS_TZ = ee.FeatureCollection('projects/afd-data-cube-project/assets/RP1_Project/districts_within_acz__zone_transition_zone');

// Canonical Ghana land-only boundary.
// Canonical Ghana land-only boundary used to clip every district and all map previews.
var GHANA_LAND_FC = ee.FeatureCollection('projects/afd-data-cube-project/assets/RP1_Project/gha_admin0');

// Study window.
// Overlap-era study window for the analytical exports. END is exclusive, so 2025-01-01 includes Dec 2024.
var START = '2001-01-01';
var END   = '2025-01-01';
var DENOM_START_YEAR = 2001;
var DENOM_END_YEAR   = 2024;

// Default UI selection.
// Initial ACZ shown in the UI and used if an invalid zone is requested.
var DEFAULT_ZONE_ID = 'transition_zone';

// District source mode:
//  - 'combined_filtered' : use the combined district asset and filter by canonical zone_id
//  - 'split_asset'       : use one zone-specific district asset per ACZ
var DISTRICT_SOURCE_MODE = 'combined_filtered';

// Export controls.
// Drive export controls: folder, base filename prefix, and UI/task behaviour.
var EXPORT_FOLDER = 'RP1_Project_MODIS_BA_c1_2001';
var FILE_PREFIX_BASE = 'rp1_ba_district_monthly_c1';
var ENABLE_EXPORTS = true;
var ENABLE_AUTO_EXPORT_CURRENT_SELECTION = false;
var DEBUG_UI_PRINTS = false;

// Provenance constants.
var SRC_MODIS_VERSION  = 'MCD64A1 v6.1';
var SRC_LC_VERSION     = 'MCD12Q1 v6.1';
var LEVEL_VALUE        = 'district';
var PARENT_LEVEL_VALUE = 'acz';

// Dedicated RP1 export-family contract controls. The analytical backbone still
// runs across the full overlap-era window, but the exported merger-ready RP1
// rows are clipped to the BA/AF shared monthly window below.
var RP1_SCHEMA_VERSION = 'rp1_ba_monthly_stage1_generic_v1';
var RP1_EXPORT_START_YYYYMM = 200101;
var RP1_EXPORT_END_YYYYMM   = 202412;
var RP1_EXPORT_START_LABEL  = '2001-01';
var RP1_EXPORT_END_LABEL    = '2024-12';

// Frozen c1 method / provenance labels.
// Frozen provenance labels carried into exports so downstream merges can identify the exact analytical contract.
var SCRIPT_RELEASE = 'c1';
var SCRIPT_LINEAGE = 'v3_strict_backbone_plus_fixed_v4_LW_OR_LC17_baseline';
var FIXED_BA_MASK_MODE = 'LW_OR_LC17';
var BA_MASK_MODE = FIXED_BA_MASK_MODE;
var BA_MASK_SHORT_CODE = 'LW_OR_LC17';
var BA_MASK_LAYER_LABEL = 'LW != 2 OR LC_Type1 == 17';
var BA_MASK_KEEP_SUMMARY = 'Keep pixels where LW == 2 and LC_Type1 != 17';
var BA_MASK_EXCLUDED_SUMMARY = 'Exclude pixels where LW != 2 or LC_Type1 == 17';


// =========================== DATASETS & BANDS ================================

// Source products for the numerator (MCD64A1) and denominator (MCD12Q1).
var IMPACT_PRODUCT_ID = 'MODIS/061/MCD64A1';
var DENOM_PRODUCT_ID  = 'MODIS/061/MCD12Q1';

var IMPACT_BAND_BURNDATE    = 'BurnDate';
var IMPACT_BANDS_RECOGNISED = ee.List(['BurnDate', 'QA', 'FirstDay', 'LastDay']);
var DENOM_BAND_LC_TYPE1     = 'LC_Type1';
var DENOM_BAND_LW           = 'LW';

var MCD64A1 = ee.ImageCollection(IMPACT_PRODUCT_ID).select(IMPACT_BAND_BURNDATE);
var MCD12Q1 = ee.ImageCollection(DENOM_PRODUCT_ID).select([DENOM_BAND_LC_TYPE1, DENOM_BAND_LW]);


// Analysis constants: LC class set, reducer settings, tolerance thresholds, provenance strings, and canonical zone metadata.
// ============================== CONSTANTS ====================================

// Burnable LC_Type1 classes retained in the annual and union denominators.
var LC_INCLUDE = ee.List([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14]);

var SCALE_BA   = 500;
var MAX_PIXELS = 1e13;
var TILE_SCALE = 4;

var SMALL_DEN_THRESHOLD_KM2 = 50;
var OUTSIDE_LAND_WARN_FRAC  = 1e-4;

var DENOM_DRIFT_TOL_ABS_KM2  = 1;
var DENOM_DRIFT_TOL_REL_FRAC = 0.001;

var PARTIAL_VIIRS_OVERLAP_YYYYMM = Number(START.slice(0, 4) + START.slice(5, 7));

var NOW_JS = new Date();
var RUN_STAMP_STR = NOW_JS.toISOString().replace(/[-:]/g, '').replace(/\..*/, 'Z');
var CREATED_ISO_STR = NOW_JS.toISOString();
var RUN_STAMP = ee.String(RUN_STAMP_STR);
var CREATED_ISO = ee.String(CREATED_ISO_STR);
var RUN_DATE_ISO = CREATED_ISO;

var REDUCER_TYPE      = 'sum';
var REDUCER_WEIGHTING = 'unweighted';
var DENOM_EXACT_YEAR_REQUIRED_FLAG = 1;
var DENOM_UNION_ROLE  = 'primary_fixed_union_exposure';
var DENOM_ANNUAL_ROLE = 'secondary_year_specific_exposure';

// Client-side canonical ACZ metadata used for UI labels and all-ACZ export loops.
var CANONICAL_ZONES = [
  {zone_id: 'coastal_zone',    zone_name: 'COASTAL ZONE',    zone_code: 'CZ'},
  {zone_id: 'forest_zone',     zone_name: 'FOREST ZONE',     zone_code: 'FZ'},
  {zone_id: 'guinea_savannah', zone_name: 'GUINEA SAVANNAH', zone_code: 'GS'},
  {zone_id: 'sudan_savannah',  zone_name: 'SUDAN SAVANNAH',  zone_code: 'SS'},
  {zone_id: 'transition_zone', zone_name: 'TRANSITION ZONE', zone_code: 'TZ'}
];

var ZONE_BY_ID_OBJ = {
  'coastal_zone':    {zone_id: 'coastal_zone',    zone_name: 'COASTAL ZONE',    zone_code: 'CZ'},
  'forest_zone':     {zone_id: 'forest_zone',     zone_name: 'FOREST ZONE',     zone_code: 'FZ'},
  'guinea_savannah': {zone_id: 'guinea_savannah', zone_name: 'GUINEA SAVANNAH', zone_code: 'GS'},
  'sudan_savannah':  {zone_id: 'sudan_savannah',  zone_name: 'SUDAN SAVANNAH',  zone_code: 'SS'},
  'transition_zone': {zone_id: 'transition_zone', zone_name: 'TRANSITION ZONE', zone_code: 'TZ'}
};

var ZONE_UI_LABELS = CANONICAL_ZONES.map(function(z) {
  return z.zone_name + ' (' + z.zone_code + ')';
});
var ZONE_ID_TO_LABEL = {};
var ZONE_LABEL_TO_ID = {};
for (var zi = 0; zi < CANONICAL_ZONES.length; zi++) {
  var zoneMetaIter = CANONICAL_ZONES[zi];
  var zoneLabelIter = zoneMetaIter.zone_name + ' (' + zoneMetaIter.zone_code + ')';
  ZONE_ID_TO_LABEL[zoneMetaIter.zone_id] = zoneLabelIter;
  ZONE_LABEL_TO_ID[zoneLabelIter] = zoneMetaIter.zone_id;
}

// Mask-mode metadata retained mainly for labels and provenance; analytical execution is still hard-frozen to LW_OR_LC17.
var BA_MASK_MODES = {
  'LC17': {
    key: 'LC17',
    shortCode: 'LC17',
    uiLabel: 'Strict water only — LC_Type1 class 17',
    layerLabel: 'LC_Type1 == 17 (Water Bodies)',
    keepSummary: 'Keep pixels where LC_Type1 != 17',
    excludedSummary: 'Exclude pixels where LC_Type1 == 17'
  },
  'LC11_17': {
    key: 'LC11_17',
    shortCode: 'LC11_17',
    uiLabel: 'Conservative water + wetlands — LC_Type1 classes 11 and 17',
    layerLabel: 'LC_Type1 in {11, 17}',
    keepSummary: 'Keep pixels where LC_Type1 not in {11, 17}',
    excludedSummary: 'Exclude pixels where LC_Type1 in {11, 17}'
  },
  'LW': {
    key: 'LW',
    shortCode: 'LW',
    uiLabel: 'Dedicated binary land/water mask — LW == 2 kept',
    layerLabel: 'LW != 2 excluded / LW == 2 kept',
    keepSummary: 'Keep pixels where LW == 2',
    excludedSummary: 'Exclude pixels where LW != 2'
  },
  'LW_OR_LC17': {
    key: 'LW_OR_LC17',
    shortCode: 'LW_OR_LC17',
    uiLabel: 'Conservative water union — LW water OR LC_Type1 class 17',
    layerLabel: 'LW != 2 OR LC_Type1 == 17',
    keepSummary: 'Keep pixels where LW == 2 and LC_Type1 != 17',
    excludedSummary: 'Exclude pixels where LW != 2 or LC_Type1 == 17'
  },
  'LW_OR_LC11_17': {
    key: 'LW_OR_LC11_17',
    shortCode: 'LW_OR_LC11_17',
    uiLabel: 'Broad hydrology/wetness union — LW water OR LC_Type1 in {11,17}',
    layerLabel: 'LW != 2 OR LC_Type1 in {11,17}',
    keepSummary: 'Keep pixels where LW == 2 and LC_Type1 not in {11,17}',
    excludedSummary: 'Exclude pixels where LW != 2 or LC_Type1 in {11,17}'
  }
};


// Preview styling for LC classes, excluded-mask, boundaries, burn layers, and legend colours.
// =========================== VISUAL DEFINITIONS ==============================

// LC_Type1 palette (MCD12Q1 IGBP).
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
var EXCLUDED_VIS = {palette: ['2b83ba']};
var UNION_VIS = {palette: ['ffd92f']};
var DISTRICT_BOUNDARY_VIS = {palette: ['000000']};
var SELECTED_DISTRICT_VIS = {palette: ['ffff00']};
var ZONE_BOUNDARY_VIS = {palette: ['ff0000']};
var BURNMASK_VIS = {palette: ['000000']};
var BURNDATE_VIS = {min: 1, max: 366, palette: ['f2f2f2', '000000']};

var LC_OPACITY = 0.85;
var WATER_OPACITY = 0.75;
var UNION_OPACITY = 0.7;
var BA_OPACITY = 0.9;


// Human-readable study-window and LC-class strings reused in labels, exports, and provenance fields.
// ============================ TEXTUAL METADATA ===============================

// Format month/day-like integers as two-digit strings for labels, filenames, and YYYY-MM text.
function pad2(n) { return (n < 10 ? '0' : '') + n; }

// Convert an exclusive END date (YYYY-MM-DD) into the final included YYYY-MM string for human-readable metadata.
function monthBeforeExclusiveEnd(endStr) {
  var y = Number(endStr.slice(0, 4));
  var m = Number(endStr.slice(5, 7));
  m -= 1;
  if (m === 0) {
    m = 12;
    y -= 1;
  }
  return String(y) + '-' + pad2(m);
}

var STUDY_WINDOW_TEXT = START.slice(0, 7) + ' to ' + monthBeforeExclusiveEnd(END);
var RP1_EXPORT_WINDOW_TEXT = RP1_EXPORT_START_LABEL + ' to ' + RP1_EXPORT_END_LABEL;
var DENOM_YEAR_RANGE_TEXT = String(DENOM_START_YEAR) + ' to ' + String(DENOM_END_YEAR);
var LC_INCLUDE_TEXT = LC_INCLUDE.getInfo().join(', ');

// Ordered selector lists used to keep the dedicated RP1 CSV schemas stable.
// RP1_BASE_SELECTORS is the lean merger-ready analytical extract.
// RP1_EXT_SELECTORS begins with the exact same base schema, then appends
// row-level diagnostics, QA flags, provenance, and implementation metadata.
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

  'canonical_unit_binding_ok_flag',
  'canonical_unit_binding_source',
  'canonical_parent_binding_ok_flag',
  'canonical_parent_binding_source',
  'parent_zone_binding_status',
  'raw_dist_id',
  'raw_dist_name',
  'raw_dist_code',
  'raw_zone_id',
  'raw_zone_name',
  'raw_zone_code',
  'raw_dist_id_source',
  'raw_dist_name_source',
  'raw_dist_code_source',
  'raw_zone_id_source',
  'raw_zone_name_source',
  'raw_zone_code_source',
  'unit_code_available_flag',
  'unit_code_blank_flag',
  'unit_code_source_field',
  'fallback_unit_id_if_unresolved',

  'small_den',

  'denom_year_target',
  'denom_year_used',
  'denom_year_fallback_flag',
  'denom_years_used_pipe',
  'denom_missing_years_count',
  'denom_missing_years_pipe',

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
  'impact_bands_recognised_pipe',
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

  'target_zone_id',
  'target_zone_name',
  'target_zone_code',
  'district_source_mode',

  'created_utc',
  'run_date',
  'start',
  'end_exclusive',
  'months_count'
];

var RP1_BASE_SELECTORS = RP1_BASE_IDENTITY_COLS.concat(RP1_BASE_ANALYTICAL_COLS);
var RP1_EXT_SELECTORS = RP1_BASE_SELECTORS.concat(RP1_EXT_EXTRA_COLS);


// Client-side guards that fail early if required assets or exact denominator years are missing.
// =========================== CLIENT-SIDE VALIDATION ==========================

// Client-side configuration guard: force a lightweight access check so missing or inaccessible assets fail early.
function validateFeatureCollectionAsset(name, fc) {
  try {
    var sz = ee.FeatureCollection(fc).limit(1).size().getInfo();
    if (sz === null || sz === undefined) {
      throw new Error('Unable to confirm asset: ' + name);
    }
  } catch (err) {
    throw new Error('Asset validation failed for ' + name + ': ' + err);
  }
}

// Build a client-side year -> image-count lookup for MCD12Q1 so exact-year denominator support can be validated before analysis.
function clientMcd12YearCounts() {
  var times = ee.List(MCD12Q1.aggregate_array('system:time_start')).getInfo();
  var out = {};
  for (var i = 0; i < times.length; i++) {
    var y = new Date(times[i]).getUTCFullYear();
    out[y] = (out[y] || 0) + 1;
  }
  return out;
}

// Ensure the configured default ACZ is one of the canonical Stage 1 zone IDs.
function validateDefaultZoneId(zoneId) {
  if (!ZONE_BY_ID_OBJ[zoneId]) {
    throw new Error('DEFAULT_ZONE_ID is not recognised: ' + zoneId);
  }
}

// Ensure the district source mode is one of the two supported routing options.
function validateDistrictSourceMode(mode) {
  if (mode !== 'combined_filtered' && mode !== 'split_asset') {
    throw new Error('DISTRICT_SOURCE_MODE must be "combined_filtered" or "split_asset".');
  }
}

// Route district loading either through the combined national asset or the zone-specific split assets.
function zoneFcFromMode(zoneId, mode) {
  if (mode === 'combined_filtered') {
    return ee.FeatureCollection(STAGE1_DISTRICTS_COMBINED)
      .filter(ee.Filter.eq('zone_id', zoneId));
  }
  if (zoneId === 'coastal_zone') return STAGE1_DISTRICTS_CZ;
  if (zoneId === 'forest_zone') return STAGE1_DISTRICTS_FZ;
  if (zoneId === 'guinea_savannah') return STAGE1_DISTRICTS_GS;
  if (zoneId === 'sudan_savannah') return STAGE1_DISTRICTS_SS;
  if (zoneId === 'transition_zone') return STAGE1_DISTRICTS_TZ;
  throw new Error('No zone asset mapping for zoneId=' + zoneId);
}

// Run all client-side configuration checks up front: assets, zone selection, source mode, and exact-year MCD12Q1 availability.
function validateConfig() {
  validateFeatureCollectionAsset('GHANA_LAND_FC', GHANA_LAND_FC);
  validateFeatureCollectionAsset('STAGE1_DISTRICTS_COMBINED', STAGE1_DISTRICTS_COMBINED);
  validateFeatureCollectionAsset('STAGE1_DISTRICTS_CZ', STAGE1_DISTRICTS_CZ);
  validateFeatureCollectionAsset('STAGE1_DISTRICTS_FZ', STAGE1_DISTRICTS_FZ);
  validateFeatureCollectionAsset('STAGE1_DISTRICTS_GS', STAGE1_DISTRICTS_GS);
  validateFeatureCollectionAsset('STAGE1_DISTRICTS_SS', STAGE1_DISTRICTS_SS);
  validateFeatureCollectionAsset('STAGE1_DISTRICTS_TZ', STAGE1_DISTRICTS_TZ);

  validateDefaultZoneId(DEFAULT_ZONE_ID);
  validateDistrictSourceMode(DISTRICT_SOURCE_MODE);

  var yearCounts = clientMcd12YearCounts();
  for (var y = DENOM_START_YEAR; y <= DENOM_END_YEAR; y++) {
    if (!yearCounts[y]) {
      throw new Error('Missing exact MCD12Q1 year support for denominator year ' + y);
    }
    if (yearCounts[y] !== 1) {
      throw new Error('Expected exactly one MCD12Q1 image for year ' + y + ', found ' + yearCounts[y]);
    }
  }
}

validateConfig();


// Reusable Earth Engine helpers for geometry cleaning, masking, drift audits, and identifier normalisation.
// ============================== EE HELPERS ===================================

// Geometry hygiene helper: repair potentially invalid polygons with a zero-width buffer using a small error margin.
function cleanGeom(g) {
  return ee.Geometry(g).buffer(0, 1);
}

// Safely coerce possibly-null reducer output to an ee.Number with a fallback value.
function safeNumber(x, fallback) {
  return ee.Number(ee.Algorithms.If(x, x, fallback));
}

// Division helper that returns null when the denominator is zero instead of throwing or producing meaningless values.
function safeFrac(num, den) {
  num = ee.Number(num);
  den = ee.Number(den);
  return ee.Algorithms.If(den.gt(0), num.divide(den), null);
}

// Return an integer 0/1 flag for x > threshold, while safely handling null-like values.
function safeGt(x, thresh) {
  x = ee.Number(ee.Algorithms.If(x, x, 0));
  thresh = ee.Number(thresh);
  return ee.Number(ee.Algorithms.If(x.gt(thresh), 1, 0)).int();
}

// Normalise text for identifier resolution: trim whitespace and collapse repeated spaces.
function normText(s) {
  s = ee.String(ee.Algorithms.If(s, s, ''));
  return s.trim().replace('\\s+', ' ');
}

// Convert text into a lower-case underscore key for canonical lookups.
function normKey(s) {
  s = normText(s).toLowerCase();
  return s.replace('[^a-z0-9]+', '_');
}

// Convert text into an upper-case snake-case token used for fallback identifiers.
function toUpperSnake(s) {
  s = normText(s);
  return s.toUpperCase().replace('[^A-Z0-9]+', '_');
}

// Search a feature for the first non-missing property in a priority list and retain which source field supplied the value.
function pickPropWithSource(f, keys) {
  f = ee.Feature(f);
  keys = ee.List(keys);
  var init = ee.Dictionary({value: '', source: 'missing'});

  var picked = ee.Dictionary(keys.iterate(function(k, acc) {
    acc = ee.Dictionary(acc);
    var key = ee.String(k);
    var currentVal = ee.String(acc.get('value'));
    return ee.Dictionary(ee.Algorithms.If(
      currentVal.length().gt(0),
      acc,
      ee.Dictionary(ee.Algorithms.If(
        f.propertyNames().contains(key),
        ee.Dictionary({
          value: ee.String(ee.Algorithms.If(f.get(key), f.get(key), '')),
          source: key
        }),
        acc
      ))
    ));
  }, init));

  return picked;
}

// Join non-empty warning or exclusion tokens into a pipe-delimited string.
function joinWarnings(list) {
  list = ee.List(list).removeAll(['']);
  return ee.List(list).join('|');
}

// Convert any mask-like image into a clean 0/1 image suitable for algebraic area or pixel-count checks.
function mask01(img) {
  return ee.Image(img).unmask(0).gt(0).toUint8();
}

// Convert a 0/1 image into a true mask (self-masked) so only 1-valued pixels survive updateMask operations.
function asTrueMask(img) {
  return ee.Image(img).selfMask();
}

// Generate the full monthly sequence from START (inclusive) to END (exclusive).
function monthSequence(start, end) {
  start = ee.Date(start);
  end = ee.Date(end);
  var months = ee.List.sequence(0, end.difference(start, 'month').subtract(1));
  return months.map(function(k) {
    var d = start.advance(ee.Number(k), 'month');
    return ee.Dictionary({start: d, end: d.advance(1, 'month')});
  });
}

// Extract year, month, and YYYYMM integer keys from an ee.Date for row construction and labelling.
function dateParts(d) {
  d = ee.Date(d);
  var y = ee.Number(d.get('year')).int();
  var m = ee.Number(d.get('month')).int();
  return ee.Dictionary({
    year: y,
    month: m,
    yyyymm: y.multiply(100).add(m)
  });
}

// Clip any monthly-row collection to the dedicated merger-ready RP1 export
// window while leaving the wider analytical backbone unchanged.
function filterToRp1ExportWindow(fc) {
  return ee.FeatureCollection(fc)
    .filter(ee.Filter.gte('yyyymm', RP1_EXPORT_START_YYYYMM))
    .filter(ee.Filter.lte('yyyymm', RP1_EXPORT_END_YYYYMM));
}

// Convenience helper for pipe-delimited provenance fields.
function joinPipe(listLike) {
  return ee.List(listLike).join('|');
}

// Compare two denominator area calculations and return absolute/relative differences plus a tolerance-based drift flag.
function driftAudit(reportedKm2, checkKm2) {
  reportedKm2 = ee.Number(reportedKm2);
  checkKm2 = ee.Number(checkKm2);
  var absDiff = reportedKm2.subtract(checkKm2).abs();
  var relDiff = ee.Algorithms.If(
    checkKm2.gt(0),
    absDiff.divide(checkKm2),
    ee.Algorithms.If(reportedKm2.eq(0), 0, null)
  );
  var threshKm2 = ee.Number(ee.Algorithms.If(
    checkKm2.gt(0),
    checkKm2.multiply(DENOM_DRIFT_TOL_REL_FRAC).max(DENOM_DRIFT_TOL_ABS_KM2),
    DENOM_DRIFT_TOL_ABS_KM2
  ));
  var flag = ee.Number(ee.Algorithms.If(absDiff.gt(threshKm2), 1, 0)).int();
  return ee.Dictionary({
    abs_diff_km2: absDiff,
    rel_diff: relDiff,
    thresh_km2: threshKm2,
    flag: flag
  });
}

// Pull one property from a FeatureCollection to the client, used for grouped QA and collision checks.
function clientAggregateArray(fc, propertyName) {
  return ee.List(ee.FeatureCollection(fc).aggregate_array(propertyName)).getInfo();
}

// Read a field from a joined annual-denominator feature if present, otherwise return a default value.
function annualFieldOrDefault(annualObj, key, defaultVal) {
  return ee.Algorithms.If(
    annualObj,
    ee.Algorithms.If(
      ee.Feature(annualObj).propertyNames().contains(key),
      ee.Feature(annualObj).get(key),
      defaultVal
    ),
    defaultVal
  );
}

// Hard freeze the analytical mask mode: any requested mode is coerced back to the c1 baseline.
function getBaMaskMode(mode) {
  // c1 is intentionally fixed-method. Any incoming mode request is coerced
  // back to the frozen baseline so the analytical method cannot drift.
  return FIXED_BA_MASK_MODE;
}

// Return the metadata bundle for the frozen c1 mask mode.
function getBaMaskConfig(mode) {
  return BA_MASK_MODES[getBaMaskMode(mode)];
}

// Resolve zone metadata client-side for labels, filenames, and export provenance.
function getZoneMeta(zoneId) {
  return ZONE_BY_ID_OBJ[zoneId] || ZONE_BY_ID_OBJ[DEFAULT_ZONE_ID];
}

// Human-readable ACZ label used in the UI.
function zoneLabel(zoneId) {
  var z = getZoneMeta(zoneId);
  return z.zone_name + ' (' + z.zone_code + ')';
}

// Canonical ACZ lookup tables used to resolve parent-zone identity consistently from IDs, codes, or names.
// ===================== CANONICAL ACZ LOOKUP (STAGE 1) ========================

var CANONICAL_ZONE_IDS = ee.List([
  'coastal_zone',
  'forest_zone',
  'guinea_savannah',
  'sudan_savannah',
  'transition_zone'
]);

var ZONE_BY_ID = ee.Dictionary({
  coastal_zone:    ee.Dictionary({zone_id: 'coastal_zone',    zone_name: 'COASTAL ZONE',    zone_code: 'CZ'}),
  forest_zone:     ee.Dictionary({zone_id: 'forest_zone',     zone_name: 'FOREST ZONE',     zone_code: 'FZ'}),
  guinea_savannah: ee.Dictionary({zone_id: 'guinea_savannah', zone_name: 'GUINEA SAVANNAH', zone_code: 'GS'}),
  sudan_savannah:  ee.Dictionary({zone_id: 'sudan_savannah',  zone_name: 'SUDAN SAVANNAH',  zone_code: 'SS'}),
  transition_zone: ee.Dictionary({zone_id: 'transition_zone', zone_name: 'TRANSITION ZONE', zone_code: 'TZ'})
});

var ZONE_BY_CODE = ee.Dictionary({
  CZ: ee.Dictionary({zone_id: 'coastal_zone',    zone_name: 'COASTAL ZONE',    zone_code: 'CZ'}),
  FZ: ee.Dictionary({zone_id: 'forest_zone',     zone_name: 'FOREST ZONE',     zone_code: 'FZ'}),
  GS: ee.Dictionary({zone_id: 'guinea_savannah', zone_name: 'GUINEA SAVANNAH', zone_code: 'GS'}),
  SS: ee.Dictionary({zone_id: 'sudan_savannah',  zone_name: 'SUDAN SAVANNAH',  zone_code: 'SS'}),
  TZ: ee.Dictionary({zone_id: 'transition_zone', zone_name: 'TRANSITION ZONE', zone_code: 'TZ'})
});

var ZONE_BY_NAME = ee.Dictionary({
  COASTAL_ZONE: ee.Dictionary({zone_id: 'coastal_zone',    zone_name: 'COASTAL ZONE',    zone_code: 'CZ'}),
  FOREST_ZONE: ee.Dictionary({zone_id: 'forest_zone',     zone_name: 'FOREST ZONE',     zone_code: 'FZ'}),
  GUINEA_SAVANNAH: ee.Dictionary({zone_id: 'guinea_savannah', zone_name: 'GUINEA SAVANNAH', zone_code: 'GS'}),
  SUDAN_SAVANNAH: ee.Dictionary({zone_id: 'sudan_savannah',  zone_name: 'SUDAN SAVANNAH',  zone_code: 'SS'}),
  TRANSITION_ZONE: ee.Dictionary({zone_id: 'transition_zone', zone_name: 'TRANSITION ZONE', zone_code: 'TZ'})
});

// Resolve canonical ACZ metadata from a canonical zone_id.
function canonicalFieldFromId(zoneId, fieldName) {
  zoneId = ee.String(ee.Algorithms.If(zoneId, zoneId, ''));
  return ee.String(ee.Algorithms.If(
    ZONE_BY_ID.contains(zoneId),
    ee.Dictionary(ZONE_BY_ID.get(zoneId)).get(fieldName),
    ''
  ));
}

// Resolve canonical ACZ metadata from a zone code.
function canonicalFieldFromCode(zoneCode, fieldName) {
  zoneCode = ee.String(ee.Algorithms.If(zoneCode, zoneCode, '')).toUpperCase();
  return ee.String(ee.Algorithms.If(
    ZONE_BY_CODE.contains(zoneCode),
    ee.Dictionary(ZONE_BY_CODE.get(zoneCode)).get(fieldName),
    ''
  ));
}

// Resolve canonical ACZ metadata from a zone name.
function canonicalFieldFromName(zoneName, fieldName) {
  zoneName = normKey(zoneName).toUpperCase();
  return ee.String(ee.Algorithms.If(
    ZONE_BY_NAME.contains(zoneName),
    ee.Dictionary(ZONE_BY_NAME.get(zoneName)).get(fieldName),
    ''
  ));
}

// Resolve one canonical ACZ field using ID first, then code, then name.
function resolveCanonicalZoneField(rawZoneId, rawZoneCode, rawZoneName, fieldName) {
  var fromId = canonicalFieldFromId(rawZoneId, fieldName);
  var fromCode = canonicalFieldFromCode(rawZoneCode, fieldName);
  var fromName = canonicalFieldFromName(rawZoneName, fieldName);

  return ee.String(ee.Algorithms.If(
    fromId.length().gt(0), fromId,
    ee.Algorithms.If(fromCode.length().gt(0), fromCode, fromName)
  ));
}


// Priority order for reading district and ACZ identifiers from input feature properties.
// ======================= INPUT FIELD PRIORITY ORDER ==========================

var DIST_ID_KEYS = [
  'dist_id',
  'district_id',
  'district_code'
];

var DIST_NAME_KEYS = [
  'dist_name',
  'district_name',
  'district'
];

// District unit_code is populated only from genuine district-code fields.
// The Stage 1 example unit_universe carries blank district unit_code values,
// so this list is intentionally conservative and the fallback is blank.
var DIST_CODE_KEYS = [
  'unit_code',
  'dist_code',
  'district_code'
];

var ZONE_ID_KEYS = [
  'zone_id',
  'acz_id'
];

var ZONE_NAME_KEYS = [
  'zone_name',
  'acz_name'
];

var ZONE_CODE_KEYS = [
  'zone_code',
  'acz_code'
];


// Global support objects: land mask, target years, month sequence, MODIS grid, and exact-year denominator diagnostics.
// ============================ GLOBAL SUPPORT =================================

// Global land geometry and analysis-grid support objects derived once and reused everywhere.
var GHANA_LAND = cleanGeom(GHANA_LAND_FC.geometry());
var TARGET_YEARS = ee.List.sequence(DENOM_START_YEAR, DENOM_END_YEAR);
var MONTHS_ALL = monthSequence(START, END);

var IMPACT_PROJ = ee.Image(MCD64A1.first()).select(IMPACT_BAND_BURNDATE).projection();
var IMPACT_CRS = IMPACT_PROJ.crs();
var IMPACT_NOMINAL_SCALE_M = IMPACT_PROJ.nominalScale();
var PIXEL_AREA_KM2_IMPACT = ee.Image.pixelArea().reproject({crs: IMPACT_PROJ}).divide(1e6);

// Enumerate distinct annual MCD12Q1 support years actually present in Earth Engine.
function availableYearsMcd12() {
  return ee.List(MCD12Q1.aggregate_array('system:time_start')).map(function(t) {
    return ee.Date(ee.Number(t)).get('year');
  }).distinct().sort();
}
var MCD12_AVAILABLE_YEARS = availableYearsMcd12();

var MISSING_TARGET_YEARS = ee.List(TARGET_YEARS.iterate(function(y, acc) {
  acc = ee.List(acc);
  y = ee.Number(y).int();
  return ee.List(ee.Algorithms.If(MCD12_AVAILABLE_YEARS.contains(y), acc, acc.add(y)));
}, ee.List([])));

var DENOM_MISSING_YEARS_COUNT = ee.Number(MISSING_TARGET_YEARS.length());
var DENOM_YEARS_USED_PIPE = ee.List(TARGET_YEARS).map(function(y) { return ee.Number(y).format('%d'); }).join('|');
var DENOM_MISSING_YEARS_PIPE = ee.List(MISSING_TARGET_YEARS).map(function(y) { return ee.Number(y).format('%d'); }).join('|');

print(ee.Dictionary({message: 'MCD12 available years', value: MCD12_AVAILABLE_YEARS}));
print(ee.Dictionary({message: 'Target denominator years', value: TARGET_YEARS}));
print(ee.Dictionary({message: 'Missing target years count', value: DENOM_MISSING_YEARS_COUNT}));

// Return the exact start/end date window for one calendar month.
function monthWindow(year, month) {
  var start = ee.Date.fromYMD(ee.Number(year).int(), ee.Number(month).int(), 1);
  return {start: start, end: start.advance(1, 'month')};
}

// Compute masked area on the fixed MODIS analysis grid using the true-mask path.
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

// Independent algebraic area path for denominator auditing: mask01 * pixelArea on the same MODIS grid.
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

// Count masked pixels on the MODIS grid using an unweighted sum of a 0/1 mask.
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

// Primary monthly burned-area numerator definition: BurnDate > 0 in ANY overlapping image, combined by pixel-wise OR / max.
function monthlyBurnedMaskOr(start, end) {
  start = ee.Date(start);
  end = ee.Date(end);
  var monthCol = MCD64A1.filterDate(start, end);
  var burnedAny01 = ee.ImageCollection(monthCol.map(function(img) {
    return ee.Image(img).gt(0);
  })).max().unmask(0);
  return asTrueMask(burnedAny01);
}

// Diagnostic monthly BurnDate image created by taking the per-pixel max BurnDate across the month.
function monthlyBurnDateMax(start, end) {
  start = ee.Date(start);
  end = ee.Date(end);
  var monthCol = MCD64A1.filterDate(start, end);
  return ee.Image(monthCol.max()).select(IMPACT_BAND_BURNDATE).selfMask();
}


// Exact-year denominator source image for one annual MCD12Q1 year.
function mcd12ImageForYearExact(year) {
  year = ee.Number(year).int();
  return ee.Image(MCD12Q1.filter(ee.Filter.calendarRange(year, year, 'year')).first())
    .select([DENOM_BAND_LC_TYPE1, DENOM_BAND_LW]);
}

// Selected-year excluded mask under the frozen c1 rule: exclude if LW != 2 OR LC_Type1 == 17.
function annualBaExcludedMaskForYear(year, maskMode) {
  year = ee.Number(year).int();
  var img = mcd12ImageForYearExact(year);
  var lc = img.select(DENOM_BAND_LC_TYPE1).unmask(0);
  var lw = img.select(DENOM_BAND_LW).unmask(0);
  var excluded01 = lw.neq(2).or(lc.eq(17));
  return asTrueMask(excluded01).rename('annual_excluded');
}

// Selected-year keep mask under the frozen c1 rule: keep if LW == 2 AND LC_Type1 != 17.
function annualBaKeepMaskForYear(year, maskMode) {
  year = ee.Number(year).int();
  var img = mcd12ImageForYearExact(year);
  var lc = img.select(DENOM_BAND_LC_TYPE1).unmask(0);
  var lw = img.select(DENOM_BAND_LW).unmask(0);
  var keep01 = lw.eq(2).and(lc.neq(17));
  return asTrueMask(keep01).rename('annual_keep');
}

// Annual land-support mask, identical to the selected-year keep mask for this frozen c1 baseline.
function annualLandMaskForYear(year) {
  return annualBaKeepMaskForYear(year, FIXED_BA_MASK_MODE).rename('annual_land');
}

// Annual burnable denominator mask for one year.
function annualBurnableMaskForYear(year, maskMode) {
  year = ee.Number(year).int();
  var img = mcd12ImageForYearExact(year);
  var lc = img.select(DENOM_BAND_LC_TYPE1).unmask(0);
  var keepMask = annualBaKeepMaskForYear(year, maskMode).unmask(0);

  var lcBurnable = lc.remap(
    LC_INCLUDE,
    ee.List.repeat(1, LC_INCLUDE.length()),
    0
  ).toUint8();

  var burnable01 = lcBurnable.eq(1).and(keepMask.gt(0));
  return asTrueMask(burnable01).rename('annual_burnable');
}

// Fixed UNION denominator across all exact annual burnable masks in the configured denominator year range.
function buildBurnableUnionExact(targetYears, maskMode) {
  var yearMasks = ee.List(targetYears).map(function(y) {
    return annualBurnableMaskForYear(y, maskMode).unmask(0).rename('annual_burnable');
  });
  var union01 = ee.ImageCollection.fromImages(yearMasks).max().gt(0).toUint8();
  return asTrueMask(union01).rename('burnable_union');
}

// Draw vector boundaries as a thin raster outline for map preview.
function getBoundaryImage(fc, widthPx) {
  widthPx = widthPx || 1;
  return ee.Image().byte().paint(ee.FeatureCollection(fc), 1, widthPx).selfMask();
}


// Strict district preparation pipeline: canonicalise IDs, attach parent ACZ, enforce land-only geometry, and flag exclusions.
// ============================== UNIT PREP ====================================

// Choose the first non-empty property from a priority list and record the source field used.
function pickFirstNonEmpty(f, keys) {
  var out = {value: '', source: 'missing'};
  var props = ee.Feature(f).toDictionary();
  for (var i = 0; i < keys.length; i++) {
    var k = keys[i];
    var v = props.get(k);
    out = ee.Algorithms.If(
      ee.String(out.value).length().gt(0),
      out,
      ee.Algorithms.If(
        props.contains(k).and(ee.String(ee.Algorithms.If(v, v, '')).length().gt(0)),
        {value: ee.String(v), source: k},
        out
      )
    );
  }
  return ee.Dictionary(out);
}

// Prepare one district feature into the canonical Stage 1-aligned identity contract plus geometry diagnostics and exclusion flags.
function prepareDistrictUnits(fc) {
  fc = ee.FeatureCollection(fc);

  return ee.FeatureCollection(fc.map(function(f) {
    f = ee.Feature(f);

    var rawDistIdInfo = pickPropWithSource(f, DIST_ID_KEYS);
    var rawDistNameInfo = pickPropWithSource(f, DIST_NAME_KEYS);
    var rawDistCodeInfo = pickPropWithSource(f, DIST_CODE_KEYS);

    var rawZoneIdInfo = pickPropWithSource(f, ZONE_ID_KEYS);
    var rawZoneNameInfo = pickPropWithSource(f, ZONE_NAME_KEYS);
    var rawZoneCodeInfo = pickPropWithSource(f, ZONE_CODE_KEYS);

    var rawDistId = normText(rawDistIdInfo.get('value'));
    var rawDistName = normText(rawDistNameInfo.get('value'));
    var rawDistCode = normText(rawDistCodeInfo.get('value'));

    var rawZoneId = normText(rawZoneIdInfo.get('value'));
    var rawZoneName = normText(rawZoneNameInfo.get('value'));
    var rawZoneCode = normText(rawZoneCodeInfo.get('value'));

    var fallbackUnitId = ee.String('DIST_').cat(toUpperSnake(rawDistName));

    var unitId = ee.String(ee.Algorithms.If(
      rawDistId.length().gt(0),
      rawDistId,
      ee.Algorithms.If(rawDistName.length().gt(0), fallbackUnitId, '')
    ));

    var unitName = rawDistName;
    var unitCode = ee.String(ee.Algorithms.If(rawDistCode.length().gt(0), rawDistCode, ''));

    var parentId = resolveCanonicalZoneField(rawZoneId, rawZoneCode, rawZoneName, 'zone_id');
    var parentName = resolveCanonicalZoneField(rawZoneId, rawZoneCode, rawZoneName, 'zone_name');
    var parentCode = resolveCanonicalZoneField(rawZoneId, rawZoneCode, rawZoneName, 'zone_code');

    var unitBindingOk = unitId.length().gt(0).and(unitName.length().gt(0));
    var parentBindingOk = parentId.length().gt(0).and(parentName.length().gt(0)).and(parentCode.length().gt(0));

    var unitBindingSource = ee.String(ee.Algorithms.If(
      unitBindingOk.not(),
      'unresolved',
      ee.Algorithms.If(rawDistId.length().gt(0), 'district_id', 'district_name_fallback')
    ));

    var parentBindingSource = ee.String(ee.Algorithms.If(
      parentBindingOk.not(),
      'unresolved',
      ee.Algorithms.If(
        canonicalFieldFromId(rawZoneId, 'zone_id').length().gt(0),
        'zone_id',
        ee.Algorithms.If(
          canonicalFieldFromCode(rawZoneCode, 'zone_id').length().gt(0),
          'zone_code',
          'zone_name'
        )
      )
    ));

    var rawGeom = cleanGeom(f.geometry());
    var landGeom = cleanGeom(rawGeom.intersection(GHANA_LAND, 1));

    var aoiAreaKm2 = ee.Number(rawGeom.area({maxError: 1})).divide(1e6);
    var aoiAreaLandKm2 = ee.Number(landGeom.area({maxError: 1})).divide(1e6);
    var aoiOutsideLandKm2 = ee.Number(ee.Algorithms.If(
      aoiAreaKm2.subtract(aoiAreaLandKm2).lt(0),
      0,
      aoiAreaKm2.subtract(aoiAreaLandKm2)
    ));
    var aoiOutsideLandFrac = safeFrac(aoiOutsideLandKm2, aoiAreaKm2);
    var outsideLandWarnFlag = safeGt(aoiOutsideLandFrac, OUTSIDE_LAND_WARN_FRAC);
    var recordsOutsideLand = aoiAreaLandKm2.lte(0).int();
    var recordsJoinedLand = recordsOutsideLand.not().int();

    var reasons = ee.List([]);
    reasons = ee.List(ee.Algorithms.If(unitBindingOk, reasons, reasons.add('unresolved_unit_identity')));
    reasons = ee.List(ee.Algorithms.If(parentBindingOk, reasons, reasons.add('unresolved_parent_identity')));
    reasons = ee.List(ee.Algorithms.If(recordsJoinedLand.eq(1), reasons, reasons.add('zero_land_intersection')));

    var excludeFlag = ee.Number(reasons.length().gt(0)).int();

    return ee.Feature(landGeom, {
      schema_version: RP1_SCHEMA_VERSION,
      level: LEVEL_VALUE,
      unit_id: unitId,
      unit_code: unitCode,
      unit_name: unitName,
      parent_level: PARENT_LEVEL_VALUE,
      parent_id: parentId,
      parent_code: parentCode,
      parent_name: parentName,

      canonical_unit_binding_ok_flag: ee.Number(unitBindingOk).int(),
      canonical_unit_binding_source: unitBindingSource,
      canonical_parent_binding_ok_flag: ee.Number(parentBindingOk).int(),
      canonical_parent_binding_source: parentBindingSource,
      parent_zone_binding_status: ee.String(ee.Algorithms.If(parentBindingOk, 'resolved', 'unresolved')),

      raw_dist_id: rawDistId,
      raw_dist_name: rawDistName,
      raw_dist_code: rawDistCode,
      raw_zone_id: rawZoneId,
      raw_zone_name: rawZoneName,
      raw_zone_code: rawZoneCode,
      raw_dist_id_source: rawDistIdInfo.get('source'),
      raw_dist_name_source: rawDistNameInfo.get('source'),
      raw_dist_code_source: rawDistCodeInfo.get('source'),
      raw_zone_id_source: rawZoneIdInfo.get('source'),
      raw_zone_name_source: rawZoneNameInfo.get('source'),
      raw_zone_code_source: rawZoneCodeInfo.get('source'),

      unit_code_available_flag: ee.Number(rawDistCode.length().gt(0)).int(),
      unit_code_blank_flag: ee.Number(rawDistCode.length().eq(0)).int(),
      unit_code_source_field: ee.String(ee.Algorithms.If(rawDistCode.length().gt(0), rawDistCodeInfo.get('source'), 'missing')),
      fallback_unit_id_if_unresolved: fallbackUnitId,

      aoi_area_km2: aoiAreaKm2,
      aoi_area_land_km2: aoiAreaLandKm2,
      aoi_outside_land_km2: aoiOutsideLandKm2,
      aoi_outside_land_frac: aoiOutsideLandFrac,
      outside_land_warn_flag: outsideLandWarnFlag,
      records_joined_land: recordsJoinedLand,
      records_outside_land: recordsOutsideLand,

      exclusion_reasons: joinWarnings(reasons),
      exclude_flag: excludeFlag
    });
  }));
}


// Drop-log export assembly for excluded districts.
// ============================== DROP LOG =====================================

// Build the excluded-district drop log with generic Stage 1 identity fields and explicit exclusion reasons.
function buildDropLog(unitsExcluded, zoneMeta) {
  unitsExcluded = ee.FeatureCollection(unitsExcluded);

  return ee.FeatureCollection(unitsExcluded.map(function(f) {
    f = ee.Feature(f);
    return ee.Feature(null, {
      schema_version: RP1_SCHEMA_VERSION,
      level: LEVEL_VALUE,
      unit_id: f.get('unit_id'),
      unit_code: f.get('unit_code'),
      unit_name: f.get('unit_name'),
      parent_level: PARENT_LEVEL_VALUE,
      parent_id: f.get('parent_id'),
      parent_code: f.get('parent_code'),
      parent_name: f.get('parent_name'),
      target_zone_id: zoneMeta.zone_id,
      target_zone_name: zoneMeta.zone_name,
      target_zone_code: zoneMeta.zone_code,
      district_source_mode: DISTRICT_SOURCE_MODE,

      canonical_unit_binding_ok_flag: f.get('canonical_unit_binding_ok_flag'),
      canonical_unit_binding_source: f.get('canonical_unit_binding_source'),
      canonical_parent_binding_ok_flag: f.get('canonical_parent_binding_ok_flag'),
      canonical_parent_binding_source: f.get('canonical_parent_binding_source'),
      raw_dist_id: f.get('raw_dist_id'),
      raw_dist_name: f.get('raw_dist_name'),
      raw_dist_code: f.get('raw_dist_code'),
      raw_zone_id: f.get('raw_zone_id'),
      raw_zone_name: f.get('raw_zone_name'),
      raw_zone_code: f.get('raw_zone_code'),

      exclusion_reasons: f.get('exclusion_reasons'),

      aoi_area_km2: f.get('aoi_area_km2'),
      aoi_area_land_km2: f.get('aoi_area_land_km2'),
      aoi_outside_land_km2: f.get('aoi_outside_land_km2'),
      aoi_outside_land_frac: f.get('aoi_outside_land_frac'),
      outside_land_warn_flag: f.get('outside_land_warn_flag'),
      records_joined_land: f.get('records_joined_land'),
      records_outside_land: f.get('records_outside_land'),

      unit_code_available_flag: f.get('unit_code_available_flag'),
      unit_code_blank_flag: f.get('unit_code_blank_flag'),
      unit_code_source_field: f.get('unit_code_source_field'),

      created_utc: CREATED_ISO,
      run_date: RUN_DATE_ISO
    });
  }));
}


// Client-side grouped QA summary rows and FC wrapper.
// ============================== QA SUMMARY ===================================

// Build grouped QA summary rows on the client for the selected ACZ.
function buildGroupedAczQaSummaryRowsClient(unitsPrep, unitsReady, zoneId) {
  var prepCount = ee.Number(unitsPrep.size()).getInfo() || 0;
  var readyCount = ee.Number(unitsReady.size()).getInfo() || 0;
  var excludedCount = prepCount - readyCount;
  var zeroLandCount = ee.Number(unitsPrep.filter(ee.Filter.eq('records_outside_land', 1)).size()).getInfo() || 0;
  var warnCount = ee.Number(unitsPrep.filter(ee.Filter.eq('outside_land_warn_flag', 1)).size()).getInfo() || 0;
  var unresolvedUnitCount = ee.Number(unitsPrep.filter(ee.Filter.eq('canonical_unit_binding_ok_flag', 0)).size()).getInfo() || 0;
  var unresolvedParentCount = ee.Number(unitsPrep.filter(ee.Filter.eq('canonical_parent_binding_ok_flag', 0)).size()).getInfo() || 0;
  var blankUnitCodeCount = ee.Number(unitsPrep.filter(ee.Filter.eq('unit_code_blank_flag', 1)).size()).getInfo() || 0;

  var zoneMeta = getZoneMeta(zoneId);

  return [{
    schema_version: RP1_SCHEMA_VERSION,
    level: LEVEL_VALUE,
    target_zone_id: zoneMeta.zone_id,
    target_zone_name: zoneMeta.zone_name,
    target_zone_code: zoneMeta.zone_code,
    district_source_mode: DISTRICT_SOURCE_MODE,
    prepared_district_count: prepCount,
    ready_district_count: readyCount,
    excluded_district_count: excludedCount,
    zero_land_district_count: zeroLandCount,
    outside_land_warn_count: warnCount,
    unresolved_unit_id_count: unresolvedUnitCount,
    unresolved_parent_count: unresolvedParentCount,
    blank_unit_code_count: blankUnitCodeCount,
    created_utc: CREATED_ISO_STR,
    run_date: CREATED_ISO_STR
  }];
}

// Convert grouped QA summary row objects into a FeatureCollection for export.
function qaRowsToFeatureCollection(rows) {
  var feats = rows.map(function(r) { return ee.Feature(null, r); });
  return ee.FeatureCollection(feats);
}


// Client-side identifier collision checks and FC wrapper.
// =========================== COLLISION CHECKS ================================

// Build collision summary rows client-side so one unit_id cannot map to multiple names/codes/parents.
function buildCollisionSummaryRowsClient(unitsReady, zoneMeta) {
  var unitIds = clientAggregateArray(unitsReady, 'unit_id') || [];
  var unitCodes = clientAggregateArray(unitsReady, 'unit_code') || [];
  var unitNames = clientAggregateArray(unitsReady, 'unit_name') || [];
  var parentIds = clientAggregateArray(unitsReady, 'parent_id') || [];
  var parentCodes = clientAggregateArray(unitsReady, 'parent_code') || [];
  var parentNames = clientAggregateArray(unitsReady, 'parent_name') || [];

  var acc = {};

  for (var i = 0; i < unitIds.length; i++) {
    var k = String(unitIds[i] || '');
    if (!k) continue;
    if (!acc[k]) {
      acc[k] = {
        unit_codes: {},
        unit_names: {},
        parent_ids: {},
        parent_codes: {},
        parent_names: {}
      };
    }
    acc[k].unit_codes[String(unitCodes[i] || '')] = 1;
    acc[k].unit_names[String(unitNames[i] || '')] = 1;
    acc[k].parent_ids[String(parentIds[i] || '')] = 1;
    acc[k].parent_codes[String(parentCodes[i] || '')] = 1;
    acc[k].parent_names[String(parentNames[i] || '')] = 1;
  }

  var rows = [];
  Object.keys(acc).sort().forEach(function(unitId) {
    var item = acc[unitId];
    var unitCodesList = Object.keys(item.unit_codes).sort();
    var unitNamesList = Object.keys(item.unit_names).sort();
    var parentIdsList = Object.keys(item.parent_ids).sort();
    var parentCodesList = Object.keys(item.parent_codes).sort();
    var parentNamesList = Object.keys(item.parent_names).sort();

    var collisionFlag =
      (unitCodesList.length > 1) ||
      (unitNamesList.length > 1) ||
      (parentIdsList.length > 1) ||
      (parentCodesList.length > 1) ||
      (parentNamesList.length > 1) ? 1 : 0;

    rows.push({
      schema_version: RP1_SCHEMA_VERSION,
      level: LEVEL_VALUE,
      target_zone_id: zoneMeta.zone_id,
      target_zone_name: zoneMeta.zone_name,
      target_zone_code: zoneMeta.zone_code,
      unit_id: unitId,
      unit_codes_pipe: unitCodesList.join('|'),
      unit_names_pipe: unitNamesList.join('|'),
      parent_ids_pipe: parentIdsList.join('|'),
      parent_codes_pipe: parentCodesList.join('|'),
      parent_names_pipe: parentNamesList.join('|'),
      collision_flag: collisionFlag,
      created_utc: CREATED_ISO_STR,
      run_date: CREATED_ISO_STR
    });
  });

  return rows;
}

// Convert collision summary row objects into a FeatureCollection for inspection/export.
function collisionRowsToFeatureCollection(rows) {
  var feats = rows.map(function(r) { return ee.Feature(null, r); });
  return ee.FeatureCollection(feats);
}


// Client-side district UI option builder.
// ============================== UI OPTIONS ===================================

// Build a stable district dropdown list from the ready district set.
function buildDistrictUiOptionsClient(unitsReady) {
  var unitIds = clientAggregateArray(unitsReady, 'unit_id') || [];
  var unitNames = clientAggregateArray(unitsReady, 'unit_name') || [];
  var unitCodes = clientAggregateArray(unitsReady, 'unit_code') || [];

  var out = [];
  for (var i = 0; i < unitIds.length; i++) {
    var unitId = String(unitIds[i] || '');
    if (!unitId) continue;
    var unitName = String(unitNames[i] || '');
    var unitCode = String(unitCodes[i] || '');
    var label = unitName + (unitCode ? ' (' + unitCode + ')' : '') + ' — ' + unitId;
    out.push({unit_id: unitId, label: label});
  }

  out.sort(function(a, b) {
    return a.label.localeCompare(b.label);
  });

  return out;
}


// DISTRICT CONTEXT BUILDER (v4 core)
// ===================== DISTRICT CONTEXT BUILDER (v4 core) ====================

// Core context builder for one selected ACZ: prepares units, denominators, grouped QA, previews, selectors, and export metadata.
function buildDistrictContext(zoneId, maskMode) {
  zoneId = ZONE_BY_ID_OBJ[zoneId] ? zoneId : DEFAULT_ZONE_ID;
  maskMode = FIXED_BA_MASK_MODE;

  var zoneMeta = getZoneMeta(zoneId);
  var maskCfg = getBaMaskConfig(maskMode);
  var districtFc = zoneFcFromMode(zoneId, DISTRICT_SOURCE_MODE);

  var aoiGeom_raw = cleanGeom(districtFc.geometry());
  var aoiGeom_land = cleanGeom(aoiGeom_raw.intersection(GHANA_LAND, 1));

  var AOI_AREA_KM2_RAW = ee.Number(aoiGeom_raw.area({maxError: 1})).divide(1e6);
  var AOI_AREA_KM2_LAND = ee.Number(aoiGeom_land.area({maxError: 1})).divide(1e6);
  var AOI_OUTSIDE_LAND_KM2 = ee.Number(ee.Algorithms.If(
    AOI_AREA_KM2_RAW.subtract(AOI_AREA_KM2_LAND).lt(0),
    0,
    AOI_AREA_KM2_RAW.subtract(AOI_AREA_KM2_LAND)
  ));
  var AOI_OUTSIDE_LAND_FRAC = safeFrac(AOI_OUTSIDE_LAND_KM2, AOI_AREA_KM2_RAW);

  var unitsPrep = prepareDistrictUnits(districtFc);
  var unitsReady = unitsPrep.filter(ee.Filter.eq('exclude_flag', 0));
  var unitsExcluded = unitsPrep.filter(ee.Filter.eq('exclude_flag', 1));

  var readyCountInfo = ee.Number(unitsReady.size()).getInfo();
  var excludedCountInfo = ee.Number(unitsExcluded.size()).getInfo();
  var zeroLandCountInfo = ee.Number(unitsPrep.filter(ee.Filter.eq('records_outside_land', 1)).size()).getInfo();
  var warnCountInfo = ee.Number(unitsPrep.filter(ee.Filter.eq('outside_land_warn_flag', 1)).size()).getInfo();
  var unresolvedUnitCountInfo = ee.Number(unitsPrep.filter(ee.Filter.eq('canonical_unit_binding_ok_flag', 0)).size()).getInfo();
  var unresolvedParentCountInfo = ee.Number(unitsPrep.filter(ee.Filter.eq('canonical_parent_binding_ok_flag', 0)).size()).getInfo();

  var dropLog = buildDropLog(unitsExcluded, zoneMeta);
  var qaRowsClient = buildGroupedAczQaSummaryRowsClient(unitsPrep, unitsReady, zoneId);
  var qaByAcz = qaRowsToFeatureCollection(qaRowsClient);

  var collisionSummaryRowsClient = buildCollisionSummaryRowsClient(unitsReady, zoneMeta);
  var collisionRowsClient = collisionSummaryRowsClient.filter(function(row) {
    return row.collision_flag === 1;
  });
  if (collisionRowsClient.length > 0) {
    print(ee.Dictionary({message: 'Identifier collision rows detected'}));
    print(collisionRowsToFeatureCollection(collisionRowsClient));
    throw new Error('Identifier collision check failed: one unit_id maps to multiple unit_name, unit_code, parent_id, parent_name, or parent_code values.');
  }

  var districtUiOptions = buildDistrictUiOptionsClient(unitsReady);

  var DENOMINATOR_DEFINITION = ee.String(
    'Burnable UNION denominator: OR across annual burnable masks for ' + DENOM_YEAR_RANGE_TEXT +
    ', where annual burnable = (LC_Type1 in [' + LC_INCLUDE_TEXT + ']) AND (' + maskCfg.keepSummary + ').'
  );

  var ANNUAL_DENOMINATOR_DEFINITION = ee.String(
    'Burnable ANNUAL denominator: exact matching MCD12Q1 year; annual burnable = (LC_Type1 in [' + LC_INCLUDE_TEXT +
    ']) AND (' + maskCfg.keepSummary + '). No nearest-year fallback is allowed.'
  );

  var ANNUAL_LAND_DEFINITION = ee.String(
    'Annual baseline keep-mask support: exact-year MCD12Q1 pixels where ' + maskCfg.keepSummary + '.'
  );

  var MONTHLY_BA_DEFINITION = ee.String(
    'Monthly burned pixels: for each month, burned = BurnDate > 0 in ANY MCD64A1 image overlapping the month ' +
    '(pixel-wise OR via max over per-image burned masks), then restricted to the fixed union burnable denominator.'
  );

  var WATER_MASK_DEFINITION = ee.String(
    'Frozen c1 BA mask mode = ' + maskCfg.key + '; ' + maskCfg.excludedSummary + '.'
  );

  var BURN_UNION = buildBurnableUnionExact(TARGET_YEARS, maskMode);
  var ZONE_BURNABLE_KM2_UNION = areaMaskedKm2(BURN_UNION.clip(aoiGeom_land), aoiGeom_land);

// Attach fixed UNION denominator area/pixel-count fields to each ready district.
  function addUnionDenominators(fc, burnUnion) {
    var unionAreaImg = PIXEL_AREA_KM2_IMPACT.updateMask(burnUnion).rename('burnable_km2_union');
    var unionPcImg = mask01(burnUnion).rename('burnable_pixel_count_union');

    var reduced = unionAreaImg.addBands(unionPcImg).reduceRegions({
      collection: fc,
      reducer: ee.Reducer.sum().unweighted(),
      scale: SCALE_BA,
      crs: IMPACT_CRS,
      tileScale: TILE_SCALE
    });

    return ee.FeatureCollection(reduced.map(function(f) {
      f = ee.Feature(f);
      var unionKm2 = safeNumber(f.get('burnable_km2_union'), 0);
      var unionPc = safeNumber(f.get('burnable_pixel_count_union'), 0);
      return f.set({
        burnable_km2_union: unionKm2,
        burnable_pixel_count_union: unionPc,
        zero_union_den_flag: unionKm2.lte(0).int(),
        small_den: unionKm2.lt(SMALL_DEN_THRESHOLD_KM2).int(),
        denom_years_used_pipe: DENOM_YEARS_USED_PIPE,
        denom_missing_years_count: DENOM_MISSING_YEARS_COUNT,
        denom_missing_years_pipe: DENOM_MISSING_YEARS_PIPE
      });
    }));
  }

// Attach the independent union-denominator audit fields to each ready district.
  function addUnionDenomAudit(fc, burnUnion) {
    return ee.FeatureCollection(fc.map(function(f) {
      f = ee.Feature(f);
      var geom = f.geometry();
      var denomReported = ee.Number(f.get('burnable_km2_union'));
      var denomCheck = areaMaskedKm2Audit(burnUnion.clip(geom), geom);
      var audit = driftAudit(denomReported, denomCheck);

      return f.set({
        denom_km2_check: denomCheck,
        denom_abs_diff_km2: audit.get('abs_diff_km2'),
        denom_rel_diff: audit.get('rel_diff'),
        denom_drift_thresh_km2: audit.get('thresh_km2'),
        denom_drift_tol_abs_km2: DENOM_DRIFT_TOL_ABS_KM2,
        denom_drift_tol_rel_frac: DENOM_DRIFT_TOL_REL_FRAC,
        denom_drift_flag: audit.get('flag')
      });
    }));
  }

// Build district-level annual denominator rows for one year, including annual land area and annual denominator drift checks.
  function annualDenomRowsForYear(targetYear, unitsDenom) {
    targetYear = ee.Number(targetYear).int();
    var annualLand = annualLandMaskForYear(targetYear);
    var annualBurnable = annualBurnableMaskForYear(targetYear, maskMode);

    var annualAreaImg = PIXEL_AREA_KM2_IMPACT.updateMask(annualBurnable).rename('burnable_km2_annual');
    var annualPcImg = mask01(annualBurnable).rename('burnable_pixel_count_annual');
    var annualLandAreaImg = PIXEL_AREA_KM2_IMPACT.updateMask(annualLand).rename('annual_land_km2');
    var annualLandPcImg = mask01(annualLand).rename('annual_land_pixel_count');

    var reduced = annualAreaImg.addBands(annualPcImg)
      .addBands(annualLandAreaImg)
      .addBands(annualLandPcImg)
      .reduceRegions({
        collection: unitsDenom,
        reducer: ee.Reducer.sum().unweighted(),
        scale: SCALE_BA,
        crs: IMPACT_CRS,
        tileScale: TILE_SCALE
      });

    return ee.FeatureCollection(reduced.map(function(f) {
      f = ee.Feature(f);
      var geom = f.geometry();
      var annualKm2 = safeNumber(f.get('burnable_km2_annual'), 0);
      var annualPc = safeNumber(f.get('burnable_pixel_count_annual'), 0);
      var annualLandKm2 = safeNumber(f.get('annual_land_km2'), 0);
      var annualLandPc = safeNumber(f.get('annual_land_pixel_count'), 0);
      var zeroAnnualDenFlag = annualKm2.lte(0).int();
      var denomAnnualCheck = areaMaskedKm2Audit(annualBurnable.clip(geom), geom);
      var audit = driftAudit(annualKm2, denomAnnualCheck);

      return ee.Feature(null, {
        unit_id: f.get('unit_id'),
        year: targetYear,
        denom_year_target: targetYear,
        denom_year_used: targetYear,
        denom_year_fallback_flag: 0,
        annual_land_km2: annualLandKm2,
        annual_land_pixel_count: annualLandPc,
        burnable_km2_annual: annualKm2,
        burnable_pixel_count_annual: annualPc,
        zero_annual_den_flag: zeroAnnualDenFlag,
        denom_annual_km2_check: denomAnnualCheck,
        denom_annual_abs_diff_km2: audit.get('abs_diff_km2'),
        denom_annual_rel_diff: audit.get('rel_diff'),
        denom_annual_drift_thresh_km2: audit.get('thresh_km2'),
        denom_annual_drift_flag: audit.get('flag')
      });
    }));
  }

  var unitsUnion = addUnionDenominators(unitsReady, BURN_UNION);
  var unitsDenom = addUnionDenomAudit(unitsUnion, BURN_UNION);

  var annualDenomTable = ee.FeatureCollection(TARGET_YEARS.map(function(y) {
    return annualDenomRowsForYear(y, unitsDenom);
  })).flatten();

  var MAIN_SELECTORS = RP1_BASE_SELECTORS;
  var EXT_SELECTORS = RP1_EXT_SELECTORS;

  var startYM = RP1_EXPORT_START_LABEL;
  var endYM = RP1_EXPORT_END_LABEL;
  var zoneSlug = zoneMeta.zone_code.replace(/[^A-Za-z0-9]+/g, '_');
  var maskSlug = maskCfg.shortCode.replace(/[^A-Za-z0-9]+/g, '_');

  var mainFilePrefix = FILE_PREFIX_BASE + '_' + zoneSlug + '_' + maskSlug + '_' + startYM + '_to_' + endYM;
  var extFilePrefix  = mainFilePrefix + '_ext';
  var dropFilePrefix = mainFilePrefix + '_drop_log';
  var qaFilePrefix   = mainFilePrefix + '_qa_by_acz';

  return {
    zoneId: zoneId,
    zoneMeta: zoneMeta,
    maskMode: maskMode,
    maskCfg: maskCfg,
    districtFc: districtFc,
    aoiGeomRaw: aoiGeom_raw,
    aoiGeomLand: aoiGeom_land,
    aoiAreaKm2Raw: AOI_AREA_KM2_RAW,
    aoiAreaKm2Land: AOI_AREA_KM2_LAND,
    aoiOutsideLandKm2: AOI_OUTSIDE_LAND_KM2,
    aoiOutsideLandFrac: AOI_OUTSIDE_LAND_FRAC,

    unitsPrep: unitsPrep,
    unitsReady: unitsReady,
    unitsExcluded: unitsExcluded,
    unitsDenom: unitsDenom,
    annualDenomTable: annualDenomTable,
    dropLog: dropLog,
    qaByAcz: qaByAcz,

    readyCountInfo: readyCountInfo,
    excludedCountInfo: excludedCountInfo,
    zeroLandCountInfo: zeroLandCountInfo,
    warnCountInfo: warnCountInfo,
    unresolvedUnitCountInfo: unresolvedUnitCountInfo,
    unresolvedParentCountInfo: unresolvedParentCountInfo,

    districtUiOptions: districtUiOptions,

    burnUnion: BURN_UNION,
    zoneBurnableKm2Union: ZONE_BURNABLE_KM2_UNION,

    zoneBoundaryImage: getBoundaryImage(districtFc, 2),
    readyDistrictBoundaryImage: getBoundaryImage(unitsReady, 1),
    excludedDistrictBoundaryImage: getBoundaryImage(unitsExcluded, 1),

    mainSelectors: MAIN_SELECTORS,
    extSelectors: EXT_SELECTORS,
    mainFilePrefix: mainFilePrefix,
    extFilePrefix: extFilePrefix,
    dropFilePrefix: dropFilePrefix,
    qaFilePrefix: qaFilePrefix,
    hasExportUnitsInfo: readyCountInfo > 0,

    denominatorDefinition: DENOMINATOR_DEFINITION,
    annualDenominatorDefinition: ANNUAL_DENOMINATOR_DEFINITION,
    annualLandDefinition: ANNUAL_LAND_DEFINITION,
    monthlyBaDefinition: MONTHLY_BA_DEFINITION,
    waterMaskDefinition: WATER_MASK_DEFINITION,
    previewMonthsCount: ee.Number(MONTHS_ALL.length())
  };
}

// Build the full district-month export table by combining monthly BA numerators with district denominators and annual QA fields.
function buildDistrictRowsForExport(ctx) {
  var zoneMeta = ctx.zoneMeta;
  var maskCfg = ctx.maskCfg;
  var unitsDenom = ctx.unitsDenom;
  var annualDenomTable = ctx.annualDenomTable;
  var BURN_UNION = ctx.burnUnion;

// Compute the Ghana-wide monthly burned-area reference used for the zero-local-but-national-BA diagnostic.
  function nationalBaKm2(start, end) {
    var burnedAny = monthlyBurnedMaskOr(start, end)
      .updateMask(BURN_UNION)
      .clip(GHANA_LAND);
    return areaMaskedKm2(burnedAny, GHANA_LAND);
  }

  return ee.FeatureCollection(MONTHS_ALL.map(function(md) {
    md = ee.Dictionary(md);
    var start = ee.Date(md.get('start'));
    var end = ee.Date(md.get('end'));
    var parts = dateParts(start);
    var monthYear = ee.Number(parts.get('year')).int();
    var monthYYYYMM = ee.Number(parts.get('yyyymm')).int();

    var burnedOnUnion = monthlyBurnedMaskOr(start, end).updateMask(BURN_UNION);

    var baImg = PIXEL_AREA_KM2_IMPACT.updateMask(burnedOnUnion).rename('ba_km2');
    var pcImg = mask01(burnedOnUnion).rename('burned_pixel_count');
    var natBaKm2 = nationalBaKm2(start, end);

    var reduced = baImg.addBands(pcImg).reduceRegions({
      collection: unitsDenom,
      reducer: ee.Reducer.sum().unweighted(),
      scale: SCALE_BA,
      crs: IMPACT_CRS,
      tileScale: TILE_SCALE
    });

    var annualForYear = annualDenomTable.filter(ee.Filter.eq('year', monthYear));
    var joined = ee.Join.saveFirst('annual').apply({
      primary: reduced,
      secondary: annualForYear,
      condition: ee.Filter.equals({leftField: 'unit_id', rightField: 'unit_id'})
    });

    return ee.FeatureCollection(joined.map(function(f) {
      f = ee.Feature(f);
      var annualObj = f.get('annual');

      var baKm2 = safeNumber(f.get('ba_km2'), 0);
      var burnedPixelCount = safeNumber(f.get('burned_pixel_count'), 0);
      var baAny = baKm2.gt(0).int();

      var burnableKm2Union = ee.Number(f.get('burnable_km2_union'));
      var burnedFracUnion = ee.Algorithms.If(burnableKm2Union.gt(0), baKm2.divide(burnableKm2Union), null);

      var annualLandKm2 = ee.Number(annualFieldOrDefault(annualObj, 'annual_land_km2', 0));
      var annualLandPc = ee.Number(annualFieldOrDefault(annualObj, 'annual_land_pixel_count', 0));
      var burnableKm2Annual = ee.Number(annualFieldOrDefault(annualObj, 'burnable_km2_annual', 0));
      var burnablePixelCountAnnual = ee.Number(annualFieldOrDefault(annualObj, 'burnable_pixel_count_annual', 0));
      var zeroAnnualDenFlag = ee.Number(annualFieldOrDefault(annualObj, 'zero_annual_den_flag', 1)).int();
      var denomYearTarget = ee.Number(annualFieldOrDefault(annualObj, 'denom_year_target', monthYear)).int();
      var denomYearUsed = ee.Number(annualFieldOrDefault(annualObj, 'denom_year_used', monthYear)).int();
      var denomYearFallbackFlag = ee.Number(annualFieldOrDefault(annualObj, 'denom_year_fallback_flag', 0)).int();
      var burnedFracAnnual = ee.Algorithms.If(burnableKm2Annual.gt(0), baKm2.divide(burnableKm2Annual), null);

      var denomAnnualKm2Check = ee.Number(annualFieldOrDefault(annualObj, 'denom_annual_km2_check', 0));
      var denomAnnualAbsDiffKm2 = ee.Number(annualFieldOrDefault(annualObj, 'denom_annual_abs_diff_km2', 0));
      var denomAnnualRelDiff = annualFieldOrDefault(annualObj, 'denom_annual_rel_diff', null);
      var denomAnnualDriftThreshKm2 = ee.Number(annualFieldOrDefault(annualObj, 'denom_annual_drift_thresh_km2', 0));
      var denomAnnualDriftFlag = ee.Number(annualFieldOrDefault(annualObj, 'denom_annual_drift_flag', 1)).int();
      var denomAnyDriftFlag = ee.Number(f.get('denom_drift_flag')).max(denomAnnualDriftFlag).int();

      var zeroLocalButNationalBa = ee.Number(ee.Algorithms.If(baKm2.eq(0).and(ee.Number(natBaKm2).gt(0)), 1, 0)).int();
      var partialViirsOverlapFlag = ee.Number(monthYYYYMM.eq(PARTIAL_VIIRS_OVERLAP_YYYYMM)).int();

      return ee.Feature(null, {
        run_id: RUN_STAMP.cat('_').cat(LEVEL_VALUE).cat('_').cat(zoneMeta.zone_code).cat('_').cat(maskCfg.shortCode),
        schema_version: f.get('schema_version'),
        level: f.get('level'),
        unit_id: f.get('unit_id'),
        unit_code: f.get('unit_code'),
        unit_name: f.get('unit_name'),
        parent_level: f.get('parent_level'),
        parent_id: f.get('parent_id'),
        parent_code: f.get('parent_code'),
        parent_name: f.get('parent_name'),
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
        modis_aoi_area_land_km2: f.get('aoi_area_land_km2'),
        modis_zero_union_den_flag: f.get('zero_union_den_flag'),
        modis_zero_annual_den_flag: zeroAnnualDenFlag,

        annual_land_km2: annualLandKm2,
        annual_land_pixel_count: annualLandPc,
        burnable_pixel_count_union: f.get('burnable_pixel_count_union'),
        burnable_pixel_count_annual: burnablePixelCountAnnual,

        aoi_area_km2: f.get('aoi_area_km2'),
        aoi_outside_land_km2: f.get('aoi_outside_land_km2'),
        aoi_outside_land_frac: f.get('aoi_outside_land_frac'),
        outside_land_warn_flag: f.get('outside_land_warn_flag'),
        records_joined_land: f.get('records_joined_land'),
        records_outside_land: f.get('records_outside_land'),

        canonical_unit_binding_ok_flag: f.get('canonical_unit_binding_ok_flag'),
        canonical_unit_binding_source: f.get('canonical_unit_binding_source'),
        canonical_parent_binding_ok_flag: f.get('canonical_parent_binding_ok_flag'),
        canonical_parent_binding_source: f.get('canonical_parent_binding_source'),
        parent_zone_binding_status: f.get('parent_zone_binding_status'),
        raw_dist_id: f.get('raw_dist_id'),
        raw_dist_name: f.get('raw_dist_name'),
        raw_dist_code: f.get('raw_dist_code'),
        raw_zone_id: f.get('raw_zone_id'),
        raw_zone_name: f.get('raw_zone_name'),
        raw_zone_code: f.get('raw_zone_code'),
        raw_dist_id_source: f.get('raw_dist_id_source'),
        raw_dist_name_source: f.get('raw_dist_name_source'),
        raw_dist_code_source: f.get('raw_dist_code_source'),
        raw_zone_id_source: f.get('raw_zone_id_source'),
        raw_zone_name_source: f.get('raw_zone_name_source'),
        raw_zone_code_source: f.get('raw_zone_code_source'),
        unit_code_available_flag: f.get('unit_code_available_flag'),
        unit_code_blank_flag: f.get('unit_code_blank_flag'),
        unit_code_source_field: f.get('unit_code_source_field'),
        fallback_unit_id_if_unresolved: f.get('fallback_unit_id_if_unresolved'),

        small_den: f.get('small_den'),

        denom_year_target: denomYearTarget,
        denom_year_used: denomYearUsed,
        denom_year_fallback_flag: denomYearFallbackFlag,
        denom_years_used_pipe: f.get('denom_years_used_pipe'),
        denom_missing_years_count: f.get('denom_missing_years_count'),
        denom_missing_years_pipe: f.get('denom_missing_years_pipe'),

        zero_local_but_national_ba: zeroLocalButNationalBa,
        partial_viirs_overlap_flag: partialViirsOverlapFlag,
        denom_km2_check: f.get('denom_km2_check'),
        denom_abs_diff_km2: f.get('denom_abs_diff_km2'),
        denom_rel_diff: f.get('denom_rel_diff'),
        denom_drift_thresh_km2: f.get('denom_drift_thresh_km2'),
        denom_drift_tol_abs_km2: f.get('denom_drift_tol_abs_km2'),
        denom_drift_tol_rel_frac: f.get('denom_drift_tol_rel_frac'),
        denom_drift_flag: f.get('denom_drift_flag'),
        denom_annual_km2_check: denomAnnualKm2Check,
        denom_annual_abs_diff_km2: denomAnnualAbsDiffKm2,
        denom_annual_rel_diff: denomAnnualRelDiff,
        denom_annual_drift_thresh_km2: denomAnnualDriftThreshKm2,
        denom_annual_drift_flag: denomAnnualDriftFlag,
        denom_any_drift_flag: denomAnyDriftFlag,

        impact_product_id: IMPACT_PRODUCT_ID,
        impact_band_used_for_ba: IMPACT_BAND_BURNDATE,
        impact_bands_recognised_pipe: IMPACT_BANDS_RECOGNISED.join('|'),
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
        ba_mask_mode: maskCfg.key,
        ba_mask_short_code: maskCfg.shortCode,
        ba_mask_layer_label: maskCfg.layerLabel,
        ba_mask_keep_summary: maskCfg.keepSummary,
        ba_mask_excluded_summary: maskCfg.excludedSummary,
        water_mask_definition: ctx.waterMaskDefinition,
        lc_include_pipe: LC_INCLUDE_TEXT,

        reducer_type: REDUCER_TYPE,
        reducer_weighting: REDUCER_WEIGHTING,
        reducer_scale_m: SCALE_BA,
        reducer_tileScale: TILE_SCALE,
        reducer_maxPixels: MAX_PIXELS,
        reduction_crs: IMPACT_CRS,
        reduction_nominal_scale_m: IMPACT_NOMINAL_SCALE_M,

        denominator_definition: ctx.denominatorDefinition,
        annual_denominator_definition: ctx.annualDenominatorDefinition,
        annual_land_definition: ctx.annualLandDefinition,
        monthly_ba_definition: ctx.monthlyBaDefinition,
        date_window_method_note: ee.String(
          'Analytical backbone window: ' + STUDY_WINDOW_TEXT +
          ' (START inclusive, END exclusive). RP1 export window: ' + RP1_EXPORT_WINDOW_TEXT +
          '. Denominator year range: ' + DENOM_YEAR_RANGE_TEXT + '.'
        ),

        target_zone_id: zoneMeta.zone_id,
        target_zone_name: zoneMeta.zone_name,
        target_zone_code: zoneMeta.zone_code,
        district_source_mode: DISTRICT_SOURCE_MODE,

        created_utc: CREATED_ISO,
        run_date: RUN_DATE_ISO,
        start: START,
        end_exclusive: END,
        months_count: ee.Number(MONTHS_ALL.length())
      });
    }));
  })).flatten();
}


// Helpers that generate the map layers for LC, excluded mask, burnable support, and monthly BA previews.
// ============================ PREVIEW HELPERS ================================

// Preview helper: selected-year LC_Type1 layer clipped to the current ACZ.
function getLcPreviewImage(ctx, year) {
  return mcd12ImageForYearExact(year)
    .select(DENOM_BAND_LC_TYPE1)
    .clip(ctx.aoiGeomLand);
}

// Preview helper: selected-year excluded-mask layer under the frozen c1 baseline.
function getExcludedPreviewImage(ctx, year) {
  return annualBaExcludedMaskForYear(year, ctx.maskMode).clip(ctx.aoiGeomLand);
}

// Preview helper: fixed union burnable denominator layer.
function getUnionPreviewImage(ctx) {
  return ctx.burnUnion.clip(ctx.aoiGeomLand);
}

// Preview helper: selected-year annual burnable denominator layer.
function getAnnualBurnablePreviewImage(ctx, year) {
  return annualBurnableMaskForYear(year, ctx.maskMode).clip(ctx.aoiGeomLand);
}

// Preview helper: selected month either as BurnMask or BurnDate, always restricted to the fixed UNION denominator.
function getMonthlyBurnPreviewImage(ctx, year, month, displayMode) {
  var w = monthWindow(year, month);
  if (displayMode === 'BurnDate') {
    return monthlyBurnDateMax(w.start, w.end)
      .updateMask(ctx.burnUnion)
      .clip(ctx.aoiGeomLand);
  }
  return monthlyBurnedMaskOr(w.start, w.end)
    .updateMask(ctx.burnUnion)
    .clip(ctx.aoiGeomLand);
}

// Preview helper: highlight the currently selected district without affecting exports.
function getSelectedDistrictBoundaryImage(ctx, districtId) {
  if (!districtId) {
    return ee.Image(0).selfMask();
  }
  var sel = ee.FeatureCollection(ctx.unitsReady).filter(ee.Filter.eq('unit_id', districtId));
  return getBoundaryImage(sel, 2);
}


// Button-triggered export helpers for selected-ACZ and all-ACZ district bundles.
// ============================= EXPORT HELPERS ================================

// Queue Drive CSV exports for one ACZ: drop-log (if needed), grouped QA, analytical rows, and ext/provenance rows.
function exportDistrictTables(ctx) {
  if (!ENABLE_EXPORTS) {
    print(ee.Dictionary({message: 'Exports disabled', zone_id: ctx.zoneMeta.zone_id}));
    return;
  }

  print(ee.Dictionary({
    message: 'Queueing district export bundle',
    zone_id: ctx.zoneMeta.zone_id,
    zone_code: ctx.zoneMeta.zone_code,
    mask_mode: ctx.maskCfg.key,
    district_source_mode: DISTRICT_SOURCE_MODE,
    ready_district_count: ctx.readyCountInfo,
    excluded_district_count: ctx.excludedCountInfo
  }));

  if (ctx.excludedCountInfo > 0) {
    Export.table.toDrive({
      collection: ctx.dropLog,
      description: ctx.dropFilePrefix,
      folder: EXPORT_FOLDER,
      fileNamePrefix: ctx.dropFilePrefix,
      fileFormat: 'CSV'
    });
  }

  Export.table.toDrive({
    collection: ctx.qaByAcz,
    description: ctx.qaFilePrefix,
    folder: EXPORT_FOLDER,
    fileNamePrefix: ctx.qaFilePrefix,
    fileFormat: 'CSV'
  });

  if (!ctx.hasExportUnitsInfo) {
    print(ee.Dictionary({message: 'STOP: no districts remain for main/ext export after strict exclusion rules.', zone_id: ctx.zoneMeta.zone_id}));
    return;
  }

  var rows = filterToRp1ExportWindow(buildDistrictRowsForExport(ctx));

  Export.table.toDrive({
    collection: rows.select(ctx.mainSelectors),
    description: ctx.mainFilePrefix,
    folder: EXPORT_FOLDER,
    fileNamePrefix: ctx.mainFilePrefix,
    fileFormat: 'CSV',
    selectors: ctx.mainSelectors
  });

  Export.table.toDrive({
    collection: rows.select(ctx.extSelectors),
    description: ctx.extFilePrefix,
    folder: EXPORT_FOLDER,
    fileNamePrefix: ctx.extFilePrefix,
    fileFormat: 'CSV',
    selectors: ctx.extSelectors
  });
}

// Queue exports for the ACZ currently selected in the UI.
function exportSelectedDistrictTables() {
  var ctx = currentCtx || buildDistrictContext(state.zoneId, state.maskMode);
  exportDistrictTables(ctx);
}

// Queue the same export bundle for every canonical ACZ in turn under the frozen c1 method.
function exportAllDistrictZoneTables() {
  for (var i = 0; i < CANONICAL_ZONES.length; i++) {
    var zoneId = CANONICAL_ZONES[i].zone_id;
    var ctx = buildDistrictContext(zoneId, state.maskMode);
    exportDistrictTables(ctx);
  }
}


// Client-side UI state: selected ACZ, highlighted district, preview date, and layer visibility toggles.
// ============================== UI STATE =====================================

// UI state object. The district script is fixed-method, but preview settings still live here.
var state = {
  zoneId: DEFAULT_ZONE_ID,
  selectedDistrictId: '',
  year: 2024,
  month: 1,
  maskMode: 'LW_OR_LC17',
  burnDisplayMode: 'BurnMask',

  showZoneBoundary: true,
  showDistrictBoundaries: true,
  showSelectedDistrict: true,
  showLc: false,
  showExcluded: false,
  showUnion: false,
  showAnnualBurnable: false,
  showBa: true,
  showLegend: true
};

var currentCtx = null;
var currentCtxKey = null;
var currentCenteredZoneId = null;
var injectedYearStackLayers = [];
var suppressDistrictSelectChange = false;
var DISTRICT_LABEL_TO_ID = {};
var DISTRICT_ID_TO_LABEL = {};


// Map-layer initialisation for boundaries, LC, excluded mask, denominator previews, and monthly BA.
// ============================ MAP / LAYER SETUP ==============================

Map.setOptions('SATELLITE');

var zoneBoundaryLayer = ui.Map.Layer(ee.Image(0), ZONE_BOUNDARY_VIS, 'Selected ACZ boundary', true);
var districtBoundaryLayer = ui.Map.Layer(ee.Image(0), DISTRICT_BOUNDARY_VIS, 'Ready district boundaries', true);
var selectedDistrictLayer = ui.Map.Layer(ee.Image(0), SELECTED_DISTRICT_VIS, 'Selected district outline', true);
var lcLayer = ui.Map.Layer(ee.Image(0), LC_VIS, 'LC_Type1', false, LC_OPACITY);
var excludedLayer = ui.Map.Layer(ee.Image(0), EXCLUDED_VIS, 'Excluded mask', false, WATER_OPACITY);
var unionLayer = ui.Map.Layer(ee.Image(0), UNION_VIS, 'Union burnable', false, UNION_OPACITY);
var annualBurnableLayer = ui.Map.Layer(ee.Image(0), UNION_VIS, 'Annual burnable', false, UNION_OPACITY);
var baLayer = ui.Map.Layer(ee.Image(0), BURNMASK_VIS, 'Monthly burned area', true, BA_OPACITY);

Map.layers().reset([
  lcLayer,
  excludedLayer,
  unionLayer,
  annualBurnableLayer,
  baLayer,
  districtBoundaryLayer,
  zoneBoundaryLayer,
  selectedDistrictLayer
]);


// =============================== LEGEND ======================================

var legendPanel = ui.Panel({
  style: {
    position: 'top-right',
    padding: '8px',
    width: '300px',
    shown: state.showLegend,
    backgroundColor: 'rgba(255,255,255,0.9)'
  }
});

// Build one legend row consisting of a colour swatch and label.
function legendRow(color, label) {
  var box = ui.Label('', {
    backgroundColor: color,
    padding: '8px',
    margin: '0 8px 4px 0'
  });
  var txt = ui.Label(label, {margin: '0 0 4px 0', fontSize: '11px'});
  return ui.Panel([box, txt], ui.Panel.Layout.flow('horizontal'));
}

// Rebuild the legend so it reflects the current year/month preview and always documents the frozen baseline.
function refreshLegend() {
  legendPanel.clear();
  legendPanel.add(ui.Label({
    value: 'Legend',
    style: {fontWeight: 'bold', margin: '0 0 6px 0'}
  }));
  legendPanel.add(ui.Label({
    value: 'Preview year ' + state.year + ' — month ' + pad2(state.month),
    style: {fontSize: '11px', margin: '0 0 6px 0'}
  }));
  legendPanel.add(ui.Label({
    value: 'Frozen baseline: ' + FIXED_BA_MASK_MODE,
    style: {fontSize: '11px', margin: '0 0 6px 0'}
  }));

  legendPanel.add(legendRow('#ff0000', 'Selected ACZ boundary'));
  legendPanel.add(legendRow('#000000', 'Ready district boundaries'));
  legendPanel.add(legendRow('#ffff00', 'Selected district outline'));
  legendPanel.add(legendRow('#2b83ba', 'Excluded mask'));
  legendPanel.add(legendRow('#ffd92f', 'Union / annual burnable'));
  legendPanel.add(legendRow('#000000', 'Monthly BA overlay'));

  legendPanel.add(ui.Label({
    value: 'LC_Type1 IGBP classes',
    style: {fontSize: '11px', whiteSpace: 'pre-wrap', margin: '6px 0 4px 0', fontWeight: 'bold'}
  }));
  for (var i = 0; i < IGBP.length; i++) {
    legendPanel.add(legendRow('#' + String(IGBP[i].color).replace('#', ''), IGBP[i].value + ' — ' + IGBP[i].name));
  }
}
Map.add(legendPanel);


// Left-panel UI: Controls, Exports, and About tabs for the fixed-method district preview/export workflow.
// =============================== MAIN PANEL ==================================

var mainPanel = ui.Panel({
  style: {
    position: 'top-left',
    width: '380px',
    height: '680px',
    padding: '8px',
    backgroundColor: 'rgba(255,255,255,0.95)'
  }
});
Map.add(mainPanel);

var panelNav = ui.Panel({
  layout: ui.Panel.Layout.flow('horizontal'),
  style: {margin: '6px 0 8px 0', stretch: 'horizontal'}
});

var controlsViewPanel = ui.Panel({
  style: {
    stretch: 'horizontal',
    shown: true
  }
});

var exportsViewPanel = ui.Panel({
  style: {
    stretch: 'horizontal',
    shown: false
  }
});

var aboutViewPanel = ui.Panel({
  style: {
    stretch: 'horizontal',
    shown: false
  }
});

// Small UI layout helper used to stack one label and one input together.
function controlBlock(labelWidget, inputWidget) {
  return ui.Panel({
    widgets: [labelWidget, inputWidget],
    layout: ui.Panel.Layout.flow('vertical'),
    style: {stretch: 'horizontal', margin: '0 0 8px 0'}
  });
}

// Styled section header used in the left control panel.
function sectionHeader(text) {
  return ui.Label({
    value: text,
    style: {fontWeight: 'bold', margin: '8px 0 4px 0'}
  });
}

// Apply consistent spacing to checkbox controls.
function styleCheckboxControl(checkbox) {
  checkbox.style().set({margin: '2px 0'});
  return checkbox;
}

var controlsTabButton;
var exportsTabButton;

// Switch the left panel between Controls, Exports, and About tabs.
function setPanelView(viewName) {
  controlsViewPanel.style().set('shown', viewName === 'controls');
  exportsViewPanel.style().set('shown', viewName === 'exports');
  aboutViewPanel.style().set('shown', viewName === 'about');
}

controlsTabButton = ui.Button({
  label: 'Controls',
  onClick: function() { setPanelView('controls'); },
  style: {stretch: 'horizontal', margin: '0 4px 0 0'}
});

exportsTabButton = ui.Button({
  label: 'Exports',
  onClick: function() { setPanelView('exports'); },
  style: {stretch: 'horizontal', margin: '0 4px 0 0'}
});

var aboutTabButton = ui.Button({
  label: 'About',
  onClick: function() { setPanelView('about'); },
  style: {stretch: 'horizontal', margin: '0'}
});

mainPanel.add(ui.Label({
  value: 'RP1 District c1 — fixed-method QA preview',
  style: {fontWeight: 'bold', fontSize: '14px'}
}));
mainPanel.add(ui.Label({
  value: 'Clean analytical district script with a frozen LW_OR_LC17 baseline. The selected district controls the highlight only; exports remain ACZ-scoped district bundles under the fixed c1 method.',
  style: {fontSize: '11px', whiteSpace: 'pre-wrap'}
}));
panelNav.add(controlsTabButton);
panelNav.add(exportsTabButton);
panelNav.add(aboutTabButton);
mainPanel.add(panelNav);
mainPanel.add(controlsViewPanel);
mainPanel.add(exportsViewPanel);
mainPanel.add(aboutViewPanel);


// Controls tab: ACZ selection, district highlight, time sliders, layer toggles, and analytical summaries.
// ----------------------------- Controls view ---------------------------------

var zoneSelectLabel = ui.Label('ACZ', {margin: '0 0 4px 0'});
var zoneSelect = ui.Select({
  items: ZONE_UI_LABELS,
  value: ZONE_ID_TO_LABEL[state.zoneId],
  onChange: function(label) {
    state.zoneId = ZONE_LABEL_TO_ID[label] || DEFAULT_ZONE_ID;
    redraw({forceRebuild: true, forceCenter: true, forcePrint: true});
  },
  style: {stretch: 'horizontal'}
});

var districtSelectLabel = ui.Label('District (preview highlight)', {margin: '0 0 4px 0'});
var districtSelect = ui.Select({
  items: [],
  placeholder: 'Select district',
  onChange: function(label) {
    if (suppressDistrictSelectChange) return;
    state.selectedDistrictId = DISTRICT_LABEL_TO_ID[label] || '';
    redraw({forceRebuild: false, forceCenter: false, forcePrint: false});
  },
  style: {stretch: 'horizontal'}
});

var yearLabel = ui.Label('Year: ' + state.year, {margin: '0 0 4px 0'});
var yearSlider = ui.Slider({
  min: DENOM_START_YEAR,
  max: DENOM_END_YEAR,
  value: state.year,
  step: 1,
  style: {stretch: 'horizontal'},
  onChange: function(v) {
    state.year = Number(v);
    yearLabel.setValue('Year: ' + state.year);
    redraw({forceRebuild: false, forceCenter: false, forcePrint: false});
  }
});

var monthLabel = ui.Label('Month: ' + pad2(state.month), {margin: '0 0 4px 0'});
var monthSlider = ui.Slider({
  min: 1,
  max: 12,
  value: state.month,
  step: 1,
  style: {stretch: 'horizontal'},
  onChange: function(v) {
    state.month = Number(v);
    monthLabel.setValue('Month: ' + pad2(state.month));
    redraw({forceRebuild: false, forceCenter: false, forcePrint: false});
  }
});

var frozenBaselineInfoLabel = ui.Label({
  value:
    'Frozen baseline mask: ' + BA_MASK_MODE + '\n' +
    'Keep rule: ' + BA_MASK_KEEP_SUMMARY + '\n' +
    'Excluded rule: ' + BA_MASK_EXCLUDED_SUMMARY + '\n' +
    'Alternative mask comparison is intentionally disabled here and belongs in the dedicated viewer script.',
  style: {fontSize: '11px', whiteSpace: 'pre-wrap', margin: '0 0 8px 0', color: '#333333'}
});

var BURN_DISPLAY_LABEL_TO_KEY = {
  BurnMask: 'BurnMask',
  BurnDate: 'BurnDate'
};
var BURN_DISPLAY_KEY_TO_LABEL = {
  BurnMask: 'BurnMask',
  BurnDate: 'BurnDate'
};

var burnDisplayLabel = ui.Label('Burn display layer', {margin: '0 0 4px 0'});
var burnDisplaySelect = ui.Select({
  items: ['BurnMask', 'BurnDate'],
  value: BURN_DISPLAY_KEY_TO_LABEL[state.burnDisplayMode],
  onChange: function(label) {
    state.burnDisplayMode = BURN_DISPLAY_LABEL_TO_KEY[label] || 'BurnMask';
    redraw({forceRebuild: false, forceCenter: false, forcePrint: false});
  },
  style: {stretch: 'horizontal'}
});

var selectionSummaryLabel = ui.Label('', {whiteSpace: 'pre-wrap', fontSize: '11px'});
var analyticsSummaryLabel = ui.Label('', {whiteSpace: 'pre-wrap', fontSize: '11px'});

var addYearStackButton = ui.Button({
  label: 'Add all monthly BA layers for selected year',
  onClick: function() {
    var ctx = currentCtx || buildDistrictContext(state.zoneId, state.maskMode);
    addMonthlyBaYearStackLayers(ctx, state.year, state.burnDisplayMode);
  },
  style: {stretch: 'horizontal', margin: '4px 0'}
});

var returnToSliderPreviewButton = ui.Button({
  label: 'Return to slider preview',
  onClick: function() {
    clearInjectedYearStackLayers();
    redraw({forceRebuild: false, forceCenter: false, forcePrint: false});
    if (DEBUG_UI_PRINTS) {
      print(ee.Dictionary({
        message: 'Returned to slider preview',
        zone_id: state.zoneId,
        selected_district_id: state.selectedDistrictId,
        year: state.year,
        month: state.month,
        mask_mode: state.maskMode,
        burn_display_mode: state.burnDisplayMode
      }));
    }
  },
  style: {stretch: 'horizontal', margin: '4px 0 8px 0'}
});

var showZoneBoundaryCheckbox = ui.Checkbox('Show selected ACZ boundary', state.showZoneBoundary, function(v) {
  state.showZoneBoundary = v; redraw({forceRebuild: false, forceCenter: false, forcePrint: false});
});
var showDistrictBoundariesCheckbox = ui.Checkbox('Show ready district boundaries', state.showDistrictBoundaries, function(v) {
  state.showDistrictBoundaries = v; redraw({forceRebuild: false, forceCenter: false, forcePrint: false});
});
var showSelectedDistrictCheckbox = ui.Checkbox('Show selected district outline', state.showSelectedDistrict, function(v) {
  state.showSelectedDistrict = v; redraw({forceRebuild: false, forceCenter: false, forcePrint: false});
});
var showLcCheckbox = ui.Checkbox('Show LC_Type1', state.showLc, function(v) {
  state.showLc = v; redraw({forceRebuild: false, forceCenter: false, forcePrint: false});
});
var showExcludedCheckbox = ui.Checkbox('Show active excluded-mask', state.showExcluded, function(v) {
  state.showExcluded = v; redraw({forceRebuild: false, forceCenter: false, forcePrint: false});
});
var showUnionCheckbox = ui.Checkbox('Show union burnable layer', state.showUnion, function(v) {
  state.showUnion = v; redraw({forceRebuild: false, forceCenter: false, forcePrint: false});
});
var showAnnualBurnableCheckbox = ui.Checkbox('Show annual burnable layer', state.showAnnualBurnable, function(v) {
  state.showAnnualBurnable = v; redraw({forceRebuild: false, forceCenter: false, forcePrint: false});
});
var showBaCheckbox = ui.Checkbox('Show monthly burned-area layer', state.showBa, function(v) {
  state.showBa = v; redraw({forceRebuild: false, forceCenter: false, forcePrint: false});
});
var showLegendCheckbox = ui.Checkbox('Show legend', state.showLegend, function(v) {
  state.showLegend = v; redraw({forceRebuild: false, forceCenter: false, forcePrint: false});
});

controlsViewPanel.add(ui.Label({
  value: 'Preview controls',
  style: {fontWeight: 'bold', margin: '0 0 4px 0'}
}));
controlsViewPanel.add(controlBlock(zoneSelectLabel, zoneSelect));
controlsViewPanel.add(controlBlock(districtSelectLabel, districtSelect));
controlsViewPanel.add(controlBlock(yearLabel, yearSlider));
controlsViewPanel.add(controlBlock(monthLabel, monthSlider));
controlsViewPanel.add(controlBlock(burnDisplayLabel, burnDisplaySelect));
controlsViewPanel.add(frozenBaselineInfoLabel);
controlsViewPanel.add(addYearStackButton);
controlsViewPanel.add(returnToSliderPreviewButton);
controlsViewPanel.add(sectionHeader('Layer visibility'));
controlsViewPanel.add(styleCheckboxControl(showZoneBoundaryCheckbox));
controlsViewPanel.add(styleCheckboxControl(showDistrictBoundariesCheckbox));
controlsViewPanel.add(styleCheckboxControl(showSelectedDistrictCheckbox));
controlsViewPanel.add(styleCheckboxControl(showLcCheckbox));
controlsViewPanel.add(styleCheckboxControl(showExcludedCheckbox));
controlsViewPanel.add(styleCheckboxControl(showUnionCheckbox));
controlsViewPanel.add(styleCheckboxControl(showAnnualBurnableCheckbox));
controlsViewPanel.add(styleCheckboxControl(showBaCheckbox));
controlsViewPanel.add(styleCheckboxControl(showLegendCheckbox));
controlsViewPanel.add(sectionHeader('Selected configuration'));
controlsViewPanel.add(selectionSummaryLabel);
controlsViewPanel.add(sectionHeader('Analytical summary'));
controlsViewPanel.add(analyticsSummaryLabel);


// Exports tab: queue ACZ-scoped or all-ACZ district CSV tasks under the frozen c1 baseline.
// ------------------------------ Exports view ---------------------------------

exportsViewPanel.add(ui.Label({
  value: 'CSV export tasks',
  style: {fontWeight: 'bold', margin: '0 0 4px 0'}
}));
exportsViewPanel.add(ui.Label({
  value: 'Selected ACZ exports queue the district bundle for the current ACZ: merger-ready base CSV, ext CSV, grouped QA by ACZ, and drop log when exclusions exist. The baseline method is fixed to LW_OR_LC17 and monthly RP1 exports are clipped to 2001-01 through 2024-12.',
  style: {fontSize: '11px', whiteSpace: 'pre-wrap', margin: '0 0 6px 0'}
}));
exportsViewPanel.add(ui.Button({
  label: 'Queue CSV exports — selected ACZ',
  onClick: function() {
    exportSelectedDistrictTables();
  },
  style: {stretch: 'horizontal'}
}));
exportsViewPanel.add(ui.Button({
  label: 'Queue CSV exports — all ACZs',
  onClick: function() {
    exportAllDistrictZoneTables();
  },
  style: {stretch: 'horizontal'}
}));
exportsViewPanel.add(ui.Label({
  value: 'The selected district does not subset exports; it only controls the highlighted district in the map preview.',
  style: {fontSize: '11px', whiteSpace: 'pre-wrap', margin: '8px 0 6px 0'}
}));
exportsViewPanel.add(ui.Button({
  label: 'Print current preview context',
  onClick: function() {
    if (currentCtx) {
      printPreviewDiagnostics(currentCtx);
    }
  },
  style: {stretch: 'horizontal'}
}));



aboutViewPanel.add(ui.Label({
  value: 'About c1',
  style: {fontWeight: 'bold', margin: '0 0 4px 0'}
}));
aboutViewPanel.add(ui.Label({
  value:
    'This is the fixed-method district extractor for RP1. The analytical baseline is locked to LW_OR_LC17, exact-year MCD12Q1 denominator support, and the overlap-era window 2001-01 through 2024-12.\n\n' +
    'The selected district only affects the preview highlight. Analytical CSV exports remain ACZ-scoped district bundles. Use the dedicated viewer script for exploratory mask comparisons.',
  style: {fontSize: '11px', whiteSpace: 'pre-wrap', margin: '0 0 6px 0'}
}));

// UI refresh orchestration: update context, layers, summaries, legend, and map centring after state changes.
// ================================ REDRAW =====================================

// Refresh the textual summary boxes with the current frozen-baseline configuration and zone-level analytical preview metrics.
function updateSummaryLabels(ctx) {
  var maskCfg = getBaMaskConfig(FIXED_BA_MASK_MODE);
  var selectedDistrictLabel = DISTRICT_ID_TO_LABEL[state.selectedDistrictId] || '(none selected)';
  selectionSummaryLabel.setValue(
    'Zone: ' + ctx.zoneMeta.zone_name + ' (' + ctx.zoneMeta.zone_code + ')\n' +
    'Selected district: ' + selectedDistrictLabel + '\n' +
    'Frozen baseline mask: ' + maskCfg.key + '\n' +
    'Rule: ' + maskCfg.layerLabel + '\n' +
    'Keep: ' + maskCfg.keepSummary + '\n' +
    'Exclude: ' + maskCfg.excludedSummary + '\n' +
    'Burn display: ' + state.burnDisplayMode + '\n' +
    'Month preview: ' + state.year + '-' + pad2(state.month)
  );

  var selectedAnnualExcludedKm2 = areaMaskedKm2(
    annualBaExcludedMaskForYear(state.year, ctx.maskMode).clip(ctx.aoiGeomLand),
    ctx.aoiGeomLand
  );

  var selectedAnnualBurnableKm2 = areaMaskedKm2(
    annualBurnableMaskForYear(state.year, ctx.maskMode).clip(ctx.aoiGeomLand),
    ctx.aoiGeomLand
  );

  var metrics = ee.Dictionary({
    zone_id: ctx.zoneMeta.zone_id,
    zone_code: ctx.zoneMeta.zone_code,
    ready_district_count: ctx.readyCountInfo,
    excluded_district_count: ctx.excludedCountInfo,
    zero_land_count: ctx.zeroLandCountInfo,
    unresolved_unit_count: ctx.unresolvedUnitCountInfo,
    unresolved_parent_count: ctx.unresolvedParentCountInfo,
    union_burnable_km2: ctx.zoneBurnableKm2Union,
    selected_annual_excluded_km2: selectedAnnualExcludedKm2,
    selected_annual_burnable_km2: selectedAnnualBurnableKm2,
    annual_zero_den_rows: ctx.annualDenomTable.filter(ee.Filter.eq('zero_annual_den_flag', 1)).size(),
    months_count: ctx.previewMonthsCount
  });

  metrics.evaluate(function(obj) {
    if (!obj) {
      analyticsSummaryLabel.setValue('Unable to evaluate analytical summary.');
      return;
    }
    analyticsSummaryLabel.setValue(
      'Zone ID: ' + obj.zone_id + '\n' +
      'Zone code: ' + obj.zone_code + '\n' +
      'Ready districts: ' + obj.ready_district_count + '\n' +
      'Excluded districts: ' + obj.excluded_district_count + '\n' +
      'Zero-land districts: ' + obj.zero_land_count + '\n' +
      'Unresolved district IDs: ' + obj.unresolved_unit_count + '\n' +
      'Unresolved parent ACZs: ' + obj.unresolved_parent_count + '\n' +
      'Zone union burnable area (km²): ' + Number(obj.union_burnable_km2 || 0).toFixed(4) + '\n' +
      'Selected-year excluded area (km²): ' + Number(obj.selected_annual_excluded_km2 || 0).toFixed(4) + '\n' +
      'Selected-year annual burnable (km²): ' + Number(obj.selected_annual_burnable_km2 || 0).toFixed(4) + '\n' +
      'Annual zero-denominator rows: ' + obj.annual_zero_den_rows + '\n' +
      'Months in export window: ' + obj.months_count
    );
  });
}

// Rebuild the district context only when the selected ACZ changes or a forced rebuild is requested.
function ensureContext(forceRebuild) {
  var nextKey = state.zoneId + '|' + state.maskMode;
  if (forceRebuild || !currentCtx || currentCtxKey !== nextKey) {
    currentCtx = buildDistrictContext(state.zoneId, state.maskMode);
    currentCtxKey = nextKey;
    return true;
  }
  return false;
}

// Repopulate the district dropdown from the ready district set in the current ACZ context.
function refreshDistrictSelectFromContext(ctx) {
  DISTRICT_LABEL_TO_ID = {};
  DISTRICT_ID_TO_LABEL = {};

  var labels = [];
  for (var i = 0; i < ctx.districtUiOptions.length; i++) {
    var opt = ctx.districtUiOptions[i];
    DISTRICT_LABEL_TO_ID[opt.label] = opt.unit_id;
    DISTRICT_ID_TO_LABEL[opt.unit_id] = opt.label;
    labels.push(opt.label);
  }

  if (ctx.districtUiOptions.length === 0) {
    state.selectedDistrictId = '';
    labels = ['(No eligible districts)'];
  } else if (!DISTRICT_ID_TO_LABEL[state.selectedDistrictId]) {
    state.selectedDistrictId = ctx.districtUiOptions[0].unit_id;
  }

  suppressDistrictSelectChange = true;
  districtSelect.items().reset(labels);
  if (ctx.districtUiOptions.length === 0) {
    districtSelect.setValue('(No eligible districts)', false);
  } else {
    districtSelect.setValue(DISTRICT_ID_TO_LABEL[state.selectedDistrictId], false);
  }
  suppressDistrictSelectChange = false;
}

// Push all current preview layers to the map with the correct visibility, opacity, and selected month/year.
function refreshPreviewLayers(ctx) {
  zoneBoundaryLayer.setEeObject(ctx.zoneBoundaryImage.clip(ctx.aoiGeomLand));
  zoneBoundaryLayer.setShown(state.showZoneBoundary);

  districtBoundaryLayer.setEeObject(ctx.readyDistrictBoundaryImage.clip(ctx.aoiGeomLand));
  districtBoundaryLayer.setShown(state.showDistrictBoundaries);

  selectedDistrictLayer.setEeObject(getSelectedDistrictBoundaryImage(ctx, state.selectedDistrictId).clip(ctx.aoiGeomLand));
  selectedDistrictLayer.setShown(state.showSelectedDistrict);

  lcLayer.setEeObject(getLcPreviewImage(ctx, state.year));
  lcLayer.setShown(state.showLc);
  lcLayer.setOpacity(LC_OPACITY);

  excludedLayer.setEeObject(getExcludedPreviewImage(ctx, state.year));
  excludedLayer.setShown(state.showExcluded);
  excludedLayer.setOpacity(WATER_OPACITY);

  unionLayer.setEeObject(getUnionPreviewImage(ctx));
  unionLayer.setShown(state.showUnion);
  unionLayer.setOpacity(UNION_OPACITY);

  annualBurnableLayer.setEeObject(getAnnualBurnablePreviewImage(ctx, state.year));
  annualBurnableLayer.setShown(state.showAnnualBurnable);
  annualBurnableLayer.setOpacity(UNION_OPACITY);

  baLayer.setEeObject(getMonthlyBurnPreviewImage(ctx, state.year, state.month, state.burnDisplayMode));
  baLayer.setVisParams(state.burnDisplayMode === 'BurnDate' ? BURNDATE_VIS : BURNMASK_VIS);
  baLayer.setName('Monthly BA — ' + state.burnDisplayMode);
  baLayer.setShown(state.showBa);
  baLayer.setOpacity(BA_OPACITY);
}

// Remove existing year-stack layers from the map.
function clearInjectedYearStackLayers() {
  var layers = Map.layers();
  while (injectedYearStackLayers.length) {
    var lyr = injectedYearStackLayers.pop();
    layers.remove(lyr);
  }
}

// Add twelve month-specific BA layers for the selected year so the user can inspect the full year stack at once.
function addMonthlyBaYearStackLayers(ctx, year, burnDisplayMode) {
  clearInjectedYearStackLayers();

  var layers = Map.layers();
  var visParams = burnDisplayMode === 'BurnDate' ? BURNDATE_VIS : BURNMASK_VIS;
  var maskCfg = getBaMaskConfig(ctx.maskMode);

  for (var m = 1; m <= 12; m++) {
    var monthImg = getMonthlyBurnPreviewImage(ctx, year, m, burnDisplayMode);
    var layerName = 'Year-stack BA ' +
      year + '-' + pad2(m) + ' — ' +
      burnDisplayMode + ' — ' +
      ctx.zoneMeta.zone_code + ' — ' +
      maskCfg.key;

    var monthLayer = ui.Map.Layer(
      monthImg,
      visParams,
      layerName,
      false,
      BA_OPACITY
    );

    injectedYearStackLayers.push(monthLayer);
    layers.add(monthLayer);
  }

  if (DEBUG_UI_PRINTS) {
    print(ee.Dictionary({
      message: 'Added monthly BA year-stack layers to map',
      zone_id: ctx.zoneMeta.zone_id,
      zone_code: ctx.zoneMeta.zone_code,
      year: year,
      burn_display_mode: burnDisplayMode,
      mask_mode: maskCfg.key,
      layers_added: 12
    }));
  }
}

// Refresh the textual panels and legend after state changes.
function refreshPanels(ctx) {
  updateSummaryLabels(ctx);
  refreshLegend();
  legendPanel.style().set('shown', !!state.showLegend);
}

// Centre the map on the current ACZ when first built or when the selected ACZ changes.
function centerMapOnContext(ctx, forceCenter) {
  var zoneChanged = currentCenteredZoneId !== ctx.zoneMeta.zone_id;
  if (forceCenter || !currentCenteredZoneId || zoneChanged) {
    Map.centerObject(ctx.districtFc, 7);
    currentCenteredZoneId = ctx.zoneMeta.zone_id;
  }
}

// Optional debug printer for current preview context, annual denominator tables, and grouped QA summaries.
function printPreviewDiagnostics(ctx) {
  if (!DEBUG_UI_PRINTS) return;

  var selectedAnnualExcludedKm2 = areaMaskedKm2(
    annualBaExcludedMaskForYear(state.year, ctx.maskMode).clip(ctx.aoiGeomLand),
    ctx.aoiGeomLand
  );

  var selectedAnnualBurnableKm2 = areaMaskedKm2(
    annualBurnableMaskForYear(state.year, ctx.maskMode).clip(ctx.aoiGeomLand),
    ctx.aoiGeomLand
  );

  print(ee.Dictionary({
    message: 'Preview context',
    zone_id: ctx.zoneMeta.zone_id,
    zone_name: ctx.zoneMeta.zone_name,
    zone_code: ctx.zoneMeta.zone_code,
    selected_district_id: state.selectedDistrictId,
    mask_mode: ctx.maskCfg.key,
    year: state.year,
    month: state.month,
    burn_display_mode: state.burnDisplayMode
  }));

  print(ee.Dictionary({message: 'Preview annual denominator table'}));
  print(ctx.annualDenomTable.limit(10));
  print(ee.Dictionary({message: 'Preview grouped QA by ACZ'}));
  print(ctx.qaByAcz.limit(10));
  print(ee.Dictionary({
    message: 'Preview lightweight summary',
    zone_id: ctx.zoneMeta.zone_id,
    zone_code: ctx.zoneMeta.zone_code,
    ready_district_count: ctx.readyCountInfo,
    excluded_district_count: ctx.excludedCountInfo,
    zero_land_count: ctx.zeroLandCountInfo,
    unresolved_unit_count: ctx.unresolvedUnitCountInfo,
    unresolved_parent_count: ctx.unresolvedParentCountInfo,
    zone_union_burnable_km2: ctx.zoneBurnableKm2Union,
    selected_annual_excluded_km2: selectedAnnualExcludedKm2,
    selected_annual_burnable_km2: selectedAnnualBurnableKm2,
    months_count: ctx.previewMonthsCount
  }));
}

// Main UI refresh loop: rebuild context when needed, refresh layers/panels, recenter if needed, and optionally print diagnostics.
function redraw(options) {
  options = options || {};
  var didRebuild = ensureContext(!!options.forceRebuild);
  var ctx = currentCtx;

  if (didRebuild) {
    clearInjectedYearStackLayers();
    refreshDistrictSelectFromContext(ctx);
  }

  refreshPreviewLayers(ctx);
  refreshPanels(ctx);
  centerMapOnContext(ctx, !!options.forceCenter);

  if (didRebuild || options.forcePrint) {
    printPreviewDiagnostics(ctx);
  }
}

redraw({forceRebuild: true, forceCenter: true, forcePrint: true});

if (ENABLE_AUTO_EXPORT_CURRENT_SELECTION) {
  exportSelectedDistrictTables();
}