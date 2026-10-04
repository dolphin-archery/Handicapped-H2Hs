"""Bridge between the browser UI and the h2h core: the event document and its replay.

UISpec.md section 5. Pure functions only: no Flask, no module-level mutable state, no file or
network access. The UI holds the event document below as the single source of truth and Python
keeps nothing between calls: whenever an `Event` is needed it is rebuilt from the document by
replaying the stored scores (`rebuild_event`). Public functions return the envelope
`{"ok": True, "data": ...}` or `{"ok": False, "error": {"code": ..., "message": ...}}`, apart from
`rebuild_event` and `schedule_for`, the building blocks the commands use.

The event document, schema version 1 (JSON, snake_case keys)::

    {"schema_version": 1, "id": str, "name": str, "created_at": ISO-8601, "updated_at": ISO-8601,
     "revision": int, "status": "setup" | "running" | "complete",
     "setup": {"stage": 0 to 3 (furthest stage completed), "n_archers": int,
               "total_arrows": int, "n_pass": int, "setup_mode": "simple" | "advanced",
               "shoot_byes": bool, "target": {"distance_key": str, "face_cm": int},
               "update_handicaps": bool, "n_lookback": int | None, "start_weight": int | None},
     "archers": [{"name": str, "bowstyle": str, "handicap": float,
                  "target": None | {"distance_key": str, "face_cm": int, "face_type": str}}],
     "assignment": [index into "archers" for each schedule position] | None,
     "scores": {"<pass>": {"<match>": {"scores": {"<position>": int}, "closest": int | None}}},
     "current_pass": int}

After the Stage 3 draw the event's archer indices are schedule positions: position `p` is
`archers[assignment[p]]`, and the score keys and `closest` use positions. The schedule is not
stored; `schedule_for` rebuilds it deterministically. Only inputs are stored, never results.
"""

from __future__ import annotations

import math
from datetime import datetime

from .models import (
    MAX_HANDICAP,
    MIN_HANDICAP,
    Archer,
    Bowstyle,
    Event,
    TargetSetup,
)
from .rotation import Rotation, build_schedule, build_sit_out_schedule

SCHEMA_VERSION = 1

# Event status values (UISpec.md section 5.2, decision D11).
SETUP = "setup"
RUNNING = "running"
COMPLETE = "complete"

# Setup modes, as `h2h.state` names them (the bridge does not import the Flask-era state).
SIMPLE = "simple"
ADVANCED = "advanced"

# Error codes of the envelope (UISpec.md section 5.1).
VALIDATION = "validation"

_SETUP_KEYS = (
    "stage",
    "n_archers",
    "total_arrows",
    "n_pass",
    "setup_mode",
    "shoot_byes",
    "target",
    "update_handicaps",
    "n_lookback",
    "start_weight",
)
_DOCUMENT_KEYS = (
    "schema_version",
    "id",
    "name",
    "created_at",
    "updated_at",
    "revision",
    "status",
    "setup",
    "archers",
    "assignment",
    "scores",
    "current_pass",
)


class DocumentError(ValueError):
    """An event document that does not follow schema version 1."""


def _ok(data: object) -> dict:
    """The success envelope.

    Parameters
    ----------
    data : object
        The JSON-serialisable result.

    Returns
    -------
    dict
        `{"ok": True, "data": data}`.
    """
    return {"ok": True, "data": data}


def _error(code: str, message: str) -> dict:
    """The failure envelope.

    Parameters
    ----------
    code : str
        One of the error codes of UISpec.md section 5.1, e.g. `VALIDATION`.
    message : str
        Text to show the user.

    Returns
    -------
    dict
        `{"ok": False, "error": {"code": code, "message": message}}`.
    """
    return {"ok": False, "error": {"code": code, "message": message}}


