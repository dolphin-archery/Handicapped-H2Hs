"""Tests for the rotation-based event Flask routes (h2h.app).

Covers Stage 1/2 setup, the overview / per-match / advance page flow, and the
results and chart pages.
"""

import json
import random
import re
from pathlib import Path

import pytest

from h2h.app import create_app
from h2h.models import DEFAULT_TARGET_SETUP, METRE, TargetSetup
from h2h.state import SessionState

from .helpers import make_state, overview_table, save_match, score_current_pass


def make_client():
    """A Flask test client with its own isolated SessionState."""
    return create_app(state=make_state()).test_client()


def stage1_form(
    n_archers=4, total_arrows=60, n_pass=12, distance="20yd", face_cm=60, setup_mode="simple"
):
    """Build a /event/stage1 form payload (simple setup: one distance and face for everyone)."""
    return {
        "n_archers": str(n_archers),
        "total_arrows": str(total_arrows),
        "n_pass": str(n_pass),
        "setup_mode": setup_mode,
        "distance": distance,
        "face_cm": str(face_cm),
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


def test_an_outdoor_distance_is_accepted_like_any_other():
    """A long (outdoor-class) distance and a big face go through Stage 1 normally."""
    client = make_client()
    resp = client.post(
        "/event/stage1", data=stage1_form(distance="70m", face_cm=122), follow_redirects=True
    )
    assert resp.status_code == 200
    assert b"Event setup - Stage 2" in resp.data


# --- "Shoot byes?" option (Feedback 3) -----------------------------------


def make_client_and_state():
    """A Flask test client plus the SessionState it uses, for inspecting stored state."""
    state = make_state()
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


def complete_stage1(
    client, n_archers=3, total_arrows=60, n_pass=12, distance="20yd", face_cm=60
):
    """Run Stage 1 so Stage 2 is reachable."""
    client.post(
        "/event/stage1",
        data=stage1_form(
            n_archers=n_archers,
            total_arrows=total_arrows,
            n_pass=n_pass,
            distance=distance,
            face_cm=face_cm,
        ),
    )


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


def test_valid_stage2_submission_goes_to_stage3_without_starting_the_event():
    """Submitting valid archer details moves on to Stage 3; the event starts only on confirm."""
    client, state = make_client_and_state()
    complete_stage1(client, n_archers=2)
    resp = client.post(
        "/event/stage2",
        data=stage2_form([("Alice", "Recurve", 20), ("Bob", "Compound", 30)]),
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"Event setup - Stage 3" in resp.data
    assert state.event is None


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


# --- Handicap range validation (Feedback 4) -----------------------------------


def stage2_after_stage1(n_archers=2):
    """A client + state that has completed Stage 1 for `n_archers`, ready for Stage 2."""
    client, state = make_client_and_state()
    complete_stage1(client, n_archers=n_archers)
    return client, state


@pytest.mark.parametrize("bad", ["-0.1", "-1", "150.1", "1000", "nan", "inf", "-inf"])
def test_out_of_range_handicap_is_rejected_naming_the_row_and_the_range(bad):
    """Handicaps outside 0-150 (and nan/inf) are rejected, with the row and range in the message."""
    client, state = stage2_after_stage1()
    resp = client.post(
        "/event/stage2", data=stage2_form([("Alice", "Recurve", 20), ("Bob", "Compound", bad)])
    )
    assert resp.status_code == 200  # re-rendered, not accepted
    assert b"Row 2: handicap must be between 0 and 150" in resp.data
    assert state.event is None


@pytest.mark.parametrize("good", ["0", "150", "22.5", "0.0", "149.9"])
def test_in_range_handicaps_including_the_boundaries_are_accepted(good):
    """0 and 150 themselves, and decimals, are valid starting handicaps."""
    client, _ = stage2_after_stage1()
    resp = client.post(
        "/event/stage2", data=stage2_form([("Alice", "Recurve", good), ("Bob", "Compound", 30)])
    )
    assert resp.status_code == 302  # accepted: moves on rather than re-rendering Stage 2


def test_rejected_handicap_leaves_the_form_filled_in_for_correction():
    """After a rejection the typed names, handicaps and bowstyles are put back."""
    client, _ = stage2_after_stage1()
    resp = client.post(
        "/event/stage2",
        data=stage2_form([("Alice", "Longbow", 20), ("Bob", "Compound", 150.1)]),
    )
    page = resp.data.decode()
    assert 'value="Alice"' in page and 'value="Bob"' in page
    assert 'value="150.1"' in page and 'value="20"' in page
    assert '<option value="Longbow" selected>' in page
    assert '<option value="Compound" selected>' in page
    assert '<option value="Recurve" selected>' not in page


def test_non_numeric_and_missing_handicaps_keep_their_existing_messages():
    """The range check sits alongside, not instead of, the earlier checks."""
    client, _ = stage2_after_stage1()
    resp = client.post(
        "/event/stage2", data=stage2_form([("Alice", "Recurve", "abc"), ("Bob", "Compound", 30)])
    )
    assert b"Row 1: handicap must be a number" in resp.data
    resp = client.post(
        "/event/stage2", data=stage2_form([("Alice", "Recurve", ""), ("Bob", "Compound", 30)])
    )
    assert b"name, handicap, and bowstyle are all required" in resp.data


def test_stage2_handicap_inputs_carry_the_range_as_min_and_max():
    """Every row's handicap input has min=0 and max=150 attributes."""
    client, _ = stage2_after_stage1(n_archers=3)
    page = client.get("/event/stage2").data.decode()
    assert page.count('min="0" max="150"') == 3


def test_handicap_bounds_are_defined_once_in_the_models_module():
    """The 0 and 150 live as constants in h2h.models, not as literals in the route or template."""
    from h2h import models

    assert (models.MIN_HANDICAP, models.MAX_HANDICAP) == (0, 150)
    root = Path(__file__).resolve().parent.parent / "h2h"
    for path in (root / "app.py", root / "templates" / "stage2.html"):
        assert "150" not in path.read_text(encoding="utf-8"), path.name


# --- Overview, per-match pages and advance (Feedback 3) --------------------
# Replaces task 20's single page that scored a whole rotation at once.


def complete_stage2(client, archers):
    """Run Stage 2 with the given (name, bowstyle, handicap) tuples."""
    resp = client.post("/event/stage2", data=stage2_form(archers))
    if resp.status_code == 302:  # accepted: confirm the (identity) Stage 3 draw to start the event
        return client.post("/event/stage3", follow_redirects=True)
    return resp


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

    _, rows = overview_table(client.get("/event/rotation").data.decode())
    assert rows[0][:2] == ["A1 vs A4", "100 - 60"]
    assert rows[1][:4] == ["A2 vs A3", "-", "-", "-"]  # the other match is unscored


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
    _, rows = overview_table(client.get("/event/rotation").data.decode())
    assert rows[0][1] == "-"  # nothing was recorded


def test_resaving_a_match_replaces_its_scores():
    """Saving a match again replaces the earlier scores, and the form is prefilled."""
    client = make_client()
    start_two_archer_event(client)
    save_match(client, 0, {0: 100, 1: 60})
    save_match(client, 0, {0: 90, 1: 80})

    _, rows = overview_table(client.get("/event/rotation").data.decode())
    assert len(rows) == 1 and rows[0][1] == "90 - 80"
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
    state = make_state()
    client = create_app(state=state).test_client()
    start_four_archer_event(client)
    score_current_pass(client)

    resp = client.post("/event/advance", follow_redirects=True)
    assert b"Pass 2 of 3" in resp.data
    names = {i: name for i, (name, _, _) in enumerate(FOUR_ARCHERS)}
    for a, b in state.event.matches(1):
        assert f"{names[a]} vs {names[b]}".encode() in resp.data
    _, rows = overview_table(resp.data.decode())
    assert [row[1] for row in rows] == ["-", "-"]  # fresh pass, nothing scored yet

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


def test_results_link_to_chart_only_shown_with_graph_view_on():
    """The 'View chart' link must only appear while graph view is on."""
    client = make_client()
    start_two_archer_event(client, n_pass=12)
    save_match(client, 0, {0: 100, 1: 60})

    resp_off = client.get("/event/results")
    assert b"View chart" not in resp_off.data

    client.post("/graph-view", data={"next": "/event/results"})
    resp_on = client.get("/event/results")
    assert b"View chart" in resp_on.data


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


# --- Per-match results and charts on the match pages (Feedback 3) -----------


def turn_on_graph_view(client):
    """Switch the session's graph view on."""
    client.post("/graph-view", data={"next": "/event/rotation"})


def embedded_chart_payload(html):
    """The JSON embedded as window.MATCH_CHART_DATA in a rendered page."""
    marker = "window.MATCH_CHART_DATA = "
    start = html.index(marker) + len(marker)
    return json.loads(html[start : html.index(";\n", start)])


def start_repeating_pair_event(client):
    """Two archers, two passes: the same pair meets in both."""
    complete_stage1(client, n_archers=2, total_arrows=24, n_pass=12)
    complete_stage2(client, [("Alice", "Recurve", 15), ("Bob", "Compound", 45)])


def match_page_table(html):
    """The (headings, rows) of the single table on a match page, as plain text."""
    assert html.count("<table>") <= 1
    if "<table>" not in html:
        return None
    return overview_table(html)


def test_match_page_has_no_results_table_before_scoring_and_one_this_pass_table_after():
    """After saving, the page has one table: Archer | Score | Percentile | Winner."""
    client = make_client()
    start_two_archer_event(client)
    before = client.get("/event/match/0").data.decode()
    assert match_page_table(before) is None
    assert "Results so far" not in before

    save_match(client, 0, {0: 120, 1: 0})
    page = client.get("/event/match/0").data.decode()
    headings, rows = match_page_table(page)
    assert headings == ["Archer", "Score", "Percentile", "Winner"]
    assert [row[0] for row in rows] == ["Alice", "Bob"]
    assert [row[1] for row in rows] == ["120", "0"]
    assert [row[3] for row in rows] == ["Yes", "No"]
    assert all(re.fullmatch(r"\d+\.\d%", row[2]) for row in rows)
    assert "Results so far" not in page


def test_match_page_table_agrees_with_the_events_recorded_results():
    """Score, percentile and winner in the table are the Event's own, for several score pairs."""
    for scores in ({0: 100, 1: 60}, {0: 60, 1: 100}, {0: 118, 1: 119}, {0: 0, 1: 1}):
        client, state = make_client_and_state()
        start_two_archer_event(client)
        save_match(client, 0, scores)
        _, rows = match_page_table(client.get("/event/match/0").data.decode())
        results = {r.archer_index: r for r in state.event.results}
        for index, row in enumerate(rows):
            assert row[0] == state.event.archers[index].name
            assert row[1] == str(results[index].score)
            assert row[2] == f"{results[index].percentile * 100:.1f}%"
            assert row[3] == ("Yes" if results[index].won else "No")


def test_match_page_shows_only_this_pass_not_earlier_passes_of_the_same_pair():
    """A pair that meets again sees just the new pass's two rows."""
    client = make_client()
    start_repeating_pair_event(client)
    save_match(client, 0, {0: 100, 1: 60})
    client.post("/event/advance")
    save_match(client, 0, {0: 91, 1: 82})

    page = client.get("/event/match/0").data.decode()
    _, rows = match_page_table(page)
    assert [row[1] for row in rows] == ["91", "82"]
    assert ">100<" not in page and ">60<" not in page
    assert "<th>Pass</th>" not in page and "Equiv. handicap" not in page and "Opponent" not in page


def test_match_page_never_shows_results_against_a_different_opponent():
    """Each match page lists only its own two archers' scores for the pass."""
    client, state = make_client_and_state()
    complete_stage1(client, n_archers=4, total_arrows=36, n_pass=12)
    complete_stage2(client, [(n, "Recurve", 20 + 5 * i) for i, n in enumerate(("Ann", "Ben", "Cat", "Dan"))])
    first, second = state.event.matches(0)
    save_match(client, 0, {p: 61 + p for p in first})
    save_match(client, 1, {p: 71 + p for p in second})
    page = client.get("/event/match/0").data.decode()
    _, rows = match_page_table(page)
    assert [row[0] for row in rows] == [state.event.archers[p].name for p in first]
    for p in second:
        assert state.event.archers[p].name not in rows[0][0] + rows[1][0]


def test_bye_match_page_shows_own_result_and_no_chart_either_way():
    """A bye match shows the archer's own result, and never a chart."""
    client, state = make_client_and_state()
    start_three_archer_event(client, shoot_byes=True)
    bye_archer = state.event.schedule[0].bye
    save_match(client, 1, {bye_archer: 70})  # the bye match is listed after the pair

    view_off = client.get("/event/match/1").data.decode()
    assert ">70<" in view_off and "bye" in view_off.lower()
    assert 'id="match-chart"' not in view_off

    turn_on_graph_view(client)
    view_on = client.get("/event/match/1").data.decode()
    assert ">70<" in view_on
    assert 'id="match-chart"' not in view_on
    assert "no distribution chart" in view_on


def test_graph_view_match_page_renders_chart_even_before_any_scoring():
    """Graph view on: the chart, checkbox, payload and maths appear before the first pass."""
    client = make_client()
    start_two_archer_event(client)
    turn_on_graph_view(client)
    page = client.get("/event/match/0").data.decode()
    assert 'id="match-chart"' in page
    assert 'id="show-previous-passes"' in page
    assert "How the winner is decided" in page
    payload = embedded_chart_payload(page)
    assert payload["archer_a"]["passes"] == [] and payload["archer_b"]["passes"] == []
    assert payload["archer_a"]["name"] == "Alice"
    assert payload["archer_a"]["legend"] == "Alice (handicap 15)"
    assert payload["archer_b"]["legend"] == "Bob (handicap 45)"
    assert payload["distribution_a"] and payload["distribution_b"]


def test_graph_view_match_page_chart_gains_the_scored_pass():
    """After saving, the embedded payload carries the pass's scores for the markers."""
    client = make_client()
    start_two_archer_event(client)
    turn_on_graph_view(client)
    save_match(client, 0, {0: 100, 1: 60})
    payload = embedded_chart_payload(client.get("/event/match/0").data.decode())
    assert payload["archer_a"]["passes"] == [{"index": 0, "score": 100}]
    assert payload["archer_b"]["passes"] == [{"index": 0, "score": 60}]
    assert payload["current_pass"] == 0


def test_match_page_with_graph_view_off_has_no_chart_or_maths_explanation():
    """Graph view off shows none of the graph-view content on a match page."""
    client = make_client()
    start_two_archer_event(client)
    save_match(client, 0, {0: 100, 1: 60})
    page = client.get("/event/match/0").data.decode()
    assert 'id="match-chart"' not in page
    assert "MATCH_CHART_DATA" not in page
    assert "How the winner is decided" not in page


def test_pair_history_and_results_pages_still_render_their_content():
    """The pair-history chart page and the results page keep their tables and chart."""
    client = make_client()
    start_two_archer_event(client)
    save_match(client, 0, {0: 100, 1: 60})
    pair_page = client.get("/event/pair/0/1").data.decode()
    assert 'id="match-chart"' in pair_page and "How the winner is decided" in pair_page
    results_page = client.get("/event/results").data.decode()
    for header in ("Percentile", "Equiv. handicap", "Opponent", "Won?"):
        assert header in results_page


def test_chart_maths_and_results_table_markup_is_not_duplicated_across_templates():
    """Each of the shared blocks lives in exactly one template file (a partial)."""
    templates = Path(__file__).resolve().parent.parent / "h2h" / "templates"
    sources = {p.name: p.read_text(encoding="utf-8") for p in templates.glob("*.html")}
    for needle, owner in (
        ("How the winner is decided", "_pair_chart.html"),
        ("window.MATCH_CHART_DATA", "_pair_chart.html"),
        ("<th>Equiv. handicap</th>", "_results_table.html"),
    ):
        assert [name for name, src in sources.items() if needle in src] == [owner]


# --- Graph view (Feedback 4: renamed from advanced mode) --------------------


def started_pair_with_a_shared_pass():
    """A client + state with a 2-archer event whose only match has been scored."""
    client, state = make_client_and_state()
    start_two_archer_event(client)
    save_match(client, 0, {0: 100, 1: 60})
    return client, state


def test_post_graph_view_flips_the_setting_and_redirects_to_next():
    """POST /graph-view toggles the session setting and returns to the page it came from."""
    client, state = make_client_and_state()
    assert state.graph_view is False
    resp = client.post("/graph-view", data={"next": "/event/match/0"})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/event/match/0")
    assert state.graph_view is True
    client.post("/graph-view", data={"next": "/event/match/0"})
    assert state.graph_view is False


def test_the_old_mode_endpoint_no_longer_exists():
    """POST /mode (the old basic/advanced toggle) is gone."""
    client = make_client()
    assert client.post("/mode", data={"next": "/"}).status_code == 404


def test_graph_view_toggle_is_on_match_pages_only():
    """The toggle form appears on match pages and on no summary/setup page."""
    client, _ = started_pair_with_a_shared_pass()
    toggle = b'action="/graph-view"'
    assert toggle in client.get("/event/match/0").data
    for url in (
        "/event/rotation",
        "/event/results",
        "/event/stage1",
        "/event/stage2",
        "/event/handicap-calculator",
        "/event/pair/0/1",
    ):
        assert toggle not in client.get(url).data, url


def test_graph_view_button_text_shows_the_current_state():
    """The button reads 'Graph view: off' by default and 'Graph view: on' after toggling."""
    client = make_client()
    start_two_archer_event(client)
    assert b"Graph view: off" in client.get("/event/match/0").data
    client.post("/graph-view", data={"next": "/event/match/0"})
    assert b"Graph view: on" in client.get("/event/match/0").data


def test_nothing_user_facing_calls_it_advanced_or_basic_mode():
    """The old 'advanced mode' / 'basic mode' wording is gone from templates and pages."""
    templates = Path(__file__).resolve().parent.parent / "h2h" / "templates"
    for template in templates.glob("*.html"):
        source = template.read_text(encoding="utf-8").lower()
        assert "advanced mode" not in source, template.name
        assert "basic mode" not in source, template.name

    client, _ = started_pair_with_a_shared_pass()
    for url in ("/event/rotation", "/event/match/0", "/event/results"):
        page = client.get(url).data.decode().lower()
        assert "advanced mode" not in page and "basic mode" not in page
        assert "mode:" not in page


def test_toggling_graph_view_keeps_scores_and_the_current_pass():
    """Switching graph view on and off loses nothing."""
    client, state = started_pair_with_a_shared_pass()
    before = list(state.event.results)
    client.post("/graph-view", data={"next": "/event/match/0"})
    client.post("/graph-view", data={"next": "/event/match/0"})
    assert state.event.results == before
    assert state.event.current_rotation_index == 0
    _, rows = overview_table(client.get("/event/rotation").data.decode())
    assert rows[0][1] == "100 - 60"


# --- Handicaps on the match pages (Feedback 4) ------------------------------


def start_event_with_handicaps(client, handicaps):
    """A 2-archer event (Alice, Bob) with the given handicaps."""
    complete_stage1(client, n_archers=2, total_arrows=12, n_pass=12)
    complete_stage2(client, [("Alice", "Recurve", handicaps[0]), ("Bob", "Compound", handicaps[1])])


def heading(html):
    """The text of the page's <h1>, tags removed and whitespace collapsed."""
    return " ".join(re.sub(r"<[^>]+>", " ", re.search(r"<h1>(.*?)</h1>", html, re.S).group(1)).split())


def test_match_page_heading_has_no_handicaps_but_the_score_labels_do():
    """Feedback 5: names only in the heading; each handicap stays beside its score box."""
    client = make_client()
    start_event_with_handicaps(client, (15, 22.5))
    for expected_state in ("before", "after"):
        page = client.get("/event/match/0").data.decode()
        assert heading(page) == "Alice vs Bob", expected_state
        assert "Alice (handicap 15) score" in page
        assert "Bob (handicap 22.5) score" in page
        save_match(client, 0, {0: 100, 1: 60})


def test_whole_number_handicaps_have_no_trailing_zero_and_decimals_are_in_full():
    """15.0 shows as 15, while 22.5 and 7.25 keep their decimals."""
    client = make_client()
    start_event_with_handicaps(client, (15.0, 7.25))
    page = client.get("/event/match/0").data.decode()
    assert "handicap 15)" in page and "handicap 15.0" not in page
    assert "handicap 7.25)" in page


def test_handicaps_are_attached_to_the_right_archers():
    """With very different handicaps, each appears against its own archer's name."""
    client = make_client()
    start_event_with_handicaps(client, (5, 120))
    page = client.get("/event/match/0").data.decode()
    assert "Alice (handicap 5)" in page and "Bob (handicap 120)" in page
    assert "Alice (handicap 120)" not in page and "Bob (handicap 5)" not in page


def test_bye_match_page_shows_the_bye_archers_handicap():
    """A bye match shows its single archer's handicap."""
    client, state = make_client_and_state()
    start_three_archer_event(client, shoot_byes=True)
    bye_archer = state.event.schedule[0].bye
    expected = state.event.archers[bye_archer]
    page = client.get("/event/match/1").data.decode()
    assert heading(page) == f"{expected.name} - bye, no opponent"
    assert f"{expected.name} (handicap {expected.handicap:g}) score" in page


# --- Simplified "How the winner is decided" text (Feedback 4) ----------------


def winner_explanation_text(html):
    """The plain text of the 'How the winner is decided' block in a rendered page."""
    start = html.index('<div class="maths">')
    block = html[start : html.index("</div>", start)]
    return " ".join(re.sub(r"<[^>]+>", " ", block).split())


def test_winner_explanation_is_short_and_free_of_statistical_jargon():
    """The explanation is brief and avoids the old technical terms."""
    client, _ = started_pair_with_a_shared_pass()
    turn_on_graph_view(client)
    text = winner_explanation_text(client.get("/event/match/0").data.decode())
    assert len(text) < 650  # the old explanation was about 950 characters
    lowered = text.lower()
    for jargon in ("convol", "standard deviation", "sigma", "&sigma", "variance",
                   "humanspec", "indoor-compound", "n_pass", "x-ring"):
        assert jargon not in lowered, jargon


def test_winner_explanation_still_explains_percentile_winner_and_the_vertical_lines():
    """The short text keeps the three ideas a scorer needs."""
    client, _ = started_pair_with_a_shared_pass()
    turn_on_graph_view(client)
    text = winner_explanation_text(client.get("/event/match/0").data.decode())
    assert "percentile" in text
    assert "chance of scoring that much or less" in text
    assert "higher percentile" in text and "wins the pass" in text
    assert "vertical lines" in text and "actually shot" in text


def test_winner_explanation_appears_with_the_chart_only():
    """It shows on the match page and pair-history page with graph view on, never off."""
    client, _ = started_pair_with_a_shared_pass()
    assert "How the winner is decided" not in client.get("/event/match/0").data.decode()
    turn_on_graph_view(client)
    assert "How the winner is decided" in client.get("/event/match/0").data.decode()
    assert "How the winner is decided" in client.get("/event/pair/0/1").data.decode()


def test_winner_explanation_text_lives_in_one_template_only():
    """The wording is in the shared partial, not copied into other templates."""
    templates = Path(__file__).resolve().parent.parent / "h2h" / "templates"
    owners = [
        t.name
        for t in templates.glob("*.html")
        if "chance of scoring that much or less" in t.read_text(encoding="utf-8")
    ]
    assert owners == ["_pair_chart.html"]


# --- Overview table: Match | Score | Percentiles | Winner | Actions (Feedback 4) --


def percent(p):
    """A percentile as the overview formats it, e.g. 0.1234 -> '12.3%'."""
    return f"{p * 100:.1f}%"


def test_overview_table_has_the_five_headed_columns_in_order():
    """The matches table is headed Match, Score, Percentiles, Winner, Actions."""
    client = make_client()
    start_four_archer_event(client)
    headings, rows = overview_table(client.get("/event/rotation").data.decode())
    assert headings == ["Match", "Score", "Percentiles", "Winner", "Actions"]
    assert all(len(row) == 5 for row in rows)


def test_unscored_pair_row_shows_dashes_and_an_enter_scores_link():
    """Before scoring, Score, Percentiles and Winner are '-' and Actions says Enter scores."""
    client = make_client()
    start_four_archer_event(client)
    page = client.get("/event/rotation").data.decode()
    _, rows = overview_table(page)
    assert rows[0] == ["A1 vs A4", "-", "-", "-", "Enter scores"]
    assert 'href="/event/match/0"' in page


def test_scored_pair_row_matches_the_events_recorded_results():
    """After scoring: scores and percentiles in opponent order, the winner's name, View / edit."""
    client, state = make_client_and_state()
    start_four_archer_event(client)
    save_match(client, 0, {0: 60, 3: 100})
    save_match(client, 1, {1: 90, 2: 90})

    event = state.event
    _, rows = overview_table(client.get("/event/rotation").data.decode())
    for row, (a, b) in zip(rows, event.matches(0), strict=True):
        result_a, result_b = event.match_results(0, (a, b))
        winner = result_a if result_a.won else result_b
        assert row == [
            f"{event.archers[a].name} vs {event.archers[b].name}",
            f"{result_a.score} - {result_b.score}",
            f"{percent(result_a.percentile)} - {percent(result_b.percentile)}",
            event.archers[winner.archer_index].name,
            "View / edit",
        ]


def test_score_and_percentile_orientation_follows_the_match_column_for_every_pair():
    """In a pair listed with the higher archer index first, Score/Percentiles keep that order."""
    client, state = make_client_and_state()
    start_four_archer_event(client)
    score_current_pass(client)
    client.post("/event/advance")
    event = state.event
    # Pass 2 of a 4-archer round-robin has a pair listed higher-index first.
    flipped = [i for i, (a, b) in enumerate(event.matches(1)) if a > b]
    assert flipped, "expected a pair listed higher-index first in pass 2"

    for match_index, (a, b) in enumerate(event.matches(1)):
        save_match(client, match_index, {a: 50 + 7 * a, b: 50 + 7 * b})
    _, rows = overview_table(client.get("/event/rotation").data.decode())
    for i in flipped:
        a, b = event.matches(1)[i]
        result_a, result_b = event.match_results(1, (a, b))
        assert rows[i][0] == f"{event.archers[a].name} vs {event.archers[b].name}"
        assert rows[i][1] == f"{50 + 7 * a} - {50 + 7 * b}"
        assert rows[i][2] == f"{percent(result_a.percentile)} - {percent(result_b.percentile)}"


def test_bye_match_row_shows_one_score_one_percentile_and_no_winner():
    """A solo bye match shows its single score and percentile, and '-' as Winner."""
    client, state = make_client_and_state()
    start_three_archer_event(client, shoot_byes=True)
    bye_archer = state.event.schedule[0].bye
    save_match(client, 1, {bye_archer: 70})

    result = state.event.match_results(0, (bye_archer, None))[0]
    _, rows = overview_table(client.get("/event/rotation").data.decode())
    name = state.event.archers[bye_archer].name
    assert rows[1] == [
        f"{name} (bye - no opponent, shoots alone)",
        "70",
        percent(result.percentile),
        "-",
        "View / edit",
    ]


def test_resaving_a_match_updates_its_row_and_awaiting_scores_text_is_gone():
    """The row follows a re-save (including the winner), and no 'Awaiting scores' remains."""
    client, state = make_client_and_state()
    start_two_archer_event(client)
    save_match(client, 0, {0: 120, 1: 0})
    _, rows = overview_table(client.get("/event/rotation").data.decode())
    assert rows[0][3] == "Alice"
    save_match(client, 0, {0: 0, 1: 120})
    page = client.get("/event/rotation").data.decode()
    _, rows = overview_table(page)
    assert rows[0][1] == "0 - 120" and rows[0][3] == "Bob"
    assert "Awaiting scores" not in page


# --- Reset confirmation (Feedback 4) ----------------------------------------


def test_get_reset_shows_a_confirmation_page_and_changes_nothing():
    """GET /reset asks first: it has a POST button and a cancel link, and loses nothing."""
    client, state = started_pair_with_a_shared_pass()
    results_before = list(state.event.results)
    event_before = state.event

    resp = client.get("/reset")
    page = resp.data.decode()
    assert resp.status_code == 200
    assert "Reset everything" in page
    assert '<form method="post" action="/reset">' in page
    assert 'href="/event/rotation"' in page  # cancel goes back to the current pass

    assert state.event is event_before
    assert state.event.results == results_before
    assert state.n_archers == 2 and state.schedule is not None


def test_post_reset_clears_everything_and_goes_to_stage1():
    """Only the confirming POST resets, back to a fresh session at Stage 1."""
    client, state = started_pair_with_a_shared_pass()
    client.post("/graph-view", data={"next": "/"})
    resp = client.post("/reset")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/event/stage1")
    assert state.event is None
    assert state.schedule is None and state.n_archers is None
    assert state.graph_view is False
    assert state.shoot_byes is True


def test_cancel_link_goes_to_stage1_when_there_is_no_event():
    """With nothing to lose yet, the cancel link points at Stage 1."""
    client = make_client()
    page = client.get("/reset").data.decode()
    assert 'href="/event/stage1"' in page
    assert "Cancel" in page


def test_nav_reset_link_points_at_the_confirmation_page():
    """The nav's Reset link is a plain link to /reset (the confirmation page)."""
    client = make_client()
    assert b'<a href="/reset">Reset</a>' in client.get("/event/stage1").data


def test_following_the_reset_link_without_confirming_never_loses_scores():
    """Opening the confirmation page and then going elsewhere keeps the scores."""
    client, state = started_pair_with_a_shared_pass()
    client.get("/reset")
    client.get("/event/rotation")
    _, rows = overview_table(client.get("/event/rotation").data.decode())
    assert rows[0][1] == "100 - 60"
    assert state.event is not None


# --- Stage 1 simple/advanced setup (Feedback 4) ------------------------------


def select_block(page, name):
    """The HTML of the <select name="..."> element in a page."""
    start = page.index(f'<select name="{name}"')
    return page[start : page.index("</select>", start)]


def option_values(block):
    """The value attributes of the <option>s in an HTML block, in order."""
    return re.findall(r'<option value="([^"]*)"', block)


def stage2_intro(page):
    """The Stage 2 introductory paragraph, as whitespace-normalised text."""
    start = page.index("Enter each of the")
    return " ".join(re.sub(r"<[^>]+>", " ", page[start : page.index("</p>", start)]).split())


def test_stage1_has_setup_mode_toggle_with_simple_selected_by_default():
    """A fresh Stage 1 offers Simple (selected) and Advanced setup modes."""
    page = make_client().get("/event/stage1").data.decode()
    simple = page[page.index('name="setup_mode" value="simple"') :].split(">")[0]
    advanced = page[page.index('name="setup_mode" value="advanced"') :].split(">")[0]
    assert "checked" in simple
    assert "checked" not in advanced


def test_stage1_distance_dropdown_has_exactly_the_standard_options_grouped():
    """The Distance dropdown has Metric and Imperial groups with the 16 standard distances."""
    page = make_client().get("/event/stage1").data.decode()
    block = select_block(page, "distance")
    assert '<optgroup label="Metric">' in block and '<optgroup label="Imperial">' in block
    assert option_values(block) == [
        "18m", "25m", "30m", "40m", "50m", "60m", "70m", "90m",
        "20yd", "25yd", "30yd", "40yd", "50yd", "60yd", "80yd", "100yd",
    ]
    assert '<option value="20yd" selected>20 yd</option>' in block  # the default
    assert ">18 m</option>" in block and ">100 yd</option>" in block


def test_stage1_face_size_dropdown_has_the_four_standard_faces():
    """The Face size dropdown offers 40, 60, 80 and 122 cm, 60 selected."""
    block = select_block(make_client().get("/event/stage1").data.decode(), "face_cm")
    assert option_values(block) == ["40", "60", "80", "122"]
    assert '<option value="60" selected>60 cm</option>' in block


def test_stage1_no_longer_has_the_indoor_outdoor_or_named_round_choices():
    """The old Indoor/Outdoor and Portsmouth/WA 18 radios are gone from Stage 1."""
    page = make_client().get("/event/stage1").data.decode()
    for old in ('name="round_mode"', 'name="indoor_round"', "Portsmouth", "WA 18", "Outdoor"):
        assert old not in page, old


def test_posting_a_simple_setup_stores_it_and_it_is_remembered_on_return():
    """A chosen distance and face are stored in the session and re-selected on Stage 1."""
    client, state = make_client_and_state()
    resp = client.post("/event/stage1", data=stage1_form(distance="50m", face_cm=80))
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/event/stage2")
    assert state.target_setup == TargetSetup(distance=50, unit=METRE, face_cm=80)

    page = client.get("/event/stage1").data.decode()
    assert '<option value="50m" selected>' in select_block(page, "distance")
    assert '<option value="80" selected>' in select_block(page, "face_cm")


@pytest.mark.parametrize(
    ("distance", "face", "expected"),
    [
        ("20m", 60, b"standard distances"),
        ("abc", 60, b"standard distances"),
        ("", 60, b"standard distances"),
        ("18m", 50, b"standard face sizes"),
        ("18m", "abc", b"standard face sizes"),
    ],
)
def test_a_distance_or_face_outside_the_options_is_rejected_and_stores_nothing(
    distance, face, expected
):
    """A forged distance/face value gets a clear message and leaves the session untouched."""
    client, state = make_client_and_state()
    resp = client.post("/event/stage1", data=stage1_form(distance=distance, face_cm=face))
    assert resp.status_code == 200
    assert expected in resp.data
    assert state.schedule is None
    assert state.target_setup == DEFAULT_TARGET_SETUP


def test_stage2_intro_names_the_distance_face_and_whether_it_counts_as_indoor():
    """Stage 2 says what everyone shoots, and the reduced-10 note appears only indoors."""
    client = make_client()
    complete_stage1(client, n_archers=2, distance="20yd", face_cm=60)
    intro = stage2_intro(client.get("/event/stage2").data.decode())
    assert "20 yd" in intro and "60 cm" in intro and "indoor" in intro
    assert "inner ring" in intro

    complete_stage1(client, n_archers=2, distance="50m", face_cm=80)
    intro = stage2_intro(client.get("/event/stage2").data.decode())
    assert "50 m" in intro and "80 cm" in intro and "outdoor" in intro
    assert "inner ring" not in intro


def test_no_leftover_reference_to_the_old_round_mode_form_in_the_app():
    """The app package has no round-mode names or temporary bridge left."""
    root = Path(__file__).resolve().parent.parent / "h2h"
    sources = [p for p in root.rglob("*") if p.suffix in {".py", ".html", ".js"}]
    assert sources
    # (`resolve_indoor_round` is the calculator's legitimate function, so only the old
    # quoted form-field name is forbidden, not the substring.)
    forbidden = ["round_mode", '"indoor_round"', "RoundMode", "_bridge", "OUTDOOR"]
    for path in sources:
        text = path.read_text(encoding="utf-8")
        for name in forbidden:
            assert name not in text, f"{name} in {path.name}"


# --- Stage 3: random pairing assignment with redraw (Feedback 4) ---------------------

NAMES = ["Ann", "Ben", "Cat", "Dan", "Eve", "Fay", "Gus", "Hal"]


def client_at_stage3(n=4, total_arrows=36, rng=None, shoot_byes=True):
    """A client + state that has completed Stages 1 and 2 (no event yet), drawn with `rng`."""
    state = SessionState(rng=rng or random.Random(0))
    client = create_app(state=state).test_client()
    form = stage1_form(n_archers=n, total_arrows=total_arrows)
    form["shoot_byes"] = "yes" if shoot_byes else "no"
    client.post("/event/stage1", data=form)
    client.post(
        "/event/stage2",
        data=stage2_form([(NAMES[i], "Recurve", 15 + 5 * i) for i in range(n)]),
    )
    return client, state


def stage3_matches(page):
    """For each pass on the Stage 3 page, the list of 'X vs Y' pairings it shows."""
    _, rows = overview_table(page)
    return [re.findall(r"[A-Z][a-z]+ vs [A-Z][a-z]+", row[1]) for row in rows]


def test_stage2_submission_redirects_to_stage3_and_draws_an_assignment():
    """Stage 2 -> Stage 3, with the archers stored, a draw made, and no event."""
    client, state = client_at_stage3()
    assert state.event is None
    assert [a.name for a in state.pending_archers] == NAMES[:4]
    assert sorted(state.assignment) == [0, 1, 2, 3]


def test_a_rejected_stage2_submission_draws_nothing_and_does_not_reach_stage3():
    """Invalid input (a bad handicap) stays on Stage 2 with no draw."""
    state = SessionState(rng=random.Random(0))
    client = create_app(state=state).test_client()
    client.post("/event/stage1", data=stage1_form(n_archers=2))
    resp = client.post(
        "/event/stage2", data=stage2_form([("Ann", "Recurve", 20), ("Ben", "Compound", 999)])
    )
    assert resp.status_code == 200 and b"Stage 2" in resp.data
    assert state.pending_archers is None and state.assignment is None


def test_stage3_shows_every_pass_with_its_pairings_by_name():
    """One row per pass of the schedule, each pairing listed, every archer appearing."""
    client, state = client_at_stage3(n=4, total_arrows=36)
    page = client.get("/event/stage3").data.decode()
    headings, rows = overview_table(page)
    assert headings == ["Pass", "Matches", "Sitting out"]
    assert [row[0] for row in rows] == ["1", "2", "3"]
    pairings = stage3_matches(page)
    assert all(len(p) == 2 for p in pairings)  # two matches in each of the three passes
    for name in NAMES[:4]:
        assert name in page
    # Over a full round-robin every pair of the four archers appears exactly once.
    seen = {frozenset(m.split(" vs ")) for p in pairings for m in p}
    assert len(seen) == 6


def test_stage3_shows_the_bye_archer_shooting_alone_when_byes_are_shot():
    """With byes shot, each pass lists a '(bye - shoots alone)' entry."""
    client, _ = client_at_stage3(n=3, total_arrows=36, shoot_byes=True)
    _, rows = overview_table(client.get("/event/stage3").data.decode())
    assert len(rows) == 3
    assert all("(bye - shoots alone)" in row[1] for row in rows)
    assert all(row[2] == "-" for row in rows)


def test_stage3_lists_who_sits_out_when_byes_are_not_shot():
    """With byes not shot, the sitting-out archers are named and nobody shoots alone."""
    client, state = client_at_stage3(n=5, total_arrows=60, shoot_byes=False)
    page = client.get("/event/stage3").data.decode()
    _, rows = overview_table(page)
    assert len(rows) == len(state.schedule) == 7
    assert all("bye" not in row[1] for row in rows)
    archers = state.assigned_archers()
    for row, rotation in zip(rows, state.schedule, strict=True):
        assert row[2] == ", ".join(archers[i].name for i in rotation.sitting_out)


def test_reloading_stage3_without_redrawing_shows_the_same_assignment():
    """GET is stable: only the Redraw button changes the draw."""
    client, state = client_at_stage3()
    first = client.get("/event/stage3").data
    second = client.get("/event/stage3").data
    assert first == second


def test_redraw_shows_different_pairings_and_stays_on_stage3():
    """POST redraw gives a valid new draw whose pairings differ, and returns to Stage 3."""
    client, state = client_at_stage3(rng=random.Random(5))
    before = stage3_matches(client.get("/event/stage3").data.decode())
    resp = client.post("/event/stage3/redraw")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/event/stage3")
    assert sorted(state.assignment) == [0, 1, 2, 3]
    after = stage3_matches(client.get("/event/stage3").data.decode())
    assert after != before
    assert state.event is None


def test_confirming_starts_the_event_with_exactly_the_pairings_shown():
    """Confirm builds the event from the shown draw; the overview's first pass matches it."""
    client, state = client_at_stage3(rng=random.Random(7))
    shown_first_pass = stage3_matches(client.get("/event/stage3").data.decode())[0]
    resp = client.post("/event/stage3")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/event/rotation")

    event = state.event
    assert event is not None
    assert [a.name for a in event.archers] == [state.pending_archers[i].name for i in state.assignment]
    _, rows = overview_table(client.get("/event/rotation").data.decode())
    assert [row[0] for row in rows] == shown_first_pass


def test_stage3_without_completing_stage2_redirects_back_to_setup():
    """No Stage 1 -> Stage 1; Stage 1 done but no archers yet -> Stage 2."""
    state = SessionState()
    client = create_app(state=state).test_client()
    assert client.get("/event/stage3").headers["Location"].endswith("/event/stage1")
    assert client.post("/event/stage3").headers["Location"].endswith("/event/stage1")
    assert client.post("/event/stage3/redraw").headers["Location"].endswith("/event/stage1")

    client.post("/event/stage1", data=stage1_form(n_archers=3))
    assert client.get("/event/stage3").headers["Location"].endswith("/event/stage2")
    assert client.post("/event/stage3").headers["Location"].endswith("/event/stage2")
    assert state.event is None


def test_once_the_event_has_started_stage3_redirects_and_changes_nothing():
    """After confirming, neither page nor either button can alter the running event."""
    client, state = client_at_stage3(rng=random.Random(9))
    client.post("/event/stage3")
    event, assignment = state.event, list(state.assignment)
    save_match(client, 0, {p: 60 for p in event.matches(0)[0]})

    for response in (
        client.get("/event/stage3"),
        client.post("/event/stage3"),
        client.post("/event/stage3/redraw"),
    ):
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/event/rotation")
    assert state.event is event
    assert state.assignment == assignment
    assert event.results  # the scored match is still there


# --- Tie-break tick boxes on the match page (Feedback 5) --------------------------


def start_tied_pair_event(client):
    """Ann and Ben: same handicap, bowstyle and target, so equal scores tie exactly."""
    complete_stage1(client, n_archers=2, total_arrows=24, n_pass=12)
    complete_stage2(client, [("Ann", "Recurve", 30), ("Ben", "Recurve", 30)])


def closest_boxes(html):
    """The (value, checked) pairs of the page's `closest` checkboxes."""
    found = re.findall(r'<input type="checkbox" name="closest" value="(\d+)"([^>]*)>', html)
    return [(value, "checked" in attrs) for value, attrs in found]


def test_paired_match_page_has_two_closest_boxes_and_the_note_but_a_bye_match_has_none():
    """One box per archer, with the 'only used if tied' explanation; no boxes for a solo bye."""
    client, state = make_client_and_state()
    start_tied_pair_event(client)
    page = client.get("/event/match/0").data.decode()
    assert closest_boxes(page) == [("0", False), ("1", False)]
    assert "Only used if the percentile and the score are exactly tied" in page
    assert page.count('type="checkbox"') == 2

    client, state = make_client_and_state()
    start_three_archer_event(client, shoot_byes=True)
    assert 'type="checkbox"' not in client.get("/event/match/1").data.decode()


def test_a_tie_without_a_tick_is_refused_with_a_message_and_the_typed_scores_kept():
    """Nothing is saved; the page asks for the tick and refills the score boxes."""
    client, state = make_client_and_state()
    start_tied_pair_event(client)
    resp = save_match(client, 0, {0: 90, 1: 90})
    page = resp.data.decode()
    assert resp.status_code == 200
    assert "Percentile and score are tied. Tick which archer" in page
    assert page.count('value="90"') == 2
    assert state.event.results == []
    assert closest_boxes(page) == [("0", False), ("1", False)]


def test_a_tie_with_a_tick_is_saved_and_decided_for_the_ticked_archer():
    """The ticked archer wins everywhere, the page says why, and the box stays ticked."""
    client, state = make_client_and_state()
    start_tied_pair_event(client)
    resp = save_match(client, 0, {0: 90, 1: 90}, closest=1)
    assert resp.status_code == 302

    page = client.get("/event/match/0").data.decode()
    _, rows = match_page_table(page)
    assert [row[3] for row in rows] == ["No", "Yes"]
    assert "Percentile and score were tied; decided by closest to the middle." in page
    assert closest_boxes(page) == [("0", False), ("1", True)]
    _, overview = overview_table(client.get("/event/rotation").data.decode())
    assert overview[0][3] == "Ben"


def test_ticking_both_boxes_is_rejected_even_when_the_scores_are_not_tied():
    """The server enforces exclusivity itself; nothing is recorded."""
    client, state = make_client_and_state()
    start_tied_pair_event(client)
    resp = client.post(
        "/event/match/0", data={"score_0": "100", "score_1": "60", "closest": ["0", "1"]}
    )
    assert resp.status_code == 200
    assert "Tick only one archer" in resp.data.decode()
    assert state.event.results == []


def test_a_closest_value_outside_the_match_is_rejected():
    """A forced POST naming a different archer is refused and records nothing."""
    client, state = make_client_and_state()
    start_tied_pair_event(client)
    resp = client.post("/event/match/0", data={"score_0": "90", "score_1": "90", "closest": "7"})
    assert resp.status_code == 200
    assert "must be one of the two in this match" in resp.data.decode()
    assert state.event.results == []


def test_an_unneeded_tick_is_ignored_and_not_shown_afterwards():
    """Different scores: the percentile decides, and the reopened page has nothing ticked."""
    client, state = make_client_and_state()
    start_tied_pair_event(client)
    assert save_match(client, 0, {0: 100, 1: 60}, closest=1).status_code == 302
    page = client.get("/event/match/0").data.decode()
    _, rows = match_page_table(page)
    assert [row[3] for row in rows] == ["Yes", "No"]  # the better score won, not the tick
    assert closest_boxes(page) == [("0", False), ("1", False)]
    assert "decided by closest" not in page


def test_editing_a_decided_by_closest_match_to_untied_scores_clears_the_note():
    """Re-saving with scores that no longer tie replaces the result and drops the tie note."""
    client, state = make_client_and_state()
    start_tied_pair_event(client)
    save_match(client, 0, {0: 90, 1: 90}, closest=0)
    save_match(client, 0, {0: 90, 1: 95})
    page = client.get("/event/match/0").data.decode()
    _, rows = match_page_table(page)
    assert [row[3] for row in rows] == ["No", "Yes"]
    assert "decided by closest" not in page
    assert closest_boxes(page) == [("0", False), ("1", False)]


def test_editing_a_decided_match_back_to_a_tie_without_a_tick_keeps_the_saved_result():
    """The rejected re-save leaves the earlier result and its tick in place."""
    client, state = make_client_and_state()
    start_tied_pair_event(client)
    save_match(client, 0, {0: 90, 1: 95})
    resp = save_match(client, 0, {0: 90, 1: 90})
    assert "Percentile and score are tied" in resp.data.decode()
    assert [(r.archer_index, r.score) for r in state.event.results] == [(0, 90), (1, 95)]


def test_the_tie_message_survives_a_rejected_tie_that_had_a_wrong_tick():
    """A tie with both boxes ticked is rejected for the ticks, not mistaken for a plain tie."""
    client, state = make_client_and_state()
    start_tied_pair_event(client)
    resp = client.post("/event/match/0", data={"score_0": "90", "score_1": "90", "closest": ["0", "1"]})
    page = resp.data.decode()
    assert "Tick only one archer" in page and "Percentile and score are tied" not in page
    assert closest_boxes(page) == [("0", True), ("1", True)]  # shown as submitted


def test_the_match_page_script_makes_the_boxes_exclusive():
    """The page carries the small script that clears the other box (browser-checked separately)."""
    client, state = make_client_and_state()
    start_tied_pair_event(client)
    page = client.get("/event/match/0").data.decode()
    assert "input[name=\"closest\"]" in page
    assert "other.checked = false" in page


# --- Per-target maximum score on the match page (Feedback 5) ------------------------


def test_match_page_score_boxes_use_each_archers_own_maximum():
    """A 5-zone archer's box tops out at 9 per arrow, a 10-zone archer's at 10."""
    from h2h.models import YARD, Archer, Bowstyle, Event
    from h2h.rotation import build_schedule

    state = make_state()
    archers = [
        Archer("Fiver", 30, Bowstyle.RECURVE, target_setup=TargetSetup(20, YARD, 60, "5_zone")),
        Archer("Tenner", 30, Bowstyle.RECURVE, target_setup=TargetSetup(20, YARD, 60, "10_zone")),
    ]
    state.schedule = build_schedule(2, 1)
    state.event = Event(archers, 12, None, state.schedule)
    client = create_app(state=state).test_client()

    page = client.get("/event/match/0").data.decode()
    assert "Fiver (handicap 30) score (0-108)" in page
    assert "Tenner (handicap 30) score (0-120)" in page
    assert 'max="108" name="score_0"' in page and 'max="120" name="score_1"' in page

    too_high = save_match(client, 0, {0: 109, 1: 100})
    assert too_high.status_code == 200
    assert b"between 0 and 108" in too_high.data
    assert state.event.results == []
    assert save_match(client, 0, {0: 108, 1: 119}).status_code == 302


# --- Advanced setup: per-archer face type, face size and distance (Feedback 5) -------

from h2h.stats import percentile as stats_percentile  # noqa: E402

ADVANCED_ARCHERS = [
    # name, bowstyle, handicap, face type, face size, distance
    ("Ann", "Recurve", 20, "10_zone", 40, "18m"),
    ("Ben", "Compound", 25, "10_zone_compound", 40, "18m"),
    ("Cat", "Barebow", 35, "5_zone", 122, "50yd"),
    ("Dan", "Longbow", 45, "Worcester", 40, "20yd"),
]


def advanced_form(rows=ADVANCED_ARCHERS):
    """A /event/stage2 payload for advanced setup from the tuples in ADVANCED_ARCHERS."""
    form = {}
    for i, (name, bowstyle, handicap, face_type, face_cm, distance) in enumerate(rows):
        form.update(
            {
                f"name_{i}": name,
                f"bowstyle_{i}": bowstyle,
                f"handicap_{i}": str(handicap),
                f"face_type_{i}": face_type,
                f"face_cm_{i}": str(face_cm),
                f"distance_{i}": distance,
            }
        )
    return form


def start_advanced_stage2(client, n_archers=4, total_arrows=36):
    """Run Stage 1 in advanced mode so the advanced Stage 2 page is reachable."""
    return client.post(
        "/event/stage1",
        data=stage1_form(n_archers=n_archers, total_arrows=total_arrows, setup_mode="advanced"),
    )


def test_advanced_is_no_longer_a_placeholder_and_the_submit_button_is_never_disabled():
    """Stage 1 renders both modes with Continue enabled; nothing in the templates says TBA."""
    page = make_client().get("/event/stage1").data.decode()
    button = re.search(r'<button[^>]*id="stage1_submit"[^>]*>', page).group(0)
    assert "disabled" not in button
    assert "TBA" not in page
    templates = Path(__file__).resolve().parent.parent / "h2h" / "templates"
    assert all("TBA" not in p.read_text(encoding="utf-8") for p in templates.glob("*.html"))


def test_posting_advanced_mode_goes_to_stage_2_and_keeps_the_last_simple_choice():
    """Advanced is stored, the schedule is built, and the simple distance/face are left alone."""
    client, state = make_client_and_state()
    client.post("/event/stage1", data=stage1_form(n_archers=4, distance="50m", face_cm=80))
    resp = start_advanced_stage2(client, n_archers=6, total_arrows=36)
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/event/stage2")
    assert state.setup_mode == "advanced"
    assert state.n_archers == 6 and state.schedule is not None
    assert state.target_setup == TargetSetup(distance=50, unit=METRE, face_cm=80)


def test_advanced_mode_ignores_the_hidden_simple_dropdowns():
    """Whatever the hidden distance/face fields hold, an advanced POST does not validate them."""
    client, state = make_client_and_state()
    data = stage1_form(n_archers=4, distance="not-a-distance", face_cm="abc", setup_mode="advanced")
    assert client.post("/event/stage1", data=data).status_code == 302
    assert state.setup_mode == "advanced"


def test_an_unknown_setup_mode_is_rejected_and_stores_nothing():
    """Only simple and advanced exist."""
    client, state = make_client_and_state()
    resp = client.post("/event/stage1", data=stage1_form(setup_mode="expert"))
    assert resp.status_code == 200
    assert b"Setup mode must be Simple or Advanced" in resp.data
    assert state.schedule is None


def test_returning_to_stage_1_shows_the_chosen_mode_and_reset_restores_simple():
    """Advanced stays selected on return, with the simple section hidden; Reset goes back to simple."""
    client, state = make_client_and_state()
    start_advanced_stage2(client)
    page = client.get("/event/stage1").data.decode()
    advanced = page[page.index('name="setup_mode" value="advanced"') :].split(">")[0]
    assert "checked" in advanced
    assert "hidden" in page[page.index('<div id="simple_setup"') :].split(">")[0]
    assert "hidden" not in page[page.index('<div id="advanced_setup"') :].split(">")[0]

    client.post("/reset")
    assert state.setup_mode == "simple"
    page = client.get("/event/stage1").data.decode()
    simple = page[page.index('name="setup_mode" value="simple"') :].split(">")[0]
    assert "checked" in simple


def test_a_rejected_stage_1_keeps_the_mode_that_was_posted():
    """An invalid number of archers in advanced mode re-renders with Advanced still selected."""
    client = make_client()
    resp = client.post("/event/stage1", data=stage1_form(n_archers=1, setup_mode="advanced"))
    page = resp.data.decode()
    assert b"at least 2 archers" in resp.data
    assert "checked" in page[page.index('name="setup_mode" value="advanced"') :].split(">")[0]


def test_advanced_stage_2_has_three_dropdowns_per_archer_with_the_right_options_and_defaults():
    """Face type (16, 10 zone selected), face size (8, 60 selected), distance (16, 20 yd selected)."""
    client = make_client()
    start_advanced_stage2(client, n_archers=3, total_arrows=36)
    page = client.get("/event/stage2").data.decode()
    for i in range(3):
        face_type = select_block(page, f"face_type_{i}")
        assert len(option_values(face_type)) == 16
        assert '<option value="10_zone" selected>' in face_type
        assert "10 zone (standard 10-ring face)" in face_type
        face_size = select_block(page, f"face_cm_{i}")
        assert option_values(face_size) == ["20", "35", "40", "50", "60", "65", "80", "122"]
        assert '<option value="60" selected>' in face_size
        distance = select_block(page, f"distance_{i}")
        assert len(option_values(distance)) == 16
        assert '<optgroup label="Metric">' in distance and '<optgroup label="Imperial">' in distance
        assert '<option value="20yd" selected>' in distance
    assert "Target face type" in page and "Face size" in page and "Distance" in page


def test_simple_stage_2_has_none_of_the_per_archer_target_dropdowns():
    """Simple mode's Stage 2 is unchanged."""
    client = make_client()
    complete_stage1(client, n_archers=2)
    page = client.get("/event/stage2").data.decode()
    assert "face_type_" not in page and "face_cm_" not in page and 'name="distance_' not in page
    assert "Everyone shoots 20 yd" in stage2_intro(page)


def test_valid_advanced_rows_give_each_archer_their_own_target_through_stage_3():
    """The chosen face type, size and distance end up on each archer's resolved target."""
    client, state = make_client_and_state()
    start_advanced_stage2(client)
    resp = client.post("/event/stage2", data=advanced_form())
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/event/stage3")
    assert all(a.target_setup is not None for a in state.pending_archers)
    client.post("/event/stage3")

    targets = [state.event.target_for(i) for i in range(4)]
    assert [t.scoring_system for t in targets] == ["10_zone", "10_zone_compound", "5_zone", "Worcester"]
    assert [round(t.diameter * 100) for t in targets] == [40, 40, 122, 40]
    assert [round(t.distance, 3) for t in targets] == [18.0, 18.0, 45.72, 18.288]
    assert [t.indoor for t in targets] == [True, True, False, True]
    assert state.event.target_setup is None


@pytest.mark.parametrize(
    ("column", "bad", "expected"),
    [
        (5, "19m", "standard distances"),
        (4, "45", "standard face sizes"),
        (3, "bogus", "target face types"),
        (3, "Custom", "target face types"),
    ],
)
def test_an_invalid_target_value_names_the_row_stores_nothing_and_refills_the_form(
    column, bad, expected
):
    """A bad face type, size or distance in row 3 is refused with 'Row 3: ...' and the form refilled."""
    client, state = make_client_and_state()
    start_advanced_stage2(client)
    rows = [list(r) for r in ADVANCED_ARCHERS]
    rows[2][column] = bad
    resp = client.post("/event/stage2", data=advanced_form(rows))
    page = resp.data.decode()
    assert resp.status_code == 200
    assert "Row 3:" in page and expected in page
    assert state.pending_archers is None and state.event is None
    assert 'value="Cat"' in page and 'value="Dan"' in page
    assert '<option value="Worcester" selected>' in select_block(page, "face_type_3")


def test_a_missing_advanced_field_is_rejected_not_defaulted():
    """A forced POST without the per-archer target fields is refused rather than guessed."""
    client, state = make_client_and_state()
    start_advanced_stage2(client, n_archers=2, total_arrows=24)
    resp = client.post("/event/stage2", data=stage2_form([("Ann", "Recurve", 20), ("Ben", "Recurve", 30)]))
    assert resp.status_code == 200 and b"Row 1:" in resp.data
    assert state.pending_archers is None


def test_a_full_advanced_event_with_mixed_targets_plays_through_over_http():
    """5-zone and 10-zone archers: each score is checked against its own maximum, the pages render."""
    client, state = make_client_and_state()
    start_advanced_stage2(client, n_archers=2, total_arrows=24)
    rows = [
        ("Fiver", "Recurve", 30, "5_zone", 60, "20yd"),
        ("Tenner", "Recurve", 30, "10_zone", 60, "20yd"),
    ]
    client.post("/event/stage2", data=advanced_form(rows))
    client.post("/event/stage3")
    event = state.event
    assert event.max_score_for(0) == 108 and event.max_score_for(1) == 120

    too_high = save_match(client, 0, {0: 110, 1: 100})
    assert b"between 0 and 108" in too_high.data and event.results == []
    for pass_number in (1, 2):
        assert save_match(client, 0, {0: 100, 1: 110}).status_code == 302
        if pass_number == 1:
            assert client.post("/event/advance").status_code == 302
    assert event.is_complete
    for path in ("/event/rotation", "/event/results", "/event/match/0"):
        assert client.get(path).status_code == 200
    results = {r.archer_index: r for r in event.results if r.rotation_index == 0}
    assert results[0].percentile == pytest.approx(
        stats_percentile(event.distribution_for(0), 100)
    )
    assert results[1].percentile == pytest.approx(
        stats_percentile(event.distribution_for(1), 110)
    )
    assert results[0].percentile != results[1].percentile
