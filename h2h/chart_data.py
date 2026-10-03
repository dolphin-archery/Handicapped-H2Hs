"""Chart data for the interactive distribution graph on match and pair pages.

Builds a JSON-serialisable payload consumed by the client-side Chart.js
rendering in `h2h/static/match_chart.js`: each archer's score-distribution
curve (trimmed to a sensible range, per Specification/feedback.md), plus every
score each of the two archers has shot so far (against any opponent), so the
browser can toggle which passes' markers are shown without a server round-trip.
The x-range always covers every one of those scores. Kept independent of Flask
so it can be tested in isolation.
"""

from __future__ import annotations

import math

from .models import Event

# How many standard deviations either side of the mean to display by
# default; trims the "full score range" per Specification/feedback.md.
_DISPLAY_STD_SPAN = 4.0

# Minimum x-axis width to show, so a near-zero-variance distribution (very
# low or very high handicap) doesn't render as a single spike with no
# visible context either side.
_MIN_DISPLAY_WIDTH = 10

# Room left beside the outermost score marker so its line is not on the plot's edge.
_MARKER_MARGIN = 1


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


def _scored_passes(event: Event, archer: int) -> list[dict[str, int]]:
    """Every pass an archer has scored so far, whoever their opponent was.

    Parameters
    ----------
    event : h2h.models.Event
        The event the archer belongs to.
    archer : int
        The archer's index.

    Returns
    -------
    list[dict[str, int]]
        `{"index": rotation index (0-based), "score": score}` per scored pass,
        oldest first. Includes a bye pass shot alone; a pass sat out is absent.
    """
    results = sorted(
        (r for r in event.results if r.archer_index == archer), key=lambda r: r.rotation_index
    )
    return [{"index": r.rotation_index, "score": r.score} for r in results]


def build_pair_chart_data(event: Event, a: int, b: int) -> dict:
    """Build the JSON payload for a pair-of-archers' interactive distribution chart.

    Each archer's distribution comes from their own resolved target
    (`Event.distribution_for`). The marked scores are every score each of the
    two archers has shot so far, against any opponent -- not only passes the
    pair shared -- and the x-range is widened (beyond the curves' trimmed range)
    to include all of them, so no marker is ever outside the plot.

    Parameters
    ----------
    event : h2h.models.Event
        The event both archers belong to.
    a, b : int
        The two archers' indices. They need not have met: a match page charts
        the pair before their first scored pass, in which case each archer's
        `passes` is just whatever they shot in earlier passes against others.

    Returns
    -------
    dict
        JSON-serialisable structure: for each archer a `name` and `passes`
        (`{"index", "score"}` per scored pass);
        each archer's (score, probability) curve points over the shared x-range
        (`x_min` to `x_max`, covering the curves' trimmed range and every
        score in either archer's `passes`, with a margin); the y-axis ceiling
        for the vertical markers; and `current_pass`, the index of the pass
        being scored, whose scores the chart shows by default.
    """
    dist_a = event.distribution_for(a)
    dist_b = event.distribution_for(b)
    max_possible = max(event.max_score_for(a), event.max_score_for(b))

    x_min, x_max = _display_range(dist_a, dist_b, max_possible)

    passes_a = _scored_passes(event, a)
    passes_b = _scored_passes(event, b)
    shot = [p["score"] for p in passes_a + passes_b]
    if shot:
        x_min = max(0, min(x_min, min(shot) - _MARKER_MARGIN))
        x_max = min(max_possible, max(x_max, max(shot) + _MARKER_MARGIN))

    def points(dist: dict[float, float]) -> list[dict[str, float]]:
        # One point per whole score across the final range, zero where the distribution has
        # no probability, so the curve (and its hover tooltip) exists at every score a marker
        # can be at, however far from this archer's usual scores.
        return [{"x": score, "y": dist.get(float(score), 0.0)} for score in range(x_min, x_max + 1)]

    y_max = max(max(dist_a.values()), max(dist_b.values())) * 1.15

    return {
        "archer_a": {"name": event.archers[a].name, "passes": passes_a},
        "archer_b": {"name": event.archers[b].name, "passes": passes_b},
        "distribution_a": points(dist_a),
        "distribution_b": points(dist_b),
        "x_min": x_min,
        "x_max": x_max,
        "y_max": y_max,
        "current_pass": event.current_rotation_index,
    }