def schedule_for(setup: dict) -> list[Rotation]:
    """Rebuild the rotation schedule from a document's setup, as Stage 1 builds it.

    Parameters
    ----------
    setup : dict
        A valid document `setup` (uses `n_archers`, `total_arrows`, `n_pass`, `shoot_byes`).

    Returns
    -------
    list[h2h.rotation.Rotation]
        `build_sit_out_schedule` for an odd number of archers who do not shoot byes,
        otherwise `build_schedule`, over `total_arrows // n_pass` passes per archer.
    """
    passes_per_archer = setup["total_arrows"] // setup["n_pass"]
    if setup["n_archers"] % 2 == 1 and not setup["shoot_byes"]:
        return build_sit_out_schedule(setup["n_archers"], passes_per_archer)
    return build_schedule(setup["n_archers"], passes_per_archer)


def _archer(entry: dict) -> Archer:
    """Build an `Archer` from a document `archers` entry.

    Parameters
    ----------
    entry : dict
        `{"name", "bowstyle", "handicap", "target"}`, `target` being None (simple setup) or
        `{"distance_key", "face_cm", "face_type"}` (advanced setup).

    Returns
    -------
    h2h.models.Archer
        The archer, with their own target setup in advanced setup.
    """
    target = entry["target"]
    target_setup = None
    if target is not None:
        target_setup = TargetSetup.parse_advanced(
            target["distance_key"], target["face_cm"], target["face_type"]
        )
    return Archer(
        name=entry["name"],
        handicap=float(entry["handicap"]),
        bowstyle=Bowstyle(entry["bowstyle"]),
        target_setup=target_setup,
    )


def rebuild_event(doc: dict) -> Event:
    """Build the `Event` a document describes by replaying its stored scores (UISpec.md 5.3).

    The schedule and the event are built from `setup`, `archers` and `assignment`; then each
    pass from the first to `current_pass` has its stored matches recorded in match order, and
    the event advances past every pass before the current one. This reproduces the event the
    scores were entered into, because a pass's handicaps depend only on earlier passes.

    Parameters
    ----------
    doc : dict
        A valid event document (see the module docstring) whose Stage 2 is complete.

    Returns
    -------
    h2h.models.Event
        The event at `current_pass`, with every stored score recorded.

    Raises
    ------
    ValueError
        If Stage 2 has not been completed (there is no assignment yet), or the core rejects a
        stored score or an advance (the core's own message; `h2h.stats.TieBreakRequired` for
        a tie stored without a closest archer).
    """
    if doc["assignment"] is None:
        msg = "Stage 2 must be completed before the event can be built."
        raise ValueError(msg)
    setup = doc["setup"]
    entered = [_archer(entry) for entry in doc["archers"]]
    shared_setup = None
    if setup["setup_mode"] != ADVANCED:
        shared_setup = TargetSetup.parse(setup["target"]["distance_key"], setup["target"]["face_cm"])
    event = Event(
        [entered[i] for i in doc["assignment"]],
        setup["n_pass"],
        shared_setup,
        schedule_for(setup),
        update_handicaps=setup["update_handicaps"],
        n_lookback=setup["n_lookback"],
        start_weight=setup["start_weight"],
    )
    for pass_index in range(doc["current_pass"] + 1):
        stored = doc["scores"].get(str(pass_index), {})
        for match_key in sorted(stored, key=int):
            match = stored[match_key]
            scores = {int(position): score for position, score in match["scores"].items()}
            event.record_match(scores, closest=match["closest"])
        if pass_index < doc["current_pass"]:
            event.advance()
    return event


# --- Validation (UISpec.md 5.4 `validate_document`, section 6 rules 7 and 9) -----------------


