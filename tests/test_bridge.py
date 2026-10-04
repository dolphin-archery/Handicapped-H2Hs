"""Tests for h2h.bridge: the event document, its replay and its validation (UISpec.md section 5)."""

import ast
import copy
import json
import math
import random
from pathlib import Path

import pytest

from h2h import bridge, outputs
from h2h.models import Archer, Bowstyle, TargetSetup
from h2h.state import SessionState
from h2h.stats import TieBreakRequired

TIMESTAMP = "2026-10-04T15:30:12.345Z"

SIMPLE_SETUP = {
    "stage": 3,
    "n_archers": 4,
    "total_arrows": 60,
    "n_pass": 12,
    "setup_mode": "simple",
    "shoot_byes": True,
    "target": {"distance_key": "20yd", "face_cm": 60},
    "update_handicaps": False,
    "n_lookback": None,
    "start_weight": None,
}
SIMPLE_ARCHERS = [  # Ann and Dan share a handicap and bowstyle, so equal scores tie
    {"name": "Ann", "bowstyle": "Recurve", "handicap": 35.0, "target": None},
    {"name": "Ben", "bowstyle": "Compound", "handicap": 20.0, "target": None},
    {"name": "Cat", "bowstyle": "Barebow", "handicap": 50.0, "target": None},
    {"name": "Dan", "bowstyle": "Recurve", "handicap": 35.0, "target": None},
]
ADVANCED_ARCHERS = [
    {"name": "Ann", "bowstyle": "Recurve", "handicap": 40.0,
     "target": {"distance_key": "70m", "face_cm": 122, "face_type": "10_zone"}},
    {"name": "Ben", "bowstyle": "Compound", "handicap": 25.0,
     "target": {"distance_key": "50m", "face_cm": 80, "face_type": "10_zone_6_ring"}},
    {"name": "Cat", "bowstyle": "Longbow", "handicap": 70.0,
     "target": {"distance_key": "60yd", "face_cm": 122, "face_type": "5_zone"}},
    {"name": "Dan", "bowstyle": "Barebow", "handicap": 55.0,
     "target": {"distance_key": "20yd", "face_cm": 40, "face_type": "Worcester"}},
]
# Per-pass scores by archer name (12-arrow passes on the simple setup).
SIMPLE_SCORES = {"Ann": [100, 95, 104, 98, 91], "Ben": [110, 112, 108, 113, 115],
                 "Cat": [85, 90, 80, 0, 70], "Dan": [100, 95, 104, 98, 91]}
# Per-pass scores by archer name (6-arrow passes on the advanced targets).
ADVANCED_SCORES = {"Ann": [44, 40, 47, 38, 45], "Ben": [52, 55, 50, 56, 53],
                   "Cat": [30, 33, 28, 35, 31], "Dan": [21, 24, 19, 25, 22]}


def _legacy(setup, archers, seed=4):
    """Run Stages 1-3 through the Flask-era `SessionState` with a seeded draw.

    Parameters
    ----------
    setup : dict
        A document `setup` holding the Stage 1 (and updating) inputs.
    archers : list[dict]
        Document `archers` entries, the Stage 2 inputs in entry order.
    seed : int, default=4
        Seed of the Stage 3 draw (4 moves every archer, for 4 and for 5 archers).

    Returns
    -------
    h2h.state.SessionState
        The session, with its event started.
    """
    state = SessionState(rng=random.Random(seed))
    target = setup["target"]
    state.start_stage1(
        setup["n_archers"],
        setup["total_arrows"],
        setup["n_pass"],
        TargetSetup.parse(target["distance_key"], target["face_cm"]),
        setup["shoot_byes"],
        setup["setup_mode"],
    )
    state.start_stage2(
        [
            Archer(
                a["name"],
                a["handicap"],
                Bowstyle(a["bowstyle"]),
                None if a["target"] is None else TargetSetup.parse_advanced(**a["target"]),
            )
            for a in archers
        ],
        setup["update_handicaps"],
        setup["n_lookback"],
        setup["start_weight"],
    )
    state.start_event()
    # A draw that keeps the entry order would not show whether the replay applies the assignment.
    assert state.assignment != sorted(state.assignment)
    return state


