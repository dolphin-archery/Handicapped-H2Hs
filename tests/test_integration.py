"""End-to-end integration check for the Handicapped H2H scoring tool.

Exercises the full HTTP flow (setup -> matches -> scoring -> result) rather
than calling h2h.models/h2h.stats directly, to confirm the web layer is
correctly wired to the stats/model layers verified in isolation by tasks
2-5. Also checks a directional worked example and that state does not leak
between app instances (the closest meaningful proxy, in an in-memory-only
app, for "restarting clears state" -- see Specification/logbook.md
Assumption 7).
"""

from h2h.app import create_app
from h2h.state import SessionState


def start_form(*archers, n_pass):
    """Build a /start form payload from (name, handicap) tuples."""
    form = {"n_pass": str(n_pass)}
    for i, (name, handicap) in enumerate(archers):
        form[f"name_{i}"] = name
        form[f"handicap_{i}"] = str(handicap)
    return form


def test_full_session_end_to_end():
    """A full session from setup through final result completes without error."""
    client = create_app(state=SessionState()).test_client()

    assert client.get("/").status_code == 200

    resp = client.post(
        "/start",
        data=start_form(("Alice", 15), ("Bob", 45), n_pass=12),
        follow_redirects=True,
    )
    assert resp.status_code == 200

    for pass_scores in [(100, 60), (95, 55), (105, 65), (98, 50), (102, 58)]:
        resp = client.post(
            "/match/0/pass",
            data={"score_a": pass_scores[0], "score_b": pass_scores[1]},
            follow_redirects=True,
        )
        assert resp.status_code == 200

    assert b"Result:" in resp.data


def test_worked_example_favoured_archer_wins_directionally():
    """Worked example: an archer scoring near the maximum every pass, against
    one scoring near the minimum every pass, must win the match -- this holds
    regardless of the handicaps involved, since it only relies on percentiles
    being monotonic in score (higher score -> higher or equal percentile),
    which follows directly from `percentile` being a CDF. This is the
    "directional sanity check" named in prd.json task 10, rather than a full
    hand-derivation of the underlying probabilities (already cross-checked
    against archeryutils in tests/test_stats.py).
    """
    client = create_app(state=SessionState()).test_client()
    client.post(
        "/start",
        data=start_form(("Favoured", 20), ("Underdog", 20), n_pass=12),
    )

    max_pass_score = 120  # 12 arrows * 10 points, Portsmouth's 10_zone face
    for i in range(5):
        resp = client.post(
            "/match/0/pass",
            data={"score_a": max_pass_score, "score_b": 0},
            follow_redirects=True,
        )

    assert b"Result: Favoured wins" in resp.data


def test_new_app_instance_starts_with_no_matches():
    """A fresh app/state (the in-memory analogue of a process restart) must
    not see another instance's matches -- there is no persistence layer for
    state to leak through.
    """
    first_client = create_app(state=SessionState()).test_client()
    first_client.post("/start", data=start_form(("Alice", 15), ("Bob", 45), n_pass=12))
    assert b"Alice" in first_client.get("/matches").data

    second_client = create_app(state=SessionState()).test_client()
    resp = second_client.get("/matches")
    assert b"Alice" not in resp.data
    assert b"No matches yet" in resp.data