def _fields(value: object, where: str, keys: tuple[str, ...]) -> dict:
    """Check a value is an object with every one of `keys`.

    Parameters
    ----------
    value : object
        The value to check.
    where : str
        Its name for messages, e.g. "setup".
    keys : tuple[str, ...]
        The keys it must have (others are ignored).

    Returns
    -------
    dict
        `value`, unchanged.

    Raises
    ------
    DocumentError
        If it is not a dict or a key is missing.
    """
    if not isinstance(value, dict):
        msg = f"{where} must be an object."
        raise DocumentError(msg)
    missing = [key for key in keys if key not in value]
    if missing:
        msg = f"{where} is missing {', '.join(missing)}."
        raise DocumentError(msg)
    return value


def _whole(value: object, where: str, minimum: int) -> int:
    """Check a value is a whole number (a JSON integer, not a boolean) of at least `minimum`.

    Parameters
    ----------
    value : object
        The value to check.
    where : str
        Its name for messages, e.g. "setup.n_pass".
    minimum : int
        The smallest allowed value.

    Returns
    -------
    int
        `value`, unchanged.

    Raises
    ------
    DocumentError
        If it is not an int, or is below `minimum`.
    """
    if type(value) is not int or value < minimum:
        msg = f"{where} must be a whole number of at least {minimum}."
        raise DocumentError(msg)
    return value


def _flag(value: object, where: str) -> bool:
    """Check a value is a boolean.

    Parameters
    ----------
    value : object
        The value to check.
    where : str
        Its name for messages.

    Returns
    -------
    bool
        `value`, unchanged.

    Raises
    ------
    DocumentError
        If it is not a bool.
    """
    if type(value) is not bool:
        msg = f"{where} must be true or false."
        raise DocumentError(msg)
    return value


def _text(value: object, where: str, allow_blank: bool = False) -> str:
    """Check a value is a string (and not blank, unless allowed).

    Parameters
    ----------
    value : object
        The value to check.
    where : str
        Its name for messages.
    allow_blank : bool, default=False
        Whether an empty or all-whitespace string is accepted.

    Returns
    -------
    str
        `value`, unchanged.

    Raises
    ------
    DocumentError
        If it is not a str, or is blank when that is not allowed.
    """
    if not isinstance(value, str) or (not allow_blank and not value.strip()):
        msg = f"{where} must be {'text' if allow_blank else 'non-empty text'}."
        raise DocumentError(msg)
    return value


def _timestamp(value: object, where: str) -> str:
    """Check a value is an ISO-8601 date and time.

    Parameters
    ----------
    value : object
        The value to check, e.g. "2026-10-04T15:30:12.345Z".
    where : str
        Its name for messages.

    Returns
    -------
    str
        `value`, unchanged.

    Raises
    ------
    DocumentError
        If it is not a string `datetime.fromisoformat` accepts.
    """
    try:
        datetime.fromisoformat(_text(value, where))
    except ValueError:
        msg = f"{where} must be an ISO-8601 date and time."
        raise DocumentError(msg) from None
    return value


def _index_key(key: object, where: str) -> int:
    """Check an object key is a whole number written plainly ("0", "12"; not "01" or "-1").

    Parameters
    ----------
    key : object
        The key.
    where : str
        Where it was found, for messages.

    Returns
    -------
    int
        The number.

    Raises
    ------
    DocumentError
        If it is not such a string.
    """
    if not (isinstance(key, str) and key.isdecimal() and key.isascii() and str(int(key)) == key):
        msg = f"{where} has a key {key!r} that is not a whole number."
        raise DocumentError(msg)
    return int(key)


