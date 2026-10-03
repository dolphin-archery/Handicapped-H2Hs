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


# --- "Shoot byes?" (Feedback 3) -------------------------------------------


def test_shoot_byes_defaults_to_true():
    """Byes are shot unless the scorer says otherwise (the earlier behaviour)."""
    assert SessionState().shoot_byes is True


def test_odd_archers_with_byes_shot_keeps_the_ordinary_schedule():
    """shoot_byes=True: total_arrows // n_pass rotations, each with a solo bye archer."""
    state = SessionState()
    state.start_stage1(5, 60, 12, RoundMode.INDOOR_PORTSMOUTH, shoot_byes=True)
    assert len(state.schedule) == 5
    assert all(r.bye is not None and r.sitting_out == () for r in state.schedule)


def test_odd_archers_without_byes_shot_gets_a_longer_sit_out_schedule():
    """shoot_byes=False with 5 archers needing 5 passes -> 7 rotations, nobody shoots alone."""
    state = SessionState()
    state.start_stage1(5, 60, 12, RoundMode.INDOOR_PORTSMOUTH, shoot_byes=False)
    assert state.shoot_byes is False
    assert len(state.schedule) == 7
    assert all(r.bye is None and r.sitting_out for r in state.schedule)


def test_even_archers_ignore_shoot_byes():
    """With an even archer count there are no byes, so the flag changes nothing."""
    with_flag = SessionState()
    with_flag.start_stage1(4, 60, 12, RoundMode.INDOOR_PORTSMOUTH, shoot_byes=False)
    without = SessionState()
    without.start_stage1(4, 60, 12, RoundMode.INDOOR_PORTSMOUTH, shoot_byes=True)
    assert with_flag.schedule == without.schedule
    assert len(with_flag.schedule) == 5


def test_reset_restores_shoot_byes_default():
    """reset() puts shoot_byes back to its default of True."""
    state = SessionState()
    state.start_stage1(5, 60, 12, RoundMode.INDOOR_PORTSMOUTH, shoot_byes=False)
    state.reset()
    assert state.shoot_byes is True
