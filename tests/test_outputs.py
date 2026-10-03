"""Tests for h2h.outputs: completed passes, the leaderboard and the per-archer results."""

import inspect

import pytest

from h2h import outputs
from h2h.models import Archer, Bowstyle, Event, PassResult
from h2h.outputs import archer_results, leaderboard
from h2h.rotation import build_schedule, build_sit_out_schedule

from .helpers import PORTSMOUTH


def make_event(n_archers=4, rotations=None, n_pass=12, schedule=None):
    """An Event of n archers with distinct handicaps (20, 30, 40, ...) and a round-robin schedule."""
    archers = [Archer(f"A{i}", 20 + 10 * i, Bowstyle.RECURVE) for i in range(n_archers)]
    if schedule is None:
        if rotations is None:
            rotations = n_archers if n_archers % 2 else n_archers - 1
        schedule = build_schedule(n_archers, rotations)
    return Event(archers, n_pass, PORTSMOUTH, schedule)


def score_pass(event, score_fn=lambda archer: 80 + archer):
    """Record every match of the event's current pass."""
    for match in event.matches(event.current_rotation_index):
        event.record_match({p: score_fn(p) for p in match if p is not None})


def play_event(event, score_fn=lambda archer: 80 + archer):
    """Score every pass, advancing between them."""
    for i in range(len(event.schedule)):
        score_pass(event, lambda a, i=i: score_fn(a) + i)
        if i < len(event.schedule) - 1:
            event.advance()


def fake_results(event, winner_of):
    """Fill an event's results directly: for every pair, `winner_of(frozenset(pair))` wins.

    Used to get exact, chosen win counts (the real winner depends on the maths).
    """
    for rotation_index, rotation in enumerate(event.schedule):
        for a, b in rotation.pairs:
            winner = winner_of(frozenset((a, b)))
            for me, other in ((a, b), (b, a)):
                won = me == winner
                event.results.append(
                    PassResult(rotation_index, me, 90 if won else 80, 0.9 if won else 0.1,
                               30.0, other, won, "percentile")
                )


# --- Nothing scored ------------------------------------------------------------------


def test_with_nothing_scored_everyone_is_on_zero_points_and_tied_first():
    """No completed pass: every archer 0 points, 0 decided, rank 1, in event order."""
    event = make_event(4)
    assert event.completed_passes == []
    assert [(r.rank, r.name, r.points, r.passes_decided) for r in leaderboard(event)] == [
        (1, "A0", 0, 0), (1, "A1", 0, 0), (1, "A2", 0, 0), (1, "A3", 0, 0),
    ]


def test_with_nothing_scored_every_archer_has_an_empty_table_and_no_averages():
    """Headings are available, rows are empty and so are the averages."""
    sections = archer_results(make_event(4))
    assert [s.name for s in sections] == ["A0", "A1", "A2", "A3"]
    assert [s.handicap for s in sections] == [20, 30, 40, 50]
    assert all(s.rows == [] and s.averages is None and s.total_score == 0 for s in sections)


# --- Completed passes only -----------------------------------------------------------


def test_a_partly_scored_pass_is_left_out_until_its_last_match_is_saved():
    """Pass 2 with one of its two matches saved adds nothing; saving the second adds it."""
    event = make_event(4)
    score_pass(event)
    event.advance()
    first, second = event.matches(1)
    event.record_match({p: 80 + p for p in first})
    assert event.completed_passes == [0]
    assert all(len(s.rows) == 1 for s in archer_results(event))  # pass 1 only
    pass_1_points = [r.points for r in leaderboard(event)]

    event.record_match({p: 80 + p for p in second})
    assert event.completed_passes == [0, 1]
    assert all(len(s.rows) == 2 for s in archer_results(event))
    assert sum(r.points for r in leaderboard(event)) == sum(pass_1_points) + 2


def test_completed_passes_lists_only_fully_scored_rotations():
    """The rotations not reached yet are never complete."""
    event = make_event(4)
    assert event.completed_passes == []
    score_pass(event)
    assert event.completed_passes == [0]
    event.advance()
    assert event.completed_passes == [0]


# --- Leaderboard ---------------------------------------------------------------------


