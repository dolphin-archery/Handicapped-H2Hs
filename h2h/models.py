"""Event/rotation data model for handicapped H2H archery events.

Orchestrates the statistics engine (`h2h.stats`) and rotation scheduler
(`h2h.rotation`) over a full rotation-based event, per AISpec.md section 6.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from archeryutils import load_rounds
from archeryutils import rounds
from archeryutils import targets

from . import stats
from .rotation import Rotation

# Hard-coded per Specification/feedback.md ("hard code max score per arrow to 10
# for now"); revisit if a target face other than a 10-ring face is supported.
MAX_SCORE_PER_ARROW = 10


def _validate_score(score: float, n_pass: int) -> int:
    """Validate a raw pass score and coerce it to an in-range integer.

    Parameters
    ----------
    score : float
        Score to validate; must represent a whole number.
    n_pass : int
        Number of arrows in the pass this score is for.

    Returns
    -------
    int
        The validated score.

    Raises
    ------
    ValueError
        If `score` is not a whole number, or is outside
        `[0, n_pass * MAX_SCORE_PER_ARROW]`.
    """
    if not float(score).is_integer():
        msg = f"Score must be a whole number, got {score}."
        raise ValueError(msg)
    score = int(score)
    max_score = n_pass * MAX_SCORE_PER_ARROW
    if not (0 <= score <= max_score):
        msg = (
            f"Score must be between 0 and {max_score} for a {n_pass}-arrow "
            f"pass, got {score}."
        )
        raise ValueError(msg)
    return score


class Bowstyle(str, Enum):
    """The bowstyles offered in the archer setup dropdown.

    Per Specification/feedback.md "Feedback 2" (Longbow added in "Feedback
    3"): deliberately a smaller set than archeryutils's own
    `AGB_bowstyles`, which includes several more categories not asked for
    here. Only Compound has a distinct scoring variant (indoors); see
    `resolve_target`.
    """

    RECURVE = "Recurve"
    COMPOUND = "Compound"
    BAREBOW = "Barebow"
    LONGBOW = "Longbow"


class RoundMode(str, Enum):
    """The round-mode choices offered at event setup (AISpec.md section 5.1)."""

    INDOOR_PORTSMOUTH = "indoor_portsmouth"
    INDOOR_WA18 = "indoor_wa18"
    OUTDOOR = "outdoor"


def _outdoor_target() -> targets.Target:
    """The single fixed outdoor target used for every bowstyle (Assumption 12).

    Returns
    -------
    archeryutils.targets.Target
        WA720's 70m / 122cm 10-zone target.
    """
    return load_rounds.WA_outdoor.wa720_70.passes[0].target


def resolve_indoor_round(round_mode: RoundMode, compound: bool) -> rounds.Round:
    """Look up the real archeryutils indoor round for a round mode and bow type.

    Shared by `resolve_target` and the standalone handicap calculator so the
    compound/non-compound round choice (AISpec.md sections 5.2a and 5.5) lives
    in exactly one place.

    Parameters
    ----------
    round_mode : RoundMode
        `INDOOR_PORTSMOUTH` or `INDOOR_WA18`.
    compound : bool
        Whether the round is shot with a compound bow, which selects the
        `*_compound` variant (same face/distance, only the X-ring scores 10).

    Returns
    -------
    archeryutils.rounds.Round
        The complete indoor round (e.g. `portsmouth` or `portsmouth_compound`).

    Raises
    ------
    ValueError
        If `round_mode` is not an indoor round mode.
    """
    if round_mode == RoundMode.INDOOR_PORTSMOUTH:
        return (
            load_rounds.AGB_indoor.portsmouth_compound
            if compound
            else load_rounds.AGB_indoor.portsmouth
        )
    if round_mode == RoundMode.INDOOR_WA18:
        return load_rounds.WA_indoor.wa18_compound if compound else load_rounds.WA_indoor.wa18
    msg = f"{round_mode.value!r} is not an indoor round mode."
    raise ValueError(msg)


def resolve_target(round_mode: RoundMode, bowstyle: Bowstyle) -> targets.Target:
    """Resolve an archer's effective target from round mode and bowstyle.

    Per AISpec.md section 5.2a: indoor Compound archers use the AGB
    indoor-compound scoring variant (same face/distance, only the X-ring
    scores 10) of whichever indoor round is in use; indoor Recurve/Barebow/
    Longbow use the plain variant; outdoor mode uses one single fixed target
    regardless of bowstyle (Assumption 12).

    Parameters
    ----------
    round_mode : RoundMode
        The event's round mode.
    bowstyle : Bowstyle
        The archer's bowstyle.

    Returns
    -------
    archeryutils.targets.Target
        The target to compute this archer's score distribution against.
    """
    if round_mode == RoundMode.OUTDOOR:
        return _outdoor_target()

    rnd = resolve_indoor_round(round_mode, compound=bowstyle == Bowstyle.COMPOUND)
    return rnd.passes[0].target


@dataclass
class Archer:
    """A single archer entered into a match.

    Attributes
    ----------
    name : str
        Archer's display name.
    handicap : float
        Current AGB (2023 scheme) handicap. The sole skill input used in
        calculations.
    bowstyle : Bowstyle | None
        Used by `Event`/`resolve_target` to pick the Compound scoring variant
        when indoor (AISpec.md section 5.2a); optional at the dataclass level
        (Stage 2's form is what enforces a valid selection) since `sigma_r`
        itself remains bowstyle-blind either way (Specification/humanSpec.md).
    """

    name: str
    handicap: float
    bowstyle: Bowstyle | None = None


@dataclass(frozen=True)
class PassResult:
    """One archer's recorded result for one rotation's pass.

    Attributes
    ----------
    rotation_index : int
        Which rotation this pass belongs to.
    archer_index : int
        Index into `Event.archers` of the archer this result is for.
    score : int
        The score they shot.
    percentile : float
        Their percentile under their own score distribution.
    handicap : float | None
        Full-round-equivalent handicap implied by `score` (None if `score`
        is 0).
    opponent_index : int | None
        Index of the archer they faced this rotation, or None if they had
        the bye.
    won : bool | None
        Whether they won the pass, or None if they had the bye (no
        opponent to compare against).
    """

    rotation_index: int
    archer_index: int
    score: int
    percentile: float
    handicap: float | None
    opponent_index: int | None
    won: bool | None


@dataclass(frozen=True)
class PairwiseResult:
    """Aggregated head-to-head result between two archers.

    Attributes
    ----------
    archer_a, archer_b : int
        The two archers' indices.
    wins_a, wins_b : int
        How many of their shared passes each won.
    """

    archer_a: int
    archer_b: int
    wins_a: int
    wins_b: int

    @property
    def outcome(self) -> int | str:
        """int | str: the winning archer's index, or "draw"."""
        if self.wins_a > self.wins_b:
            return self.archer_a
        if self.wins_b > self.wins_a:
            return self.archer_b
        return "draw"


class Event:
    """A full H2H event: archers rotating opponents every n_pass arrows.

    Each archer's score distribution depends only on their own handicap and
    resolved target (`resolve_target`) -- not on who they face -- so it is
    precomputed once per archer at construction time.

    Parameters
    ----------
    archers : list[Archer]
        Archers in schedule-position order (archer i corresponds to
        `schedule`'s archer-index i).
    n_pass : int
        Number of arrows per rotation's pass.
    round_mode : RoundMode
        The event's round mode; combined with each archer's bowstyle to
        resolve their target (AISpec.md section 5.2a).
    schedule : list[h2h.rotation.Rotation]
        The rotation schedule (built by `h2h.rotation.build_schedule` or, when
        bye archers sit out, `build_sit_out_schedule`, before archers were
        known -- see AISpec.md sections 5.1 and 5.3).

    Attributes
    ----------
    current_rotation_index : int
        Index of the rotation (pass) currently being shot; moves forward only
        via `advance`.
    results : list[PassResult]
        Every recorded result so far, across all rotations.
    """

    def __init__(
        self,
        archers: list[Archer],
        n_pass: int,
        round_mode: RoundMode,
        schedule: list[Rotation],
    ) -> None:
        max_index = -1
        for rotation in schedule:
            referenced = [p for match in rotation.matches for p in match if p is not None]
            referenced.extend(rotation.sitting_out)
            if referenced:
                max_index = max(max_index, max(referenced))
        if max_index >= len(archers):
            msg = (
                f"Schedule references archer index {max_index}, but only "
                f"{len(archers)} archers were provided."
            )
            raise ValueError(msg)

        self.archers = archers
        self.n_pass = n_pass
        self.round_mode = round_mode
        self.schedule = schedule
        self.current_rotation_index = 0
        self.results: list[PassResult] = []

        self._targets = [resolve_target(round_mode, a.bowstyle) for a in archers]
        self._distributions = [
            stats.n_pass_score_distribution(stats.per_arrow_pmf(a.handicap, t), n_pass)
            for a, t in zip(archers, self._targets, strict=True)
        ]

    def target_for(self, archer_index: int) -> targets.Target:
        """archeryutils.targets.Target: the resolved target for an archer."""
        return self._targets[archer_index]

    def distribution_for(self, archer_index: int) -> dict[float, float]:
        """dict[float, float]: an archer's own n_pass score distribution."""
        return self._distributions[archer_index]

    @property
    def is_complete(self) -> bool:
        """bool: whether the final rotation has been reached and every match in it scored."""
        last = len(self.schedule) - 1
        return self.current_rotation_index == last and self.is_rotation_complete(last)

    def _pair_results(
        self, rotation_index: int, a: int, b: int, score_a: int, score_b: int
    ) -> list[PassResult]:
        """Build both archers' results for a head-to-head match (nothing is stored).

        Parameters
        ----------
        rotation_index : int
            Rotation the match belongs to.
        a, b : int
            The two archers' indices.
        score_a, score_b : int
            Their already-validated scores.

        Returns
        -------
        list[PassResult]
            `[a's result, b's result]`, each using that archer's OWN
            distribution/target, with the pass winner decided between them.
        """
        pct_a = stats.percentile(self._distributions[a], score_a)
        pct_b = stats.percentile(self._distributions[b], score_b)
        winner = stats.decide_pass_winner(pct_a, score_a, pct_b, score_b)
        return [
            PassResult(
                rotation_index=rotation_index,
                archer_index=a,
                score=score_a,
                percentile=pct_a,
                handicap=stats.equivalent_handicap(score_a, self.n_pass, self._targets[a]),
                opponent_index=b,
                won=(winner == "a"),
            ),
            PassResult(
                rotation_index=rotation_index,
                archer_index=b,
                score=score_b,
                percentile=pct_b,
                handicap=stats.equivalent_handicap(score_b, self.n_pass, self._targets[b]),
                opponent_index=a,
                won=(winner == "b"),
            ),
        ]

    def _solo_result(self, rotation_index: int, archer: int, score: int) -> PassResult:
        """Build the result for an archer shooting a bye match alone (nothing is stored).

        Parameters
        ----------
        rotation_index : int
            Rotation the match belongs to.
        archer : int
            The archer's index.
        score : int
            Their already-validated score.

        Returns
        -------
        PassResult
            Result with no opponent and no winner (nothing to compare against).
        """
        return PassResult(
            rotation_index=rotation_index,
            archer_index=archer,
            score=score,
            percentile=stats.percentile(self._distributions[archer], score),
            handicap=stats.equivalent_handicap(score, self.n_pass, self._targets[archer]),
            opponent_index=None,
            won=None,
        )

    def matches(self, rotation_index: int) -> list[tuple[int, int | None]]:
        """list[tuple[int, int | None]]: a rotation's matches (pairs, then any bye match)."""
        return self.schedule[rotation_index].matches

    def match_results(
        self, rotation_index: int, match: tuple[int, int | None]
    ) -> list[PassResult]:
        """list[PassResult]: results recorded so far for one match of a rotation."""
        archers = {p for p in match if p is not None}
        return [
            r
            for r in self.results
            if r.rotation_index == rotation_index and r.archer_index in archers
        ]

    def pair_results(self, a: int, b: int) -> list[PassResult]:
        """list[PassResult]: both archers' results for every pass `a` and `b` have shared.

        Ordered by pass, with each pass's two results kept together. Empty if
        the pair has not shared a scored rotation yet.
        """
        shared = [
            r
            for r in self.results
            if (r.archer_index, r.opponent_index) in ((a, b), (b, a))
        ]
        return sorted(shared, key=lambda r: r.rotation_index)

    def is_match_scored(self, rotation_index: int, match_index: int) -> bool:
        """bool: whether the match at `match_index` in a rotation has scores recorded."""
        match = self.matches(rotation_index)[match_index]
        return bool(self.match_results(rotation_index, match))

    def is_rotation_complete(self, rotation_index: int) -> bool:
        """bool: whether every match in a rotation has scores recorded."""
        return all(
            self.is_match_scored(rotation_index, i)
            for i in range(len(self.matches(rotation_index)))
        )

    def record_match(self, scores: dict[int, float]) -> list[PassResult]:
        """Record one match of the current rotation, replacing any earlier scores for it.

        Parameters
        ----------
        scores : dict[int, float]
            Mapping of archer index to raw score covering exactly one match
            of the current rotation: both archers of a pair, or just the bye
            archer if byes are shot.

        Returns
        -------
        list[PassResult]
            The results recorded for this match (one per archer). If the
            match had already been scored, they replace the earlier results
            in place (same position in `results`), so a mistyped score can be
            corrected until the rotation is advanced past.

        Raises
        ------
        ValueError
            If `scores`' keys are not exactly one match of the current
            rotation, or any score is invalid (see `_validate_score`).
            Raised before anything is recorded.
        """
        rotation_index = self.current_rotation_index
        match = next(
            (
                m
                for m in self.matches(rotation_index)
                if {p for p in m if p is not None} == set(scores)
            ),
            None,
        )
        if match is None:
            msg = (
                f"Scores must be for exactly one match in pass {rotation_index + 1}; "
                f"got archers {sorted(scores)}."
            )
            raise ValueError(msg)

        validated = {idx: _validate_score(score, self.n_pass) for idx, score in scores.items()}
        a, b = match
        if b is None:
            new_results = [self._solo_result(rotation_index, a, validated[a])]
        else:
            new_results = self._pair_results(rotation_index, a, b, validated[a], validated[b])

        for new in new_results:
            existing = next(
                (
                    i
                    for i, r in enumerate(self.results)
                    if r.rotation_index == new.rotation_index and r.archer_index == new.archer_index
                ),
                None,
            )
            if existing is None:
                self.results.append(new)
            else:
                self.results[existing] = new
        return new_results

    def advance(self) -> None:
        """Move on to the next rotation, once every match in the current one is scored.

        Raises
        ------
        ValueError
            If the current rotation still has unscored matches, or it is the
            final rotation (there is no next one).
        """
        if not self.is_rotation_complete(self.current_rotation_index):
            msg = "Every match in the current pass must have scores before advancing."
            raise ValueError(msg)
        if self.current_rotation_index >= len(self.schedule) - 1:
            msg = "This is the final pass; there is no next pass to advance to."
            raise ValueError(msg)
        self.current_rotation_index += 1

    def pairwise_result(self, a: int, b: int) -> PairwiseResult | None:
        """Aggregated head-to-head result between two archers so far.

        Parameters
        ----------
        a, b : int
            The two archers' indices.

        Returns
        -------
        PairwiseResult | None
            None if `a` and `b` have not yet shared a rotation.
        """
        wins_a = sum(1 for r in self.results if r.archer_index == a and r.opponent_index == b and r.won)
        wins_b = sum(1 for r in self.results if r.archer_index == b and r.opponent_index == a and r.won)
        shared = any(r.archer_index == a and r.opponent_index == b for r in self.results)
        if not shared:
            return None
        return PairwiseResult(archer_a=a, archer_b=b, wins_a=wins_a, wins_b=wins_b)

    def all_pairwise_results(self) -> list[PairwiseResult]:
        """Every pairwise result for pairs that have shared at least one rotation.

        Returns
        -------
        list[PairwiseResult]
            Sorted by (archer_a, archer_b) for deterministic display.
        """
        pairs = sorted(
            {
                tuple(sorted((r.archer_index, r.opponent_index)))
                for r in self.results
                if r.opponent_index is not None
            }
        )
        return [self.pairwise_result(a, b) for a, b in pairs]