def _document(setup, archers, assignment):
    """A started (status running) event document with no scores yet.

    Parameters
    ----------
    setup : dict
        The document `setup`.
    archers : list[dict]
        The document `archers`.
    assignment : list[int]
        The Stage 3 draw (schedule position -> index into `archers`).

    Returns
    -------
    dict
        A new document; its parts are deep copies.
    """
    return {
        "schema_version": 1,
        "id": "event-1",
        "name": "Club night",
        "created_at": TIMESTAMP,
        "updated_at": TIMESTAMP,
        "revision": 3,
        "status": "running",
        "setup": copy.deepcopy(setup),
        "archers": copy.deepcopy(archers),
        "assignment": list(assignment),
        "scores": {},
        "current_pass": 0,
    }


def _record(event, doc, match_index, scores):
    """Save one match of the current pass in the legacy event and in the document alike.

    If the scores tie, the lower position is named closest to the middle, as a scorer would
    after the tie-break request.

    Parameters
    ----------
    event : h2h.models.Event
        The legacy event.
    doc : dict
        The document, updated in place.
    match_index : int
        The match's position in the current pass.
    scores : dict[int, int]
        Schedule position -> score.
    """
    closest = None
    try:
        event.record_match(scores)
    except TieBreakRequired:
        closest = min(scores)
        event.record_match(scores, closest=closest)
    doc["scores"].setdefault(str(event.current_rotation_index), {})[str(match_index)] = {
        "scores": {str(p): s for p, s in scores.items()},
        "closest": closest,
    }
    doc["status"] = "complete" if event.is_complete else "running"


def _advance(event, doc):
    """Advance the legacy event and the document to the next pass."""
    event.advance()
    doc["current_pass"] = event.current_rotation_index


def _play(event, doc, by_name, passes=None, order=None):
    """Score whole passes in the legacy event and the document, advancing between them.

    Parameters
    ----------
    event : h2h.models.Event
        The legacy event.
    doc : dict
        The document, updated in place.
    by_name : dict[str, list[int]]
        Each archer's score in every pass, by name.
    passes : int | None, default=None
        How many passes to play; all of them by default. The last one played is not advanced.
    order : callable(int) -> list[int] | None, default=None
        Match indices in the order to save them, given the number of matches; index order by
        default.
    """
    passes = len(event.schedule) if passes is None else passes
    for pass_index in range(passes):
        for m in (order or range)(len(event.matches(pass_index))):
            _score_match(event, doc, by_name, m)
        if pass_index < passes - 1:
            _advance(event, doc)


def _score_match(event, doc, by_name, match_index):
    """Save one match of the current pass with each archer's scripted score for that pass.

    Parameters
    ----------
    event : h2h.models.Event
        The legacy event.
    doc : dict
        The document, updated in place.
    by_name : dict[str, list[int]]
        Each archer's score in every pass, by name.
    match_index : int
        The match's position in the current pass.
    """
    pass_index = event.current_rotation_index
    match = event.matches(pass_index)[match_index]
    _record(event, doc, match_index, {p: by_name[event.archers[p].name][pass_index] for p in match if p is not None})


def _replayed(doc):
    """The event rebuilt from the document after a JSON round trip, as the browser stores it."""
    return bridge.rebuild_event(json.loads(json.dumps(doc, allow_nan=False)))


def _assert_same_event(replayed, legacy):
    """Assert two events hold the same archers, pass, results and outputs."""
    assert replayed.results == legacy.results
    assert replayed.current_rotation_index == legacy.current_rotation_index
    assert replayed.archers == legacy.archers
    assert replayed.is_complete == legacy.is_complete
    assert outputs.leaderboard(replayed) == outputs.leaderboard(legacy)
    assert outputs.archer_results(replayed) == outputs.archer_results(legacy)


