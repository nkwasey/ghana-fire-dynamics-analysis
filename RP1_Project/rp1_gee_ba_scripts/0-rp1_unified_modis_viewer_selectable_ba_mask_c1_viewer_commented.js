// =============================================================================
// RP1 — Unified MODIS Viewer + GeoTIFF Exporter (c1 viewer)
// Selectable burned-area mask viewer aligned to the clean analytical baseline
// Google Earth Engine (JavaScript / Code Editor)
//
// OVERVIEW
// --------
// This script is the visual QA, sensitivity-analysis, and raster-export
// companion to the clean analytical c1 panel scripts for Ghana:
//
//   • 1-rp1_zone_monthly_panel_c1.js
//   • 2-rp1_district_monthly_panel_c1.js
//
// It is intentionally NOT the primary analytical CSV constructor. Instead, it
// is the environment where the frozen analytical baseline can be inspected
// visually, compared against alternative annual MCD12Q1-based masking rules,
// and exported as GeoTIFF products and diagnostic rasters.
//
// The monthly burned-area numerator is derived from MODIS MCD64A1 Collection
// 6.1 BurnDate and is defined per month as the pixel-wise OR across all
// MCD64A1 images overlapping that month (burned = BurnDate > 0 in any
// overlapping month image).
//
// The c1 analytical line is fully MODIS-based. This viewer therefore uses
// MCD12Q1 only for annual land / water / excluded-mask support, and aligns to
// the same overlap-era study window as the analytical scripts:
//
//   • study window: January 2012 through December 2024
//   • denominator support: exact-year MCD12Q1 only
//   • no denominator fallback
//
// The official analytical baseline used by the zone and district extractors is:
//
//   • exclude if (LW != 2) OR (LC_Type1 == 17)
//   • equivalently keep only pixels where:
//       (LW == 2) AND (LC_Type1 != 17)
//
// This baseline is labelled in the viewer as:
//
//   • LW_OR_LC17
//
// The viewer opens in that baseline mode by default. Alternative mask modes are
// preserved here only as sensitivity options and not as competing analytical
// baselines.
//
// WHAT THIS SCRIPT IS FOR
// -----------------------
// 1) Open in the agreed c1 analytical baseline used by the clean panel scripts:
//      baseline BA mask = LW_OR_LC17
//
// 2) Let the user inspect the baseline visually:
//      • month by month,
//      • year by year,
//      • as single-month views or year-stacks.
//
// 3) Let the user compare the official baseline against sensitivity
//    alternatives without contaminating the fixed analytical extractors.
//
// 4) Export GeoTIFF products and diagnostic rasters with filenames that encode
//    the currently selected mask mode, so baseline and sensitivity runs remain
//    distinguishable.
//
// FROZEN ALIGNMENT WITH THE c1 ANALYTICAL LINE
// --------------------------------------------
// • Monthly BA numerator:
//     BurnDate > 0 in ANY MCD64A1 image overlapping the month
//     (pixel-wise OR / max across overlapping images).
//
// • Denominator / annual support source:
//     MODIS/061/MCD12Q1 only.
//
// • Official c1 analytical baseline:
//     exclude if (LW != 2) OR (LC_Type1 == 17)
//     equivalently keep only pixels where:
//       (LW == 2) AND (LC_Type1 != 17)
//
// • Viewer default mask mode:
//     LW_OR_LC17
//
// • Sensitivity options retained in the viewer:
//     LC17
//     LC11_17
//     LW
//     LW_OR_LC11_17
//
// • Study window aligned to the analytical overlap era:
//     2012-01 through 2024-12
//
// • Exact-year MCD12Q1 support is required.
//   No denominator fallback is allowed.
//
// DESIGN INTENT
// -------------
// • The zone and district c1 scripts are fixed-method production extractors.
// • This viewer remains flexible for QA and sensitivity analysis, but it is
//   not method-neutral in presentation:
//     – the opening state identifies LW_OR_LC17 as the official baseline,
//     – the summary text identifies baseline versus sensitivity modes,
//     – export descriptions preserve the selected mask mode in filenames.
//
// • The left-side UI uses tabbed subviews so controls remain accessible on
//   smaller displays without depending on unsupported CSS-like overflow
//   styling.
//
// • The legend is placed at the top right and includes the full LC_Type1 class
//   list so annual land-cover interpretation remains available alongside BA and
//   excluded-mask diagnostics.
//
// WHAT THIS SCRIPT DOES (STEP-BY-STEP)
// ------------------------------------
// 1) INPUT AOI + LAND-ONLY ENFORCEMENT
//    • Reads an AOI FeatureCollection and a canonical Ghana land-only boundary.
//    • Repairs both geometries using a geometry-cleaning helper.
//    • Intersects the AOI with Ghana land so all previews and exports are
//      explicitly land-only.
//    • Builds an AOI mask image used consistently for display and export.
//
// 2) DATASET INITIALISATION
//    • Uses three authoritative MODIS products:
//        – MOD11A1 for daily LST,
//        – MCD12Q1 for annual land cover / LW,
//        – MCD64A1 for monthly burned area.
//    • Reads product-native projections once so exports can prefer native
//      grid specifications where available.
//
// 3) YEAR SUPPORT VALIDATION
//    • Validates that MCD12Q1 has exact-year support for all UI years from
//      2012 to 2024.
//    • Fails early if any required year is unavailable.
//
// 4) ANNUAL MCD12Q1 HELPERS
//    • Retrieves annual MCD12Q1 images for the selected year.
//    • Builds annual LC_Type1 layers for land-cover preview and export.
//    • Builds annual BA keep-mask and excluded-mask layers under the currently
//      selected baseline or sensitivity rule.
//    • Provides concise BA mask diagnostics for keep-area and excluded-area
//      reporting.
//
// 5) MONTHLY BURNED-AREA MODULE (MCD64A1)
//    • Builds the monthly BurnDate surface as the pixel-wise max across all
//      MCD64A1 images overlapping the selected month.
//    • Reprojects the annual keep-mask to the BA grid before masking.
//    • Produces a two-band monthly BA product:
//        – BurnDate (masked timing surface)
//        – BurnMask (BurnDate > 0 after masking)
//    • Supports both BurnMask display and BurnDate diagnostic display.
//
// 6) MONTHLY LST MODULE (MOD11A1)
//    • Applies mandatory QA filtering to daily MOD11A1 imagery.
//    • Converts raw LST to Celsius.
//    • Computes monthly mean Day and Night LST, plus monthly counts and view
//      times.
//    • Keeps LST as an AOI-only display/export product separate from the BA
//      masking logic.
//
// 7) STANDARD SINGLE-MONTH MAP VIEW
//    • Maintains persistent map layers for:
//        – AOI boundary,
//        – annual LC_Type1,
//        – monthly LST,
//        – annual excluded-mask diagnostic,
//        – monthly burned-area layer.
//    • Updates those layers from the current UI state.
//
// 8) YEAR-STACK VISUALISATION
//    • Can replace the standard monthly view with:
//        – a 12-layer annual LST stack, or
//        – a 12-layer annual BA stack.
//    • Preserves the selected year and mask mode while switching display mode.
//
// 9) TABBED UI PANEL
//    • Uses one compact floating left panel with four internal tabs:
//        – Controls
//        – Layers
//        – Exports
//        – About
//    • This avoids the clutter and accessibility problems of long multi-panel
//      layouts.
//
// 10) LEGEND + DYNAMIC LABELLING
//    • Maintains a separate top-right legend panel.
//    • Includes:
//        – BurnMask / BurnDate keys,
//        – excluded-mask key,
//        – LST palette strip,
//        – full LC_Type1 class list,
//        – current baseline/sensitivity mode summary.
//    • Updates legend and summary labels dynamically when the selected mask
//      mode changes.
//
// 11) EXPORTS (GOOGLE DRIVE GEOTIFFS)
//    • Supports selected-month exports for:
//        – LST,
//        – BA,
//        – all monthly products.
//    • Supports selected-month diagnostic exports for:
//        – masked BurnMask,
//        – masked BurnDate.
//    • Supports selected-year exports for:
//        – monthly LST stack,
//        – monthly BA stack,
//        – annual LC_Type1,
//        – annual keep-mask,
//        – annual excluded-mask.
//    • All BA-related export filenames encode the active mask mode so baseline
//      and sensitivity products remain distinguishable.
//
// INPUT DATASETS
// --------------
// • Land Surface Temperature:
//     MODIS/061/MOD11A1
//
// • Land-cover / annual support source:
//     MODIS/061/MCD12Q1
//     – LC_Type1
//     – LW
//
// • Burned-area numerator:
//     MODIS/061/MCD64A1
//     – BurnDate
//
// • AOI geometry:
//     User AOI FeatureCollection asset
//
// • Ghana land-only boundary:
//     Canonical Ghana land-only FeatureCollection asset
//
// HOW TO USE
// ----------
// 1) Set AOI_ASSET and GHANA_LAND_ASSET.
// 2) Confirm the export folders and file prefixes.
// 3) Confirm YEAR_MIN / YEAR_MAX / INIT_YEAR / INIT_MONTH.
// 4) Leave DEFAULT_BA_MASK_MODE as LW_OR_LC17 if you want alignment with the
//    clean c1 analytical scripts.
// 5) Run the script.
// 6) Use the Controls tab to choose year, month, Burn display mode, and
//    baseline or sensitivity mask mode.
// 7) Use the Layers tab for visibility toggles and year-stack views.
// 8) Use the Exports tab to queue GeoTIFF products and diagnostic rasters.
// 9) Start queued tasks from the Tasks tab.
//
// CONVENTIONS / OUTPUTS
// ---------------------
// • This script is a viewer/exporter, not the canonical analytical CSV builder.
// • The official analytical baseline is:
//      LW_OR_LC17
// • Areas and masks are interpreted on the product-native MODIS grids used by
//   the relevant display/export product.
// • LST exports preserve Day/Night information.
// • BA exports preserve BurnDate and BurnMask information.
// • Diagnostic exports preserve annual keep-mask and excluded-mask information.
// • Exact-year MCD12Q1 support is required for all annual mask operations.
// • Export filenames encode the current BA mask mode so baseline and
//   sensitivity products remain auditable.
// =============================================================================

// -----------------------------------------------------------------------------
// ANNOTATION:
// This section is the only part a user would normally edit before running the
// viewer. It controls:
//   • AOI and Ghana land-only assets,
//   • Drive folders and filename prefixes,
//   • initial year/month opening state,
//   • the default BA mask mode,
//   • export behaviour and fallback scales,
//   • map display defaults.
// The analytical logic itself is implemented below and should not be changed
// casually if the goal is to remain aligned with the c1 baseline.
// -----------------------------------------------------------------------------
/*** =====================================================================
  USER SETTINGS (EDIT THESE)
===================================================================== ***/

