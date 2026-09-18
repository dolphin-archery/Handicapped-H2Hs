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


# --- Feedback 1: score validation ---------------------------------------


def test_negative_score_is_rejected():
    """A score below 0 must be rejected and must not record anything."""
    strong, weak = make_archers()
    match = Match(strong, weak, n_pass=12)
    with pytest.raises(ValueError):
        match.record_pass(0, score_a=-1, score_b=50)
    assert not match.passes[0].is_scored


def test_score_above_max_is_rejected():
    """A score above n_pass * MAX_SCORE_PER_ARROW must be rejected."""
    strong, weak = make_archers()
    match = Match(strong, weak, n_pass=12)  # max possible = 120
    with pytest.raises(ValueError):
        match.record_pass(0, score_a=121, score_b=50)
    assert not match.passes[0].is_scored


def test_non_integer_score_is_rejected():
    """A non-whole-number score must be rejected."""
    strong, weak = make_archers()
    match = Match(strong, weak, n_pass=12)
    with pytest.raises(ValueError):
        match.record_pass(0, score_a=100.5, score_b=50)


def test_whole_number_float_score_is_accepted_and_stored_as_int():
    """A score like 100.0 is accepted and stored as a plain int."""
    strong, weak = make_archers()
    match = Match(strong, weak, n_pass=12)
    match.record_pass(0, score_a=100.0, score_b=50.0)
    assert match.passes[0].score_a == 100
    assert isinstance(match.passes[0].score_a, int)


def test_boundary_scores_zero_and_max_are_accepted():
    """0 and n_pass * MAX_SCORE_PER_ARROW are valid (inclusive) boundaries."""
    strong, weak = make_archers()
    match = Match(strong, weak, n_pass=12)
    match.record_pass(0, score_a=0, score_b=120)
    assert match.passes[0].score_a == 0
    assert match.passes[0].score_b == 120


# --- Feedback 1: equivalent handicap per pass ----------------------------


def test_equivalent_handicap_recorded_for_nonzero_scores():
    """A nonzero pass score gets a recorded equivalent handicap for both archers."""
    strong, weak = make_archers()
    match = Match(strong, weak, n_pass=12)
    match.record_pass(0, score_a=100, score_b=50)
    assert match.passes[0].handicap_a is not None
    assert match.passes[0].handicap_b is not None


def test_equivalent_handicap_is_none_for_zero_score():
    """A zero pass score has an undefined equivalent handicap (None)."""
    strong, weak = make_archers()
    match = Match(strong, weak, n_pass=12)
    match.record_pass(0, score_a=0, score_b=50)
    assert match.passes[0].handicap_a is None
    assert match.passes[0].handicap_b is None or isinstance(
        match.passes[0].handicap_b, float
    )
