"""Tests for h2h.chart_data.build_pair_chart_data (Event-based chart payload)."""

import json

import pytest

from h2h.chart_data import build_pair_chart_data
from h2h.models import METRE, YARD, Archer, Bowstyle, Event, TargetSetup
from h2h.rotation import build_schedule, build_sit_out_schedule

from .helpers import PORTSMOUTH, record_whole_rotation


def make_event(n_archers=4, n_pass=12, target_setup=PORTSMOUTH, handicaps=None):
    bowstyles = [Bowstyle.RECURVE, Bowstyle.COMPOUND, Bowstyle.BAREBOW]
    archers = [
        Archer(
            name=f"A{i}",
            handicap=handicaps[i] if handicaps else 15 + i * 10,
            bowstyle=bowstyles[i % 3],
        )
        for i in range(n_archers)
    ]
    schedule = build_schedule(n_archers, n_archers - 1 if n_archers % 2 == 0 else n_archers)
    return Event(archers, n_pass, target_setup, schedule)


def score_pass(event, score_fn):
    """Record every match of the current pass with score_fn(archer_index) for each archer."""
    for match in event.matches(event.current_rotation_index):
        event.record_match({p: score_fn(p) for p in match if p is not None})


def scores_of(data, side):
    """The (pass index, score) pairs in one archer's payload entry."""
    return [(p["index"], p["score"]) for p in data[side]["passes"]]


def test_payload_uses_each_archers_own_distribution():
    """The payload's distributions must match Event.distribution_for each archer."""
    event = make_event()
    data = build_pair_chart_data(event, 0, 1)
    assert data["archer_a"]["name"] == "A0"
    assert data["archer_b"]["name"] == "A1"


def test_different_bowstyles_give_visibly_different_curves():
    """Two archers with different resolved targets must get different distributions."""
    event = make_event(target_setup=PORTSMOUTH)
    # Archer 0 is Recurve, archer 1 is Compound (per make_event's bowstyle cycle).
    data = build_pair_chart_data(event, 0, 1)
    assert data["distribution_a"] != data["distribution_b"]


def test_no_scores_before_anything_is_scored():
    """Before any pass is scored, neither archer has any score to mark."""
    event = make_event()
    a, b = event.schedule[0].pairs[0]
    data = build_pair_chart_data(event, a, b)
    assert data["archer_a"]["passes"] == [] and data["archer_b"]["passes"] == []


def test_a_scored_pass_appears_in_both_archers_lists():
    """After scoring pass 1, each archer's list has that pass's score."""
    event = make_event()
    a, b = event.schedule[0].pairs[0]
    record_whole_rotation(event, score=60)
    data = build_pair_chart_data(event, a, b)
    assert scores_of(data, "archer_a") == [(0, 60)]
    assert scores_of(data, "archer_b") == [(0, 60)]


def test_every_pass_an_archer_has_shot_is_listed_whoever_the_opponent_was():
    """Three passes against three different opponents: all three scores are in each list."""
    event = make_event(4)
    for _ in range(3):
        score_pass(event, lambda p: 70 + 5 * p + 2 * event.current_rotation_index)
        if event.current_rotation_index < 2:
            event.advance()
    opponents_of_0 = {r.opponent_index for r in event.results if r.archer_index == 0}
    assert len(opponents_of_0) == 3  # a genuine round-robin: a different opponent every pass

    data = build_pair_chart_data(event, 0, 1)
    assert scores_of(data, "archer_a") == [(0, 70), (1, 72), (2, 74)]
    assert scores_of(data, "archer_b") == [(0, 75), (1, 77), (2, 79)]


def test_a_pair_that_has_not_met_still_shows_each_archers_earlier_scores():
    """The reported bug: a not-yet-met pair showed no earlier lines at all."""
    event = make_event(6)  # 5 rotations; only pass 1 and 2 scored
    for _ in range(2):
        score_pass(event, lambda p: 60 + 4 * p + 3 * event.current_rotation_index)
        event.advance()
    met = {frozenset(pair) for rot in event.schedule[:2] for pair in rot.pairs}
    a, b = next((x, y) for x in range(6) for y in range(x + 1, 6) if frozenset((x, y)) not in met)

    data = build_pair_chart_data(event, a, b)
    assert scores_of(data, "archer_a") == [(0, 60 + 4 * a), (1, 63 + 4 * a)]
    assert scores_of(data, "archer_b") == [(0, 60 + 4 * b), (1, 63 + 4 * b)]