def test_points_are_the_passes_won_and_total_one_point_per_decided_match():
    """Over a whole 4-archer event, points match the Event's own winners."""
    event = make_event(4)
    play_event(event)
    rows = {r.archer_index: r for r in leaderboard(event)}
    for i in range(4):
        wins = sum(1 for r in event.results if r.archer_index == i and r.won)
        assert rows[i].points == wins
        assert rows[i].passes_decided == 3  # everyone faces every other archer once
    assert sum(r.points for r in rows.values()) == 6  # 2 matches x 3 passes, one winner each


def test_leaderboard_is_ordered_by_points_with_distinct_ranks_when_points_differ():
    """3, 2, 1, 0 wins: ranks 1 to 4, best first, whatever the event order."""
    event = make_event(4)
    strength = {0: 3, 1: 0, 2: 2, 3: 1}  # the stronger archer wins each pair
    fake_results(event, lambda pair: max(pair, key=strength.get))
    rows = leaderboard(event)
    assert [(r.rank, r.archer_index, r.points) for r in rows] == [
        (1, 0, 3), (2, 2, 2), (3, 3, 1), (4, 1, 0),
    ]


def test_equal_points_share_a_rank_and_keep_event_order():
    """Points 3, 1, 1, 1 give ranks 1, 2, 2, 2, with the tied archers in event order."""
    event = make_event(4)
    beats = {frozenset((1, 2)): 1, frozenset((2, 3)): 2, frozenset((1, 3)): 3}
    fake_results(event, lambda pair: 0 if 0 in pair else beats[pair])
    assert [(r.rank, r.archer_index, r.points) for r in leaderboard(event)] == [
        (1, 0, 3), (2, 1, 1), (2, 2, 1), (2, 3, 1),
    ]


def test_ranks_skip_after_a_tie():
    """Competition ranking: two archers tied on 2 points are 1 and 1, the next two are 3 and 3."""
    event = make_event(4)
    winners = {
        frozenset(pair): winner
        for pair, winner in [((0, 1), 0), ((0, 2), 0), ((0, 3), 3), ((1, 2), 1), ((1, 3), 1), ((2, 3), 2)]
    }
    fake_results(event, lambda pair: winners[pair])
    assert [(r.rank, r.archer_index, r.points) for r in leaderboard(event)] == [
        (1, 0, 2), (1, 1, 2), (3, 2, 1), (3, 3, 1),
    ]


def test_two_archers_who_win_a_pass_each_are_both_rank_one():
    """A repeated pairing split one pass each leaves them level."""
    event = make_event(2, rotations=2)
    wins = iter([0, 1])
    fake_results(event, lambda pair: next(wins))
    assert [(r.rank, r.points) for r in leaderboard(event)] == [(1, 1), (1, 1)]


def test_a_bye_pass_scores_no_point_and_is_not_counted_as_decided():
    """Odd archers, byes shot: the bye archer's solo pass has no winner."""
    event = make_event(3, rotations=3)
    bye_archer = event.schedule[0].bye
    score_pass(event)
    rows = {r.archer_index: r for r in leaderboard(event)}
    assert rows[bye_archer].points == 0 and rows[bye_archer].passes_decided == 0
    others = [i for i in range(3) if i != bye_archer]
    assert all(rows[i].passes_decided == 1 for i in others)
    assert sum(r.points for r in rows.values()) == 1


def test_resaving_a_match_does_not_count_it_twice():
    """Editing a saved match replaces its result: points stay one per decided match."""
    event = make_event(2, rotations=1)
    event.record_match({0: 100, 1: 60})
    event.record_match({0: 60, 1: 100})
    rows = leaderboard(event)
    assert sum(r.points for r in rows) == 1
    assert [r.passes_decided for r in rows] == [1, 1]


# --- Per-archer results --------------------------------------------------------------


def test_rows_are_in_pass_order_with_one_based_pass_numbers_and_the_opponents_name():
    """Each row has the pass number, opponent name, score, percentile and handicap."""
    event = make_event(4)
    play_event(event)
    for section in archer_results(event):
        assert [row.pass_number for row in section.rows] == [1, 2, 3]
        mine = sorted((r for r in event.results if r.archer_index == section.archer_index),
                      key=lambda r: r.rotation_index)
        for row, r in zip(section.rows, mine, strict=True):
            assert row.opponent == event.archers[r.opponent_index].name
            assert (row.score, row.percentile, row.handicap) == (r.score, r.percentile, r.handicap)
        assert len({row.opponent for row in section.rows}) == 3  # a different opponent each pass


