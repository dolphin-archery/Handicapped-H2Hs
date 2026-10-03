"""End-to-end integration checks for the rotation-based event flow.

Exercises the full HTTP flow (Stage 1 -> Stage 2 -> overview / per-match
pages / advance for every pass -> results) against the real Flask app,
covering the scenarios prd.json task 25 calls out: even/odd n_archers (bye
handling), indoor mode with mixed bowstyles, outdoor mode, and that a fresh
app/state sees no prior event.
"""

import random
import re

from h2h.app import create_app
from h2h.models import Bowstyle, resolve_target
from h2h.state import SessionState

from .helpers import (
    OUTDOOR_70M,
    PORTSMOUTH,
    make_state,
    overview_table,
    pass_position,
    play_whole_event,
    save_match,
    score_current_pass,
)


def make_client():
    """A Flask test client with its own isolated SessionState."""
    return create_app(state=make_state()).test_client()


def stage1_form(n_archers, total_arrows=60, n_pass=12, distance="20yd", face_cm=60):
    """Build a /event/stage1 form payload (simple setup)."""
    return {
        "n_archers": str(n_archers),
        "total_arrows": str(total_arrows),
        "n_pass": str(n_pass),
        "setup_mode": "simple",
        "distance": distance,
        "face_cm": str(face_cm),
    }


def stage2_form(archers):
    form = {}
    for i, (name, bowstyle, handicap) in enumerate(archers):
        form[f"name_{i}"] = name
        form[f"bowstyle_{i}"] = bowstyle
        form[f"handicap_{i}"] = str(handicap)
    return form


def run_full_event(client, archers, n_pass=12, total_arrows=None, distance="20yd", face_cm=60, score_fn=None):
    """Complete Stage 1 + Stage 2, then score every pass to completion.

    Parameters
    ----------
    score_fn : callable(archer_index) -> int, optional
        Score generator; defaults to a fixed 60 for everyone.
    """
    n_archers = len(archers)
    if total_arrows is None:
        n_rotations = n_archers if n_archers % 2 else n_archers - 1
        total_arrows = n_rotations * n_pass
    client.post(
        "/event/stage1",
        data=stage1_form(n_archers, total_arrows, n_pass, distance, face_cm),
    )
    client.post("/event/stage2", data=stage2_form(archers))
    client.post("/event/stage3")

    if score_fn is None:
        play_whole_event(client)
    else:
        play_whole_event(client, score_fn)

    return client.get("/event/results")


def test_even_n_archers_full_round_robin_coverage():
    """Even n_archers: every archer faces every other archer exactly once."""
    client = make_client()
    archers = [(f"A{i}", "Recurve", 20 + i) for i in range(4)]
    resp = run_full_event(client, archers)
    assert resp.status_code == 200
    for name, _, _ in archers:
        assert name.encode() in resp.data


def test_odd_n_archers_each_rotation_has_exactly_one_bye():
    """Odd n_archers: every pass has two pairs and one solo bye match, scored with no winner."""
    client = make_client()
    archers = [(f"A{i}", "Recurve", 20 + i) for i in range(5)]
    client.post("/event/stage1", data=stage1_form(5, total_arrows=60, n_pass=12))
    client.post("/event/stage2", data=stage2_form(archers))
    client.post("/event/stage3")

    for pass_number in range(1, 6):  # 5 passes for 5 archers, one full round-robin
        assert pass_position(client) == (pass_number, 5)
        assert b"bye" in client.get("/event/rotation").data.lower()
        matches = score_current_pass(client)
        assert sorted(len(m) for m in matches) == [1, 2, 2]  # 2 pairs + 1 bye archer
        assert len({a for m in matches for a in m}) == 5  # everyone shoots
        if pass_number < 5:
            client.post("/event/advance")

    results = client.get("/event/results")
    # Every archer must appear at least once as a bye-labelled opponent.
    assert results.data.count(b"bye") >= 5


