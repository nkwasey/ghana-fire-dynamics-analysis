"""Ghana Fire RP1 Analysis package."""

import importlib.metadata
from pathlib import Path
import tomllib

from .config import (
    SCHEMA_VERSION,
    ConfigurationBundle,
    EXECUTION_CONTRACT_FILENAME,
    QUALIFICATION_CONTRACT_FILENAME,
    load_configuration_bundle,
    load_execution_contract,
    load_qualification_contract,
)
from .data_io import DataAuthorities, load_data_authorities

from .source_projection import (
    ExcludedArtifact,
    ProjectionResult,
    QualificationProjectionError,
    SourceInventory,
    SourceInventoryEntry,
    inventory_governed_source,
    probe_projected_imports,
    project_governed_source,
    remove_generated_artifacts_from_projection,
    projected_import_environment,
    projected_source_roots,
    verify_projected_inventory,
    write_projection_evidence,
)
from .execution_contract import (
    ExecutionContractError,
    required_artifact_filenames,
    resolve_execution_mode,
    validate_execution_record,
    validate_required_artifact_presence,
    validate_secondary_completion_state,
)
from .inequality import gini_coefficient
from .inference import (
    SenSlopeResult,
    StudentizedGlobalMannKendallPermutationResult,
    benjamini_hochberg,
    sen_slope_point_estimate,
    sens_slope,
    studentized_global_mann_kendall_permutation,
)
from .observability import (
    PredictorDiagnostics,
    RQ3Tables,
    build_paired_overlap_panel,
    build_rq3_tables,
    classify_observation_states,
)
from .gee import GEEDesignError, GEEMeanModelDesign, build_gee_mean_model_design, build_gee_population
from .paths import ProjectPaths, discover_subproject_root
from .integration import (
    CanonicalIntegrationResult,
    InteractiveFinalisationResult,
    finalise_interactive_run,
    build_publication_run_isolated,
    build_secondary_input_run_isolated,
    validate_canonical_integration,
    validate_governed_inputs,
)
from .publication import PublicationRun, build_publication_run
from .seasonality import CircularStatisticsResult, SeasonalitySummary, circular_mean_resultant, summarise_seasonality
from .satscan_integration import (
    OptionalSaTScanIntegrationError,
    OptionalSaTScanIntegrationResult,
    validate_and_integrate_satscan_results_if_available,
)
from .secondary_clusters import (
    EXTERNAL_RESULTS_REQUIRED,
    INPUTS_READY,
    RESULTS_VALIDATED,
    SecondaryInputRun,
    build_secondary_input_run,
    load_scan_scenarios,
)
from .spatial_scale import RQ1Tables, build_rq1_tables
from .spatial_stats import (
    GlobalMoranResult,
    QueenWeights,
    global_morans_i,
    queen_contiguity_weights,
)
from .temporal import YearMonth, parse_yyyymm
from .validation import DataContractSummary, validate_data_authorities

def _package_version() -> str:
    source_pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    if source_pyproject.is_file():
        with source_pyproject.open("rb") as handle:
            raw = tomllib.load(handle)
        return str(raw["project"]["version"])
    return importlib.metadata.version("rp1-analysis-v1")


__version__ = _package_version()

__all__ = [
    "SCHEMA_VERSION",
    "ConfigurationBundle",
    "EXECUTION_CONTRACT_FILENAME",
    "QUALIFICATION_CONTRACT_FILENAME",
    "ExecutionContractError",
    "DataAuthorities",
    "DataContractSummary",
    "CircularStatisticsResult",
    "CanonicalIntegrationResult",
    "InteractiveFinalisationResult",
    "GlobalMoranResult",
    "QueenWeights",
    "GEEDesignError",
    "GEEMeanModelDesign",
    "build_gee_mean_model_design",
    "build_gee_population",
    "ProjectPaths",
    "PublicationRun",
    "PredictorDiagnostics",
    "RQ3Tables",
    "RQ1Tables",
    "SenSlopeResult",
    "StudentizedGlobalMannKendallPermutationResult",
    "SeasonalitySummary",
    "YearMonth",
    "build_rq1_tables",
    "build_publication_run",
    "build_publication_run_isolated",
    "benjamini_hochberg",
    "gini_coefficient",
    "circular_mean_resultant",
    "discover_subproject_root",
    "global_morans_i",
    "load_configuration_bundle",
    "load_execution_contract",
    "load_qualification_contract",
    "load_data_authorities",
    "parse_yyyymm",
    "queen_contiguity_weights",
    "build_paired_overlap_panel",
    "build_rq3_tables",
    "classify_observation_states",
    "sen_slope_point_estimate",
    "sens_slope",
    "studentized_global_mann_kendall_permutation",
    "summarise_seasonality",
    "validate_data_authorities",
    "validate_canonical_integration",
    "validate_governed_inputs",
    "finalise_interactive_run",
    "required_artifact_filenames",
    "resolve_execution_mode",
    "validate_execution_record",
    "validate_required_artifact_presence",
    "validate_secondary_completion_state",
    "ExcludedArtifact",
    "ProjectionResult",
    "QualificationProjectionError",
    "SourceInventory",
    "SourceInventoryEntry",
    "inventory_governed_source",
    "probe_projected_imports",
    "project_governed_source",
    "remove_generated_artifacts_from_projection",
    "projected_import_environment",
    "projected_source_roots",
    "verify_projected_inventory",
    "write_projection_evidence",
    "INPUTS_READY",
    "EXTERNAL_RESULTS_REQUIRED",
    "RESULTS_VALIDATED",
    "SecondaryInputRun",
    "build_secondary_input_run",
    "build_secondary_input_run_isolated",
    "load_scan_scenarios",
    "OptionalSaTScanIntegrationError",
    "OptionalSaTScanIntegrationResult",
    "validate_and_integrate_satscan_results_if_available",
]
