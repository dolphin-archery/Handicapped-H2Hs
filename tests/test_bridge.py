"""Tests for h2h.bridge: the event document, its replay, its validation and the commands
(UISpec.md section 5)."""

import ast
import base64
import copy
import io
import json
import math
import random
from datetime import datetime
from pathlib import Path

import pypdf
import pytest

from h2h import bridge, chart_data, exports, models, outputs, stats
from h2h.draw import draw_assignment, pairings_signature
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


# --- Commands (UISpec.md 5.4) ------------------------------------------------------------------

NOW = "2026-10-04T15:30:12"
SIMPLE_FORM = {"n_archers": 4, "total_arrows": 60, "n_pass": 12, "setup_mode": "simple",
               "distance": "20yd", "face_cm": "60", "shoot_byes": True}
SIMPLE_ROWS = [{"name": a["name"], "bowstyle": a["bowstyle"], "handicap": a["handicap"]} for a in SIMPLE_ARCHERS]
ADVANCED_ROWS = [
    {"name": a["name"], "bowstyle": a["bowstyle"], "handicap": a["handicap"], "distance": a["target"]["distance_key"],
     "face_cm": str(a["target"]["face_cm"]), "face_type": a["target"]["face_type"]}
    for a in ADVANCED_ARCHERS
]
NO_UPDATING = {"update_handicaps": False}


def _data(result):
    """The data of a successful envelope (the test fails with the error otherwise)."""
    assert result["ok"] is True, result
    return result["data"]


def _refused(result, code, message=None):
    """Assert an envelope is an error with `code` (and exactly `message`, when given)."""
    assert result["ok"] is False, result
    assert result["error"]["code"] == code
    if message is not None:
        assert result["error"]["message"] == message


def _at_stage1(form=SIMPLE_FORM):
    """A new document with Stage 1 submitted."""
    return _data(bridge.apply_stage1(_data(bridge.new_document("e1", NOW)), form))["document"]


def _at_stage2(form=SIMPLE_FORM, rows=SIMPLE_ROWS, updating=NO_UPDATING, seed=4):
    """A document with Stages 1 and 2 submitted and the pairings drawn."""
    return _data(bridge.apply_stage2(_at_stage1(form), rows, updating, seed))["document"]


def _started(form=SIMPLE_FORM, rows=SIMPLE_ROWS, updating=NO_UPDATING, seed=4):
    """A started event document (Stage 3 confirmed)."""
    return _data(bridge.start_event(_at_stage2(form, rows, updating, seed)))["document"]


def _match_scores(doc, match_index, by_name):
    """Each archer's scripted score for the current pass in one match, keyed by position text.

    Parameters
    ----------
    doc : dict
        A started event document.
    match_index : int
        The match in the current pass.
    by_name : dict[str, list[int]]
        Each archer's score in every pass, by name.

    Returns
    -------
    dict[str, int]
        The `scores` argument of `record_match`.
    """
    view = _data(bridge.match(doc, match_index))
    return {str(a["position"]): by_name[a["name"]][view["pass_index"]] for a in view["archers"]}


def _save(doc, match_index, by_name):
    """Save a match with the scripted scores (see `_match_scores`); return the new document.

    If the scores tie, the lower position is named closest to the middle and the match saved
    again, as `tests.helpers.save_match_breaking_ties` does for the Flask app.
    """
    scores = _match_scores(doc, match_index, by_name)
    result = bridge.record_match(doc, match_index, scores)
    if not result["ok"]:
        _refused(result, "tiebreak_required")
        result = bridge.record_match(doc, match_index, scores, min(int(p) for p in scores))
    return _data(result)["document"]


def _play_all(doc, by_name):
    """Score every pass of a started event through the commands, breaking ties for the lower position.

    Parameters
    ----------
    doc : dict
        A started event document.
    by_name : dict[str, list[int]]
        Each archer's score in every pass, by name.

    Returns
    -------
    dict
        The document with every pass scored, on the final pass.
    """
    while True:
        for i in range(_data(bridge.overview(doc))["match_count"]):
            doc = _save(doc, i, by_name)
        if _data(bridge.overview(doc))["is_last"]:
            return doc
        doc = _data(bridge.advance(doc))["document"]


def test_options_lists_what_the_forms_offer():
    """options() gives the dropdown lists, ranges and defaults from the core's constants."""
    data = _data(bridge.options())
    assert [g["group"] for g in data["distance_groups"]] == ["Metric", "Imperial"]
    assert {"value": "20yd", "label": "20 yd"} in data["distance_groups"][1]["items"]
    assert data["face_sizes"] == [40, 60, 80, 122]
    assert data["advanced_face_sizes"] == [20, 35, 40, 50, 60, 65, 80, 122]
    assert [t["value"] for t in data["face_types"]] == list(models.FACE_TYPES)
    assert data["bowstyles"] == ["Recurve", "Compound", "Barebow", "Longbow"]
    assert (data["min_handicap"], data["max_handicap"]) == (0, 150)
    assert data["defaults"] == {"n_archers": 4, "total_arrows": 60, "n_pass": 12, "setup_mode": "simple",
                                "shoot_byes": True, "distance_key": "20yd", "face_cm": 60, "face_type": "10_zone",
                                "n_lookback": 4}
    indoor = data["calculator"]["rounds"]["indoor"]
    assert [r["value"] for r in indoor] == list(models.calculator_rounds("indoor"))
    assert data["calculator"]["defaults"] == {"indoor": "portsmouth", "outdoor": "wa720_70"}


