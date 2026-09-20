# RP1 Analysis v1.2.3 implementation/governance addendum

**Scope:** runtime input admission, provenance and execution-record semantics only.  
**Software release:** RP1 Analysis v1.2.3.  
**Historical scientific authority retained:** `RP1_Scientific_Analysis_Methods_and_Implementation_Protocol_2026-08-25.pdf` (RP1 Analysis v1.1.0, dated 25 August 2026).

## Purpose

The dated protocol is not rewritten by v1.2.3. It remains the historical authority for the scientific design. This addendum documents a software-governance correction: the implementation now distinguishes exact identity with the canonical release bytes from scientific admissibility of the current inputs. It does not claim that the 25 August 2026 protocol originally expressed this distinction in the present terms.

## Corrected runtime contract

Ordinary analysis is admitted only when `input_validation_status=PASS`. Current files are loaded and checked against the complete governed schema, support, structural-missingness, fixed-denominator, geometry, relationship, district-to-ACZ reconciliation and analytical-population requirements. Missing/unreadable required files and malformed authorities fail closed.

`canonical_input_identity` is a separate provenance classification:

- `MATCH` — all current governed file hashes and sizes equal the immutable release inventory in `data/input_sha256.json`;
- `DIFFERENT` — at least one current governed byte identity differs.

A `DIFFERENT` result is not, by itself, scientific invalidity. A reconstructed/replacement input can proceed only if its complete scientific/data validation passes. The files shipped as the canonical release must still satisfy `PASS + MATCH`, and `data/input_sha256.json` must not be rewritten to rebase canonical identity onto a candidate reconstruction.

## Run provenance

Every run continues to calculate and record the SHA-256 and size of the files actually analysed. Run provenance therefore answers two independent questions: (1) what exact bytes were analysed, and (2) did those bytes equal the release inputs? Active v1.2.3 completion records use `rp1-notebook-execution-v3`; controlled `nbclient` and direct-Jupyter modes share the same `PASS` admission semantics and both allow canonical identity `MATCH` or `DIFFERENT`.

## Scientific invariance

This correction does **not** change the research questions, estimands, analytical populations, study periods, MCD64A1/VIIRS product semantics, RQ1 support/heterogeneity/seasonality/Moran methods, RQ2 Sen-slope or Romano–Tirlea permutation settings, RQ3 predictors/model/covariance/inference, SaTScan models or scan parameters. Any future scientific correction requires its own governed change rather than being folded into this implementation addendum.