// AOI feature collection (your uploaded shapefile as an EE Asset)
var AOI_ASSET = 'projects/afd-data-cube-project/assets/RP1_Project/gha_admin0';

// Canonical Ghana land-only boundary (used to enforce land-only AOI)
var GHANA_LAND_ASSET = 'projects/afd-data-cube-project/assets/RP1_Project/gha_admin0';

// Drive export folders
var FOLDER_LST     = 'MOD11A1_monthly_LST';
var FOLDER_BA      = 'MCD64A1_monthly_BA';
var FOLDER_LC      = 'MCD12Q1_yearly_LC';
var FOLDER_BA_DIAG = 'MCD64A1_mask_DIAG';

// File prefixes
var PREFIX_LST            = 'MOD11A1_061_DN';
var PREFIX_BA             = 'MCD64A1_061_Burn';
var PREFIX_LC             = 'MCD12Q1_061_LCType1';
var PREFIX_BA_KEEP        = 'MCD12Q1_061_BAKeepMask';
var PREFIX_BA_EXCLUDED    = 'MCD12Q1_061_BAExcludedMask';
var PREFIX_BA_BURNMASK    = 'MCD64A1_061_BurnMaskMasked';
var PREFIX_BA_BURNDATE_DI = 'MCD64A1_061_BurnDateMasked';

// UI year bounds aligned to the clean analytical overlap-era window.
// Kept within exact-year MCD12Q1 availability used by the annual BA mask.
var YEAR_MIN = 2012;
var YEAR_MAX = 2024;

// Initial selection opens in the latest study year under the clean baseline.
var INIT_YEAR  = 2024;
var INIT_MONTH = 1;

// Default burned-area masking mode for the viewer. This must match the frozen
// analytical c1 baseline used by the zone and district extractors.
// Allowed values: 'LC17', 'LC11_17', 'LW', 'LW_OR_LC17', 'LW_OR_LC11_17'
var DEFAULT_BA_MASK_MODE = 'LW_OR_LC17';

// Viewer provenance.
var SCRIPT_RELEASE = 'c1_viewer';
var SCRIPT_LINEAGE = 'v4_selectable_viewer_with_c1_baseline_default';
var ANALYTICAL_BASELINE_MASK = 'LW_OR_LC17';

// Export safety
var MAX_PIXELS = 1e13;

// Preferred export strategy
var USE_NATIVE_TRANSFORM = true;

// Fallback scales (m) if native transform cannot be fetched
var SCALE_LST_M = 1000;
var SCALE_BA_M  = 500;
var SCALE_LC_M  = 500;

// GeoTIFF NoData values
var NODATA_LST  = -9999;
var NODATA_BA   = -9999;
var NODATA_LC   = 255;
var NODATA_MASK = 255;

// Map visual defaults
var LST_VIS_MIN_C = 10;
var LST_VIS_MAX_C = 45;
var LST_PALETTE = ['040274','2c7bb6','abd9e9','ffffbf','fdae61','f46d43','d73027','7f0000'];

// Burn visuals
var BURNMASK_VIS = {palette: ['000000']}; // black
var BURNDAY_VIS  = {min: 1, max: 366, palette: ['f2f2f2','000000']}; // greyscale

// Active excluded-mask diagnostic visual (blue)
var WATER_VIS = {palette: ['2b83ba']};
var WATER_OPACITY = 0.55;

// MCD12Q1 IGBP palette (LC_Type1 1..17)
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
var LC_VIS = {min: 1, max: 17, palette: IGBP.map(function(d){ return d.color; })};

// Burned-area mask-mode metadata.
// Notes:
//  - LC11_17 is hydrology-conservative rather than strictly water-only.
//  - LW_OR_LC17 is a water-focused conservative union mask.
//  - LW_OR_LC11_17 is a broader hydrology/wetness exclusion rather than a purely water-only mask.
// This lookup table is the central source of truth for all viewer mask-mode
// labels and rule summaries. The actual pixel logic is implemented later in
// getAnnualBaKeepMask(...), but the UI and export naming both rely on these
// metadata entries to remain consistent.
var BA_MASK_MODES = {
  'LC17': {
    key: 'LC17',
    shortCode: 'LC17',
    uiLabel: 'Sensitivity — strict water only (LC_Type1 class 17)',
    layerLabel: 'LC_Type1 == 17 (Water Bodies)',
    keepSummary: 'Keep pixels where LC_Type1 != 17',
    excludedSummary: 'Exclude pixels where LC_Type1 == 17'
  },
  'LC11_17': {
    key: 'LC11_17',
    shortCode: 'LC11_17',
    uiLabel: 'Sensitivity — water + wetlands (LC_Type1 classes 11 and 17)',
    layerLabel: 'LC_Type1 in {11, 17} (Permanent Wetlands + Water Bodies)',
    keepSummary: 'Keep pixels where LC_Type1 not in {11, 17}',
    excludedSummary: 'Exclude pixels where LC_Type1 in {11, 17}'
  },
  'LW': {
    key: 'LW',
    shortCode: 'LW',
    uiLabel: 'Sensitivity — dedicated LW water mask',
    layerLabel: 'LW != 2 excluded / LW == 2 kept',
    keepSummary: 'Keep pixels where LW == 2 (Land)',
    excludedSummary: 'Exclude pixels where LW != 2'
  },
  'LW_OR_LC17': {
    key: 'LW_OR_LC17',
    shortCode: 'LW_OR_LC17',
    uiLabel: 'Baseline — LW OR LC17 conservative water union',
    layerLabel: 'LW != 2 OR LC_Type1 == 17',
    keepSummary: 'Keep pixels where LW == 2 and LC_Type1 != 17',
    excludedSummary: 'Exclude pixels where LW != 2 or LC_Type1 == 17'
  },
  'LW_OR_LC11_17': {
    key: 'LW_OR_LC11_17',
    shortCode: 'LW_OR_LC11_17',
    uiLabel: 'Sensitivity — broad LW or LC11/17 hydrology union',
    layerLabel: 'LW != 2 OR LC_Type1 in {11, 17}',
    keepSummary: 'Keep pixels where LW == 2 and LC_Type1 not in {11, 17}',
    excludedSummary: 'Exclude pixels where LW != 2 or LC_Type1 in {11, 17}'
  }
};


// -----------------------------------------------------------------------------
// ANNOTATION:
// These are the authoritative MODIS collections used by the viewer.
// The script keeps the product roles separate:
//   • MOD11A1 -> LST viewing/export only,
//   • MCD12Q1 -> annual support, LC, LW, excluded-mask logic,
//   • MCD64A1 -> monthly burned-area timing and burn-mask logic.
// -----------------------------------------------------------------------------
/*** =====================================================================
  DATASETS (authoritative IDs)
===================================================================== ***/
var IC_LST = ee.ImageCollection('MODIS/061/MOD11A1');
var IC_LC  = ee.ImageCollection('MODIS/061/MCD12Q1');
var IC_BA  = ee.ImageCollection('MODIS/061/MCD64A1');


// -----------------------------------------------------------------------------
// ANNOTATION:
// The helpers below are reused across modules so that date handling, geometry
// repair, mask-mode interpretation, export specification, and small client-side
// checks are all implemented consistently in one place.
// -----------------------------------------------------------------------------
/*** =====================================================================
  SHARED HELPERS
===================================================================== ***/

/**
 * Left-pad month numbers (and similar small integers) to two characters.
 * Example: 1 -> '01'. Used in layer names, labels, and export filenames.
 */
function pad2(n) {
  return (n < 10) ? ('0' + n) : ('' + n);
}


/**
 * Best-effort geometry repair helper.
 * buffer(0, 1) is commonly used in Earth Engine to reduce topology defects such
 * as minor self-intersections before further spatial operations.
 */
function cleanGeom(g) {
  return ee.Geometry(g).buffer(0, 1);
}


/**
 * Build a canonical month window where start is inclusive and end is the first
 * day of the next month. The same helper is reused for filtering BA and LST.
 */
function monthWindow(year, month) {
  var start = ee.Date.fromYMD(year, month, 1);
  var end = start.advance(1, 'month');
  return {start: start, end: end};
}


/**
 * Server-side year clamp for Earth Engine numbers. This is used when a year is
 * still being handled as an ee.Number and must remain on the server.
 */
function clampYear(year, minY, maxY) {
  year = ee.Number(year);
  return year.max(minY).min(maxY).toInt();
}


/**
 * Client-side year clamp for ordinary JavaScript numbers. This is used for UI
 * labels and other client-side state updates.
 */
function clampYearClient(year, minY, maxY) {
  year = Math.round(year);
  return Math.max(minY, Math.min(maxY, year));
}


/**
 * Return v only if it is one of the allowed discrete choices; otherwise fall
 * back to the provided default. This protects UI state from invalid values.
 */
function asChoice(v, allowed, d) {
  return allowed.indexOf(v) >= 0 ? v : d;
}


/**
 * Validate a BA mask mode key against BA_MASK_MODES. If the incoming key is not
 * recognised, fall back to DEFAULT_BA_MASK_MODE.
 */
function getBaMaskMode(mode) {
  return BA_MASK_MODES[mode] ? mode : DEFAULT_BA_MASK_MODE;
}


/**
 * Fetch the full metadata/config object for the currently requested BA mask
 * mode, including the UI label, short code, and textual rule summary.
 */
function getBaMaskConfig(mode) {
  return BA_MASK_MODES[getBaMaskMode(mode)];
}


/**
 * Convenience accessor for the short code used in export filenames and compact
 * layer naming.
 */
function getBaMaskShortCode(mode) {
  return getBaMaskConfig(mode).shortCode;
}


/**
 * Earth Engine projections can report their transforms in slightly different
 * shapes depending on context. This helper normalises those variants to a
 * standard six-element CRS transform array whenever possible.
 */
