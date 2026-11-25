# Reference Method Validation

Reference fixtures under `tests/reference_methods/` are test-only qualification assets. They validate implemented numerical capabilities without owning the Ghana study design and must not import the production function under test as their reference calculation.

## Active qualified families

| Family | Independent basis | Acceptance |
|---|---|---|
| Sen slope | hand-verifiable pairwise-slope definition | effect estimate agreement |
| Benjamini-Hochberg | independent ordered step-up calculation | adjusted p-values agree |
| Gini coefficient | pairwise absolute-difference definition | coefficient agrees |
| Circular statistics | independent unit-circle vector calculation | mean direction/resultant agree |
| Queen contiguity | hand-verifiable polygon fixture | exact neighbour/island identity agrees |
| Global Moran's I | independent matrix/permutation calculation | statistic, expectation and pseudo-p agree |
| Local Moran's I | independent direct-loop conditional-permutation calculation | statistic and adopted study-design pseudo-p convention agree within declared Monte Carlo tolerance |
| Firth-type PGEE coefficients | independent bias-reduced logistic reference under working independence | finite coefficient parity |
| Morel–Bokossa–Neerchal covariance | independent formula transcription | covariance/factors agree |
| SaTScan interface/parser | fixed synthetic parameter/result fixtures | model semantics, parser and provenance checks agree |

The Romano–Tirlea RQ2 inferential method is implemented with a separate test-only mathematical reference that does not import production inference code. The global reference framework formulates the null as strict stationarity and its stated theoretical validity conditions include absolute regularity, no ties/continuous marginal distribution, summable beta-mixing coefficients, positive long-run variance and an asymptotically admissible bandwidth sequence. Tie admissibility is checked against the realised annual inputs during each analysis run.

The independent helper uses exact rank arithmetic for the two-sided tail comparison so mathematical equality under `abs(T_perm) >= abs(T_obs)` is counted as extreme without relying on separately rounded square roots. Qualification covers the right-continuous ECDF, long-run variance, the configured finite-sample bandwidth and variance floor, per-permutation studentisation, plus-one Monte Carlo construction, deterministic seeded permutations, synthetic boundary cases and the configured five-member BH family. Generated annual series can additionally be compared with the independent helper without pinning their results to a stored research run. These tests verify the configured implementation; they do not convert project-defined finite-sample choices into theorem-defined parameters.

Tied realised input is outside the strict reference-qualified inferential route and fails closed under the configured production admissibility rule. Generic MK pairwise code may correctly assign zero to an equal pair; that local kernel convention must not be described as theoretical qualification of tied time-series inference. The project does not claim a tied-data Romano–Tirlea extension without a separate authority.

## External SaTScan boundary

Python validates deterministic inputs, parameter serialisation, parsing and recorded file identities. The optional integration contract distinguishes absence (`EXTERNAL_RESULTS_REQUIRED`) from two-family validation (`RESULTS_VALIDATED`) and fails closed on partial or invalid material. These checks do not independently establish that external result files were produced by the recorded executable and inputs. Qualified executable identity and external execution evidence must be reviewed separately before cluster claims are accepted. Self-contained synthetic result fixtures test this state machine; they are not scientific Ghana results. Genuine accepted results generate run-local T3/F6/S6 sources and never mutate repository authority files.

## Qualification command

```bash
python scripts/qualify_reference_methods.py --json-out out/reference_method_qualification.json
```

The command qualifies the implemented reference families and reports external-engine requirements explicitly when they cannot be executed in the current environment.

Local Moran uses the adopted inclusive doubled-smaller-tail study convention. Its registry status is `study_design_defined_implementation_reference_verified`: a separate direct-loop reference checks numerical conformity, while direct tests exercise inclusive tails, tie cases, plus-one correction and the cap at one. The reference is test-only software, not a new geographic dataset or an alternative study authority. This status does not claim independent empirical validation of the Ghana inputs or spatial exchangeability. See `Local_Moran_Two_Sided.md` for the exact formula and evidence mapping. The external SaTScan engine remains subject to separate execution and result validation.

The external SaTScan engine is executed locally and qualified separately from parser and numerical reference tests.