def test_new_document_is_a_valid_fresh_document():
    """new_document gives a stage-0 document with the defaults, which validates unchanged."""
    doc = _data(bridge.new_document("e1", NOW))
    assert doc["status"] == "setup" and doc["setup"]["stage"] == 0 and doc["revision"] == 0
    assert doc["created_at"] == doc["updated_at"] == NOW
    assert bridge.validate_document(doc) == {"ok": True, "data": doc}
    _refused(bridge.new_document("", NOW), "validation")
    _refused(bridge.new_document("e1", "yesterday"), "validation")


def test_apply_stage1_stores_the_configuration_and_reports_the_schedule_size():
    """A valid Stage 1 sets stage 1 and the setup; byes sat out add passes to the schedule."""
    data = _data(bridge.apply_stage1(_data(bridge.new_document("e1", NOW)), SIMPLE_FORM))
    assert data["document"]["setup"] == {**SIMPLE_SETUP, "stage": 1}
    assert (data["passes_per_archer"], data["n_passes"]) == (5, 5)
    form = {**SIMPLE_FORM, "n_archers": "5", "shoot_byes": "no"}
    data = _data(bridge.apply_stage1(_data(bridge.new_document("e1", NOW)), form))
    assert data["document"]["setup"]["shoot_byes"] is False
    assert data["n_passes"] > data["passes_per_archer"] == 5


def test_apply_stage1_again_clears_the_later_stages():
    """Re-submitting Stage 1 discards the archers and the draw, as SessionState.start_stage1 does."""
    doc = _data(bridge.apply_stage1(_at_stage2(), SIMPLE_FORM))["document"]
    assert (doc["setup"]["stage"], doc["archers"], doc["assignment"]) == (1, [], None)
    assert bridge.validate_document(doc)["ok"]


def test_apply_stage1_in_advanced_setup_keeps_the_last_simple_target():
    """Advanced setup ignores the shared target fields and keeps the previous choice."""
    doc = _at_stage1({**SIMPLE_FORM, "distance": "18m", "face_cm": "40"})
    doc = _data(bridge.apply_stage1(doc, {**SIMPLE_FORM, "setup_mode": "advanced", "distance": "bad"}))["document"]
    assert doc["setup"]["setup_mode"] == "advanced"
    assert doc["setup"]["target"] == {"distance_key": "18m", "face_cm": 40}


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"n_pass": 7}, "Arrows per pass (7) must evenly divide total arrows (60)."),
        ({"n_pass": 0}, "Arrows per pass (0) must evenly divide total arrows (60)."),
        ({"n_archers": 1}, "Need at least 2 archers, got 1."),
        ({"setup_mode": "expert"}, "Setup mode must be Simple or Advanced, got 'expert'."),
        ({"distance": "20m"}, "'20m' is not one of the standard distances."),
        ({"face_cm": "50"}, "'50' is not one of the standard face sizes."),
        ({"n_archers": "abc"}, "invalid literal for int() with base 10: 'abc'"),
        ({"total_arrows": ""}, "invalid literal for int() with base 10: ''"),
    ],
)
def test_apply_stage1_refuses_invalid_input_with_the_existing_messages(changes, message):
    """Each invalid Stage 1 value is refused with the message the Flask app showed."""
    result = bridge.apply_stage1(_data(bridge.new_document("e1", NOW)), {**SIMPLE_FORM, **changes})
    _refused(result, "validation", message)


def test_stage2_info_gives_the_flask_page_values():
    """Stage 2's target sentence and default start weight, as the Flask route passed them."""
    info = _data(bridge.stage2_info(_at_stage1()))
    assert info == {
        "n_archers": 4,
        "setup_mode": "simple",
        "target": {"distance_label": "20 yd", "face_cm": 60, "indoor": True},
        "default_start_weight": 5,  # 60 arrows // 12 per pass
        "default_n_lookback": models.DEFAULT_N_LOOKBACK,
    }
    outdoor = _data(bridge.stage2_info(_at_stage1({**SIMPLE_FORM, "distance": "50m", "face_cm": "122"})))
    assert outdoor["target"] == {"distance_label": "50 m", "face_cm": 122, "indoor": False}


def test_stage2_info_needs_stage1_and_still_answers_after_the_start():
    """Refused before Stage 1; answered for a started event (the read-only summary)."""
    _refused(bridge.stage2_info(_data(bridge.new_document("e1", NOW))), "state", bridge.STAGE1_FIRST)
    assert bridge.stage2_info(_running_simple_document())["ok"]


def test_apply_stage2_stores_the_archers_and_draws_as_the_session_would():
    """Stage 2 stores the cleaned rows and draws the same assignment SessionState draws for the seed."""
    rows = [{**row, "name": f"  {row['name']} ", "handicap": str(row["handicap"])} for row in SIMPLE_ROWS]
    doc = _data(bridge.apply_stage2(_at_stage1(), rows, NO_UPDATING, 4))["document"]
    assert doc["setup"]["stage"] == 2 and doc["status"] == "setup"
    assert doc["archers"] == SIMPLE_ARCHERS
    assert doc["assignment"] == _legacy(SIMPLE_SETUP, SIMPLE_ARCHERS, seed=4).assignment
    assert bridge.validate_document(doc)["ok"]