function normaliseCrsTransform(trInfo) {
  if (trInfo === null || trInfo === undefined) return null;

  if (typeof trInfo === 'string') return trInfo;

  if (Array.isArray(trInfo)) {
    if (trInfo.length === 6) return trInfo;

    if (trInfo.length === 3 &&
        Array.isArray(trInfo[0]) && trInfo[0].length >= 3 &&
        Array.isArray(trInfo[1]) && trInfo[1].length >= 3) {
      return [trInfo[0][0], trInfo[0][1], trInfo[0][2],
              trInfo[1][0], trInfo[1][1], trInfo[1][2]];
    }

    if (trInfo.length === 9) {
      return [trInfo[0], trInfo[1], trInfo[2], trInfo[3], trInfo[4], trInfo[5]];
    }

    return null;
  }

  if (typeof trInfo === 'object') {
    if (trInfo.transform) return normaliseCrsTransform(trInfo.transform);

    var a = trInfo.elt_0_0;
    var b = (trInfo.elt_0_1 !== undefined) ? trInfo.elt_0_1 : 0;
    var c = trInfo.elt_0_2;
    var d = (trInfo.elt_1_0 !== undefined) ? trInfo.elt_1_0 : 0;
    var e = trInfo.elt_1_1;
    var f = trInfo.elt_1_2;

    if ([a, c, e, f].every(function(v){ return v !== undefined && v !== null; })) {
      return [a, b, c, d, e, f];
    }
  }

  return null;
}


/**
 * Build an export specification that prefers native CRS + CRS transform.
 * If the projection cannot be interrogated safely, the function falls back to a
 * scale-based export spec so the script still remains usable.
 */
function tryGetNativeSpec(proj, fallbackScale) {
  var out = {useTransform: false, crs: null, crsTransform: null, scale: fallbackScale};
  if (!USE_NATIVE_TRANSFORM) return out;

  try {
    var info = proj.getInfo();
    var crs = (info && info.crs) ? info.crs : proj.crs().getInfo();
    var trRaw = (info && info.transform) ? info.transform : proj.transform().getInfo();
    var tr = normaliseCrsTransform(trRaw);

    if (!tr) {
      print('WARN: Native CRS/transform not exportable; falling back to scale-based export. Raw transform=', trRaw);
      return out;
    }

    out.useTransform = true;
    out.crs = crs;
    out.crsTransform = tr;
    return out;

  } catch (e) {
    print('WARN: Failed to fetch native CRS/transform; falling back to scale-based export. Error:', e);
    return out;
  }
}


/**
 * Queue a GeoTIFF export to Google Drive using either:
 *   (a) a native CRS + CRS transform export, or
 *   (b) a scale-based fallback export.
 *
 * This helper centralises export task creation so all product and diagnostic
 * exports follow the same region / maxPixels / cloud-optimised conventions.
 */
function scheduleImageToDrive(image, description, folder, spec, noDataValue) {
  var args = {
    image: image,
    description: description,
    folder: folder,
    fileNamePrefix: description,
    region: aoiLand,
    maxPixels: MAX_PIXELS,
    fileFormat: 'GeoTIFF',
    formatOptions: {cloudOptimized: true, noData: noDataValue}
  };

  if (spec.useTransform && spec.crs && spec.crsTransform) {
    args.crs = spec.crs;
    args.crsTransform = spec.crsTransform;
  } else {
    args.scale = spec.scale;
  }

  Export.image.toDrive(args);
}


/**
 * Lightweight client-side source-image count for a month. Used to skip empty
 * exports before tasks are queued.
 */
function getClientMonthCount(ic, year, month) {
  var w = monthWindow(year, month);
  return ic.filterDate(w.start, w.end).size().getInfo();
}


/**
 * Confirm that MCD12Q1 has at least one image for the requested exact calendar
 * year. The UI range is pre-validated at startup to fail early if support is
 * missing.
 */
function validateMcd12YearAvailable(year) {
  var n = IC_LC.filter(ee.Filter.calendarRange(year, year, 'year')).size().getInfo();
  if (n < 1) {
    throw new Error('STOP: MCD12Q1 exact-year support is unavailable for year ' + year + '.');
  }
}


/**
 * Print source-image counts for the current month so the user can audit whether
 * the requested month has underlying BA and LST support before export.
 */
function printSelectedMonthCounts(year, month) {
  var w = monthWindow(year, month);
  var info = ee.Dictionary({
    year: year,
    month: month,
    mod11a1_daily_count: IC_LST.filterDate(w.start, w.end).size(),
    mcd64a1_month_count: IC_BA.filterDate(w.start, w.end).size()
  });
  print('Selected-month source image counts:', info);
}


/**
 * Print monthly source-image counts for the selected year. This is mainly a QA
 * aid before scheduling all-year export batches.
 */
function printMonthCountsForYear(year) {
  var months = ee.List.sequence(1, 12);

  var lstCounts = ee.FeatureCollection(months.map(function(m) {
    m = ee.Number(m);
    var w = monthWindow(year, m);
    var n = IC_LST.filterDate(w.start, w.end).size();
    return ee.Feature(null, {product: 'MOD11A1', year: year, month: m, image_count: n});
  }));

  var baCounts = ee.FeatureCollection(months.map(function(m) {
    m = ee.Number(m);
    var w = monthWindow(year, m);
    var n = IC_BA.filterDate(w.start, w.end).size();
    return ee.Feature(null, {product: 'MCD64A1', year: year, month: m, image_count: n});
  }));

  print('Monthly image counts (MOD11A1 raw daily; MCD64A1 monthly) for year=' + year + ':');
  print(lstCounts);
  print(baCounts);
}


/**
 * Convert a binary 0/1 mask image to total area in km² inside the land-only AOI.
 * This is used in BA mask diagnostics for keep-area and excluded-area reporting.
 */
function areaKm2FromMask(maskImg) {
  var areaImg = ee.Image.pixelArea().divide(1e6).rename('area')
    .updateMask(ee.Image(maskImg).eq(1));

  var stats = areaImg.reduceRegion({
    reducer: ee.Reducer.sum(),
    geometry: aoiLand,
    scale: SCALE_LC_M,
    maxPixels: MAX_PIXELS
  });

  return ee.Number(stats.get('area'));
}


// -----------------------------------------------------------------------------
// ANNOTATION:
// This block builds the land-only AOI that every later display and export uses.
// The viewer never works on the raw AOI directly once this section has run.
// Instead, every product is clipped and masked to AOI ∩ Ghana land.
// -----------------------------------------------------------------------------
/*** =====================================================================
  AOI PREP (land-only enforcement + AOI mask image)
===================================================================== ***/
// Read the user AOI and the canonical Ghana land boundary as FeatureCollections.
var aoiFc = ee.FeatureCollection(AOI_ASSET);
var ghLandFc = ee.FeatureCollection(GHANA_LAND_ASSET);

// Repair both geometries before intersection to reduce topology-related surprises.
var aoiRaw = cleanGeom(aoiFc.geometry());
var ghLand = cleanGeom(ghLandFc.geometry());

// Land-only AOI = AOI ∩ Ghana land boundary
// The analysis AOI is explicitly land-only: AOI intersect canonical Ghana land.
var aoiLand = cleanGeom(aoiRaw.intersection(ghLand, 1));

// AOI mask image (1 inside AOI, masked outside)
// AOI_MASK is reused to ensure display layers stay masked outside the land-only AOI.
var AOI_MASK = ee.Image.constant(1).clip(aoiLand).selfMask();

// Fail-fast if AOI has no land intersection
var HAS_LAND = aoiLand.area(1).gt(0).getInfo();
if (!HAS_LAND) {
  throw new Error('STOP: AOI has zero intersection with Ghana land boundary (aoiLand.area == 0).');
}

// Context prints
print('AOI feature count:', aoiFc.size());
print('MOD11A1 collection size:', IC_LST.size());
print('MCD12Q1 collection size:', IC_LC.size());
print('MCD64A1 collection size:', IC_BA.size());
print('MOD11A1 first date:', ee.Date(IC_LST.sort('system:time_start').first().get('system:time_start')));
print('MOD11A1 last date :', ee.Date(IC_LST.sort('system:time_start', false).first().get('system:time_start')));
print('MCD12Q1 first date:', ee.Date(IC_LC.sort('system:time_start').first().get('system:time_start')));
print('MCD12Q1 last date :', ee.Date(IC_LC.sort('system:time_start', false).first().get('system:time_start')));
print('MCD64A1 first date:', ee.Date(IC_BA.sort('system:time_start').first().get('system:time_start')));
print('MCD64A1 last date :', ee.Date(IC_BA.sort('system:time_start', false).first().get('system:time_start')));

// Basic exact-year validation for the UI range
for (var _y = YEAR_MIN; _y <= YEAR_MAX; _y++) {
  validateMcd12YearAvailable(_y);
}
print('MCD12Q1 exact-year validation passed for UI years: ' + YEAR_MIN + '-' + YEAR_MAX);


// -----------------------------------------------------------------------------
// ANNOTATION:
// This block inspects each product's native projection so Drive exports can
// preserve the intended grid whenever possible. If Earth Engine cannot provide
// a usable CRS transform, the script falls back to scale-based export settings.
// -----------------------------------------------------------------------------
/*** =====================================================================
  EXPORT PROJECTIONS (native grid specs per product)
===================================================================== ***/
// Read product-native projections once so exports can prefer each product's native grid.
var PROJ_LST = ee.Image(IC_LST.first()).select('LST_Day_1km').projection();
var PROJ_BA  = ee.Image(IC_BA.first()).select('BurnDate').projection();
var PROJ_LC  = ee.Image(IC_LC.first()).select('LC_Type1').projection();

var SPEC_LST = tryGetNativeSpec(PROJ_LST, SCALE_LST_M);
var SPEC_BA  = tryGetNativeSpec(PROJ_BA,  SCALE_BA_M);
var SPEC_LC  = tryGetNativeSpec(PROJ_LC,  SCALE_LC_M);

print('Export spec (LST):', SPEC_LST);
print('Export spec (BA) :', SPEC_BA);
print('Export spec (LC) :', SPEC_LC);


// -----------------------------------------------------------------------------
// ANNOTATION:
// This is the annual support module. It is where the selected BA mask mode is
// translated into annual keep/excluded masks. Those annual masks then feed the
// monthly BA module below.
// -----------------------------------------------------------------------------
/*** =====================================================================
  MCD12Q1 ANNUAL HELPERS
===================================================================== ***/
var LC_YEAR_MIN = 2001;
var LC_YEAR_MAX = 2024;


/**
 * Clamp a requested year to the supported MCD12Q1 year range on the server.
 */
function getMcd12Year(year) {
  return clampYear(year, LC_YEAR_MIN, LC_YEAR_MAX);
}


/**
 * Client-side equivalent of getMcd12Year(...) used for labels and messages.
 */
function getMcd12YearClient(year) {
  return clampYearClient(year, LC_YEAR_MIN, LC_YEAR_MAX);
}


/**
 * Fetch the annual MCD12Q1 image for the selected year and keep only the two
 * fields needed here:
 *   • LC_Type1 for IGBP class-based masking,
 *   • LW for binary land/water masking.
 */
