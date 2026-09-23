"""Round-robin rotation scheduling for multi-archer H2H events.

Generates a schedule of archer-position pairings (the standard "circle
method" round-robin), independent of archer identities (Stage 1 runs before
names/handicaps are known -- see AISpec.md section 5.1) and of the stats
engine. An odd number of archers gets a bye slot each rotation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rotation:
    """One rotation of a round-robin schedule.

    Attributes
    ----------
    pairs : list[tuple[int, int]]
        Archer-index pairs facing off this rotation.
    bye : int | None
        Archer index sitting out this rotation (shoots alone, no comparison
        -- see AISpec.md Assumption 14), or None if `n_archers` is even.
    """

    pairs: list[tuple[int, int]]
    bye: int | None = None


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
