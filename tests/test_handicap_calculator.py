"""Tests for the static score-to-handicap calculator (h2h.stats, h2h.models lookups and routes)."""

import re

import pytest
from archeryutils import handicaps as hc
from archeryutils import load_rounds

from h2h import stats
from h2h.app import create_app
from h2h.models import (
    DEFAULT_CALCULATOR_ROUND,
    INDOOR,
    OUTDOOR,
    calculator_round,
    calculator_rounds,
)
from h2h.state import SessionState

_AGB_SCHEME = hc.handicap_scheme("AGB")


def test_handicap_for_round_score_matches_archeryutils_directly():
    """The wrapper must match calling archeryutils directly on the real round."""
    rnd = load_rounds.AGB_indoor.portsmouth
    expected = _AGB_SCHEME.handicap_from_score(500, rnd)
    assert stats.handicap_for_round_score(500, rnd) == expected


def test_handicap_for_round_score_works_for_wa18():
    """The wrapper must also work against the real WA18 round."""
    rnd = load_rounds.WA_indoor.wa18
    expected = _AGB_SCHEME.handicap_from_score(550, rnd)
    assert stats.handicap_for_round_score(550, rnd) == expected


def make_client():
    """A Flask test client with its own isolated SessionState."""
    return create_app(state=SessionState()).test_client()


def calculate(client, kind=INDOOR, round_name=None, score="500", compound=None):
    """POST the calculator form the way the page does (the chosen kind's round field only)."""
    round_name = round_name or DEFAULT_CALCULATOR_ROUND[kind]
    data = {"kind": kind, f"round_{kind}": round_name, "score": str(score)}
    if compound:
        data["compound"] = "yes"
    return client.post("/event/handicap-calculator", data=data)


def _shown_handicap(resp):
    """The handicap text rendered by the calculator page, e.g. '30.4'."""
    text = resp.data.decode()
    marker = "Handicap: "
    start = text.index(marker) + len(marker)
    return text[start : text.index("</strong>", start)]


def expected_handicap(rnd, score):
    """archeryutils's own handicap for a score on a round, to one decimal place as shown."""
    return str(round(_AGB_SCHEME.handicap_from_score(score, rnd), 1))


# --- the round lists ------------------------------------------------------------------------


def non_compound(round_set):
    """The codenames of a round set that are not compound variants."""
    return {k for k in round_set if not k.endswith(("_compound", "_compound_triple"))}


def test_indoor_list_is_the_non_compound_agb_and_wa_indoor_rounds():
    """Bray, Stafford, Portsmouth, Worcester, Vegas, WA 18m and 25m (with triples), each once."""
    indoor = calculator_rounds(INDOOR)
    assert set(indoor) == non_compound(load_rounds.AGB_indoor) | non_compound(load_rounds.WA_indoor)
    assert len(indoor) == 16
    names = [r.name for r in indoor.values()]
    assert len(names) == len(set(names))
    for expected in ("Portsmouth", "WA 18m", "WA 25m", "Bray I", "Stafford", "Worcester", "Vegas"):
        assert expected in names


def test_outdoor_list_is_the_non_compound_agb_and_wa_outdoor_rounds():
    """Imperial and metric AGB rounds and the WA rounds, each once."""
    outdoor = calculator_rounds(OUTDOOR)
    expected = (
        non_compound(load_rounds.AGB_outdoor_imperial)
        | non_compound(load_rounds.AGB_outdoor_metric)
        | non_compound(load_rounds.WA_outdoor)
    )
    assert set(outdoor) == expected and len(outdoor) == 76
    for needed in ("york", "hereford", "metric_i", "wa1440_90", "wa720_70", "wa900"):
        assert needed in outdoor


def test_no_compound_variant_is_listed_and_the_lists_do_not_overlap():
    """Compound variants are reached through the checkbox, not the dropdown."""
    both = set(calculator_rounds(INDOOR)) | set(calculator_rounds(OUTDOOR))
    assert not any(k.endswith(("_compound", "_compound_triple")) for k in both)
    assert not set(calculator_rounds(INDOOR)) & set(calculator_rounds(OUTDOOR))


def test_the_lists_exclude_the_other_round_families():
    """No Australian, visually-impaired, field, experimental or miscellaneous round."""
    listed = set(calculator_rounds(INDOOR)) | set(calculator_rounds(OUTDOOR))
    for other in (load_rounds.AA_indoor, load_rounds.AA_outdoor_metric, load_rounds.AGB_VI,
                  load_rounds.WA_VI, load_rounds.WA_field, load_rounds.IFAA_field,
                  load_rounds.WA_experimental, load_rounds.misc):
        assert not listed & set(other)


