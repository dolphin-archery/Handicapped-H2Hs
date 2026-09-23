"""Tests for h2h.rotation (round-robin scheduling)."""

import pytest

from h2h.rotation import build_schedule


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
