"""In-memory session state for the Handicapped H2H web app.

Per AISpec.md section 3/Assumption 7: single machine, single scorer, no
database, no persistence across process restarts. A single global instance
is deliberately used instead of Flask sessions/cookies, since this is a
single-user local tool for one scorer running one set of matches at a time.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Archer, Match


@dataclass
class SessionState:
    """All state for the current set of matches.

    Attributes
    ----------
    mode : str
        "basic" or "advanced" -- controls UI detail level.
    n_pass : int
        Arrows per pass for the current set of matches.
    matches : list[Match]
        One Match per archer pair, in pairing order.
    unpaired : Archer | None
        An archer left over from an odd-sized entry list, excluded from
        scoring.
    """

    mode: str = "basic"
    n_pass: int = 12
    matches: list[Match] = field(default_factory=list)
    unpaired: Archer | None = None

    def start_matches(self, archers: list[Archer], n_pass: int) -> None:
        """Reset state and build fresh matches from sequential archer pairs.

        Parameters
        ----------
        archers : list[Archer]
            Archers in entry order; paired as (0,1), (2,3), ...
        n_pass : int
            Arrows per pass to use for every match in this set.
        """
        pairs = list(zip(archers[0::2], archers[1::2], strict=False))
        new_matches = [Match(archer_a, archer_b, n_pass) for archer_a, archer_b in pairs]

        # Only commit state once every match has validated successfully, so
        # an invalid n_pass never leaves the session in a half-updated state.
        self.n_pass = n_pass
        self.matches = new_matches
        self.unpaired = archers[-1] if len(archers) % 2 == 1 else None

    def toggle_mode(self) -> None:
        """Switch between "basic" and "advanced" display modes."""
        self.mode = "advanced" if self.mode == "basic" else "basic"

    def reset(self) -> None:
        """Clear all match state back to a fresh session."""
        self.mode = "basic"
        self.n_pass = 12
        self.matches = []
        self.unpaired = None


# Single shared instance for the whole (single-user, single-process) app.
session = SessionState()
