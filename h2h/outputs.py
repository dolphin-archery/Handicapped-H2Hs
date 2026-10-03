"""Event outputs: the leaderboard and the per-archer results (AISpec.md section 5.4a).

Flask-free functions that turn an `Event` into plain rows, which the Results pages
render as HTML and `h2h.exports` renders as CSV and PDF. Everything is derived on
each call (nothing is stored), so it is always live, and uses only the passes in
which every match has been scored (`Event.completed_passes`): a partly scored pass
is left out until its last match is saved, so a ranking is never based on only some
of a pass's matches.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import stats
from .models import Event, PassResult
from .stats import PERCENTILE_REL_TOLERANCE

BYE = "bye"

# The most decimal places a pair of percentiles is shown to when the display rule has to add
# places to tell them apart (AISpec.md section 5.3, Assumption 42).
MAX_PERCENTILE_DECIMALS = 20


@dataclass(frozen=True)
class LeaderboardRow:
    """One archer's line of the leaderboard.

    Attributes
    ----------
    rank : int
        1-based rank by points; archers on equal points share a rank (1, 2, 2, 4).
    archer_index : int
        Index into `Event.archers`.
    name : str
        The archer's name.
    points : int
        Passes won (1 point each; a lost pass scores 0).
    passes_decided : int
        Completed passes in which the archer had an opponent (a bye pass has no
        winner and so is not counted).
    starting_handicap : float
        The handicap entered at Stage 2.
    to_date_handicap : float | None
        The handicap implied by the archer's total score over every arrow shot in the
        completed passes (see `_to_date_handicaps`), or None if there is none.
    """

    rank: int
    archer_index: int
    name: str
    points: int
    passes_decided: int
    starting_handicap: float
    to_date_handicap: float | None


@dataclass(frozen=True)
class ArcherResultRow:
    """One archer's result in one completed pass.

    Attributes
    ----------
    pass_number : int
        1-based pass number.
    opponent : str
        The opponent's name, or "bye" when the archer shot alone.
    score : int
        The score shot in the pass.
    percentile : float
        That score's percentile in the archer's own distribution, as a fraction
        in [0, 1] (shown as a percentage by the pages and exports).
    handicap : float | None
        The handicap implied by the score, or None for a score of 0.
    """

    pass_number: int
    opponent: str
    score: int
    percentile: float
    handicap: float | None


@dataclass(frozen=True)
class ArcherAverages:
    """The mean of an archer's numeric result columns.

    Attributes
    ----------
    score, percentile : float
        Means over every row (percentile as a fraction).
    handicap : float | None
        Mean over the rows that have a handicap; None if none do.
    """

    score: float
    percentile: float
    handicap: float | None


@dataclass(frozen=True)
class ArcherResults:
    """One archer's section of the per-archer results.

    Attributes
    ----------
    archer_index : int
        Index into `Event.archers`.
    name : str
        The archer's name.
    handicap : float
        The starting handicap, the one entered at Stage 2.
    to_date_handicap : float | None
        The handicap implied by the total score over `arrows_shot` arrows (see
        `_to_date_handicaps`), or None if there is none.
    arrows_shot : int
        The arrows the archer shot in the completed passes (`n_pass` per pass).
    total_score : int
        The sum of the archer's scores over the completed passes.
    rows : list[ArcherResultRow]
        One row per completed pass the archer shot in, in pass order.
    averages : ArcherAverages | None
        Means of the numeric columns, or None if there are no rows.
    """

    archer_index: int
    name: str
    handicap: float
    to_date_handicap: float | None
    arrows_shot: int
    total_score: int
    rows: list[ArcherResultRow]
    averages: ArcherAverages | None


def _completed_results(event: Event) -> list[PassResult]:
    """The event's recorded results that belong to completed passes, in pass order.

    Parameters
    ----------
    event : h2h.models.Event
        The event.

    Returns
    -------
    list[PassResult]
        Results of every completed pass, ordered by pass (and otherwise as recorded).
    """
    completed = set(event.completed_passes)
    kept = [r for r in event.results if r.rotation_index in completed]
    return sorted(kept, key=lambda r: r.rotation_index)


def _to_date_handicaps(event: Event, results: list[PassResult]) -> list[float | None]:
    """Each archer's to-date handicap: their total score over all the arrows shot so far.

    It is the handicap implied by the total of the archer's scores in the completed passes
    over `n_pass` times the number of passes they shot (byes included), on their own target:
    the same calculation as a pass's handicap, but over every arrow, so after the last pass
    it equals the handicap a full-round calculation of their whole score gives
    (AISpec.md section 5.4a, Assumption 47).

    Parameters
    ----------
    event : h2h.models.Event
        The event.
    results : list[PassResult]
        The results of the completed passes (see `_completed_results`).

    Returns
    -------
    list[float | None]
        One entry per archer; None if they have shot no completed pass or their total is 0.
    """
    handicaps = []
    for i in range(len(event.archers)):
        scores = [r.score for r in results if r.archer_index == i]
        if not scores:
            handicaps.append(None)
            continue
        handicaps.append(
            stats.equivalent_handicap(sum(scores), event.n_pass * len(scores), event.target_for(i))
        )
    return handicaps


def leaderboard(event: Event) -> list[LeaderboardRow]:
    """The event-wide leaderboard over the completed passes.

    Parameters
    ----------
    event : h2h.models.Event
        The event.

    Returns
    -------
    list[LeaderboardRow]
        One row per archer, highest points first. Archers on equal points share a
        rank (competition ranking: 1, 2, 2, 4) and keep event order within it.
    """
    results = _completed_results(event)
    to_date = _to_date_handicaps(event, results)
    points = [0] * len(event.archers)
    decided = [0] * len(event.archers)
    for r in results:
        if r.opponent_index is None:
            continue  # a bye pass has no winner
        decided[r.archer_index] += 1
        if r.won:
            points[r.archer_index] += 1

    order = sorted(range(len(event.archers)), key=lambda i: (-points[i], i))
    rows = []
    for position, i in enumerate(order):
        tied_with_previous = position > 0 and points[i] == points[order[position - 1]]
        rank = rows[-1].rank if tied_with_previous else position + 1
        rows.append(
            LeaderboardRow(
                rank, i, event.archers[i].name, points[i], decided[i],
                event.archers[i].handicap, to_date[i],
            )
        )
    return rows


def _mean(values: list[float]) -> float | None:
    """The mean of `values`, or None if there are none."""
    return sum(values) / len(values) if values else None


def archer_results(event: Event) -> list[ArcherResults]:
    """Every archer's results over the completed passes, with averages.

    Parameters
    ----------
    event : h2h.models.Event
        The event.

    Returns
    -------
    list[ArcherResults]
        One entry per archer, in event order. A pass an archer sat out has no row.
    """
    results = _completed_results(event)
    to_date = _to_date_handicaps(event, results)
    sections = []
    for i, archer in enumerate(event.archers):
        rows = [
            ArcherResultRow(
                pass_number=r.rotation_index + 1,
                opponent=BYE if r.opponent_index is None else event.archers[r.opponent_index].name,
                score=r.score,
                percentile=r.percentile,
                handicap=r.handicap,
            )
            for r in results
            if r.archer_index == i
        ]
        averages = None
        if rows:
            averages = ArcherAverages(
                score=_mean([row.score for row in rows]),
                percentile=_mean([row.percentile for row in rows]),
                handicap=_mean([row.handicap for row in rows if row.handicap is not None]),
            )
        sections.append(
            ArcherResults(
                archer_index=i,
                name=archer.name,
                handicap=archer.handicap,
                to_date_handicap=to_date[i],
                arrows_shot=event.n_pass * len(rows),
                total_score=sum(row.score for row in rows),
                rows=rows,
                averages=averages,
            )
        )
    return sections


# --- Display helpers shared by the pass tables (AISpec.md section 5.3) -------------------


def percentile_pair_text(percentile_a: float, percentile_b: float) -> tuple[str, str]:
    """Show two archers' percentiles as percentages that can be told apart.

    Both are shown to one decimal place unless that makes them look the same, in which case
    a decimal place is added to both, repeatedly, until they differ, up to
    `MAX_PERCENTILE_DECIMALS`. Two percentiles that are tied (equal within the tie-break
    tolerance, for instance both exactly 100%) cannot be told apart by any number of places,
    and neither can two that are still identical at the limit; both of those stay at one
    decimal place.

    Parameters
    ----------
    percentile_a, percentile_b : float
        The two percentiles as fractions in [0, 1].

    Returns
    -------
    tuple[str, str]
        The two percentages with a "%" sign, e.g. ("59.8%", "12.3%"), in argument order.
    """
    one_place = (f"{percentile_a * 100:.1f}%", f"{percentile_b * 100:.1f}%")
    if math.isclose(percentile_a, percentile_b, rel_tol=PERCENTILE_REL_TOLERANCE, abs_tol=0.0):
        return one_place
    for decimals in range(1, MAX_PERCENTILE_DECIMALS + 1):
        text_a = f"{percentile_a * 100:.{decimals}f}"
        text_b = f"{percentile_b * 100:.{decimals}f}"
        if text_a != text_b:
            return f"{text_a}%", f"{text_b}%"
    return one_place


@dataclass(frozen=True)
class PassTableRow:
    """One row of a pass results table, as the text to show.

    Attributes
    ----------
    archer : str
        The archer's name.
    score : str
        The score shot.
    percentile : str
        The percentile as a percentage (see `percentile_pair_text`).
    start_handicap : str
        The handicap the archer's distribution for this pass was built from, to one decimal
        place (`Event.handicap_for`); the table shows it only when handicaps are updated.
    handicap : str
        The handicap implied by the score to one decimal place, or "-" for a score of 0.
    winner : str
        "Yes" or "No" for a paired match, "-" for a bye match.
    """

    archer: str
    score: str
    percentile: str
    start_handicap: str
    handicap: str
    winner: str


def pass_table_rows(event: Event, results: list[PassResult]) -> list[PassTableRow]:
    """Turn one match's results into the rows of the pass results table.

    Parameters
    ----------
    event : h2h.models.Event
        The event (for the archers' names).
    results : list[PassResult]
        One match's results in the order to show them: one result for a bye match,
        two for a pair (see `Event.match_results`).

    Returns
    -------
    list[PassTableRow]
        One row per result. A pair's percentiles follow `percentile_pair_text`; a bye match's
        use one decimal place.
    """
    if len(results) == 2:
        percentiles = percentile_pair_text(results[0].percentile, results[1].percentile)
    else:
        percentiles = tuple(f"{r.percentile * 100:.1f}%" for r in results)
    return [
        PassTableRow(
            archer=event.archers[r.archer_index].name,
            score=str(r.score),
            percentile=text,
            start_handicap=f"{event.handicap_for(r.archer_index, r.rotation_index):.1f}",
            handicap="-" if r.handicap is None else f"{r.handicap:.1f}",
            winner="-" if r.won is None else ("Yes" if r.won else "No"),
        )
        for r, text in zip(results, percentiles, strict=True)
    ]