def test_indoor_mode_compound_archer_uses_compound_target():
    """Indoor mode: a Compound archer's distribution must use the compound scoring target."""
    compound_target = resolve_target(PORTSMOUTH, Bowstyle.COMPOUND)
    recurve_target = resolve_target(PORTSMOUTH, Bowstyle.RECURVE)
    assert compound_target.scoring_system == "10_zone_compound"
    assert recurve_target.scoring_system == "10_zone"

    client = make_client()
    archers = [("Rec", "Recurve", 20), ("Comp", "Compound", 20)]
    client.post("/event/stage1", data=stage1_form(2, total_arrows=12, n_pass=12))
    client.post("/event/stage2", data=stage2_form(archers))
    client.post("/event/stage3")
    save_match(client, 0, {0: 100, 1: 100})
    results_resp = client.get("/event/results", follow_redirects=True)
    # Same raw score, different bowstyle/target -> different equivalent handicaps.
    assert results_resp.status_code == 200


def test_outdoor_mode_ignores_bowstyle_for_target():
    """Outdoor mode: every bowstyle resolves to the same target."""
    for bowstyle in Bowstyle:
        target = resolve_target(OUTDOOR_70M, bowstyle)
        assert target.scoring_system == "10_zone"
        assert target.distance == resolve_target(OUTDOOR_70M, Bowstyle.RECURVE).distance


def test_fresh_app_state_sees_no_prior_event():
    """A brand-new app/SessionState (the in-memory analogue of a restart) has no event."""
    first_client = make_client()
    archers = [("Alice", "Recurve", 20), ("Bob", "Compound", 30)]
    run_full_event(first_client, archers)
    assert b"Alice" in first_client.get("/event/results").data

    second_client = make_client()
    resp = second_client.get("/event/results", follow_redirects=True)
    assert b"Alice" not in resp.data


# --- Feedback 3: overview / match pages / advance, bye modes, Longbow ------


def make_client_and_state():
    """A Flask test client plus the SessionState it uses, for inspecting the Event."""
    state = make_state()
    return create_app(state=state).test_client(), state


def start_event(client, archers, total_arrows, n_pass=12, shoot_byes=True, **stage1_kwargs):
    """Run Stage 1 and Stage 2 (without scoring anything)."""
    form = stage1_form(len(archers), total_arrows, n_pass, **stage1_kwargs)
    form["shoot_byes"] = "yes" if shoot_byes else "no"
    client.post("/event/stage1", data=form)
    client.post("/event/stage2", data=stage2_form(archers))
    client.post("/event/stage3")


def passes_shot(event):
    """{archer_index: number of passes they have a recorded result for}."""
    counts = {i: 0 for i in range(len(event.archers))}
    for result in event.results:
        counts[result.archer_index] += 1
    return counts


def test_even_n_archers_every_pair_appears_in_the_pairwise_results():
    """Even n_archers: a full event completes and all n*(n-1)/2 pairs have a result."""
    client, state = make_client_and_state()
    archers = [(f"A{i}", "Recurve", 20 + 5 * i) for i in range(4)]
    start_event(client, archers, total_arrows=36)  # 3 passes = a full round-robin of 4
    passes = play_whole_event(client)

    assert len(passes) == 3
    assert all(len(p) == 2 and all(len(m) == 2 for m in p) for p in passes)  # 2 pairs per pass
    assert state.event.is_complete
    pairs = {(r.archer_a, r.archer_b) for r in state.event.all_pairwise_results()}
    assert pairs == {(a, b) for a in range(4) for b in range(a + 1, 4)}