def test_apply_stage2_in_advanced_setup_stores_targets_and_updating():
    """Advanced rows keep each archer's target; updating stores its two parameters."""
    form = {**SIMPLE_FORM, "total_arrows": 30, "n_pass": 6, "setup_mode": "advanced"}
    updating = {"update_handicaps": True, "n_lookback": "4", "start_weight": 5}
    doc = _data(bridge.apply_stage2(_at_stage1(form), ADVANCED_ROWS, updating, 4))["document"]
    assert doc["archers"] == ADVANCED_ARCHERS
    setup = doc["setup"]
    assert (setup["update_handicaps"], setup["n_lookback"], setup["start_weight"]) == (True, 4, 5)


def test_apply_stage2_ignores_updating_in_simple_setup():
    """Handicap updating applies only in advanced setup, as in SessionState.start_stage2."""
    result = bridge.apply_stage2(_at_stage1(), SIMPLE_ROWS, {"update_handicaps": True, "n_lookback": "x"}, 4)
    assert _data(result)["document"]["setup"]["update_handicaps"] is False


def _rows_with(index, **changes):
    """SIMPLE_ROWS with one row changed."""
    rows = copy.deepcopy(SIMPLE_ROWS)
    rows[index].update(changes)
    return rows


@pytest.mark.parametrize(
    ("rows", "row", "field", "message"),
    [
        (_rows_with(1, name="  "), 1, "name", "Row 2: name, handicap, and bowstyle are all required."),
        (_rows_with(0, handicap=""), 0, "handicap", "Row 1: name, handicap, and bowstyle are all required."),
        (SIMPLE_ROWS[:3], 3, "name", "Row 4: name, handicap, and bowstyle are all required."),
        (_rows_with(2, bowstyle="Crossbow"), 2, "bowstyle", "Row 3: 'Crossbow' is not a valid bowstyle."),
        (_rows_with(0, handicap="abc"), 0, "handicap", "Row 1: handicap must be a number."),
        (_rows_with(1, handicap="151"), 1, "handicap", "Row 2: handicap must be between 0 and 150, got 151."),
        (_rows_with(1, handicap=-0.5), 1, "handicap", "Row 2: handicap must be between 0 and 150, got -0.5."),
        (_rows_with(3, handicap="nan"), 3, "handicap", "Row 4: handicap must be between 0 and 150, got nan."),
    ],
)
def test_apply_stage2_refuses_a_bad_row_with_its_row_and_field(rows, row, field, message):
    """The first bad row is refused with the existing row-numbered message plus its row and field."""
    result = bridge.apply_stage2(_at_stage1(), rows, NO_UPDATING, 4)
    _refused(result, "validation", message)
    assert (result["error"]["row"], result["error"]["field"]) == (row, field)


@pytest.mark.parametrize(
    ("changes", "field", "message"),
    [
        ({"distance": "19m"}, "distance", "Row 3: '19m' is not one of the standard distances."),
        ({"distance": ""}, "distance", "Row 3: '' is not one of the standard distances."),
        ({"face_cm": "45"}, "face_cm", "Row 3: '45' is not one of the standard face sizes."),
        ({"face_type": "Custom"}, "face_type", "Row 3: 'Custom' is not one of the target face types."),
    ],
)
def test_apply_stage2_in_advanced_setup_needs_a_valid_target_per_row(changes, field, message):
    """Advanced setup refuses a missing or invalid target field, naming the row and field."""
    form = {**SIMPLE_FORM, "setup_mode": "advanced"}
    rows = copy.deepcopy(ADVANCED_ROWS)
    rows[2].update(changes)
    result = bridge.apply_stage2(_at_stage1(form), rows, NO_UPDATING, 4)
    _refused(result, "validation", message)
    assert (result["error"]["row"], result["error"]["field"]) == (2, field)


@pytest.mark.parametrize(
    ("updating", "field", "message"),
    [
        ({"update_handicaps": True, "n_lookback": "0", "start_weight": "5"}, "n_lookback",
         "Lookback must be a whole number of at least 1."),
        ({"update_handicaps": "yes", "n_lookback": "4", "start_weight": "2.5"}, "start_weight",
         "Start weight must be a whole number of at least 1."),
    ],
)
def test_apply_stage2_refuses_bad_updating_parameters(updating, field, message):
    """The updating parameters must be whole numbers of at least 1 (no row: they are event-wide)."""
    form = {**SIMPLE_FORM, "setup_mode": "advanced"}
    result = bridge.apply_stage2(_at_stage1(form), ADVANCED_ROWS, updating, 4)
    _refused(result, "validation", message)
    assert (result["error"]["row"], result["error"]["field"]) == (None, field)


