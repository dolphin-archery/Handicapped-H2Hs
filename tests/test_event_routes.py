"""Tests for the new rotation-based event Flask routes (h2h.app).

Kept separate from tests/test_app.py (the old fixed-pair flow's tests),
since that file is replaced wholesale when prd task 24 retires the old flow.
"""

from h2h.app import create_app
from h2h.state import SessionState


def make_client():
    """A Flask test client with its own isolated SessionState."""
    return create_app(state=SessionState()).test_client()


def stage1_form(n_archers=4, total_arrows=60, n_pass=12, round_mode="indoor", indoor_round="portsmouth"):
    """Build a /event/stage1 form payload."""
    return {
        "n_archers": str(n_archers),
        "total_arrows": str(total_arrows),
        "n_pass": str(n_pass),
        "round_mode": round_mode,
        "indoor_round": indoor_round,
    }


# --- Task 18: Stage 1 setup UI ------------------------------------------


def test_stage1_get_returns_200():
    """GET /event/stage1 should render the form."""
    client = make_client()
    resp = client.get("/event/stage1")
    assert resp.status_code == 200


def test_valid_stage1_submission_redirects_to_stage2():
    """Valid Stage 1 input builds a schedule and redirects onward."""
    client = make_client()
    resp = client.post("/event/stage1", data=stage1_form(), follow_redirects=True)
    assert resp.status_code == 200


def test_n_pass_not_dividing_total_arrows_rejected():
    """n_pass that doesn't evenly divide total_arrows must show a clear error."""
    client = make_client()
    resp = client.post("/event/stage1", data=stage1_form(total_arrows=60, n_pass=7))
    assert resp.status_code == 200
    assert b"must evenly divide" in resp.data


def test_changing_total_arrows_changes_accepted_n_pass():
    """total_arrows=40 should accept n_pass=8 but reject n_pass=12."""
    client = make_client()
    resp_ok = client.post(
        "/event/stage1", data=stage1_form(total_arrows=40, n_pass=8), follow_redirects=True
    )
    assert resp_ok.status_code == 200
    assert b"must evenly divide" not in resp_ok.data

    resp_bad = client.post("/event/stage1", data=stage1_form(total_arrows=40, n_pass=12))
    assert b"must evenly divide" in resp_bad.data


def test_n_archers_below_two_rejected():
    """n_archers < 2 must be rejected with a clear error, not a 500."""
    client = make_client()
    resp = client.post("/event/stage1", data=stage1_form(n_archers=1))
    assert resp.status_code == 200
    assert b"at least 2" in resp.data


def test_outdoor_mode_does_not_require_indoor_round_choice():
    """Selecting outdoor must work without a meaningful indoor_round value."""
    client = make_client()
    resp = client.post(
        "/event/stage1", data=stage1_form(round_mode="outdoor"), follow_redirects=True
    )
    assert resp.status_code == 200
