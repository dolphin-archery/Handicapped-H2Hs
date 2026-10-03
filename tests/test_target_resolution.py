"""Tests for h2h.models.TargetSetup and resolve_target (setup x bowstyle -> Target)."""

import itertools
import math

import pytest
from archeryutils import load_rounds

from h2h import stats
from h2h.models import (
    DEFAULT_TARGET_SETUP,
    METRE,
    STANDARD_DISTANCES,
    STANDARD_FACE_SIZES_CM,
    YARD,
    Bowstyle,
    IndoorRound,
    TargetSetup,
    distance_option_groups,
    resolve_indoor_round,
    resolve_target,
)

from .helpers import OUTDOOR_70M, PORTSMOUTH, WA18

NON_COMPOUND = (Bowstyle.RECURVE, Bowstyle.BAREBOW, Bowstyle.LONGBOW)


# --- TargetSetup: indoor inference, units, option lists ------------------------


@pytest.mark.parametrize(
    ("distance", "unit"),
    [(18, METRE), (25, METRE), (20, YARD), (25, YARD)],
)
def test_distances_up_to_25_m_count_as_indoor(distance, unit):
    """18 m, 25 m, 20 yd and 25 yd are indoor."""
    assert TargetSetup(distance, unit, 60).indoor is True


@pytest.mark.parametrize(
    ("distance", "unit"),
    [(30, METRE), (40, METRE), (50, METRE), (70, METRE), (90, METRE),
     (30, YARD), (40, YARD), (80, YARD), (100, YARD)],
)
def test_distances_from_30_m_or_30_yd_count_as_outdoor(distance, unit):
    """30 m / 30 yd and beyond are outdoor (nothing beyond 30 m is indoor in archeryutils)."""
    assert TargetSetup(distance, unit, 122).indoor is False


def test_distance_in_metres_converts_yards_exactly():
    """A yard is 0.9144 m: 20 yd = 18.288 m, 100 yd = 91.44 m; metres are unchanged."""
    assert TargetSetup(20, YARD, 60).distance_m == pytest.approx(18.288)
    assert TargetSetup(100, YARD, 60).distance_m == pytest.approx(91.44)
    assert TargetSetup(18, METRE, 40).distance_m == 18.0


def test_distance_keys_and_labels():
    """Form values look like '18m' / '20yd' and labels like '18 m' / '20 yd'."""
    assert TargetSetup(18, METRE, 40).distance_key == "18m"
    assert TargetSetup(20, YARD, 60).distance_key == "20yd"
    assert TargetSetup(18, METRE, 40).distance_label == "18 m"
    assert TargetSetup(20, YARD, 60).distance_label == "20 yd"


def test_standard_options_are_exactly_the_agreed_lists():
    """8 metric + 8 imperial distances, 4 face sizes, grouped Metric / Imperial."""
    groups = distance_option_groups()
    assert list(groups) == ["Metric", "Imperial"]
    assert [v for v, _ in groups["Metric"]] == [
        "18m", "25m", "30m", "40m", "50m", "60m", "70m", "90m"
    ]
    assert [v for v, _ in groups["Imperial"]] == [
        "20yd", "25yd", "30yd", "40yd", "50yd", "60yd", "80yd", "100yd"
    ]
    assert dict(groups["Metric"])["18m"] == "18 m"
    assert dict(groups["Imperial"])["100yd"] == "100 yd"
    assert STANDARD_FACE_SIZES_CM == (40, 60, 80, 122)
    assert len(STANDARD_DISTANCES) == 16


def test_default_setup_is_20_yd_on_a_60_cm_face():
    """The default is the Portsmouth setup."""
    assert DEFAULT_TARGET_SETUP == TargetSetup(20, YARD, 60) == PORTSMOUTH


def test_parse_accepts_standard_values_from_the_form():
    """parse builds a setup from the form's distance key and face size."""
    assert TargetSetup.parse("50m", "80") == TargetSetup(50, METRE, 80)
    assert TargetSetup.parse("100yd", 122) == TargetSetup(100, YARD, 122)


@pytest.mark.parametrize("bad_distance", ["20m", "18", "abc", "", "18 m", "20YD"])
def test_parse_rejects_non_standard_distances(bad_distance):
    """Anything outside the offered distances is a ValueError."""
    with pytest.raises(ValueError, match="standard distances"):
        TargetSetup.parse(bad_distance, 60)


