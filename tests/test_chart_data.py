"""Tests for h2h.chart_data (interactive-chart JSON payload builder)."""

from h2h.chart_data import build_match_chart_data
from h2h.models import Archer, Match


def make_match(n_pass=12):
    """A match between two clearly different archers."""
    return Match(Archer(name="Alice", handicap=15), Archer(name="Bob", handicap=55), n_pass)


def test_payload_has_expected_top_level_keys():
    """The chart payload must include everything match_chart.js needs to render."""
    match = make_match()
    data = build_match_chart_data(match)
    assert set(data) == {
        "archer_a",
        "archer_b",
        "distribution_a",
        "distribution_b",
        "x_min",
        "x_max",
        "y_max",
        "passes",
    }


def test_x_range_is_trimmed_not_full_score_range():
    """The x-range should not span the full 0..max_possible score range."""
    match = make_match(n_pass=12)
    data = build_match_chart_data(match)
    max_possible = 12 * 10
    assert data["x_min"] >= 0
    assert data["x_max"] <= max_possible
    # For two archers this different in skill, the trimmed range should be
    # meaningfully narrower than the full range.
    assert (data["x_max"] - data["x_min"]) < max_possible


def test_x_range_has_a_minimum_width():
    """Even a near-zero-variance distribution gets a sensible minimum width."""
    match = Match(Archer(name="Elite", handicap=0), Archer(name="Elite2", handicap=0), n_pass=1)
    data = build_match_chart_data(match)
    assert (data["x_max"] - data["x_min"]) >= 10


def test_distribution_points_are_within_x_range():
    """Every plotted point must fall within the reported x-range."""
    match = make_match()
    data = build_match_chart_data(match)
    for key in ("distribution_a", "distribution_b"):
        for point in data[key]:
            assert data["x_min"] <= point["x"] <= data["x_max"]
            assert 0.0 <= point["y"] <= 1.0


def test_no_scored_passes_gives_empty_passes_list():
    """Before any pass is scored, the passes list must be empty."""
    match = make_match()
    data = build_match_chart_data(match)
    assert data["passes"] == []


def test_scored_passes_are_included_in_order():
    """Scored passes must appear in the payload, in pass order, with raw scores."""
    match = make_match()
    match.record_pass(0, score_a=100, score_b=50)
    match.record_pass(1, score_a=90, score_b=60)
    data = build_match_chart_data(match)
    assert data["passes"] == [
        {"index": 0, "score_a": 100, "score_b": 50},
        {"index": 1, "score_a": 90, "score_b": 60},
    ]


def test_y_max_exceeds_peak_probability():
    """y_max should give some headroom above the tallest point of either curve."""
    match = make_match()
    data = build_match_chart_data(match)
    peak = max(
        max(p["y"] for p in data["distribution_a"]),
        max(p["y"] for p in data["distribution_b"]),
    )
    assert data["y_max"] > peak
