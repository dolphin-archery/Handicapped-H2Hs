"""Tests for the rotation-based event Flask routes (h2h.app).

Covers Stage 1/2 setup, the overview / per-match / advance page flow, and the
results and chart pages.
"""

import pytest

from h2h.app import create_app
from h2h.state import SessionState

from .helpers import save_match, score_current_pass


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


# --- Overview, per-match pages and advance (Feedback 3) --------------------
# Replaces task 20's single page that scored a whole rotation at once.


def complete_stage2(client, archers):
    """Run Stage 2 with the given (name, bowstyle, handicap) tuples."""
    return client.post("/event/stage2", data=stage2_form(archers), follow_redirects=True)


def start_two_archer_event(client, n_pass=12):
    """Set up a minimal 2-archer event, ready for scoring."""
    complete_stage1(client, n_archers=2, total_arrows=n_pass, n_pass=n_pass)
    complete_stage2(client, [("Alice", "Recurve", 15), ("Bob", "Compound", 45)])


FOUR_ARCHERS = [
    ("A1", "Recurve", 15),
    ("A2", "Compound", 25),
    ("A3", "Barebow", 35),
    ("A4", "Longbow", 45),
]
THREE_ARCHERS = [("Alice", "Recurve", 15), ("Bob", "Compound", 45), ("Carol", "Barebow", 30)]


def start_four_archer_event(client, total_arrows=36):
    """Set up a 4-archer event (3 passes by default: no byes, two matches per pass)."""
    complete_stage1(client, n_archers=4, total_arrows=total_arrows, n_pass=12)
    complete_stage2(client, FOUR_ARCHERS)


def start_three_archer_event(client, shoot_byes=True, total_arrows=24):
    """Set up a 3-archer event (one bye per pass)."""
    client.post(
        "/event/stage1",
        data={
            **stage1_form(n_archers=3, total_arrows=total_arrows, n_pass=12),
            "shoot_byes": "yes" if shoot_byes else "no",
        },
    )
    complete_stage2(client, THREE_ARCHERS)


def test_overview_shows_pass_heading_matches_and_links_but_no_score_boxes():
    """The overview lists every match with a link, and has no score-entry inputs."""
    client = make_client()
    start_four_archer_event(client)
    resp = client.get("/event/rotation")
    assert resp.status_code == 200
    assert b"Pass 1 of 3" in resp.data
    assert b'href="/event/match/0"' in resp.data
    assert b'href="/event/match/1"' in resp.data
    assert b'href="/event/match/2"' not in resp.data
    assert b" vs " in resp.data
    assert b'name="score_' not in resp.data


def test_overview_lists_the_bye_match_when_byes_are_shot():
    """With an odd archer count and byes shot, the bye archer has a solo match."""
    client = make_client()
    start_three_archer_event(client, shoot_byes=True)
    resp = client.get("/event/rotation")
    assert b"bye" in resp.data.lower()
    assert b'href="/event/match/0"' in resp.data
    assert b'href="/event/match/1"' in resp.data  # the pair, plus the bye match


def test_overview_lists_sitting_out_archers_when_byes_are_not_shot():
    """When byes aren't shot, the bye archer is listed as sitting out and gets no match."""
    client = make_client()
    start_three_archer_event(client, shoot_byes=False)
    resp = client.get("/event/rotation")
    assert b"Sitting out this pass:" in resp.data
    assert b'href="/event/match/0"' in resp.data
    assert b'href="/event/match/1"' not in resp.data  # only the one pair shoots


def test_posting_a_whole_rotation_is_no_longer_allowed():
    """No endpoint accepts a whole rotation's scores at once."""
    client = make_client()
    start_two_archer_event(client)
    resp = client.post("/event/rotation", data={"score_0": "100", "score_1": "60"})
    assert resp.status_code == 405


def test_match_page_shows_score_boxes_only_for_its_own_archers():
    """A pair's page has exactly its two boxes; a bye match's page has one."""
    client = make_client()
    start_four_archer_event(client)
    page = client.get("/event/match/0").data.decode()
    assert page.count('name="score_') == 2

    client = make_client()
    start_three_archer_event(client, shoot_byes=True)
    pair_page = client.get("/event/match/0").data.decode()
    bye_page = client.get("/event/match/1").data.decode()
    assert pair_page.count('name="score_') == 2
    assert bye_page.count('name="score_') == 1
    assert "bye" in bye_page.lower()


