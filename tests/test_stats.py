"""Tests for the h2h.stats statistical engine."""

import math

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
