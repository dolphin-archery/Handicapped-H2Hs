"""The Stage 3 draw: which entered archer fills each schedule position (AISpec.md section 5.3).

Pure functions with no Flask and no state of their own (UISpec.md decision D17): the caller
supplies the random source, so the Flask-era `SessionState` (with its own `rng`) and the
browser bridge (with `random.Random(seed)` for a seed chosen in JavaScript) make exactly the
same draw from the same source.
"""

from __future__ import annotations

import random

from .rotation import Rotation

# How many fresh random draws a redraw may try to find pairings that differ from the
# current ones, before accepting whatever it last drew (e.g. with only 2 archers there
# is nothing different to find).
_MAX_REDRAW_ATTEMPTS = 50


def pairings_signature(schedule: list[Rotation], assignment: list[int]) -> tuple:
    """A hashable summary of who meets whom, and who byes or sits out, in every pass.

    Two assignments with the same signature give the scorer the same pairings, even if they
    differ in (say) which archer is listed first in a pair.

    Parameters
    ----------
    schedule : list[h2h.rotation.Rotation]
        The rotation schedule, over schedule positions.
    assignment : list[int]
        A position -> entered-archer index assignment.

    Returns
    -------
    tuple
        One `(pairs, bye archer, sitting-out archers)` entry per rotation.
    """
    return tuple(
        (
            frozenset(frozenset((assignment[a], assignment[b])) for a, b in rotation.pairs),
            None if rotation.bye is None else assignment[rotation.bye],
            frozenset(assignment[i] for i in rotation.sitting_out),
        )
        for rotation in schedule
    )


def draw_assignment(
    schedule: list[Rotation],
    n_archers: int,
    rng: random.Random,
    current: list[int] | None = None,
) -> list[int]:
    """Draw a random assignment of the entered archers to schedule positions.

    With a current assignment, a draw whose pairings differ from it is preferred (so pressing
    "Redraw" visibly changes something), trying up to `_MAX_REDRAW_ATTEMPTS` times; if none is
    found (e.g. with only two archers) the last draw is kept.

    Parameters
    ----------
    schedule : list[h2h.rotation.Rotation]
        The rotation schedule, over schedule positions.
    n_archers : int
        The number of entered archers.
    rng : random.Random
        The random source; each attempt calls its `shuffle` once.
    current : list[int] | None, default=None
        The assignment being replaced, or None for the first draw.

    Returns
    -------
    list[int]
        `assignment[position]` is the index of the entered archer filling that position (a
        permutation of `range(n_archers)`).
    """
    previous = None if current is None else pairings_signature(schedule, current)
    for _ in range(_MAX_REDRAW_ATTEMPTS):
        order = list(range(n_archers))
        rng.shuffle(order)
        if previous is None or pairings_signature(schedule, order) != previous:
            break
    return order
