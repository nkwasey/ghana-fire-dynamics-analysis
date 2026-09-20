# `rp1_gee_ba_scripts` structure

`RP1_Project/rp1_gee_ba_scripts/` contains the Earth Engine source and the
burned-area CSV export bundles used for RP1 data reconstruction. It is not a
Python package and is not executed by the canonical analysis notebook.

## Canonical location

```text
ghana-fire-rp1-analysis-main/RP1_Project/rp1_gee_ba_scripts/
```

## Shipped structure

```text
rp1_gee_ba_scripts/
├── 0-rp1_unified_modis_viewer_selectable_ba_mask_c1_viewer_commented.js
├── 1-rp1_zone_monthly_2001-2024_panel_c1_commented.js
├── 1-rp1_zone_monthly_2012-2024_panel_c1_commented.js
├── 2-rp1_district_monthly_2001-2024_panel_c1_commented.js
├── 2-rp1_district_monthly_2012-2024_panel_c1_commented.js
├── RP1_Project_MODIS_BA_c1_2001/   # 25 governed CSV exports
└── RP1_Project_MODIS_BA_c1_2012/   # 25 governed CSV exports
```

The BA-2001 family supports the long-run burned-area workflow. The BA-2012
family supports the MODIS/VIIRS overlap-era workflow. The exported files retain
ACZ and district base/extended products plus district QA summaries as defined
by the Earth Engine scripts.

## Merger roots

```text
RP1_Project/rp1_gee_ba_scripts/RP1_Project_MODIS_BA_c1_2001
RP1_Project/rp1_gee_ba_scripts/RP1_Project_MODIS_BA_c1_2012
```

The AF/BA merger interface can be inspected with:

```bash
python RP1_Project/merge_af_ba_panels.py --help
```

Regenerating the CSV exports requires external Earth Engine execution. The
shipped export bundles are sufficient for repository-based reconstruction and
do not create a network dependency for normal analysis or testing.