def test_defaults_are_portsmouth_indoors_and_wa_70m_outdoors():
    """Both defaults are in their lists."""
    assert DEFAULT_CALCULATOR_ROUND == {INDOOR: "portsmouth", OUTDOOR: "wa720_70"}
    assert "portsmouth" in calculator_rounds(INDOOR) and "wa720_70" in calculator_rounds(OUTDOOR)
    assert calculator_rounds(OUTDOOR)["wa720_70"].name == "WA 70m"


def test_calculator_round_returns_the_real_archeryutils_rounds_and_compound_variants():
    """A compound indoor choice maps to the compound variant, plain and triple, where one exists."""
    assert calculator_round(INDOOR, "portsmouth", False) is load_rounds.AGB_indoor.portsmouth
    assert calculator_round(INDOOR, "portsmouth", True) is load_rounds.AGB_indoor.portsmouth_compound
    assert calculator_round(INDOOR, "wa18", True) is load_rounds.WA_indoor.wa18_compound
    assert calculator_round(INDOOR, "wa25", True) is load_rounds.WA_indoor.wa25_compound
    assert calculator_round(INDOOR, "bray_ii", True) is load_rounds.AGB_indoor.bray_ii_compound
    assert calculator_round(INDOOR, "stafford", True) is load_rounds.AGB_indoor.stafford_compound
    assert calculator_round(INDOOR, "vegas", True) is load_rounds.AGB_indoor.vegas_compound
    assert calculator_round(INDOOR, "portsmouth_triple", True) is (
        load_rounds.AGB_indoor.portsmouth_compound_triple
    )
    assert calculator_round(INDOOR, "wa18_triple", True) is load_rounds.WA_indoor.wa18_compound_triple


@pytest.mark.parametrize("codename", ["worcester", "worcester_5_centre", "vegas_300", "vegas_300_triple"])
def test_an_indoor_round_without_a_compound_variant_is_used_as_chosen(codename):
    """No error and no substitution when archeryutils has no compound version."""
    assert calculator_round(INDOOR, codename, True) is calculator_rounds(INDOOR)[codename]


def test_outdoor_rounds_ignore_the_compound_flag():
    """Compound only changes indoor scoring."""
    assert calculator_round(OUTDOOR, "york", True) is load_rounds.AGB_outdoor_imperial.york
    assert calculator_round(OUTDOOR, "wa1440_90", True) is load_rounds.WA_outdoor.wa1440_90


@pytest.mark.parametrize(
    ("kind", "codename"),
    [(INDOOR, "york"), (OUTDOOR, "portsmouth"), (INDOOR, "portsmouth_compound"), (INDOOR, "nonsense"),
     (OUTDOOR, ""), ("sideways", "portsmouth")],
)
def test_a_round_outside_the_chosen_kinds_list_is_rejected(kind, codename):
    """Wrong-kind, unlisted and unknown rounds all raise ValueError."""
    with pytest.raises(ValueError):
        calculator_round(kind, codename, False)


# --- the page and the route ---------------------------------------------------------------------


def test_calculator_page_get_returns_200_and_works_with_no_event():
    """The form renders even with no event set up at all."""
    resp = make_client().get("/event/handicap-calculator")
    assert resp.status_code == 200


def test_the_page_has_the_kind_radios_both_round_lists_the_compound_box_and_a_score_box():
    """Indoor checked, Portsmouth and WA 70m selected, compound inside the indoor-only block."""
    page = make_client().get("/event/handicap-calculator").data.decode()
    indoor = page[page.index('name="kind" value="indoor"') :].split(">")[0]
    outdoor = page[page.index('name="kind" value="outdoor"') :].split(">")[0]
    assert "checked" in indoor and "checked" not in outdoor
    indoor_block = page[page.index('<select name="round_indoor"') : page.index("</select>")]
    assert '<option value="portsmouth" selected>Portsmouth</option>' in indoor_block
    outdoor_start = page.index('<select name="round_outdoor"')
    outdoor_block = page[outdoor_start : page.index("</select>", outdoor_start)]
    assert '<option value="wa720_70" selected>WA 70m</option>' in outdoor_block
    assert len(re.findall(r"<option ", indoor_block)) == 16
    assert len(re.findall(r"<option ", outdoor_block)) == 76
    # Outdoor list and compound checkbox are hidden/shown by kind.
    assert "hidden" in page[page.index('id="outdoor_rounds"') :].split(">")[0]
    assert "hidden" not in page[page.index('id="compound_choice"') :].split(">")[0]
    assert 'name="compound"' in page and 'name="score"' in page