def test_a_bye_row_names_bye_and_a_sat_out_pass_has_no_row():
    """A solo pass reads 'bye'; sitting a pass out leaves no row."""
    byes = make_event(3, rotations=3)
    bye_archer = byes.schedule[0].bye
    score_pass(byes)
    section = archer_results(byes)[bye_archer]
    assert [(row.pass_number, row.opponent) for row in section.rows] == [(1, "bye")]

    sit = make_event(3, schedule=build_sit_out_schedule(3, 3))
    sitter = sit.schedule[0].sitting_out[0]
    score_pass(sit)
    assert archer_results(sit)[sitter].rows == []


def test_total_score_is_the_sum_of_the_rows_and_the_averages_are_their_means():
    """Totals and means over the completed passes; handicap mean ignores a score of 0."""
    event = make_event(2, rotations=3)
    event.record_match({0: 100, 1: 70})
    event.advance()
    event.record_match({0: 90, 1: 0})  # a zero has no equivalent handicap
    event.advance()
    event.record_match({0: 110, 1: 80})

    first, second = archer_results(event)
    assert first.total_score == 300 and second.total_score == 150
    assert first.averages.score == pytest.approx(100.0)
    assert second.averages.score == pytest.approx(50.0)
    assert first.averages.percentile == pytest.approx(sum(r.percentile for r in first.rows) / 3)
    assert second.rows[1].handicap is None
    expected = [row.handicap for row in second.rows if row.handicap is not None]
    assert len(expected) == 2
    assert second.averages.handicap == pytest.approx(sum(expected) / 2)


def test_the_handicap_average_is_none_when_no_row_has_a_handicap():
    """A single scoreless pass: score and percentile average, handicap does not."""
    event = make_event(2, rotations=1)
    event.record_match({0: 0, 1: 5})
    zero = archer_results(event)[0]
    assert zero.rows[0].handicap is None
    assert zero.averages.handicap is None
    assert zero.averages.score == 0


def test_results_use_only_completed_passes_even_if_a_later_pass_has_a_saved_match():
    """A saved match in an unfinished pass is not in anyone's rows or total."""
    event = make_event(4)
    score_pass(event)
    event.advance()
    first, _ = event.matches(1)
    event.record_match({first[0]: 90, first[1]: 85})
    for section in archer_results(event):
        assert [row.pass_number for row in section.rows] == [1]


# --- Module hygiene ------------------------------------------------------------------


def test_the_module_is_flask_free_and_every_function_has_a_docstring():
    """h2h.outputs depends only on the model, and documents each function."""
    source = inspect.getsource(outputs)
    assert "import flask" not in source and "from flask" not in source
    for name, obj in inspect.getmembers(outputs, inspect.isfunction):
        if obj.__module__ == outputs.__name__:
            assert obj.__doc__ and obj.__doc__.strip(), name


# --- Feedback 6: percentile display rule and pass table rows ----------------------------


from h2h.outputs import (  # noqa: E402
    MAX_PERCENTILE_DECIMALS,
    PassTableRow,
    pass_table_rows,
    percentile_pair_text,
)


def test_percentiles_that_already_differ_at_one_place_are_unchanged():
    """The common case: one decimal place each."""
    assert percentile_pair_text(0.598, 0.123) == ("59.8%", "12.3%")
    assert percentile_pair_text(0.5, 0.01) == ("50.0%", "1.0%")


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (0.50003, 0.50004, ("50.003%", "50.004%")),
        (0.5004, 0.5001, ("50.04%", "50.01%")),
        (0.0002, 0.0003, ("0.02%", "0.03%")),
    ],
)
def test_places_are_added_until_the_two_look_different(a, b, expected):
    """The fewest extra decimal places that separate the pair, applied to both."""
    assert percentile_pair_text(a, b) == expected


