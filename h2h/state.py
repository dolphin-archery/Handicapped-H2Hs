"""In-memory session state for the Handicapped H2H web app.

Per AISpec.md section 3/Assumption 7: single machine, single scorer, no
database, no persistence across process restarts. A single global instance
is deliberately used instead of Flask sessions/cookies, since this is a
single-user local tool for one scorer running one event at a time.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from .models import DEFAULT_TARGET_SETUP, Archer, Event, TargetSetup
from .rotation import Rotation, build_schedule, build_sit_out_schedule

# How many fresh random draws a redraw may try to find pairings that differ from the
# current ones, before accepting whatever it last drew (e.g. with only 2 archers there
# is nothing different to find).
_MAX_REDRAW_ATTEMPTS = 50

# The two setup modes (AISpec.md section 5.1).
SIMPLE = "simple"
ADVANCED = "advanced"


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
    setup_mode : str
        "simple" (one shared distance and face for everyone) or "advanced"
        (each archer's own face type, face size and distance, entered at Stage 2).
    n_archers, total_arrows, target_setup : int | int | TargetSetup
        Stage 1 event configuration (`target_setup` is the shared distance
        and face size, used in simple mode; in advanced mode it only remembers
        the last simple choice).
    shoot_byes : bool
        For an odd `n_archers`: whether the archer with the bye shoots alone
        (True) or sits the pass out, adding passes to the event (False).
        Ignored for an even `n_archers`.
    schedule : list[Rotation] | None
        The rotation schedule built at the end of Stage 1, over archer
        *positions* -- set before archer identities are known.
    pending_archers : list[Archer] | None
        The archers entered at Stage 2, in entry order, awaiting Stage 3.
    assignment : list[int] | None
        The Stage 3 draw: `assignment[position]` is the index into
        `pending_archers` of the archer filling that schedule position.
    event : Event | None
        The full event, built when Stage 3 is confirmed.
    rng : random.Random
        Source of randomness for the Stage 3 draw (injectable for tests).
    clock : Callable[[], datetime]
        Gives the current local date and time, which the exports are stamped with
        (injectable for tests).
    """

    graph_view: bool = False
    n_pass: int = 12
    setup_mode: str = SIMPLE

    n_archers: int | None = None
    total_arrows: int = 60
    target_setup: TargetSetup = DEFAULT_TARGET_SETUP
    shoot_byes: bool = True
    schedule: list[Rotation] | None = None
    pending_archers: list[Archer] | None = None
    assignment: list[int] | None = None
    event: Event | None = None
    rng: random.Random = field(default_factory=random.Random, repr=False, compare=False)
    clock: Callable[[], datetime] = field(default=datetime.now, repr=False, compare=False)

    def start_stage1(
        self,
        n_archers: int,
        total_arrows: int,
        n_pass: int,
        target_setup: TargetSetup,
        shoot_byes: bool = True,
        setup_mode: str = SIMPLE,
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
        target_setup : TargetSetup
            The shared shooting distance and target face size (used in simple
            mode; in advanced mode each archer brings their own at Stage 2).
        shoot_byes : bool, default=True
            Whether the bye archer shoots alone (True) or sits out (False)
            when `n_archers` is odd; ignored for an even `n_archers`. Sitting
            out lengthens the schedule beyond `total_arrows // n_pass`
            rotations (see `build_sit_out_schedule`).
        setup_mode : str, default="simple"
            "simple" or "advanced" (see the class docstring).

        Raises
        ------
        ValueError
            If `n_archers` < 2, `n_pass` does not evenly divide `total_arrows`,
            or `setup_mode` is not "simple" or "advanced".
        """
        if setup_mode not in (SIMPLE, ADVANCED):
            msg = f"Setup mode must be Simple or Advanced, got {setup_mode!r}."
            raise ValueError(msg)
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
        self.target_setup = target_setup
        self.setup_mode = setup_mode
        self.shoot_byes = shoot_byes
        self.schedule = new_schedule
        self.pending_archers = None  # discard any previous archers, draw and event
        self.assignment = None
        self.event = None

    def start_stage2(self, archers: list[Archer]) -> None:
        """Store the entered archers and draw their random assignment (Stage 3 follows).

        No event is built yet: that happens when the draw is confirmed
        (`start_event`). Any previous event is discarded.

        Parameters
        ----------
        archers : list[Archer]
            Exactly `self.n_archers` archers, in entry order (each with their
            own `target_setup` in advanced mode).

        Raises
        ------
        RuntimeError
            If Stage 1 has not been completed yet.
        ValueError
            If the number of archers doesn't match `self.n_archers`, or an
            archer has no `target_setup` in advanced mode.
        """
        if self.schedule is None or self.n_archers is None:
            msg = "Stage 1 must be completed before Stage 2."
            raise RuntimeError(msg)
        if len(archers) != self.n_archers:
            msg = f"Expected {self.n_archers} archers, got {len(archers)}."
            raise ValueError(msg)
        if self.setup_mode == ADVANCED:
            missing = [a.name for a in archers if a.target_setup is None]
            if missing:
                msg = f"Advanced setup needs a target setup for every archer; missing for {missing}."
                raise ValueError(msg)

        self.pending_archers = list(archers)
        self.assignment = None
        self.event = None
        self.redraw_pairings()

    def _pairings_signature(self, assignment: list[int]) -> tuple:
        """A hashable summary of who meets whom, and who byes or sits out, in every pass.

        Two assignments with the same signature give the scorer the same
        pairings, even if they differ in (say) which archer is listed first
        in a pair.

        Parameters
        ----------
        assignment : list[int]
            A position -> `pending_archers` index assignment.

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
            for rotation in self.schedule
        )

    def redraw_pairings(self) -> None:
        """Draw a fresh random assignment of the entered archers to schedule positions.

        A draw whose pairings differ from the current ones is preferred (so
        pressing "Redraw" visibly changes something), trying up to
        `_MAX_REDRAW_ATTEMPTS` times; if none is found (e.g. with only two
        archers) the last draw is kept.

        Raises
        ------
        RuntimeError
            If Stage 2 has not been completed yet.
        """
        if self.pending_archers is None or self.schedule is None:
            msg = "Stage 2 must be completed before pairings can be drawn."
            raise RuntimeError(msg)

        previous = None if self.assignment is None else self._pairings_signature(self.assignment)
        for _ in range(_MAX_REDRAW_ATTEMPTS):
            order = list(range(len(self.pending_archers)))
            self.rng.shuffle(order)
            if previous is None or self._pairings_signature(order) != previous:
                break
        self.assignment = order

    def assigned_archers(self) -> list[Archer]:
        """list[Archer]: the entered archers in schedule-position order, per the current draw.

        Raises
        ------
        RuntimeError
            If Stage 2 has not been completed yet.
        """
        if self.pending_archers is None or self.assignment is None:
            msg = "Stage 2 must be completed before pairings can be drawn."
            raise RuntimeError(msg)
        return [self.pending_archers[i] for i in self.assignment]

    def start_event(self) -> None:
        """Confirm the Stage 3 draw and build the Event from it.

        Raises
        ------
        RuntimeError
            If Stage 2 has not been completed yet.
        """
        if self.schedule is None:
            msg = "Stage 1 must be completed before the event can start."
            raise RuntimeError(msg)
        shared_setup = None if self.setup_mode == ADVANCED else self.target_setup
        self.event = Event(self.assigned_archers(), self.n_pass, shared_setup, self.schedule)

    def toggle_graph_view(self) -> None:
        """Switch graph view (charts and explanation) on or off."""
        self.graph_view = not self.graph_view

    def reset(self) -> None:
        """Clear all event state back to a fresh session."""
        self.graph_view = False
        self.n_pass = 12
        self.setup_mode = SIMPLE
        self.n_archers = None
        self.total_arrows = 60
        self.target_setup = DEFAULT_TARGET_SETUP
        self.shoot_byes = True
        self.schedule = None
        self.pending_archers = None
        self.assignment = None
        self.event = None


# Single shared instance for the whole (single-user, single-process) app.
session = SessionState()
