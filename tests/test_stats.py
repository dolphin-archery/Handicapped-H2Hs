"""Tests for the h2h.stats statistical engine."""

import math
import random

import pytest
from archeryutils import handicaps as hc
from archeryutils import load_rounds

from h2h import stats

_AGB_SCHEME = hc.handicap_scheme("AGB")
_PORTSMOUTH_TARGET = load_rounds.AGB_indoor.portsmouth.passes[0].target
_WA18_TARGET = load_rounds.WA_indoor.wa18.passes[0].target
_TARGETS = [_PORTSMOUTH_TARGET, _WA18_TARGET]
_HANDICAPS = [0, 10, 25, 50, 80]


@pytest.mark.parametrize("target", _TARGETS)
@pytest.mark.parametrize("handicap", _HANDICAPS)
def test_per_arrow_pmf_sums_to_one(target, handicap):
    """The per-arrow PMF must be a valid probability distribution."""
    pmf = stats.per_arrow_pmf(handicap, target)
    assert math.isclose(sum(pmf.values()), 1.0, abs_tol=1e-9)


@pytest.mark.parametrize("target", _TARGETS)
@pytest.mark.parametrize("handicap", _HANDICAPS)
def test_per_arrow_pmf_matches_archeryutils_mean(target, handicap):
    """The PMF's expectation must match archeryutils's own expected arrow score."""
    pmf = stats.per_arrow_pmf(handicap, target)
    expected = sum(score * prob for score, prob in pmf.items())
    reference = float(_AGB_SCHEME.arrow_score(handicap, target))
    assert math.isclose(expected, reference, abs_tol=1e-6)


@pytest.mark.parametrize("target", _TARGETS)
@pytest.mark.parametrize("handicap", _HANDICAPS)
def test_per_arrow_pmf_nonnegative(target, handicap):
    """No probability in the PMF may be negative."""
    pmf = stats.per_arrow_pmf(handicap, target)
    assert all(p >= 0.0 for p in pmf.values())


@pytest.mark.parametrize("n_pass", [1, 6, 12, 60])
@pytest.mark.parametrize("handicap", _HANDICAPS)
def test_n_pass_distribution_sums_to_one(handicap, n_pass):
    """The n_pass score distribution must be a valid probability distribution."""
    pmf = stats.per_arrow_pmf(handicap, _PORTSMOUTH_TARGET)
    dist = stats.n_pass_score_distribution(pmf, n_pass)
    assert math.isclose(sum(dist.values()), 1.0, abs_tol=1e-6)


@pytest.mark.parametrize("n_pass", [1, 6, 12, 60])
@pytest.mark.parametrize("handicap", _HANDICAPS)
def test_n_pass_distribution_mean_scales_linearly(handicap, n_pass):
    """The n_pass distribution's mean must equal n_pass times the per-arrow mean."""
    pmf = stats.per_arrow_pmf(handicap, _PORTSMOUTH_TARGET)
    dist = stats.n_pass_score_distribution(pmf, n_pass)
    mean_n_pass = sum(score * prob for score, prob in dist.items())
    reference = n_pass * float(_AGB_SCHEME.arrow_score(handicap, _PORTSMOUTH_TARGET))
    assert math.isclose(mean_n_pass, reference, abs_tol=1e-6)


@pytest.mark.parametrize("handicap", _HANDICAPS)
def test_n_pass_distribution_identity_for_single_arrow(handicap):
    """n_pass=1 must reproduce the input per-arrow PMF exactly."""
    pmf = stats.per_arrow_pmf(handicap, _PORTSMOUTH_TARGET)
    dist = stats.n_pass_score_distribution(pmf, 1)
    assert dist == pytest.approx(pmf, abs=1e-12)


def test_n_pass_distribution_rejects_non_positive_n_pass():
    """n_pass must be a positive integer."""
    pmf = stats.per_arrow_pmf(10, _PORTSMOUTH_TARGET)
    with pytest.raises(ValueError):
        stats.n_pass_score_distribution(pmf, 0)


@pytest.fixture
def dist_h25():
    """n_pass=12 score distribution for a handicap-25 archer on Portsmouth."""
    pmf = stats.per_arrow_pmf(25, _PORTSMOUTH_TARGET)
    return stats.n_pass_score_distribution(pmf, 12)


def test_percentile_is_in_unit_interval(dist_h25):
    """Percentiles must always lie in [0, 1]."""
    for score in dist_h25:
        p = stats.percentile(dist_h25, score)
        assert 0.0 <= p <= 1.0


def test_percentile_extremes(dist_h25):
    """The worst achievable score has a near-zero percentile, the best near one."""
    min_score = min(dist_h25)
    max_score = max(dist_h25)
    assert stats.percentile(dist_h25, min_score) == pytest.approx(
        dist_h25[min_score], abs=1e-9
    )
    assert stats.percentile(dist_h25, max_score) == pytest.approx(1.0, abs=1e-9)


def test_decide_pass_winner_picks_higher_percentile():
    """A clearly higher percentile wins regardless of raw score."""
    assert stats.decide_pass_winner(0.9, 100, 0.1, 200) == "a"
    assert stats.decide_pass_winner(0.1, 200, 0.9, 100) == "b"


def test_decide_pass_winner_tie_breaks_on_raw_score():
    """Equal percentiles fall back to comparing raw scores."""
    assert stats.decide_pass_winner(0.5, 110, 0.5, 100) == "a"
    assert stats.decide_pass_winner(0.5, 100, 0.5, 110) == "b"


def test_decide_pass_winner_full_tie_is_a_genuine_coin_flip():
    """Equal percentile and equal score must still resolve, via a fair coin flip."""
    outcomes = {
        stats.decide_pass_winner(0.5, 100, 0.5, 100, rng=random.Random(seed))
        for seed in range(50)
    }
    assert outcomes == {"a", "b"}
