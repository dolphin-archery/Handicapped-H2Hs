"""Tests for updating handicaps during an event (Event.handicap_for, AISpec.md section 5.2c)."""

import pytest

from h2h import stats
from h2h.models import MAX_HANDICAP, YARD, Archer, Bowstyle, Event, TargetSetup
from h2h.rotation import build_schedule, build_sit_out_schedule

from .helpers import PORTSMOUTH


def make_pair_event(rotations=4, handicaps=(30, 40), update=True, n_lookback=1, start_weight=5, n_pass=12):
    """Two Recurve archers who meet every pass, with handicap updating as given."""
    archers = [Archer(f"A{i}", h, Bowstyle.RECURVE) for i, h in enumerate(handicaps)]
    return Event(
        archers, n_pass, PORTSMOUTH, build_schedule(2, rotations),
        update_handicaps=update, n_lookback=n_lookback, start_weight=start_weight,
    )


def score_passes(event, scores):
    """Record each pass's (score_0, score_1) in turn, advancing between passes."""
    for i, (s0, s1) in enumerate(scores):
        event.record_match({0: s0, 1: s1})
        if i < len(scores) - 1:
            event.advance()


def recent_handicap(event, archer, scores):
    """The equivalent handicap of a list of pass scores over len(scores) passes, as the model uses."""
    return stats.equivalent_handicap(sum(scores), len(scores) * event.n_pass, event.target_for(archer))


def weighted(entered, weight, recent, m):
    """(weight x entered + m x recent) / (weight + m)."""
    return (weight * entered + m * recent) / (weight + m)


# --- off: nothing changes --------------------------------------------------------------


def test_with_updating_off_the_handicap_is_always_the_entered_one_and_the_distribution_is_unchanged():
    """handicap_for ignores results; distribution_for equals the plain per-handicap distribution."""
    event = make_pair_event(update=False, n_lookback=None, start_weight=None)
    score_passes(event, [(80, 100), (70, 90), (60, 95)])
    for rotation in range(4):
        assert event.handicap_for(0, rotation) == 30 and event.handicap_for(1, rotation) == 40
    plain = stats.n_pass_score_distribution(stats.per_arrow_pmf(30, event.target_for(0)), 12)
    assert event.distribution_for(0) == plain
    assert event.distribution_for(0, 2) == plain


def test_the_settings_are_ignored_when_updating_is_off_even_if_they_are_invalid():
    """No ValueError for nonsense settings while updating is off, and they are not kept."""
    archers = [Archer("A", 30, Bowstyle.RECURVE), Archer("B", 40, Bowstyle.RECURVE)]
    event = Event(archers, 12, PORTSMOUTH, build_schedule(2, 1), update_handicaps=False,
                  n_lookback=0, start_weight=-3)
    assert event.update_handicaps is False and event.n_lookback is None and event.start_weight is None


# --- the formula ---------------------------------------------------------------------------


def test_before_pass_1_the_handicap_is_the_entered_one_and_before_pass_2_it_is_the_weighted_average():
    """n_lookback 1, start weight 5: (5 x H0 + 1 x H_pass1) / 6."""
    event = make_pair_event(n_lookback=1, start_weight=5)
    assert event.handicap_for(0) == 30 and event.handicap_for(1) == 40
    score_passes(event, [(80, 100)])
    event.advance()
    assert event.current_rotation_index == 1
    for archer, score in ((0, 80), (1, 100)):
        recent = recent_handicap(event, archer, [score])
        entered = event.archers[archer].handicap
        assert event.handicap_for(archer) == pytest.approx(weighted(entered, 5, recent, 1))
    assert event.handicap_for(0) > 30  # a poor pass raised (worsened) the handicap


def test_only_the_last_n_lookback_passes_are_used():
    """n_lookback 2, start weight 3, three scored passes: before pass 4 the first pass is not used."""
    event = make_pair_event(n_lookback=2, start_weight=3)
    score_passes(event, [(70, 100), (90, 95), (100, 105)])
    event.advance()
    recent = recent_handicap(event, 0, [90, 100])  # the last two scores over 24 arrows
    assert event.handicap_for(0) == pytest.approx(weighted(30, 3, recent, 2))
    with_first = recent_handicap(event, 0, [70, 90, 100])
    assert recent != with_first  # the discarded first pass would have mattered


