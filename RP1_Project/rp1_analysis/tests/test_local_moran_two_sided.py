import numpy as np
import pytest
from rp1_analysis_v1.spatial_stats import (
    QueenWeights,
    SpatialStatsError,
    _conditional_without_replacement_means,
    local_moran_smaller_tail_plus_one,
    local_morans_i,
)


def two(values, obs):
    return local_moran_smaller_tail_plus_one(values, obs, upper_tail_comparison='greater_than_or_equal', tie_allocation='both_tails', multiply_smaller_tail_by_two=True)

@pytest.mark.parametrize('sample,observed,expected', [
    ([1,2,3,4,5], 5, 4/6),
    ([1,2,3,4,5], 6, 2/6),
    ([1,2,3,4,5], 0, 2/6),
    ([0,0,0,0], 0, 1),
    ([0,1,1,2], 1, 1),
    ([1,2,3,4,5], 3, 1),
])
def test_inclusive_two_sided(sample, observed, expected):
    assert two(sample, observed) == pytest.approx(expected)
    assert two([-v for v in sample], -observed) == pytest.approx(expected)


def test_invalid_and_inconsistent_settings_rejected():
    with pytest.raises(SpatialStatsError):
        two([], 0)
    with pytest.raises(SpatialStatsError):
        two([np.nan], 0)
    with pytest.raises(SpatialStatsError):
        local_moran_smaller_tail_plus_one([1,2], 1, upper_tail_comparison='greater_than', tie_allocation='both_tails', multiply_smaller_tail_by_two=True)


def test_local_moran_full_pool_draws_preserve_exact_ties():
    ids = tuple("abcde")
    weights = QueenWeights(
        ids, {unit_id: tuple(other for other in ids if other != unit_id) for unit_id in ids},
        (), "row_standardised", "exclude_from_statistic",
    )
    result = local_morans_i(
        [1, 2, 5, 29, 45], weights, permutations=99, random_seed=123, alpha=0.05,
        family_name="complete", upper_tail_comparison="greater_than_or_equal",
        tie_allocation="both_tails", multiply_smaller_tail_by_two=True,
    )
    np.testing.assert_array_equal(result["permutation_p"], np.ones(len(ids)))
    np.testing.assert_array_equal(result["bh_q"], np.ones(len(ids)))


def test_near_complete_local_moran_samples_do_not_use_duplicate_rejection():
    values = np.arange(20, dtype=float)

    class DenseRng:
        def choice(self, population, sample_size, *, replace):
            assert (population, sample_size, replace) == (20, 19, False)
            return np.arange(19, 0, -1)

    means = _conditional_without_replacement_means(values, sample_size=19, draws=4, rng=DenseRng())
    np.testing.assert_array_equal(means, np.full(4, values[1:].mean()))


def test_stale_publication_sources_are_rejected(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    from rp1_analysis_v1 import publication_sources
    from rp1_analysis_v1.paths import ProjectPaths
    root = tmp_path
    source = root / "data/authorities/publication"
    source.mkdir(parents=True)
    (source / "SOURCE_MANIFEST.json").write_text(json.dumps({"configuration_sha256":"old", "sources":{}}))
    monkeypatch.setattr(publication_sources, "load_configuration_bundle", lambda _: SimpleNamespace(configuration_sha256="current"))
    with pytest.raises(publication_sources.PublicationSourceError, match='do not match the current configuration'):
        publication_sources.load_publication_authorities(paths=ProjectPaths(root))