@pytest.mark.parametrize("bad_face", ["50", "abc", "", "0", "40.5", None])
def test_parse_rejects_non_standard_face_sizes(bad_face):
    """Anything outside the offered face sizes is a ValueError."""
    with pytest.raises(ValueError, match="standard face sizes"):
        TargetSetup.parse("18m", bad_face)


# --- resolve_target ----------------------------------------------------------


def test_compound_indoors_gets_the_reduced_10():
    """Compound at an indoor distance scores 10_zone_compound."""
    for setup in (PORTSMOUTH, WA18, TargetSetup(25, METRE, 60)):
        assert resolve_target(setup, Bowstyle.COMPOUND).scoring_system == "10_zone_compound"


def test_compound_outdoors_scores_the_plain_face():
    """Compound at an outdoor distance scores the plain 10_zone (Assumption 23)."""
    for setup in (OUTDOOR_70M, TargetSetup(30, METRE, 80), TargetSetup(30, YARD, 60)):
        assert resolve_target(setup, Bowstyle.COMPOUND).scoring_system == "10_zone"


@pytest.mark.parametrize("bowstyle", NON_COMPOUND)
@pytest.mark.parametrize("setup", [PORTSMOUTH, WA18, OUTDOOR_70M, TargetSetup(50, METRE, 80)])
def test_non_compound_bowstyles_always_score_the_plain_face(setup, bowstyle):
    """Recurve, Barebow and Longbow score 10_zone at every distance."""
    assert resolve_target(setup, bowstyle).scoring_system == "10_zone"


@pytest.mark.parametrize("bowstyle", list(Bowstyle))
def test_target_has_the_chosen_face_distance_and_inferred_indoor_flag(bowstyle):
    """The Target carries the setup's diameter, distance and indoor classification."""
    for setup in (PORTSMOUTH, WA18, OUTDOOR_70M, TargetSetup(40, YARD, 80)):
        target = resolve_target(setup, bowstyle)
        assert target.diameter == pytest.approx(setup.face_cm / 100)
        assert target.distance == pytest.approx(setup.distance_m)
        assert target.indoor is setup.indoor


def test_longbow_matches_recurve_at_every_standard_distance_and_face():
    """Longbow has no scoring variant of its own, anywhere."""
    for (distance, unit), face in itertools.product(STANDARD_DISTANCES, STANDARD_FACE_SIZES_CM):
        setup = TargetSetup(distance, unit, face)
        assert resolve_target(setup, Bowstyle.LONGBOW) == resolve_target(setup, Bowstyle.RECURVE)


# --- agreement with archeryutils's own rounds ----------------------------------


def test_portsmouth_setup_equals_archeryutils_portsmouth():
    """20 yd / 60 cm is archeryutils's Portsmouth target, and compound its compound variant."""
    assert resolve_target(PORTSMOUTH, Bowstyle.RECURVE) == (
        load_rounds.AGB_indoor.portsmouth.passes[0].target
    )
    assert resolve_target(PORTSMOUTH, Bowstyle.COMPOUND) == (
        load_rounds.AGB_indoor.portsmouth_compound.passes[0].target
    )


def test_wa18_setup_equals_archeryutils_wa18():
    """18 m / 40 cm is archeryutils's WA 18 target, and compound its compound variant."""
    assert resolve_target(WA18, Bowstyle.RECURVE) == load_rounds.WA_indoor.wa18.passes[0].target
    assert resolve_target(WA18, Bowstyle.COMPOUND) == (
        load_rounds.WA_indoor.wa18_compound.passes[0].target
    )


def test_70m_122cm_setup_equals_archeryutils_wa720_70():
    """70 m / 122 cm is archeryutils's WA 720 70 m target, for every bowstyle."""
    expected = load_rounds.WA_outdoor.wa720_70.passes[0].target
    for bowstyle in Bowstyle:
        assert resolve_target(OUTDOOR_70M, bowstyle) == expected


# --- every offered combination works in the stats engine -------------------------