def _checked_setup(raw: object) -> dict:
    """Validate a document's `setup` and return a clean copy.

    Parameters
    ----------
    raw : object
        The untrusted `setup` value.

    Returns
    -------
    dict
        The setup with exactly the schema's keys, in schema order.

    Raises
    ------
    DocumentError
        If any field is missing, of the wrong type, or inconsistent (for example arrows per
        pass not dividing total arrows, or handicap updating outside advanced setup).
    ValueError
        If the shared target is not one of the standard options (the core's message).
    """
    setup = _fields(raw, "setup", _SETUP_KEYS)
    stage = _whole(setup["stage"], "setup.stage", 0)
    if stage > 3:
        msg = "setup.stage must be 0, 1, 2 or 3."
        raise DocumentError(msg)
    n_pass = _whole(setup["n_pass"], "setup.n_pass", 1)
    total_arrows = _whole(setup["total_arrows"], "setup.total_arrows", 1)
    if total_arrows % n_pass != 0:
        msg = f"setup.n_pass ({n_pass}) must evenly divide setup.total_arrows ({total_arrows})."
        raise DocumentError(msg)
    if setup["setup_mode"] not in (SIMPLE, ADVANCED):
        msg = "setup.setup_mode must be 'simple' or 'advanced'."
        raise DocumentError(msg)
    target = _fields(setup["target"], "setup.target", ("distance_key", "face_cm"))
    distance_key = _text(target["distance_key"], "setup.target.distance_key")
    TargetSetup.parse(distance_key, _whole(target["face_cm"], "setup.target.face_cm", 1))
    updating = _flag(setup["update_handicaps"], "setup.update_handicaps")
    if updating and (setup["setup_mode"] != ADVANCED or stage < 2):
        msg = "setup.update_handicaps can only be true in advanced setup once Stage 2 is complete."
        raise DocumentError(msg)
    for key in ("n_lookback", "start_weight"):
        if updating:
            _whole(setup[key], f"setup.{key}", 1)
        elif setup[key] is not None:
            msg = f"setup.{key} must be null when handicaps are not updated."
            raise DocumentError(msg)
    return {
        "stage": stage,
        "n_archers": _whole(setup["n_archers"], "setup.n_archers", 2),
        "total_arrows": total_arrows,
        "n_pass": n_pass,
        "setup_mode": setup["setup_mode"],
        "shoot_byes": _flag(setup["shoot_byes"], "setup.shoot_byes"),
        "target": {"distance_key": target["distance_key"], "face_cm": target["face_cm"]},
        "update_handicaps": updating,
        "n_lookback": setup["n_lookback"],
        "start_weight": setup["start_weight"],
    }


def _checked_archer(raw: object, where: str, advanced: bool) -> dict:
    """Validate one document `archers` entry and return a clean copy.

    Parameters
    ----------
    raw : object
        The untrusted entry.
    where : str
        Its name for messages, e.g. "archers[2]".
    advanced : bool
        Whether the event uses advanced setup (each archer then needs their own target).

    Returns
    -------
    dict
        `{"name", "bowstyle", "handicap" (as a float), "target"}`.

    Raises
    ------
    DocumentError
        If a field is missing or invalid.
    ValueError
        If an advanced target is not one of the offered options (the core's message).
    """
    entry = _fields(raw, where, ("name", "bowstyle", "handicap", "target"))
    if entry["bowstyle"] not in {b.value for b in Bowstyle}:
        msg = f"{where}.bowstyle must be one of {', '.join(b.value for b in Bowstyle)}."
        raise DocumentError(msg)
    handicap = entry["handicap"]
    if (
        type(handicap) not in (int, float)
        or not math.isfinite(handicap)
        or not MIN_HANDICAP <= handicap <= MAX_HANDICAP
    ):
        msg = f"{where}.handicap must be a number between {MIN_HANDICAP} and {MAX_HANDICAP}."
        raise DocumentError(msg)
    target = None
    if advanced:
        found = _fields(entry["target"], f"{where}.target", ("distance_key", "face_cm", "face_type"))
        target = {
            "distance_key": _text(found["distance_key"], f"{where}.target.distance_key"),
            "face_cm": _whole(found["face_cm"], f"{where}.target.face_cm", 1),
            "face_type": _text(found["face_type"], f"{where}.target.face_type"),
        }
        TargetSetup.parse_advanced(target["distance_key"], target["face_cm"], target["face_type"])
    elif entry["target"] is not None:
        msg = f"{where}.target must be null in simple setup."
        raise DocumentError(msg)
    return {
        "name": _text(entry["name"], f"{where}.name"),
        "bowstyle": entry["bowstyle"],
        "handicap": float(handicap),
        "target": target,
    }