function getMcd12Image(year) {
  var y = getMcd12Year(year);

  var img = ee.Image(
    IC_LC.filter(ee.Filter.calendarRange(y, y, 'year')).first()
  ).select(['LC_Type1', 'LW']);

  img = img.clip(aoiLand).updateMask(AOI_MASK);
  img = img.setDefaultProjection(PROJ_LC);

  img = ee.Image(img.set({
    'year_used': y,
    'requested_year': year
  }));

  return img;
}


/**
 * Return the annual LC_Type1 raster used only for contextual land-cover display
 * and annual LC export. This layer is not additionally masked by the BA rule.
 */
function getLcImage(year) {
  var y = getMcd12Year(year);

  var img = getMcd12Image(year).select('LC_Type1').toUint8();
  img = img.clip(aoiLand).updateMask(AOI_MASK);
  img = img.setDefaultProjection(PROJ_LC);

  img = ee.Image(img.set({
    'lc_year_used': y,
    'requested_year': year
  }));

  return img;
}


/**
 * Build the annual binary BA keep-mask for the selected year and selected mode.
 *
 * Keep-mask semantics:
 *   1 = pixel remains eligible for BA analysis/export
 *   0 = pixel is excluded by the chosen annual rule
 *
 * The five supported modes are all resolved here so downstream BA display and
 * export logic can reuse a single consistent annual eligibility surface.
 */
function getAnnualBaKeepMask(year, mode) {
  var y = getMcd12Year(year);
  var cfg = getBaMaskConfig(mode);
  var mcd12 = getMcd12Image(year);
  var lc = mcd12.select('LC_Type1');
  var lwLand = mcd12.select('LW').eq(2);
  var keep;

  if (cfg.key === 'LC17') {
    keep = lc.neq(17);
  } else if (cfg.key === 'LC11_17') {
    keep = lc.neq(11).and(lc.neq(17));
  } else if (cfg.key === 'LW') {
    keep = lwLand;
  } else if (cfg.key === 'LW_OR_LC17') {
    keep = lwLand.and(lc.neq(17));
  } else if (cfg.key === 'LW_OR_LC11_17') {
    keep = lwLand.and(lc.neq(11)).and(lc.neq(17));
  } else {
    keep = lwLand;
  }

  keep = keep.rename('BA_MaskKeep').toUint8();
  keep = keep.clip(aoiLand).updateMask(AOI_MASK);
  keep = keep.setDefaultProjection(PROJ_LC);

  return ee.Image(keep.set({
    'ba_mask_mode': cfg.key,
    'ba_mask_short_code': cfg.shortCode,
    'ba_mask_label': cfg.uiLabel,
    'ba_mask_year_used': y,
    'requested_year': year
  }));
}


/**
 * Build the annual excluded-mask as the logical complement of the keep-mask.
 * This is the raster shown in blue when the excluded-mask diagnostic is turned
 * on in the UI.
 */
function getAnnualBaExcludedMask(year, mode) {
  var cfg = getBaMaskConfig(mode);
  var excluded = getAnnualBaKeepMask(year, mode)
    .eq(0)
    .rename('BA_MaskExcluded')
    .toUint8();

  excluded = excluded.clip(aoiLand).updateMask(AOI_MASK);
  excluded = excluded.setDefaultProjection(PROJ_LC);

  return ee.Image(excluded.set({
    'ba_mask_mode': cfg.key,
    'ba_mask_short_code': cfg.shortCode,
    'ba_mask_label': cfg.uiLabel,
    'ba_mask_year_used': getMcd12Year(year),
    'requested_year': year
  }));
}


/**
 * Convert the annual excluded-mask to a self-masked display layer so only
 * excluded pixels remain visible on the map.
 */
function getAnnualBaExcludedMaskForDisplay(year, mode) {
  return getAnnualBaExcludedMask(year, mode).selfMask();
}


/**
 * Print a concise audit summary for the currently current BA mask mode and year,
 * including the rule description and the total keep / excluded areas in km².
 */
function printBaMaskDiagnostics(year, mode) {
  var cfg = getBaMaskConfig(mode);
  var d = ee.Dictionary({
    requested_year: year,
    ba_mask_year_used: getMcd12YearClient(year),
    ba_mask_mode: cfg.key,
    ba_mask_label: cfg.uiLabel,
    keep_rule: cfg.keepSummary,
    excluded_rule: cfg.excludedSummary,
    keep_area_km2: areaKm2FromMask(getAnnualBaKeepMask(year, mode)),
    excluded_area_km2: areaKm2FromMask(getAnnualBaExcludedMask(year, mode))
  });

  print('Burned-area mask diagnostics:', d);
}


// -----------------------------------------------------------------------------
// ANNOTATION:
// This is the monthly burned-area module. It builds the month-level BurnDate
// surface, reprojects the annual keep-mask to the BA grid, and outputs both
// BurnDate and BurnMask after masking.
// -----------------------------------------------------------------------------
/*** =====================================================================
  MODULE 1: MCD64A1 Burned Area (monthly; selectable annual mask)
===================================================================== ***/

/**
 * Safe empty BurnDate image returned when a month has no overlapping MCD64A1
 * imagery. This preserves schema/projection consistency for downstream logic.
 */
function emptyBurnDateImage() {
  return ee.Image.constant(0)
    .rename('BurnDate')
    .toInt16()
    .clip(aoiLand)
    .updateMask(AOI_MASK)
    .setDefaultProjection(PROJ_BA);
}


/**
 * Reproject an annual mask image onto the BA grid before it is used to filter
 * monthly BurnDate and BurnMask rasters.
 */
function toBAProjectionMask(maskImg, outBandName) {
  var out = ee.Image(maskImg)
    .rename(outBandName)
    .reproject({crs: PROJ_BA})
    .toInt16();

  out = out.clip(aoiLand).updateMask(AOI_MASK);
  out = out.setDefaultProjection(PROJ_BA);

  return out;
}


/**
 * Build the monthly raw BurnDate image from MCD64A1.
 *
 * The monthly rule used here is:
 *   monthly BurnDate = pixel-wise max(BurnDate) across all images intersecting
 *   the month window.
 */
function getMonthlyBurnDateImage(year, month) {
  var w = monthWindow(year, month);
  var col = IC_BA.filterDate(w.start, w.end).select('BurnDate');

  var burnDate = ee.Image(
    ee.Algorithms.If(
      col.size().gt(0),
      col.max().rename('BurnDate').toInt16(),
      emptyBurnDateImage()
    )
  );

  burnDate = burnDate.clip(aoiLand).updateMask(AOI_MASK);
  burnDate = burnDate.setDefaultProjection(PROJ_BA);

  return ee.Image(burnDate.set({
    'year': year,
    'month': month,
    'label': w.start.format('YYYY_MM'),
    'system:time_start': w.start.millis()
  }));
}


/**
 * Apply the selected annual BA keep-mask to the month’s BurnDate surface and
 * derive a two-band output containing:
 *   • BurnDate  (masked timing surface)
 *   • BurnMask  (BurnDate > 0 after masking)
 */
function getBurnMonthImage(year, month, mode) {
  var w = monthWindow(year, month);
  var cfg = getBaMaskConfig(mode);

  var burnDateRaw = getMonthlyBurnDateImage(year, month).rename('BurnDate').toInt16();
  var keepMaskBA = toBAProjectionMask(getAnnualBaKeepMask(year, mode), 'BA_MaskKeep');

  var burnDate = burnDateRaw
    .updateMask(keepMaskBA.eq(1))
    .rename('BurnDate')
    .toInt16();

  var burnMask = burnDateRaw
    .gt(0)
    .updateMask(keepMaskBA.eq(1))
    .rename('BurnMask')
    .toInt16();

  var out = burnDate.addBands(burnMask);

  out = out.clip(aoiLand).updateMask(AOI_MASK);
  out = out.setDefaultProjection(PROJ_BA);

  out = ee.Image(out.set({
    'year': year,
    'month': month,
    'label': w.start.format('YYYY_MM'),
    'ba_mask_mode': cfg.key,
    'ba_mask_short_code': cfg.shortCode,
    'ba_mask_label': cfg.uiLabel,
    'ba_mask_year_used': getMcd12Year(year),
    'system:time_start': w.start.millis()
  }));

  return out;
}


/**
 * Return a self-masked display version of the monthly BurnMask band so only
 * burned pixels remain visible in BurnMask view.
 */
function getBurnMaskForDisplay(year, month, mode) {
  var img = getBurnMonthImage(year, month, mode);
  return img.select('BurnMask').eq(1).selfMask();
}


/**
 * Return a display version of the monthly masked BurnDate band where only
 * positive BurnDate values are shown.
 */
function getBurnDateForDisplay(year, month, mode) {
  var img = getBurnMonthImage(year, month, mode);
  var bd = img.select('BurnDate');
  return bd.updateMask(bd.gt(0));
}


// -----------------------------------------------------------------------------
// ANNOTATION:
// This is the monthly LST module. It is deliberately separate from BA logic so
// the viewer can show/export temperature products without entangling them with
// the burned-area masking rules.
// -----------------------------------------------------------------------------
/*** =====================================================================
  MODULE 2: MOD11A1 LST (monthly composites)
===================================================================== ***/

/**
 * MOD11A1 mandatory QA filter.
 * Bits 0–1 of the QC band are retained only when they equal 0.
 */
function goodMandatoryQa(qcBand) {
  var mandatory = qcBand.bitwiseAnd(3); // bits 0–1
  return mandatory.eq(0);
}


/**
 * Convert one daily MOD11A1 image into QA-masked Celsius/view-time bands that
 * are ready for monthly averaging.
 */
function processDailyLST(img) {
  img = ee.Image(img);

  var dayOk = goodMandatoryQa(img.select('QC_Day'));
  var nightOk = goodMandatoryQa(img.select('QC_Night'));

  var dayC = img.select('LST_Day_1km')
    .multiply(0.02).subtract(273.15)
    .rename('LST_Day_C')
    .updateMask(dayOk);

  var nightC = img.select('LST_Night_1km')
    .multiply(0.02).subtract(273.15)
    .rename('LST_Night_C')
    .updateMask(nightOk);

  var dayVT = img.select('Day_view_time')
    .multiply(0.1)
    .rename('Day_view_time_h')
    .updateMask(dayOk);

  var nightVT = img.select('Night_view_time')
    .multiply(0.1)
    .rename('Night_view_time_h')
    .updateMask(nightOk);

  var out = dayC.addBands(nightC).addBands(dayVT).addBands(nightVT);

  // AOI-only display/export. No extra water/support mask is applied.
  out = out.clip(aoiLand).updateMask(AOI_MASK);
  out = ee.Image(out.copyProperties(img, ['system:time_start']));

  return out;
}