def test_a_bye_pass_is_listed_and_a_sat_out_pass_is_not():
    """A solo bye score counts as a score shot; sitting a pass out leaves no entry."""
    archers = [Archer(f"B{i}", 20 + 10 * i, Bowstyle.RECURVE) for i in range(3)]
    byes = Event(archers, 12, PORTSMOUTH, build_schedule(3, 3))
    bye_archer = byes.schedule[0].bye
    score_pass(byes, lambda p: 80 + p)
    other = next(i for i in range(3) if i != bye_archer)
    data = build_pair_chart_data(byes, bye_archer, other)
    assert scores_of(data, "archer_a") == [(0, 80 + bye_archer)]

    sit = Event(archers, 12, PORTSMOUTH, build_sit_out_schedule(3, 3))
    sitter = sit.schedule[0].sitting_out[0]
    score_pass(sit, lambda p: 80 + p)
    other = next(i for i in range(3) if i != sitter)
    data = build_pair_chart_data(sit, sitter, other)
    assert scores_of(data, "archer_a") == []
    assert scores_of(data, "archer_b") == [(0, 80 + other)]


def test_current_pass_is_the_events_current_rotation():
    """The pass the chart shows by default, and an archer with no score in it has no entry for it."""
    event = make_event(4)
    assert build_pair_chart_data(event, 0, 1)["current_pass"] == 0
    score_pass(event, lambda p: 70 + 5 * p)
    event.advance()
    data = build_pair_chart_data(event, 0, 1)
    assert data["current_pass"] == 1
    assert all(p["index"] != 1 for p in data["archer_a"]["passes"] + data["archer_b"]["passes"])


def test_the_x_range_widens_to_include_scores_far_outside_the_curves():
    """A very low and a very high score are both inside [x_min, x_max], within [0, max score]."""
    archers = [Archer("Low", 30, Bowstyle.RECURVE), Archer("High", 30, Bowstyle.RECURVE)]
    event = Event(archers, 12, PORTSMOUTH, build_schedule(2, 1))
    base = build_pair_chart_data(event, 0, 1)
    event.record_match({0: 20, 1: 118})

    data = build_pair_chart_data(event, 0, 1)
    assert data["x_min"] <= 19 and data["x_max"] >= 119
    assert 0 <= data["x_min"] and data["x_max"] <= 120
    assert data["x_min"] < base["x_min"]  # the old trimmed range excluded the 20


def test_the_x_range_is_clamped_to_the_possible_scores():
    """A perfect score of 120 gives an x_max of 120, not 121; a zero gives an x_min of 0."""
    archers = [Archer("Zero", 30, Bowstyle.RECURVE), Archer("Max", 5, Bowstyle.RECURVE)]
    event = Event(archers, 12, PORTSMOUTH, build_schedule(2, 1))
    event.record_match({0: 0, 1: 120})
    data = build_pair_chart_data(event, 0, 1)
    assert data["x_min"] == 0 and data["x_max"] == 120


def test_scores_inside_the_trimmed_range_leave_the_range_alone_apart_from_the_margin():
    """When every score is where the curves are, the range is the old trimmed one."""
    archers = [Archer("A", 30, Bowstyle.RECURVE), Archer("B", 40, Bowstyle.RECURVE)]
    event = Event(archers, 12, PORTSMOUTH, build_schedule(2, 1))
    before = build_pair_chart_data(event, 0, 1)
    middle = (before["x_min"] + before["x_max"]) // 2
    event.record_match({0: middle, 1: middle + 3})
    after = build_pair_chart_data(event, 0, 1)
    assert (after["x_min"], after["x_max"]) == (before["x_min"], before["x_max"])


def test_the_range_is_set_by_all_the_scores_so_it_does_not_depend_on_which_are_shown():
    """One payload, one range: it already covers a far-out earlier score and the latest one."""
    archers = [Archer("A", 30, Bowstyle.RECURVE), Archer("B", 31, Bowstyle.RECURVE)]
    event = Event(archers, 12, PORTSMOUTH, build_schedule(2, 2))
    event.record_match({0: 15, 1: 25})  # far below the curves, in pass 1
    event.advance()
    event.record_match({0: 100, 1: 101})
    data = build_pair_chart_data(event, 0, 1)
    assert data["x_min"] <= 14  # pass 1's score is in range even though only pass 2 shows by default


def test_each_curve_has_a_point_at_every_whole_score_in_the_final_range_zero_where_impossible():
    """Full curves: a marker far from one archer's usual scores still has a curve value under it."""
    archers = [Archer("A", 30, Bowstyle.RECURVE), Archer("B", 30, Bowstyle.RECURVE)]
    event = Event(archers, 12, PORTSMOUTH, build_schedule(2, 1))
    event.record_match({0: 30, 1: 110})
    data = build_pair_chart_data(event, 0, 1)
    full_range = list(range(data["x_min"], data["x_max"] + 1))
    for index, curve in ((0, data["distribution_a"]), (1, data["distribution_b"])):
        distribution = event.distribution_for(index)
        assert [p["x"] for p in curve] == full_range
        assert [p["y"] for p in curve] == [distribution.get(float(x), 0.0) for x in full_range]
    assert data["distribution_a"][0]["y"] < 1e-100  # a score of 29 at handicap 30: negligible
    assert any(p["y"] > 0 for p in data["distribution_a"])


