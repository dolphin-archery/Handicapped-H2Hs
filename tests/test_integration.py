"""End-to-end integration checks for the rotation-based event flow.

Exercises the full HTTP flow (Stage 1 -> Stage 2 -> overview / per-match
pages / advance for every pass -> results) against the real Flask app,
covering the scenarios prd.json task 25 calls out: even/odd n_archers (bye
handling), indoor mode with mixed bowstyles, outdoor mode, and that a fresh
app/state sees no prior event.
"""

from h2h.app import create_app
from h2h.models import Bowstyle, RoundMode, resolve_target
from h2h.state import SessionState

from .helpers import pass_position, play_whole_event, save_match, score_current_pass


def make_client():
    """A Flask test client with its own isolated SessionState."""
    return create_app(state=SessionState()).test_client()


def stage1_form(n_archers, total_arrows=60, n_pass=12, round_mode="indoor", indoor_round="portsmouth"):
    return {
        "n_archers": str(n_archers),
        "total_arrows": str(total_arrows),
        "n_pass": str(n_pass),
        "round_mode": round_mode,
        "indoor_round": indoor_round,
    }


def stage2_form(archers):
    form = {}
    for i, (name, bowstyle, handicap) in enumerate(archers):
        form[f"name_{i}"] = name
        form[f"bowstyle_{i}"] = bowstyle
        form[f"handicap_{i}"] = str(handicap)
    return form


def run_full_event(client, archers, n_pass=12, total_arrows=None, round_mode="indoor", indoor_round="portsmouth", score_fn=None):
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
        data=stage1_form(n_archers, total_arrows, n_pass, round_mode, indoor_round),
    )
    client.post("/event/stage2", data=stage2_form(archers))

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
    compound_target = resolve_target(RoundMode.INDOOR_PORTSMOUTH, Bowstyle.COMPOUND)
    recurve_target = resolve_target(RoundMode.INDOOR_PORTSMOUTH, Bowstyle.RECURVE)
    assert compound_target.scoring_system == "10_zone_compound"
    assert recurve_target.scoring_system == "10_zone"

    client = make_client()
    archers = [("Rec", "Recurve", 20), ("Comp", "Compound", 20)]
    client.post("/event/stage1", data=stage1_form(2, total_arrows=12, n_pass=12))
    client.post("/event/stage2", data=stage2_form(archers))
    save_match(client, 0, {0: 100, 1: 100})
    results_resp = client.get("/event/results", follow_redirects=True)
    # Same raw score, different bowstyle/target -> different equivalent handicaps.
    assert results_resp.status_code == 200


def test_outdoor_mode_ignores_bowstyle_for_target():
    """Outdoor mode: every bowstyle resolves to the same target."""
    for bowstyle in Bowstyle:
        target = resolve_target(RoundMode.OUTDOOR, bowstyle)
        assert target.scoring_system == "10_zone"
        assert target.distance == resolve_target(RoundMode.OUTDOOR, Bowstyle.RECURVE).distance


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
    state = SessionState()
    return create_app(state=state).test_client(), state


def start_event(client, archers, total_arrows, n_pass=12, shoot_byes=True, **stage1_kwargs):
    """Run Stage 1 and Stage 2 (without scoring anything)."""
    form = stage1_form(len(archers), total_arrows, n_pass, **stage1_kwargs)
    form["shoot_byes"] = "yes" if shoot_byes else "no"
    client.post("/event/stage1", data=form)
    client.post("/event/stage2", data=stage2_form(archers))


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
    start_event(client, archers, total_arrows=36, round_mode="outdoor")
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