def _full_simple_event():
    """The legacy session and matching document of a fully scored simple event (with a tie)."""
    state = _legacy(SIMPLE_SETUP, SIMPLE_ARCHERS)
    doc = _document(SIMPLE_SETUP, SIMPLE_ARCHERS, state.assignment)
    _play(state.event, doc, SIMPLE_SCORES)
    return state, doc


def _running_simple_document():
    """A document part-way through a simple event: passes 1-3 done (so every pair has met,
    and Ann and Dan have tied), pass 4 half scored."""
    state = _legacy(SIMPLE_SETUP, SIMPLE_ARCHERS)
    doc = _document(SIMPLE_SETUP, SIMPLE_ARCHERS, state.assignment)
    _play(state.event, doc, SIMPLE_SCORES, passes=3)
    _advance(state.event, doc)
    _score_match(state.event, doc, SIMPLE_SCORES, 0)
    return doc


# --- The module itself -------------------------------------------------------------------------


def test_bridge_imports_neither_flask_nor_the_session_state():
    """bridge.py is importable without Flask and does not use the Flask-era SessionState."""
    tree = ast.parse(Path(bridge.__file__).read_text(encoding="utf-8"))
    imported = [
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
    ] + [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(name.split(".")[0] == "flask" for name in imported)
    assert "state" not in imported and "h2h.state" not in imported


# --- Replay equals the legacy path (UISpec.md 5.3) ---------------------------------------------


def test_replay_of_a_full_simple_event_matches_the_legacy_path():
    """A whole simple event, including a tie decided by the closest archer, replays identically."""
    state, doc = _full_simple_event()
    assert any(r.decided_by == "closest" for r in state.event.results)  # the tie-break was used
    assert doc["status"] == "complete"
    _assert_same_event(_replayed(doc), state.event)


def test_replay_of_a_part_scored_pass_matches_the_legacy_path():
    """An event stopped part-way through a pass replays to the same pass and results."""
    state = _legacy(SIMPLE_SETUP, SIMPLE_ARCHERS)
    doc = _document(SIMPLE_SETUP, SIMPLE_ARCHERS, state.assignment)
    _play(state.event, doc, SIMPLE_SCORES, passes=2)
    _advance(state.event, doc)
    _score_match(state.event, doc, SIMPLE_SCORES, 1)
    assert state.event.current_rotation_index == 2
    assert doc["scores"]["2"].keys() == {"1"}
    _assert_same_event(_replayed(doc), state.event)


def test_replay_after_correcting_a_saved_score_matches_the_legacy_path():
    """Re-saving a match replaces its scores in both paths, and the replay agrees."""
    state = _legacy(SIMPLE_SETUP, SIMPLE_ARCHERS)
    event = state.event
    doc = _document(SIMPLE_SETUP, SIMPLE_ARCHERS, state.assignment)
    _play(event, doc, SIMPLE_SCORES, passes=2)
    first, second = event.matches(1)
    _record(event, doc, 0, dict.fromkeys(first, 77))  # a typo, then the correction
    _record(event, doc, 0, {first[0]: 105, first[1]: 99})
    _record(event, doc, 1, {second[0]: 120, second[1]: 0})
    assert [r.score for r in event.match_results(1, first)] == [105, 99]
    _assert_same_event(_replayed(doc), event)


def test_saving_order_within_a_pass_changes_nothing_that_is_shown():
    """Matches saved out of order replay in match order: the same results, in another order.

    The document keys scores by match, not by the order they were saved in (JavaScript orders
    integer-like keys numerically), so only the order of `Event.results` within a pass can
    differ; no output depends on it.
    """
    state = _legacy(SIMPLE_SETUP, SIMPLE_ARCHERS)
    doc = _document(SIMPLE_SETUP, SIMPLE_ARCHERS, state.assignment)
    _play(state.event, doc, SIMPLE_SCORES, order=lambda n: list(reversed(range(n))))
    replayed = _replayed(doc)
    key = lambda r: (r.rotation_index, r.archer_index)  # noqa: E731
    assert replayed.results != state.event.results
    assert sorted(replayed.results, key=key) == sorted(state.event.results, key=key)
    assert outputs.leaderboard(replayed) == outputs.leaderboard(state.event)
    assert outputs.archer_results(replayed) == outputs.archer_results(state.event)
    assert replayed.all_pairwise_results() == state.event.all_pairwise_results()


@pytest.mark.parametrize("shoot_byes", [False, True], ids=["byes-sat-out", "byes-shot"])
def test_replay_with_an_odd_number_of_archers_matches_the_legacy_path(shoot_byes):
    """Five archers, with byes sat out (the sit-out schedule) or shot alone, replay identically."""
    setup = {**SIMPLE_SETUP, "n_archers": 5, "total_arrows": 36, "shoot_byes": shoot_byes}
    archers = [*SIMPLE_ARCHERS, {"name": "Eve", "bowstyle": "Longbow", "handicap": 80.0, "target": None}]
    by_name = {**SIMPLE_SCORES, "Eve": [60, 72, 55, 64, 70, 58]}
    by_name = {name: (scores * 2)[:6] for name, scores in by_name.items()}
    state = _legacy(setup, archers)
    schedule = state.event.schedule
    if shoot_byes:
        assert all(r.bye is not None for r in schedule)
    else:
        assert all(r.bye is None for r in schedule) and any(r.sitting_out for r in schedule)
    doc = _document(setup, archers, state.assignment)
    _play(state.event, doc, by_name)
    assert doc["status"] == "complete"
    _assert_same_event(_replayed(doc), state.event)


@pytest.mark.parametrize("updating", [True, False], ids=["updating-on", "updating-off"])
def test_replay_of_an_advanced_event_matches_the_legacy_path(updating):
    """Advanced setup with per-archer targets replays identically with handicap updating on and off."""
    setup = {
        **SIMPLE_SETUP,
        "total_arrows": 30,
        "n_pass": 6,
        "setup_mode": "advanced",
        "update_handicaps": updating,
        "n_lookback": 4 if updating else None,
        "start_weight": 5 if updating else None,
    }
    state = _legacy(setup, ADVANCED_ARCHERS)
    assert state.event.update_handicaps is updating
    doc = _document(setup, ADVANCED_ARCHERS, state.assignment)
    _play(state.event, doc, ADVANCED_SCORES)
    replayed = _replayed(doc)
    _assert_same_event(replayed, state.event)
    handicaps = {
        (a, r): replayed.handicap_for(a, r) for a in range(4) for r in range(len(replayed.schedule))
    }
    assert handicaps == {(a, r): state.event.handicap_for(a, r) for a, r in handicaps}
    assert (len(set(handicaps.values())) > 4) is updating  # updating moves the handicaps


def test_rebuild_event_refuses_a_document_without_the_stage_3_draw():
    """There is no event to build before Stage 2 has drawn the assignment."""
    doc = _document(SIMPLE_SETUP, [], [])
    doc["assignment"] = None
    with pytest.raises(ValueError, match="Stage 2 must be completed"):
        bridge.rebuild_event(doc)


# --- validate_document -------------------------------------------------------------------------


def _fresh_document():
    """A schema-version-1 document as a new event starts: Stage 1 not yet submitted."""
    doc = _document({**SIMPLE_SETUP, "stage": 0}, [], [])
    doc.update(status="setup", assignment=None, revision=0)
    return doc


def _stage2_document():
    """A document with Stage 2 done and the pairings drawn, not yet confirmed."""
    doc = _document({**SIMPLE_SETUP, "stage": 2}, SIMPLE_ARCHERS, [2, 0, 3, 1])
    doc["status"] = "setup"
    return doc


@pytest.mark.parametrize(
    "make",
    [_fresh_document, _stage2_document, _running_simple_document, lambda: _full_simple_event()[1]],
    ids=["fresh", "stage-2", "running", "complete"],
)
def test_validate_document_accepts_valid_documents_unchanged(make):
    """Valid documents at every stage come back as they went in, and the input is not mutated."""
    doc = make()
    before = copy.deepcopy(doc)
    result = bridge.validate_document(doc)
    assert result == {"ok": True, "data": doc}
    assert doc == before
    json.dumps(result, allow_nan=False)


def test_validate_document_cleans_what_it_returns():
    """Unknown keys are dropped, whole-number handicaps become floats, scores become ints."""
    doc = _running_simple_document()
    doc["extra"] = "dropped"
    doc["setup"]["extra"] = "dropped"
    doc["archers"][0]["handicap"] = 35  # JSON from JavaScript loses the ".0"
    match = doc["scores"]["0"]["0"]
    key = next(iter(match["scores"]))
    match["scores"][key] = float(match["scores"][key])
    data = bridge.validate_document(doc)["data"]
    assert "extra" not in data and "extra" not in data["setup"]
    assert type(data["archers"][0]["handicap"]) is float
    assert type(data["scores"]["0"]["0"]["scores"][key]) is int


def _tie_match(doc):
    """The stored match that was decided by the closest archer."""
    return next(m for p in doc["scores"].values() for m in p.values() if m["closest"] is not None)


def _set(path, value):
    """A mutation that sets a nested key (a tuple of keys and indices) to `value`."""

    def mutate(doc):
        target = doc
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return mutate


def _drop(key):
    """A mutation that removes a top-level key."""
    return lambda doc: doc.pop(key)


def _first_match_scores(doc, value):
    """Give the first archer of the first stored match the score `value`."""
    scores = doc["scores"]["0"]["0"]["scores"]
    scores[next(iter(scores))] = value


INVALID_RUNNING = [
    ("schema-2", _set(("schema_version",), 2), "schema version 2 is not supported"),
    ("schema-bool", _set(("schema_version",), True), "schema version True is not supported"),
    ("missing-scores", _drop("scores"), "is missing scores"),
    ("blank-id", _set(("id",), ""), "id must be non-empty text"),
    ("bad-time", _set(("created_at",), "yesterday"), "created_at must be an ISO-8601"),
    ("negative-revision", _set(("revision",), -1), "revision must be a whole number of at least 0"),
    ("bad-status", _set(("status",), "done"), "status must be 'setup', 'running' or 'complete'"),
    ("setup-status-after-start", _set(("status",), "setup"), "status must be 'setup' before Stage 3"),
    ("not-dividing", _set(("setup", "n_pass"), 7), "must evenly divide"),
    ("text-count", _set(("setup", "n_archers"), "4"), "setup.n_archers must be a whole number"),
    ("text-flag", _set(("setup", "shoot_byes"), "yes"), "setup.shoot_byes must be true or false"),
    ("bad-distance", _set(("setup", "target", "distance_key"), "21yd"), "not one of the standard distances"),
    ("simple-updating", _set(("setup", "update_handicaps"), True), "can only be true in advanced setup"),
    ("short-archers", lambda d: d["archers"].pop(), "archers must have 4 entries, got 3"),
    ("high-handicap", _set(("archers", 0, "handicap"), 151), "handicap must be a number between 0 and 150"),
    ("nan-handicap", _set(("archers", 0, "handicap"), math.nan), "handicap must be a number between"),
    ("bool-handicap", _set(("archers", 0, "handicap"), True), "handicap must be a number between"),
    ("bad-bowstyle", _set(("archers", 1, "bowstyle"), "Crossbow"), "bowstyle must be one of"),
    ("blank-name", _set(("archers", 0, "name"), "  "), "archers[0].name must be non-empty text"),
    ("simple-own-target", _set(("archers", 0, "target"), ADVANCED_ARCHERS[0]["target"]), "must be null in simple setup"),
    ("repeat-assignment", _set(("assignment",), [0, 0, 1, 2]), "assignment must list each of 0 to 3 once"),
    ("no-assignment", _set(("assignment",), None), "assignment must list each of 0 to 3 once"),
    ("late-pass", _set(("scores", "4"), {}), "scores has pass 5, after the current pass 4."),
    ("padded-key", lambda d: d["scores"].__setitem__("01", d["scores"].pop("1")), "scores has a key '01' that is not a whole number."),
    ("no-such-match", lambda d: d["scores"]["1"].__setitem__("5", d["scores"]["1"]["0"]), "is not a match of pass 2"),
    ("wrong-archers", lambda d: d["scores"]["0"].__setitem__("0", d["scores"]["0"]["1"]), "must be for archers"),
    ("text-score", lambda d: _first_match_scores(d, "100"), "must be a number"),
    ("score-too-high", lambda d: _first_match_scores(d, 500), "Score must be between 0 and 120 for a 12-arrow pass, got 500."),
    ("half-score", lambda d: _first_match_scores(d, 99.5), "Score must be a whole number, got 99.5."),
    ("tie-without-closest", lambda d: _tie_match(d).__setitem__("closest", None), "Percentile and score are tied"),
    ("closest-outsider", lambda d: _tie_match(d).__setitem__("closest", 9), "closest must be null or one of the two archers"),
    ("unscored-earlier-pass", lambda d: d["scores"]["0"].pop("1"), "Every match in the current pass must have scores"),
    ("complete-too-early", _set(("status",), "complete"), "status must be 'complete' exactly when"),
    ("pass-out-of-range", _set(("current_pass",), 9), "current_pass must be below the number of passes (5)"),
]


@pytest.mark.parametrize(("mutate", "message"), [case[1:] for case in INVALID_RUNNING], ids=[c[0] for c in INVALID_RUNNING])
def test_validate_document_rejects_malformed_documents(mutate, message):
    """Each malformed variant of a valid running document is rejected with a clear message."""
    doc = _running_simple_document()
    assert _tie_match(doc)["closest"] is not None  # the base document has a tie to break
    mutate(doc)
    result = bridge.validate_document(doc)
    assert result["ok"] is False
    assert result["error"]["code"] == "validation"
    assert result["error"]["message"].startswith("Invalid event document: ")
    assert message in result["error"]["message"]


@pytest.mark.parametrize(
    ("make", "mutate", "message"),
    [
        (lambda: "not a document", None, "The document must be an object."),
        (lambda: [], None, "The document must be an object."),
        (_fresh_document, _set(("archers",), SIMPLE_ARCHERS), "archers must be empty and assignment null"),
        (_fresh_document, _set(("scores",), {"0": {}}), "scores must be empty and current_pass 0"),
        (_fresh_document, _set(("setup", "stage"), 4), "setup.stage must be 0, 1, 2 or 3"),
        (lambda: _full_simple_event()[1], _set(("status",), "running"), "status must be 'complete' exactly when"),
        (
            _stage2_document,
            lambda d: d["setup"].update(setup_mode="advanced"),
            "archers[0].target must be an object",
        ),
    ],
    ids=["text", "list", "archers-too-early", "scores-too-early", "stage-4", "complete-not-marked", "advanced-no-target"],
)
def test_validate_document_rejects_other_malformed_documents(make, mutate, message):
    """Malformed documents at other stages, and values that are not documents, are rejected."""
    doc = make()
    if mutate is not None:
        mutate(doc)
    result = bridge.validate_document(doc)
    assert result["ok"] is False
    assert result["error"]["code"] == "validation"
    assert result["error"]["message"].startswith("Invalid event document: ")
    assert message in result["error"]["message"]