def test_apply_stage2_and_redraw_need_a_whole_number_seed():
    """The draw seed comes from JavaScript as an integer; anything else is refused."""
    _refused(bridge.apply_stage2(_at_stage1(), SIMPLE_ROWS, NO_UPDATING, "4"), "validation")
    _refused(bridge.redraw(_at_stage2(), 1.5), "validation")


def test_redraw_changes_the_pairings_and_nothing_else():
    """A redraw gives different pairings when they exist and leaves every other field alone."""
    doc = _at_stage2()
    schedule = bridge.schedule_for(doc["setup"])
    for seed in range(10):
        new = _data(bridge.redraw(doc, seed))["document"]
        assert pairings_signature(schedule, new["assignment"]) != pairings_signature(schedule, doc["assignment"])
        assert new["assignment"] == draw_assignment(schedule, 4, random.Random(seed), doc["assignment"])
        assert {k: v for k, v in new.items() if k != "assignment"} == {
            k: v for k, v in doc.items() if k != "assignment"
        }
        doc = new


def test_pairings_lists_every_pass_by_name_with_byes_and_sitting_out():
    """Stage 3 shows names per pass: a bye has no opponent, sat-out archers are listed."""
    data = _data(bridge.pairings(_at_stage2()))
    assert [p["pass_number"] for p in data["passes"]] == [1, 2, 3, 4, 5] and data["started"] is False
    assert all(len(p["matches"]) == 2 and p["sitting_out"] == [] for p in data["passes"])
    doc = _at_stage2()
    names = [doc["archers"][i]["name"] for i in doc["assignment"]]
    first = bridge.schedule_for(doc["setup"])[0]
    assert data["passes"][0]["matches"] == [{"a": names[a], "b": names[b]} for a, b in first.pairs]
    rows = [*SIMPLE_ROWS, {"name": "Eve", "bowstyle": "Longbow", "handicap": 80}]
    byes = _data(bridge.pairings(_at_stage2({**SIMPLE_FORM, "n_archers": 5}, rows)))["passes"]
    assert all(p["matches"][-1]["b"] is None and p["sitting_out"] == [] for p in byes)
    sit = _data(bridge.pairings(_at_stage2({**SIMPLE_FORM, "n_archers": 5, "shoot_byes": False}, rows)))["passes"]
    assert all(p["sitting_out"] for p in sit)
    assert all(m["b"] is not None for p in sit for m in p["matches"])


def test_start_event_starts_once():
    """Confirming Stage 3 sets status running and stage 3; it cannot be done twice."""
    doc = _data(bridge.start_event(_at_stage2()))["document"]
    assert (doc["status"], doc["setup"]["stage"]) == ("running", 3)
    assert _data(bridge.pairings(doc))["started"] is True
    _refused(bridge.start_event(doc), "state", bridge.ALREADY_STARTED)


def _fresh():
    """A new document (nothing submitted)."""
    return _data(bridge.new_document("e1", NOW))


OUT_OF_ORDER = [
    ("stage2-first", _fresh, lambda d: bridge.apply_stage2(d, SIMPLE_ROWS, NO_UPDATING, 1),
     "Stage 1 must be completed before Stage 2."),
    ("redraw-early", _at_stage1, lambda d: bridge.redraw(d, 1), "Stage 2 must be completed before pairings can be drawn."),
    ("pairings-early", _at_stage1, bridge.pairings, "Stage 2 must be completed before pairings can be drawn."),
    ("start-at-stage-0", _fresh, bridge.start_event, "Stage 1 must be completed before the event can start."),
    ("start-at-stage-1", _at_stage1, bridge.start_event, "Stage 2 must be completed before pairings can be drawn."),
    ("stage1-after-start", _started, lambda d: bridge.apply_stage1(d, SIMPLE_FORM), bridge.ALREADY_STARTED),
    ("stage2-after-start", _started, lambda d: bridge.apply_stage2(d, SIMPLE_ROWS, NO_UPDATING, 1),
     bridge.ALREADY_STARTED),
    ("redraw-after-start", _started, lambda d: bridge.redraw(d, 1), bridge.ALREADY_STARTED),
    ("overview-early", _at_stage2, bridge.overview, bridge.NOT_STARTED),
    ("match-early", _at_stage2, lambda d: bridge.match(d, 0), bridge.NOT_STARTED),
    ("record-early", _at_stage2, lambda d: bridge.record_match(d, 0, {}), bridge.NOT_STARTED),
    ("advance-early", _at_stage2, bridge.advance, bridge.NOT_STARTED),
    ("results-early", _at_stage2, bridge.results, bridge.NOT_STARTED),
    ("archer-results-early", _at_stage2, bridge.archer_results, bridge.NOT_STARTED),
    ("chart-early", _at_stage2, lambda d: bridge.pair_chart(d, 0, 1), bridge.NOT_STARTED),
    ("export-early", _at_stage2, lambda d: bridge.export(d, "leaderboard_csv", NOW), bridge.NOT_STARTED),
]


@pytest.mark.parametrize(("make", "command", "message"), [c[1:] for c in OUT_OF_ORDER], ids=[c[0] for c in OUT_OF_ORDER])
def test_commands_out_of_order_are_refused_with_a_state_error(make, command, message):
    """Each command used before (or after) its stage gives code 'state' and changes nothing."""
    doc = make()
    before = copy.deepcopy(doc)
    _refused(command(doc), "state", message)
    assert doc == before


