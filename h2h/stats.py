"""Statistical engine for handicapped archery H2H matches.

Derives per-arrow and n_pass score distributions directly from the AGB
handicap model implemented by `archeryutils`, per the recommendation in
Testing/idea_evaluation.md: handicap -> sigma_r -> per-arrow score PMF ->
convolved n_pass-arrow distribution -> percentile comparison. No bowstyle-
variance correction is applied (excluded per Specification/humanSpec.md).

Deliberately has no dependency on Flask so it can be developed and tested
in isolation.
"""

from __future__ import annotations

import numpy as np

from archeryutils import handicaps as hc
from archeryutils import targets

_AGB_SCHEME = hc.handicap_scheme("AGB")


def per_arrow_pmf(
    handicap: float,
    target: targets.Target,
    arw_d: float | None = None,
) -> dict[float, float]:
    """Compute the exact per-arrow score probability mass function for a handicap.

    Uses the same isotropic-Gaussian aiming-error model that `archeryutils`
    uses internally to compute expected arrow score (`HandicapScheme._s_bar`),
    but returns the full per-ring probability mass function instead of just
    its expectation.

    Parameters
    ----------
    handicap : float
        AGB (2023 scheme) handicap to compute the distribution for.
    target : archeryutils.targets.Target
        Target face being shot at (defines ring sizes, distance, indoor/outdoor).
    arw_d : float | None, default=None
        Arrow diameter override in [metres]; defaults to the AGB scheme's
        indoor/outdoor default.

    Returns
    -------
    dict[float, float]
        Mapping of achievable arrow score (including 0.0 for a miss) to its
        probability. Probabilities sum to 1.
    """
    if arw_d is None:
        arw_d = _AGB_SCHEME.arw_d_in if target.indoor else _AGB_SCHEME.arw_d_out
    arw_rad = arw_d / 2.0
    sig_r = float(_AGB_SCHEME.sigma_r(handicap, target.distance))

    # Rings ordered smallest-diameter (highest score) to largest (lowest score).
    spec = dict(sorted(target.face_spec.items()))
    ring_diams = list(spec.keys())
    ring_scores = list(spec.values())

    # tail[k] = P(landing radius > ring k's radius), i.e. probability of
    # scoring worse than ring k. Same term used in archeryutils's _s_bar.
    tail = [
        float(np.exp(-((arw_rad + diam / 2.0) / sig_r) ** 2)) for diam in ring_diams
    ]

    pmf: dict[float, float] = {}
    prev_tail = 1.0
    for score, t in zip(ring_scores, tail, strict=True):
        pmf[float(score)] = prev_tail - t
        prev_tail = t
    pmf[0.0] = prev_tail  # miss: landed beyond the outermost ring

    return pmf


def n_pass_score_distribution(pmf: dict[float, float], n_pass: int) -> dict[float, float]:
    """Compute the exact distribution of the summed score over n_pass arrows.

    Uses discrete self-convolution of the per-arrow PMF, which is exact (not
    a Monte Carlo or Gaussian/CLT approximation) and cheap for the small
    per-arrow support sizes and pass lengths used here.

    Parameters
    ----------
    pmf : dict[float, float]
        Per-arrow score PMF, as returned by `per_arrow_pmf`.
    n_pass : int
        Number of arrows summed per pass. Must be a positive integer.

    Returns
    -------
    dict[float, float]
        Mapping of achievable n_pass-arrow total score to its probability.
        Probabilities sum to 1.

    Raises
    ------
    ValueError
        If `n_pass` is not a positive integer.
    """
    if n_pass < 1:
        raise ValueError("n_pass must be a positive integer.")

    max_score = max(pmf)
    dense = np.zeros(int(max_score) + 1)
    for score, prob in pmf.items():
        dense[int(score)] = prob

    total = dense.copy()
    for _ in range(n_pass - 1):
        total = np.convolve(total, dense)

    return {float(i): float(p) for i, p in enumerate(total) if p > 0.0}


def percentile(distribution: dict[float, float], observed_score: float) -> float:
    """Compute an archer's percentile for a score under their own distribution.

    Parameters
    ----------
    distribution : dict[float, float]
        Score distribution, as returned by `n_pass_score_distribution`.
    observed_score : float
        The score actually shot.

    Returns
    -------
    float
        Cumulative probability of scoring at or below `observed_score`
        under `distribution`, in [0, 1].
    """
    return float(sum(p for score, p in distribution.items() if score <= observed_score))
