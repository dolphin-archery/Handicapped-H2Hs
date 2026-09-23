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


# --- Task 19: Stage 2 setup UI -------------------------------------------


def stage2_form(archers):
    """Build a /event/stage2 form payload from (name, bowstyle, handicap) tuples."""
    form = {}
    for i, (name, bowstyle, handicap) in enumerate(archers):
        form[f"name_{i}"] = name
        form[f"bowstyle_{i}"] = bowstyle
        form[f"handicap_{i}"] = str(handicap)
    return form


def complete_stage1(client, n_archers=3, total_arrows=60, n_pass=12, round_mode="indoor"):
    """Run Stage 1 so Stage 2 is reachable."""
    client.post("/event/stage1", data=stage1_form(n_archers=n_archers, total_arrows=total_arrows, n_pass=n_pass, round_mode=round_mode))


def test_stage2_renders_exactly_n_archers_rows():
    """Stage 2 must show exactly as many rows as Stage 1's n_archers."""
    client = make_client()
    complete_stage1(client, n_archers=5)
    resp = client.get("/event/stage2")
    assert resp.status_code == 200
    for i in range(5):
        assert f'name="name_{i}"'.encode() in resp.data
    assert b'name="name_5"' not in resp.data


def test_stage2_without_stage1_redirects_to_stage1():
    """Reaching Stage 2 without completing Stage 1 must redirect back."""
    client = make_client()
    resp = client.get("/event/stage2", follow_redirects=True)
    assert b"Event setup - Stage 1" in resp.data


def test_valid_stage2_submission_creates_event():
    """Submitting valid archer details for every row starts the event."""
    client = make_client()
    complete_stage1(client, n_archers=2)
    resp = client.post(
        "/event/stage2",
        data=stage2_form([("Alice", "Recurve", 20), ("Bob", "Compound", 30)]),
        follow_redirects=True,
    )
    assert resp.status_code == 200


def test_stage2_missing_bowstyle_rejected():
    """A missing/invalid bowstyle must be rejected with a clear error."""
    client = make_client()
    complete_stage1(client, n_archers=2)
    resp = client.post(
        "/event/stage2",
        data=stage2_form([("Alice", "", 20), ("Bob", "Compound", 30)]),
    )
    assert resp.status_code == 200
    assert b"required" in resp.data or b"bowstyle" in resp.data.lower()


# --- Task 20: rotation scoring UI ----------------------------------------


def complete_stage2(client, archers):
    """Run Stage 2 with the given (name, bowstyle, handicap) tuples."""
    return client.post("/event/stage2", data=stage2_form(archers), follow_redirects=True)


def start_two_archer_event(client, n_pass=12):
    """Set up a minimal 2-archer event, ready for rotation scoring."""
    complete_stage1(client, n_archers=2, total_arrows=n_pass, n_pass=n_pass)
    complete_stage2(client, [("Alice", "Recurve", 15), ("Bob", "Compound", 45)])


def test_rotation_page_shows_correct_boxes_for_a_pair():
    """A rotation with one pair (no bye) shows exactly two score boxes."""
    client = make_client()
    start_two_archer_event(client)
    resp = client.get("/event/rotation")
    assert resp.status_code == 200
    assert b'name="score_0"' in resp.data
    assert b'name="score_1"' in resp.data


def test_rotation_page_shows_bye_box_for_odd_archers():
    """An odd-archer event's bye rotation shows a single box for the bye archer."""
    client = make_client()
    complete_stage1(client, n_archers=3, total_arrows=36, n_pass=12)
    complete_stage2(
        client,
        [("Alice", "Recurve", 15), ("Bob", "Compound", 45), ("Carol", "Barebow", 30)],
    )
    resp = client.get("/event/rotation")
    assert resp.status_code == 200
    assert b"bye" in resp.data.lower()


def test_submitting_a_rotation_advances_to_the_next_one():
    """Submitting valid scores for the current rotation advances the event."""
    client = make_client()
    start_two_archer_event(client, n_pass=12)  # total_arrows == n_pass -> 1 rotation
    resp = client.post(
        "/event/rotation",
        data={"score_0": "100", "score_1": "60"},
        follow_redirects=True,
    )
    assert resp.status_code == 200


def test_invalid_score_in_rotation_rejected_with_clear_error():
    """An invalid score anywhere in the rotation must be rejected, not partially recorded."""
    client = make_client()
    start_two_archer_event(client)
    resp = client.post(
        "/event/rotation",
        data={"score_0": "abc", "score_1": "60"},
    )
    assert resp.status_code == 200
    assert b"must be a number" in resp.data


def test_event_complete_redirects_to_results():
    """Once every rotation is scored, /event/rotation redirects to results."""
    client = make_client()
    start_two_archer_event(client, n_pass=12)  # single rotation
    client.post("/event/rotation", data={"score_0": "100", "score_1": "60"})
    resp = client.get("/event/rotation", follow_redirects=True)
    assert resp.status_code == 200