def test_overview_shows_the_current_pass_as_the_overview_page_did():
    """Unscored matches show "-"; a saved match shows "A - B" scores, percentiles and the winner."""
    doc = _started()
    data = _data(bridge.overview(doc))
    assert (data["pass_number"], data["n_passes"], data["n_pass"]) == (1, 5, 12)
    assert (data["scored_count"], data["match_count"], data["pass_complete"]) == (0, 2, False)
    assert all((m["score"], m["percentiles"], m["winner"]) == ("-", "-", "-") for m in data["matches"])
    doc = _save(doc, 1, SIMPLE_SCORES)
    event = bridge.rebuild_event(doc)
    pair = event.matches(0)[1]
    rows = outputs.pass_table_rows(event, event.match_results(0, pair))
    shown = _data(bridge.overview(doc))["matches"][1]
    assert shown["scored"] is True and shown["bye"] is False
    assert shown["names"] == [event.archers[p].name for p in pair]
    assert shown["score"] == f"{rows[0].score} - {rows[1].score}"
    assert shown["percentiles"] == f"{rows[0].percentile} - {rows[1].percentile}"
    assert shown["winner"] == next(row.archer for row in rows if row.winner == "Yes")


def test_overview_of_a_bye_has_one_name_and_no_winner():
    """A bye match lists one archer, shows the single score and no winner."""
    rows = [*SIMPLE_ROWS, {"name": "Eve", "bowstyle": "Longbow", "handicap": 80}]
    doc = _started({**SIMPLE_FORM, "n_archers": 5}, rows)
    by_name = {**SIMPLE_SCORES, "Eve": [60, 72, 55, 64, 70]}
    bye_index = _data(bridge.overview(doc))["match_count"] - 1
    doc = _save(doc, bye_index, by_name)
    shown = _data(bridge.overview(doc))["matches"][bye_index]
    assert shown["bye"] is True and len(shown["names"]) == 1
    assert (shown["score"], shown["winner"]) == (str(by_name[shown["names"][0]][0]), "-")


def test_match_view_before_and_after_saving():
    """The match view gives names, maxima and saved scores, the pass table, and the next unscored match."""
    doc = _started()
    view = _data(bridge.match(doc, 0))
    assert [a["max_score"] for a in view["archers"]] == [120, 120]
    assert all(a["score"] is None for a in view["archers"])
    assert (view["scored"], view["rows"], view["next_unscored_match"]) == (False, [], 1)
    doc = _save(doc, 0, SIMPLE_SCORES)
    view = _data(bridge.match(doc, 0))
    event = bridge.rebuild_event(doc)
    expected = outputs.pass_table_rows(event, event.match_results(0, event.matches(0)[0]))
    assert view["rows"] == [vars(row) for row in expected]
    assert [a["score"] for a in view["archers"]] == [SIMPLE_SCORES[a["name"]][0] for a in view["archers"]]
    assert (view["next_unscored_match"], view["show_start_handicap"]) == (1, False)
    assert _data(bridge.match(_save(doc, 1, SIMPLE_SCORES), 1))["next_unscored_match"] is None
    _refused(bridge.match(doc, 2), "validation")
    _refused(bridge.match(doc, "0"), "validation")


def test_record_match_saves_and_replaces_scores_until_the_pass_advances():
    """Saving stores the scores; saving again replaces them; the new document replays to the same results."""
    doc = _started()
    view = _data(bridge.match(doc, 0))
    a, b = (str(x["position"]) for x in view["archers"])
    first = _data(bridge.record_match(doc, 0, {a: "100", b: 90}))
    assert first["document"]["scores"]["0"]["0"] == {"scores": {a: 100, b: 90}, "closest": None}
    second = _data(bridge.record_match(first["document"], 0, {a: 80, b: 90}))
    assert second["document"]["scores"]["0"]["0"]["scores"] == {a: 80, b: 90}
    assert [row["score"] for row in second["match"]["rows"]] == ["80", "90"]
    assert bridge.validate_document(second["document"])["ok"]


def _doc_at_tie():
    """A started simple event on the pass where Ann and Dan (equal handicaps) meet.

    Returns
    -------
    tuple[dict, int, list[int]]
        The document, the index of Ann and Dan's match, and their positions in match order.
    """
    doc = _started()
    while True:
        for i in range(_data(bridge.overview(doc))["match_count"]):
            view = _data(bridge.match(doc, i))
            if {a["name"] for a in view["archers"]} == {"Ann", "Dan"}:
                return doc, i, [a["position"] for a in view["archers"]]
        for i in range(_data(bridge.overview(doc))["match_count"]):
            doc = _save(doc, i, SIMPLE_SCORES)
        doc = _data(bridge.advance(doc))["document"]