def test_rounding_not_truncation_decides_when_two_near_100_look_the_same():
    """0.99996 and 0.99991 both round to 100.0% at one place; two places already separate them."""
    assert percentile_pair_text(0.99996, 0.99991) == ("100.00%", "99.99%")


@pytest.mark.parametrize(
    ("a", "b"),
    [(1.0, 1.0), (1.0, 1.0 - 1e-12), (0.0, 0.0), (0.5, 0.5), (0.5, 0.5 + 1e-12)],
)
def test_a_genuine_tie_stays_at_one_decimal_place(a, b):
    """Both exactly 100% (or any other tie within the tolerance): nothing can tell them apart."""
    text_a, text_b = percentile_pair_text(a, b)
    assert text_a == f"{a * 100:.1f}%" and text_b == f"{b * 100:.1f}%"
    assert text_a.count(".") == 1 and len(text_a.split(".")[1]) == 2  # one place plus the sign


def test_tiny_but_different_percentiles_get_enough_places_when_the_limit_allows():
    """1e-18 and 1e-20 as fractions are 1e-16 % and 1e-18 %: 18 places separate them."""
    text_a, text_b = percentile_pair_text(1e-18, 1e-20)
    assert text_a != text_b
    assert len(text_a.split(".")[1]) - 1 <= MAX_PERCENTILE_DECIMALS


def test_pairs_that_look_the_same_even_at_the_limit_stay_at_one_place():
    """Two different values far below the limit's resolution fall back to one place."""
    assert percentile_pair_text(1e-30, 1e-25) == ("0.0%", "0.0%")


def test_the_rule_never_raises_and_never_exceeds_the_limit_for_any_pair():
    """A sweep of awkward pairs across [0, 1]."""
    values = [0.0, 1e-300, 1e-30, 1e-18, 1e-9, 0.001, 0.0999999, 0.1, 0.5, 0.9999999, 1 - 1e-12, 1.0]
    for a in values:
        for b in values:
            for text in percentile_pair_text(a, b):
                assert text.endswith("%")
                assert len(text[:-1].split(".")[1]) <= MAX_PERCENTILE_DECIMALS


def test_pass_table_rows_for_a_scored_pair_are_in_match_order_with_the_display_texts():
    """Name, score, the pair's percentile texts, handicap to one decimal, Yes/No."""
    event = make_event(4)
    first, _ = event.matches(0)
    event.record_match({p: 80 + p for p in first})
    results = event.match_results(0, first)
    rows = pass_table_rows(event, results)
    texts = percentile_pair_text(results[0].percentile, results[1].percentile)
    assert [r.archer for r in rows] == [event.archers[p].name for p in first]
    assert [r.score for r in rows] == [str(80 + p) for p in first]
    assert [r.percentile for r in rows] == list(texts)
    assert [r.handicap for r in rows] == [f"{x.handicap:.1f}" for x in results]
    assert sorted(r.winner for r in rows) == ["No", "Yes"]
    assert isinstance(rows[0], PassTableRow)


def test_pass_table_rows_use_a_dash_for_a_zero_score_and_for_a_bye_winner():
    """A score of 0 has no handicap; a bye match has no winner and one decimal place."""
    event = make_event(3, rotations=3)
    pair, solo = event.matches(0)
    event.record_match({pair[0]: 0, pair[1]: 60})
    event.record_match({solo[0]: 70})
    zero_row = pass_table_rows(event, event.match_results(0, pair))[0]
    assert zero_row.score == "0" and zero_row.handicap == "-"
    (bye_row,) = pass_table_rows(event, event.match_results(0, solo))
    assert bye_row.winner == "-"
    assert bye_row.percentile == f"{event.match_results(0, solo)[0].percentile * 100:.1f}%"
    assert pass_table_rows(event, []) == []


def test_match_results_come_back_in_match_order_whatever_order_they_were_saved_in():
    """The second archer's result is never listed before the first's."""
    event = make_event(2, rotations=1)
    a, b = event.matches(0)[0]
    event.record_match({b: 90, a: 80})
    assert [r.archer_index for r in event.match_results(0, (a, b))] == [a, b]
    assert [r.archer_index for r in event.match_results(0, (b, a))] == [b, a]
