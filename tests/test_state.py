"""Tests for h2h.state.SessionState's three-stage event setup methods."""

import random

import pytest

from h2h.models import DEFAULT_TARGET_SETUP, METRE, Archer, Bowstyle, TargetSetup
from h2h.state import SessionState

from .helpers import OUTDOOR_70M, PORTSMOUTH, WA18, NoShuffle, make_state


def test_start_stage1_builds_schedule():
    """A valid Stage 1 config builds and stores a rotation schedule."""
    state = SessionState()
    state.start_stage1(4, 60, 12, PORTSMOUTH)
    assert state.schedule is not None
    assert len(state.schedule) == 60 // 12
    assert state.n_archers == 4
    assert state.n_pass == 12
    assert state.target_setup == PORTSMOUTH


def test_start_stage1_rejects_too_few_archers():
    """n_archers < 2 must be rejected without touching state."""
    state = SessionState()
    with pytest.raises(ValueError):
        state.start_stage1(1, 60, 12, PORTSMOUTH)
    assert state.schedule is None


def test_start_stage1_rejects_non_dividing_n_pass():
    """n_pass that doesn't evenly divide total_arrows must be rejected."""
    state = SessionState()
    with pytest.raises(ValueError):
        state.start_stage1(4, 60, 7, PORTSMOUTH)
    assert state.schedule is None


def test_start_stage1_discards_previous_event():
    """Starting a new Stage 1 clears any previously built Event."""
    state = SessionState()
    state.start_stage1(2, 12, 12, PORTSMOUTH)
    state.start_stage2([
        Archer(name="A", handicap=20, bowstyle=Bowstyle.RECURVE),
        Archer(name="B", handicap=30, bowstyle=Bowstyle.RECURVE),
    ])
    state.start_event()
    assert state.event is not None
    state.start_stage1(3, 60, 12, WA18)
    assert state.event is None
    assert state.pending_archers is None and state.assignment is None


def test_start_stage2_requires_stage1_first():
    """Calling start_stage2 before start_stage1 must raise."""
    state = SessionState()
    with pytest.raises(RuntimeError):
        state.start_stage2([Archer(name="A", handicap=20, bowstyle=Bowstyle.RECURVE)])


def test_start_stage2_requires_matching_archer_count():
    """The archer count must match Stage 1's n_archers."""
    state = SessionState()
    state.start_stage1(3, 60, 12, PORTSMOUTH)
    with pytest.raises(ValueError):
        state.start_stage2(
            [
                Archer(name="A", handicap=20, bowstyle=Bowstyle.RECURVE),
                Archer(name="B", handicap=30, bowstyle=Bowstyle.RECURVE),
            ]
        )


def test_start_stage2_stores_the_archers_and_draws_but_builds_no_event():
    """Stage 2 keeps the entered archers and a valid draw; the event waits for Stage 3."""
    state = make_state()
    state.start_stage1(2, 12, 12, OUTDOOR_70M)
    state.start_stage2(
        [
            Archer(name="A", handicap=20, bowstyle=Bowstyle.RECURVE),
            Archer(name="B", handicap=30, bowstyle=Bowstyle.COMPOUND),
        ]
    )
    assert state.event is None
    assert [a.name for a in state.pending_archers] == ["A", "B"]
    assert sorted(state.assignment) == [0, 1]


def test_start_event_builds_a_usable_event_in_the_assigned_order():
    """Confirming Stage 3 builds the Event with archers[position] = the assigned archer."""
    state = SessionState(rng=random.Random(3))
    state.start_stage1(4, 36, 12, OUTDOOR_70M)
    entered = [Archer(name=n, handicap=20 + i, bowstyle=Bowstyle.RECURVE) for i, n in enumerate("ABCD")]
    state.start_stage2(entered)
    state.start_event()
    assert state.event is not None
    assert [a.name for a in state.event.archers] == [entered[i].name for i in state.assignment]
    assert state.event.schedule is state.schedule


def test_reset_clears_new_event_fields_too():
    """reset() clears the new Stage 1/2/event fields, not just the old ones."""
    state = SessionState()
    state.start_stage1(2, 12, 12, PORTSMOUTH)
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
    assert state.pending_archers is None and state.assignment is None


# --- "Shoot byes?" (Feedback 3) -------------------------------------------


def test_shoot_byes_defaults_to_true():
    """Byes are shot unless the scorer says otherwise (the earlier behaviour)."""
    assert SessionState().shoot_byes is True


def test_odd_archers_with_byes_shot_keeps_the_ordinary_schedule():
    """shoot_byes=True: total_arrows // n_pass rotations, each with a solo bye archer."""
    state = SessionState()
    state.start_stage1(5, 60, 12, PORTSMOUTH, shoot_byes=True)
    assert len(state.schedule) == 5
    assert all(r.bye is not None and r.sitting_out == () for r in state.schedule)