def test_fewer_passes_than_n_lookback_uses_every_pass_shot():
    """n_lookback 5 with only two passes scored: m = 2."""
    event = make_pair_event(n_lookback=5, start_weight=4)
    score_passes(event, [(80, 100), (95, 100)])
    event.advance()
    recent = recent_handicap(event, 0, [80, 95])
    assert event.handicap_for(0) == pytest.approx(weighted(30, 4, recent, 2))


def test_when_both_settings_equal_the_passes_per_archer_every_arrow_so_far_is_used():
    """The defaults of Stage 2 (both = passes per archer): all passes so far, start counted as that many."""
    event = make_pair_event(rotations=5, n_lookback=5, start_weight=5)
    score_passes(event, [(90, 100), (95, 100), (100, 100)])
    event.advance()
    recent = recent_handicap(event, 0, [90, 95, 100])
    assert event.handicap_for(0) == pytest.approx(weighted(30, 5, recent, 3))


def test_a_zero_total_counts_as_the_maximum_handicap_and_the_result_stays_in_range():
    """A total of 0 has no equivalent handicap: 150 is used, and the average is within 0-150."""
    event = make_pair_event(handicaps=(140, 40), n_lookback=1, start_weight=1)
    score_passes(event, [(0, 100)])
    event.advance()
    assert event.handicap_for(0) == pytest.approx((1 * 140 + 1 * MAX_HANDICAP) / 2)
    for rotation in range(2):
        for archer in (0, 1):
            assert 0 <= event.handicap_for(archer, rotation) <= MAX_HANDICAP
    event = make_pair_event(handicaps=(150, 150), n_lookback=1, start_weight=1)
    score_passes(event, [(0, 0 + 1)])
    event.advance()
    assert event.handicap_for(0) == MAX_HANDICAP  # 150 averaged with 150 stays at 150, not above


def test_a_very_good_pass_cannot_push_the_handicap_below_zero():
    """The weighted average is clamped at 0 even with a tiny starting handicap and a perfect pass."""
    event = make_pair_event(handicaps=(0, 0), n_lookback=1, start_weight=1)
    score_passes(event, [(120, 119)])
    event.advance()
    assert 0 <= event.handicap_for(0) <= MAX_HANDICAP and 0 <= event.handicap_for(1) <= MAX_HANDICAP


# --- which passes count -------------------------------------------------------------------------


def test_a_sat_out_pass_adds_nothing_and_a_bye_pass_counts():
    """j counts passes an archer scored: a sit-out is not one, a solo bye is."""
    archers = [Archer(f"S{i}", 30 + 5 * i, Bowstyle.RECURVE) for i in range(3)]
    sit = Event(archers, 12, PORTSMOUTH, build_sit_out_schedule(3, 3),
                update_handicaps=True, n_lookback=3, start_weight=3)
    sitter = sit.schedule[0].sitting_out[0]
    for match in sit.matches(0):
        sit.record_match({p: 90 + p for p in match if p is not None})
    sit.advance()
    assert sit.handicap_for(sitter) == sit.archers[sitter].handicap  # nothing shot yet

    byes = Event(archers, 12, PORTSMOUTH, build_schedule(3, 3),
                 update_handicaps=True, n_lookback=3, start_weight=3)
    bye_archer = byes.schedule[0].bye
    for match in byes.matches(0):
        byes.record_match({p: 90 + p for p in match if p is not None})
    byes.advance()
    recent = recent_handicap(byes, bye_archer, [90 + bye_archer])
    entered = byes.archers[bye_archer].handicap
    assert byes.handicap_for(bye_archer) == pytest.approx(weighted(entered, 3, recent, 1))


