# Configuration

The YAML configuration is passed with `--config`. Paths in `inputs` and `outputs.root` are resolved against `project_root`; that root is resolved relative to the configuration file. The supplied configs use `project_root: '..'`, so their root is the project containing the `configs` directory. They have no machine-specific paths.

| Setting | Meaning |
|---|---|
| `inputs.districts.path` | Administrative Polygon/MultiPolygon dataset; shapefile and GeoPackage inputs are supported through GeoPandas |
| `inputs.<role>.layer` | Optional exact layer name for districts, zones or national reference; required when a source contains more than one layer |
| `inputs.districts.name_field` | Required source district label |
| `inputs.districts.id_field` | Optional canonical ID field; otherwise derive IDs from labels |
| `inputs.districts.code_field` | Optional district code metadata; otherwise blank |
| `inputs.zones.path` | Reference zonal polygon layer |
| `inputs.zones.name_field` | Required source zone label |
| `inputs.zones.id_field` | Optional canonical ID; otherwise derive from labels |
| `inputs.zones.code_field` | Optional zone code field |
| `inputs.zones.code_mapping` | Zone-name to code mapping, used when no code field is selected |
| `inputs.national.path` | Optional national polygon reference for union comparison |
| `crs.working` | Projected metre-based CRS for overlap assignment and geometric area diagnostics |
| `crs.area` | Projected metre-based CRS for reported unit areas |
| `crs.output` | Must equal district source CRS; district coordinates are preserved |
| `crs.analysis` | Optional projected metre-based CRS for the additional analysis boundary handoff; omit it to skip those layers |
| `assignment.tie_tolerance` | Dimensionless tolerance for shares considered tied; finite value in [0,1] |
| `assignment.warning_share` | Winning shares below this produce warnings; not an accuracy threshold |
| `assignment.warning_margin` | Margins below this produce warnings when competing zones exist |
| `qa.area_tolerance_m2` | Numerical area tolerance for overlap/coverage diagnostics in square metres |
| `outputs.root` | Output directory; every run receives its own subdirectory |
| `outputs.splits` | Produce per-zone shapefile/GeoJSON/attribute bundles and district-list CSVs |
| `outputs.plots` | Produce combined overview and numbered per-zone PNG/PDF maps with district-name keys and placement inventories |
| `expected.districts`, `expected.zones` | Optional study-specific count checks; zone count means zones receiving districts |

Only the settings listed here and `project_root` are accepted. Unknown settings and duplicate YAML keys are errors. Use YAML booleans `true` and `false` without quotes for output switches, numeric values for tolerances and warning thresholds, and positive integers for expected counts. Null sections and quoted numeric values are not substitutes for these types. The optional `clip_to_aoi: false` setting can state the whole-district policy explicitly; `true` is rejected.

Single-layer inputs can omit `layer`; their resolved layer names are still recorded in provenance. Multilayer sources require an explicit layer name, preventing accidental selection of the first layer. Identifiers within a role must not differ only in letter case. Zone IDs must also avoid Windows reserved basenames such as `CON`, `NUL` and `COM1`, since they become output filenames. Repeated records with exactly the same zone ID and consistent metadata are combined normally.

Both supplied profiles use EPSG:32630 for overlap and area calculations and preserve EPSG:4326 district coordinates in the `boundaries/` shapefiles. The climatic profile also sets `crs.analysis: EPSG:32630` to create a separate projected handoff under `analysis_boundaries/`, and checks 260 districts and five assigned zones. The ecological profile uses the supplied `CAPTION` field and its own zone definitions; it must not be interpreted as the same five-zone system. Set `crs.analysis` explicitly for a projected derivative of another profile when required.

The supplied warning settings (share 0.5, margin 0.05) are review aids. They are not universal scientific acceptance thresholds. The area tolerance (0.0001 m²) is a strict numerical diagnostic convention, not boundary positional accuracy. The same positive-area geometry can produce a warning even when its practical area is tiny.

Keep `tie_tolerance` small when it represents numerical equality. Any candidate within this absolute share difference from the maximum can win the deterministic lexical tie-break; large values can therefore change membership substantially. Low-overlap warnings evaluate the selected candidate, not another candidate's larger share.

A reference zone receiving no districts is reported as unused and is not emitted as an empty reporting-zone polygon. Examine this condition when using small zones or a district system too coarse to represent them.

Use explicit field mappings and versioned source data for reproducible identities. Changing names when IDs are derived can change keys. Retain the generated assignment CSV and complete provenance with each output run. Update downstream paths deliberately when selecting a new run; the program does not choose the newest directory automatically.

The CLI run ID is a single directory name beginning with a letter or digit and containing only letters, digits, underscores, hyphens and periods. It must not end in a period or use a reserved device basename, including a basename followed by an extension. Existing run directories are never overwritten. Use distinct portable IDs such as `local_acz_01`.

All runs include EPSG:4326 GeoJSON counterparts, independent of the shapefile output CRS or the plot switch. District transformations must therefore yield valid, finite geographic coordinates even when plots are disabled. A successful transformation is a computational check; it does not independently establish that the input CRS was assigned correctly.