@pytest.mark.parametrize("handicap", [0, 40, 100, 150])
def test_every_offered_combination_gives_a_valid_pmf_at_any_handicap(handicap):
    """Every distance x face x bowstyle-kind gives a PMF that sums to 1 with no negatives."""
    for (distance, unit), face, bowstyle in itertools.product(
        STANDARD_DISTANCES, STANDARD_FACE_SIZES_CM, (Bowstyle.RECURVE, Bowstyle.COMPOUND)
    ):
        target = resolve_target(TargetSetup(distance, unit, face), bowstyle)
        pmf = stats.per_arrow_pmf(handicap, target)
        assert math.isclose(sum(pmf.values()), 1.0, abs_tol=1e-9)
        assert all(p >= 0 for p in pmf.values())


# --- the calculator's named rounds (unchanged behaviour) ---------------------------


def test_resolve_indoor_round_returns_the_real_archeryutils_rounds():
    """Each named round x compound flag maps to the matching archeryutils round."""
    assert resolve_indoor_round(IndoorRound.PORTSMOUTH, compound=False) is (
        load_rounds.AGB_indoor.portsmouth
    )
    assert resolve_indoor_round(IndoorRound.PORTSMOUTH, compound=True) is (
        load_rounds.AGB_indoor.portsmouth_compound
    )
    assert resolve_indoor_round(IndoorRound.WA18, compound=False) is load_rounds.WA_indoor.wa18
    assert resolve_indoor_round(IndoorRound.WA18, compound=True) is (
        load_rounds.WA_indoor.wa18_compound
    )


# --- Feedback 5: advanced setup - explicit face types, per-target maximum ------------

from typing import get_args  # noqa: E402

from archeryutils import targets as au_targets  # noqa: E402

from h2h.models import (  # noqa: E402
    ADVANCED_FACE_SIZES_CM,
    FACE_TYPES,
    max_arrow_score,
)

ALL_SYSTEMS = [s for s in get_args(au_targets.ScoringSystem) if s != "Custom"]


def test_face_types_are_every_archeryutils_scoring_system_except_custom():
    """The dropdown offers exactly what archeryutils has (a library addition fails this test)."""
    assert set(FACE_TYPES) == set(ALL_SYSTEMS)
    assert len(FACE_TYPES) == 16
    assert all(isinstance(name, str) and name.strip() for name in FACE_TYPES.values())


def test_every_face_type_has_a_curated_readable_name_not_just_its_key():
    """Each system has a hand-written name (so the dropdown never shows a raw key)."""
    from h2h.models import _FACE_TYPE_NAMES

    assert set(_FACE_TYPE_NAMES) == set(ALL_SYSTEMS)
    assert all(FACE_TYPES[key] == name for key, name in _FACE_TYPE_NAMES.items())


def test_advanced_face_sizes_are_the_diameters_archeryutils_rounds_use():
    """20, 35, 40, 50, 60, 65, 80, 122 cm, and they include every simple-mode size."""
    assert ADVANCED_FACE_SIZES_CM == (20, 35, 40, 50, 60, 65, 80, 122)
    assert set(STANDARD_FACE_SIZES_CM) <= set(ADVANCED_FACE_SIZES_CM)


@pytest.mark.parametrize("bowstyle", list(Bowstyle))
@pytest.mark.parametrize("face_type", ALL_SYSTEMS)
def test_a_chosen_face_type_is_used_exactly_whatever_the_bowstyle(face_type, bowstyle):
    """Advanced setup: the scoring system, diameter, distance and indoor flag come from the setup."""
    setup = TargetSetup(distance=18, unit=METRE, face_cm=40, face_type=face_type)
    target = resolve_target(setup, bowstyle)
    assert target.scoring_system == face_type
    assert target.diameter == pytest.approx(0.4)
    assert target.distance == pytest.approx(18.0)
    assert target.indoor is True


def test_a_chosen_face_type_overrides_the_compound_rule_both_ways():
    """A Compound archer given 10_zone indoors scores the plain face; others can be given the reduced 10."""
    indoor = TargetSetup(20, YARD, 60, face_type="10_zone")
    assert resolve_target(indoor, Bowstyle.COMPOUND).scoring_system == "10_zone"
    reduced = TargetSetup(20, YARD, 60, face_type="10_zone_compound")
    assert resolve_target(reduced, Bowstyle.RECURVE).scoring_system == "10_zone_compound"
    outdoor_reduced = TargetSetup(70, METRE, 122, face_type="10_zone_compound")
    assert resolve_target(outdoor_reduced, Bowstyle.BAREBOW).scoring_system == "10_zone_compound"