def test_odd_n_archers_byes_shot_has_one_winnerless_bye_match_per_pass():
    """Byes shot: total_arrows // n_pass passes, each with exactly one solo, winnerless result."""
    client, state = make_client_and_state()
    archers = [(f"A{i}", "Recurve", 20 + 5 * i) for i in range(5)]
    start_event(client, archers, total_arrows=60, shoot_byes=True)
    passes = play_whole_event(client)

    assert len(passes) == 60 // 12
    event = state.event
    assert event.is_complete
    for pass_index in range(len(passes)):
        solo = [
            r
            for r in event.results
            if r.rotation_index == pass_index and r.opponent_index is None
        ]
        assert len(solo) == 1
        assert solo[0].won is None
    assert set(passes_shot(event).values()) == {5}  # everyone shoots every pass


def test_odd_n_archers_byes_not_shot_sits_archers_out_and_adds_passes():
    """Byes not shot: bye archers enter no scores, and the pass count follows Assumption 15."""
    client, state = make_client_and_state()
    archers = [(f"A{i}", "Recurve", 20 + 5 * i) for i in range(5)]
    start_event(client, archers, total_arrows=60, shoot_byes=False)  # needs 5 passes each
    event = state.event
    assert len(event.schedule) == 7  # 6 round-robin passes + 1 catch-up pass

    for pass_index in range(len(event.schedule)):
        overview = client.get("/event/rotation").data.decode()
        assert "Sitting out this pass:" in overview
        scored = score_current_pass(client)
        shooters = {a for match in scored for a in match}
        sitting = set(event.schedule[pass_index].sitting_out)
        assert sitting and shooters.isdisjoint(sitting)  # sitting archers got no score box
        assert shooters | sitting == set(range(5))
        assert all(len(match) == 2 for match in scored)  # nobody shoots alone
        if pass_index < len(event.schedule) - 1:
            client.post("/event/advance")

    assert event.is_complete
    counts = sorted(passes_shot(event).values())
    assert counts == [5, 5, 5, 5, 6]  # everyone at least 5, one archer one extra


def test_odd_n_archers_byes_not_shot_needs_no_catch_up_when_passes_divide_evenly():
    """5 archers needing 4 passes: one round-robin, one bye each, everyone shoots exactly 4."""
    client, state = make_client_and_state()
    archers = [(f"A{i}", "Recurve", 20 + 5 * i) for i in range(5)]
    start_event(client, archers, total_arrows=48, shoot_byes=False)
    play_whole_event(client)
    assert len(state.event.schedule) == 5
    assert set(passes_shot(state.event).values()) == {4}


def test_indoor_event_with_all_four_bowstyles_uses_the_right_targets():
    """Indoor: Compound uses the compound scoring target; Recurve/Barebow/Longbow the plain one."""
    client, state = make_client_and_state()
    archers = [
        ("Rec", "Recurve", 20),
        ("Comp", "Compound", 20),
        ("Bare", "Barebow", 20),
        ("Long", "Longbow", 20),
    ]
    start_event(client, archers, total_arrows=36)
    play_whole_event(client)

    event = state.event
    assert event.is_complete
    systems = [event.target_for(i).scoring_system for i in range(4)]
    assert systems == ["10_zone", "10_zone_compound", "10_zone", "10_zone"]
    # Same handicap and score, so only the target can explain a different percentile.
    percentiles = {r.archer_index: r.percentile for r in event.results if r.rotation_index == 0}
    assert set(percentiles) == {0, 1, 2, 3}  # a 4-archer pass has everyone shooting
    assert percentiles[0] == percentiles[2] == percentiles[3]  # plain scoring agrees
    assert percentiles[1] != percentiles[0]  # compound scoring differs


def test_outdoor_event_gives_every_archer_the_same_target():
    """Outdoor: whatever the bowstyle, every archer is scored against one fixed target."""
    client, state = make_client_and_state()
    archers = [
        ("Rec", "Recurve", 20),
        ("Comp", "Compound", 20),
        ("Bare", "Barebow", 30),
        ("Long", "Longbow", 40),
    ]
    start_event(client, archers, total_arrows=36, distance="70m", face_cm=122)
    play_whole_event(client)

    event = state.event
    assert event.is_complete
    targets = [event.target_for(i) for i in range(4)]
    assert all(t.scoring_system == "10_zone" and not t.indoor for t in targets)
    assert len({(t.diameter, t.distance) for t in targets}) == 1


