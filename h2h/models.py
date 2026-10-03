"""Event/rotation data model for handicapped H2H archery events.

Orchestrates the statistics engine (`h2h.stats`) and rotation scheduler
(`h2h.rotation`) over a full rotation-based event, per AISpec.md section 6.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import get_args

from archeryutils import load_rounds
from archeryutils import rounds
from archeryutils import targets

from . import stats
from .rotation import Rotation

# Allowed range of a starting AGB handicap (Specification/feedback.md "Feedback 4").
MIN_HANDICAP = 0
MAX_HANDICAP = 150


def max_arrow_score(target: targets.Target) -> int:
    """The most one arrow can score on a target (10 on a standard face, 9 on a 5-zone one).

    Parameters
    ----------
    target : archeryutils.targets.Target
        The target face.

    Returns
    -------
    int
        The highest ring value of the target's scoring system.
    """
    return int(max(target.face_spec.values()))


def _validate_score(score: float, n_pass: int, max_arrow: int) -> int:
    """Validate a raw pass score and coerce it to an in-range integer.

    Parameters
    ----------
    score : float
        Score to validate; must represent a whole number.
    n_pass : int
        Number of arrows in the pass this score is for.
    max_arrow : int
        The most one arrow can score on the archer's target (`max_arrow_score`).

    Returns
    -------
    int
        The validated score.

    Raises
    ------
    ValueError
        If `score` is not a whole number, or is outside
        `[0, n_pass * max_arrow]`.
    """
    if not float(score).is_integer():
        msg = f"Score must be a whole number, got {score}."
        raise ValueError(msg)
    score = int(score)
    max_score = n_pass * max_arrow
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


# --- Standalone handicap calculator rounds (AISpec.md section 5.5, Assumption 40) -----

INDOOR = "indoor"
OUTDOOR = "outdoor"

# The archeryutils round sets the calculator offers: the rounds the AGB handicap scheme is
# built for. (Australian, visually-impaired, field, experimental and miscellaneous sets are
# left out.)
_CALCULATOR_SETS = {
    INDOOR: (load_rounds.AGB_indoor, load_rounds.WA_indoor),
    OUTDOOR: (
        load_rounds.AGB_outdoor_imperial,
        load_rounds.AGB_outdoor_metric,
        load_rounds.WA_outdoor,
    ),
}
# The round selected when the calculator opens, by kind (archeryutils codenames).
DEFAULT_CALCULATOR_ROUND = {INDOOR: "portsmouth", OUTDOOR: "wa720_70"}


def _is_compound_variant(codename: str) -> bool:
    """Whether a round's codename is a compound variant ("portsmouth_compound", "..._compound_triple")."""
    return codename.endswith(("_compound", "_compound_triple"))


def calculator_rounds(kind: str) -> dict[str, rounds.Round]:
    """The standard rounds the calculator offers for indoor or outdoor shooting.

    Compound variants are not listed separately: the compound option switches a chosen
    indoor round to its variant (see `calculator_round`).

    Parameters
    ----------
    kind : str
        `INDOOR` or `OUTDOOR`.

    Returns
    -------
    dict[str, archeryutils.rounds.Round]
        Codename -> round, each round once, sorted by the round's name.

    Raises
    ------
    ValueError
        If `kind` is neither `INDOOR` nor `OUTDOOR`.
    """
    if kind not in _CALCULATOR_SETS:
        msg = f"Choose indoor or outdoor, got {kind!r}."
        raise ValueError(msg)
    found = {
        codename: rnd
        for round_set in _CALCULATOR_SETS[kind]
        for codename, rnd in round_set.items()
        if not _is_compound_variant(codename)
    }
    return dict(sorted(found.items(), key=lambda item: item[1].name.lower()))