/**
 * Build the monthly LST composite from daily MOD11A1 imagery.
 * Output bands:
 *   • LST_Day_C
 *   • LST_Night_C
 *   • Day_view_time_h
 *   • Night_view_time_h
 *   • n_day
 *   • n_night
 */
function getMonthlyLSTImage(year, month) {
  var w = monthWindow(year, month);

  var daily = IC_LST.filterDate(w.start, w.end).map(processDailyLST);

  var meanLST = daily.select(['LST_Day_C', 'LST_Night_C']).mean();
  var meanVT  = daily.select(['Day_view_time_h', 'Night_view_time_h']).mean();

  var nDay   = daily.select('LST_Day_C').count().toFloat().rename('n_day');
  var nNight = daily.select('LST_Night_C').count().toFloat().rename('n_night');

  var out = meanLST.addBands(meanVT).addBands(nDay).addBands(nNight).toFloat();

  out = out.updateMask(AOI_MASK);
  out = out.setDefaultProjection(PROJ_LST);

  out = ee.Image(out.set({
    'year': year,
    'month': month,
    'label': w.start.format('YYYY_MM'),
    'system:time_start': w.start.millis()
  }));

  return out;
}


// -----------------------------------------------------------------------------
// ANNOTATION:
// The map is built from persistent ui.Map.Layer objects. Instead of constantly
// recreating the whole map state, the script updates these layer objects in
// place. That makes redraws more predictable and helps preserve ordering.
// -----------------------------------------------------------------------------
/*** =====================================================================
  MAP LAYERS (persistent; fixed ordering)
===================================================================== ***/
// Persistent base layers are created once and then updated in place during redraws.
var aoiOutline = ee.Image().byte().paint(ee.FeatureCollection([ee.Feature(aoiLand)]), 1, 2);
var aoiLayer = ui.Map.Layer(aoiOutline, {palette: ['000000'], opacity: 1.0}, 'AOI boundary (under LC)', true);

var lcLayer = ui.Map.Layer(ee.Image(0), LC_VIS, 'LC_Type1 (MCD12Q1)', true, 0.75);

var lstLayer = ui.Map.Layer(
  ee.Image(0),
  {min: LST_VIS_MIN_C, max: LST_VIS_MAX_C, palette: LST_PALETTE},
  'LST (MOD11A1)',
  true,
  0.85
);

var waterLayer = ui.Map.Layer(
  ee.Image(0),
  WATER_VIS,
  'Excluded-mask diagnostic',
  false,
  WATER_OPACITY
);

var burnLayer = ui.Map.Layer(
  ee.Image(0),
  BURNMASK_VIS,
  'Burn mask (MCD64A1; selectable annual mask; black)',
  true,
  0.85
);

// Base order:
// 1. AOI boundary
// 2. Land cover
// 3. LST
// 4. Active excluded-mask diagnostic
// 5. Burned area (topmost)
Map.layers().reset([aoiLayer, lcLayer, lstLayer, waterLayer, burnLayer]);
Map.centerObject(aoiLand, 7);


// -----------------------------------------------------------------------------
// ANNOTATION:
// This block is the glue between the controls panel and the map/export logic.
// The state object records current selections, and the update functions redraw
// layers or switch into stack mode without changing the underlying datasets.
// -----------------------------------------------------------------------------
/*** =====================================================================
  UI STATE + UPDATE FUNCTIONS
===================================================================== ***/
// UI state is stored here so redraws and export actions share a single source of truth.
// Client-side state object. Nothing here changes the analytical datasets on
// disk; it only records what the viewer should currently display or export.
var state = {
  year: INIT_YEAR,
  month: INIT_MONTH,
  lstMode: 'Day',
  burnMode: 'Mask',
  baMaskMode: DEFAULT_BA_MASK_MODE,
  showAOI: true,
  showLC: false,
  showWater: true,
  showBurn: true,
  showLST: false,
  showLegend: true,
  panelView: 'controls',
  stackLST: false,
  stackBurn: false
};


/**
 * Resolve which LST band should be displayed on the map. Exports still include
 * both day and night information regardless of this display choice.
 */
function getLSTDisplayBandName() {
  return (state.lstMode === 'Night') ? 'LST_Night_C' : 'LST_Day_C';
}


/**
 * Restore the persistent base-layer set in the intended order.
 *
 * IMPORTANT:
 * We do NOT remove "extra" layers by trimming from the end of Map.layers(),
 * because LST stack layers are intentionally inserted *before* the excluded-mask
 * and burned-area layers. In that situation, end-trimming can accidentally
 * delete the persistent waterLayer / burnLayer objects while leaving some stack
 * layers behind.
 *
 * By resetting explicitly to the five persistent layer objects, we guarantee
 * that stack-mode clean-up is deterministic and that the excluded-mask
 * diagnostic layer remains available after entering/leaving stack views.
 */
function clearDynamicLayers() {
  Map.layers().reset([aoiLayer, lcLayer, lstLayer, waterLayer, burnLayer]);
}


/**
 * Synchronise small UI text elements with the current BA mask mode.
 * This keeps the panel and legend consistent with the active rule.
 */
function updateDynamicLabels() {
  var cfg = getBaMaskConfig(state.baMaskMode);
  if (maskSummaryLabel) {
    maskSummaryLabel.setValue('Current BA mask mode: ' + cfg.uiLabel + (state.baMaskMode === ANALYTICAL_BASELINE_MASK ? ' [official c1 baseline]' : ' [sensitivity comparison]'));
  }
  if (legendActiveMaskLabel) {
    legendActiveMaskLabel.setValue('Current mode: ' + cfg.uiLabel + (state.baMaskMode === ANALYTICAL_BASELINE_MASK ? ' [baseline]' : ' [sensitivity]'));
  }
}


/**
 * Redraw the standard single-month map view using the current UI state.
 * This updates:
 *   • LC layer
 *   • monthly LST layer
 *   • annual excluded-mask diagnostic
 *   • monthly BA layer
 */
function updateBaseMap() {
  clearDynamicLayers();
  state.stackLST = false;
  state.stackBurn = false;
  updateDynamicLabels();

  var cfg = getBaMaskConfig(state.baMaskMode);

  aoiLayer.setShown(state.showAOI);

  // LC
  var lcYearUsed = getMcd12YearClient(state.year);
  var lc = getLcImage(state.year);
  lcLayer.setEeObject(lc);
  lcLayer.setName('LC_Type1 (MCD12Q1) — year used: ' + lcYearUsed);
  lcLayer.setShown(state.showLC);

  // LST
  if (state.showLST) {
    var lst = getMonthlyLSTImage(state.year, state.month).select(getLSTDisplayBandName());
    lstLayer.setEeObject(lst);
    lstLayer.setVisParams({min: LST_VIS_MIN_C, max: LST_VIS_MAX_C, palette: LST_PALETTE});
    lstLayer.setName('LST ' + state.lstMode + ' (°C; monthly mean; AOI-only) — ' +
      state.year + '-' + pad2(state.month));
    lstLayer.setShown(true);
  } else {
    lstLayer.setShown(false);
  }

  // Active excluded-mask diagnostic
  if (state.showWater) {
    var excluded = getAnnualBaExcludedMaskForDisplay(state.year, state.baMaskMode);
    waterLayer.setEeObject(excluded);
    waterLayer.setVisParams(WATER_VIS);
    waterLayer.setName('Excluded-mask diagnostic — ' + cfg.layerLabel + ' — year ' + lcYearUsed);
    waterLayer.setShown(true);
  } else {
    waterLayer.setShown(false);
  }

  // Burned area
  if (state.showBurn) {
    if (state.burnMode === 'Mask') {
      burnLayer.setEeObject(getBurnMaskForDisplay(state.year, state.month, state.baMaskMode));
      burnLayer.setVisParams(BURNMASK_VIS);
      burnLayer.setName('Burn mask (BurnDate > 0; ' + cfg.shortCode + '; black; AOI-only) — ' +
        state.year + '-' + pad2(state.month));
    } else {
      burnLayer.setEeObject(getBurnDateForDisplay(state.year, state.month, state.baMaskMode));
      burnLayer.setVisParams(BURNDAY_VIS);
      burnLayer.setName('BurnDate diagnostic (' + cfg.shortCode + '; greyscale; AOI-only) — ' +
        state.year + '-' + pad2(state.month));
    }
    burnLayer.setShown(true);
  } else {
    burnLayer.setShown(false);
  }
}


/**
 * Replace the single-month LST view with a 12-layer annual LST stack while
 * keeping the excluded-mask and BA overlays consistent with the selected year.
 */
function addLSTStackForYear(year) {
  clearDynamicLayers();
  state.stackLST = true;
  state.stackBurn = false;
  updateDynamicLabels();

  var cfg = getBaMaskConfig(state.baMaskMode);
  var lcYearUsed = getMcd12YearClient(year);

  aoiLayer.setShown(state.showAOI);

  var lc = getLcImage(year);
  lcLayer.setEeObject(lc);
  lcLayer.setName('LC_Type1 (MCD12Q1) — year used: ' + lcYearUsed);
  lcLayer.setShown(state.showLC);

  lstLayer.setShown(false);

  // Insert before the excluded-mask and burn layers so Burn remains topmost.
  // Reverse insertion yields Jan..Dec ordering in the layer list.
  for (var m = 12; m >= 1; m--) {
    var img = getMonthlyLSTImage(year, m).select(getLSTDisplayBandName());
    var nm = 'LST ' + state.lstMode + ' (°C; AOI-only) — ' + year + '-' + pad2(m);
    var lyr = ui.Map.Layer(
      img,
      {min: LST_VIS_MIN_C, max: LST_VIS_MAX_C, palette: LST_PALETTE},
      nm,
      state.showLST && (m === state.month),
      0.85
    );
    Map.layers().insert(3, lyr);
  }

  if (state.showWater) {
    waterLayer.setEeObject(getAnnualBaExcludedMaskForDisplay(year, state.baMaskMode));
    waterLayer.setVisParams(WATER_VIS);
    waterLayer.setName('Excluded-mask diagnostic — ' + cfg.layerLabel + ' — year ' + lcYearUsed);
    waterLayer.setShown(true);
  } else {
    waterLayer.setShown(false);
  }

  if (state.showBurn) {
    if (state.burnMode === 'Mask') {
      burnLayer.setEeObject(getBurnMaskForDisplay(year, state.month, state.baMaskMode));
      burnLayer.setVisParams(BURNMASK_VIS);
      burnLayer.setName('Burn mask (BurnDate > 0; ' + cfg.shortCode + '; black; AOI-only) — ' +
        year + '-' + pad2(state.month));
    } else {
      burnLayer.setEeObject(getBurnDateForDisplay(year, state.month, state.baMaskMode));
      burnLayer.setVisParams(BURNDAY_VIS);
      burnLayer.setName('BurnDate diagnostic (' + cfg.shortCode + '; greyscale; AOI-only) — ' +
        year + '-' + pad2(state.month));
    }
    burnLayer.setShown(true);
  } else {
    burnLayer.setShown(false);
  }
}


