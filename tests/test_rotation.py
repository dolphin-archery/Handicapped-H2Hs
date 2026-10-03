"""Tests for h2h.rotation (round-robin scheduling)."""

import pytest

from h2h.rotation import Rotation, build_schedule, build_sit_out_schedule


def _all_pairs_covered(schedule, n_archers):
    """Every possible archer pair appears in `schedule`, each exactly once."""
    seen = []
    for rotation in schedule:
        seen.extend(tuple(sorted(p)) for p in rotation.pairs)
    expected = {
        tuple(sorted((i, j))) for i in range(n_archers) for j in range(n_archers) if i < j
    }
    return sorted(seen) == sorted(expected)


@pytest.mark.parametrize("n_archers", [4, 6, 8])
def test_even_n_archers_full_coverage_no_byes(n_archers):
    """Even n_archers: full round-robin, every pair once, no byes."""
    schedule = build_schedule(n_archers, n_archers - 1)
    assert len(schedule) == n_archers - 1
    assert all(r.bye is None for r in schedule)
    assert _all_pairs_covered(schedule, n_archers)


@pytest.mark.parametrize("n_archers", [3, 5, 7])
def test_odd_n_archers_full_coverage_one_bye_each(n_archers):
    """Odd n_archers: n_archers rotations, each with one bye, full coverage."""
    schedule = build_schedule(n_archers, n_archers)
    assert len(schedule) == n_archers
    byes = [r.bye for r in schedule]
    assert sorted(byes) == list(range(n_archers))  # each archer gets exactly one bye
    assert _all_pairs_covered(schedule, n_archers)


@pytest.mark.parametrize("n_archers", [4, 5, 6, 7, 8])
def test_no_self_pairing_or_duplicate_within_rotation(n_archers):
    """No archer is paired with themselves, or appears twice in one rotation."""
    schedule = build_schedule(n_archers, n_archers)
    for rotation in schedule:
        participants = [p for pair in rotation.pairs for p in pair]
        if rotation.bye is not None:
            participants.append(rotation.bye)
        assert len(participants) == len(set(participants))
        for a, b in rotation.pairs:
            assert a != b


def test_truncated_schedule_is_a_prefix_of_the_full_schedule():
    """Fewer rotations than a full round-robin needs gives a truncated prefix."""
    full = build_schedule(6, 5)
    truncated = build_schedule(6, 2)
    assert truncated == full[:2]


def test_cycled_schedule_repeats_from_the_start():
    """More rotations than a full round-robin needs repeats the schedule."""
    full = build_schedule(4, 3)
    cycled = build_schedule(4, 7)
    assert len(cycled) == 7
    assert cycled == full + full + full[:1]


def test_two_archers_single_pair_no_bye():
    """n_archers=2 produces one rotation, one pair, no bye."""
    schedule = build_schedule(2, 1)
    assert len(schedule) == 1
    assert schedule[0].bye is None
    assert schedule[0].pairs == [(0, 1)]


def test_rejects_too_few_archers():
    """n_archers < 2 is invalid."""
    with pytest.raises(ValueError):
        build_schedule(1, 1)


def test_rejects_negative_rotations():
    """A negative rotation count is invalid."""
    with pytest.raises(ValueError):
        build_schedule(4, -1)


def test_zero_rotations_gives_empty_schedule():
    """Requesting zero rotations is valid and gives an empty schedule."""
    assert build_schedule(4, 0) == []


ODD_CASES = [(n, p) for n in (3, 5, 7, 9) for p in range(1, 13)]


def _shots(schedule, n_archers):
    """Passes shot by each archer: the number of matches they appear in, over all rotations."""
    counts = [0] * n_archers
    for rotation in schedule:
        for match in rotation.matches:
            for archer in match:
                if archer is not None:
                    counts[archer] += 1
    return counts


