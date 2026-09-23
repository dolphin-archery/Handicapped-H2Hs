"""Match/round data model for handicapped H2H archery matches.

Orchestrates the statistics engine (`h2h.stats`) over a single 60-arrow
round, split into equal `n_pass`-arrow passes, per AISpec.md section 6.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from archeryutils import load_rounds
from archeryutils import rounds as au_rounds
from archeryutils import targets

from . import stats
from .rotation import Rotation

TOTAL_ARROWS = 60
VALID_N_PASS = tuple(n for n in range(1, TOTAL_ARROWS + 1) if TOTAL_ARROWS % n == 0)
DEFAULT_N_PASS = 12

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


def default_round() -> tuple[au_rounds.Round, targets.Target]:
    """Return the default 60-arrow round and its canonical target.

    Returns
    -------
    tuple[archeryutils.rounds.Round, archeryutils.targets.Target]
        The Portsmouth round object, and the target used by its passes.
        Portsmouth's two archeryutils passes share an identical
        target/distance, so either may be used to compute score
        distributions for the round as a whole (see Assumption 1 in
        Specification/logbook.md).
    """
    rnd = load_rounds.AGB_indoor.portsmouth
    return rnd, rnd.passes[0].target


class Bowstyle(str, Enum):
    """The three bowstyles offered in the archer setup dropdown.

    Per Specification/feedback.md "Feedback 2": deliberately a smaller set
    than archeryutils's own `AGB_bowstyles`, which includes several more
    categories not asked for here.
    """

    RECURVE = "Recurve"
    COMPOUND = "Compound"
    BAREBOW = "Barebow"


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


def resolve_target(round_mode: RoundMode, bowstyle: Bowstyle) -> targets.Target:
    """Resolve an archer's effective target from round mode and bowstyle.

    Per AISpec.md section 5.2a: indoor Compound archers use the AGB
    indoor-compound scoring variant (same face/distance, only the X-ring
    scores 10) of whichever indoor round is in use; indoor Recurve/Barebow use
    the plain variant; outdoor mode uses one single fixed target regardless of
    bowstyle (Assumption 12).

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

    is_compound = bowstyle == Bowstyle.COMPOUND
    if round_mode == RoundMode.INDOOR_PORTSMOUTH:
        rnd = (
            load_rounds.AGB_indoor.portsmouth_compound
            if is_compound
            else load_rounds.AGB_indoor.portsmouth
        )
    else:  # RoundMode.INDOOR_WA18
        rnd = (
            load_rounds.WA_indoor.wa18_compound if is_compound else load_rounds.WA_indoor.wa18
        )
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
        Required for events using `Event`/`resolve_target` (indoor mode uses
        it to pick the Compound scoring variant, per AISpec.md section 5.2a).
        Optional here (default None) only because the older, single-pair
        `Match` flow never reads it; `sigma_r` itself remains bowstyle-blind
        either way (Specification/humanSpec.md).
    """

    name: str
    handicap: float
    bowstyle: Bowstyle | None = None


@dataclass
class Pass:
    """A single scored pass within a match.

    Attributes
    ----------
    pass_index : int
        0-based index of this pass within the match.
    score_a, score_b : int | None
        Recorded pass score for each archer, or None if not yet entered.
    percentile_a, percentile_b : float | None
        Each archer's percentile for this pass, once scored.
    handicap_a, handicap_b : float | None
        Full-round-equivalent AGB handicap implied by that pass score (see
        `h2h.stats.equivalent_handicap`), or None if the score was 0.
    winner : str | None
        "a", "b", or None if not yet scored.
    """

    pass_index: int
    score_a: int | None = None
    score_b: int | None = None
    percentile_a: float | None = None
    percentile_b: float | None = None
    handicap_a: float | None = None
    handicap_b: float | None = None
    winner: str | None = None

    @property
    def is_scored(self) -> bool:
        """bool: whether this pass has been scored."""
        return self.winner is not None


class Match:
    """A single H2H match between two archers over one 60-arrow round.

    Parameters
    ----------
    archer_a, archer_b : Archer
        The two archers competing.
    n_pass : int
        Number of arrows per pass; must be in `VALID_N_PASS`.
    target : archeryutils.targets.Target | None, default=None
        Target to use for score distributions; defaults to
        `default_round()`'s target.

    Attributes
    ----------
    passes : list[Pass]
        One Pass per `TOTAL_ARROWS / n_pass` passes in the match, in order.
    """

    def __init__(
        self,
        archer_a: Archer,
        archer_b: Archer,
        n_pass: int,
        target: targets.Target | None = None,
    ) -> None:
        if n_pass not in VALID_N_PASS:
            msg = (
                f"Arrows per pass must be one of {VALID_N_PASS} so a "
                f"{TOTAL_ARROWS}-arrow round divides evenly; got {n_pass}."
            )
            raise ValueError(msg)

        self.archer_a = archer_a
        self.archer_b = archer_b
        self.n_pass = n_pass
        self.target = target if target is not None else default_round()[1]

        n_passes = TOTAL_ARROWS // n_pass
        self.passes: list[Pass] = [Pass(pass_index=i) for i in range(n_passes)]

        self._dist_a = stats.n_pass_score_distribution(
            stats.per_arrow_pmf(archer_a.handicap, self.target), n_pass
        )
        self._dist_b = stats.n_pass_score_distribution(
            stats.per_arrow_pmf(archer_b.handicap, self.target), n_pass
        )

    def distribution_for(self, archer: str) -> dict[float, float]:
        """Return the pre-computed n_pass score distribution for an archer.

        Parameters
        ----------
        archer : str
            "a" or "b".

        Returns
        -------
        dict[float, float]
            That archer's n_pass score distribution.
        """
        return self._dist_a if archer == "a" else self._dist_b

    def next_pass_index(self) -> int | None:
        """int | None: index of the next unscored pass, or None if all are scored."""
        for p in self.passes:
            if not p.is_scored:
                return p.pass_index
        return None

    def record_pass(self, pass_index: int, score_a: float, score_b: float) -> Pass:
        """Record both archers' scores for a pass and decide its winner.

        Parameters
        ----------
        pass_index : int
            Index of the pass being scored.
        score_a, score_b : float
            Raw scores shot by archer_a and archer_b for this pass; each must
            be a whole number in `[0, n_pass * MAX_SCORE_PER_ARROW]`.

        Returns
        -------
        Pass
            The updated Pass object.

        Raises
        ------
        ValueError
            If either score is not a whole number or is out of range. Raised
            before anything is recorded, so a rejected call leaves the pass
            untouched.
        """
        score_a = _validate_score(score_a, self.n_pass)
        score_b = _validate_score(score_b, self.n_pass)

        p = self.passes[pass_index]
        p.score_a = score_a
        p.score_b = score_b
        p.percentile_a = stats.percentile(self._dist_a, score_a)
        p.percentile_b = stats.percentile(self._dist_b, score_b)
        p.handicap_a = stats.equivalent_handicap(score_a, self.n_pass, self.target)
        p.handicap_b = stats.equivalent_handicap(score_b, self.n_pass, self.target)
        p.winner = stats.decide_pass_winner(
            p.percentile_a, score_a, p.percentile_b, score_b
        )
        return p

    @property
    def is_complete(self) -> bool:
        """bool: whether every pass in the match has been scored."""
        return all(p.is_scored for p in self.passes)

    @property
    def pass_wins(self) -> tuple[int, int]:
        """tuple[int, int]: (archer_a wins, archer_b wins) among scored passes."""
        wins_a = sum(1 for p in self.passes if p.winner == "a")
        wins_b = sum(1 for p in self.passes if p.winner == "b")
        return wins_a, wins_b

    def result(self) -> str:
        """Determine the overall match result.

        Returns
        -------
        str
            "a" or "b" if that archer won a strict majority of passes,
            otherwise "draw".

        Raises
        ------
        RuntimeError
            If not all passes have been scored yet.
        """
        if not self.is_complete:
            msg = "Cannot compute match result before all passes are scored."
            raise RuntimeError(msg)
        wins_a, wins_b = self.pass_wins
        if wins_a > wins_b:
            return "a"
        if wins_b > wins_a:
            return "b"
        return "draw"


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

    Replaces the old fixed-pair `Match` (Specification/feedback.md
    "Feedback 2"). Each archer's score distribution depends only on their
    own handicap and resolved target (`resolve_target`) -- not on who they
    face -- so it is precomputed once per archer at construction time.

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
        The rotation schedule (built by `h2h.rotation.build_schedule` before
        archers were known -- see AISpec.md section 5.1).

    Attributes
    ----------
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
            participants = [p for pair in rotation.pairs for p in pair]
            if rotation.bye is not None:
                participants.append(rotation.bye)
            if participants:
                max_index = max(max_index, max(participants))
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

    def next_rotation_index(self) -> int | None:
        """int | None: index of the next unscored rotation, or None if done."""
        scored = {r.rotation_index for r in self.results}
        for i in range(len(self.schedule)):
            if i not in scored:
                return i
        return None

    @property
    def is_complete(self) -> bool:
        """bool: whether every rotation has been scored."""
        return self.next_rotation_index() is None

    def record_rotation(self, rotation_index: int, scores: dict[int, float]) -> list[PassResult]:
        """Record every archer's score for a rotation and derive results.

        Parameters
        ----------
        rotation_index : int
            Index of the rotation being scored.
        scores : dict[int, float]
            Mapping of archer index to raw score, covering exactly the
            archers active in this rotation (every paired archer, plus the
            bye archer if there is one).

        Returns
        -------
        list[PassResult]
            The results recorded for this rotation, one per participant.

        Raises
        ------
        ValueError
            If `scores`' keys don't exactly match the rotation's
            participants, or any score is invalid (see `_validate_score`).
            Raised before anything is recorded.
        """
        rotation = self.schedule[rotation_index]
        expected = {p for pair in rotation.pairs for p in pair}
        if rotation.bye is not None:
            expected.add(rotation.bye)
        if set(scores) != expected:
            msg = (
                f"Scores must be provided for exactly rotation {rotation_index}'s "
                f"participants {sorted(expected)}; got {sorted(scores)}."
            )
            raise ValueError(msg)

        validated = {idx: _validate_score(score, self.n_pass) for idx, score in scores.items()}

        results: list[PassResult] = []
        for a, b in rotation.pairs:
            score_a, score_b = validated[a], validated[b]
            pct_a = stats.percentile(self._distributions[a], score_a)
            pct_b = stats.percentile(self._distributions[b], score_b)
            winner = stats.decide_pass_winner(pct_a, score_a, pct_b, score_b)
            results.append(
                PassResult(
                    rotation_index=rotation_index,
                    archer_index=a,
                    score=score_a,
                    percentile=pct_a,
                    handicap=stats.equivalent_handicap(score_a, self.n_pass, self._targets[a]),
                    opponent_index=b,
                    won=(winner == "a"),
                )
            )
            results.append(
                PassResult(
                    rotation_index=rotation_index,
                    archer_index=b,
                    score=score_b,
                    percentile=pct_b,
                    handicap=stats.equivalent_handicap(score_b, self.n_pass, self._targets[b]),
                    opponent_index=a,
                    won=(winner == "b"),
                )
            )

        if rotation.bye is not None:
            bye_idx = rotation.bye
            score_bye = validated[bye_idx]
            results.append(
                PassResult(
                    rotation_index=rotation_index,
                    archer_index=bye_idx,
                    score=score_bye,
                    percentile=stats.percentile(self._distributions[bye_idx], score_bye),
                    handicap=stats.equivalent_handicap(
                        score_bye, self.n_pass, self._targets[bye_idx]
                    ),
                    opponent_index=None,
                    won=None,
                )
            )

        self.results.extend(results)
        return results

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
