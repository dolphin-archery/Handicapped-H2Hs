"""Chart data for the match page's interactive distribution graph.

Builds a JSON-serialisable payload consumed by the client-side Chart.js
rendering in `h2h/static/match_chart.js`: each archer's score-distribution
curve (trimmed to a sensible range, per Specification/feedback.md), plus
every scored pass's raw scores, so the browser can toggle which passes'
markers are shown without a server round-trip. Kept independent of Flask so
it can be tested in isolation.
"""

from __future__ import annotations

import math

from .models import Match

# How many standard deviations either side of the mean to display by
# default; trims the "full score range" per Specification/feedback.md.
_DISPLAY_STD_SPAN = 4.0

# Minimum x-axis width to show, so a near-zero-variance distribution (very
# low or very high handicap) doesn't render as a single spike with no
# visible context either side.
_MIN_DISPLAY_WIDTH = 10


def _mean_and_std(distribution: dict[float, float]) -> tuple[float, float]:
    """Mean and standard deviation of a discrete score distribution."""
    mean = sum(score * prob for score, prob in distribution.items())
    variance = sum(prob * (score - mean) ** 2 for score, prob in distribution.items())
    return mean, math.sqrt(variance)


def _display_range(
    dist_a: dict[float, float], dist_b: dict[float, float], max_possible: int
) -> tuple[int, int]:
    """Compute a shared, sensible x-axis range covering both distributions.

    Picks a window of at least `_MIN_DISPLAY_WIDTH` (but never wider than
    `max_possible`) centred on the two distributions' combined mean +/-
    `_DISPLAY_STD_SPAN` standard deviations, then shifts (without shrinking)
    that window to fit inside `[0, max_possible]` -- so a distribution whose
    mean sits right at one edge (e.g. a very low handicap, near-certain top
    scores) still gets a full-width window instead of being clipped there.
    """
    mean_a, std_a = _mean_and_std(dist_a)
    mean_b, std_b = _mean_and_std(dist_b)

    raw_min = min(mean_a - _DISPLAY_STD_SPAN * std_a, mean_b - _DISPLAY_STD_SPAN * std_b)
    raw_max = max(mean_a + _DISPLAY_STD_SPAN * std_a, mean_b + _DISPLAY_STD_SPAN * std_b)

    width = min(max(_MIN_DISPLAY_WIDTH, raw_max - raw_min), max_possible)
    center = (raw_min + raw_max) / 2
    x_min = center - width / 2
    x_max = center + width / 2

    if x_min < 0:
        x_max -= x_min
        x_min = 0.0
    if x_max > max_possible:
        x_min -= x_max - max_possible
        x_max = float(max_possible)
    x_min = max(0.0, x_min)

    return math.floor(x_min), math.ceil(x_max)


def build_match_chart_data(match: Match) -> dict:
    """Build the JSON payload for a match's interactive distribution chart.

    Parameters
    ----------
    match : h2h.models.Match
        The match to build chart data for.

    Returns
    -------
    dict
        JSON-serialisable structure: each archer's name/handicap and
        (score, probability) points over a shared, trimmed x-range; the
        y-axis ceiling to use for vertical pass-score markers; and every
        scored pass's raw scores, in order.
    """
    dist_a = match.distribution_for("a")
    dist_b = match.distribution_for("b")
    max_possible = match.n_pass * 10  # kept in sync with MAX_SCORE_PER_ARROW

    x_min, x_max = _display_range(dist_a, dist_b, max_possible)

    def points(dist: dict[float, float]) -> list[dict[str, float]]:
        return [
            {"x": score, "y": prob}
            for score, prob in sorted(dist.items())
            if x_min <= score <= x_max
        ]

    y_max = max(max(dist_a.values()), max(dist_b.values())) * 1.15

    passes = [
        {"index": p.pass_index, "score_a": p.score_a, "score_b": p.score_b}
        for p in match.passes
        if p.is_scored
    ]

    return {
        "archer_a": {"name": match.archer_a.name, "handicap": match.archer_a.handicap},
        "archer_b": {"name": match.archer_b.name, "handicap": match.archer_b.handicap},
        "distribution_a": points(dist_a),
        "distribution_b": points(dist_b),
        "x_min": x_min,
        "x_max": x_max,
        "y_max": y_max,
        "passes": passes,
    }