def calculator_round(kind: str, codename: str, compound: bool) -> rounds.Round:
    """Look up the real archeryutils round for a calculator choice.

    Parameters
    ----------
    kind : str
        `INDOOR` or `OUTDOOR`.
    codename : str
        The archeryutils codename of a round in `calculator_rounds(kind)`.
    compound : bool
        Whether the round was shot with a compound bow. Only indoor rounds have a
        compound variant (same face and distance, only the X-ring scoring 10): an indoor
        round with no variant in archeryutils, and any outdoor round, is used as chosen.

    Returns
    -------
    archeryutils.rounds.Round
        The complete round whose scoring the handicap is worked out against.

    Raises
    ------
    ValueError
        If `kind` is invalid or `codename` is not one of that kind's rounds.
    """
    available = calculator_rounds(kind)
    if codename not in available:
        msg = f"'{codename}' is not one of the standard {kind} rounds."
        raise ValueError(msg)
    if compound and kind == INDOOR:
        variant = (
            codename.removesuffix("_triple") + "_compound_triple"
            if codename.endswith("_triple")
            else codename + "_compound"
        )
        for round_set in _CALCULATOR_SETS[INDOOR]:
            if variant in round_set:
                return round_set[variant]
    return available[codename]


# --- Shared target setup (AISpec.md sections 5.1 and 5.2a) --------------------

METRE = "metre"
YARD = "yard"

# The standard distances offered at Stage 1 (Assumption 24), in their own units.
STANDARD_DISTANCES_M = (18, 25, 30, 40, 50, 60, 70, 90)
STANDARD_DISTANCES_YD = (20, 25, 30, 40, 50, 60, 80, 100)
STANDARD_FACE_SIZES_CM = (40, 60, 80, 122)
STANDARD_DISTANCES = tuple((d, METRE) for d in STANDARD_DISTANCES_M) + tuple(
    (d, YARD) for d in STANDARD_DISTANCES_YD
)

# Advanced setup (Assumption 34): the face diameters, in cm, that archeryutils's
# standard rounds use. Superset of the simple-setup sizes.
ADVANCED_FACE_SIZES_CM = (20, 35, 40, 50, 60, 65, 80, 122)

# Readable names for archeryutils's scoring systems (the "face types" of advanced
# setup), in the order they are offered. A test checks this covers every system
# archeryutils has, so one added by a library update is noticed.
_FACE_TYPE_NAMES = {
    "10_zone": "10 zone (standard 10-ring face)",
    "10_zone_compound": "10 zone, compound (inner 10 only)",
    "10_zone_6_ring": "10 zone, 6 ring (small face, rings 10 to 5)",
    "10_zone_5_ring": "10 zone, 5 ring (triple spot, rings 10 to 6)",
    "10_zone_5_ring_compound": "10 zone, 5 ring, compound (triple spot, inner 10 only)",
    "11_zone": "11 zone (inner ring scores 11)",
    "11_zone_6_ring": "11 zone, 6 ring (rings 11 to 5)",
    "11_zone_5_ring": "11 zone, 5 ring (triple spot, rings 11 to 6)",
    "5_zone": "5 zone (gold 9 to white 1, imperial rounds)",
    "WA_field": "WA field (6 to 1)",
    "IFAA_field": "IFAA field (5, 4, 3)",
    "IFAA_field_expert": "IFAA field, expert (5 to 1)",
    "AA_national_field": "AA national field (5 to 1)",
    "Worcester": "Worcester (5 to 1)",
    "Worcester_2_ring": "Worcester, 2 ring (5-spot, 5 and 4)",
    "Beiter_hit_miss": "Beiter hit or miss (1 or 0)",
}
_UNOFFERED_SCORING_SYSTEMS = ("Custom",)  # needs ring data a dropdown cannot supply

# face type value -> readable name, for every scoring system archeryutils offers apart
# from "Custom". A system missing from `_FACE_TYPE_NAMES` is still offered, by its own name.
FACE_TYPES: dict[str, str] = {
    **{key: name for key, name in _FACE_TYPE_NAMES.items() if key in get_args(targets.ScoringSystem)},
    **{
        key: key
        for key in get_args(targets.ScoringSystem)
        if key not in _FACE_TYPE_NAMES and key not in _UNOFFERED_SCORING_SYSTEMS
    },
}
DEFAULT_FACE_TYPE = "10_zone"

# A distance of at most this many metres is treated as indoor (Assumption 22):
# 18 m, 25 m, 20 yd and 25 yd are indoor; 30 m / 30 yd and beyond are outdoor.
INDOOR_MAX_DISTANCE_M = 25.0