def test_odd_archers_without_byes_shot_gets_a_longer_sit_out_schedule():
    """shoot_byes=False with 5 archers needing 5 passes -> 7 rotations, nobody shoots alone."""
    state = SessionState()
    state.start_stage1(5, 60, 12, PORTSMOUTH, shoot_byes=False)
    assert state.shoot_byes is False
    assert len(state.schedule) == 7
    assert all(r.bye is None and r.sitting_out for r in state.schedule)


def test_even_archers_ignore_shoot_byes():
    """With an even archer count there are no byes, so the flag changes nothing."""
    with_flag = SessionState()
    with_flag.start_stage1(4, 60, 12, PORTSMOUTH, shoot_byes=False)
    without = SessionState()
    without.start_stage1(4, 60, 12, PORTSMOUTH, shoot_byes=True)
    assert with_flag.schedule == without.schedule
    assert len(with_flag.schedule) == 5


def test_reset_restores_shoot_byes_default():
    """reset() puts shoot_byes back to its default of True."""
    state = SessionState()
    state.start_stage1(5, 60, 12, PORTSMOUTH, shoot_byes=False)
    state.reset()
    assert state.shoot_byes is True


# --- Graph view (Feedback 4) ------------------------------------------------


def test_graph_view_defaults_to_off_and_toggles():
    """Graph view starts off, flips on each toggle, and there is no string `mode` any more."""
    state = SessionState()
    assert state.graph_view is False
    state.toggle_graph_view()
    assert state.graph_view is True
    state.toggle_graph_view()
    assert state.graph_view is False
    assert not hasattr(state, "mode")


def test_reset_turns_graph_view_off():
    """reset() restores the default of graph view off."""
    state = SessionState()
    state.toggle_graph_view()
    state.reset()
    assert state.graph_view is False


# --- Target setup (Feedback 4) ----------------------------------------------


def test_session_starts_with_the_default_target_setup():
    """A fresh session has the default 20 yd / 60 cm setup."""
    assert SessionState().target_setup == DEFAULT_TARGET_SETUP


def test_start_stage1_stores_the_chosen_target_setup():
    """Stage 1 keeps the shared distance and face size it was given."""
    state = SessionState()
    chosen = TargetSetup(distance=50, unit=METRE, face_cm=80)
    state.start_stage1(4, 60, 12, chosen)
    assert state.target_setup == chosen


def test_rejected_stage1_leaves_the_previous_target_setup_untouched():
    """A failed Stage 1 (bad n_pass) does not half-update the setup."""
    state = SessionState()
    with pytest.raises(ValueError):
        state.start_stage1(4, 60, 7, TargetSetup(distance=50, unit=METRE, face_cm=80))
    assert state.target_setup == DEFAULT_TARGET_SETUP


def test_reset_restores_the_default_target_setup():
    """reset() puts the setup back to 20 yd / 60 cm."""
    state = SessionState()
    state.start_stage1(4, 60, 12, TargetSetup(distance=90, unit=METRE, face_cm=122))
    state.reset()
    assert state.target_setup == DEFAULT_TARGET_SETUP


def test_the_event_is_built_with_the_chosen_target_setup():
    """The Event resolves every archer's target from the session's setup."""
    state = make_state()
    chosen = TargetSetup(distance=50, unit=METRE, face_cm=80)
    state.start_stage1(2, 12, 12, chosen)
    state.start_stage2(
        [
            Archer(name="A", handicap=20, bowstyle=Bowstyle.RECURVE),
            Archer(name="B", handicap=30, bowstyle=Bowstyle.COMPOUND),
        ]
    )
    state.start_event()
    event = state.event
    assert event.target_setup == chosen
    for i in (0, 1):
        assert event.target_for(i).distance == 50
        assert event.target_for(i).diameter == pytest.approx(0.8)


# --- Stage 3: pairing assignment (Feedback 4) -------------------------------------


def entered_archers(n):
    """n archers with distinct names/handicaps, in entry order."""
    return [
        Archer(name=f"A{i}", handicap=15 + 5 * i, bowstyle=Bowstyle.RECURVE) for i in range(n)
    ]


def state_at_stage3(n=4, total_arrows=36, rng=None, shoot_byes=True):
    """A session that has completed Stages 1 and 2 (no event yet)."""
    state = SessionState(rng=rng or random.Random(0))
    state.start_stage1(n, total_arrows, 12, PORTSMOUTH, shoot_byes=shoot_byes)
    state.start_stage2(entered_archers(n))
    return state


@pytest.mark.parametrize("seed", range(5))
def test_the_draw_is_always_a_permutation_of_the_entered_archers(seed):
    """Whatever the random source, every archer fills exactly one position."""
    state = state_at_stage3(n=6, total_arrows=60, rng=random.Random(seed))
    assert sorted(state.assignment) == list(range(6))


def test_a_non_shuffling_source_gives_entry_order_and_a_seeded_one_a_fixed_shuffle():
    """The random source is injectable: identity for tests, deterministic when seeded."""
    assert state_at_stage3(n=5, total_arrows=60, rng=NoShuffle()).assignment == [0, 1, 2, 3, 4]
    first = state_at_stage3(n=8, total_arrows=84, rng=random.Random(42)).assignment
    again = state_at_stage3(n=8, total_arrows=84, rng=random.Random(42)).assignment
    assert first == again
    assert first != list(range(8))