def test_a_tie_is_refused_until_the_closest_archer_is_given():
    """Equal percentile and score: tiebreak_required (nothing saved), then the closest archer decides."""
    doc, index, (a, b) = _doc_at_tie()
    tied = {str(a): 100, str(b): 100}
    _refused(bridge.record_match(doc, index, tied), "tiebreak_required", bridge.TIEBREAK_MESSAGE)
    data = _data(bridge.record_match(doc, index, tied, b))
    assert data["document"]["scores"][str(doc["current_pass"])][str(index)]["closest"] == b
    assert (data["match"]["decided_by_closest"], data["match"]["closest"]) == (True, b)
    assert [row["winner"] for row in data["match"]["rows"]] == ["No", "Yes"]
    resaved = _data(bridge.record_match(data["document"], index, {str(a): 101, str(b): 100}, b))
    assert resaved["document"]["scores"][str(doc["current_pass"])][str(index)]["closest"] is None
    assert resaved["match"]["decided_by_closest"] is False


@pytest.mark.parametrize(
    ("score_a", "closest", "message"),
    [
        ("abc", None, "{A}'s score must be a number."),
        ("", None, "{A}'s score must be a number."),
        ("121", None, "Score must be between 0 and 120 for a 12-arrow pass, got 121."),
        ("-1", None, "Score must be between 0 and 120 for a 12-arrow pass, got -1."),
        ("99.5", None, "Score must be a whole number, got 99.5."),
        ("100", 9, "The archer closest to the middle must be one of the two in this match."),
    ],
)
def test_record_match_refuses_invalid_scores_with_the_existing_messages(score_a, closest, message):
    """Bad scores and a closest archer outside the match are refused with the Flask messages."""
    doc = _started()
    first, second = _data(bridge.match(doc, 0))["archers"]
    result = bridge.record_match(doc, 0, {str(first["position"]): score_a, str(second["position"]): "90"}, closest)
    _refused(result, "validation", message.format(A=first["name"]))


def test_advance_refuses_an_unfinished_pass_and_the_final_pass():
    """Advance needs every match scored and a next pass; the refusals carry the core's messages."""
    doc = _started()
    _refused(bridge.advance(doc), "state", "Every match in the current pass must have scores before advancing.")
    doc = _save(_save(doc, 0, SIMPLE_SCORES), 1, SIMPLE_SCORES)
    doc = _data(bridge.advance(doc))["document"]
    assert doc["current_pass"] == 1 and _data(bridge.overview(doc))["scored_count"] == 0
    final = _play_all(_started(), SIMPLE_SCORES)
    _refused(bridge.advance(final), "state", "This is the final pass; there is no next pass to advance to.")


def test_the_event_becomes_complete_on_its_last_save_and_stays_complete():
    """Decision D11: the last match of the final pass sets 'complete'; re-saving it keeps it."""
    doc = _started()
    for _ in range(4):
        doc = _save(_save(doc, 0, SIMPLE_SCORES), 1, SIMPLE_SCORES)
        doc = _data(bridge.advance(doc))["document"]
    doc = _save(doc, 0, SIMPLE_SCORES)
    assert doc["status"] == "running"
    doc = _save(doc, 1, SIMPLE_SCORES)
    assert doc["status"] == "complete"
    shown = _data(bridge.overview(doc))
    assert shown["event_complete"] and shown["is_last"] and shown["pass_complete"]
    view = _data(bridge.match(doc, 1))
    doc = _data(bridge.record_match(doc, 1, {str(a["position"]): 50 for a in view["archers"]}))["document"]
    assert doc["status"] == "complete"
    assert bridge.validate_document(doc)["ok"]


def test_results_show_the_outputs_as_the_results_page_did():
    """Leaderboard, pairwise and per-pass tables carry the core's values as the page's text."""
    doc = _play_all(_started(), SIMPLE_SCORES)
    data = _data(bridge.results(doc))
    event = bridge.rebuild_event(doc)
    expected = [
        {"archer_index": r.archer_index, "rank": str(r.rank), "name": r.name, "points": str(r.points),
         "passes_decided": str(r.passes_decided), "starting_handicap": f"{r.starting_handicap:g}",
         "to_date_handicap": "-" if r.to_date_handicap is None else f"{r.to_date_handicap:.1f}"}
        for r in outputs.leaderboard(event)
    ]
    assert data["leaderboard"] == expected
    assert data["leaderboard"][0]["starting_handicap"] == "20"  # entered as 20.0, shown with %g
    assert (data["completed_passes"], data["n_passes"], data["event_complete"]) == (5, 5, True)
    assert len(data["pairwise"]) == 6
    for pr in data["pairwise"]:
        found = event.pairwise_result(pr["archer_a"], pr["archer_b"])
        assert (pr["wins_a"], pr["wins_b"]) == (str(found.wins_a), str(found.wins_b))
        assert pr["result"] == ("Draw" if pr["draw"] else f"{event.archers[found.outcome].name} wins")
    assert [p["pass_number"] for p in data["passes"]] == [1, 2, 3, 4, 5]
    assert all(len(p["groups"]) == 2 and all(len(g) == 2 for g in p["groups"]) for p in data["passes"])


def test_results_count_only_completed_passes():
    """A half-scored pass appears in the per-pass tables but not in the completed count."""
    doc = _save(_started(), 0, SIMPLE_SCORES)
    data = _data(bridge.results(doc))
    assert data["completed_passes"] == 0
    assert all(row["points"] == "0" and row["to_date_handicap"] == "-" for row in data["leaderboard"])
    assert len(data["passes"]) == 1 and len(data["passes"][0]["groups"]) == 1
    sections = _data(bridge.archer_results(doc))["sections"]
    assert all(s["rows"] == [] and s["average"] is None and s["total_score"] == "0" for s in sections)


