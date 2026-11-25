# Upload annual fire detections to Google Earth Engine

Run `ghana-fire-archive build --run-id study-2024` or `ghana-fire-archive prepare --run-id study-2024`, then `ghana-fire-archive verify --manifest out/runs/study-2024/archive-manifest.json` in the activated `ghana-fire-archive` Conda environment. To export an existing accepted archive without downloading it again, use `ghana-fire-archive export --manifest /path/to/archive-manifest.json --output out/runs/export-view`.

The generated `out/runs/<run-id>/annual/` folder is organised as follows (only acquired source/year combinations are present):

```text
annual/
  MODIS/Ghana_MODIS_SP_2024.zip
  VIIRS/Ghana_VIIRS_SNPP_SP_2024.zip
  NOAA20/Ghana_VIIRS_NOAA20_SP_2024.zip
  NOAA21/Ghana_VIIRS_NOAA21_SP_2024.zip
  metadata/                      Field definitions and source provenance
  annual-index.csv
  annual-export.json
  README.txt
```

Each annual ZIP contains exactly one shapefile family at its root. For example:

```text
Ghana_MODIS_SP_2024.shp
Ghana_MODIS_SP_2024.shx
Ghana_MODIS_SP_2024.dbf
Ghana_MODIS_SP_2024.prj
Ghana_MODIS_SP_2024.cpg
```

All five components have matching stems, with only one period before the extension. Geometry is point data in WGS84 (EPSG:4326); DBF text is UTF-8. No directories, JSON files or other shapefiles are placed inside an individual upload ZIP. Field dictionaries and provenance stay in `annual/metadata/<sensor>/`.

## Upload steps

1. Open the Earth Engine Code Editor with an account and Cloud project enabled for Earth Engine.
2. In **Assets**, choose **NEW**, then **Table upload**, then **Shape files**.
3. Select **one annual ZIP**, for example `MODIS/Ghana_MODIS_SP_2024.zip`. It can be uploaded directly without extracting its components.
4. Choose the destination asset folder and a new asset ID, for example `Ghana_MODIS_SP_2024`.
5. Submit the upload and check the ingestion task in **Tasks**. When it succeeds, the table is available in Assets.

If you used `ghana-fire-archive package`, extract the resulting collection first. It contains the sensor folders and individual annual ZIPs. **Do not upload the collection ZIP as a single table**, because it contains multiple shapefiles.

`annual-index.csv` records each ZIP's hash, feature count, checked dates and `gee_upload_ready` flag. An empty annual dataset remains explicitly recorded with `gee_upload_ready=False`; do not submit it as an asset. An unavailable period has no annual partition and is reported separately in `annual-export.json`.

The project checks the local ZIP structure, point geometry and coordinates, feature count, complete DBF schema and all 19 attributes against the canonical data, CRS and encoding. Annual ZIP component bytes must match their accepted scientific artifacts. QA flags remain in separate `qa/` CSVs, joined through canonical `id` or shapefile `obs_id`, so flag generation does not alter an upload ZIP. Actual asset ingestion also depends on your Earth Engine account, project permissions and quotas. The project does not log in to Earth Engine, upload assets or confirm remote ingestion.

## Use the uploaded table

Replace the example asset path with the asset ID shown in your Assets panel:

```javascript
var fires = ee.FeatureCollection('projects/your-project/assets/Ghana_MODIS_SP_2024');
Map.addLayer(fires, {color: 'ff5b24'}, 'MODIS SP detections, 2024');
Map.centerObject(fires);
print('Detection count', fires.size());
```

`acq_date` and `time_utc` are UTC strings, not an automatically populated `system:time_start` property. `frp_mw` is numeric. See the matching `_fields.json` dictionary for all abbreviated DBF names. Satellite detections are observations, not unique fire incidents or burned-area polygons. Distinct platforms/overpasses and valid confidence classes remain represented; apply your research filters explicitly.

Official requirements: [Google Earth Engine — Importing Table Data](https://developers.google.com/earth-engine/guides/table_upload).
