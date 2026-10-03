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


# --- "Shoot byes?" option (Feedback 3) -----------------------------------


def make_client_and_state():
    """A Flask test client plus the SessionState it uses, for inspecting stored state."""
    state = SessionState()
    return create_app(state=state).test_client(), state


def test_stage1_page_offers_shoot_byes_control_and_explanation():
    """Stage 1 renders the Shoot byes? Yes/No control with its explanatory text."""
    client = make_client()
    resp = client.get("/event/stage1")
    assert b"Shoot byes?" in resp.data
    assert b'name="shoot_byes" value="yes"' in resp.data
    assert b'name="shoot_byes" value="no"' in resp.data
    assert b"adds passes" in resp.data


def test_shoot_byes_control_defaults_to_yes():
    """A fresh Stage 1 page has Yes selected."""
    client = make_client()
    page = client.get("/event/stage1").data.decode()
    yes_input = page[page.index('name="shoot_byes" value="yes"') :].split(">")[0]
    assert "checked" in yes_input


def test_shoot_byes_control_is_server_hidden_for_even_and_shown_for_odd():
    """The control starts hidden for an even archer count and visible for an odd one."""
    client, state = make_client_and_state()

    def control_tag(html):
        return html[html.index('id="shoot_byes_choice"') :].split(">")[0]

    assert "hidden" in control_tag(client.get("/event/stage1").data.decode())  # default 4
    client.post("/event/stage1", data=stage1_form(n_archers=5))
    assert "hidden" not in control_tag(client.get("/event/stage1").data.decode())


def test_posting_shoot_byes_no_with_odd_archers_stores_false_and_longer_schedule():
    """shoot_byes=no with 5 archers x 5 passes stores False and builds 7 rotations."""
    client, state = make_client_and_state()
    form = {**stage1_form(n_archers=5), "shoot_byes": "no"}
    resp = client.post("/event/stage1", data=form, follow_redirects=True)
    assert resp.status_code == 200
    assert state.shoot_byes is False
    assert len(state.schedule) == 7


def test_posting_shoot_byes_yes_keeps_the_ordinary_schedule():
    """shoot_byes=yes (and an omitted field) keep total_arrows // n_pass rotations."""
    for form in (
        {**stage1_form(n_archers=5), "shoot_byes": "yes"},
        stage1_form(n_archers=5),
    ):
        client, state = make_client_and_state()
        client.post("/event/stage1", data=form)
        assert state.shoot_byes is True
        assert len(state.schedule) == 5


def test_shoot_byes_field_is_ignored_for_even_archers():
    """With an even archer count the field changes nothing about the schedule."""
    client, state = make_client_and_state()
    client.post("/event/stage1", data={**stage1_form(n_archers=4), "shoot_byes": "no"})
    assert len(state.schedule) == 5
    assert all(r.sitting_out == () for r in state.schedule)


def test_stage1_page_remembers_a_previous_no_choice():
    """Returning to Stage 1 after choosing No shows No selected."""
    client = make_client()
    client.post("/event/stage1", data={**stage1_form(n_archers=5), "shoot_byes": "no"})
    page = client.get("/event/stage1").data.decode()
    no_input = page[page.index('name="shoot_byes" value="no"') :].split(">")[0]
    assert "checked" in no_input


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


def test_stage2_dropdown_offers_longbow_in_every_row():
    """Every row's bowstyle dropdown must offer Longbow alongside the other three."""
    client = make_client()
    complete_stage1(client, n_archers=3)
    resp = client.get("/event/stage2")
    assert resp.data.count(b'<option value="Longbow">') == 3
    for name in (b"Recurve", b"Compound", b"Barebow"):
        assert resp.data.count(b'<option value="' + name + b'">') == 3


