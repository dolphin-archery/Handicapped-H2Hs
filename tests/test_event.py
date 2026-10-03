"""Tests for h2h.models.Event (rotation-based multi-archer orchestration)."""

import pytest

from h2h import stats
from h2h.models import METRE, YARD, Archer, Bowstyle, Event, TargetSetup
from h2h.rotation import Rotation, build_schedule, build_sit_out_schedule

from .helpers import OUTDOOR_70M, PORTSMOUTH, record_whole_rotation


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


def make_event(n_archers, n_pass=12, target_setup=PORTSMOUTH, n_rotations=None):
    """A ready-to-score Event for n_archers, with a full round-robin schedule."""
    archers = make_archers(n_archers)
    if n_rotations is None:
        n_rotations = n_archers if n_archers % 2 else n_archers - 1
    schedule = build_schedule(n_archers, n_rotations)
    return Event(archers, n_pass, target_setup, schedule)


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
        Event(archers, 12, PORTSMOUTH, schedule)


def test_recording_a_rotation_uses_each_archers_own_distribution():
    """Percentile/handicap for each archer must use their OWN resolved target."""
    event = make_event(2, target_setup=PORTSMOUTH)
    results = event.record_match({0: 100, 1: 60})
    assert len(results) == 2
    for r in results:
        assert 0.0 <= r.percentile <= 1.0


def test_missing_or_extra_scores_rejected():
    """Scores must cover exactly one match's archers, no more, no less."""
    event = make_event(2)
    with pytest.raises(ValueError):
        event.record_match({0: 100})  # missing archer 1
    with pytest.raises(ValueError):
        event.record_match({0: 100, 1: 60, 5: 10})  # extra, unknown archer


def test_bye_archer_recorded_with_no_winner_and_no_pairwise_result():
    """The bye archer's pass is recorded but produces no winner or pairwise result."""
    event = make_event(3, n_rotations=3)  # odd -> each rotation has one bye
    rotation = event.schedule[0]
    record_whole_rotation(event, score=50)

    bye_result = next(r for r in event.results if r.archer_index == rotation.bye)
    assert bye_result.won is None
    assert bye_result.opponent_index is None
    # The bye archer must not appear in any pairwise result derived from this rotation.
    for pr in event.all_pairwise_results():
        assert rotation.bye not in (pr.archer_a, pr.archer_b)


def test_pairwise_result_after_one_shared_pass():
    """After sharing one pass, the pair's pairwise result reflects that pass's winner."""
    event = make_event(2, n_pass=12)
    event.record_match({0: 120, 1: 0})  # archer 0 crushes archer 1
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
    record_whole_rotation(event)
    assert len(event.all_pairwise_results()) == len(rotation0.pairs)


def test_is_complete_only_once_the_final_rotation_is_fully_scored():
    """is_complete flips only when the last rotation is current and every match in it is scored."""
    event = make_event(4)  # 3 rotations, two matches each
    assert not event.is_complete
    for _ in range(2):  # score and advance past the first two rotations
        record_whole_rotation(event)
        assert not event.is_complete
        event.advance()
    assert not event.is_complete  # final rotation reached but unscored
    first, second = event.matches(2)
    event.record_match({p: 60 for p in first})
    assert not event.is_complete  # one of the two matches still unscored
    event.record_match({p: 60 for p in second})
    assert event.is_complete


def test_invalid_score_leaves_match_unrecorded():
    """An invalid score must not partially record the match."""
    event = make_event(2)
    with pytest.raises(ValueError):
        event.record_match({0: 100.5, 1: 50})
    assert event.results == []  # nothing recorded
    assert not event.is_rotation_complete(0)


def test_different_bowstyles_give_different_indoor_distributions():
    """Same handicap, different bowstyle (Recurve vs Compound) indoors -> different distributions."""
    archers = [
        Archer(name="R", handicap=20, bowstyle=Bowstyle.RECURVE),
        Archer(name="C", handicap=20, bowstyle=Bowstyle.COMPOUND),
    ]
    schedule = build_schedule(2, 1)
    event = Event(archers, 12, PORTSMOUTH, schedule)
    assert event.distribution_for(0) != event.distribution_for(1)


def test_longbow_gives_same_indoor_distribution_as_recurve():
    """Same handicap, Recurve vs Longbow indoors -> identical distributions (no scoring variant)."""
    archers = [
        Archer(name="R", handicap=20, bowstyle=Bowstyle.RECURVE),
        Archer(name="L", handicap=20, bowstyle=Bowstyle.LONGBOW),
    ]
    schedule = build_schedule(2, 1)
    event = Event(archers, 12, PORTSMOUTH, schedule)
    assert event.distribution_for(0) == event.distribution_for(1)