def test_the_default_random_source_is_a_real_random_generator():
    """Without injection the session uses random.Random (so draws really are random)."""
    assert isinstance(SessionState().rng, random.Random)
    assert not isinstance(SessionState().rng, NoShuffle)


def test_redraw_changes_the_pairings_when_a_different_one_exists():
    """Each redraw gives pairings that differ from the previous draw's (4+ archers)."""
    state = state_at_stage3(n=4, total_arrows=36, rng=random.Random(1))
    for _ in range(25):
        before = state._pairings_signature(state.assignment)
        state.redraw_pairings()
        assert sorted(state.assignment) == [0, 1, 2, 3]
        assert state._pairings_signature(state.assignment) != before


def test_redraw_with_two_archers_keeps_a_valid_draw_since_nothing_else_exists():
    """With only one possible pairing, redraw cannot change it but must not fail."""
    state = state_at_stage3(n=2, total_arrows=12, rng=random.Random(1))
    state.redraw_pairings()
    assert sorted(state.assignment) == [0, 1]


def test_redraw_does_not_touch_the_schedule_structure():
    """The schedule keeps its rotations and sit-out counts; only who fills them changes."""
    state = state_at_stage3(n=5, total_arrows=60, rng=random.Random(2), shoot_byes=False)
    schedule = state.schedule
    shape = [(len(r.pairs), len(r.sitting_out), r.bye) for r in schedule]
    for _ in range(5):
        state.redraw_pairings()
    assert state.schedule is schedule
    assert [(len(r.pairs), len(r.sitting_out), r.bye) for r in schedule] == shape


def test_redraw_and_assigned_archers_require_stage2_first():
    """Drawing, reading or confirming before Stage 2 is a RuntimeError."""
    state = SessionState()
    state.start_stage1(4, 36, 12, PORTSMOUTH)
    for call in (state.redraw_pairings, state.assigned_archers, state.start_event):
        with pytest.raises(RuntimeError):
            call()


def test_resubmitting_stage2_discards_the_old_draw_and_any_event():
    """Entering the archers again starts from a fresh draw and no event."""
    state = state_at_stage3(n=4, total_arrows=36)
    state.start_event()
    state.start_stage2(entered_archers(4))
    assert state.event is None
    assert state.assignment is not None


# --- Setup mode: simple or advanced (Feedback 5) -------------------------------------


def advanced_archers(n=2):
    """Archers that each carry their own target setup."""
    return [
        Archer(
            name=f"A{i}",
            handicap=15 + 5 * i,
            bowstyle=Bowstyle.RECURVE,
            target_setup=TargetSetup(18, METRE, 40, "10_zone" if i % 2 == 0 else "5_zone"),
        )
        for i in range(n)
    ]


def test_setup_mode_defaults_to_simple_and_is_stored_by_stage_1_and_cleared_by_reset():
    """start_stage1 records the mode, and reset restores simple."""
    state = SessionState()
    assert state.setup_mode == "simple"
    state.start_stage1(4, 60, 12, PORTSMOUTH, setup_mode="advanced")
    assert state.setup_mode == "advanced"
    state.reset()
    assert state.setup_mode == "simple"


def test_an_unknown_setup_mode_is_rejected_without_touching_state():
    """Only 'simple' and 'advanced' are valid."""
    state = SessionState()
    with pytest.raises(ValueError, match="Simple or Advanced"):
        state.start_stage1(4, 60, 12, PORTSMOUTH, setup_mode="expert")
    assert state.schedule is None and state.setup_mode == "simple"


def test_advanced_stage_2_needs_a_target_setup_for_every_archer():
    """An archer without their own setup is refused in advanced mode, and nothing is stored."""
    state = SessionState(rng=NoShuffle())
    state.start_stage1(2, 24, 12, PORTSMOUTH, setup_mode="advanced")
    with pytest.raises(ValueError, match="A1"):
        state.start_stage2([advanced_archers(2)[0], Archer("A1", 20, Bowstyle.RECURVE)])
    assert state.pending_archers is None


def test_advanced_event_has_no_shared_setup_and_each_archer_keeps_their_own():
    """start_event passes no shared setup in advanced mode; the targets come from the archers."""
    state = SessionState(rng=NoShuffle())
    state.start_stage1(2, 24, 12, PORTSMOUTH, setup_mode="advanced")
    state.start_stage2(advanced_archers(2))
    state.start_event()
    assert state.event.target_setup is None
    assert [state.event.target_for(i).scoring_system for i in (0, 1)] == ["10_zone", "5_zone"]


def test_simple_event_still_uses_the_shared_setup():
    """In simple mode the Event gets the session's shared TargetSetup."""
    state = SessionState(rng=NoShuffle())
    state.start_stage1(2, 24, 12, PORTSMOUTH)
    state.start_stage2(entered_archers(2))
    state.start_event()
    assert state.event.target_setup == PORTSMOUTH
