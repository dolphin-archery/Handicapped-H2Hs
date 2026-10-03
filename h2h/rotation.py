"""Round-robin rotation scheduling for multi-archer H2H events.

Generates a schedule of archer-position pairings (the standard "circle
method" round-robin), independent of archer identities (Stage 1 runs before
names/handicaps are known -- see AISpec.md section 5.1) and of the stats
engine. An odd number of archers gets a bye slot each rotation, which is
either shot alone (`build_schedule`) or sat out (`build_sit_out_schedule`,
which adds a catch-up rotation so every archer still shoots all their passes
-- see AISpec.md section 5.3 and Assumption 15).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class Rotation:
    """One rotation of a round-robin schedule.

    Attributes
    ----------
    pairs : list[tuple[int, int]]
        Archer-index pairs facing off this rotation.
    bye : int | None
        Archer index shooting alone with no opponent this rotation (no
        comparison -- see AISpec.md Assumption 14), or None. Only set when
        byes are shot and `n_archers` is odd.
    sitting_out : tuple[int, ...]
        Archer indices not shooting this rotation (empty unless the schedule
        comes from `build_sit_out_schedule`).
    """

    pairs: list[tuple[int, int]]
    bye: int | None = None
    sitting_out: tuple[int, ...] = ()

    @property
    def matches(self) -> list[tuple[int, int | None]]:
        """Every match shot this rotation.

        Returns
        -------
        list[tuple[int, int | None]]
            The `pairs`, followed by `(bye, None)` (the bye archer's solo
            match) if `bye` is not None.
        """
        solo = [] if self.bye is None else [(self.bye, None)]
        return [*self.pairs, *solo]


def _full_round_robin(n_archers: int) -> list[Rotation]:
    """Generate one full round-robin schedule via the circle method.

    Parameters
    ----------
    n_archers : int
        Number of archers (archer-index positions 0..n_archers-1).

    Returns
    -------
    list[Rotation]
        `n_archers - 1` rotations (even `n_archers`) or `n_archers` rotations
        with one bye each (odd `n_archers`), covering every possible pair
        exactly once.
    """
    positions: list[int | None] = list(range(n_archers))
    if n_archers % 2 == 1:
        positions.append(None)  # bye placeholder

    n = len(positions)
    num_rounds = n - 1

    rotations = []
    arr = positions[:]
    for _ in range(num_rounds):
        pairs: list[tuple[int, int]] = []
        bye: int | None = None
        for i in range(n // 2):
            a, b = arr[i], arr[n - 1 - i]
            if a is None:
                bye = b
            elif b is None:
                bye = a
            else:
                pairs.append((a, b))
        rotations.append(Rotation(pairs=pairs, bye=bye))
        arr = [arr[0], arr[-1], *arr[1:-1]]

    return rotations


def build_schedule(n_archers: int, n_rotations: int) -> list[Rotation]:
    """Build a rotation schedule for a requested number of rotations.

    Parameters
    ----------
    n_archers : int
        Number of archers (must be >= 2).
    n_rotations : int
        Number of rotations to produce.

    Returns
    -------
    list[Rotation]
        A full round-robin (see `_full_round_robin`) truncated to
        `n_rotations` if fewer are requested than a full round-robin needs,
        or repeated from the start to fill `n_rotations` if more are
        requested (see AISpec.md Assumption 13).

    Raises
    ------
    ValueError
        If `n_archers` < 2 or `n_rotations` < 0.
    """
    if n_archers < 2:
        msg = f"n_archers must be at least 2, got {n_archers}."
        raise ValueError(msg)
    if n_rotations < 0:
        msg = f"n_rotations must not be negative, got {n_rotations}."
        raise ValueError(msg)

    full = _full_round_robin(n_archers)
    return [full[i % len(full)] for i in range(n_rotations)]


def _catch_up_rotation(
    n_archers: int,
    passes_per_archer: int,
    main_rotations: list[Rotation],
) -> Rotation | None:
    """Build the single rotation that tops up archers who are one pass short.

    Parameters
    ----------
    n_archers : int
        Number of archers (archer-index positions 0..n_archers-1).
    passes_per_archer : int
        Passes every archer must shoot.
    main_rotations : list[Rotation]
        The sit-out rotations already scheduled; only their `pairs` are read.

    Returns
    -------
    Rotation | None
        None if nobody is short. Otherwise a rotation pairing the short
        archers with each other (plus one already-complete archer as an extra
        partner if their number is odd, chosen as the one who has faced the
        fewest short archers, ties to the lowest index), preferring opponents
        not yet faced in `main_rotations`; everyone else sits out.
    """
    shots = Counter(a for r in main_rotations for pair in r.pairs for a in pair)
    shooters = [a for a in range(n_archers) if shots[a] < passes_per_archer]
    if not shooters:
        return None

    faced = {frozenset(pair) for r in main_rotations for pair in r.pairs}
    if len(shooters) % 2 == 1:
        complete = [a for a in range(n_archers) if a not in shooters]
        partner = min(
            complete,
            key=lambda c: (sum(frozenset((c, s)) in faced for s in shooters), c),
        )
        shooters = sorted([*shooters, partner])

    pairs: list[tuple[int, int]] = []
    remaining = shooters[:]
    while remaining:
        a = remaining.pop(0)
        b = next((x for x in remaining if frozenset((a, x)) not in faced), remaining[0])
        remaining.remove(b)
        pairs.append((a, b))

    sitting_out = tuple(a for a in range(n_archers) if a not in shooters)
    return Rotation(pairs=pairs, bye=None, sitting_out=sitting_out)


def build_sit_out_schedule(n_archers: int, passes_per_archer: int) -> list[Rotation]:
    """Build a schedule in which bye archers sit out rather than shoot alone.

    Parameters
    ----------
    n_archers : int
        Number of archers (must be >= 2).
    passes_per_archer : int
        Passes every archer must shoot (must be >= 1).

    Returns
    -------
    list[Rotation]
        For an even `n_archers`, exactly `build_schedule(n_archers,
        passes_per_archer)`. For an odd `n_archers`, the cycled circle-method
        round-robin run for the largest number of rotations R in which nobody
        shoots more than `passes_per_archer` passes (the archers with the
        fewest byes have shot R - R // n_archers passes), each rotation's bye
        archer in `sitting_out` and `bye` None. Every archer then has shot
        `passes_per_archer` or one fewer; if any are short, one catch-up
        rotation (see `_catch_up_rotation`) is appended. Everyone ends with at
        least `passes_per_archer` passes and at most one archer with one extra
        (an exact count is impossible when both `n_archers` and
        `passes_per_archer` are odd, as every rotation has an even number of
        shooters). See AISpec.md Assumption 15.

    Raises
    ------
    ValueError
        If `n_archers` < 2 or `passes_per_archer` < 1.
    """
    if n_archers < 2:
        msg = f"n_archers must be at least 2, got {n_archers}."
        raise ValueError(msg)
    if passes_per_archer < 1:
        msg = f"passes_per_archer must be at least 1, got {passes_per_archer}."
        raise ValueError(msg)
    if n_archers % 2 == 0:
        return build_schedule(n_archers, passes_per_archer)

    n_main = 0
    while (n_main + 1) - (n_main + 1) // n_archers <= passes_per_archer:
        n_main += 1

    main = [
        Rotation(pairs=r.pairs, bye=None, sitting_out=(r.bye,))
        for r in build_schedule(n_archers, n_main)
    ]
    catch_up = _catch_up_rotation(n_archers, passes_per_archer, main)
    return main if catch_up is None else [*main, catch_up]
