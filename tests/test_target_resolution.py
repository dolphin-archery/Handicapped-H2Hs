"""Tests for h2h.models.resolve_target (round mode x bowstyle -> Target)."""

from archeryutils import load_rounds

from h2h.models import Bowstyle, RoundMode, resolve_target


def test_indoor_portsmouth_compound_uses_compound_variant():
    """Indoor Portsmouth + Compound resolves to portsmouth_compound's target."""
    target = resolve_target(RoundMode.INDOOR_PORTSMOUTH, Bowstyle.COMPOUND)
    expected = load_rounds.AGB_indoor.portsmouth_compound.passes[0].target
    assert target.scoring_system == "10_zone_compound"
    assert target.diameter == expected.diameter
    assert target.distance == expected.distance
    assert target.indoor is True


def test_indoor_portsmouth_recurve_and_barebow_use_plain_variant():
    """Indoor Portsmouth + Recurve/Barebow resolves to portsmouth's own target."""
    expected = load_rounds.AGB_indoor.portsmouth.passes[0].target
    for bowstyle in (Bowstyle.RECURVE, Bowstyle.BAREBOW):
        target = resolve_target(RoundMode.INDOOR_PORTSMOUTH, bowstyle)
        assert target.scoring_system == "10_zone"
        assert target.diameter == expected.diameter
        assert target.distance == expected.distance


def test_indoor_wa18_compound_uses_compound_variant():
    """Indoor WA18 + Compound resolves to wa18_compound's target."""
    target = resolve_target(RoundMode.INDOOR_WA18, Bowstyle.COMPOUND)
    expected = load_rounds.WA_indoor.wa18_compound.passes[0].target
    assert target.scoring_system == "10_zone_compound"
    assert target.diameter == expected.diameter
    assert target.distance == expected.distance


def test_indoor_wa18_recurve_and_barebow_use_plain_variant():
    """Indoor WA18 + Recurve/Barebow resolves to wa18's own target."""
    expected = load_rounds.WA_indoor.wa18.passes[0].target
    for bowstyle in (Bowstyle.RECURVE, Bowstyle.BAREBOW):
        target = resolve_target(RoundMode.INDOOR_WA18, bowstyle)
        assert target.scoring_system == "10_zone"
        assert target.diameter == expected.diameter


def test_outdoor_mode_ignores_bowstyle():
    """Outdoor mode resolves to the same fixed target for every bowstyle."""
    targets_by_bowstyle = {
        bowstyle: resolve_target(RoundMode.OUTDOOR, bowstyle) for bowstyle in Bowstyle
    }
    diameters = {t.diameter for t in targets_by_bowstyle.values()}
    distances = {t.distance for t in targets_by_bowstyle.values()}
    systems = {t.scoring_system for t in targets_by_bowstyle.values()}
    assert len(diameters) == 1
    assert len(distances) == 1
    assert len(systems) == 1


def test_outdoor_target_is_not_indoor():
    """The outdoor target must have indoor=False (so arrow diameter differs)."""
    target = resolve_target(RoundMode.OUTDOOR, Bowstyle.RECURVE)
    assert target.indoor is False


def test_indoor_targets_are_indoor():
    """Both indoor round choices must have indoor=True."""
    for round_mode in (RoundMode.INDOOR_PORTSMOUTH, RoundMode.INDOOR_WA18):
        target = resolve_target(round_mode, Bowstyle.RECURVE)
        assert target.indoor is True