def test_stage2_submission_with_longbow_archer_starts_event():
    """A Longbow archer is accepted by Stage 2 and the event starts."""
    client = make_client()
    complete_stage1(client, n_archers=2)
    resp = client.post(
        "/event/stage2",
        data=stage2_form([("Alice", "Longbow", 40), ("Bob", "Recurve", 30)]),
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Alice" in resp.data


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


# --- Task 21: per-pass and pairwise results display -----------------------


def test_results_page_shows_scored_rotation():
    """After scoring a rotation, its per-pass results appear on the results page."""
    client = make_client()
    start_two_archer_event(client, n_pass=12)
    client.post("/event/rotation", data={"score_0": "100", "score_1": "60"})
    resp = client.get("/event/results")
    assert resp.status_code == 200
    assert b"Alice" in resp.data
    assert b"Bob" in resp.data
    assert b"100" in resp.data
    assert b"60" in resp.data


def test_results_page_shows_pairwise_result():
    """After a pair shares a pass, their pairwise result appears."""
    client = make_client()
    start_two_archer_event(client, n_pass=12)
    client.post("/event/rotation", data={"score_0": "120", "score_1": "0"})
    resp = client.get("/event/results")
    assert b"wins" in resp.data.lower()


def test_results_page_before_any_scoring_shows_no_pairwise_results():
    """Before any rotation is scored, no pairwise results should be shown."""
    client = make_client()
    complete_stage1(client, n_archers=4, total_arrows=36, n_pass=12)
    complete_stage2(
        client,
        [
            ("A1", "Recurve", 15),
            ("A2", "Compound", 25),
            ("A3", "Barebow", 35),
            ("A4", "Recurve", 45),
        ],
    )
    resp = client.get("/event/results")
    assert resp.status_code == 200
    assert b"No pairs have shared a rotation yet" in resp.data


def test_pair_chart_page_renders_for_a_shared_pair():
    """A pair that has shared a rotation gets a working chart page."""
    client = make_client()
    start_two_archer_event(client, n_pass=12)
    client.post("/event/rotation", data={"score_0": "100", "score_1": "60"})
    resp = client.get("/event/pair/0/1")
    assert resp.status_code == 200
    assert b'id="match-chart"' in resp.data
    assert b"MATCH_CHART_DATA" in resp.data


def test_pair_chart_redirects_for_an_unshared_pair():
    """A pair that has never shared a rotation redirects back to results."""
    client = make_client()
    complete_stage1(client, n_archers=4, total_arrows=36, n_pass=12)
    complete_stage2(
        client,
        [
            ("A1", "Recurve", 15),
            ("A2", "Compound", 25),
            ("A3", "Barebow", 35),
            ("A4", "Recurve", 45),
        ],
    )
    resp = client.get("/event/pair/0/1", follow_redirects=True)
    assert resp.status_code == 200


def test_results_link_to_chart_only_shown_in_advanced_mode():
    """The 'View chart' link must only appear in advanced mode."""
    client = make_client()
    start_two_archer_event(client, n_pass=12)
    client.post("/event/rotation", data={"score_0": "100", "score_1": "60"})

    resp_basic = client.get("/event/results")
    assert b"View chart" not in resp_basic.data

    client.post("/mode", data={"next": "/event/results"})
    resp_advanced = client.get("/event/results")
    assert b"View chart" in resp_advanced.data


def test_results_page_does_not_show_a_ranked_leaderboard():
    """The results page must not compute/display a single ranked score total.

    The page's own prose may mention "leaderboard" to clarify that this view
    is deliberately NOT one (see results.html) -- that's fine. What must be
    absent is an actual ranking: a "Rank"/"Points" column or table.
    """
    client = make_client()
    start_two_archer_event(client, n_pass=12)
    client.post("/event/rotation", data={"score_0": "100", "score_1": "60"})
    resp = client.get("/event/results")
    assert b"<th>Rank</th>" not in resp.data
    assert b"<th>Points</th>" not in resp.data
    assert b"<th>Total</th>" not in resp.data