def test_without_a_face_type_resolution_is_the_simple_setup_behaviour():
    """face_type None (the default) gives exactly the bowstyle-based choice as before."""
    assert TargetSetup(20, YARD, 60).face_type is None
    assert resolve_target(PORTSMOUTH, Bowstyle.COMPOUND).scoring_system == "10_zone_compound"
    assert resolve_target(OUTDOOR_70M, Bowstyle.COMPOUND).scoring_system == "10_zone"


@pytest.mark.parametrize(
    ("face_type", "maximum"),
    [("10_zone", 10), ("10_zone_compound", 10), ("5_zone", 9), ("11_zone", 11),
     ("Worcester", 5), ("WA_field", 6), ("IFAA_field", 5), ("Beiter_hit_miss", 1)],
)
def test_max_arrow_score_is_the_highest_ring_of_the_face(face_type, maximum):
    """10 on a standard face, 9 on 5-zone, 11 on 11-zone, 1 on hit/miss, ..."""
    target = resolve_target(TargetSetup(20, YARD, 60, face_type=face_type), Bowstyle.RECURVE)
    assert max_arrow_score(target) == maximum


@pytest.mark.parametrize("face_type", ALL_SYSTEMS)
def test_the_statistics_engine_handles_every_face_type(face_type):
    """Whatever the face: the per-arrow PMF sums to 1, matches archeryutils's mean, in whole scores."""
    for face_cm, (distance, unit), handicap in itertools.product(
        (20, 40, 60, 122), ((18, METRE), (20, YARD), (50, METRE), (100, YARD)), (0, 50, 100, 150)
    ):
        setup = TargetSetup(distance, unit, face_cm, face_type=face_type)
        target = resolve_target(setup, Bowstyle.RECURVE)
        pmf = stats.per_arrow_pmf(handicap, target)
        assert math.isclose(sum(pmf.values()), 1.0, abs_tol=1e-9)
        assert all(p >= 0 for p in pmf.values())
        assert all(float(score).is_integer() for score in pmf)
        mean = sum(score * p for score, p in pmf.items())
        assert mean == pytest.approx(float(stats._AGB_SCHEME.arrow_score(handicap, target)), abs=1e-6)
        dist = stats.n_pass_score_distribution(pmf, 12)
        assert math.isclose(sum(dist.values()), 1.0, abs_tol=1e-9)
        assert max(dist) <= 12 * max_arrow_score(target)


def test_parse_advanced_accepts_every_offered_combination():
    """Every (face type, face size, distance) the dropdowns offer parses to the matching setup."""
    for (distance, unit), face_cm, face_type in itertools.product(
        STANDARD_DISTANCES, ADVANCED_FACE_SIZES_CM, FACE_TYPES
    ):
        key = TargetSetup(distance, unit, 60).distance_key
        setup = TargetSetup.parse_advanced(key, str(face_cm), face_type)
        assert setup == TargetSetup(distance, unit, face_cm, face_type)


@pytest.mark.parametrize(
    ("args", "named"),
    [
        (("18m", "40", "bogus_zone"), "target face types"),
        (("18m", "45", "10_zone"), "standard face sizes"),
        (("18m", "abc", "10_zone"), "standard face sizes"),
        (("19m", "40", "10_zone"), "standard distances"),
        (("18m", "40", "Custom"), "target face types"),
    ],
)
def test_parse_advanced_rejects_bad_values_naming_the_one_that_is_wrong(args, named):
    """An unknown face type, an off-list face size or a non-standard distance is refused."""
    with pytest.raises(ValueError, match=named):
        TargetSetup.parse_advanced(*args)


def test_simple_parse_still_only_accepts_the_four_standard_face_sizes():
    """35 cm is an advanced-mode size only; simple setup is unchanged."""
    with pytest.raises(ValueError):
        TargetSetup.parse("18m", "35")
    assert TargetSetup.parse("18m", "40").face_type is None
