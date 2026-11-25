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