def test_advance_is_refused_until_every_match_is_scored_at_every_pass():
    """At each pass of a full event, advance is refused until the whole pass is scored."""
    client, state = make_client_and_state()
    archers = [(f"A{i}", "Recurve", 20 + 5 * i) for i in range(4)]
    start_event(client, archers, total_arrows=36)

    for pass_number in range(1, 4):
        assert pass_position(client) == (pass_number, 3)
        refused = client.post("/event/advance")
        assert b"Every match in the current pass must have scores" in refused.data
        assert pass_position(client) == (pass_number, 3)

        event = state.event
        first, second = event.matches(event.current_rotation_index)
        save_match(client, 0, {p: 60 for p in first})
        half_refused = client.post("/event/advance")  # one of two matches still unscored
        assert b"Every match in the current pass must have scores" in half_refused.data

        save_match(client, 1, {p: 60 for p in second})
        if pass_number < 3:
            client.post("/event/advance")
            assert pass_position(client) == (pass_number + 1, 3)

    final_refused = client.post("/event/advance")  # nothing after the last pass
    assert b"final pass" in final_refused.data
    assert state.event.is_complete


# --- Feedback 4: setup stages, shared target, summary table, graph view, reset -----

MIXED_BOWS = [
    ("Rec", "Recurve", 20),
    ("Comp", "Compound", 20),
    ("Bare", "Barebow", 30),
    ("Long", "Longbow", 40),
]


def start_with_setup(client, archers, distance, face_cm, total_arrows=36):
    """Stage 1 (simple setup with the given distance/face), Stage 2, then confirm Stage 3."""
    client.post(
        "/event/stage1",
        data=stage1_form(len(archers), total_arrows, 12, distance=distance, face_cm=face_cm),
    )
    client.post("/event/stage2", data=stage2_form(archers))
    client.post("/event/stage3")


def test_outdoor_distance_event_gives_everyone_the_chosen_face_and_no_reduced_ten():
    """50 m / 80 cm: every archer shoots that target, outdoors, and Compound scores plain 10_zone."""
    client, state = make_client_and_state()
    start_with_setup(client, MIXED_BOWS, distance="50m", face_cm=80)
    play_whole_event(client)

    event = state.event
    assert event.is_complete
    for i in range(4):
        target = event.target_for(i)
        assert target.distance == 50 and target.diameter == 0.8
        assert target.indoor is False
        assert target.scoring_system == "10_zone"
    # Same handicap, same score: Recurve and outdoor Compound share a distribution.
    assert event.distribution_for(0) == event.distribution_for(1)


def test_indoor_distance_event_gives_compound_the_reduced_ten_only():
    """18 m / 40 cm: Compound scores 10_zone_compound, the others 10_zone."""
    client, state = make_client_and_state()
    start_with_setup(client, MIXED_BOWS, distance="18m", face_cm=40)
    play_whole_event(client)

    event = state.event
    assert [event.target_for(i).scoring_system for i in range(4)] == [
        "10_zone", "10_zone_compound", "10_zone", "10_zone",
    ]
    assert all(event.target_for(i).indoor for i in range(4))
    assert event.distribution_for(0) != event.distribution_for(1)


def test_imperial_distance_is_converted_and_classified_by_its_length_in_metres():
    """30 yd (27.4 m) is outdoor while 25 yd (22.9 m) is indoor."""
    for distance, indoor in (("30yd", False), ("25yd", True)):
        client, state = make_client_and_state()
        start_with_setup(client, MIXED_BOWS, distance=distance, face_cm=60)
        assert state.event.target_for(0).indoor is indoor
        assert state.event.target_for(0).distance == round(int(distance[:2]) * 0.9144, 6)


