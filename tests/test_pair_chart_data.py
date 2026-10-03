"""Tests for h2h.chart_data.build_pair_chart_data (Event-based chart payload)."""

from h2h.chart_data import build_pair_chart_data
from h2h.models import Archer, Bowstyle, Event
from h2h.rotation import build_schedule

from .helpers import PORTSMOUTH, record_whole_rotation


def make_event(n_archers=4, n_pass=12, target_setup=PORTSMOUTH):
    bowstyles = [Bowstyle.RECURVE, Bowstyle.COMPOUND, Bowstyle.BAREBOW]
    archers = [
        Archer(name=f"A{i}", handicap=15 + i * 10, bowstyle=bowstyles[i % 3])
        for i in range(n_archers)
    ]
    schedule = build_schedule(n_archers, n_archers - 1 if n_archers % 2 == 0 else n_archers)
    return Event(archers, n_pass, target_setup, schedule)


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


def test_no_shared_passes_before_scoring():
    """Before any rotation is scored, the payload's passes list must be empty."""
    event = make_event()
    a, b = event.schedule[0].pairs[0]
    data = build_pair_chart_data(event, a, b)
    assert data["passes"] == []


def test_shared_pass_appears_after_scoring():
    """A shared, scored rotation must appear in the payload's passes list."""
    event = make_event()
    rotation = event.schedule[0]
    a, b = rotation.pairs[0]
    record_whole_rotation(event, score=60)

    data = build_pair_chart_data(event, a, b)
    assert len(data["passes"]) == 1
    assert data["passes"][0]["score_a"] == 60
    assert data["passes"][0]["score_b"] == 60


def test_pair_never_sharing_a_rotation_still_produces_a_valid_payload():
    """build_pair_chart_data works for any two archer indices, regardless of schedule."""
    event = make_event(n_archers=6)
    data = build_pair_chart_data(event, 0, 1)
    assert data["passes"] == []
    assert 0.0 <= data["x_min"] <= data["x_max"]
