# Local Moran conditional permutation inference

For each eligible non-island district, compute the Local Moran statistic as the district's population-standardised value multiplied by the row-standardised mean of its neighbours. Hold the focal value fixed. In each of B = 9,999 conditional draws, select the required number of neighbour values without replacement from the other eligible non-island districts. Use the configured random seed and order. This is a conditional randomisation reference, not proof that spatial exchangeability holds.

For observed I and simulated I(b), let L count values <= I and U count values >= I. Equality belongs to both tails. The p-value is `min(1, 2 * min((L+1)/(B+1), (U+1)/(B+1)))`. Plus one is applied separately to each tail. This doubled-smaller-tail convention can differ from other two-sided definitions for asymmetric or discrete reference distributions. With 9,999 draws the minimum p is 0.0002. Evaluate the observed neighbour set and each sampled subset in the same district order so reordering a subset cannot break a tie. Ties use exact stored floating-point comparisons. A completely tied distribution gives p=1.

Apply Benjamini–Hochberg over eligible non-island districts at configured alpha. Islands remain without local p/q and are excluded from the family; a constant surface is undefined. Only FDR-supported districts receive HH, LL, HL or LH classes from the signs of the focal value and spatial lag; other eligible districts are NS. Preserve raw p, adjusted q, island and support status.

## Study design and implementation evidence

The configured study uses this inclusive doubled-smaller-tail convention for every eligible district.

`config/method_authorities.yml` records `study_design_defined_implementation_reference_verified`. This means that the implemented statistic and probability construction have been checked against a separate numerical reference for the selected convention. It does not claim empirical validation of the Ghana inputs, spatial exchangeability, or every possible inferential application.

The independent test-only `local_moran_reference` in `tests/reference_methods/reference_implementations.py` computes standardisation, conditional samples and inclusive corrected tails without importing the production calculation. `test_local_moran_reference_fixture_and_production_parity` checks the statistic, deterministic production output and Monte Carlo probability agreement within its declared sampling tolerance. Different valid sampling implementations need not produce identical Monte Carlo streams from the same seed. Direct tail tests additionally cover ties, sign reflection, values outside the simulated range and the cap at one. No external reference dataset or new Earth Engine exercise is required for these implementation checks.

## Output mapping and reuse

- `spatial_statistics_authority` / S3 contains local I, raw p, BH q, class and island information.
- `seasonality_spatial_organisation_source` feeds the Local Moran panel in F3 and its figure-data source.
- S4 in this codebase is the RQ2 temporal robustness table, not the Local Moran table. Manuscript mapping and updates remain deferred; future updates must use verified run-local values.
- Repository publication sources carry a configuration digest. They are rejected if it differs from the current configuration; a matching digest alone does not prove input lineage. Rebuild and verify all dependent sources before rendering. RQ3 method-receipt and BA input gates remain separate.

Retain raw p and q values, classifications, eligible-family identities and district counts with each analysis run. Generate S3 and the relevant F3 panels from that run. Validate RQ2 S4 against its own inputs and method.