/**
 * Replace the single-month BA view with a 12-layer annual BA stack using the
 * currently selected Burn display mode and active annual BA mask rule.
 */
function addBurnStackForYear(year) {
  clearDynamicLayers();
  state.stackBurn = true;
  state.stackLST = false;
  updateDynamicLabels();

  var cfg = getBaMaskConfig(state.baMaskMode);
  var lcYearUsed = getMcd12YearClient(year);

  aoiLayer.setShown(state.showAOI);

  var lc = getLcImage(year);
  lcLayer.setEeObject(lc);
  lcLayer.setName('LC_Type1 (MCD12Q1) — year used: ' + lcYearUsed);
  lcLayer.setShown(state.showLC);

  lstLayer.setShown(false);
  burnLayer.setShown(false);

  if (state.showWater) {
    waterLayer.setEeObject(getAnnualBaExcludedMaskForDisplay(year, state.baMaskMode));
    waterLayer.setVisParams(WATER_VIS);
    waterLayer.setName('Excluded-mask diagnostic — ' + cfg.layerLabel + ' — year ' + lcYearUsed);
    waterLayer.setShown(true);
  } else {
    waterLayer.setShown(false);
  }

  for (var m = 1; m <= 12; m++) {
    var img = (state.burnMode === 'Mask') ?
      getBurnMaskForDisplay(year, m, state.baMaskMode) :
      getBurnDateForDisplay(year, m, state.baMaskMode);

    var vis = (state.burnMode === 'Mask') ? BURNMASK_VIS : BURNDAY_VIS;
    var nm = (state.burnMode === 'Mask') ?
      ('Burn mask (' + cfg.shortCode + '; black; AOI-only) — ' + year + '-' + pad2(m)) :
      ('BurnDate diagnostic (' + cfg.shortCode + '; greyscale; AOI-only) — ' + year + '-' + pad2(m));

    Map.layers().add(ui.Map.Layer(img, vis, nm, state.showBurn && (m === state.month), 0.85));
  }
}


/**
 * Dispatch redraw logic according to whether the UI is in single-month mode,
 * LST stack mode, or Burn stack mode.
 */
function applyCurrentView() {
  if (state.stackLST) addLSTStackForYear(state.year);
  else if (state.stackBurn) addBurnStackForYear(state.year);
  else updateBaseMap();
}

// Debounce redraws so rapid slider moves do not trigger unnecessary repeated work.
var redrawDebounced = ui.util.debounce(function() {
  applyCurrentView();
}, 150);


// -----------------------------------------------------------------------------
// ANNOTATION:
// These helpers queue Drive exports but do not run them automatically.
// They also print useful diagnostics before export so the user can inspect the
// current month/year support and the current annual BA mask rule.
// -----------------------------------------------------------------------------
/*** =====================================================================
  EXPORT HELPERS
===================================================================== ***/


/**
 * Minimum-scope diagnostic export:
 * annual keep-mask raster for the current BA mask mode.
 */
function exportBaKeepMaskYear(year) {
  year = Math.round(year);

  var cfg = getBaMaskConfig(state.baMaskMode);
  var img = getAnnualBaKeepMask(year, state.baMaskMode).toUint8();
  var desc = PREFIX_BA_KEEP + '_' + cfg.shortCode + '_' + year;

  printBaMaskDiagnostics(year, state.baMaskMode);
  scheduleImageToDrive(img, desc, FOLDER_BA_DIAG, SPEC_LC, NODATA_MASK);
  print('Queued annual BA keep-mask diagnostic export (' + cfg.shortCode + '):', desc);
}


/**
 * Minimum-scope diagnostic export:
 * annual excluded-mask raster for the current BA mask mode.
 */
function exportBaExcludedMaskYear(year) {
  year = Math.round(year);

  var cfg = getBaMaskConfig(state.baMaskMode);
  var img = getAnnualBaExcludedMask(year, state.baMaskMode).toUint8();
  var desc = PREFIX_BA_EXCLUDED + '_' + cfg.shortCode + '_' + year;

  printBaMaskDiagnostics(year, state.baMaskMode);
  scheduleImageToDrive(img, desc, FOLDER_BA_DIAG, SPEC_LC, NODATA_MASK);
  print('Queued annual BA excluded-mask diagnostic export (' + cfg.shortCode + '):', desc);
}


/**
 * Minimum-scope diagnostic export:
 * monthly masked BurnMask raster for the current BA mask mode.
 */
function exportActiveBurnMaskMonth(year, month) {
  year = Math.round(year);
  month = Math.round(month);

  var cfg = getBaMaskConfig(state.baMaskMode);

  printSelectedMonthCounts(year, month);
  printBaMaskDiagnostics(year, state.baMaskMode);

  var n = getClientMonthCount(IC_BA, year, month);
  if (n < 1) {
    print('SKIP: No MCD64A1 monthly image available for ' + year + '-' + pad2(month) + '.');
    return;
  }

  var img = getBurnMonthImage(year, month, state.baMaskMode).select('BurnMask').toUint8();
  var desc = PREFIX_BA_BURNMASK + '_' + cfg.shortCode + '_' + year + '_' + pad2(month);

  scheduleImageToDrive(img, desc, FOLDER_BA_DIAG, SPEC_BA, NODATA_MASK);
  print('Queued monthly masked BurnMask diagnostic export (' + cfg.shortCode + '):', desc);
}


/**
 * Minimum-scope diagnostic export:
 * monthly masked BurnDate raster for the current BA mask mode.
 */
function exportActiveBurnDateMonth(year, month) {
  year = Math.round(year);
  month = Math.round(month);

  var cfg = getBaMaskConfig(state.baMaskMode);

  printSelectedMonthCounts(year, month);
  printBaMaskDiagnostics(year, state.baMaskMode);

  var n = getClientMonthCount(IC_BA, year, month);
  if (n < 1) {
    print('SKIP: No MCD64A1 monthly image available for ' + year + '-' + pad2(month) + '.');
    return;
  }

  var img = getBurnMonthImage(year, month, state.baMaskMode).select('BurnDate').toInt16();
  var desc = PREFIX_BA_BURNDATE_DI + '_' + cfg.shortCode + '_' + year + '_' + pad2(month);

  scheduleImageToDrive(img, desc, FOLDER_BA_DIAG, SPEC_BA, NODATA_BA);
  print('Queued monthly masked BurnDate diagnostic export (' + cfg.shortCode + '):', desc);
}


/**
 * Queue the standard monthly MOD11A1 export.
 */
function exportLSTMonth(year, month) {
  year = Math.round(year);
  month = Math.round(month);

  printSelectedMonthCounts(year, month);

  var n = getClientMonthCount(IC_LST, year, month);
  if (n < 1) {
    print('SKIP: No MOD11A1 daily images available for ' + year + '-' + pad2(month) + '.');
    return;
  }

  var img = getMonthlyLSTImage(year, month).toFloat();
  var desc = PREFIX_LST + '_' + year + '_' + pad2(month);

  scheduleImageToDrive(img, desc, FOLDER_LST, SPEC_LST, NODATA_LST);
  print('Queued MOD11A1 selected-month export:', desc);
}


/**
 * Queue the standard monthly MCD64A1 BA export using the current BA mask mode.
 * The export contains both BurnDate and BurnMask bands.
 */
function exportBAMonth(year, month) {
  year = Math.round(year);
  month = Math.round(month);

  var cfg = getBaMaskConfig(state.baMaskMode);

  printSelectedMonthCounts(year, month);
  printBaMaskDiagnostics(year, state.baMaskMode);

  var n = getClientMonthCount(IC_BA, year, month);
  if (n < 1) {
    print('SKIP: No MCD64A1 monthly image available for ' + year + '-' + pad2(month) + '.');
    return;
  }

  var img = getBurnMonthImage(year, month, state.baMaskMode).toInt16();
  var desc = PREFIX_BA + '_' + cfg.shortCode + '_' + year + '_' + pad2(month);

  scheduleImageToDrive(img, desc, FOLDER_BA, SPEC_BA, NODATA_BA);
  print('Queued MCD64A1 selected-month export (' + cfg.shortCode + '):', desc);
}


/**
 * Convenience wrapper for queuing the standard monthly LST + BA product exports
 * together.
 */
function exportAllMonthlyProducts(year, month) {
  exportLSTMonth(year, month);
  exportBAMonth(year, month);
  print('Queued all applicable selected-month exports for ' + year + '-' + pad2(month) + '.');
}


/**
 * Queue 12 monthly LST exports for the selected year.
 */
function exportLSTYear(year) {
  year = Math.round(year);

  printMonthCountsForYear(year);

  for (var m = 1; m <= 12; m++) {
    var n = getClientMonthCount(IC_LST, year, m);
    if (n < 1) {
      print('SKIP: No MOD11A1 daily images available for ' + year + '-' + pad2(m) + '.');
      continue;
    }

    var img = getMonthlyLSTImage(year, m).toFloat();
    var desc = PREFIX_LST + '_' + year + '_' + pad2(m);

    scheduleImageToDrive(img, desc, FOLDER_LST, SPEC_LST, NODATA_LST);
  }

  print('Queued MOD11A1 selected-year exports for year ' + year + '. Start tasks from the Tasks tab.');
}


/**
 * Queue 12 monthly BA exports for the selected year using the active BA mask
 * mode.
 */
function exportBAYear(year) {
  year = Math.round(year);

  var cfg = getBaMaskConfig(state.baMaskMode);

  printMonthCountsForYear(year);
  printBaMaskDiagnostics(year, state.baMaskMode);

  for (var m = 1; m <= 12; m++) {
    var n = getClientMonthCount(IC_BA, year, m);
    if (n < 1) {
      print('SKIP: No MCD64A1 monthly image available for ' + year + '-' + pad2(m) + '.');
      continue;
    }

    var img = getBurnMonthImage(year, m, state.baMaskMode).toInt16();
    var desc = PREFIX_BA + '_' + cfg.shortCode + '_' + year + '_' + pad2(m);

    scheduleImageToDrive(img, desc, FOLDER_BA, SPEC_BA, NODATA_BA);
  }

  print('Queued MCD64A1 selected-year exports for year ' + year + ' using BA mask mode ' + cfg.shortCode + ' (' + (cfg.shortCode === ANALYTICAL_BASELINE_MASK ? 'baseline' : 'sensitivity') + '). Start tasks from the Tasks tab.');
}


