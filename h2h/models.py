"""Match/round data model for handicapped H2H archery matches.

Orchestrates the statistics engine (`h2h.stats`) over a single 60-arrow
round, split into equal `n_pass`-arrow passes, per AISpec.md section 6.
"""

from __future__ import annotations

from dataclasses import dataclass

from archeryutils import load_rounds
from archeryutils import rounds as au_rounds
from archeryutils import targets

from . import stats

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
    bowstyle : str | None
        Optional display-only label; never used in any calculation (per
        the exclusion of the bowstyle-variance correction in
        Specification/humanSpec.md).
    """

    name: str
    handicap: float
    bowstyle: str | None = None


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
