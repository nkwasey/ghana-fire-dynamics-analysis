# Method and interpretation

The project turns reference zones into a reporting hierarchy of whole administrative districts. It has two spatial operations: maximum-area-overlap assignment and district dissolve. These operations answer different questions and their diagnostics remain separate.

## Reference assignment

For district D and reference zone Z, the overlap share is area(D intersection Z) divided by area(D). Areas are calculated after transforming both layers to the configured projected working CRS. Never calculate these areas directly in longitude/latitude degrees. The Ghana configuration uses EPSG:32630. Its planar areas are a consistent study convention, not an assertion of distortion-free or surveyed ground area.

District identifiers are read from a configured field or derived deterministically from names. Generated district IDs use title-case tokens joined by underscores; generated zone IDs use lower-case tokens joined by underscores. Explicit source ID fields are preferable when maintaining an existing database. Duplicate district identifiers and unsafe or inconsistent zone identifiers are rejected. Multiple polygon records with the same zone identity are combined before overlap calculation.

The zone with the largest positive overlap share is selected. Shares within `tie_tolerance` of that maximum are treated as tied and resolved by zone ID and zone name in lexicographic order. Tie information is retained. This can select a slightly smaller share; an unusually large tolerance can materially change membership. Low-share warnings use the actual selected share, and the assignment margin is selected share minus the largest competing share. A district with no positive-area overlap is unassigned and the run fails. Touching a boundary alone is not a positive-area overlap. There is no nearest-zone fallback.

A winning share below one is not inherently an error: districts can cross reference-zone boundaries. The overlap evidence records ambiguity and reference coverage. Warning thresholds identify cases for scientific review; they do not turn a classification heuristic into independently validated climatic truth. Reference-zone gaps and overlaps must be interpreted from diagnostics, not hidden by renormalizing the shares.

The pairing CSV is generated from the reference input for each run. The calculation does not treat an unrelated saved pairing as the source of truth. Stable inputs, configuration and implementation are needed to reproduce membership.

## Whole-district reporting geometry

After assignment, the complete original district polygon is retained. It is not clipped to its selected reference zone or to the national boundary. There is no silent snapping, buffering, simplification or geometry repair.

Each final reporting zone is the union of its assigned districts. The district boundary export is read back before dissolving so final zones and serialized district coordinates share one representation. The national input is a validation reference, not a clipping mask.

When `crs.analysis` is configured, the exported source-CRS districts are transformed into that projected CRS and serialized as a separate district layer. District overlaps above `qa.area_tolerance_m2` are rejected in both the working CRS and the analysis CRS. Adjacent source districts whose common edge has different vertices can develop overlapping strips during reprojection. The projected district layer is read back before the zones are built, and each parent must equal the union of its serialized projected districts. Reprojection leaves the reference assignment and retained source-CRS boundaries unchanged.

The final zones approximate the supplied reference zones at district level. They should be described as district-based reporting zones. They do not identify exact physical climatic boundaries or demonstrate the independent accuracy of the digitised reference layer.

Reference overlap shares must remain distinct from constructed coverage. A district may overlap its reference zone by 0.65 and still be fully covered by its final reporting zone. The district attribute `ovl_share` and the crosswalk's `dominant_overlap_share` describe reference overlap. Constructed-zone containment is checked separately in QA.

## Areas and validation

The configured area CRS determines reported square kilometres in the unit universe. Input/output CRS, assignment CRS and area method are recorded. A metre-based projected CRS is required, but that condition alone does not establish suitability for a study region or make its areas equal-area or geodesic measurements. Choose the CRS deliberately for each source profile; changing it is a methodological decision. Reprojection can change floating-point coordinates; raw byte equality across different CRS or file encodings is not a geometric-equivalence test.

Validation checks unique identities within each level, positive district area, valid nonempty polygons, whole-district preservation, parent assignment, zone unions, overlaps, national coverage and serialization. Shapefile round trips must retain normalized vertex coordinates exactly, in addition to topological equality. Numerical comparison tolerances are declared in configuration and recorded in QA. They are computational tolerances rather than estimates of positional accuracy.

Exact vector unions do not guarantee exact raster reconciliation under every pixel grid, reducer or boundary inclusion rule. Burned-area exports require separate native-grid and parent/district checks. A successful geography run does not validate active-fire spatial joins, satellite QA, statistical analyses or other analyses.

## Scientific limits

Assignments depend on the chosen reference zones, administrative vintage, CRS/area convention and tie policy. Near ties can change under input or processing changes. Areas and counts should be used at the documented scale and support. The software preserves identifiers and provenance but cannot establish a source dataset's ground accuracy or redistribution rights.