@pytest.mark.parametrize(
    ("handicap", "label"),
    [(22.5, "Alice (handicap 22.5)"), (15.0, "Alice (handicap 15)"), (7.25, "Alice (handicap 7.25)")],
)
def test_legend_label_is_name_and_handicap_as_entered_when_not_updating(handicap, label):
    """Whole handicaps have no trailing .0; decimals are kept (Feedback 7 restored the legend handicap)."""
    archers = [Archer("Alice", handicap, Bowstyle.RECURVE), Archer("Bob", 40, Bowstyle.RECURVE)]
    event = Event(archers, 12, PORTSMOUTH, build_schedule(2, 1))
    data = build_pair_chart_data(event, 0, 1)
    assert data["archer_a"]["legend"] == label
    assert data["archer_b"]["legend"] == "Bob (handicap 40)"
    assert data["archer_a"]["name"] == "Alice" and set(data["archer_a"]) == {"name", "legend", "passes"}


def test_legend_label_shows_the_current_passes_handicap_to_one_decimal_when_updating():
    """Before any pass the entered handicap (one decimal); after a poor pass the updated one."""
    archers = [Archer("Alice", 30, Bowstyle.RECURVE), Archer("Bob", 40, Bowstyle.RECURVE)]
    event = Event(archers, 12, PORTSMOUTH, build_schedule(2, 2), update_handicaps=True,
                  n_lookback=1, start_weight=2)
    first = build_pair_chart_data(event, 0, 1)
    assert first["archer_a"]["legend"] == "Alice (handicap 30.0)"
    assert first["archer_b"]["legend"] == "Bob (handicap 40.0)"

    event.record_match({0: 80, 1: 100})
    event.advance()
    second = build_pair_chart_data(event, 0, 1)
    assert second["archer_a"]["legend"] == f"Alice (handicap {event.handicap_for(0):.1f})"
    assert second["archer_b"]["legend"] == f"Bob (handicap {event.handicap_for(1):.1f})"
    assert second["archer_a"]["legend"] != first["archer_a"]["legend"]


def test_pair_of_archers_on_different_faces_gets_one_shared_range_within_the_larger_maximum():
    """5-zone (max 108) against 10-zone (max 120): x_max never exceeds 120 and y_max covers both."""
    archers = [
        Archer("Five", 30, Bowstyle.RECURVE, target_setup=TargetSetup(20, YARD, 60, "5_zone")),
        Archer("Ten", 30, Bowstyle.RECURVE, target_setup=TargetSetup(20, YARD, 60, "10_zone")),
    ]
    event = Event(archers, 12, None, build_schedule(2, 1))
    event.record_match({0: 108, 1: 120})
    data = build_pair_chart_data(event, 0, 1)
    assert 0 <= data["x_min"] and data["x_max"] == 120
    peak = max(max(event.distribution_for(0).values()), max(event.distribution_for(1).values()))
    assert data["y_max"] >= peak


def test_the_payload_is_json_serialisable():
    """It is embedded in the page with tojson."""
    event = make_event(4)
    record_whole_rotation(event, score=60)
    json.dumps(build_pair_chart_data(event, 0, 1))


def test_pair_never_sharing_a_rotation_still_produces_a_valid_payload():
    """build_pair_chart_data works for any two archer indices, regardless of schedule."""
    event = make_event(n_archers=6)
    data = build_pair_chart_data(event, 0, 1)
    assert data["archer_a"]["passes"] == [] and data["archer_b"]["passes"] == []
    assert 0.0 <= data["x_min"] <= data["x_max"]


def test_the_curves_use_the_current_passes_updated_handicap():
    """With handicap updating on, after a poor pass the next pass's curve differs from the constant one."""
    def build(update):
        archers = [Archer("A", 30, Bowstyle.RECURVE), Archer("B", 40, Bowstyle.RECURVE)]
        event = Event(archers, 12, PORTSMOUTH, build_schedule(2, 2), update_handicaps=update,
                      n_lookback=1 if update else None, start_weight=2 if update else None)
        event.record_match({0: 80, 1: 100})
        event.advance()
        return build_pair_chart_data(event, 0, 1)

    updated, constant = build(True), build(False)
    assert updated["distribution_a"] != constant["distribution_a"]
    assert updated["distribution_b"] != constant["distribution_b"]
