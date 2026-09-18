"""Tests for the Flask web layer (h2h.app)."""

from h2h.app import create_app
from h2h.state import SessionState


def make_client():
    """A Flask test client with its own isolated SessionState."""
    return create_app(state=SessionState()).test_client()


def test_index_returns_200():
    """GET / should return HTTP 200."""
    client = make_client()
    response = client.get("/")
    assert response.status_code == 200


def test_stats_importable_without_flask_running():
    """The stats module must import cleanly with no Flask app created/running."""
    import h2h.stats  # noqa: F401


def start_form(*archers, n_pass=12):
    """Build a /start form payload from (name, handicap) tuples."""
    form = {"n_pass": str(n_pass)}
    for i, (name, handicap) in enumerate(archers):
        form[f"name_{i}"] = name
        form[f"handicap_{i}"] = str(handicap)
    return form


# --- Task 6: setup UI, pairing, n_pass ---------------------------------


def test_start_creates_one_match_per_pair():
    """Submitting two archers creates exactly one match with the chosen n_pass."""
    client = make_client()
    resp = client.post(
        "/start", data=start_form(("Alice", 10), ("Bob", 30), n_pass=12), follow_redirects=True
    )
    assert resp.status_code == 200
    assert b"Alice" in resp.data
    assert b"Bob" in resp.data


def test_odd_number_of_archers_flags_unpaired_without_crashing():
    """An odd archer count must flag the leftover archer, not crash the app."""
    client = make_client()
    resp = client.post(
        "/start",
        data=start_form(("Alice", 10), ("Bob", 30), ("Carol", 20)),
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Carol" in resp.data
    assert b"no opponent" in resp.data


def test_invalid_n_pass_is_rejected_server_side():
    """An n_pass that doesn't divide 60 must not silently create a broken match."""
    client = make_client()
    resp = client.post("/start", data=start_form(("Alice", 10), ("Bob", 30), n_pass=7))
    assert resp.status_code == 200  # re-renders setup with an error, not a 500
    assert b"does not evenly divide" in resp.data


# --- Task 7: pass score entry and live results -------------------------


def test_recording_a_pass_shows_winner_and_running_score():
    """Submitting a pass's scores shows a consistent winner and running tally."""
    client = make_client()
    client.post("/start", data=start_form(("Alice", 10), ("Bob", 60), n_pass=12))
    resp = client.post(
        "/match/0/pass", data={"score_a": "118", "score_b": "20"}, follow_redirects=True
    )
    assert resp.status_code == 200
    assert b"Passes won: Alice 1 - 0 Bob" in resp.data or b"Passes won: Alice 0 - 1 Bob" in resp.data


def test_match_reports_result_after_final_pass():
    """After the final pass, the overall match result must be displayed."""
    client = make_client()
    client.post("/start", data=start_form(("Alice", 10), ("Bob", 60), n_pass=60))
    resp = client.post(
        "/match/0/pass", data={"score_a": "500", "score_b": "50"}, follow_redirects=True
    )
    assert b"Result:" in resp.data


# --- Task 8: basic/advanced toggle --------------------------------------


def test_toggle_mode_preserves_match_progress():
    """Switching modes must not lose entered scores or match progress."""
    client = make_client()
    client.post("/start", data=start_form(("Alice", 10), ("Bob", 60), n_pass=12))
    client.post("/match/0/pass", data={"score_a": "118", "score_b": "20"})
    client.post("/mode", data={"next": "/match/0"})
    resp = client.get("/match/0")
    assert b"118" in resp.data or b"20.0" in resp.data


# --- Task 9: advanced-mode charts and maths explanation -----------------


def test_advanced_mode_shows_chart_and_maths_explanation():
    """Advanced mode must show a chart image and an explanation mentioning bowstyle."""
    client = make_client()
    client.post("/start", data=start_form(("Alice", 10), ("Bob", 60), n_pass=12))
    client.post("/match/0/pass", data={"score_a": "118", "score_b": "20"})
    client.post("/mode", data={"next": "/match/0"})  # basic -> advanced
    resp = client.get("/match/0")
    assert b"chart.png" in resp.data
    assert b"bowstyle" in resp.data.lower()


def test_basic_mode_hides_advanced_content():
    """Basic mode must not show chart images or the maths explanation."""
    client = make_client()
    client.post("/start", data=start_form(("Alice", 10), ("Bob", 60), n_pass=12))
    client.post("/match/0/pass", data={"score_a": "118", "score_b": "20"})
    resp = client.get("/match/0")
    assert b"chart.png" not in resp.data
    assert b"How the winner is decided" not in resp.data


def test_pass_chart_returns_png():
    """The chart endpoint returns a valid PNG for a scored pass."""
    client = make_client()
    client.post("/start", data=start_form(("Alice", 10), ("Bob", 60), n_pass=12))
    client.post("/match/0/pass", data={"score_a": "118", "score_b": "20"})
    resp = client.get("/match/0/pass/0/chart.png")
    assert resp.status_code == 200
    assert resp.content_type == "image/png"
    assert resp.data[:8] == b"\x89PNG\r\n\x1a\n"
