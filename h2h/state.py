"""In-memory session state for the Handicapped H2H web app.

Per AISpec.md section 3/Assumption 7: single machine, single scorer, no
database, no persistence across process restarts. A single global instance
is deliberately used instead of Flask sessions/cookies, since this is a
single-user local tool for one scorer running one event at a time.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Archer, Event, RoundMode
from .rotation import Rotation, build_schedule, build_sit_out_schedule


@dataclass
class SessionState:
    """All state for the current event.

    Attributes
    ----------
    graph_view : bool
        Whether the optional charts and explanation are shown (Specification/
        feedback.md "Feedback 4" renamed the old advanced mode to graph view).
    n_pass : int
        Arrows per rotation's pass.
    n_archers, total_arrows, round_mode : int | int | RoundMode
        Stage 1 event configuration.
    shoot_byes : bool
        For an odd `n_archers`: whether the archer with the bye shoots alone
        (True) or sits the pass out, adding passes to the event (False).
        Ignored for an even `n_archers`.
    schedule : list[Rotation] | None
        The rotation schedule built at the end of Stage 1, over archer
        *positions* -- set before archer identities are known.
    event : Event | None
        The full event, built once Stage 2 binds archers to `schedule`.
    """

    graph_view: bool = False
    n_pass: int = 12

    n_archers: int | None = None
    total_arrows: int = 60
    round_mode: RoundMode = RoundMode.INDOOR_PORTSMOUTH
    shoot_byes: bool = True
    schedule: list[Rotation] | None = None
    event: Event | None = None

    def start_stage1(
        self,
        n_archers: int,
        total_arrows: int,
        n_pass: int,
        round_mode: RoundMode,
        shoot_byes: bool = True,
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
        shoot_byes : bool, default=True
            Whether the bye archer shoots alone (True) or sits out (False)
            when `n_archers` is odd; ignored for an even `n_archers`. Sitting
            out lengthens the schedule beyond `total_arrows // n_pass`
            rotations (see `build_sit_out_schedule`).

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

        passes_per_archer = total_arrows // n_pass
        if n_archers % 2 == 1 and not shoot_byes:
            new_schedule = build_sit_out_schedule(n_archers, passes_per_archer)
        else:
            new_schedule = build_schedule(n_archers, passes_per_archer)

        # Only commit once the schedule has been built successfully.
        self.n_archers = n_archers
        self.total_arrows = total_arrows
        self.n_pass = n_pass
        self.round_mode = round_mode
        self.shoot_byes = shoot_byes
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

    def toggle_graph_view(self) -> None:
        """Switch graph view (charts and explanation) on or off."""
        self.graph_view = not self.graph_view

    def reset(self) -> None:
        """Clear all event state back to a fresh session."""
        self.graph_view = False
        self.n_pass = 12
        self.n_archers = None
        self.total_arrows = 60
        self.round_mode = RoundMode.INDOOR_PORTSMOUTH
        self.shoot_byes = True
        self.schedule = None
        self.event = None


# Single shared instance for the whole (single-user, single-process) app.
session = SessionState()