/**
 * Queue the annual LC_Type1 export for the selected year.
 */
function exportLCYear(year) {
  year = Math.round(year);

  var lcYearUsed = getMcd12YearClient(year);
  var img = getLcImage(year).toUint8();
  var desc = PREFIX_LC + '_' + lcYearUsed;

  scheduleImageToDrive(img, desc, FOLDER_LC, SPEC_LC, NODATA_LC);
  print('Queued MCD12Q1 LC_Type1 selected-year export for year ' + lcYearUsed + '. Start task from the Tasks tab.');
}


/**
 * Convenience wrapper for queuing all standard selected-year product exports.
 */
function exportAllApplicableYear(year) {
  exportLSTYear(year);
  exportBAYear(year);
  exportLCYear(year);
  print('Queued all applicable selected-year exports for year ' + year + '.');
}



// -----------------------------------------------------------------------------
// ANNOTATION:
// The viewer uses one floating panel with internal tabs rather than multiple
// independent floating panels. This keeps the UI manageable on smaller screens
// and avoids unsupported CSS-style scrolling tricks.
// -----------------------------------------------------------------------------
/*** =====================================================================
  FLOATING UI PANEL (single panel with switchable views)

  DESIGN NOTE
   - A dual-panel layout can overlap on smaller browser
     windows because both floating panels competed for the same left-side
     vertical space.
   - This revision uses one floating top-left panel with two internal views:
       * Controls view
       * Exports view
   - Only one internal view is shown at a time, so overlap is eliminated while
     preserving the existing export and display logic.
===================================================================== ***/
var mainPanel = null;
var controlsViewPanel = null;
var layersViewPanel = null;
var exportsViewPanel = null;
var aboutViewPanel = null;
var controlsTabButton = null;
var layersTabButton = null;
var exportsTabButton = null;
var aboutTabButton = null;


/**
 * Switch the floating left panel between the Controls, Layers, Exports, and
 * About views. Tabs are used instead of a single long panel so the viewer
 * remains usable on smaller displays without unsupported overflow styling.
 */
function setPanelView(viewName) {
  var allowed = ['controls', 'layers', 'exports', 'about'];
  state.panelView = allowed.indexOf(viewName) >= 0 ? viewName : 'controls';
  updateMainPanelUi();
}


/**
 * Apply the requested panel-view state so exactly one internal view is shown at
 * a time.
 */
function updateMainPanelUi() {
  if (controlsViewPanel) {
    controlsViewPanel.style().set('shown', state.panelView === 'controls');
  }
  if (layersViewPanel) {
    layersViewPanel.style().set('shown', state.panelView === 'layers');
  }
  if (exportsViewPanel) {
    exportsViewPanel.style().set('shown', state.panelView === 'exports');
  }
  if (aboutViewPanel) {
    aboutViewPanel.style().set('shown', state.panelView === 'about');
  }
  if (controlsTabButton) {
    controlsTabButton.setLabel(state.panelView === 'controls' ? '● Controls' : 'Controls');
  }
  if (layersTabButton) {
    layersTabButton.setLabel(state.panelView === 'layers' ? '● Layers' : 'Layers');
  }
  if (exportsTabButton) {
    exportsTabButton.setLabel(state.panelView === 'exports' ? '● Exports' : 'Exports');
  }
  if (aboutTabButton) {
    aboutTabButton.setLabel(state.panelView === 'about' ? '● About' : 'About');
  }
}

/** Small helper to create a compact section title inside the floating panel. */
function makeSectionLabel(text) {
  return ui.Label(text, {
    fontWeight: 'bold',
    fontSize: '12px',
    margin: '10px 0 4px 0'
  });
}

/** Small helper to create card-like subsection containers. */
function makeCard(children) {
  return ui.Panel(children, null, {
    stretch: 'horizontal',
    margin: '0 0 8px 0',
    padding: '8px',
    backgroundColor: 'ffffff'
  });
}

// Build the main floating control panel. Subviews are added later and shown
// or hidden with setPanelView(...).
mainPanel = ui.Panel({
  style: {
    position: 'top-left',
    padding: '8px',
    width: '470px',
    maxHeight: '640px',
    backgroundColor: 'ffffffdd'
  }
});

mainPanel.add(ui.Label({
  value: 'RP1 c1 Viewer — Unified MODIS QA, sensitivity comparison, and GeoTIFF export',
  style: {fontWeight: 'bold', fontSize: '13px', margin: '0 0 6px 0'}
}));

mainPanel.add(ui.Label({
  value: 'Official analytical baseline: LW_OR_LC17. Alternative mask modes remain available here as sensitivity views and export options only.',
  style: {fontSize: '11px', color: '444', margin: '0 0 8px 0'}
}));

var panelNav = ui.Panel({
  layout: ui.Panel.Layout.flow('horizontal'),
  style: {stretch: 'horizontal', margin: '0 0 8px 0'}
});
controlsTabButton = ui.Button({
  label: 'Controls',
  onClick: function() { setPanelView('controls'); },
  style: {stretch: 'horizontal'}
});
layersTabButton = ui.Button({
  label: 'Layers',
  onClick: function() { setPanelView('layers'); },
  style: {stretch: 'horizontal'}
});
exportsTabButton = ui.Button({
  label: 'Exports',
  onClick: function() { setPanelView('exports'); },
  style: {stretch: 'horizontal'}
});
aboutTabButton = ui.Button({
  label: 'About',
  onClick: function() { setPanelView('about'); },
  style: {stretch: 'horizontal'}
});
panelNav.add(controlsTabButton);
panelNav.add(layersTabButton);
panelNav.add(exportsTabButton);
panelNav.add(aboutTabButton);
mainPanel.add(panelNav);

controlsViewPanel = ui.Panel({style: {stretch: 'horizontal'}});
controlsViewPanel.add(ui.Label({
  value: 'Study window: ' + YEAR_MIN + '–' + YEAR_MAX + ' | All baseline previews are aligned to the clean analytical c1 overlap-era window.',
  style: {fontSize: '11px', color: '444', margin: '0 0 8px 0'}
}));

var yearLabel = ui.Label('Year: ' + state.year);
var yearSlider = ui.Slider({
  min: YEAR_MIN,
  max: YEAR_MAX,
  step: 1,
  value: state.year,
  style: {stretch: 'horizontal'}
});
yearSlider.onChange(function(v) {
  state.year = Math.round(v);
  yearLabel.setValue('Year: ' + state.year);
  redrawDebounced();
});

var monthLabel = ui.Label('Month: ' + pad2(state.month));
var monthSlider = ui.Slider({
  min: 1,
  max: 12,
  step: 1,
  value: state.month,
  style: {stretch: 'horizontal'}
});
monthSlider.onChange(function(v) {
  state.month = Math.round(v);
  monthLabel.setValue('Month: ' + pad2(state.month));
  redrawDebounced();
});

controlsViewPanel.add(makeCard([
  makeSectionLabel('Time selection'),
  yearLabel,
  yearSlider,
  monthLabel,
  monthSlider
]));

var baMaskSelect = ui.Select({
  items: [
    {label: BA_MASK_MODES.LW_OR_LC17.uiLabel, value: 'LW_OR_LC17'},
    {label: BA_MASK_MODES.LW.uiLabel, value: 'LW'},
    {label: BA_MASK_MODES.LC17.uiLabel, value: 'LC17'},
    {label: BA_MASK_MODES.LC11_17.uiLabel, value: 'LC11_17'},
    {label: BA_MASK_MODES.LW_OR_LC11_17.uiLabel, value: 'LW_OR_LC11_17'}
  ],
  value: state.baMaskMode,
  onChange: function(v) {
    state.baMaskMode = getBaMaskMode(v);
    updateDynamicLabels();
    redrawDebounced();
  },
  style: {stretch: 'horizontal'}
});

var maskSummaryLabel = ui.Label('', {
  fontSize: '11px',
  color: '444',
  margin: '4px 0 0 0'
});

var lstSelect = ui.Select({
  items: [{label: 'Day', value: 'Day'}, {label: 'Night', value: 'Night'}],
  value: state.lstMode,
  onChange: function(v) {
    state.lstMode = v;
    redrawDebounced();
  },
  style: {stretch: 'horizontal'}
});

var burnSelect = ui.Select({
  items: [
    {label: 'Burn mask (BurnDate > 0; current BA mask; black)', value: 'Mask'},
    {label: 'BurnDate diagnostic (current BA mask; greyscale)', value: 'BurnDate'}
  ],
  value: state.burnMode,
  onChange: function(v) {
    state.burnMode = v;
    redrawDebounced();
  },
  style: {stretch: 'horizontal'}
});

controlsViewPanel.add(makeCard([
  makeSectionLabel('Baseline and sensitivity mode'),
  ui.Label('Select the official baseline or a sensitivity alternative for viewing and BA-related raster export:', {fontSize: '11px', margin: '0 0 4px 0'}),
  baMaskSelect,
  maskSummaryLabel,
  ui.Label('LST display band (map only; exports always include Day + Night):', {margin: '8px 0 2px 0'}),
  lstSelect,
  ui.Label('Burn display mode:', {margin: '8px 0 2px 0'}),
  burnSelect
]));

controlsViewPanel.add(makeCard([
  makeSectionLabel('Quick navigation'),
  ui.Label('Use the Layers tab for visibility toggles and year-stack tools, or the Exports tab to queue GeoTIFF products.', {fontSize: '11px', color: '444', margin: '0 0 6px 0'}),
  ui.Button({
    label: 'Open Layers tab',
    onClick: function() { setPanelView('layers'); },
    style: {stretch: 'horizontal'}
  }),
  ui.Button({
    label: 'Open Exports tab',
    onClick: function() { setPanelView('exports'); },
    style: {stretch: 'horizontal'}
  })
]));

layersViewPanel = ui.Panel({style: {stretch: 'horizontal'}});
layersViewPanel.add(ui.Label({
  value: 'Layer visibility, legend control, and year-stack tools are grouped here so the main Controls tab stays compact.',
  style: {fontSize: '11px', color: '444', margin: '0 0 8px 0'}
}));

layersViewPanel.add(makeCard([
  makeSectionLabel('Layer visibility'),
  ui.Checkbox('Show AOI boundary (under LC)', state.showAOI, function(v){ state.showAOI = v; redrawDebounced(); }),
  ui.Checkbox('Show Land Cover (LC_Type1)', state.showLC, function(v){ state.showLC = v; redrawDebounced(); }),
  ui.Checkbox('Show LST overlay (MOD11A1)', state.showLST, function(v){ state.showLST = v; redrawDebounced(); }),
  ui.Checkbox('Show current excluded-mask diagnostic (blue)', state.showWater, function(v){ state.showWater = v; redrawDebounced(); }),
  ui.Checkbox('Show Burn overlay (MCD64A1; topmost)', state.showBurn, function(v){ state.showBurn = v; redrawDebounced(); }),
  ui.Checkbox('Show legend', state.showLegend, function(v){ state.showLegend = v; legend.style().set('shown', v); })
]));

