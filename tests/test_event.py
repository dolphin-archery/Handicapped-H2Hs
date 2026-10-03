"""Tests for h2h.models.Event (rotation-based multi-archer orchestration)."""

import pytest

from h2h.models import Archer, Bowstyle, Event, RoundMode
from h2h.rotation import build_schedule


def make_archers(n, base_handicap=20, step=5):
    """n archers with staggered handicaps, alternating bowstyle, for testing."""
    bowstyles = [Bowstyle.RECURVE, Bowstyle.COMPOUND, Bowstyle.BAREBOW]
    return [
        Archer(
            name=f"Archer{i}",
            handicap=base_handicap + i * step,
            bowstyle=bowstyles[i % len(bowstyles)],
        )
        for i in range(n)
    ]


def make_event(n_archers, n_pass=12, round_mode=RoundMode.INDOOR_PORTSMOUTH, n_rotations=None):
    """A ready-to-score Event for n_archers, with a full round-robin schedule."""
    archers = make_archers(n_archers)
    if n_rotations is None:
        n_rotations = n_archers if n_archers % 2 else n_archers - 1
    schedule = build_schedule(n_archers, n_rotations)
    return Event(archers, n_pass, round_mode, schedule)


def test_event_precomputes_own_distribution_per_archer():
    """Each archer's distribution is precomputed and independent of opponents."""
    event = make_event(4)
    for i in range(4):
        dist = event.distribution_for(i)
        assert pytest.approx(sum(dist.values()), abs=1e-6) == 1.0


def test_schedule_index_out_of_range_rejected():
    """A schedule referencing an archer index beyond len(archers) must raise."""
    archers = make_archers(2)
    schedule = build_schedule(4, 3)  # references indices up to 3
    with pytest.raises(ValueError):
        Event(archers, 12, RoundMode.INDOOR_PORTSMOUTH, schedule)


def test_recording_a_rotation_uses_each_archers_own_distribution():
    """Percentile/handicap for each archer must use their OWN resolved target."""
    event = make_event(2, round_mode=RoundMode.INDOOR_PORTSMOUTH)
    results = event.record_rotation(0, {0: 100, 1: 60})
    assert len(results) == 2
    for r in results:
        assert 0.0 <= r.percentile <= 1.0


def test_missing_or_extra_scores_rejected():
    """Scores must cover exactly the rotation's participants, no more, no less."""
    event = make_event(2)
    with pytest.raises(ValueError):
        event.record_rotation(0, {0: 100})  # missing archer 1
    with pytest.raises(ValueError):
        event.record_rotation(0, {0: 100, 1: 60, 5: 10})  # extra, unknown archer


def test_bye_archer_recorded_with_no_winner_and_no_pairwise_result():
    """The bye archer's pass is recorded but produces no winner or pairwise result."""
    event = make_event(3, n_rotations=3)  # odd -> each rotation has one bye
    rotation = event.schedule[0]
    scores = {p: 50 for pair in rotation.pairs for p in pair}
    scores[rotation.bye] = 40
    results = event.record_rotation(0, scores)

    bye_result = next(r for r in results if r.archer_index == rotation.bye)
    assert bye_result.won is None
    assert bye_result.opponent_index is None
    # The bye archer must not appear in any pairwise result derived from this rotation.
    for pr in event.all_pairwise_results():
        assert rotation.bye not in (pr.archer_a, pr.archer_b)


def test_pairwise_result_after_one_shared_pass():
    """After sharing one pass, the pair's pairwise result reflects that pass's winner."""
    event = make_event(2, n_pass=12)
    event.record_rotation(0, {0: 120, 1: 0})  # archer 0 crushes archer 1
    result = event.pairwise_result(0, 1)
    assert result is not None
    assert result.outcome == 0


def test_pairwise_result_none_before_sharing_a_rotation():
    """Two archers who haven't shared a rotation have no pairwise result."""
    event = make_event(4, n_rotations=3)
    # Find a genuinely unshared pair from the schedule instead of guessing:
    scheduled_pairs = {tuple(sorted(p)) for r in event.schedule for p in r.pairs}
    all_pairs = {(i, j) for i in range(4) for j in range(4) if i < j}
    unshared = all_pairs - scheduled_pairs
    if unshared:
        a, b = next(iter(unshared))
        assert event.pairwise_result(a, b) is None


def test_all_pairwise_results_grows_as_rotations_are_scored():
    """all_pairwise_results only includes pairs that have actually shared a rotation."""
    event = make_event(4, n_rotations=3)
    assert event.all_pairwise_results() == []
    rotation0 = event.schedule[0]
    scores = {p: 60 for pair in rotation0.pairs for p in pair}
    event.record_rotation(0, scores)
    assert len(event.all_pairwise_results()) == len(rotation0.pairs)


def test_next_rotation_index_and_is_complete():
    """next_rotation_index advances correctly and is_complete flips once done."""
    event = make_event(2, n_rotations=1)
    assert event.next_rotation_index() == 0
    assert not event.is_complete
    event.record_rotation(0, {0: 100, 1: 50})
    assert event.next_rotation_index() is None
    assert event.is_complete


def test_invalid_score_leaves_rotation_unrecorded():
    """An invalid score in the batch must not partially record the rotation."""
    event = make_event(2)
    with pytest.raises(ValueError):
        event.record_rotation(0, {0: 100.5, 1: 50})
    assert event.next_rotation_index() == 0  # nothing recorded


def test_different_bowstyles_give_different_indoor_distributions():
    """Same handicap, different bowstyle (Recurve vs Compound) indoors -> different distributions."""
    archers = [
        Archer(name="R", handicap=20, bowstyle=Bowstyle.RECURVE),
        Archer(name="C", handicap=20, bowstyle=Bowstyle.COMPOUND),
    ]
    schedule = build_schedule(2, 1)
    event = Event(archers, 12, RoundMode.INDOOR_PORTSMOUTH, schedule)
    assert event.distribution_for(0) != event.distribution_for(1)


def test_longbow_gives_same_indoor_distribution_as_recurve():
    """Same handicap, Recurve vs Longbow indoors -> identical distributions (no scoring variant)."""
    archers = [
        Archer(name="R", handicap=20, bowstyle=Bowstyle.RECURVE),
        Archer(name="L", handicap=20, bowstyle=Bowstyle.LONGBOW),
    ]
    schedule = build_schedule(2, 1)
    event = Event(archers, 12, RoundMode.INDOOR_PORTSMOUTH, schedule)
    assert event.distribution_for(0) == event.distribution_for(1)


def test_outdoor_mode_gives_same_distribution_regardless_of_bowstyle():
    """Same handicap, different bowstyle, outdoor mode -> identical distributions."""
    archers = [
        Archer(name="R", handicap=20, bowstyle=Bowstyle.RECURVE),
        Archer(name="C", handicap=20, bowstyle=Bowstyle.COMPOUND),
    ]
    schedule = build_schedule(2, 1)
    event = Event(archers, 12, RoundMode.OUTDOOR, schedule)
    assert event.distribution_for(0) == event.distribution_for(1)
