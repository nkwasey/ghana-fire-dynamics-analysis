# Space–time permutation scans

## Purpose and interpretation

The retrospective space–time permutation scan investigates whether observed
active-fire detections concentrate in a location and period compared with
the case-only space–time permutation null. The analysis uses the observed
spatial and temporal case margins to construct expected counts; these are
conditional expected counts, not observations and not exposure-normalized
estimates. The test is sensitive to space–time departures beyond the
spatial and temporal margins; interpretation is conditional on the case data
and model assumptions. Significance is assessed by the configured SaTScan
Monte Carlo procedure, subject to its scan settings and simulation count.

The configured input is the primary VIIRS active-fire detection count by
district and month. The meaning of a zero depends on the admitted source
and active-fire completeness rules. An absent or incomplete source must not
be characterized as a verified zero detection without supporting evidence.
A cluster does not establish causation, observation of every location, a
count of unique fires, or a permanent hotspot.

## Model-specific output

| Quantity | Space–time permutation interpretation |
|---|---|
| Observed | Reported case count inside the cluster |
| Conditional expected | Expected count from the case-only permutation model |
| Observed/expected | Ratio to this conditional expectation |
| Test statistic | The statistic reported by the model |
| P-value | Monte Carlo result with its original reported qualifier |
| Relative risk | Not available as a discrete-Poisson exposure-based RR |
| Exposure-based expected count | Not defined for the case-only model |

The discrete Poisson analysis uses its own population/exposure authority,
expectation, log likelihood ratio and relative-risk fields. Do not substitute
a conditional observed/expected ratio for the Poisson relative risk or
compare the measures as if their denominators and null hypotheses were the
same. No Poisson model for VIIRS should be introduced merely to obtain an RR:
it would require a defensible, separately specified exposure measure.

## Assumptions and limitations

The permutation null accounts for the observed overall spatial and temporal
case margins. It does not automatically adjust for spatially varying changes
in sensor observation opportunity, cloud, detection probability, source
completeness, platform coverage or land characteristics. These factors can
produce changes in the observed distribution and must be assessed before
interpreting a cluster as a change in actual fire occurrence. QA and
uncertainty should accompany results; unsupported time periods should not be
quietly interpreted as observed absence.

The null, unit universe, case construction, confidence filtering, study
window, maximum spatial and temporal windows, reporting hierarchy,
simulation count, seed/engine behavior, multiple-testing interpretation and
external SaTScan inputs must be recorded with each run. Existing fixed
population authorities are associated with their recorded data and cannot
be assumed valid for newly generated AF/BA panels.

## Qualification plan

1. Reconcile the selected AF source, district assignments and completeness,
   including known empty source months. Confirm the active-fire confidence
   population and study interval before creating case files.
2. Prepare the configured case and geometry files and parameter file in a
   new run directory. Check the STP configuration has no exposure input.
3. Execute a qualified SaTScan installation locally. Retain the executable
   identity, input hashes and execution evidence with the output files.
4. Check model and window identities, reported conditional expectation,
   observed/expected, statistic and p-value qualifier, as well as
   cluster/membership consistency. Raw-file integrity checks alone do not
   establish that external output came from the claimed executable and inputs.
5. Generate new run-specific publication tables and maps only after the
   above checks, reconcile their values to the validated result source and
   document the conditional interpretation. Qualify the complete source-to-publication lineage.

The parser and output-contract tests exercise interpretation and validation;
they do not execute SaTScan or establish scientific validity of a new run.
Geography, MODIS QA/band masks, observation coverage, FRP confidence,
Local Moran inference and complete publication-run provenance remain
separate scientific gates.

Publication-run resume checks apply model-specific semantics to T3 and to
cluster records in S6, rejecting incompatible Poisson and permutation values
even if file hashes were refreshed. This is a semantic check, not an
independent proof that an otherwise compatible table was generated from a
particular secondary run. Source-to-publication binding remains a separate
provenance qualification.

## Reference

Kulldorff, M., Heffernan, R., Hartman, J., Assunção, R., & Mostashari, F.
(2005). A space–time permutation scan statistic for disease outbreak
detection. *PLoS Medicine, 2*(3), e59.
https://doi.org/10.1371/journal.pmed.0020059
