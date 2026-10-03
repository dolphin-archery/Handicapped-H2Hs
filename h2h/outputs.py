"""Event outputs: the leaderboard and the per-archer results (AISpec.md section 5.4a).

Flask-free functions that turn an `Event` into plain rows, which the Results pages
render as HTML and `h2h.exports` renders as CSV and PDF. Everything is derived on
each call (nothing is stored), so it is always live, and uses only the passes in
which every match has been scored (`Event.completed_passes`): a partly scored pass
is left out until its last match is saved, so a ranking is never based on only some
of a pass's matches.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Event, PassResult

BYE = "bye"


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
    """

    rank: int
    archer_index: int
    name: str
    points: int
    passes_decided: int


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
        The handicap entered at Stage 2.
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
        rows.append(LeaderboardRow(rank, i, event.archers[i].name, points[i], decided[i]))
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
                total_score=sum(row.score for row in rows),
                rows=rows,
                averages=averages,
            )
        )
    return sections