def _checked_scores(raw: object, schedule: list[Rotation], current_pass: int) -> dict:
    """Validate a document's `scores` structure against the schedule and return a clean copy.

    Only the structure is checked here (which passes, matches and archers); the score values
    themselves are checked by replaying them through the core (`rebuild_event`).

    Parameters
    ----------
    raw : object
        The untrusted `scores` value.
    schedule : list[h2h.rotation.Rotation]
        The event's schedule.
    current_pass : int
        The pass being shot; no later pass may have scores.

    Returns
    -------
    dict
        The scores with keys in numeric order.

    Raises
    ------
    DocumentError
        If a pass or match does not exist (yet), a match's scores are not for exactly that
        match's archers, a score is not a number, or `closest` is not one of a pair's archers.
    """
    if not isinstance(raw, dict):
        msg = "scores must be an object."
        raise DocumentError(msg)
    clean = {}
    for pass_key in sorted(raw, key=lambda k: _index_key(k, "scores")):
        pass_index = int(pass_key)
        if pass_index > current_pass:
            msg = f"scores has pass {pass_index + 1}, after the current pass {current_pass + 1}."
            raise DocumentError(msg)
        matches = raw[pass_key]
        if not isinstance(matches, dict):
            msg = f"scores[{pass_key}] must be an object."
            raise DocumentError(msg)
        clean_pass = {}
        for match_key in sorted(matches, key=lambda k: _index_key(k, f"scores[{pass_key}]")):
            where = f"scores[{pass_key}][{match_key}]"
            schedule_matches = schedule[pass_index].matches
            if int(match_key) >= len(schedule_matches):
                msg = f"{where} is not a match of pass {pass_index + 1}."
                raise DocumentError(msg)
            entry = _fields(matches[match_key], where, ("scores", "closest"))
            match_archers = [p for p in schedule_matches[int(match_key)] if p is not None]
            scores = _fields(entry["scores"], f"{where}.scores", ())
            if sorted(_index_key(k, f"{where}.scores") for k in scores) != sorted(match_archers):
                msg = f"{where}.scores must be for archers {sorted(match_archers)} exactly."
                raise DocumentError(msg)
            for key, score in scores.items():
                if type(score) not in (int, float):
                    msg = f"{where}.scores[{key}] must be a number."
                    raise DocumentError(msg)
            closest = entry["closest"]
            if closest is not None and (
                len(match_archers) < 2 or type(closest) is not int or closest not in match_archers
            ):
                msg = f"{where}.closest must be null or one of the two archers in the match."
                raise DocumentError(msg)
            clean_pass[match_key] = {
                "scores": {key: scores[key] for key in sorted(scores, key=int)},
                "closest": closest,
            }
        clean[pass_key] = clean_pass
    return clean


