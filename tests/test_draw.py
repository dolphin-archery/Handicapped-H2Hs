"""Tests for h2h.draw: the Stage 3 draw of archers to schedule positions (UISpec.md D17)."""

import ast
import random
from pathlib import Path

import pytest

from h2h import draw
from h2h.draw import draw_assignment, pairings_signature
from h2h.models import Archer, Bowstyle
from h2h.rotation import Rotation, build_schedule, build_sit_out_schedule
from h2h.state import SessionState

from .helpers import PORTSMOUTH


class CountingRandom(random.Random):
    """A seeded random source that counts its `shuffle` calls."""

    def __init__(self, seed):
        super().__init__(seed)
        self.shuffles = 0

    def shuffle(self, x):
        """Shuffle as `random.Random` does, counting the call."""
        self.shuffles += 1
        super().shuffle(x)


def _session(n_archers, total_arrows, seed, shoot_byes=True):
    """A SessionState at Stage 3 with `n_archers` entered and a seeded random source."""
    state = SessionState(rng=random.Random(seed))
    state.start_stage1(n_archers, total_arrows, 12, PORTSMOUTH, shoot_byes)
    state.start_stage2(
        [Archer(name=f"A{i}", handicap=20 + i, bowstyle=Bowstyle.RECURVE) for i in range(n_archers)]
    )
    return state


def test_draw_imports_no_flask():
    """draw.py is importable without Flask (it runs in the browser)."""
    tree = ast.parse(Path(draw.__file__).read_text(encoding="utf-8"))
    modules = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    modules += [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not any(m.split(".")[0] == "flask" for m in modules)
    assert "state" not in modules


@pytest.mark.parametrize("n_archers", [2, 3, 4, 5, 8, 11])
@pytest.mark.parametrize("seed", range(5))
def test_a_draw_is_a_permutation_of_the_archers(n_archers, seed):
    """Every archer fills exactly one position, on a first draw and on a redraw."""
    schedule = build_schedule(n_archers, 5)
    rng = random.Random(seed)
    first = draw_assignment(schedule, n_archers, rng)
    assert sorted(first) == list(range(n_archers))
    assert sorted(draw_assignment(schedule, n_archers, rng, first)) == list(range(n_archers))


def test_the_first_draw_is_one_shuffle():
    """With no current assignment, the first shuffle is taken as it is."""
    rng = CountingRandom(3)
    draw_assignment(build_schedule(4, 5), 4, rng)
    assert rng.shuffles == 1


@pytest.mark.parametrize(
    "schedule",
    [build_schedule(4, 3), build_schedule(6, 5), build_schedule(5, 5), build_sit_out_schedule(5, 5)],
    ids=["4-archers", "6-archers", "5-byes-shot", "5-sitting-out"],
)
def test_a_redraw_changes_the_pairings_when_it_can(schedule):
    """With more than two archers, every redraw gives pairings that differ from the current ones."""
    n_archers = 1 + max(
        p for r in schedule for p in (*[a for pair in r.pairs for a in pair], *r.sitting_out)
    )
    rng = random.Random(1)
    current = draw_assignment(schedule, n_archers, rng)
    for _ in range(25):
        new = draw_assignment(schedule, n_archers, rng, current)
        assert pairings_signature(schedule, new) != pairings_signature(schedule, current)
        current = new


def test_a_redraw_with_two_archers_gives_up_after_the_attempt_limit():
    """Two archers have only one pairing: the redraw tries the limit, then keeps a valid draw."""
    schedule = build_schedule(2, 5)
    rng = CountingRandom(1)
    result = draw_assignment(schedule, 2, rng, [0, 1])
    assert sorted(result) == [0, 1]
    assert rng.shuffles == draw._MAX_REDRAW_ATTEMPTS


def test_the_signature_ignores_the_order_within_a_pair_but_not_who_meets_whom():
    """Swapping the two archers of a pair is the same draw; changing an opponent is not."""
    schedule = [Rotation(pairs=[(0, 1), (2, 3)])]
    assert pairings_signature(schedule, [0, 1, 2, 3]) == pairings_signature(schedule, [1, 0, 3, 2])
    assert pairings_signature(schedule, [0, 1, 2, 3]) != pairings_signature(schedule, [0, 2, 1, 3])


def test_giving_another_archer_the_bye_or_the_sit_out_is_a_different_draw():
    """A draw that changes who has the bye, or who sits out, has a different signature.

    (Within a rotation everyone not in a pair has the bye or sits out, so the pairs alone
    already tell these draws apart.)
    """
    bye = [Rotation(pairs=[(0, 1)], bye=2)]
    assert pairings_signature(bye, [0, 1, 2]) != pairings_signature(bye, [2, 1, 0])
    sit = [Rotation(pairs=[(0, 1)], sitting_out=(2,))]
    assert pairings_signature(sit, [0, 1, 2]) != pairings_signature(sit, [2, 1, 0])


@pytest.mark.parametrize(
    ("n_archers", "total_arrows", "shoot_byes"),
    [(2, 12, True), (4, 60, True), (5, 60, True), (5, 60, False), (8, 84, True)],
)
@pytest.mark.parametrize("seed", [0, 1, 42])
def test_the_same_seed_gives_the_same_draws_through_the_session_and_directly(
    n_archers, total_arrows, shoot_byes, seed
):
    """SessionState's draw and redraws equal the function's, called with the same seeded source."""
    state = _session(n_archers, total_arrows, seed, shoot_byes)
    rng = random.Random(seed)
    expected = draw_assignment(state.schedule, n_archers, rng)
    assert state.assignment == expected
    for _ in range(3):
        state.redraw_pairings()
        expected = draw_assignment(state.schedule, n_archers, rng, expected)
        assert state.assignment == expected