def test_outdoor_mode_gives_same_distribution_regardless_of_bowstyle():
    """Same handicap, different bowstyle, outdoor mode -> identical distributions."""
    archers = [
        Archer(name="R", handicap=20, bowstyle=Bowstyle.RECURVE),
        Archer(name="C", handicap=20, bowstyle=Bowstyle.COMPOUND),
    ]
    schedule = build_schedule(2, 1)
    event = Event(archers, 12, OUTDOOR_70M, schedule)
    assert event.distribution_for(0) == event.distribution_for(1)


# --- Per-match recording and explicit advance (Feedback 3) -----------------


def scores_for(match, score=60):
    """A {archer_index: score} dict covering one match from `Event.matches`."""
    return {p: score for p in match if p is not None}


def test_new_event_starts_at_rotation_zero():
    """A fresh Event is on the first rotation."""
    assert make_event(4).current_rotation_index == 0


def test_record_match_records_one_pair_without_scoring_the_rest():
    """Scoring one pair leaves the rotation's other matches unscored."""
    event = make_event(4)
    first, second = event.matches(0)
    results = event.record_match(scores_for(first))
    assert {r.archer_index for r in results} == set(first)
    assert event.is_match_scored(0, 0)
    assert not event.is_match_scored(0, 1)
    assert not event.is_rotation_complete(0)
    assert event.match_results(0, second) == []


def test_record_match_uses_each_archers_own_distribution():
    """Percentile/handicap come from each archer's OWN resolved target and distribution."""
    event = make_event(2)  # Archer0 Recurve, Archer1 Compound: different indoor targets
    results = {r.archer_index: r for r in event.record_match({0: 100, 1: 100})}
    for idx in (0, 1):
        assert results[idx].percentile == stats.percentile(event.distribution_for(idx), 100)
        assert results[idx].handicap == stats.equivalent_handicap(
            100, event.n_pass, event.target_for(idx)
        )
    assert results[0].percentile != results[1].percentile


def test_record_match_on_bye_archer_has_no_winner_or_pairwise_result():
    """A solo bye match records a result with no opponent/winner, and no pairwise entry."""
    event = make_event(3, n_rotations=3)
    pair, solo = event.matches(0)
    assert solo[1] is None
    (result,) = event.record_match({solo[0]: 50})
    assert result.opponent_index is None
    assert result.won is None
    assert event.all_pairwise_results() == []


def test_record_match_rejects_scores_that_are_not_exactly_one_match():
    """Mixed matches, partial pairs, unknown archers and sitting-out archers all raise."""
    event = make_event(4)
    first, second = event.matches(0)
    bad_inputs = [
        {first[0]: 50, second[0]: 50},  # archers from different matches
        {first[0]: 50},  # half a pair
        {**scores_for(first), 9: 50},  # extra, unknown archer
        {**scores_for(first), **scores_for(second)},  # two whole matches at once
        {},  # nothing
    ]
    for bad in bad_inputs:
        with pytest.raises(ValueError):
            event.record_match(bad)
    assert event.results == []


def test_record_match_rejects_a_sitting_out_archer():
    """An archer sitting this pass out has no match to record."""
    event = Event(make_archers(3), 12, PORTSMOUTH, build_sit_out_schedule(3, 2))
    (sitting,) = event.schedule[0].sitting_out
    with pytest.raises(ValueError):
        event.record_match({sitting: 50})
    assert event.results == []


@pytest.mark.parametrize("bad_score", [100.5, -1, 121])
def test_record_match_invalid_score_records_nothing(bad_score):
    """Non-integer, negative and over-maximum scores are rejected, recording nothing."""
    event = make_event(2)
    with pytest.raises(ValueError):
        event.record_match({0: bad_score, 1: 60})
    assert event.results == []


def test_re_recording_a_match_replaces_its_results_in_place():
    """Re-saving a match replaces (not duplicates) results, recomputes the winner, keeps order."""
    event = make_event(4)
    first, second = event.matches(0)
    event.record_match(scores_for(first, 60))
    event.record_match(scores_for(second, 60))
    positions = [(r.rotation_index, r.archer_index) for r in event.results]

    a, b = first
    event.record_match({a: 120, b: 0})
    assert event.pairwise_result(a, b).outcome == a
    event.record_match({a: 0, b: 120})

    assert len(event.results) == 4
    assert [(r.rotation_index, r.archer_index) for r in event.results] == positions
    assert {r.archer_index: r.score for r in event.match_results(0, first)} == {a: 0, b: 120}
    assert event.pairwise_result(a, b).outcome == b