def _checked_document(raw: object) -> dict:
    """Validate the structure of an untrusted event document and return a clean copy.

    Parameters
    ----------
    raw : object
        The decoded JSON value (from storage or an imported backup).

    Returns
    -------
    dict
        A new document with exactly the schema's keys; unknown keys are dropped. The stored
        scores are not yet replayed.

    Raises
    ------
    DocumentError
        If the document is not a schema-version-1 document or its parts are inconsistent.
    ValueError
        If a target is not one of the offered options (the core's message).
    """
    doc = _fields(raw, "The document", ("schema_version",))
    version = doc["schema_version"]
    if version != SCHEMA_VERSION or type(version) is not int:
        msg = f"schema version {version!r} is not supported (this app reads version {SCHEMA_VERSION})."
        raise DocumentError(msg)
    _fields(doc, "The document", _DOCUMENT_KEYS)
    setup = _checked_setup(doc["setup"])
    stage = setup["stage"]

    status = doc["status"]
    if status not in (SETUP, RUNNING, COMPLETE):
        msg = "status must be 'setup', 'running' or 'complete'."
        raise DocumentError(msg)
    if (status == SETUP) != (stage < 3):
        msg = "status must be 'setup' before Stage 3 is confirmed, and not after."
        raise DocumentError(msg)

    archers = doc["archers"]
    assignment = doc["assignment"]
    if not isinstance(archers, list):
        msg = "archers must be a list."
        raise DocumentError(msg)
    if stage < 2:
        if archers or assignment is not None:
            msg = "archers must be empty and assignment null before Stage 2 is complete."
            raise DocumentError(msg)
    else:
        if len(archers) != setup["n_archers"]:
            msg = f"archers must have {setup['n_archers']} entries, got {len(archers)}."
            raise DocumentError(msg)
        advanced = setup["setup_mode"] == ADVANCED
        archers = [_checked_archer(a, f"archers[{i}]", advanced) for i, a in enumerate(archers)]
        if (
            not isinstance(assignment, list)
            or any(type(i) is not int for i in assignment)
            or sorted(assignment) != list(range(setup["n_archers"]))
        ):
            msg = f"assignment must list each of 0 to {setup['n_archers'] - 1} once."
            raise DocumentError(msg)
        assignment = list(assignment)

    current_pass = _whole(doc["current_pass"], "current_pass", 0)
    if status == SETUP:
        if current_pass != 0 or doc["scores"] != {}:
            msg = "scores must be empty and current_pass 0 before the event starts."
            raise DocumentError(msg)
        scores = {}
    else:
        schedule = schedule_for(setup)
        if current_pass >= len(schedule):
            msg = f"current_pass must be below the number of passes ({len(schedule)})."
            raise DocumentError(msg)
        scores = _checked_scores(doc["scores"], schedule, current_pass)

    return {
        "schema_version": SCHEMA_VERSION,
        "id": _text(doc["id"], "id"),
        "name": _text(doc["name"], "name", allow_blank=True),
        "created_at": _timestamp(doc["created_at"], "created_at"),
        "updated_at": _timestamp(doc["updated_at"], "updated_at"),
        "revision": _whole(doc["revision"], "revision", 0),
        "status": status,
        "setup": setup,
        "archers": archers,
        "assignment": assignment,
        "scores": scores,
        "current_pass": current_pass,
    }


def validate_document(raw: object) -> dict:
    """Check an untrusted event document (stored, or from an imported backup) and clean it.

    Never trusts its input: the structure, types and ranges are checked, then the stored scores
    are replayed through the core (`rebuild_event`), so a score the app would refuse, a tie
    without a closest archer, or an earlier pass left unscored is rejected with the core's own
    message, and `status` must say "complete" exactly when the event is complete (decision
    D11). Schema migrations will live here (UISpec.md section 6, rule 9); version 1 is the only
    version so far.

    Parameters
    ----------
    raw : object
        The decoded JSON value.

    Returns
    -------
    dict
        `{"ok": True, "data": document}` with a clean copy (unknown keys dropped, handicaps as
        floats, scores as integers, score keys in numeric order), or `{"ok": False, "error":
        {"code": "validation", "message": "Invalid event document: ..."}}`.
    """
    try:
        doc = _checked_document(raw)
        if doc["status"] != SETUP:
            event = rebuild_event(doc)
            if (doc["status"] == COMPLETE) != event.is_complete:
                msg = "status must be 'complete' exactly when every pass is scored."
                raise DocumentError(msg)
            for matches in doc["scores"].values():
                for match in matches.values():
                    match["scores"] = {key: int(score) for key, score in match["scores"].items()}
    except ValueError as exc:  # DocumentError, and the core's own checks during the replay
        return _error(VALIDATION, f"Invalid event document: {exc}")
    return _ok(doc)