layersViewPanel.add(makeCard([
  makeSectionLabel('Year-stack visualisation'),
  ui.Button({
    label: 'Add 12-month LST stack for selected year',
    onClick: function(){ state.stackLST = true; state.stackBurn = false; applyCurrentView(); },
    style: {stretch: 'horizontal'}
  }),
  ui.Button({
    label: 'Add 12-month Burn stack for selected year',
    onClick: function(){ state.stackBurn = true; state.stackLST = false; applyCurrentView(); },
    style: {stretch: 'horizontal'}
  }),
  ui.Button({
    label: 'Return to single-month view (sliders)',
    onClick: function(){ state.stackLST = false; state.stackBurn = false; applyCurrentView(); },
    style: {stretch: 'horizontal'}
  })
]));

exportsViewPanel = ui.Panel({style: {stretch: 'horizontal'}});
exportsViewPanel.add(ui.Label({
  value: 'Exports view',
  style: {fontWeight: 'bold', fontSize: '13px', margin: '0 0 6px 0'}
}));
exportsViewPanel.add(ui.Label({
  value: 'Queue GeoTIFF products and diagnostic rasters here. BA-related export filenames include the current mask code so baseline and sensitivity runs remain distinguishable.',
  style: {fontSize: '11px', color: '444', margin: '0 0 8px 0'}
}));

exportsViewPanel.add(makeCard([
  makeSectionLabel('Selected-month exports'),
  ui.Button({ label: 'Export selected month — MOD11A1 LST', onClick: function(){ exportLSTMonth(state.year, state.month); }, style: {stretch: 'horizontal'} }),
  ui.Button({ label: 'Export selected month — MCD64A1 Burned Area (current BA mask mode)', onClick: function(){ exportBAMonth(state.year, state.month); }, style: {stretch: 'horizontal'} }),
  ui.Button({ label: 'Export selected month — All monthly products', onClick: function(){ exportAllMonthlyProducts(state.year, state.month); }, style: {stretch: 'horizontal'} })
]));

exportsViewPanel.add(makeCard([
  makeSectionLabel('Diagnostic annual or masked-layer exports'),
  ui.Label('These exports write the underlying annual masks or masked BA rasters. LW_OR_LC17 is the official baseline; other modes are sensitivity exports.', {fontSize: '11px', color: '444', margin: '0 0 4px 0'}),
  ui.Button({ label: 'Export selected month — current masked BurnMask raster', onClick: function(){ exportActiveBurnMaskMonth(state.year, state.month); }, style: {stretch: 'horizontal'} }),
  ui.Button({ label: 'Export selected month — current masked BurnDate raster', onClick: function(){ exportActiveBurnDateMonth(state.year, state.month); }, style: {stretch: 'horizontal'} }),
  ui.Button({ label: 'Export selected year — current keep-mask raster', onClick: function(){ exportBaKeepMaskYear(state.year); }, style: {stretch: 'horizontal'} }),
  ui.Button({ label: 'Export selected year — current excluded-mask raster', onClick: function(){ exportBaExcludedMaskYear(state.year); }, style: {stretch: 'horizontal'} })
]));

exportsViewPanel.add(makeCard([
  makeSectionLabel('Selected-year exports'),
  ui.Button({ label: 'Export selected year — MOD11A1 LST (12 months)', onClick: function(){ exportLSTYear(state.year); }, style: {stretch: 'horizontal'} }),
  ui.Button({ label: 'Export selected year — MCD64A1 Burned Area (12 months; current BA mask mode)', onClick: function(){ exportBAYear(state.year); }, style: {stretch: 'horizontal'} }),
  ui.Button({ label: 'Export selected year — MCD12Q1 LC_Type1', onClick: function(){ exportLCYear(state.year); }, style: {stretch: 'horizontal'} }),
  ui.Button({ label: 'Export selected year — All applicable products', onClick: function(){ exportAllApplicableYear(state.year); }, style: {stretch: 'horizontal'} })
]));

exportsViewPanel.add(ui.Label({
  value:
    'Viewer release=' + SCRIPT_RELEASE + ' | baseline=' + ANALYTICAL_BASELINE_MASK +
    ' | USE_NATIVE_TRANSFORM=' + USE_NATIVE_TRANSFORM +
    ' | NoData(LST/BA/LC/Mask)=' + NODATA_LST + '/' + NODATA_BA + '/' + NODATA_LC + '/' + NODATA_MASK,
  style: {margin: '8px 0 0 0', fontSize: '11px', color: '444'}
}));

aboutViewPanel = ui.Panel({style: {stretch: 'horizontal'}});
aboutViewPanel.add(makeCard([
  makeSectionLabel('About this viewer'),
  ui.Label('This script is the QA and sensitivity companion to the clean c1 panel extractors. It is not the canonical CSV panel builder.', {fontSize: '11px', color: '444', margin: '0 0 6px 0'}),
  ui.Label('Official analytical baseline: ' + ANALYTICAL_BASELINE_MASK, {fontSize: '11px', margin: '0 0 4px 0'}),
  ui.Label('Baseline keep rule: keep LW == 2 and LC_Type1 != 17', {fontSize: '11px', margin: '0 0 2px 0'}),
  ui.Label('Sensitivity options retained here: LW, LC17, LC11_17, LW_OR_LC11_17', {fontSize: '11px', margin: '0 0 2px 0'}),
  ui.Label('Study window: ' + YEAR_MIN + '-01 through ' + YEAR_MAX + '-12 | Exact-year MCD12Q1 support only; no denominator fallback.', {fontSize: '11px', margin: '0 0 2px 0'}),
  ui.Label('Use Controls to choose year/month and mask mode, Layers for visibility and year-stacks, and Exports for GeoTIFF queueing.', {fontSize: '11px', margin: '6px 0 0 0'})
]));

mainPanel.add(controlsViewPanel);
mainPanel.add(layersViewPanel);
mainPanel.add(exportsViewPanel);
mainPanel.add(aboutViewPanel);
Map.add(mainPanel);
updateMainPanelUi();

// -----------------------------------------------------------------------------
// ANNOTATION:
// The legend is intentionally independent of the left control panel so that it
// can stay visible while the user switches between tabs. It also doubles as a
// compact reminder of the currently active baseline/sensitivity mode.
// -----------------------------------------------------------------------------
/*** =====================================================================
  RIGHT-SIDE LEGEND (LC + LST + EXCLUDED MASK + BA)
===================================================================== ***/

/**
 * Small helper for building a colour chip + label row in the right-side legend.
 */
function makeLegendRow(hexColor, labelText) {
  var colorBox = ui.Label('', {
    backgroundColor: '#' + hexColor,
    padding: '7px',
    margin: '0 0 3px 0'
  });
  var label = ui.Label(labelText, {
    margin: '0 0 3px 6px',
    fontSize: '11px',
    whiteSpace: 'nowrap'
  });
  return ui.Panel([colorBox, label], ui.Panel.Layout.flow('horizontal'));
}

var lstLegendImg = ee.Image.pixelLonLat().select('longitude');
var lstThumb = ui.Thumbnail({
  image: lstLegendImg.visualize({min: 0, max: 1, palette: LST_PALETTE}),
  params: {bbox: [0, 0, 1, 0.1], dimensions: '280x18', format: 'png'},
  style: {stretch: 'horizontal', margin: '4px 0 6px 0', maxHeight: '18px'}
});

// The legend remains separate on the right so the left-side working panel stays compact.
// Build the independent legend panel shown on the right side of the map.
var legend = ui.Panel({
  style: {
    position: 'top-right',
    padding: '10px 12px',
    backgroundColor: 'ffffffcc',
    width: '380px',
    maxHeight: '600px'
  }
});

legend.add(ui.Label('Legend', {fontWeight: 'bold', margin: '0 0 6px 0'}));
legend.add(ui.Label('Viewer release: ' + SCRIPT_RELEASE + ' | Official baseline: ' + ANALYTICAL_BASELINE_MASK, {fontSize: '11px', color: '444', margin: '0 0 6px 0'}));

legend.add(ui.Label('Burned area (MCD64A1)', {
  fontWeight: 'bold',
  fontSize: '11px',
  margin: '8px 0 4px 0'
}));
legend.add(makeLegendRow('000000', 'Burn mask (BurnDate > 0 after active annual BA mask; AOI-only)'));
legend.add(makeLegendRow('777777', 'BurnDate diagnostic (after active annual BA mask; AOI-only)'));

legend.add(ui.Label('Active excluded-mask diagnostic (annual MCD12Q1-based)', {
  fontWeight: 'bold',
  fontSize: '11px',
  margin: '10px 0 4px 0'
}));
var legendActiveMaskLabel = ui.Label('', {
  fontSize: '11px',
  margin: '0 0 4px 0',
  color: '444'
});
legend.add(legendActiveMaskLabel);
legend.add(makeLegendRow('2b83ba', 'Pixels excluded under the current BA mask mode (baseline or selected sensitivity)'));

legend.add(ui.Label('Land Surface Temperature (MOD11A1)', {
  fontWeight: 'bold',
  fontSize: '11px',
  margin: '10px 0 4px 0'
}));
legend.add(ui.Label('Monthly mean LST (°C); mandatory-QA masked; AOI-only', {
  fontSize: '11px',
  margin: '0 0 2px 0'
}));
legend.add(lstThumb);
legend.add(ui.Panel([
  ui.Label(LST_VIS_MIN_C + '°C', {fontSize: '11px', margin: '0 0 0 0'}),
  ui.Label('', {stretch: 'horizontal'}),
  ui.Label(LST_VIS_MAX_C + '°C', {fontSize: '11px', margin: '0 0 0 0'})
], ui.Panel.Layout.flow('horizontal')));

legend.add(ui.Label('Land Cover (MCD12Q1 LC_Type1)', {
  fontWeight: 'bold',
  fontSize: '11px',
  margin: '10px 0 6px 0'
}));
IGBP.forEach(function(d){
  legend.add(makeLegendRow(d.color, d.value + ' — ' + d.name));
});

Map.add(legend);
legend.style().set('shown', state.showLegend);


// Final startup sequence: sync labels, apply the requested panel view, then draw the map.
// Initialise
updateDynamicLabels();
updateBaseMap();
