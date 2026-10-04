"""Bridge between the browser UI and the h2h core: the event document and its replay.

UISpec.md section 5. Pure functions only: no Flask, no module-level mutable state, no file or
network access. The UI holds the event document below as the single source of truth and Python
keeps nothing between calls: whenever an `Event` is needed it is rebuilt from the document by
replaying the stored scores (`rebuild_event`). The commands of UISpec.md 5.4 return the
envelope `{"ok": True, "data": ...}` or `{"ok": False, "error": {"code": ..., "message": ...}}`;
`call` is the one entry point the browser uses, taking and returning JSON text. Commands that
change the document return a new one (`data["document"]`) and leave their input untouched; they
never set `revision` or `updated_at`, which belong to the storage layer (decision D12).

Form values (Stage 1, Stage 2, scores, the calculator) are read the way the Flask routes read
their form fields, as text or numbers, so every error message is the existing one. Values for
display (scores, percentiles, handicaps, winners) are returned as the text the Flask templates
showed, so the UI never formats a number itself.

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

import base64
import copy
import json
import math
import random
from dataclasses import asdict
from datetime import datetime

from . import chart_data, exports, outputs, stats
from .draw import draw_assignment
from .models import (
    ADVANCED_FACE_SIZES_CM,
    DEFAULT_CALCULATOR_ROUND,
    DEFAULT_FACE_TYPE,
    DEFAULT_N_LOOKBACK,
    DEFAULT_TARGET_SETUP,
    FACE_TYPES,
    INDOOR,
    MAX_HANDICAP,
    MIN_HANDICAP,
    OUTDOOR,
    STANDARD_FACE_SIZES_CM,
    Archer,
    Bowstyle,
    Event,
    TargetSetup,
    calculator_round,
    calculator_rounds,
    distance_option_groups,
)
from .rotation import Rotation, build_schedule, build_sit_out_schedule

SCHEMA_VERSION = 1

# Stage 1 defaults, as the Flask app's form and `SessionState` start.
DEFAULT_N_ARCHERS = 4
DEFAULT_TOTAL_ARROWS = 60
DEFAULT_N_PASS = 12
DEFAULT_EVENT_NAME = "New event"

# Event status values (UISpec.md section 5.2, decision D11).
SETUP = "setup"
RUNNING = "running"
COMPLETE = "complete"

# Setup modes, as `h2h.state` names them (the bridge does not import the Flask-era state).
SIMPLE = "simple"
ADVANCED = "advanced"

# Error codes of the envelope (UISpec.md section 5.1).
VALIDATION = "validation"
TIEBREAK_REQUIRED = "tiebreak_required"
STATE = "state"
INTERNAL = "internal"

# Messages for actions the current state does not allow (the first three are SessionState's).
STAGE1_FIRST = "Stage 1 must be completed before Stage 2."
STAGE2_FIRST = "Stage 2 must be completed before pairings can be drawn."
STAGE1_BEFORE_START = "Stage 1 must be completed before the event can start."
ALREADY_STARTED = "The event has started, so its setup can no longer be changed."
NOT_STARTED = "The event has not started yet: confirm the pairings at Stage 3 first."
# The Flask match page's message when a save is refused for a tie.
TIEBREAK_MESSAGE = (
    "Percentile and score are tied. Tick which archer's arrow was closest "
    "to the middle, then save again."
)

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


# --- Form values, read as the Flask routes read them ------------------------------------------


def _form_int(value: object) -> int:
    """A whole number from a form value, as the Flask routes read one (`int(text)`).

    Parameters
    ----------
    value : object
        Text or a number from the form; JSON numbers are read through their text, so 12.0
        is refused as the text "12.0" was.

    Returns
    -------
    int
        The number.

    Raises
    ------
    ValueError
        Python's own message, e.g. "invalid literal for int() with base 10: 'abc'".
    """
    return int(str(value))


def _form_text(row: dict, key: str, strip: bool = True) -> str:
    """A form field as text ("" when it is missing or null).

    Parameters
    ----------
    row : dict
        The form values.
    key : str
        The field.
    strip : bool, default=True
        Whether to remove surrounding whitespace (the Flask route stripped the name, bowstyle
        and handicap, but not the target dropdowns).

    Returns
    -------
    str
        The text.
    """
    value = row.get(key)
    text = "" if value is None else str(value)
    return text.strip() if strip else text


def _whole_number(raw: object, label: str) -> int:
    """A handicap-updating parameter: a whole number of at least 1 (as the Flask route reads it).

    Parameters
    ----------
    raw : object
        The text or number from the form.
    label : str
        What the number is, for the message ("Lookback" or "Start weight").

    Returns
    -------
    int
        The number.

    Raises
    ------
    ValueError
        "<label> must be a whole number of at least 1." if it is not one.
    """
    try:
        value = int(str(raw).strip())
    except ValueError:
        value = 0
    if value < 1:
        msg = f"{label} must be a whole number of at least 1."
        raise ValueError(msg)
    return value


def _one_place(value: float | None) -> str:
    """A derived handicap for display, as the Flask templates showed it.

    Parameters
    ----------
    value : float | None
        The handicap, or None when there is none (e.g. for a score of 0).

    Returns
    -------
    str
        One decimal place, or "-".
    """
    return "-" if value is None else f"{value:.1f}"


def _seed_error(seed: object) -> dict | None:
    """Check a draw seed.

    Parameters
    ----------
    seed : object
        The seed supplied by the caller.

    Returns
    -------
    dict | None
        A `validation` error envelope if the seed is not a whole number (an int, not a bool),
        otherwise None.
    """
    if type(seed) is not int:
        return _error(VALIDATION, "The draw needs a whole-number seed.")
    return None


# --- Commands (UISpec.md 5.4) ----------------------------------------------------------------


def options() -> dict:
    """The static lists and defaults the forms need.

    Returns
    -------
    dict
        Envelope whose data has `distance_groups` (`[{"group": "Metric" | "Imperial",
        "items": [{"value": "18m", "label": "18 m"}, ...]}]`), `face_sizes` and
        `advanced_face_sizes` (cm), `face_types` (`[{"value", "label"}]`), `bowstyles`,
        `min_handicap`, `max_handicap`, `defaults` (Stage 1 and Stage 2 defaults) and
        `calculator` (`{"kinds", "rounds": {kind: [{"value", "label"}]}, "defaults": {kind:
        codename}}`).
    """
    return _ok(
        {
            "distance_groups": [
                {"group": group, "items": [{"value": v, "label": label} for v, label in items]}
                for group, items in distance_option_groups().items()
            ],
            "face_sizes": list(STANDARD_FACE_SIZES_CM),
            "advanced_face_sizes": list(ADVANCED_FACE_SIZES_CM),
            "face_types": [{"value": key, "label": label} for key, label in FACE_TYPES.items()],
            "bowstyles": [b.value for b in Bowstyle],
            "min_handicap": MIN_HANDICAP,
            "max_handicap": MAX_HANDICAP,
            "defaults": {
                "n_archers": DEFAULT_N_ARCHERS,
                "total_arrows": DEFAULT_TOTAL_ARROWS,
                "n_pass": DEFAULT_N_PASS,
                "setup_mode": SIMPLE,
                "shoot_byes": True,
                "distance_key": DEFAULT_TARGET_SETUP.distance_key,
                "face_cm": DEFAULT_TARGET_SETUP.face_cm,
                "face_type": DEFAULT_FACE_TYPE,
                "n_lookback": DEFAULT_N_LOOKBACK,
            },
            "calculator": {
                "kinds": [INDOOR, OUTDOOR],
                "rounds": {
                    kind: [{"value": code, "label": rnd.name} for code, rnd in calculator_rounds(kind).items()]
                    for kind in (INDOOR, OUTDOOR)
                },
                "defaults": dict(DEFAULT_CALCULATOR_ROUND),
            },
        }
    )


def new_document(event_id: str, now_iso: str) -> dict:
    """A fresh event document with the defaults (nothing submitted yet).

    Parameters
    ----------
    event_id : str
        The new event's id (a UUID made by the UI).
    now_iso : str
        The creation time, ISO-8601.

    Returns
    -------
    dict
        Envelope whose data is the document: status "setup", stage 0, the Stage 1 defaults,
        revision 0, `created_at` and `updated_at` both `now_iso`.
    """
    if not isinstance(event_id, str) or not event_id.strip():
        return _error(VALIDATION, "An event needs a non-empty id.")
    try:
        datetime.fromisoformat(now_iso)
    except (TypeError, ValueError):
        return _error(VALIDATION, "now_iso must be an ISO-8601 date and time.")
    return _ok(
        {
            "schema_version": SCHEMA_VERSION,
            "id": event_id,
            "name": DEFAULT_EVENT_NAME,
            "created_at": now_iso,
            "updated_at": now_iso,
            "revision": 0,
            "status": SETUP,
            "setup": {
                "stage": 0,
                "n_archers": DEFAULT_N_ARCHERS,
                "total_arrows": DEFAULT_TOTAL_ARROWS,
                "n_pass": DEFAULT_N_PASS,
                "setup_mode": SIMPLE,
                "shoot_byes": True,
                "target": {
                    "distance_key": DEFAULT_TARGET_SETUP.distance_key,
                    "face_cm": DEFAULT_TARGET_SETUP.face_cm,
                },
                "update_handicaps": False,
                "n_lookback": None,
                "start_weight": None,
            },
            "archers": [],
            "assignment": None,
            "scores": {},
            "current_pass": 0,
        }
    )


def apply_stage1(doc: dict, form: dict) -> dict:
    """Submit Stage 1: validate the event configuration, store it and clear the later stages.

    Reads the form as the Flask route `stage1_submit` did and applies the checks of
    `SessionState.start_stage1`, so the messages are the same. In advanced setup the shared
    target is not read (each archer brings their own at Stage 2) and the last simple choice is
    kept.

    Parameters
    ----------
    doc : dict
        The event document; its status must be "setup".
    form : dict
        `{"n_archers", "total_arrows", "n_pass"}` (text or numbers), `"setup_mode"` ("simple"
        or "advanced"), `"distance"` (e.g. "20yd") and `"face_cm"` (simple setup), and
        `"shoot_byes"` (bool, or "yes"/"no"; default yes).

    Returns
    -------
    dict
        Envelope whose data is `{"document": new document at stage 1, "passes_per_archer":
        int, "n_passes": int}` (passes in the schedule, more than passes per archer when byes
        are sat out), or a `validation` error, or a `state` error once the event has started.
    """
    if doc["status"] != SETUP:
        return _error(STATE, ALREADY_STARTED)
    setup_mode = form.get("setup_mode", SIMPLE)
    try:
        n_archers = _form_int(form.get("n_archers", ""))
        total_arrows = _form_int(form.get("total_arrows", ""))
        n_pass = _form_int(form.get("n_pass", ""))
        if setup_mode == ADVANCED:
            target = dict(doc["setup"]["target"])  # keep the last simple choice
        else:
            parsed = TargetSetup.parse(form.get("distance", ""), form.get("face_cm", ""))
            target = {"distance_key": parsed.distance_key, "face_cm": parsed.face_cm}
        shoot_byes = form.get("shoot_byes", True) not in (False, "no")
        if setup_mode not in (SIMPLE, ADVANCED):
            msg = f"Setup mode must be Simple or Advanced, got {setup_mode!r}."
            raise ValueError(msg)
        if n_archers < 2:
            msg = f"Need at least 2 archers, got {n_archers}."
            raise ValueError(msg)
        if total_arrows <= 0 or n_pass <= 0 or total_arrows % n_pass != 0:
            msg = f"Arrows per pass ({n_pass}) must evenly divide total arrows ({total_arrows})."
            raise ValueError(msg)
    except ValueError as exc:
        return _error(VALIDATION, str(exc) or "Invalid input.")

    new = copy.deepcopy(doc)
    new["setup"] = {
        "stage": 1,
        "n_archers": n_archers,
        "total_arrows": total_arrows,
        "n_pass": n_pass,
        "setup_mode": setup_mode,
        "shoot_byes": shoot_byes,
        "target": target,
        "update_handicaps": False,
        "n_lookback": None,
        "start_weight": None,
    }
    new.update(archers=[], assignment=None, scores={}, current_pass=0)
    return _ok(
        {
            "document": new,
            "passes_per_archer": total_arrows // n_pass,
            "n_passes": len(schedule_for(new["setup"])),
        }
    )


def _row_error(row: int | None, field: str, message: str) -> dict:
    """A Stage 2 validation error that also names the offending row and field.

    Parameters
    ----------
    row : int | None
        0-based index of the archer row (None for the event-wide updating parameters).
    field : str
        The form field: "name", "bowstyle", "handicap", "distance", "face_cm", "face_type",
        "n_lookback" or "start_weight".
    message : str
        The existing row-numbered message (rows are 1-based in the text).

    Returns
    -------
    dict
        `{"ok": False, "error": {"code": "validation", "message", "row", "field"}}`.
    """
    envelope = _error(VALIDATION, message)
    envelope["error"].update(row=row, field=field)
    return envelope


# Which advanced-target field a `TargetSetup.parse_advanced` message is about.
_TARGET_FIELDS = (
    ("standard distances", "distance"),
    ("standard face sizes", "face_cm"),
    ("target face types", "face_type"),
)


def apply_stage2(doc: dict, archers: list, updating: dict, seed: int) -> dict:
    """Submit Stage 2: validate and store the archers, then draw their first assignment.

    Reads each row as the Flask route `stage2_submit` did, with the same row-numbered
    messages; the first problem found is reported, with its row and field. Handicap updating
    applies only in advanced setup. The draw is `h2h.draw.draw_assignment` with
    `random.Random(seed)`.

    Parameters
    ----------
    doc : dict
        The event document; Stage 1 must be complete and the event not started.
    archers : list[dict]
        One row per archer in entry order: `{"name", "bowstyle", "handicap"}`, plus
        `{"distance", "face_cm", "face_type"}` in advanced setup (text or numbers). Missing
        rows count as empty; extra rows are ignored.
    updating : dict
        `{"update_handicaps": bool (or "yes"/"no"), "n_lookback", "start_weight"}`.
    seed : int
        Seed of the draw (from `crypto.getRandomValues` in the browser).

    Returns
    -------
    dict
        Envelope whose data is `{"document": new document at stage 2}`, or a `validation`
        error with `row` (0-based, None for the updating parameters) and `field`, or a `state`
        error.
    """
    if doc["status"] != SETUP:
        return _error(STATE, ALREADY_STARTED)
    if doc["setup"]["stage"] < 1:
        return _error(STATE, STAGE1_FIRST)
    if (refusal := _seed_error(seed)) is not None:
        return refusal
    setup = doc["setup"]
    advanced = setup["setup_mode"] == ADVANCED
    rows = archers if isinstance(archers, list) else []
    entries = []
    for i in range(setup["n_archers"]):
        row = rows[i] if i < len(rows) and isinstance(rows[i], dict) else {}
        values = {key: _form_text(row, key) for key in ("name", "bowstyle", "handicap")}
        missing = [key for key in ("name", "handicap", "bowstyle") if not values[key]]
        if missing:
            return _row_error(i, missing[0], f"Row {i + 1}: name, handicap, and bowstyle are all required.")
        if values["bowstyle"] not in {b.value for b in Bowstyle}:
            return _row_error(i, "bowstyle", f"Row {i + 1}: '{values['bowstyle']}' is not a valid bowstyle.")
        try:
            handicap = float(values["handicap"])
        except ValueError:
            return _row_error(i, "handicap", f"Row {i + 1}: handicap must be a number.")
        if not MIN_HANDICAP <= handicap <= MAX_HANDICAP:  # also rejects nan
            return _row_error(
                i,
                "handicap",
                f"Row {i + 1}: handicap must be between {MIN_HANDICAP} and {MAX_HANDICAP}, "
                f"got {values['handicap']}.",
            )
        target = None
        if advanced:
            try:
                parsed = TargetSetup.parse_advanced(
                    *(_form_text(row, key, strip=False) for key in ("distance", "face_cm", "face_type"))
                )
            except ValueError as exc:
                field = next(f for phrase, f in _TARGET_FIELDS if phrase in str(exc))
                return _row_error(i, field, f"Row {i + 1}: {exc}")
            target = {
                "distance_key": parsed.distance_key,
                "face_cm": parsed.face_cm,
                "face_type": parsed.face_type,
            }
        entries.append(
            {"name": values["name"], "bowstyle": values["bowstyle"], "handicap": handicap, "target": target}
        )

    updating = updating if isinstance(updating, dict) else {}
    update = advanced and updating.get("update_handicaps") in (True, "yes")
    n_lookback = start_weight = None
    if update:
        try:
            n_lookback = _whole_number(updating.get("n_lookback", ""), "Lookback")
        except ValueError as exc:
            return _row_error(None, "n_lookback", str(exc))
        try:
            start_weight = _whole_number(updating.get("start_weight", ""), "Start weight")
        except ValueError as exc:
            return _row_error(None, "start_weight", str(exc))

    new = copy.deepcopy(doc)
    new["setup"].update(stage=2, update_handicaps=update, n_lookback=n_lookback, start_weight=start_weight)
    new["archers"] = entries
    new["assignment"] = draw_assignment(schedule_for(setup), len(entries), random.Random(seed))
    new.update(scores={}, current_pass=0)
    return _ok({"document": new})


def redraw(doc: dict, seed: int) -> dict:
    """Draw the pairings again, preferring a draw whose pairings differ from the current ones.

    Parameters
    ----------
    doc : dict
        The event document; Stage 2 must be complete and the event not started.
    seed : int
        Seed of the draw.

    Returns
    -------
    dict
        Envelope whose data is `{"document": new document with the new assignment}`, or a
        `state` error.
    """
    if doc["status"] != SETUP:
        return _error(STATE, ALREADY_STARTED)
    if doc["setup"]["stage"] < 2:
        return _error(STATE, STAGE2_FIRST)
    if (refusal := _seed_error(seed)) is not None:
        return refusal
    new = copy.deepcopy(doc)
    new["assignment"] = draw_assignment(
        schedule_for(doc["setup"]), len(doc["archers"]), random.Random(seed), doc["assignment"]
    )
    return _ok({"document": new})


def pairings(doc: dict) -> dict:
    """Every pass's pairings for the current draw (Stage 3, and its read-only summary later).

    Parameters
    ----------
    doc : dict
        The event document; Stage 2 must be complete.

    Returns
    -------
    dict
        Envelope whose data is `{"passes": [{"pass_number": int, "matches": [{"a": name, "b":
        name | None (a bye: shoots alone)}], "sitting_out": [names]}], "started": bool}`, or a
        `state` error.
    """
    if doc["setup"]["stage"] < 2:
        return _error(STATE, STAGE2_FIRST)
    names = [doc["archers"][i]["name"] for i in doc["assignment"]]
    return _ok(
        {
            "passes": [
                {
                    "pass_number": i + 1,
                    "matches": [
                        {"a": names[a], "b": None if b is None else names[b]} for a, b in rotation.matches
                    ],
                    "sitting_out": [names[p] for p in rotation.sitting_out],
                }
                for i, rotation in enumerate(schedule_for(doc["setup"]))
            ],
            "started": doc["status"] != SETUP,
        }
    )


def start_event(doc: dict) -> dict:
    """Confirm the Stage 3 draw and start the event.

    Parameters
    ----------
    doc : dict
        The event document; Stage 2 must be complete and the event not started.

    Returns
    -------
    dict
        Envelope whose data is `{"document": new document, status "running", stage 3}`, or a
        `state` error.
    """
    if doc["status"] != SETUP:
        return _error(STATE, ALREADY_STARTED)
    if doc["setup"]["stage"] < 1:
        return _error(STATE, STAGE1_BEFORE_START)
    if doc["setup"]["stage"] < 2:
        return _error(STATE, STAGE2_FIRST)
    new = copy.deepcopy(doc)
    new["status"] = RUNNING
    new["setup"]["stage"] = 3
    return _ok({"document": new})


def _not_started(doc: dict) -> dict | None:
    """Check that the event has started (Stage 3 confirmed).

    Parameters
    ----------
    doc : dict
        The event document.

    Returns
    -------
    dict | None
        A `state` error envelope while the status is "setup", otherwise None.
    """
    return _error(STATE, NOT_STARTED) if doc["status"] == SETUP else None


def _match_index_error(event: Event, match_index: object) -> dict | None:
    """Check a match index against the current pass.

    Parameters
    ----------
    event : h2h.models.Event
        The rebuilt event.
    match_index : object
        The index supplied by the caller.

    Returns
    -------
    dict | None
        A `validation` error envelope if it is not an int from 0 to the number of matches in
        the current pass minus one, otherwise None.
    """
    count = len(event.matches(event.current_rotation_index))
    if type(match_index) is not int or not 0 <= match_index < count:
        pass_number = event.current_rotation_index + 1
        return _error(VALIDATION, f"Pass {pass_number} has matches 0 to {count - 1}, not {match_index!r}.")
    return None


def overview(doc: dict) -> dict:
    """The current pass: every match with its status and results, as the overview shows them.

    Parameters
    ----------
    doc : dict
        The event document; the event must have started.

    Returns
    -------
    dict
        Envelope whose data has `pass_index`, `pass_number`, `n_passes`, `n_pass` (arrows per
        pass), `matches` (per match: `index`, `names` (one for a bye), `bye`, `scored`, and the
        text `score` ("100 - 98"), `percentiles` ("52.1% - 48.0%") and `winner` (a name),
        each "-" while unscored; `winner` is "-" for a bye), `sitting_out` (names),
        `scored_count`, `match_count`, `pass_complete`, `is_last` and `event_complete`; or a
        `state` error.
    """
    if (refusal := _not_started(doc)) is not None:
        return refusal
    event = rebuild_event(doc)
    idx = event.current_rotation_index
    matches = []
    for i, (a, b) in enumerate(event.matches(idx)):
        results = event.match_results(idx, (a, b))
        rows = outputs.pass_table_rows(event, results)
        scored = bool(results)
        winner = "-"
        if scored and b is not None:
            winner = event.archers[a if results[0].won else b].name
        matches.append(
            {
                "index": i,
                "names": [event.archers[p].name for p in (a, b) if p is not None],
                "bye": b is None,
                "scored": scored,
                "score": " - ".join(row.score for row in rows) if scored else "-",
                "percentiles": " - ".join(row.percentile for row in rows) if scored else "-",
                "winner": winner,
            }
        )
    return _ok(
        {
            "pass_index": idx,
            "pass_number": idx + 1,
            "n_passes": len(event.schedule),
            "n_pass": event.n_pass,
            "matches": matches,
            "sitting_out": [event.archers[p].name for p in event.schedule[idx].sitting_out],
            "scored_count": sum(m["scored"] for m in matches),
            "match_count": len(matches),
            "pass_complete": event.is_rotation_complete(idx),
            "is_last": idx == len(event.schedule) - 1,
            "event_complete": event.is_complete,
        }
    )


def _match_view(event: Event, match_index: int) -> dict:
    """One match of the current pass, as the match page shows it.

    Parameters
    ----------
    event : h2h.models.Event
        The rebuilt event.
    match_index : int
        A valid match index of the current pass.

    Returns
    -------
    dict
        `pass_index`, `pass_number`, `n_passes`, `match_index`, `bye`, `archers` (per archer
        in match order: `position`, `name`, `max_score`, saved `score` or None), `scored`,
        `rows` (the "This pass" table: `outputs.PassTableRow` fields as text),
        `show_start_handicap` (handicaps are updated), `decided_by_closest` (the saved result
        was decided by the tie-break, so the control stays shown), `closest` (the position it
        was decided for, or None), `next_unscored_match` (the next unscored match after this
        one, wrapping round, or None), `pass_complete` and `event_complete`.
    """
    idx = event.current_rotation_index
    matches = event.matches(idx)
    a, b = matches[match_index]
    results = event.match_results(idx, (a, b))
    saved = {r.archer_index: r.score for r in results}
    later_first = [*range(match_index + 1, len(matches)), *range(match_index)]
    return {
        "pass_index": idx,
        "pass_number": idx + 1,
        "n_passes": len(event.schedule),
        "match_index": match_index,
        "bye": b is None,
        "archers": [
            {
                "position": p,
                "name": event.archers[p].name,
                "max_score": event.max_score_for(p),
                "score": saved.get(p),
            }
            for p in (a, b)
            if p is not None
        ],
        "scored": bool(results),
        "rows": [asdict(row) for row in outputs.pass_table_rows(event, results)],
        "show_start_handicap": event.update_handicaps,
        "decided_by_closest": any(r.decided_by == "closest" for r in results),
        "closest": next((r.archer_index for r in results if r.won and r.decided_by == "closest"), None),
        "next_unscored_match": next((i for i in later_first if not event.is_match_scored(idx, i)), None),
        "pass_complete": event.is_rotation_complete(idx),
        "event_complete": event.is_complete,
    }


def match(doc: dict, match_index: int) -> dict:
    """One match of the current pass (see `_match_view` for the data).

    Parameters
    ----------
    doc : dict
        The event document; the event must have started.
    match_index : int
        The match's position in the current pass (pairs first, then any bye match).

    Returns
    -------
    dict
        Envelope whose data is the match view, or a `state` or `validation` error.
    """
    if (refusal := _not_started(doc)) is not None:
        return refusal
    event = rebuild_event(doc)
    if (refusal := _match_index_error(event, match_index)) is not None:
        return refusal
    return _ok(_match_view(event, match_index))


def record_match(doc: dict, match_index: int, scores: dict, closest: int | None = None) -> dict:
    """Save one match of the current pass, replacing any scores saved for it before.

    Reads the scores as the Flask route `event_match_submit` did (same messages). The status
    becomes "complete" when the event is complete, and stays so when a final-pass match is
    saved again (decision D11). Nothing is changed when the save is refused.

    Parameters
    ----------
    doc : dict
        The event document; the event must have started.
    match_index : int
        The match's position in the current pass.
    scores : dict
        Schedule position (as text, the JSON key) -> score (text or number), for each archer
        in the match.
    closest : int | None, default=None
        The position of the archer whose arrow was closest to the middle; used only when the
        percentile and the score are both tied, and stored only then.

    Returns
    -------
    dict
        Envelope whose data is `{"document": new document, "match": the match view}`; or a
        `tiebreak_required` error (the scores tie and `closest` is None); or a `validation`
        error (a score that is not a number or out of range, or `closest` not in the match);
        or a `state` error.
    """
    if (refusal := _not_started(doc)) is not None:
        return refusal
    event = rebuild_event(doc)
    if (refusal := _match_index_error(event, match_index)) is not None:
        return refusal
    idx = event.current_rotation_index
    archers = [p for p in event.matches(idx)[match_index] if p is not None]
    scores = scores if isinstance(scores, dict) else {}
    try:
        chosen = None
        if len(archers) == 2 and closest is not None:
            if closest not in archers or type(closest) is not int:
                msg = "The archer closest to the middle must be one of the two in this match."
                raise ValueError(msg)
            chosen = closest
        values = {}
        for p in archers:
            try:
                values[p] = float(str(scores.get(str(p), "")))
            except ValueError:
                msg = f"{event.archers[p].name}'s score must be a number."
                raise ValueError(msg) from None
        results = event.record_match(values, closest=chosen)
    except stats.TieBreakRequired:
        return _error(TIEBREAK_REQUIRED, TIEBREAK_MESSAGE)
    except ValueError as exc:
        return _error(VALIDATION, str(exc))

    new = copy.deepcopy(doc)
    new["scores"].setdefault(str(idx), {})[str(match_index)] = {
        "scores": {str(r.archer_index): r.score for r in results},
        "closest": chosen if results[0].decided_by == "closest" else None,
    }
    new["status"] = COMPLETE if event.is_complete else RUNNING
    return _ok({"document": new, "match": _match_view(event, match_index)})


def advance(doc: dict) -> dict:
    """Move on to the next pass, once every match in the current one is scored.

    Parameters
    ----------
    doc : dict
        The event document; the event must have started.

    Returns
    -------
    dict
        Envelope whose data is `{"document": new document on the next pass}`, or a `state`
        error (the event has not started, the pass has unscored matches, or it is the final
        pass; the last two with the core's message).
    """
    if (refusal := _not_started(doc)) is not None:
        return refusal
    event = rebuild_event(doc)
    try:
        event.advance()
    except ValueError as exc:
        return _error(STATE, str(exc))
    new = copy.deepcopy(doc)
    new["current_pass"] = event.current_rotation_index
    return _ok({"document": new})


def results(doc: dict) -> dict:
    """The Results view: leaderboard, pairwise results and the per-pass tables.

    Parameters
    ----------
    doc : dict
        The event document; the event must have started.

    Returns
    -------
    dict
        Envelope whose data has `leaderboard` (per row: `archer_index` and the text `rank`,
        `name`, `points`, `passes_decided`, `starting_handicap` (as entered),
        `to_date_handicap` (one place or "-")), `pairwise` (per pair: `archer_a`, `archer_b`,
        `name_a`, `name_b`, text `wins_a`, `wins_b`, `draw` and `result` ("Draw" or
        "<name> wins")), `passes` (each pass with any scored match: `pass_index`,
        `pass_number`, `groups`, one list of pass-table rows per scored match), and
        `completed_passes`, `n_passes`, `current_pass_number`, `event_complete`,
        `show_start_handicap`; or a `state` error.
    """
    if (refusal := _not_started(doc)) is not None:
        return refusal
    event = rebuild_event(doc)
    pairwise = []
    for pr in event.all_pairwise_results():
        draw = pr.outcome == "draw"
        pairwise.append(
            {
                "archer_a": pr.archer_a,
                "archer_b": pr.archer_b,
                "name_a": event.archers[pr.archer_a].name,
                "name_b": event.archers[pr.archer_b].name,
                "wins_a": str(pr.wins_a),
                "wins_b": str(pr.wins_b),
                "draw": draw,
                "result": "Draw" if draw else f"{event.archers[pr.outcome].name} wins",
            }
        )
    passes = []
    for idx in range(len(event.schedule)):
        groups = [
            [asdict(row) for row in outputs.pass_table_rows(event, found)]
            for found in (event.match_results(idx, m) for m in event.matches(idx))
            if found
        ]
        if groups:
            passes.append({"pass_index": idx, "pass_number": idx + 1, "groups": groups})
    return _ok(
        {
            "leaderboard": [
                {
                    "archer_index": row.archer_index,
                    "rank": str(row.rank),
                    "name": row.name,
                    "points": str(row.points),
                    "passes_decided": str(row.passes_decided),
                    "starting_handicap": f"{row.starting_handicap:g}",
                    "to_date_handicap": _one_place(row.to_date_handicap),
                }
                for row in outputs.leaderboard(event)
            ],
            "pairwise": pairwise,
            "passes": passes,
            "completed_passes": len(event.completed_passes),
            "n_passes": len(event.schedule),
            "current_pass_number": event.current_rotation_index + 1,
            "event_complete": event.is_complete,
            "show_start_handicap": event.update_handicaps,
        }
    )


def archer_results(doc: dict) -> dict:
    """Every archer's section of the Archer results, over the completed passes.

    Parameters
    ----------
    doc : dict
        The event document; the event must have started.

    Returns
    -------
    dict
        Envelope whose data has `sections` (per archer: `archer_index`, `name`, and the text
        `total_score`, `starting_handicap`, `to_date_handicap`, `rows` (`pass_number`,
        `opponent` ("bye" for a bye), `score`, `percentile` ("59.8%"), `start_handicap`,
        `handicap`) and `average` (`score`, `percentile`, `start_handicap`, `handicap`, or None
        with no rows)), and `completed_passes`, `n_passes`, `show_start_handicap`; or a `state`
        error.
    """
    if (refusal := _not_started(doc)) is not None:
        return refusal
    event = rebuild_event(doc)
    sections = []
    for section in outputs.archer_results(event):
        averages = section.averages
        sections.append(
            {
                "archer_index": section.archer_index,
                "name": section.name,
                "total_score": str(section.total_score),
                "starting_handicap": f"{section.handicap:g}",
                "to_date_handicap": _one_place(section.to_date_handicap),
                "rows": [
                    {
                        "pass_number": str(row.pass_number),
                        "opponent": row.opponent,
                        "score": str(row.score),
                        "percentile": f"{row.percentile * 100:.1f}%",
                        "start_handicap": f"{row.start_handicap:.1f}",
                        "handicap": _one_place(row.handicap),
                    }
                    for row in section.rows
                ],
                "average": None
                if averages is None
                else {
                    "score": f"{averages.score:.1f}",
                    "percentile": f"{averages.percentile * 100:.1f}%",
                    "start_handicap": f"{averages.start_handicap:.1f}",
                    "handicap": _one_place(averages.handicap),
                },
            }
        )
    return _ok(
        {
            "sections": sections,
            "completed_passes": len(event.completed_passes),
            "n_passes": len(event.schedule),
            "show_start_handicap": event.update_handicaps,
        }
    )


def pair_chart(doc: dict, a: int, b: int) -> dict:
    """The distribution chart payload for two archers (`chart_data.build_pair_chart_data`).

    Parameters
    ----------
    doc : dict
        The event document; the event must have started.
    a, b : int
        Two different schedule positions. They need not have met yet (the match view charts
        the pair before their first scored pass).

    Returns
    -------
    dict
        Envelope whose data is the chart payload, or a `validation` or `state` error.
    """
    if (refusal := _not_started(doc)) is not None:
        return refusal
    event = rebuild_event(doc)
    n = len(event.archers)
    if type(a) is not int or type(b) is not int or not (0 <= a < n and 0 <= b < n) or a == b:
        return _error(VALIDATION, f"Choose two different archers from 0 to {n - 1}.")
    return _ok(chart_data.build_pair_chart_data(event, a, b))


def export(doc: dict, kind: str, now_iso: str) -> dict:
    """A file download: the leaderboard CSV, the archer results CSV or the full PDF report.

    Parameters
    ----------
    doc : dict
        The event document; the event must have started.
    kind : str
        "leaderboard_csv", "archer_results_csv" or "results_pdf".
    now_iso : str
        The export time from the browser, ISO-8601 in the user's local time. Its clock time is
        used as written (any UTC offset is dropped, not converted), since the exports show
        local time.

    Returns
    -------
    dict
        Envelope whose data is `{"filename", "mime_type", "encoding": "utf-8" | "base64",
        "content"}` (CSV text, or the PDF bytes in base64), with the Flask app's file names
        (e.g. "leaderboard_20261004-153012.csv"); or a `validation` or `state` error.
    """
    if (refusal := _not_started(doc)) is not None:
        return refusal
    try:
        now = datetime.fromisoformat(now_iso).replace(tzinfo=None)
    except (TypeError, ValueError):
        return _error(VALIDATION, "now_iso must be an ISO-8601 date and time.")
    event = rebuild_event(doc)
    stamp = exports.filename_stamp(now)
    if kind == "leaderboard_csv":
        name, mime, content = f"leaderboard_{stamp}.csv", "text/csv", exports.leaderboard_csv(event, now)
    elif kind == "archer_results_csv":
        name, mime, content = f"archer-results_{stamp}.csv", "text/csv", exports.archer_results_csv(event, now)
    elif kind == "results_pdf":
        pdf = exports.results_pdf(event, now)
        return _ok(
            {
                "filename": f"results_{stamp}.pdf",
                "mime_type": "application/pdf",
                "encoding": "base64",
                "content": base64.b64encode(pdf).decode("ascii"),
            }
        )
    else:
        return _error(
            VALIDATION, f"Unknown export {kind!r}: choose leaderboard_csv, archer_results_csv or results_pdf."
        )
    return _ok({"filename": name, "mime_type": mime, "encoding": "utf-8", "content": content})


def calculator(kind: str, round_codename: str, compound: bool, score: object) -> dict:
    """The score-to-handicap calculator (nothing is stored).

    Reads the choice as the Flask route `handicap_calculator_submit` did, with the same
    messages.

    Parameters
    ----------
    kind : str
        "indoor" or "outdoor".
    round_codename : str
        The archeryutils codename of one of that kind's rounds (from `options`).
    compound : bool
        Shot with a compound bow (true or "yes"; only changes indoor rounds that have a
        compound variant).
    score : object
        The full-round score, as text or a number.

    Returns
    -------
    dict
        Envelope whose data is `{"handicap": float rounded to 1 decimal place, "text": the
        handicap as the page showed it}`, or a `validation` error.
    """
    try:
        rnd = calculator_round(kind, round_codename, compound=compound in (True, "yes"))
    except ValueError as exc:
        return _error(VALIDATION, str(exc))
    try:
        value = float(str(score))
        if not math.isfinite(value):  # "nan" and "inf" parse as floats but are not scores
            raise ValueError(score)
        handicap = stats.handicap_for_round_score(value, rnd)
    except ValueError:
        return _error(VALIDATION, "Enter a valid score for the chosen round.")
    rounded = round(handicap, 1)
    return _ok({"handicap": rounded, "text": str(rounded)})


_COMMANDS = {
    "options": options,
    "new_document": new_document,
    "apply_stage1": apply_stage1,
    "apply_stage2": apply_stage2,
    "redraw": redraw,
    "pairings": pairings,
    "start_event": start_event,
    "overview": overview,
    "match": match,
    "record_match": record_match,
    "advance": advance,
    "results": results,
    "archer_results": archer_results,
    "pair_chart": pair_chart,
    "export": export,
    "calculator": calculator,
    "validate_document": validate_document,
}


def call(command: str, payload_json: str) -> str:
    """Run one command for the browser: JSON text in, JSON text out (UISpec.md 5.1).

    Parameters
    ----------
    command : str
        A command name, e.g. "record_match".
    payload_json : str
        JSON object of the command's keyword arguments, e.g. `{"doc": {...}, "match_index": 0,
        "scores": {"0": 100, "3": 98}, "closest": null}`.

    Returns
    -------
    str
        The command's envelope as JSON (NaN and infinity refused). Anything unexpected (an
        unknown command, malformed arguments, a bug) becomes an `internal` error rather than
        an exception, so the UI always receives an envelope.
    """
    if command not in _COMMANDS:
        return json.dumps(_error(INTERNAL, f"Unknown command {command!r}."))
    try:
        payload = json.loads(payload_json)
        return json.dumps(_COMMANDS[command](**payload), allow_nan=False)
    except Exception as exc:  # noqa: BLE001 - every failure must reach the UI as an envelope
        return json.dumps(_error(INTERNAL, f"{command} failed: {type(exc).__name__}: {exc}"))