def test_indoor_portsmouth_matches_archeryutils_with_and_without_compound():
    """Portsmouth 500: the plain and compound results are archeryutils's own and differ."""
    client = make_client()
    plain = _shown_handicap(calculate(client, INDOOR, "portsmouth", 500))
    compound = _shown_handicap(calculate(client, INDOOR, "portsmouth", 500, compound=True))
    assert plain == expected_handicap(load_rounds.AGB_indoor.portsmouth, 500)
    assert compound == expected_handicap(load_rounds.AGB_indoor.portsmouth_compound, 500)
    assert plain != compound


def test_indoor_wa18_matches_archeryutils_with_and_without_compound():
    """WA 18m 550: likewise."""
    client = make_client()
    assert _shown_handicap(calculate(client, INDOOR, "wa18", 550)) == expected_handicap(
        load_rounds.WA_indoor.wa18, 550
    )
    assert _shown_handicap(calculate(client, INDOOR, "wa18", 550, compound=True)) == expected_handicap(
        load_rounds.WA_indoor.wa18_compound, 550
    )


def test_a_round_with_no_compound_variant_gives_the_plain_result_with_the_box_ticked():
    """Worcester has no compound version: ticking the box changes nothing and is not an error."""
    client = make_client()
    plain = _shown_handicap(calculate(client, INDOOR, "worcester", 250))
    ticked = _shown_handicap(calculate(client, INDOOR, "worcester", 250, compound=True))
    assert plain == ticked == expected_handicap(load_rounds.AGB_indoor.worcester, 250)


@pytest.mark.parametrize(
    ("round_name", "rnd", "score"),
    [
        ("york", load_rounds.AGB_outdoor_imperial.york, 900),
        ("wa1440_90", load_rounds.WA_outdoor.wa1440_90, 1100),
        ("wa720_70", load_rounds.WA_outdoor.wa720_70, 600),
    ],
)
def test_outdoor_rounds_calculate_and_ignore_a_forced_compound_flag(round_name, rnd, score):
    """Outdoors the compound box does not exist: a forced POST with it gives the plain result."""
    client = make_client()
    plain = _shown_handicap(calculate(client, OUTDOOR, round_name, score))
    forced = _shown_handicap(calculate(client, OUTDOOR, round_name, score, compound=True))
    assert plain == forced == expected_handicap(rnd, score)


def test_a_round_that_is_not_in_the_chosen_kinds_list_is_a_friendly_error_with_no_result():
    """An outdoor round posted as indoor (or an unknown one) is refused."""
    client = make_client()
    for kind, name in ((INDOOR, "york"), (OUTDOOR, "portsmouth"), (INDOOR, "nonsense")):
        resp = calculate(client, kind, name, 500)
        assert resp.status_code == 200
        assert b"is not one of the standard" in resp.data and b"Handicap: " not in resp.data


def test_a_bad_kind_is_a_friendly_error():
    """Only indoor and outdoor exist."""
    resp = make_client().post(
        "/event/handicap-calculator", data={"kind": "sideways", "round_sideways": "x", "score": "5"}
    )
    assert resp.status_code == 200 and b"Choose indoor or outdoor" in resp.data


@pytest.mark.parametrize("score", ["abc", "", "99999", "-5", "nan"])
def test_an_invalid_score_shows_the_friendly_error_not_a_500(score):
    """Non-numeric, empty, above the round's maximum and negative scores are all refused."""
    client = make_client()
    for compound in (False, True):
        resp = calculate(client, INDOOR, "portsmouth", score, compound=compound)
        assert resp.status_code == 200
        assert b"valid score" in resp.data.lower() and b"Handicap: " not in resp.data


def test_the_submitted_choices_are_shown_again_after_a_result_and_after_an_error():
    """Kind, round, compound and score are re-rendered either way."""
    client = make_client()
    ok = calculate(client, OUTDOOR, "york", 900).data.decode()
    assert "checked" in ok[ok.index('name="kind" value="outdoor"') :].split(">")[0]
    assert '<option value="york" selected>York</option>' in ok
    assert 'value="900"' in ok

    bad = calculate(client, INDOOR, "wa25", "abc", compound=True).data.decode()
    assert '<option value="wa25" selected>WA 25m</option>' in bad
    assert "checked" in bad[bad.index('name="compound"') :].split(">")[0]
    assert 'value="abc"' in bad


def test_every_listed_round_gives_a_finite_handicap_for_a_mid_range_score():
    """No round in either list breaks the rootfinder (indoor with and without compound)."""
    client = make_client()
    for kind in (INDOOR, OUTDOOR):
        for codename, rnd in calculator_rounds(kind).items():
            score = round(rnd.max_score() * 0.6)
            for compound in ((False, True) if kind == INDOOR else (False,)):
                resp = calculate(client, kind, codename, score, compound=compound)
                shown = float(_shown_handicap(resp))
                assert 0 <= shown <= 150, (codename, compound, shown)
