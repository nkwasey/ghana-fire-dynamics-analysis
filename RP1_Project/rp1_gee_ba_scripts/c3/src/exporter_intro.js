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