def _main_rotation_count(n_archers, passes_per_archer):
    """Largest R with R - R // n_archers <= passes_per_archer (the pre-catch-up rotation count)."""
    candidates = range(passes_per_archer * n_archers + 1)
    return max(r for r in candidates if r - r // n_archers <= passes_per_archer)


def test_rotation_matches_lists_pairs_then_the_bye_match():
    """Rotation.matches is the pairs plus (bye, None) when there is a bye, else just the pairs."""
    assert Rotation(pairs=[(0, 1), (2, 3)], bye=4).matches == [(0, 1), (2, 3), (4, None)]
    assert Rotation(pairs=[(0, 1), (2, 3)]).matches == [(0, 1), (2, 3)]
    assert Rotation(pairs=[(0, 1)], sitting_out=(2,)).matches == [(0, 1)]


def test_rotation_sitting_out_defaults_to_empty_and_build_schedule_is_unchanged():
    """sitting_out defaults to () and build_schedule rotations never use it."""
    assert Rotation(pairs=[(0, 1)]).sitting_out == ()
    assert all(r.sitting_out == () for r in build_schedule(5, 5))
    assert all(r.matches[-1] == (r.bye, None) for r in build_schedule(5, 5))


@pytest.mark.parametrize(("n_archers", "passes"), ODD_CASES)
def test_sit_out_everyone_shoots_at_least_p_and_at_most_one_shoots_extra(n_archers, passes):
    """Odd n_archers: everyone shoots >= P passes, at most one archer shoots P + 1, none more."""
    counts = _shots(build_sit_out_schedule(n_archers, passes), n_archers)
    assert min(counts) >= passes
    assert max(counts) <= passes + 1
    assert counts.count(passes + 1) <= 1


@pytest.mark.parametrize(
    ("n_archers", "passes", "n_rotations"),
    [(5, 4, 5), (5, 5, 7), (3, 5, 8), (3, 1, 2), (7, 5, 6)],
)
def test_sit_out_known_rotation_counts(n_archers, passes, n_rotations):
    """Known (n_archers, P) cases give the expected number of rotations."""
    assert len(build_sit_out_schedule(n_archers, passes)) == n_rotations


def test_sit_out_five_archers_four_passes_gives_everyone_exactly_four():
    """5 archers x 4 passes needs no catch-up: everyone shoots exactly 4."""
    assert _shots(build_sit_out_schedule(5, 4), 5) == [4] * 5


def test_sit_out_five_archers_five_passes_has_one_archer_on_six():
    """5 archers x 5 passes: 4 archers shoot 5 and one shoots 6 (AISpec Assumption 15 example)."""
    assert sorted(_shots(build_sit_out_schedule(5, 5), 5)) == [5, 5, 5, 5, 6]


@pytest.mark.parametrize(("n_archers", "passes"), ODD_CASES)
def test_sit_out_rotation_structure(n_archers, passes):
    """No bye, no self/duplicate archer, and sitting_out + matched archers cover everyone once."""
    for rotation in build_sit_out_schedule(n_archers, passes):
        assert rotation.bye is None
        assert all(a != b for a, b in rotation.pairs)
        matched = [a for pair in rotation.pairs for a in pair]
        assert sorted([*matched, *rotation.sitting_out]) == list(range(n_archers))


@pytest.mark.parametrize(("n_archers", "passes"), ODD_CASES)
def test_sit_out_catch_up_has_only_short_archers_plus_at_most_one_complete(n_archers, passes):
    """The catch-up rotation (if any) is the short archers plus at most one complete partner."""
    schedule = build_sit_out_schedule(n_archers, passes)
    n_main = _main_rotation_count(n_archers, passes)
    main, catch_up = schedule[:n_main], schedule[n_main:]
    short = {a for a, c in enumerate(_shots(main, n_archers)) if c == passes - 1}
    if not short:
        assert catch_up == []
        return
    assert len(catch_up) == 1
    shooters = {a for pair in catch_up[0].pairs for a in pair}
    assert short <= shooters
    assert len(shooters - short) == len(short) % 2  # a partner only when the short count is odd


@pytest.mark.parametrize(("n_archers", "passes"), [(5, 1), (7, 3), (9, 3), (9, 5), (9, 8)])
def test_sit_out_catch_up_avoids_repeat_opponents_when_possible(n_archers, passes):
    """In cases where it is possible, the catch-up pairs have not already met in the main rotations."""
    schedule = build_sit_out_schedule(n_archers, passes)
    main, catch_up = schedule[:-1], schedule[-1]
    faced = {frozenset(pair) for r in main for pair in r.pairs}
    assert catch_up.pairs
    assert all(frozenset(pair) not in faced for pair in catch_up.pairs)


def test_sit_out_catch_up_partner_is_the_complete_archer_who_faced_fewest_short_archers():
    """9 archers x 5 passes: the odd short count takes archer 8 as partner, not the lowest complete archer."""
    catch_up = build_sit_out_schedule(9, 5)[-1]
    assert catch_up.pairs == [(0, 1), (3, 5), (7, 8)]
    assert catch_up.sitting_out == (2, 4, 6)


@pytest.mark.parametrize(("n_archers", "passes"), [(2, 1), (4, 3), (4, 7), (6, 5), (8, 2)])
def test_sit_out_even_n_archers_matches_build_schedule(n_archers, passes):
    """An even n_archers returns exactly build_schedule(n_archers, passes)."""
    assert build_sit_out_schedule(n_archers, passes) == build_schedule(n_archers, passes)


@pytest.mark.parametrize(("n_archers", "passes"), [(1, 3), (0, 3), (5, 0), (5, -1), (4, 0)])
def test_sit_out_rejects_invalid_inputs(n_archers, passes):
    """n_archers < 2 or passes_per_archer < 1 raises ValueError."""
    with pytest.raises(ValueError):
        build_sit_out_schedule(n_archers, passes)