_METRES_PER_YARD = 0.9144


def _distance_key(distance: int, unit: str) -> str:
    """The short text form of a distance used in form values, e.g. "18m" or "20yd"."""
    return f"{distance}{'m' if unit == METRE else 'yd'}"


@dataclass(frozen=True)
class TargetSetup:
    """The shooting distance and target face size shared by every archer.

    Attributes
    ----------
    distance : int
        Distance, in `unit`.
    unit : str
        `METRE` or `YARD`.
    face_cm : int
        Target face diameter in centimetres.
    face_type : str | None
        An archeryutils scoring system chosen explicitly (advanced setup), used
        exactly as given. None (simple setup) means the face is the standard
        10-zone one, with the scoring system chosen from the bowstyle by
        `resolve_target`.
    """

    distance: int
    unit: str
    face_cm: int
    face_type: str | None = None

    @property
    def distance_m(self) -> float:
        """float: the distance in metres."""
        return float(self.distance) if self.unit == METRE else self.distance * _METRES_PER_YARD

    @property
    def indoor(self) -> bool:
        """bool: whether the distance counts as indoor (Assumption 22).

        Decides the arrow diameter used in the handicap maths and whether
        Compound archers score the reduced 10.
        """
        return self.distance_m <= INDOOR_MAX_DISTANCE_M

    @property
    def distance_key(self) -> str:
        """str: the distance as used in form values, e.g. "18m" or "20yd"."""
        return _distance_key(self.distance, self.unit)

    @property
    def distance_label(self) -> str:
        """str: the distance for display, e.g. "18 m" or "20 yd"."""
        return f"{self.distance} {'m' if self.unit == METRE else 'yd'}"

    @classmethod
    def parse(cls, distance_key: str, face_cm: str | int) -> TargetSetup:
        """Build a setup from the Stage 1 form values.

        Parameters
        ----------
        distance_key : str
            A distance as in `distance_key`, e.g. "18m" or "20yd".
        face_cm : str | int
            A face diameter in centimetres.

        Returns
        -------
        TargetSetup
            The corresponding setup.

        Raises
        ------
        ValueError
            If either value is not one of the standard options.
        """
        distance, unit = _parse_distance(distance_key)
        face = _parse_face_size(face_cm, STANDARD_FACE_SIZES_CM)
        return cls(distance=distance, unit=unit, face_cm=face)

    @classmethod
    def parse_advanced(
        cls, distance_key: str, face_cm: str | int, face_type: str
    ) -> TargetSetup:
        """Build one archer's setup from the advanced Stage 2 form values.

        Parameters
        ----------
        distance_key : str
            A distance as in `distance_key`, e.g. "18m" or "20yd".
        face_cm : str | int
            A face diameter in centimetres, one of `ADVANCED_FACE_SIZES_CM`.
        face_type : str
            One of the keys of `FACE_TYPES`.

        Returns
        -------
        TargetSetup
            The corresponding setup, with its face type set.

        Raises
        ------
        ValueError
            If any value is not one of the offered options; the message names
            which one.
        """
        distance, unit = _parse_distance(distance_key)
        face = _parse_face_size(face_cm, ADVANCED_FACE_SIZES_CM)
        if face_type not in FACE_TYPES:
            msg = f"'{face_type}' is not one of the target face types."
            raise ValueError(msg)
        return cls(distance=distance, unit=unit, face_cm=face, face_type=face_type)


def _parse_distance(distance_key: str) -> tuple[int, str]:
    """Look a distance key such as "18m" up in the standard distances.

    Returns the `(distance, unit)` pair; raises ValueError if it is not standard.
    """
    by_key = {_distance_key(d, u): (d, u) for d, u in STANDARD_DISTANCES}
    if distance_key not in by_key:
        msg = f"'{distance_key}' is not one of the standard distances."
        raise ValueError(msg)
    return by_key[distance_key]


