"""Generic implementation-capability registry for configured method authorities.

Scientific method identity, literature authority, qualification status and the mapping
from a method ID to an implementation ID live exclusively in
``config/method_authorities.yml``.  Python owns only executable capability identities:
whether this codebase actually contains a named implementation.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from .contracts import MethodAuthorityContract, MethodAuthoritySpec


@dataclass(frozen=True, slots=True)
class ImplementationCapability:
    implementation_id: str
    implemented: bool


# These are software capability identifiers, not scientific study selections.  A
# configured method can use a capability only when method_authorities.yml binds the
# method ID to one of these implementation IDs.
_IMPLEMENTATIONS = (
    ImplementationCapability("spatial.within_acz_rate_difference.v1", True),
    ImplementationCapability("summary.median_iqr.v1", True),
    ImplementationCapability("summary.gini_nonnegative.v1", True),
    ImplementationCapability("season.circular_mean_resultant.v1", True),
    ImplementationCapability("spatial.queen_contiguity.v1", True),
    ImplementationCapability("spatial.global_moran_permutation.v1", True),
    ImplementationCapability("spatial.local_moran_conditional.v1", True),
    ImplementationCapability("inference.randomisation_permutation.v1", True),
    ImplementationCapability("trend.sen1968.v1", True),
    ImplementationCapability("trend.romano_tirlea_studentized_global_mk.v1", True),
    ImplementationCapability("multiplicity.bh1995.v1", True),
    ImplementationCapability("gee.firth_penalized_independence.v1", True),
    ImplementationCapability("family.binomial.v1", True),
    ImplementationCapability("link.logit.v1", True),
    ImplementationCapability("gee.working_independence.v1", True),
    ImplementationCapability("covariance.mbn2003.v1", True),
    ImplementationCapability("inference.standard_normal_wald.v1", True),
    ImplementationCapability("transform.log2_positive.v1", True),
    ImplementationCapability("factor.categorical_reference.v1", True),
    ImplementationCapability("diagnostic.vif.v1", True),
    ImplementationCapability("prediction.observed_covariate_standardisation.v1", True),
    ImplementationCapability("scan.discrete_poisson_input_prequalification.v1", True),
    ImplementationCapability("scan.space_time_permutation_input_prequalification.v1", True),
    ImplementationCapability("scan.hierarchical_nonoverlap.v1", True),
    ImplementationCapability("output.dataframe_csv.v1", True),
    ImplementationCapability("output.figure_renderer.v1", True),
    ImplementationCapability("output.json_manifest.v1", True),
)

IMPLEMENTATION_CAPABILITIES: Final[MappingProxyType[str, ImplementationCapability]] = MappingProxyType(
    {item.implementation_id: item for item in _IMPLEMENTATIONS}
)


def registered_implementation_ids() -> frozenset[str]:
    """Return software implementation IDs available to the configuration layer."""

    return frozenset(IMPLEMENTATION_CAPABILITIES)


def require_implementation(implementation_id: str) -> ImplementationCapability:
    """Resolve one software capability or fail closed."""

    try:
        return IMPLEMENTATION_CAPABILITIES[implementation_id]
    except KeyError as exc:
        raise ValueError(f"Unregistered implementation identifier: {implementation_id!r}") from exc


def require_method_authority(
    methods: MethodAuthorityContract, method_id: str
) -> MethodAuthoritySpec:
    """Resolve a method ID only through the injected method-authority contract."""

    for item in methods.authorities:
        if item.method_id == method_id:
            require_implementation(item.implementation_id)
            return item
    raise ValueError(f"Unknown governed method identifier: {method_id!r}")


def method_is_implemented(methods: MethodAuthorityContract, method_id: str) -> bool:
    """Return executable readiness from config binding plus Python capability."""

    authority = require_method_authority(methods, method_id)
    capability = require_implementation(authority.implementation_id)
    configured_as_implemented = authority.status == "implemented"
    if configured_as_implemented != capability.implemented:
        raise ValueError(
            "Configured method status disagrees with software capability for "
            f"{method_id!r}: status={authority.status!r}, "
            f"implementation_id={authority.implementation_id!r}"
        )
    return capability.implemented


OUTPUT_BUILDER_REGISTRY: Final[frozenset[str]] = frozenset(
    {"dataframe_csv", "study_overview_csv", "figure_renderer", "json_manifest"}
)

FIGURE_DATA_BUILDER_REGISTRY: Final[frozenset[str]] = frozenset(
    {
        "eligible_support_map",
        "source_frame",
        "annual_trajectory_join",
        "district_metric_map",
        "cluster_membership_map",
    }
)
FIGURE_RENDERER_REGISTRY: Final[frozenset[str]] = frozenset(
    {
        "support_map",
        "choropleth",
        "coefficient_or_plot",
        "grid_composite",
        "grid_trajectory_with_sen",
        "cluster_maps_grid",
        "cluster_recurrence_maps_grid",
        "grid_district_seasonal_diagnostics",
    }
)

# Presentation-export renderer identities are implementation capability names.
# Their study-specific use, source binding and styling remain configuration-owned.
PRESENTATION_RENDERER_REGISTRY: Final[frozenset[str]] = frozenset(
    {
        "acz_categorical_context_map",
        "support_acz_map",
        "acz_choropleth",
        "district_choropleth",
        "seasonality_lines",
        "local_moran_categorical_map",
        "district_seasonal_heatmap",
        "district_circular_mean_timing",
        "resultant_length_boxplot",
        "single_trajectory_with_sen",
        "grid_trajectory_with_sen",
        "stacked_proportions",
        "coefficient_or_plot",
        "standardised_probability_pairs",
        "cluster_membership_map",
        "cluster_recurrence_map",
    }
)
