"""Tests for h2h.models (Archer/Pass/Match/Round orchestration)."""

import pytest

from h2h.models import Archer, Match


def make_archers():
    """Two archers of clearly different skill for use across tests."""
    strong = Archer(name="Strong", handicap=10)
    weak = Archer(name="Weak", handicap=60)
    return strong, weak


def test_invalid_n_pass_raises():
    """An n_pass that does not divide 60 evenly must be rejected."""
    strong, weak = make_archers()
    with pytest.raises(ValueError):
        Match(strong, weak, n_pass=7)


def test_n_pass_12_gives_5_passes():
    """n_pass=12 on a 60-arrow round must produce exactly 5 passes."""
    strong, weak = make_archers()
    match = Match(strong, weak, n_pass=12)
    assert len(match.passes) == 5


def test_recording_pass_updates_tally():
    """Recording a pass score updates the running pass-win tally."""
    strong, weak = make_archers()
    match = Match(strong, weak, n_pass=12)
    match.record_pass(0, score_a=118, score_b=60)
    wins_a, wins_b = match.pass_wins
    assert wins_a + wins_b == 1
    assert match.passes[0].winner in ("a", "b")


def test_strict_majority_wins_match():
    """An archer who wins a strict majority of passes is the overall winner."""
    strong, weak = make_archers()
    match = Match(strong, weak, n_pass=12)
    # Strong archer heavily outperforms their own distribution every pass;
    # weak archer scores at/below their own mean every pass.
    for i in range(5):
        match.record_pass(i, score_a=120, score_b=1)
    assert match.is_complete
    assert match.result() == "a"


def test_even_split_is_a_draw():
    """An even split of pass wins (even pass count) is reported as a draw."""
    strong, weak = make_archers()
    match = Match(strong, weak, n_pass=10)  # 6 passes -> even split possible
    assert len(match.passes) == 6
    # Alternate: strong wins passes 0,2,4; weak wins passes 1,3,5.
    for i in range(6):
        if i % 2 == 0:
            match.record_pass(i, score_a=100, score_b=1)
        else:
            match.record_pass(i, score_a=1, score_b=100)
    assert match.pass_wins == (3, 3)
    assert match.result() == "draw"


def test_result_before_complete_raises():
    """Requesting a result before every pass is scored must raise."""
    strong, weak = make_archers()
    match = Match(strong, weak, n_pass=12)
    with pytest.raises(RuntimeError):
        match.result()