def test_setup_flow_rejects_a_bad_handicap_then_redraws_then_confirms_the_shown_pairings():
    """Stage 2 refuses 150.1 (storing nothing); Stage 3 redraw changes pairings; confirm keeps them."""
    state = SessionState(rng=random.Random(11))
    client = create_app(state=state).test_client()
    client.post("/event/stage1", data=stage1_form(4, 36, 12))

    names = ["Ann", "Ben", "Cat", "Dan"]
    bad = stage2_form([(n, "Recurve", 20 + i) for i, n in enumerate(names)])
    bad["handicap_2"] = "150.1"
    refused = client.post("/event/stage2", data=bad)
    assert b"between 0 and 150" in refused.data
    assert state.pending_archers is None and state.assignment is None

    good = stage2_form([(n, "Recurve", 20 + i) for i, n in enumerate(names)])
    assert client.post("/event/stage2", data=good).status_code == 302

    def shown():
        page = client.get("/event/stage3").data.decode()
        return [re.findall(r"[A-Z][a-z]+ vs [A-Z][a-z]+", row[1]) for row in overview_table(page)[1]]

    first = shown()
    client.post("/event/stage3/redraw")
    second = shown()
    assert second != first

    client.post("/event/stage3")
    _, rows = overview_table(client.get("/event/rotation").data.decode())
    assert [row[0] for row in rows] == second[0]
    assert [a.name for a in state.event.archers] == [
        state.pending_archers[i].name for i in state.assignment
    ]


def test_overview_table_agrees_with_the_event_for_every_match_of_a_full_event():
    """After each pass is scored, Score / Percentiles / Winner match the Event's own results."""
    client, state = make_client_and_state()
    archers = [(f"A{i}", "Recurve", 20 + 5 * i) for i in range(4)]
    start_with_setup(client, archers, distance="20yd", face_cm=60)
    event = state.event
    scores = {0: 95, 1: 88, 2: 101, 3: 74}

    for pass_number in range(1, 4):
        score_current_pass(client, lambda archer: scores[archer] + pass_number)
        _, rows = overview_table(client.get("/event/rotation").data.decode())
        for row, (a, b) in zip(rows, event.matches(event.current_rotation_index), strict=True):
            ra, rb = event.match_results(event.current_rotation_index, (a, b))
            winner = ra if ra.won else rb
            assert row[0] == f"{event.archers[a].name} vs {event.archers[b].name}"
            assert row[1] == f"{ra.score} - {rb.score}"
            assert row[2] == " - ".join(outputs.percentile_pair_text(ra.percentile, rb.percentile))
            assert row[3] == event.archers[winner.archer_index].name
        if pass_number < 3:
            client.post("/event/advance")


def test_graph_view_toggle_lives_on_match_pages_and_switches_the_chart_without_losing_scores():
    """Graph view on/off changes only the chart and explanation; scores stay."""
    client, state = make_client_and_state()
    start_with_setup(client, MIXED_BOWS, distance="20yd", face_cm=60)
    save_match(client, 0, {0: 100, 3: 80})
    toggle = b'action="/graph-view"'

    assert toggle not in client.get("/event/rotation").data
    assert toggle not in client.get("/event/results").data
    match_page = client.get("/event/match/0").data
    assert toggle in match_page and b"Graph view: off" in match_page
    assert b'id="match-chart"' not in match_page

    client.post("/graph-view", data={"next": "/event/match/0"})
    on_page = client.get("/event/match/0").data.decode()
    assert "Graph view: on" in on_page
    assert 'id="match-chart"' in on_page and "How the winner is decided" in on_page

    client.post("/graph-view", data={"next": "/event/match/0"})
    assert b'id="match-chart"' not in client.get("/event/match/0").data
    _, rows = overview_table(client.get("/event/rotation").data.decode())
    assert rows[0][1] == "100 - 80"