def test_each_archer_uses_their_own_targets_equivalent_handicap():
    """A 5-zone and a 10-zone archer with the same score get different recent handicaps."""
    archers = [
        Archer("Ten", 30, Bowstyle.RECURVE, target_setup=TargetSetup(20, YARD, 60, "10_zone")),
        Archer("Five", 30, Bowstyle.RECURVE, target_setup=TargetSetup(20, YARD, 60, "5_zone")),
    ]
    event = Event(archers, 12, None, build_schedule(2, 2),
                  update_handicaps=True, n_lookback=1, start_weight=2)
    event.record_match({0: 100, 1: 100})
    event.advance()
    ten = weighted(30, 2, recent_handicap(event, 0, [100]), 1)
    five = weighted(30, 2, recent_handicap(event, 1, [100]), 1)
    assert event.handicap_for(0) == pytest.approx(ten) and event.handicap_for(1) == pytest.approx(five)
    assert ten != pytest.approx(five)


# --- dependence on earlier passes only ------------------------------------------------------------


def test_correcting_the_current_passes_scores_never_changes_its_handicap():
    """The handicap for a pass comes from earlier passes, so re-saving the pass leaves it alone."""
    event = make_pair_event(n_lookback=1, start_weight=5)
    score_passes(event, [(80, 100)])
    event.advance()
    before = (event.handicap_for(0), event.handicap_for(1))
    event.record_match({0: 100, 1: 90})
    assert (event.handicap_for(0), event.handicap_for(1)) == before
    event.record_match({0: 60, 1: 118})  # corrected again
    assert (event.handicap_for(0), event.handicap_for(1)) == before


def test_a_recorded_percentile_keeps_the_handicap_it_was_scored_with():
    """Pass 1's percentile is unchanged by what happens later, and uses the entered handicap."""
    event = make_pair_event(n_lookback=1, start_weight=5)
    event.record_match({0: 100, 1: 95})
    first = [r.percentile for r in event.results if r.rotation_index == 0]
    expected = stats.percentile(
        stats.n_pass_score_distribution(stats.per_arrow_pmf(30, event.target_for(0)), 12), 100
    )
    assert first[0] == pytest.approx(expected)
    event.advance()
    event.record_match({0: 70, 1: 118})
    assert [r.percentile for r in event.results if r.rotation_index == 0] == first


def test_percentile_and_distribution_for_a_later_pass_use_the_updated_handicap():
    """After a poor pass, the same score has a different (higher) percentile than with updating off."""
    updating = make_pair_event(n_lookback=1, start_weight=2)
    constant = make_pair_event(update=False, n_lookback=None, start_weight=None)
    for event in (updating, constant):
        event.record_match({0: 80, 1: 100})
        event.advance()
        event.record_match({0: 100, 1: 100 - 1})
    pass_2 = lambda event: next(  # noqa: E731
        r for r in event.results if r.rotation_index == 1 and r.archer_index == 0
    )
    assert pass_2(updating).percentile > pass_2(constant).percentile
    assert updating.distribution_for(0, 1) != constant.distribution_for(0, 1)
    assert updating.distribution_for(0, 0) == constant.distribution_for(0, 0)  # pass 1 is the same


# --- validation --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("n_lookback", "start_weight"),
    [(0, 5), (5, 0), (-1, 5), (5, -2), (2.5, 5), (5, 1.5), ("3", 5), (None, 5), (5, None), (True, 5)],
)
def test_invalid_settings_raise_when_updating_is_on(n_lookback, start_weight):
    """Both must be whole numbers of at least 1."""
    archers = [Archer("A", 30, Bowstyle.RECURVE), Archer("B", 40, Bowstyle.RECURVE)]
    with pytest.raises(ValueError):
        Event(archers, 12, PORTSMOUTH, build_schedule(2, 1), update_handicaps=True,
              n_lookback=n_lookback, start_weight=start_weight)


def test_the_smallest_valid_settings_are_accepted():
    """1 and 1 are fine."""
    event = make_pair_event(n_lookback=1, start_weight=1)
    assert event.n_lookback == 1 and event.start_weight == 1