def _parse_face_size(face_cm: str | int, allowed: tuple[int, ...]) -> int:
    """Convert a submitted face size to an int and check it is one of `allowed`.

    Raises ValueError if it is not a number or not in `allowed`.
    """
    try:
        face = int(face_cm)
    except (TypeError, ValueError):
        face = None
    if face not in allowed:
        msg = f"'{face_cm}' is not one of the standard face sizes."
        raise ValueError(msg)
    return face


# Stage 1's default: 20 yd on a 60 cm face, which is the Portsmouth round.
DEFAULT_TARGET_SETUP = TargetSetup(distance=20, unit=YARD, face_cm=60)


def distance_option_groups() -> dict[str, list[tuple[str, str]]]:
    """The standard distances grouped for a dropdown.

    Returns
    -------
    dict[str, list[tuple[str, str]]]
        `{"Metric": [(value, label), ...], "Imperial": [...]}`, where `value`
        is the form value (e.g. "18m") and `label` the display text ("18 m").
    """
    groups: dict[str, list[tuple[str, str]]] = {"Metric": [], "Imperial": []}
    for distance, unit in STANDARD_DISTANCES:
        setup = TargetSetup(distance, unit, STANDARD_FACE_SIZES_CM[0])
        group = "Metric" if unit == METRE else "Imperial"
        groups[group].append((setup.distance_key, setup.distance_label))
    return groups