def test_is_rotation_complete_only_once_every_match_is_scored():
    """A rotation is complete only when all its matches (incl. any bye match) have scores."""
    event = make_event(3, n_rotations=3)
    pair, solo = event.matches(0)
    assert not event.is_rotation_complete(0)
    event.record_match(scores_for(pair))
    assert not event.is_rotation_complete(0)
    event.record_match({solo[0]: 40})
    assert event.is_rotation_complete(0)


def test_advance_requires_a_complete_rotation_then_moves_on():
    """advance() is refused until the pass is fully scored, then applies to the next rotation."""
    event = make_event(2, n_rotations=2)  # the same pair meets twice
    with pytest.raises(ValueError):
        event.advance()
    assert event.current_rotation_index == 0

    event.record_match({0: 100, 1: 60})
    event.advance()
    assert event.current_rotation_index == 1

    results = event.record_match({0: 90, 1: 80})
    assert {r.rotation_index for r in results} == {1}


def test_advance_on_the_final_rotation_raises():
    """There is nothing to advance to after the last rotation."""
    event = make_event(2, n_rotations=1)
    event.record_match({0: 100, 1: 60})
    with pytest.raises(ValueError):
        event.advance()
    assert event.current_rotation_index == 0


def test_earlier_rotation_results_cannot_be_altered_after_advancing():
    """After advancing, record_match only ever touches the new current rotation."""
    event = make_event(2, n_rotations=2)
    event.record_match({0: 100, 1: 60})
    event.advance()
    event.record_match({0: 10, 1: 20})
    first_pass = [r for r in event.results if r.rotation_index == 0]
    assert {r.archer_index: r.score for r in first_pass} == {0: 100, 1: 60}


def test_event_accepts_a_sit_out_schedule_and_matches_exclude_sitting_archers():
    """A sit-out schedule builds an Event whose matches never include the sitting-out archer."""
    event = Event(make_archers(3), 12, PORTSMOUTH, build_sit_out_schedule(3, 2))
    for i, rotation in enumerate(event.schedule):
        in_matches = {p for m in event.matches(i) for p in m if p is not None}
        assert in_matches.isdisjoint(rotation.sitting_out)
        assert all(b is not None for _, b in event.matches(i))  # nobody shoots alone


def test_schedule_sitting_out_index_out_of_range_rejected():
    """A sitting_out index beyond len(archers) must raise, like any other schedule index."""
    schedule = [Rotation(pairs=[(0, 1)], sitting_out=(5,))]
    with pytest.raises(ValueError):
        Event(make_archers(2), 12, PORTSMOUTH, schedule)


def test_pair_results_lists_every_shared_pass_in_order():
    """pair_results returns both archers' results for each shared pass, oldest pass first."""
    event = make_event(2, n_rotations=2)  # the same pair meets in both rotations
    assert event.pair_results(0, 1) == []
    event.record_match({0: 100, 1: 60})
    event.advance()
    event.record_match({0: 90, 1: 80})

    shared = event.pair_results(0, 1)
    assert [(r.rotation_index, r.archer_index, r.score) for r in shared] == [
        (0, 0, 100),
        (0, 1, 60),
        (1, 0, 90),
        (1, 1, 80),
    ]
    assert event.pair_results(1, 0) == shared  # argument order does not matter


def test_pair_results_excludes_other_pairs_and_bye_matches():
    """Only the requested pair's own head-to-head results are returned."""
    event = make_event(3, n_rotations=3)
    record_whole_rotation(event)
    (a, b), (bye, _) = event.matches(0)
    shared = event.pair_results(a, b)
    assert {r.archer_index for r in shared} == {a, b}
    assert all(r.opponent_index is not None for r in shared)
    assert event.pair_results(a, bye) == []


def test_event_resolves_targets_from_a_non_default_target_setup():
    """The Event stores its TargetSetup and gives every archer that distance and face."""
    setup = TargetSetup(distance=40, unit=YARD, face_cm=80)
    event = make_event(2, target_setup=setup)
    assert event.target_setup == setup
    for i in (0, 1):
        target = event.target_for(i)
        assert target.diameter == pytest.approx(0.8)
        assert target.distance == pytest.approx(setup.distance_m)
        assert target.indoor is False


def test_outdoor_compound_and_recurve_share_a_distribution_but_indoor_ones_differ():
    """Compound's reduced 10 only matters at an indoor distance (Assumption 23)."""
    pair = [
        Archer(name="R", handicap=20, bowstyle=Bowstyle.RECURVE),
        Archer(name="C", handicap=20, bowstyle=Bowstyle.COMPOUND),
    ]
    schedule = build_schedule(2, 1)
    for setup, identical in ((TargetSetup(50, METRE, 80), True), (TargetSetup(25, METRE, 60), False)):
        event = Event(pair, 12, setup, schedule)
        assert (event.distribution_for(0) == event.distribution_for(1)) is identical