def test_match_index_out_of_range_redirects_to_overview():
    """An unknown match index goes back to the overview rather than erroring."""
    client = make_client()
    start_four_archer_event(client)
    resp = client.get("/event/match/9", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Pass 1 of 3" in resp.data
    resp = client.post("/event/match/9", data={"score_0": "1"}, follow_redirects=True)
    assert b"Pass 1 of 3" in resp.data


def test_event_routes_redirect_to_stage1_without_an_event():
    """With no event set up, every event page falls back to Stage 1."""
    client = make_client()
    for url in ("/event/rotation", "/event/match/0"):
        resp = client.get(url, follow_redirects=True)
        assert b"Event setup - Stage 1" in resp.data
    resp = client.post("/event/advance", follow_redirects=True)
    assert b"Event setup - Stage 1" in resp.data


def test_saving_a_match_records_only_that_match_and_returns_to_its_page():
    """Saving one match leaves the others awaiting scores and redirects to the same page."""
    client = make_client()
    start_four_archer_event(client)
    resp = save_match(client, 0, {0: 100, 3: 60})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/event/match/0")

    overview = client.get("/event/rotation").data.decode()
    assert "A1 100 - 60 A4" in overview
    assert overview.count("Awaiting scores") == 1  # the other match


@pytest.mark.parametrize(
    ("bad_score", "expected_message"),
    [
        ("abc", b"must be a number"),
        ("-5", b"between 0 and 120"),
        ("121", b"between 0 and 120"),
        ("100.5", b"whole number"),
    ],
)
def test_invalid_score_on_a_match_page_shows_an_error_and_records_nothing(
    bad_score, expected_message
):
    """Each kind of invalid score is rejected with a specific message, recording nothing."""
    client = make_client()
    start_two_archer_event(client)
    resp = save_match(client, 0, {0: bad_score, 1: 60})
    assert resp.status_code == 200
    assert expected_message in resp.data
    assert b"Awaiting scores" in client.get("/event/rotation").data


def test_resaving_a_match_replaces_its_scores():
    """Saving a match again replaces the earlier scores, and the form is prefilled."""
    client = make_client()
    start_two_archer_event(client)
    save_match(client, 0, {0: 100, 1: 60})
    save_match(client, 0, {0: 90, 1: 80})

    overview = client.get("/event/rotation").data.decode()
    assert "Alice 90 - 80 Bob" in overview
    assert "100" not in overview.split("Alice")[1].split("Bob")[0]
    page = client.get("/event/match/0").data.decode()
    assert 'value="90"' in page
    assert 'value="80"' in page


def test_advance_is_disabled_and_refused_until_every_match_is_scored():
    """The advance button is disabled, and the route refuses, until the pass is fully scored."""
    client = make_client()
    start_four_archer_event(client)
    assert b"disabled" in client.get("/event/rotation").data

    refused = client.post("/event/advance")
    assert refused.status_code == 200
    assert b"Every match in the current pass must have scores" in refused.data
    assert b"Pass 1 of 3" in refused.data

    save_match(client, 0, {0: 100, 3: 60})
    assert b"disabled" in client.get("/event/rotation").data
    save_match(client, 1, {1: 90, 2: 80})
    overview = client.get("/event/rotation").data
    assert b"disabled" not in overview
    assert b"Advance to next pass" in overview


def test_advancing_shows_the_next_passes_pairings_and_accepts_its_scores():
    """After advancing, the overview shows the new pairings and match pages take new scores."""
    state = SessionState()
    client = create_app(state=state).test_client()
    start_four_archer_event(client)
    score_current_pass(client)

    resp = client.post("/event/advance", follow_redirects=True)
    assert b"Pass 2 of 3" in resp.data
    names = {i: name for i, (name, _, _) in enumerate(FOUR_ARCHERS)}
    for a, b in state.event.matches(1):
        assert f"{names[a]} vs {names[b]}".encode() in resp.data
    assert resp.data.count(b"Awaiting scores") == 2  # fresh pass, nothing scored yet

    score_current_pass(client)
    results = client.get("/event/results").data
    assert b"Rotation 2" in results


def test_final_pass_has_no_advance_button_and_links_to_results_when_scored():
    """On the last pass there is no advance button; once scored, the event is complete."""
    client = make_client()
    start_two_archer_event(client, n_pass=12)  # a single pass
    before = client.get("/event/rotation")
    assert b"Pass 1 of 1" in before.data
    assert b"Advance to next pass" not in before.data
    assert b"final pass" in before.data

    save_match(client, 0, {0: 100, 1: 60})
    after = client.get("/event/rotation")  # not redirected away
    assert after.status_code == 200
    assert b"Advance to next pass" not in after.data
    assert b"event is complete" in after.data
    assert b'href="/event/results"' in after.data


def test_advancing_past_the_final_pass_is_refused():
    """POSTing advance on the final pass shows an error rather than moving on."""
    client = make_client()
    start_two_archer_event(client, n_pass=12)
    save_match(client, 0, {0: 100, 1: 60})
    resp = client.post("/event/advance")
    assert resp.status_code == 200
    assert b"final pass" in resp.data


# --- Task 21: per-pass and pairwise results display -----------------------


def test_results_page_shows_scored_rotation():
    """After scoring a rotation, its per-pass results appear on the results page."""
    client = make_client()
    start_two_archer_event(client, n_pass=12)
    save_match(client, 0, {0: 100, 1: 60})
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
    save_match(client, 0, {0: 120, 1: 0})
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
    save_match(client, 0, {0: 100, 1: 60})
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
    save_match(client, 0, {0: 100, 1: 60})

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
    save_match(client, 0, {0: 100, 1: 60})
    resp = client.get("/event/results")
    assert b"<th>Rank</th>" not in resp.data
    assert b"<th>Points</th>" not in resp.data
    assert b"<th>Total</th>" not in resp.data