def test_reset_asks_for_confirmation_and_only_the_post_clears_everything():
    """GET /reset loses nothing; POST /reset clears; a fresh session then sees no event."""
    client, state = make_client_and_state()
    start_with_setup(client, MIXED_BOWS, distance="20yd", face_cm=60)
    save_match(client, 0, {0: 100, 3: 80})

    asked = client.get("/reset")
    assert b"Reset everything" in asked.data
    assert state.event is not None and state.event.results

    client.post("/reset")
    assert state.event is None and state.schedule is None and state.pending_archers is None
    after = client.get("/event/results", follow_redirects=True)
    assert b"Event setup - Stage 1" in after.data  # no event any more: sent back to setup
    assert client.get("/event/stage3").headers["Location"].endswith("/event/stage1")


# --- Feedback 5: advanced setup, tie-break, outputs, exports, chart range, calculator ---

import csv  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402

import pypdf  # noqa: E402
from archeryutils import handicaps as _hc  # noqa: E402
from archeryutils import load_rounds  # noqa: E402

from h2h import outputs  # noqa: E402

ADVANCED_FOUR = [
    # name, bowstyle, handicap, face type, face size, distance
    ("Ann", "Recurve", 20, "10_zone", 40, "18m"),
    ("Ben", "Compound", 25, "10_zone_compound", 40, "18m"),
    ("Cat", "Barebow", 35, "5_zone", 122, "50yd"),
    ("Dan", "Longbow", 45, "Worcester", 40, "20yd"),
]


def start_advanced_event(client, rows=ADVANCED_FOUR, total_arrows=36):
    """Stage 1 (advanced) -> Stage 2 (per-archer targets) -> confirm Stage 3, over HTTP."""
    form = stage1_form(len(rows), total_arrows)
    form["setup_mode"] = "advanced"
    client.post("/event/stage1", data=form)
    data = {}
    for i, (name, bowstyle, handicap, face_type, face_cm, distance) in enumerate(rows):
        data.update(
            {
                f"name_{i}": name,
                f"bowstyle_{i}": bowstyle,
                f"handicap_{i}": str(handicap),
                f"face_type_{i}": face_type,
                f"face_cm_{i}": str(face_cm),
                f"distance_{i}": distance,
            }
        )
    assert client.post("/event/stage2", data=data).status_code == 302
    client.post("/event/stage3")


