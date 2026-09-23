"""Tests for h2h.state.SessionState's two-stage event setup methods."""

import pytest

from h2h.models import Archer, Bowstyle, RoundMode
from h2h.state import SessionState


def test_start_stage1_builds_schedule():
    """A valid Stage 1 config builds and stores a rotation schedule."""
    state = SessionState()
    state.start_stage1(4, 60, 12, RoundMode.INDOOR_PORTSMOUTH)
    assert state.schedule is not None
    assert len(state.schedule) == 60 // 12
    assert state.n_archers == 4
    assert state.n_pass == 12
    assert state.round_mode == RoundMode.INDOOR_PORTSMOUTH


def test_start_stage1_rejects_too_few_archers():
    """n_archers < 2 must be rejected without touching state."""
    state = SessionState()
    with pytest.raises(ValueError):
        state.start_stage1(1, 60, 12, RoundMode.INDOOR_PORTSMOUTH)
    assert state.schedule is None


def test_start_stage1_rejects_non_dividing_n_pass():
    """n_pass that doesn't evenly divide total_arrows must be rejected."""
    state = SessionState()
    with pytest.raises(ValueError):
        state.start_stage1(4, 60, 7, RoundMode.INDOOR_PORTSMOUTH)
    assert state.schedule is None


def test_start_stage1_discards_previous_event():
    """Starting a new Stage 1 clears any previously built Event."""
    state = SessionState()
    state.start_stage1(2, 12, 12, RoundMode.INDOOR_PORTSMOUTH)
    state.start_stage2([
        Archer(name="A", handicap=20, bowstyle=Bowstyle.RECURVE),
        Archer(name="B", handicap=30, bowstyle=Bowstyle.RECURVE),
    ])
    assert state.event is not None
    state.start_stage1(3, 60, 12, RoundMode.INDOOR_WA18)
    assert state.event is None


def test_start_stage2_requires_stage1_first():
    """Calling start_stage2 before start_stage1 must raise."""
    state = SessionState()
    with pytest.raises(RuntimeError):
        state.start_stage2([Archer(name="A", handicap=20, bowstyle=Bowstyle.RECURVE)])


def test_start_stage2_requires_matching_archer_count():
    """The archer count must match Stage 1's n_archers."""
    state = SessionState()
    state.start_stage1(3, 60, 12, RoundMode.INDOOR_PORTSMOUTH)
    with pytest.raises(ValueError):
        state.start_stage2(
            [
                Archer(name="A", handicap=20, bowstyle=Bowstyle.RECURVE),
                Archer(name="B", handicap=30, bowstyle=Bowstyle.RECURVE),
            ]
        )


def test_start_stage2_builds_event():
    """A matching archer count builds a usable Event."""
    state = SessionState()
    state.start_stage1(2, 12, 12, RoundMode.OUTDOOR)
    state.start_stage2(
        [
            Archer(name="A", handicap=20, bowstyle=Bowstyle.RECURVE),
            Archer(name="B", handicap=30, bowstyle=Bowstyle.COMPOUND),
        ]
    )
    assert state.event is not None
    assert state.event.archers[0].name == "A"


def test_reset_clears_new_event_fields_too():
    """reset() clears the new Stage 1/2/event fields, not just the old ones."""
    state = SessionState()
    state.start_stage1(2, 12, 12, RoundMode.INDOOR_PORTSMOUTH)
    state.start_stage2(
        [
            Archer(name="A", handicap=20, bowstyle=Bowstyle.RECURVE),
            Archer(name="B", handicap=30, bowstyle=Bowstyle.RECURVE),
        ]
    )
    state.reset()
    assert state.n_archers is None
    assert state.schedule is None
    assert state.event is None
