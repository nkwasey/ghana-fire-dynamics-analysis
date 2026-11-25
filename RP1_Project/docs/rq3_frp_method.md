# Active-fire confidence and FRP method

## Scientific definition

After common confidence mapping, TYPE filtering and land masking, VIIRS follows two streams. The count stream deduplicates the configured confidence population and supplies detection counts and nominal/high persistence. The FRP stream selects nominal/high records first, deduplicates them independently using the configured key and tie-breaks, and assigns them to the same geographic levels. Finite FRP ranks ahead of nonfinite FRP in this stream; if no finite candidate exists, the configured tie-break selects a nonfinite record, which the metric gate subsequently excludes. MODIS follows its configured preparation and FRP path. The configured global low-confidence option applies to detection counts.

For each spatial unit and UTC day, select the maximum finite FRP among eligible nominal/high records at or above `min_frp_mw`; equality passes. The monthly mean divides the sum of daily maxima by the number of UTC days with eligible FRP, and is missing when there is no such day. The 95th percentile is over the same days. The sum has MW as its numerical unit and is not fire radiative energy. Source preparation currently rejects missing, nonnumeric, and negative FRP under its strict input rules. FRP is an indicator based on sensor detections and can be affected by sampling and observation conditions.

Both primary predictors use nominal/high categories, but their surviving VIIRS records need not match. A recovered nominal/high FRP record can occur where the count stream has zero nominal/high detections. The FRP sum per primary detection is therefore a cross-stream ratio and is undefined for a zero count denominator.

## RQ3 interpretation

The RQ3 analysis uses the VIIRS nominal/high detection count and the mean of eligible unit-day FRP maxima as separate predictors; they summarize different aspects of the detected activity. State the confidence population, UTC day, daily-maximum aggregation, minimum FRP gate, active-day denominator and zero-support missingness in any publication. Do not describe the predictor merely as mean FRP of all pixels, detections, calendar days or total fire energy.

The existing conditional RQ3 population requires a positive count, so an FRP-positive row with a zero count is outside that model population. For included rows, missing required predictors or nonpositive predictors assigned a positive-log transform cause validation to fail; they are not silently imputed. Quantify these cases and changes in model eligibility during a verified rerun.

## Reproducibility and run consequences

Every run generates monthly panels, design matrices, fitted coefficients, uncertainty estimates and publication outputs from the selected inputs. Reuse requires an independently checked input-to-output provenance binding. Regenerate dependent outputs after changing data, confidence eligibility or FRP settings.

The RQ3 guard checks the merger's method claims against the original combine receipt and re-hashes the recorded preparation, geography, source and aggregation evidence under the project workspace. Retain those files with the run; missing or altered evidence prevents RQ3 admission.

1. Verify the Stage 1 geography, input FIRMS data, observation window and canonical source provenance. Regenerate canonical and monthly outputs in an isolated run using the admitted confidence and FRP settings; retain configuration snapshots and QA.
2. Examine low/nominal/high counts and FRP support, including days where the FRP gate excludes a nominal/high detection, and verify daily maxima against selected source records. Preserve counts and missingness as distinct quantities.
3. Generate Stage 3 active-fire exports when AF inputs/settings change, then merge the admitted c3 BA2001 and BA2012 domains, subject to the independent BA grid, QA, missingness and lineage gates. Do not treat successful FRP processing as BA acceptance.
4. Bind new panel hashes to the analysis; regenerate and requalify RQ3 design authorities and refit models; then regenerate all affected tables, figures and manuscript values. Verify inputs, fit diagnostics, outputs and run manifests against the same execution. Do not reuse stale or mismatched artifacts.
5. Review results, limitations and provenance before publication. A passing synthetic test is not a completed national run or a scientific validation.

Review the Local Moran method, burned-area source closure and run provenance independently before scientific use.

Active-fire receipts must establish both streams and independent FRP selection before admission. Rebuild BA-dependent densities, paired populations and models with independently admitted burned-area inputs and evidence. Source scenario zeros, withheld outcomes and restricted evidence sensitivities must retain their distinct interpretations.
