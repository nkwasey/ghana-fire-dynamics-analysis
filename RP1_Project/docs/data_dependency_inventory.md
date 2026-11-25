# Data dependencies

| Consumer | Required input | Producer |
| --- | --- | --- |
| Geography | District, reference-zone and national-reference shapefiles | Supplied source bundles |
| Active-fire preparation | Raw MODIS/VIIRS detections, unit universe and boundaries | Supplied FIRMS bundles and selected geography run |
| Merger | Verified AF exports and admitted annual c3 bundle for both domains | AF preparation, pinned c3 GEE exports and actual-consumer c3 admission |
| Analysis | Full-scope panels, mandatory 69-field c3 evidence/provenance, geography and crosswalk | Selected merger and geography runs |
| Publication | Statistical sources, validated external scan results and run metadata | Analysis and local SaTScan execution |

Output directories and analysis input staging directories are created by the workflow. A missing dependency is an error; no bundled computed authority is used as a fallback. See the root README and configuration for exact run paths.
