"""In-memory session state for the Handicapped H2H web app.

Per AISpec.md section 3/Assumption 7: single machine, single scorer, no
database, no persistence across process restarts. A single global instance
is deliberately used instead of Flask sessions/cookies, since this is a
single-user local tool for one scorer running one event at a time.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Archer, Event, RoundMode
from .rotation import Rotation, build_schedule


@dataclass
class SessionState:
    """All state for the current event.

    Attributes
    ----------
    mode : str
        "basic" or "advanced" -- controls UI detail level.
    n_pass : int
        Arrows per rotation's pass.
    n_archers, total_arrows, round_mode : int | int | RoundMode
        Stage 1 event configuration.
    schedule : list[Rotation] | None
        The rotation schedule built at the end of Stage 1, over archer
        *positions* -- set before archer identities are known.
    event : Event | None
        The full event, built once Stage 2 binds archers to `schedule`.
    """

    mode: str = "basic"
    n_pass: int = 12

    n_archers: int | None = None
    total_arrows: int = 60
    round_mode: RoundMode = RoundMode.INDOOR_PORTSMOUTH
    schedule: list[Rotation] | None = None
    event: Event | None = None

    def start_stage1(
        self, n_archers: int, total_arrows: int, n_pass: int, round_mode: RoundMode
    ) -> None:
        """Validate event configuration and build the rotation schedule.

        Parameters
        ----------
        n_archers : int
            Number of archers in the event; must be >= 2.
        total_arrows : int
            Total arrows each archer shoots; must be a positive multiple of
            `n_pass`.
        n_pass : int
            Arrows per rotation's pass.
        round_mode : RoundMode
            The event's round mode.

        Raises
        ------
        ValueError
            If `n_archers` < 2, or `n_pass` does not evenly divide
            `total_arrows`.
        """
        if n_archers < 2:
            msg = f"Need at least 2 archers, got {n_archers}."
            raise ValueError(msg)
        if total_arrows <= 0 or n_pass <= 0 or total_arrows % n_pass != 0:
            msg = (
                f"Arrows per pass ({n_pass}) must evenly divide total arrows "
                f"({total_arrows})."
            )
            raise ValueError(msg)

        new_schedule = build_schedule(n_archers, total_arrows // n_pass)

        # Only commit once the schedule has been built successfully.
        self.n_archers = n_archers
        self.total_arrows = total_arrows
        self.n_pass = n_pass
        self.round_mode = round_mode
        self.schedule = new_schedule
        self.event = None  # discard any previous event

    def start_stage2(self, archers: list[Archer]) -> None:
        """Bind archer details to the Stage 1 schedule and build the Event.

        Parameters
        ----------
        archers : list[Archer]
            Exactly `self.n_archers` archers, in schedule-position order.

        Raises
        ------
        RuntimeError
            If Stage 1 has not been completed yet.
        ValueError
            If the number of archers doesn't match `self.n_archers`.
        """
        if self.schedule is None or self.n_archers is None:
            msg = "Stage 1 must be completed before Stage 2."
            raise RuntimeError(msg)
        if len(archers) != self.n_archers:
            msg = f"Expected {self.n_archers} archers, got {len(archers)}."
            raise ValueError(msg)

        self.event = Event(archers, self.n_pass, self.round_mode, self.schedule)

    def toggle_mode(self) -> None:
        """Switch between "basic" and "advanced" display modes."""
        self.mode = "advanced" if self.mode == "basic" else "basic"

    def reset(self) -> None:
        """Clear all event state back to a fresh session."""
        self.mode = "basic"
        self.n_pass = 12
        self.n_archers = None
        self.total_arrows = 60
        self.round_mode = RoundMode.INDOOR_PORTSMOUTH
        self.schedule = None
        self.event = None


# Single shared instance for the whole (single-user, single-process) app.
session = SessionState()
