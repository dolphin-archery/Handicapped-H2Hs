"""Tests for the static score-to-handicap calculator (h2h.stats + routes)."""

from archeryutils import handicaps as hc
from archeryutils import load_rounds

from h2h import stats
from h2h.app import create_app
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


def test_calculator_page_get_returns_200():
    """GET /event/handicap-calculator should render the form."""
    client = make_client()
    resp = client.get("/event/handicap-calculator")
    assert resp.status_code == 200


def test_calculator_valid_portsmouth_score_shows_correct_handicap():
    """A valid Portsmouth score returns the correct handicap, rounded to 1dp."""
    client = make_client()
    rnd = load_rounds.AGB_indoor.portsmouth
    expected = round(_AGB_SCHEME.handicap_from_score(500, rnd), 1)
    resp = client.post(
        "/event/handicap-calculator", data={"round": "portsmouth", "score": "500"}
    )
    assert str(expected).encode() in resp.data


def test_calculator_valid_wa18_score_shows_correct_handicap():
    """A valid WA18 score returns the correct handicap."""
    client = make_client()
    rnd = load_rounds.WA_indoor.wa18
    expected = round(_AGB_SCHEME.handicap_from_score(550, rnd), 1)
    resp = client.post("/event/handicap-calculator", data={"round": "wa18", "score": "550"})
    assert str(expected).encode() in resp.data


def test_calculator_invalid_score_shows_friendly_error():
    """A non-numeric or out-of-range score must show an error, not a 500."""
    client = make_client()
    resp = client.post(
        "/event/handicap-calculator", data={"round": "portsmouth", "score": "abc"}
    )
    assert resp.status_code == 200
    assert b"valid score" in resp.data.lower()


def test_calculator_reachable_independent_of_event_setup_progress():
    """The calculator must be reachable even with no event set up at all."""
    client = make_client()
    resp = client.get("/event/handicap-calculator")
    assert resp.status_code == 200


# --- Compound option (Feedback 3) ----------------------------------------


def _shown_handicap(resp):
    """The handicap text rendered by the calculator page, e.g. '30.4'."""
    text = resp.data.decode()
    marker = "Handicap: "
    start = text.index(marker) + len(marker)
    return text[start : text.index("</strong>", start)]


def test_calculator_compound_portsmouth_uses_compound_round():
    """Compound ticked: the handicap comes from archeryutils's portsmouth_compound round."""
    client = make_client()
    plain = _AGB_SCHEME.handicap_from_score(500, load_rounds.AGB_indoor.portsmouth)
    compound = _AGB_SCHEME.handicap_from_score(500, load_rounds.AGB_indoor.portsmouth_compound)
    assert round(plain, 1) != round(compound, 1)  # the option must actually matter

    resp = client.post(
        "/event/handicap-calculator",
        data={"round": "portsmouth", "score": "500", "compound": "yes"},
    )
    assert _shown_handicap(resp) == str(round(compound, 1))


def test_calculator_compound_wa18_uses_compound_round():
    """Compound ticked: WA 18 uses archeryutils's wa18_compound round."""
    client = make_client()
    compound = _AGB_SCHEME.handicap_from_score(550, load_rounds.WA_indoor.wa18_compound)
    resp = client.post(
        "/event/handicap-calculator",
        data={"round": "wa18", "score": "550", "compound": "yes"},
    )
    assert _shown_handicap(resp) == str(round(compound, 1))


def test_calculator_without_compound_field_uses_plain_round():
    """Omitting the compound field behaves exactly as before: the plain round."""
    client = make_client()
    plain = _AGB_SCHEME.handicap_from_score(500, load_rounds.AGB_indoor.portsmouth)
    resp = client.post(
        "/event/handicap-calculator", data={"round": "portsmouth", "score": "500"}
    )
    assert _shown_handicap(resp) == str(round(plain, 1))


def test_calculator_invalid_score_with_compound_shows_friendly_error():
    """A bad score with compound ticked is still a friendly error, not a 500."""
    client = make_client()
    resp = client.post(
        "/event/handicap-calculator",
        data={"round": "portsmouth", "score": "abc", "compound": "yes"},
    )
    assert resp.status_code == 200
    assert b"valid score" in resp.data.lower()


def test_calculator_page_renders_a_compound_control():
    """The calculator form offers a compound checkbox."""
    client = make_client()
    resp = client.get("/event/handicap-calculator")
    assert b'name="compound"' in resp.data
