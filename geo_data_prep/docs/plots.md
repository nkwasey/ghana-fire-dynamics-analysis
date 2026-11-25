# Numbered district maps

With `outputs.plots: true`, a run produces a combined reporting-zone overview and a numbered district map for every assigned zone. District numbers match an alphabetical number-to-name key and are local to that zone. They are cartographic identifiers, not administrative codes.

## Layout

The Forest and Coastal maps use a large central map above a four-column district-name key. Other zones retain a prominent centred map and use a key sized to their district count and map proportions. The map aspect ratio preserves the geographic shape; the map is not stretched to fill the page.

Numbers are placed within district polygons. Where a small district cannot accommodate a readable number on the main map, a clearly marked detail panel enlarges that area. Read its number inside the corresponding polygon in that panel. Detail frames identify the corresponding extent on the main map. Embedded details use empty map space and are checked not to obscure district geometry; a compact separate panel is used if a safe empty region is unavailable. A frame is not an administrative boundary or a spatial relationship between districts.

Every district occurs exactly once in the name key and number-placement inventory. All district outlines remain visible on the main map. Insets may also show surrounding outlines for context. The software checks rendered number placement against the appropriate district geometry and checks number overlap, key text and page bounds.

PNG files support quick viewing. Vector PDFs preserve legible text and lines when zooming or printing. Dense-zone maps are large-format figures; use the PDF at a suitable zoom rather than judging text at a fit-to-window scale.

The axes identify the plotting coordinate system. Number positions are interior cartographic points, not district capitals or population centres. Names come from the prepared district-name field. Map geometry, parent assignments and analytical area calculations are unaffected by number placement.

## Outputs

Each map in `plots/per_zone/` has a matching PDF, PNG and `<zone_id>_labels.csv` inventory. `plots/district_label_checks.json` records the plot checks. The inventory links each district ID and name to its number, rendering panel, geographic position, font size and placement status. It is separate from the authoritative geometry and assignment crosswalk.

## Generate maps

Run from the project root after installation:

```bash
geo-prep run --config configs/example_acz.yaml --run-id numbered_districts
```

A run ID must not already exist. The ecological configuration produces its own reporting-zone maps and does not redefine the climatic zones. When changing inputs, names or assignments, generate a new complete run so all maps, spatial handoffs and provenance identify the same source data.

Map rendering does not establish independent source accuracy or resolve reference-zone QA warnings.