def test_archer_results_show_each_section_as_the_page_did():
    """Every row and the Average row carry the template's formats, including "-" for a score of 0."""
    updating = {"update_handicaps": True, "n_lookback": 4, "start_weight": 5}
    form = {**SIMPLE_FORM, "total_arrows": 30, "n_pass": 6, "setup_mode": "advanced"}
    doc = _play_all(_started(form, ADVANCED_ROWS, updating), {**ADVANCED_SCORES, "Dan": [21, 0, 19, 25, 22]})
    data = _data(bridge.archer_results(doc))
    assert data["show_start_handicap"] is True
    event = bridge.rebuild_event(doc)
    for shown, section in zip(data["sections"], outputs.archer_results(event), strict=True):
        assert shown["starting_handicap"] == f"{section.handicap:g}"
        assert shown["total_score"] == str(section.total_score)
        assert [r["percentile"] for r in shown["rows"]] == [f"{r.percentile * 100:.1f}%" for r in section.rows]
        assert [r["start_handicap"] for r in shown["rows"]] == [f"{r.start_handicap:.1f}" for r in section.rows]
        assert shown["average"]["score"] == f"{section.averages.score:.1f}"
    dan = next(s for s in data["sections"] if s["name"] == "Dan")
    assert "-" in [r["handicap"] for r in dan["rows"]]  # the score of 0 has no handicap


def test_pair_chart_is_the_core_payload():
    """pair_chart returns build_pair_chart_data unchanged, for any two different archers."""
    doc = _save(_started(), 0, SIMPLE_SCORES)
    assert _data(bridge.pair_chart(doc, 0, 2)) == chart_data.build_pair_chart_data(bridge.rebuild_event(doc), 0, 2)
    for a, b in ((0, 0), (0, 4), (-1, 2), ("0", 1)):
        _refused(bridge.pair_chart(doc, a, b), "validation")


@pytest.mark.parametrize(
    ("kind", "filename", "build"),
    [
        ("leaderboard_csv", "leaderboard_20261004-153012.csv", exports.leaderboard_csv),
        ("archer_results_csv", "archer-results_20261004-153012.csv", exports.archer_results_csv),
    ],
)
def test_csv_exports_match_the_core_with_the_browser_time(kind, filename, build):
    """The CSVs are the core's text, stamped with the given local time, with the Flask file names."""
    doc = _play_all(_started(), SIMPLE_SCORES)
    data = _data(bridge.export(doc, kind, "2026-10-04T15:30:12+05:30"))  # the offset is not applied
    assert (data["filename"], data["mime_type"], data["encoding"]) == (filename, "text/csv", "utf-8")
    assert data["content"] == build(bridge.rebuild_event(doc), datetime(2026, 10, 4, 15, 30, 12))
    assert "2026-10-04 15:30:12" in data["content"]


def test_pdf_export_is_base64_pdf_bytes():
    """The PDF comes back as base64 of a PDF file named like the Flask download."""
    doc = _play_all(_started(), SIMPLE_SCORES)
    data = _data(bridge.export(doc, "results_pdf", NOW))
    assert (data["filename"], data["mime_type"], data["encoding"]) == (
        "results_20261004-153012.pdf", "application/pdf", "base64")
    assert base64.b64decode(data["content"]).startswith(b"%PDF-")
    _refused(bridge.export(doc, "results_docx", NOW), "validation")
    _refused(bridge.export(doc, "results_pdf", "now"), "validation")


def test_pdf_export_opens_with_pypdf_and_holds_the_report():
    """pypdf reads the bridge's PDF: same text as the core's report, with the title, stamp, leaderboard and every archer."""
    doc = _play_all(_started(), SIMPLE_SCORES)
    pdf = base64.b64decode(_data(bridge.export(doc, "results_pdf", NOW))["content"])
    reader = pypdf.PdfReader(io.BytesIO(pdf))
    text = "\n".join(page.extract_text() for page in reader.pages)
    core = exports.results_pdf(bridge.rebuild_event(doc), datetime(2026, 10, 4, 15, 30, 12))
    assert text == "\n".join(page.extract_text() for page in pypdf.PdfReader(io.BytesIO(core)).pages)
    assert len(reader.pages) >= 1
    assert "Handicapped H2H results" in text and "Exported 2026-10-04 15:30:12" in text
    for row in _data(bridge.results(doc))["leaderboard"]:
        assert row["name"] in text
    for section in _data(bridge.archer_results(doc))["sections"]:
        assert f"{section['name']} - total score {section['total_score']}" in " ".join(text.split())


@pytest.mark.parametrize(
    ("kind", "codename", "compound", "score"),
    [("indoor", "portsmouth", False, 550), ("indoor", "portsmouth", True, "570"), ("outdoor", "wa720_70", True, 600)],
)
def test_calculator_rounds_the_core_handicap_to_one_place(kind, codename, compound, score):
    """The calculator gives the core's handicap for the round to 1 decimal place."""
    rnd = models.calculator_round(kind, codename, compound)
    expected = round(stats.handicap_for_round_score(float(score), rnd), 1)
    assert _data(bridge.calculator(kind, codename, compound, score)) == {"handicap": expected, "text": str(expected)}


