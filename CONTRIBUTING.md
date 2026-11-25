# Contributing

Use the shared environment in `environment.yml`. It installs the geography, active-fire archive, monthly panels and analysis projects editably. From the repository root, check that those imports resolve to this checkout.

```bash
python tools/qualify_source_checkout.py --origins-only
python -m pytest
```

Keep test fixtures self-contained and production inputs checksum-verified. Changes to acquisition or intake should preserve archive coverage, empty-year handling, source provenance and transactional validation. Changes to analysis should preserve the contracts under `RP1_Project/rp1_analysis/config/` unless the study design explicitly changes.

## Input data

The source includes the original Earth Engine CSVs, study boundary shapefiles and input checksums. See [source geography](docs/SOURCE_GEOGRAPHY.md) for the separately obtained FIRMS reference files. Keep local copies of those reference files, generated data, credentials, run outputs and executed notebooks out of Git.

## Source qualification

Use an external evidence directory. The qualifier checks import origins, tests, the offline Earth Engine suite, independently specified method fixtures and the installed wheel interfaces.

```bash
python tools/qualify_environment.py --source-only --evidence-dir /path/to/qualification-evidence
```

Source qualification covers the code and available test inputs. The real notebook and SaTScan runs have their own [execution evidence](docs/EXECUTION_EVIDENCE.md) and output validation.