# --- Feedback 5: tie-break (percentile, then score, then closest to the middle) ----


def make_tied_event(n_pass=12):
    """A 2-archer event whose archers have the same handicap, bowstyle and target.

    Any equal scores for the two give an exact tie in percentile and score.
    """
    archers = [Archer(f"T{i}", 30, Bowstyle.RECURVE) for i in range(2)]
    return Event(archers, n_pass, PORTSMOUTH, build_schedule(2, 1))


def test_a_tied_match_without_a_closest_archer_raises_and_records_nothing():
    """Same handicap, target and score: a tie that needs the closest-to-the-middle archer."""
    event = make_tied_event()
    with pytest.raises(stats.TieBreakRequired):
        event.record_match({0: 90, 1: 90})
    assert event.results == []
    assert not event.is_rotation_complete(0)


@pytest.mark.parametrize("closest", [0, 1])
def test_a_tied_match_is_decided_by_the_closest_archer(closest):
    """Exactly the ticked archer wins, and the result says how it was decided."""
    event = make_tied_event()
    results = {r.archer_index: r for r in event.record_match({0: 90, 1: 90}, closest=closest)}
    assert results[closest].won is True
    assert results[1 - closest].won is False
    assert {r.decided_by for r in results.values()} == {"closest"}
    assert event.pairwise_result(0, 1).outcome == closest


def test_a_closest_archer_who_is_not_in_the_match_is_rejected():
    """closest must be one of the two archers; nothing is recorded otherwise."""
    event = make_tied_event()
    with pytest.raises(ValueError):
        event.record_match({0: 90, 1: 90}, closest=5)
    assert event.results == []


def test_results_record_which_step_decided_them():
    """decided_by is 'percentile' when percentiles differ and 'score' when only scores do."""
    event = make_event(2)
    results = event.record_match({0: 110, 1: 60})
    assert {r.decided_by for r in results} == {"percentile"}


def test_a_closest_archer_is_ignored_when_percentile_or_score_decides():
    """The tick is not stored (decided_by stays percentile) and cannot override the winner."""
    event = make_event(2)
    results = {r.archer_index: r for r in event.record_match({0: 110, 1: 60}, closest=1)}
    assert results[0].won is True
    assert results[0].decided_by == results[1].decided_by == "percentile"


def test_resaving_a_tied_match_with_the_other_closest_archer_replaces_the_winner():
    """The tick can be corrected like any score until the pass is advanced."""
    event = make_tied_event()
    event.record_match({0: 90, 1: 90}, closest=0)
    event.record_match({0: 90, 1: 90}, closest=1)
    assert len(event.results) == 2
    assert {r.archer_index for r in event.results if r.won} == {1}


def test_resaving_a_tied_match_with_scores_that_no_longer_tie_drops_the_tick():
    """With different scores the better one wins and the result is no longer 'closest'."""
    event = make_tied_event()
    event.record_match({0: 90, 1: 90}, closest=0)
    results = {r.archer_index: r for r in event.record_match({0: 90, 1: 95}, closest=0)}
    assert results[1].won is True
    assert {r.decided_by for r in results.values()} == {"percentile"}


def test_equal_percentiles_at_the_top_end_are_decided_by_score_not_rounding_noise():
    """Handicap-150 archers' near-impossible high scores all sit at ~100%: the score decides."""
    archers = [Archer(f"H{i}", 150, Bowstyle.RECURVE) for i in range(2)]
    event = Event(archers, 12, PORTSMOUTH, build_schedule(2, 1))
    results = {r.archer_index: r for r in event.record_match({0: 100, 1: 90})}
    assert results[0].won is True
    assert {r.decided_by for r in results.values()} == {"score"}


def test_resaving_a_match_as_a_tie_without_a_tick_keeps_the_earlier_result():
    """A rejected re-save leaves what was saved before untouched."""
    event = make_tied_event()
    event.record_match({0: 90, 1: 95})
    before = list(event.results)
    with pytest.raises(stats.TieBreakRequired):
        event.record_match({0: 90, 1: 90})
    assert event.results == before


def test_a_bye_match_has_no_tie_break_and_ignores_closest():
    """A solo bye has nothing to tie with: decided_by is None and a closest value is ignored."""
    event = make_event(3, n_rotations=3)
    _, solo = event.matches(0)
    (result,) = event.record_match({solo[0]: 50}, closest=solo[0])
    assert result.won is None
    assert result.decided_by is None