@pytest.mark.parametrize(
    ("kind", "codename", "score", "message"),
    [
        ("both", "portsmouth", 500, "Choose indoor or outdoor, got 'both'."),
        ("outdoor", "portsmouth", 500, "'portsmouth' is not one of the standard outdoor rounds."),
        ("indoor", "portsmouth", "abc", "Enter a valid score for the chosen round."),
        ("indoor", "portsmouth", "nan", "Enter a valid score for the chosen round."),
        ("indoor", "portsmouth", 601, "Enter a valid score for the chosen round."),
    ],
)
def test_calculator_refuses_invalid_input_with_the_existing_messages(kind, codename, score, message):
    """Invalid kinds, rounds and scores give the Flask calculator's messages."""
    _refused(bridge.calculator(kind, codename, False, score), "validation", message)


def _record_first_match(doc):
    """Save the first match of the current pass with 90 for each archer."""
    view = _data(bridge.match(doc, 0))
    return bridge.record_match(doc, 0, {str(a["position"]): 90 for a in view["archers"]})


MUTATING = [
    ("apply_stage1", _fresh, lambda d: bridge.apply_stage1(d, SIMPLE_FORM)),
    ("apply_stage2", _at_stage1, lambda d: bridge.apply_stage2(d, SIMPLE_ROWS, NO_UPDATING, 7)),
    ("redraw", _at_stage2, lambda d: bridge.redraw(d, 7)),
    ("start_event", _at_stage2, bridge.start_event),
    ("record_match", _started, _record_first_match),
    ("advance", lambda: _save(_save(_started(), 0, SIMPLE_SCORES), 1, SIMPLE_SCORES), bridge.advance),
]


@pytest.mark.parametrize(("make", "command"), [m[1:] for m in MUTATING], ids=[m[0] for m in MUTATING])
def test_mutating_commands_return_a_new_document_and_leave_the_input_alone(make, command):
    """Every command that changes the event returns a new document object; the input is unchanged."""
    doc = make()
    before = copy.deepcopy(doc)
    new = _data(command(doc))["document"]
    assert doc == before
    assert new is not doc and new != doc
    assert all(new[key] is not doc[key] for key in ("setup", "archers", "scores"))
    assert (new["revision"], new["updated_at"]) == (doc["revision"], doc["updated_at"])  # the storage layer's (D12)
    assert bridge.validate_document(new)["ok"]


def test_every_command_round_trips_through_call_as_json():
    """Every command's output passes json.dumps(allow_nan=False), via `call` exactly as the worker uses it."""

    called = set()

    def call(command, **payload):
        called.add(command)
        result = json.loads(bridge.call(command, json.dumps(payload, allow_nan=False)))
        assert result == json.loads(json.dumps(getattr(bridge, command)(**payload), allow_nan=False))
        assert not (result["ok"] is False and result["error"]["code"] == "internal"), result
        return result

    doc = call("new_document", event_id="e1", now_iso=NOW)["data"]
    call("validate_document", raw=doc)
    call("options")
    doc = call("apply_stage1", doc=doc, form=SIMPLE_FORM)["data"]["document"]
    call("stage2_info", doc=doc)
    doc = call("apply_stage2", doc=doc, archers=SIMPLE_ROWS, updating=NO_UPDATING, seed=4)["data"]["document"]
    doc = call("redraw", doc=doc, seed=5)["data"]["document"]
    call("pairings", doc=doc)
    doc = call("start_event", doc=doc)["data"]["document"]
    doc = _play_all(doc, SIMPLE_SCORES)
    call("overview", doc=doc)
    view = call("match", doc=doc, match_index=1)["data"]
    call("record_match", doc=doc, match_index=1, scores={str(a["position"]): 60 for a in view["archers"]}, closest=None)
    call("advance", doc=doc)  # refused (final pass), still an envelope
    call("results", doc=doc)
    call("archer_results", doc=doc)
    call("pair_chart", doc=doc, a=0, b=1)
    for kind in ("leaderboard_csv", "archer_results_csv", "results_pdf"):
        call("export", doc=doc, kind=kind, now_iso=NOW)
    call("calculator", kind="indoor", round_codename="portsmouth", compound=False, score=500)
    spec_commands = {
        "options", "new_document", "apply_stage1", "apply_stage2", "redraw", "pairings", "start_event", "overview",
        "match", "record_match", "advance", "results", "archer_results", "pair_chart", "export", "calculator",
        "validate_document",
    }  # every command of UISpec.md 5.4
    spec_commands.add("stage2_info")  # added at the owner's request after the UI-9 review
    assert called == set(bridge._COMMANDS) == spec_commands


def test_call_turns_unexpected_failures_into_internal_errors():
    """An unknown command, malformed JSON or wrong arguments give an 'internal' envelope, not an exception."""
    for command, payload in (("nonsense", "{}"), ("options", "not json"), ("options", '{"x": 1}'),
                             ("overview", '{"doc": {}}')):
        result = json.loads(bridge.call(command, payload))
        assert result["ok"] is False and result["error"]["code"] == "internal"