def table_rows(html, headings):
    """The body rows (cell texts) of the first page table with exactly these headings."""

    def text(fragment):
        return " ".join(re.sub(r"<[^>]+>", " ", fragment).split())

    for block in re.findall(r"<table>(.*?)</table>", html, re.S):
        if [text(h) for h in re.findall(r"<th>(.*?)</th>", block, re.S)] == headings:
            return [
                [text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
                for row in re.findall(r"<tr[^>]*>(.*?)</tr>", block, re.S)
                if "<td" in row
            ]
    raise AssertionError(f"no table with headings {headings}")


def csv_rows(text):
    """Parse CSV text the way a spreadsheet would."""
    return list(csv.reader(io.StringIO(text, newline="")))


LEADERBOARD_HEADINGS = ["Rank", "Archer", "Points", "Passes decided"]


def wins_so_far(event, passes):
    """{archer_index: passes won among the first `passes` rotations}, from the Event's own results."""
    wins = {i: 0 for i in range(len(event.archers))}
    for r in event.results:
        if r.rotation_index < passes and r.won:
            wins[r.archer_index] += 1
    return wins


def test_advanced_event_leaderboard_follows_the_winners_after_every_completed_pass():
    """4 archers on four different targets: each score respects its own maximum, and after every
    pass the Results page's points equal the passes each archer has won so far."""
    client, state = make_client_and_state()
    start_advanced_event(client)
    event = state.event
    assert [event.max_score_for(i) for i in range(4)] == [120, 120, 108, 60]

    for pass_number in range(1, 4):
        score_current_pass(
            client, lambda i, n=pass_number: int(event.max_score_for(i) * 0.55) + 2 * n + i
        )
        page = client.get("/event/results").data.decode()
        rows = table_rows(page, LEADERBOARD_HEADINGS)
        wins = wins_so_far(event, pass_number)
        assert {row[1]: int(row[2]) for row in rows} == {
            event.archers[i].name: wins[i] for i in range(4)
        }
        assert [row[3] for row in rows] == [str(pass_number)] * 4
        if pass_number < 3:
            client.post("/event/advance")
    assert event.is_complete


def test_after_the_last_pass_every_output_and_export_agrees_with_the_event():
    """Leaderboard page, archer results page, both CSVs and the PDF all say the same thing."""
    client, state = make_client_and_state()
    start_advanced_event(client)
    event = state.event
    for pass_number in range(1, 4):
        score_current_pass(
            client, lambda i, n=pass_number: int(event.max_score_for(i) * 0.55) + 2 * n + i
        )
        if pass_number < 3:
            client.post("/event/advance")

    board = outputs.leaderboard(event)
    sections = outputs.archer_results(event)
    assert sum(r.points for r in board) == 6  # 2 decided matches in each of 3 passes

    page = client.get("/event/results").data.decode()
    assert table_rows(page, LEADERBOARD_HEADINGS) == [
        [str(r.rank), r.name, str(r.points), str(r.passes_decided)] for r in board
    ]
    assert csv_rows(client.get("/event/export/leaderboard.csv").data.decode())[1:] == [
        [str(r.rank), r.name, str(r.points), str(r.passes_decided)] for r in board
    ]

    archer_page = client.get("/event/archers").data.decode()
    results_columns = ["Pass", "Opponent", "Score", "Percentile", "Handicap"]
    csv_all = csv_rows(client.get("/event/export/archer-results.csv").data.decode())[1:]
    pdf = pypdf.PdfReader(io.BytesIO(client.get("/event/export/results.pdf").data))
    pdf_text = "\n".join(p.extract_text() for p in pdf.pages)
    for section in sections:
        assert f"{section.name} - total score {section.total_score} - handicap {section.handicap:g}" in " ".join(
            re.sub(r"<[^>]+>", " ", archer_page).split()
        )
        assert f"{section.name} - total score {section.total_score}" in pdf_text
        mine = [row for row in csv_all if row[0] == section.name]
        assert [(r[2], r[3], r[4]) for r in mine] == [
            (str(row.pass_number), row.opponent, str(row.score)) for row in section.rows
        ]
        assert [r[5] for r in mine] == [f"{row.percentile * 100:.1f}" for row in section.rows]
    # One results table per archer on the page, each with its 3 passes plus the Average row.
    assert archer_page.count("<table>") == 4
    assert len(table_rows(archer_page, results_columns)) == 3 + 1


def test_a_tie_is_blocked_until_a_box_is_ticked_then_the_ticked_archer_is_credited():
    """Same handicap and score: the match will not save without the tick; the leaderboard then counts it."""
    client, state = make_client_and_state()
    form = stage1_form(2, 24)
    client.post("/event/stage1", data=form)
    client.post("/event/stage2", data=stage2_form([("Ann", "Recurve", 30), ("Ben", "Recurve", 30)]))
    client.post("/event/stage3")

    blocked = save_match(client, 0, {0: 90, 1: 90})
    assert blocked.status_code == 200 and b"Percentile and score are tied" in blocked.data
    assert state.event.results == []
    assert client.post("/event/advance").status_code == 200  # still refused: the pass is not scored

    assert save_match(client, 0, {0: 90, 1: 90}, closest=1).status_code == 302
    client.post("/event/advance")
    assert save_match(client, 0, {0: 100, 1: 95}).status_code == 302

    event = state.event
    rows = table_rows(client.get("/event/results").data.decode(), LEADERBOARD_HEADINGS)
    points = {row[1]: int(row[2]) for row in rows}
    assert points == {"Ann": 1, "Ben": 1}  # Ben on the tie-break, Ann on the percentile
    assert sum(points.values()) == len([r for r in event.results if r.won]) == 2
    assert {r.decided_by for r in event.results} == {"closest", "percentile"}


def test_a_half_scored_pass_is_left_out_of_the_outputs_and_the_exports_match():
    """Pass 2 with one match saved changes neither the leaderboard nor the CSVs."""
    client, state = make_client_and_state()
    start_event(client, [(f"A{i}", "Recurve", 20 + 10 * i) for i in range(4)], total_arrows=36)
    score_current_pass(client, lambda i: 80 + i)
    client.post("/event/advance")
    first, _ = state.event.matches(1)
    save_match(client, 0, {p: 85 + p for p in first})

    rows = table_rows(client.get("/event/results").data.decode(), LEADERBOARD_HEADINGS)
    assert [row[3] for row in rows] == ["1", "1", "1", "1"]  # pass 1 only
    exported = csv_rows(client.get("/event/export/leaderboard.csv").data.decode())[1:]
    assert [row[1:] for row in exported] == [row[1:] for row in rows]
    assert len(csv_rows(client.get("/event/export/archer-results.csv").data.decode())) == 1 + 4


def embedded_payload(html):
    """The JSON embedded in a page as window.MATCH_CHART_DATA."""
    marker = "window.MATCH_CHART_DATA = "
    start = html.index(marker) + len(marker)
    return json.loads(html[start : html.index(";\n", start)])


def test_chart_shows_earlier_scores_of_a_pair_that_has_not_met_and_covers_extreme_scores():
    """Pass 2's pair has not met, but both archers' pass-1 scores are listed and inside the x-range."""
    client, state = make_client_and_state()
    start_event(client, [(f"A{i}", "Recurve", 20 + 10 * i) for i in range(4)], total_arrows=36)
    client.post("/graph-view", data={"next": "/event/rotation"})
    event = state.event
    first, second = event.matches(0)
    save_match(client, 0, {first[0]: 5, first[1]: 118})  # far outside the curves' usual range
    save_match(client, 1, {p: 90 + p for p in second})
    client.post("/event/advance")

    a, b = event.matches(1)[0]
    page = client.get("/event/match/0").data.decode()
    payload = embedded_payload(page)
    met_before = {frozenset(m) for m in event.matches(0)}
    assert frozenset((a, b)) not in met_before  # a genuinely new pairing
    shown = {p["score"] for side in ("archer_a", "archer_b") for p in payload[side]["passes"]}
    expected = {r.score for r in event.results if r.archer_index in (a, b)}
    assert shown == expected and len(expected) == 2
    assert payload["current_pass"] == 1
    assert all(payload["x_min"] <= score <= payload["x_max"] for score in shown)
    assert payload["archer_a"]["legend"].endswith("(handicap %g)" % event.archers[a].handicap)


def test_calculator_flow_over_http_for_an_indoor_compound_and_an_outdoor_round():
    """Indoor compound Portsmouth and outdoor WA 1440 (90m) give archeryutils's own handicaps."""
    scheme = _hc.handicap_scheme("AGB")
    client = make_client()

    indoor = client.post(
        "/event/handicap-calculator",
        data={"kind": "indoor", "round_indoor": "portsmouth", "compound": "yes", "score": "540"},
    ).data.decode()
    expected = round(scheme.handicap_from_score(540, load_rounds.AGB_indoor.portsmouth_compound), 1)
    assert f"Handicap: {expected}" in indoor

    outdoor = client.post(
        "/event/handicap-calculator",
        data={"kind": "outdoor", "round_outdoor": "wa1440_90", "score": "1100"},
    ).data.decode()
    expected = round(scheme.handicap_from_score(1100, load_rounds.WA_outdoor.wa1440_90), 1)
    assert f"Handicap: {expected}" in outdoor