def resolve_target(setup: TargetSetup, bowstyle: Bowstyle) -> targets.Target:
    """Resolve an archer's effective target from the target setup and bowstyle.

    Per AISpec.md section 5.2a: the target has the setup's face size and
    distance and its inferred indoor/outdoor flag (which picks the arrow
    diameter in `h2h.stats.per_arrow_pmf`). If the setup names a face type
    (advanced setup) that scoring system is used exactly as given and the
    bowstyle is ignored. Otherwise (simple setup) Compound archers score the
    reduced 10 (`10_zone_compound`, only the X-ring scores 10) when the distance
    is indoor; everyone else, and Compound outdoors, scores the plain `10_zone`
    face (Assumption 23).

    Parameters
    ----------
    setup : TargetSetup
        The distance and face size (and, in advanced setup, the face type).
    bowstyle : Bowstyle | None
        The archer's bowstyle.

    Returns
    -------
    archeryutils.targets.Target
        The target to compute this archer's score distribution against.
    """
    if setup.face_type is not None:
        scoring_system = setup.face_type
    else:
        reduced_ten = bowstyle == Bowstyle.COMPOUND and setup.indoor
        scoring_system = "10_zone_compound" if reduced_ten else "10_zone"
    return targets.Target(
        scoring_system,
        (setup.face_cm, "cm"),
        (setup.distance, setup.unit),
        indoor=setup.indoor,
    )


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
    target_setup : TargetSetup | None
        The archer's own distance, face size and face type (advanced setup).
        None means the event's shared setup applies.
    """

    name: str
    handicap: float
    bowstyle: Bowstyle | None = None
    target_setup: TargetSetup | None = None


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
    decided_by : str | None
        Which step of the tie-break chain decided the pass ("percentile",
        "score" or "closest": the closest to the middle), or None for a bye.
        When it is "closest", the winner is the archer who was ticked.
    """

    rotation_index: int
    archer_index: int
    score: int
    percentile: float
    handicap: float | None
    opponent_index: int | None
    won: bool | None
    decided_by: str | None = None


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
    target_setup : TargetSetup | None
        The shared distance and face size; combined with each archer's
        bowstyle to resolve their target (AISpec.md section 5.2a). An archer's
        own `target_setup` takes precedence; it may be None only if every
        archer has one (advanced setup).
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
        target_setup: TargetSetup,
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
        self.target_setup = target_setup
        self.schedule = schedule
        self.current_rotation_index = 0
        self.results: list[PassResult] = []

        for a in archers:
            if a.target_setup is None and target_setup is None:
                msg = f"Archer {a.name!r} has no target setup and no shared one was given."
                raise ValueError(msg)
        self._targets = [
            resolve_target(a.target_setup or target_setup, a.bowstyle) for a in archers
        ]
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

    def max_score_for(self, archer_index: int) -> int:
        """int: the highest pass score possible on an archer's own target.

        That is `n_pass` times the most one arrow can score on it (10 on a
        standard face, but 9 on a 5-zone face, 11 on an 11-zone one, ...).
        """
        return self.n_pass * max_arrow_score(self._targets[archer_index])

    @property
    def is_complete(self) -> bool:
        """bool: whether the final rotation has been reached and every match in it scored."""
        last = len(self.schedule) - 1
        return self.current_rotation_index == last and self.is_rotation_complete(last)

    def _pair_results(
        self,
        rotation_index: int,
        a: int,
        b: int,
        score_a: int,
        score_b: int,
        closest: int | None = None,
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
        closest : int | None, default=None
            Index of the archer whose arrow was closest to the middle; only
            used if the percentiles and scores are both tied.

        Returns
        -------
        list[PassResult]
            `[a's result, b's result]`, each using that archer's OWN
            distribution/target, with the pass winner decided between them.

        Raises
        ------
        h2h.stats.TieBreakRequired
            If the percentiles and scores are tied and `closest` is None.
        """
        pct_a = stats.percentile(self._distributions[a], score_a)
        pct_b = stats.percentile(self._distributions[b], score_b)
        closest_side = None if closest is None else ("a" if closest == a else "b")
        decision = stats.decide_pass_winner(pct_a, score_a, pct_b, score_b, closest_side)
        winner = decision.winner
        return [
            PassResult(
                rotation_index=rotation_index,
                archer_index=a,
                score=score_a,
                percentile=pct_a,
                handicap=stats.equivalent_handicap(score_a, self.n_pass, self._targets[a]),
                opponent_index=b,
                won=(winner == "a"),
                decided_by=decision.decided_by,
            ),
            PassResult(
                rotation_index=rotation_index,
                archer_index=b,
                score=score_b,
                percentile=pct_b,
                handicap=stats.equivalent_handicap(score_b, self.n_pass, self._targets[b]),
                opponent_index=a,
                won=(winner == "b"),
                decided_by=decision.decided_by,
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
        """list[PassResult]: results recorded so far for one match of a rotation.

        In match order (the first archer's result, then the second's), whatever
        order they were recorded in.
        """
        order = [p for p in match if p is not None]
        found = [
            r
            for r in self.results
            if r.rotation_index == rotation_index and r.archer_index in order
        ]
        return sorted(found, key=lambda r: order.index(r.archer_index))

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

    @property
    def completed_passes(self) -> list[int]:
        """list[int]: the rotations in which every match is scored, in order.

        The leaderboard and per-archer results use only these (AISpec.md
        section 5.4a): a pass that is only partly scored is left out until its
        last match is saved.
        """
        return [i for i in range(len(self.schedule)) if self.is_rotation_complete(i)]

    def record_match(
        self, scores: dict[int, float], closest: int | None = None
    ) -> list[PassResult]:
        """Record one match of the current rotation, replacing any earlier scores for it.

        Parameters
        ----------
        scores : dict[int, float]
            Mapping of archer index to raw score covering exactly one match
            of the current rotation: both archers of a pair, or just the bye
            archer if byes are shot.
        closest : int | None, default=None
            Index of the archer whose arrow was closest to the middle, as
            judged by the archers. Only used if the two percentiles and scores
            are exactly tied (AISpec.md section 5.3 "Tie-break"); otherwise,
            and for a bye match, it is ignored.

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
            rotation, any score is invalid (see `_validate_score`), or
            `closest` is given for a pair but is not one of its two archers.
            Raised before anything is recorded.
        h2h.stats.TieBreakRequired
            (A ValueError.) If the percentiles and scores of a pair are tied
            and `closest` is None. Raised before anything is recorded, so any
            earlier scores for the match stay as they were.
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

        validated = {
            idx: _validate_score(score, self.n_pass, max_arrow_score(self._targets[idx]))
            for idx, score in scores.items()
        }
        a, b = match
        if b is None:
            new_results = [self._solo_result(rotation_index, a, validated[a])]
        else:
            if closest is not None and closest not in (a, b):
                msg = f"The closest-to-the-middle archer must be {a} or {b}, got {closest}."
                raise ValueError(msg)
            new_results = self._pair_results(
                rotation_index, a, b, validated[a], validated[b], closest
            )

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
