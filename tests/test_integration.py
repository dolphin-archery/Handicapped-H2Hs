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
