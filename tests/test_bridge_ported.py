"""Bridge-level ports of the Flask route tests (tests/test_event_routes.py and tests/test_integration.py).

Each test drives an event through the `h2h.bridge` commands, as the browser UI does, and checks
the rule or value the Flask pages checked: validation messages, the tie-break, advancing, byes
and sit-outs, simple and advanced setup, handicap updating, the results views and the exports.
Page layout, links, redirects, templates and the Flask session are left to the UI.

The Flask tests drew with `NoShuffle`, so positions were the entry order; `_stage2` does the
same by setting the document's assignment to the identity permutation before the start.
"""

import base64
import copy
import csv
import io
import re
from collections import Counter

import pypdf
import pytest
from archeryutils import rounds as au_rounds

from h2h import bridge, outputs, stats
from h2h.outputs import percentile_pair_text

NOW = "2026-10-04T15:30:12"  # the export time used throughout
STAMP = "2026-10-04 15:30:12"  # NOW as the exports show it
SEED = 0

ADVANCE_UNSCORED = "Every match in the current pass must have scores before advancing."
ADVANCE_FINAL = "This is the final pass; there is no next pass to advance to."
CLOSEST_OUTSIDE = "The archer closest to the middle must be one of the two in this match."

TWO_ARCHERS = [("Alice", "Recurve", 15), ("Bob", "Compound", 45)]
THREE_ARCHERS = [("Alice", "Recurve", 15), ("Bob", "Compound", 45), ("Carol", "Barebow", 30)]
FOUR_ARCHERS = [("A1", "Recurve", 15), ("A2", "Compound", 25), ("A3", "Barebow", 35), ("A4", "Longbow", 45)]
NAMED_FOUR = [(name, "Recurve", 20 + 10 * i) for i, name in enumerate(("Ann", "Ben", "Cat", "Dan"))]
TIED_PAIR = [("Ann", "Recurve", 30), ("Ben", "Recurve", 30)]  # equal scores tie exactly
SAME_HANDICAP_BOWS = [("Rec", "Recurve", 20), ("Comp", "Compound", 20), ("Bare", "Barebow", 20), ("Long", "Longbow", 20)]
# name, bowstyle, handicap, face type, face size, distance
ADVANCED_FOUR = [
    ("Ann", "Recurve", 20, "10_zone", 40, "18m"),
    ("Ben", "Compound", 25, "10_zone_compound", 40, "18m"),
    ("Cat", "Barebow", 35, "5_zone", 122, "50yd"),
    ("Dan", "Longbow", 45, "Worcester", 40, "20yd"),
]
TWO_ADVANCED = [("Ann", "Recurve", 30, "10_zone", 60, "20yd"), ("Ben", "Recurve", 40, "10_zone", 60, "20yd")]
FIVE_AND_TEN_ZONE = [("Fiver", "Recurve", 30, "5_zone", 60, "20yd"), ("Tenner", "Recurve", 30, "10_zone", 60, "20yd")]
UPDATING = {"update_handicaps": "yes", "n_lookback": "1", "start_weight": "2"}


# --- Helpers -----------------------------------------------------------------------------------


def _data(envelope):
    """The data of a successful bridge envelope.

    Parameters
    ----------
    envelope : dict
        A command's result.

    Returns
    -------
    object
        `envelope["data"]`, after asserting that the command succeeded.
    """
    assert envelope["ok"] is True, envelope
    return envelope["data"]


def _refusal(envelope, code):
    """The message of a refused bridge envelope, after checking its error code.

    Parameters
    ----------
    envelope : dict
        A command's result.
    code : str
        The expected error code: "validation", "tiebreak_required" or "state".

    Returns
    -------
    str
        The error message.
    """
    assert envelope["ok"] is False, envelope
    assert envelope["error"]["code"] == code, envelope
    return envelope["error"]["message"]


def _fresh():
    """A new event document (nothing submitted yet).

    Returns
    -------
    dict
        The document from `bridge.new_document`.
    """
    return _data(bridge.new_document("e1", NOW))


def _form(n_archers=4, total_arrows=60, n_pass=12, distance="20yd", face_cm=60, setup_mode="simple", **extra):
    """A Stage 1 form as the UI sends it (text values, like the Flask form).

    Parameters
    ----------
    n_archers, total_arrows, n_pass : int | str
        The event size.
    distance : str, default="20yd"
        The shared distance key (simple setup).
    face_cm : int | str, default=60
        The shared face size in cm (simple setup).
    setup_mode : str, default="simple"
        "simple" or "advanced".
    **extra
        Further fields, e.g. `shoot_byes="no"`.

    Returns
    -------
    dict
        The form values.
    """
    return {
        "n_archers": str(n_archers),
        "total_arrows": str(total_arrows),
        "n_pass": str(n_pass),
        "setup_mode": setup_mode,
        "distance": distance,
        "face_cm": str(face_cm),
        **extra,
    }


def _stage1(**form):
    """A fresh document with Stage 1 submitted.

    Parameters
    ----------
    **form
        Keyword arguments of `_form`.

    Returns
    -------
    dict
        The document at stage 1.
    """
    return _data(bridge.apply_stage1(_fresh(), _form(**form)))["document"]


def _rows(archers):
    """Stage 2 rows from archer tuples, values as text like the Flask form.

    Parameters
    ----------
    archers : list[tuple]
        `(name, bowstyle, handicap)` per archer, plus `(face_type, face_cm, distance)` for
        advanced setup.

    Returns
    -------
    list[dict]
        One row per archer with the keys `apply_stage2` reads.
    """
    keys = ("name", "bowstyle", "handicap", "face_type", "face_cm", "distance")
    return [{key: str(value) for key, value in zip(keys, archer)} for archer in archers]


def _stage2(archers, updating=None, **form):
    """A document with Stages 1 and 2 submitted and the draw set to the entry order.

    Parameters
    ----------
    archers : list[tuple]
        The archers, as `_rows` takes them.
    updating : dict | None, default=None
        The Stage 2 handicap-updating fields; none by default.
    **form
        Further Stage 1 fields for `_form` (`n_archers` comes from `archers`).

    Returns
    -------
    dict
        The document at stage 2, whose assignment keeps the entry order (as `NoShuffle` did).
    """
    doc = _stage1(n_archers=len(archers), **form)
    doc = _data(bridge.apply_stage2(doc, _rows(archers), updating or {}, SEED))["document"]
    doc["assignment"] = list(range(len(archers)))
    return doc


def _start(archers, updating=None, **form):
    """A started event whose schedule positions are the entry order.

    Parameters
    ----------
    archers : list[tuple]
        The archers, as `_rows` takes them.
    updating : dict | None, default=None
        The Stage 2 handicap-updating fields.
    **form
        Further Stage 1 fields for `_form`.

    Returns
    -------
    dict
        The running document on pass 1.
    """
    return _data(bridge.start_event(_stage2(archers, updating, **form)))["document"]


def _record(doc, match_index, scores, closest=None):
    """Run `record_match` with scores keyed by position.

    Parameters
    ----------
    doc : dict
        A running event document.
    match_index : int
        The match's index in the current pass.
    scores : dict[int, int | str]
        Schedule position -> score (text or number).
    closest : object, default=None
        The closest-to-the-middle archer, passed through unchanged.

    Returns
    -------
    dict
        The command's envelope.
    """
    return bridge.record_match(doc, match_index, {str(p): s for p, s in scores.items()}, closest)


def _save(doc, match_index, scores, closest=None):
    """Save a match that must be accepted.

    Parameters
    ----------
    doc, match_index, scores, closest
        As for `_record`.

    Returns
    -------
    dict
        The new document.
    """
    return _data(_record(doc, match_index, scores, closest))["document"]


def _advance(doc):
    """Advance to the next pass, which must be allowed.

    Parameters
    ----------
    doc : dict
        A running event document.

    Returns
    -------
    dict
        The new document.
    """
    return _data(bridge.advance(doc))["document"]


def _score_pass(doc, score_fn=lambda position: 60):
    """Save every match of the current pass, finding each match's archers from the match view.

    A tie is broken for the lower position, as the Flask helper `save_match_breaking_ties` did.

    Parameters
    ----------
    doc : dict
        A running event document.
    score_fn : callable(int) -> int, default=lambda position: 60
        The score to enter for an archer, by schedule position.

    Returns
    -------
    dict
        The new document.
    """
    for match_index in range(_data(bridge.overview(doc))["match_count"]):
        positions = [a["position"] for a in _data(bridge.match(doc, match_index))["archers"]]
        scores = {p: score_fn(p) for p in positions}
        result = _record(doc, match_index, scores)
        if not result["ok"] and result["error"]["code"] == bridge.TIEBREAK_REQUIRED:
            result = _record(doc, match_index, scores, min(scores))
        doc = _data(result)["document"]
    return doc


def _play(doc, score_fn=lambda position, pass_index: 60):
    """Score every remaining pass, advancing between passes.

    Parameters
    ----------
    doc : dict
        A running event document.
    score_fn : callable(int, int) -> int, default=lambda position, pass_index: 60
        The score to enter, by schedule position and 0-based pass index.

    Returns
    -------
    dict
        The completed document.
    """
    n_passes = _data(bridge.overview(doc))["n_passes"]
    for pass_index in range(doc["current_pass"], n_passes):
        doc = _score_pass(doc, lambda p, i=pass_index: score_fn(p, i))
        if pass_index < n_passes - 1:
            doc = _advance(doc)
    return doc


def _csv(doc, kind):
    """The rows of a CSV export, parsed as a spreadsheet would.

    Parameters
    ----------
    doc : dict
        A running event document.
    kind : str
        "leaderboard_csv" or "archer_results_csv".

    Returns
    -------
    list[list[str]]
        The header row, then the data rows.
    """
    return list(csv.reader(io.StringIO(_data(bridge.export(doc, kind, NOW))["content"], newline="")))


def _pdf_text(doc):
    """The text of the PDF export, whitespace collapsed.

    Parameters
    ----------
    doc : dict
        A running event document.

    Returns
    -------
    str
        Every page's extracted text, joined with single spaces.
    """
    pdf = base64.b64decode(_data(bridge.export(doc, "results_pdf", NOW))["content"])
    return " ".join("\n".join(page.extract_text() for page in pypdf.PdfReader(io.BytesIO(pdf)).pages).split())


def _event(doc):
    """The core event a document describes (to compare the views with the core's own values).

    Parameters
    ----------
    doc : dict
        A running event document.

    Returns
    -------
    h2h.models.Event
        `bridge.rebuild_event(doc)`.
    """
    return bridge.rebuild_event(doc)


# --- The forms' choices and defaults ------------------------------------------------------------


def test_the_options_are_the_flask_forms_choices_and_defaults():
    """The distance, face size, face type and bowstyle choices, the handicap range and the defaults the Flask forms offered."""
    # ports test_event_routes.py::test_stage1_distance_dropdown_has_exactly_the_standard_options_grouped
    # ports test_event_routes.py::test_stage1_face_size_dropdown_has_the_four_standard_faces
    # ports test_event_routes.py::test_advanced_stage_2_has_three_dropdowns_per_archer_with_the_right_options_and_defaults
    # ports test_event_routes.py::test_stage2_dropdown_offers_longbow_in_every_row
    # ports test_event_routes.py::test_stage2_handicap_inputs_carry_the_range_as_min_and_max
    # ports test_event_routes.py::test_stage1_has_setup_mode_toggle_with_simple_selected_by_default (the default)
    # ports test_event_routes.py::test_shoot_byes_control_defaults_to_yes (the default)
    data = _data(bridge.options())
    groups = data["distance_groups"]
    assert [g["group"] for g in groups] == ["Metric", "Imperial"]
    assert [item["value"] for g in groups for item in g["items"]] == [
        "18m", "25m", "30m", "40m", "50m", "60m", "70m", "90m",
        "20yd", "25yd", "30yd", "40yd", "50yd", "60yd", "80yd", "100yd",
    ]
    assert (groups[0]["items"][0]["label"], groups[1]["items"][-1]["label"]) == ("18 m", "100 yd")
    assert data["face_sizes"] == [40, 60, 80, 122]
    assert data["advanced_face_sizes"] == [20, 35, 40, 50, 60, 65, 80, 122]
    assert len(data["face_types"]) == 16
    assert data["face_types"][0] == {"value": "10_zone", "label": "10 zone (standard 10-ring face)"}
    assert data["bowstyles"] == ["Recurve", "Compound", "Barebow", "Longbow"]
    assert (data["min_handicap"], data["max_handicap"]) == (0, 150)
    defaults = data["defaults"]
    assert (defaults["setup_mode"], defaults["shoot_byes"]) == ("simple", True)
    assert (defaults["distance_key"], defaults["face_cm"], defaults["face_type"]) == ("20yd", 60, "10_zone")


# --- Stage 1 -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("total_arrows", "n_pass", "accepted"),
    [(60, 7, False), (40, 8, True), (40, 12, False), (60, 12, True)],
)
def test_arrows_per_pass_must_divide_the_total_arrows(total_arrows, n_pass, accepted):
    """Stage 1 accepts arrows per pass only when they divide the total arrows."""
    # ports test_event_routes.py::test_valid_stage1_submission_redirects_to_stage2
    # ports test_event_routes.py::test_n_pass_not_dividing_total_arrows_rejected
    # ports test_event_routes.py::test_changing_total_arrows_changes_accepted_n_pass
    result =bridge.apply_stage1(_fresh(), _form(total_arrows=total_arrows, n_pass=n_pass))
    if accepted:
        assert _data(result)["passes_per_archer"] == total_arrows // n_pass
    else:
        message = _refusal(result, "validation")
        assert message == f"Arrows per pass ({n_pass}) must evenly divide total arrows ({total_arrows})."


@pytest.mark.parametrize("setup_mode", ["simple", "advanced"])
def test_fewer_than_two_archers_is_rejected(setup_mode):
    """n_archers below 2 is refused with the existing message in either setup mode."""
    # ports test_event_routes.py::test_n_archers_below_two_rejected
    # ports test_event_routes.py::test_a_rejected_stage_1_keeps_the_mode_that_was_posted (the message)
    result = bridge.apply_stage1(_fresh(), _form(n_archers=1, setup_mode=setup_mode))
    assert _refusal(result, "validation") == "Need at least 2 archers, got 1."


@pytest.mark.parametrize(("distance", "face_cm"), [("50m", 80), ("70m", 122)])
def test_a_simple_setup_stores_the_chosen_target(distance, face_cm):
    """Stage 1 stores the shared distance and face, outdoor ones included."""
    # ports test_event_routes.py::test_posting_a_simple_setup_stores_it_and_it_is_remembered_on_return
    # ports test_event_routes.py::test_an_outdoor_distance_is_accepted_like_any_other
    doc = _stage1(distance=distance, face_cm=face_cm)
    assert doc["setup"]["stage"] == 1
    assert doc["setup"]["target"] == {"distance_key": distance, "face_cm": face_cm}


@pytest.mark.parametrize(
    ("distance", "face_cm", "message"),
    [
        ("20m", 60, "'20m' is not one of the standard distances."),
        ("abc", 60, "'abc' is not one of the standard distances."),
        ("", 60, "'' is not one of the standard distances."),
        ("18m", 50, "'50' is not one of the standard face sizes."),
        ("18m", "abc", "'abc' is not one of the standard face sizes."),
    ],
)
def test_a_distance_or_face_outside_the_options_is_rejected_and_stores_nothing(distance, face_cm, message):
    """A forged distance or face gets the core's message and the document is left as it was."""
    # ports test_event_routes.py::test_a_distance_or_face_outside_the_options_is_rejected_and_stores_nothing
    doc = _fresh()
    before = copy.deepcopy(doc)
    result = bridge.apply_stage1(doc, _form(distance=distance, face_cm=face_cm))
    assert _refusal(result, "validation") == message
    assert doc == before


def test_an_unknown_setup_mode_is_rejected():
    """Only simple and advanced setup exist."""
    # ports test_event_routes.py::test_an_unknown_setup_mode_is_rejected_and_stores_nothing
    result = bridge.apply_stage1(_fresh(), _form(setup_mode="expert"))
    assert _refusal(result, "validation") == "Setup mode must be Simple or Advanced, got 'expert'."


def test_advanced_stage1_ignores_the_simple_fields_and_keeps_the_last_simple_target():
    """Advanced setup does not read the shared target fields and keeps the last simple choice."""
    # ports test_event_routes.py::test_posting_advanced_mode_goes_to_stage_2_and_keeps_the_last_simple_choice
    # ports test_event_routes.py::test_advanced_mode_ignores_the_hidden_simple_dropdowns
    doc = _stage1(distance="50m", face_cm=80)
    form = _form(n_archers=6, total_arrows=36, distance="not-a-distance", face_cm="abc", setup_mode="advanced")
    data = _data(bridge.apply_stage1(doc, form))
    setup = data["document"]["setup"]
    assert (setup["stage"], setup["setup_mode"], setup["n_archers"], data["n_passes"]) == (1, "advanced", 6, 3)
    assert setup["target"] == {"distance_key": "50m", "face_cm": 80}


@pytest.mark.parametrize(
    ("n_archers", "shoot_byes", "stored", "n_passes", "sits_out"),
    [
        (5, "no", False, 7, True),  # 5 passes each: 6 round-robin passes plus a catch-up pass
        (5, "yes", True, 5, False),
        (5, None, True, 5, False),  # the field omitted: byes are shot
        (4, "no", False, 5, False),  # an even count has no byes, so the choice changes nothing
    ],
)
def test_the_shoot_byes_choice_and_the_schedule_it_builds(n_archers, shoot_byes, stored, n_passes, sits_out):
    """Not shooting byes with an odd archer count sits archers out and adds passes; otherwise the schedule has total_arrows // n_pass passes."""
    # ports test_event_routes.py::test_posting_shoot_byes_no_with_odd_archers_stores_false_and_longer_schedule
    # ports test_event_routes.py::test_posting_shoot_byes_yes_keeps_the_ordinary_schedule
    # ports test_event_routes.py::test_shoot_byes_field_is_ignored_for_even_archers
    extra = {} if shoot_byes is None else {"shoot_byes": shoot_byes}
    data = _data(bridge.apply_stage1(_fresh(), _form(n_archers=n_archers, **extra)))
    setup = data["document"]["setup"]
    assert setup["shoot_byes"] is stored
    assert data["n_passes"] == n_passes == len(bridge.schedule_for(setup))
    assert any(rotation.sitting_out for rotation in bridge.schedule_for(setup)) is sits_out


# --- Stage guards --------------------------------------------------------------------------------


def test_stage2_and_the_draw_need_the_earlier_stages():
    """Stage 2 needs Stage 1, and drawing, listing or starting needs Stage 2, each refused with code state."""
    # ports test_event_routes.py::test_stage2_without_stage1_redirects_to_stage1
    # ports test_event_routes.py::test_stage3_without_completing_stage2_redirects_back_to_setup
    fresh = _fresh()
    assert _refusal(bridge.apply_stage2(fresh, _rows(THREE_ARCHERS), {}, SEED), "state") == bridge.STAGE1_FIRST
    assert _refusal(bridge.start_event(fresh), "state") == bridge.STAGE1_BEFORE_START
    assert _refusal(bridge.redraw(fresh, SEED), "state") == bridge.STAGE2_FIRST
    assert _refusal(bridge.pairings(fresh), "state") == bridge.STAGE2_FIRST
    after_stage1 = _stage1(n_archers=3)
    for result in (bridge.start_event(after_stage1), bridge.redraw(after_stage1, SEED), bridge.pairings(after_stage1)):
        assert _refusal(result, "state") == bridge.STAGE2_FIRST


EVENT_COMMANDS = [
    ("overview", bridge.overview),
    ("match", lambda doc: bridge.match(doc, 0)),
    ("record_match", lambda doc: bridge.record_match(doc, 0, {"0": 100, "1": 60})),
    ("advance", bridge.advance),
    ("results", bridge.results),
    ("archer_results", bridge.archer_results),
    ("pair_chart", lambda doc: bridge.pair_chart(doc, 0, 1)),
    ("export", lambda doc: bridge.export(doc, "leaderboard_csv", NOW)),
]


@pytest.mark.parametrize("command", [c[1] for c in EVENT_COMMANDS], ids=[c[0] for c in EVENT_COMMANDS])
def test_event_commands_are_refused_before_the_event_starts(command):
    """With no started event (a fresh document, or one waiting at Stage 3) every event command is refused."""
    # ports test_event_routes.py::test_event_routes_redirect_to_stage1_without_an_event
    # ports test_event_routes.py::test_both_output_pages_redirect_to_stage_1_without_an_event
    # ports test_integration.py::test_fresh_app_state_sees_no_prior_event
    for doc in (_fresh(), _stage2(TWO_ARCHERS)):
        assert _refusal(command(doc), "state") == bridge.NOT_STARTED


def test_once_started_the_setup_can_no_longer_change():
    """After the start, Stage 1, Stage 2, redraw and start are refused and the document keeps its scores."""
    # ports test_event_routes.py::test_once_the_event_has_started_stage3_redirects_and_changes_nothing
    doc = _save(_start(FOUR_ARCHERS, total_arrows=36), 0, {0: 60, 3: 60})
    before = copy.deepcopy(doc)
    for result in (
        bridge.apply_stage1(doc, _form()),
        bridge.apply_stage2(doc, _rows(FOUR_ARCHERS), {}, SEED),
        bridge.redraw(doc, SEED),
        bridge.start_event(doc),
    ):
        assert _refusal(result, "state") == bridge.ALREADY_STARTED
    assert doc == before
    assert _data(bridge.overview(doc))["matches"][0]["scored"] is True


# --- Stage 2 -----------------------------------------------------------------------------------


def test_valid_stage2_stores_the_archers_and_draws_without_starting():
    """Valid rows (a Longbow archer included) are stored with a drawn assignment, and the event has not started."""
    # ports test_event_routes.py::test_valid_stage2_submission_goes_to_stage3_without_starting_the_event
    # ports test_event_routes.py::test_stage2_submission_with_longbow_archer_starts_event
    # ports test_event_routes.py::test_stage2_submission_redirects_to_stage3_and_draws_an_assignment
    archers = [("Ann", "Longbow", 40), ("Ben", "Recurve", 30), ("Cat", "Compound", 20.5), ("Dan", "Barebow", 0)]
    doc = _data(bridge.apply_stage2(_stage1(n_archers=4, total_arrows=36), _rows(archers), {}, SEED))["document"]
    assert (doc["status"], doc["setup"]["stage"], doc["scores"]) == ("setup", 2, {})
    assert [(a["name"], a["bowstyle"], a["handicap"]) for a in doc["archers"]] == [
        ("Ann", "Longbow", 40.0), ("Ben", "Recurve", 30.0), ("Cat", "Compound", 20.5), ("Dan", "Barebow", 0.0),
    ]
    assert sorted(doc["assignment"]) == [0, 1, 2, 3]


def test_stage2_reads_exactly_n_archers_rows():
    """Stage 2 takes one row per archer from Stage 1: a missing row is refused, an extra one ignored."""
    # ports test_event_routes.py::test_stage2_renders_exactly_n_archers_rows
    doc = _stage1(n_archers=5)
    rows = _rows([(name, "Recurve", 20) for name in ("Ann", "Ben", "Cat", "Dan", "Eve", "Fay")])
    short = bridge.apply_stage2(doc, rows[:4], {}, SEED)
    assert _refusal(short, "validation") == "Row 5: name, handicap, and bowstyle are all required."
    assert (short["error"]["row"], short["error"]["field"]) == (4, "name")
    stored = _data(bridge.apply_stage2(doc, rows, {}, SEED))["document"]["archers"]
    assert [a["name"] for a in stored] == ["Ann", "Ben", "Cat", "Dan", "Eve"]


@pytest.mark.parametrize(
    ("first_row", "field", "message"),
    [
        (("Alice", "", 20), "bowstyle", "Row 1: name, handicap, and bowstyle are all required."),
        (("Alice", "Recurve", ""), "handicap", "Row 1: name, handicap, and bowstyle are all required."),
        (("Alice", "Recurve", "abc"), "handicap", "Row 1: handicap must be a number."),
    ],
    ids=["missing-bowstyle", "missing-handicap", "text-handicap"],
)
def test_a_missing_or_non_numeric_value_is_rejected_naming_the_row(first_row, field, message):
    """Missing values and a non-numeric handicap keep their row-numbered messages, and nothing is stored."""
    # ports test_event_routes.py::test_stage2_missing_bowstyle_rejected
    # ports test_event_routes.py::test_non_numeric_and_missing_handicaps_keep_their_existing_messages
    doc = _stage1(n_archers=2)
    before = copy.deepcopy(doc)
    result = bridge.apply_stage2(doc, _rows([first_row, ("Bob", "Compound", 30)]), {}, SEED)
    assert _refusal(result, "validation") == message
    assert (result["error"]["row"], result["error"]["field"]) == (0, field)
    assert doc == before


@pytest.mark.parametrize("bad", ["-0.1", "-1", "150.1", "1000", "nan", "inf", "-inf"])
def test_an_out_of_range_handicap_is_rejected_naming_the_row_and_the_range(bad):
    """Handicaps outside 0-150 (and nan or infinity) are refused with the row and range, and nothing is drawn."""
    # ports test_event_routes.py::test_out_of_range_handicap_is_rejected_naming_the_row_and_the_range
    # ports test_event_routes.py::test_a_rejected_stage2_submission_draws_nothing_and_does_not_reach_stage3
    # ports test_integration.py::test_setup_flow_rejects_a_bad_handicap_then_redraws_then_confirms_the_shown_pairings (the refusal)
    doc = _stage1(n_archers=2)
    result = bridge.apply_stage2(doc, _rows([("Alice", "Recurve", 20), ("Bob", "Compound", bad)]), {}, SEED)
    assert _refusal(result, "validation") == f"Row 2: handicap must be between 0 and 150, got {bad}."
    assert (result["error"]["row"], result["error"]["field"]) == (1, "handicap")
    assert (doc["setup"]["stage"], doc["archers"], doc["assignment"]) == (1, [], None)


@pytest.mark.parametrize("good", ["0", "150", "22.5", "0.0", "149.9"])
def test_in_range_handicaps_including_the_boundaries_are_accepted(good):
    """0 and 150 themselves, and decimals, are valid starting handicaps."""
    # ports test_event_routes.py::test_in_range_handicaps_including_the_boundaries_are_accepted
    rows = _rows([("Alice", "Recurve", good), ("Bob", "Compound", 30)])
    doc = _data(bridge.apply_stage2(_stage1(n_archers=2), rows, {}, SEED))["document"]
    assert doc["archers"][0]["handicap"] == float(good)


def test_advanced_rows_give_each_archer_their_own_target():
    """Each row's face type, face size and distance become that archer's resolved target."""
    # ports test_event_routes.py::test_valid_advanced_rows_give_each_archer_their_own_target_through_stage_3
    doc = _stage2(ADVANCED_FOUR, setup_mode="advanced", total_arrows=36)
    assert [a["target"] for a in doc["archers"]] == [
        {"distance_key": distance, "face_cm": face_cm, "face_type": face_type}
        for _, _, _, face_type, face_cm, distance in ADVANCED_FOUR
    ]
    event = _event(_data(bridge.start_event(doc))["document"])
    targets = [event.target_for(i) for i in range(4)]
    assert [t.scoring_system for t in targets] == ["10_zone", "10_zone_compound", "5_zone", "Worcester"]
    assert [round(t.diameter * 100) for t in targets] == [40, 40, 122, 40]
    assert [round(t.distance, 3) for t in targets] == [18.0, 18.0, 45.72, 18.288]
    assert [t.indoor for t in targets] == [True, True, False, True]
    assert event.target_setup is None


@pytest.mark.parametrize(
    ("column", "bad", "field", "message"),
    [
        (5, "19m", "distance", "Row 3: '19m' is not one of the standard distances."),
        (4, "45", "face_cm", "Row 3: '45' is not one of the standard face sizes."),
        (3, "bogus", "face_type", "Row 3: 'bogus' is not one of the target face types."),
        (3, "Custom", "face_type", "Row 3: 'Custom' is not one of the target face types."),
    ],
)
def test_an_invalid_advanced_target_names_the_row_and_field_and_stores_nothing(column, bad, field, message):
    """A bad distance, face size or face type in row 3 is refused with 'Row 3: ...'."""
    # ports test_event_routes.py::test_an_invalid_target_value_names_the_row_stores_nothing_and_refills_the_form
    doc = _stage1(n_archers=4, total_arrows=36, setup_mode="advanced")
    archers = [list(row) for row in ADVANCED_FOUR]
    archers[2][column] = bad
    result = bridge.apply_stage2(doc, _rows(archers), {}, SEED)
    assert _refusal(result, "validation") == message
    assert (result["error"]["row"], result["error"]["field"]) == (2, field)
    assert (doc["archers"], doc["assignment"]) == ([], None)


def test_a_missing_advanced_target_is_rejected_not_defaulted():
    """Advanced rows without the per-archer target fields are refused rather than guessed."""
    # ports test_event_routes.py::test_a_missing_advanced_field_is_rejected_not_defaulted
    doc = _stage1(n_archers=2, total_arrows=24, setup_mode="advanced")
    result = bridge.apply_stage2(doc, _rows([("Ann", "Recurve", 20), ("Ben", "Recurve", 30)]), {}, SEED)
    assert _refusal(result, "validation") == "Row 1: '' is not one of the standard distances."
    assert (result["error"]["row"], result["error"]["field"]) == (0, "distance")


def test_updating_on_stores_the_settings_and_the_handicaps_move_after_a_pass():
    """The event gets update_handicaps, n_lookback and start_weight, and the handicaps move after pass 1."""
    # ports test_event_routes.py::test_posting_yes_stores_the_settings_and_the_event_updates_handicaps
    updating = {"update_handicaps": "yes", "n_lookback": "2", "start_weight": "4"}
    doc = _start(TWO_ADVANCED, updating, setup_mode="advanced", total_arrows=36)
    setup = doc["setup"]
    assert (setup["update_handicaps"], setup["n_lookback"], setup["start_weight"]) == (True, 2, 4)
    event = _event(doc)
    assert (event.update_handicaps, event.n_lookback, event.start_weight) == (True, 2, 4)
    assert event.handicap_for(0) == 30  # nothing shot yet
    event = _event(_advance(_save(doc, 0, {0: 80, 1: 100})))
    assert event.handicap_for(0) != 30 and event.handicap_for(1) != 40


@pytest.mark.parametrize(
    ("setup_mode", "update"),
    [("advanced", "no"), ("advanced", None), ("simple", "yes")],
    ids=["advanced-no", "advanced-omitted", "simple-forced-yes"],
)
def test_updating_stays_off_unless_chosen_in_advanced_setup(setup_mode, update):
    """No, an omitted choice, or a forced yes in simple setup keep constant handicaps and ignore the parameters."""
    # ports test_event_routes.py::test_posting_no_or_omitting_the_field_leaves_updating_off
    # ports test_event_routes.py::test_a_forced_updating_request_in_simple_setup_is_ignored
    archers = TWO_ADVANCED if setup_mode == "advanced" else [row[:3] for row in TWO_ADVANCED]
    updating = {"n_lookback": "abc", "start_weight": "0"}
    if update is not None:
        updating["update_handicaps"] = update
    doc = _start(archers, updating, setup_mode=setup_mode, total_arrows=36)
    setup = doc["setup"]
    assert (setup["update_handicaps"], setup["n_lookback"], setup["start_weight"]) == (False, None, None)
    event = _event(_advance(_save(doc, 0, {0: 80, 1: 100})))
    assert event.update_handicaps is False
    assert (event.handicap_for(0), event.handicap_for(1)) == (30, 40)


@pytest.mark.parametrize("bad", ["0", "-1", "2.5", "abc", ""])
@pytest.mark.parametrize("field", ["n_lookback", "start_weight"])
def test_invalid_updating_parameters_are_rejected(field, bad):
    """A lookback or start weight that is not a whole number of at least 1 is refused, and nothing is stored."""
    # ports test_event_routes.py::test_invalid_parameters_are_rejected_with_a_message_and_the_form_is_refilled
    # ports test_event_routes.py::test_a_custom_lookback_still_overrides_the_default_and_invalid_ones_are_still_rejected (the refusal)
    doc = _stage1(n_archers=2, total_arrows=36, setup_mode="advanced")
    before = copy.deepcopy(doc)
    updating = {"update_handicaps": "yes", "n_lookback": "2", "start_weight": "4", field: bad}
    result = bridge.apply_stage2(doc, _rows(TWO_ADVANCED), updating, SEED)
    label = "Lookback" if field == "n_lookback" else "Start weight"
    assert _refusal(result, "validation") == f"{label} must be a whole number of at least 1."
    assert (result["error"]["row"], result["error"]["field"]) == (None, field)
    assert doc == before


def test_a_custom_lookback_is_stored_and_a_new_stage1_clears_the_updating_settings():
    """A lookback other than the default is kept; submitting Stage 1 again clears the settings and the archers."""
    # ports test_event_routes.py::test_a_custom_lookback_still_overrides_the_default_and_invalid_ones_are_still_rejected
    # ports test_event_routes.py::test_reset_and_a_new_stage_1_clear_the_settings_and_the_defaults_follow_the_event_size
    doc = _stage2(TWO_ADVANCED, {**UPDATING, "start_weight": "5"}, setup_mode="advanced", total_arrows=60)
    assert (doc["setup"]["update_handicaps"], doc["setup"]["n_lookback"]) == (True, 1)
    again = _data(bridge.apply_stage1(doc, _form(n_archers=2, total_arrows=36, setup_mode="advanced")))
    setup = again["document"]["setup"]
    assert (setup["update_handicaps"], setup["n_lookback"], setup["start_weight"]) == (False, None, None)
    assert (again["document"]["archers"], again["document"]["assignment"]) == ([], None)
    assert again["passes_per_archer"] == 3  # the start weight default follows the event size


# --- Stage 3: the draw -------------------------------------------------------------------------

NAMES = ["Ann", "Ben", "Cat", "Dan", "Eve"]


def _drawn(n, total_arrows=36, shoot_byes=True, seed=SEED):
    """A document at Stage 3 with the bridge's own draw (not the entry order).

    Parameters
    ----------
    n : int
        Number of archers (named from `NAMES`).
    total_arrows : int, default=36
        Total arrows per archer (12-arrow passes).
    shoot_byes : bool, default=True
        Whether bye archers shoot alone.
    seed : int, default=SEED
        Seed of the draw.

    Returns
    -------
    dict
        The document at stage 2 with its drawn assignment.
    """
    doc = _stage1(n_archers=n, total_arrows=total_arrows, shoot_byes="yes" if shoot_byes else "no")
    rows = _rows([(NAMES[i], "Recurve", 15 + 5 * i) for i in range(n)])
    return _data(bridge.apply_stage2(doc, rows, {}, seed))["document"]


def test_pairings_list_every_pass_by_name():
    """Every pass of the schedule is listed with its pairings by name, and over a round-robin each pair meets once."""
    # ports test_event_routes.py::test_stage3_shows_every_pass_with_its_pairings_by_name
    data = _data(bridge.pairings(_drawn(4)))
    assert data["started"] is False
    passes = data["passes"]
    assert [p["pass_number"] for p in passes] == [1, 2, 3]
    assert all(len(p["matches"]) == 2 and p["sitting_out"] == [] for p in passes)
    pairs = {frozenset((m["a"], m["b"])) for p in passes for m in p["matches"]}
    assert len(pairs) == 6
    assert set().union(*pairs) == set(NAMES[:4])


def test_pairings_show_a_bye_shot_alone_or_who_sits_out():
    """Byes shot: one solo match a pass and nobody sitting out. Not shot: no solo match, and the sitting-out names."""
    # ports test_event_routes.py::test_stage3_shows_the_bye_archer_shooting_alone_when_byes_are_shot
    # ports test_event_routes.py::test_stage3_lists_who_sits_out_when_byes_are_not_shot
    shot = _data(bridge.pairings(_drawn(3, shoot_byes=True)))["passes"]
    assert len(shot) == 3
    assert all([m["b"] for m in p["matches"]].count(None) == 1 and p["sitting_out"] == [] for p in shot)

    doc = _drawn(5, total_arrows=60, shoot_byes=False)
    sat = _data(bridge.pairings(doc))["passes"]
    schedule = bridge.schedule_for(doc["setup"])
    assert len(sat) == len(schedule) == 7
    assert all(m["b"] is not None for p in sat for m in p["matches"])
    names = [doc["archers"][i]["name"] for i in doc["assignment"]]
    assert [p["sitting_out"] for p in sat] == [[names[i] for i in r.sitting_out] for r in schedule]


def test_pairings_are_stable_until_a_redraw_changes_them():
    """Pairings are the same on every call; a redraw gives a valid new assignment with different pairings, without starting."""
    # ports test_event_routes.py::test_reloading_stage3_without_redrawing_shows_the_same_assignment
    # ports test_event_routes.py::test_redraw_shows_different_pairings_and_stays_on_stage3
    # ports test_integration.py::test_setup_flow_rejects_a_bad_handicap_then_redraws_then_confirms_the_shown_pairings (the redraw)
    doc = _drawn(4)
    assert bridge.pairings(doc) == bridge.pairings(doc)
    redrawn = _data(bridge.redraw(doc, 5))["document"]
    assert sorted(redrawn["assignment"]) == [0, 1, 2, 3]
    assert _data(bridge.pairings(redrawn))["passes"] != _data(bridge.pairings(doc))["passes"]
    assert (redrawn["status"], redrawn["setup"]["stage"]) == ("setup", 2)


def test_starting_keeps_exactly_the_pairings_shown():
    """Starting builds the event from the shown draw: pass 1's matches are the pairings shown for pass 1."""
    # ports test_event_routes.py::test_confirming_starts_the_event_with_exactly_the_pairings_shown
    # ports test_integration.py::test_setup_flow_rejects_a_bad_handicap_then_redraws_then_confirms_the_shown_pairings (the confirm)
    doc = _data(bridge.redraw(_drawn(4, seed=7), 11))["document"]
    shown = _data(bridge.pairings(doc))["passes"]
    started = _data(bridge.start_event(doc))["document"]
    assert (started["status"], started["setup"]["stage"], started["assignment"]) == ("running", 3, doc["assignment"])
    matches = _data(bridge.overview(started))["matches"]
    assert [m["names"] for m in matches] == [[m["a"], m["b"]] for m in shown[0]["matches"]]
    assert [a.name for a in _event(started).archers] == [doc["archers"][i]["name"] for i in doc["assignment"]]
    assert _data(bridge.pairings(started))["started"] is True


# --- Overview, match view, saving and advancing --------------------------------------------------


def test_the_overview_lists_the_pass_and_its_unscored_matches():
    """Pass 1 of 3 with its two matches, each showing '-' until scored, and nothing to advance to yet."""
    # ports test_event_routes.py::test_overview_shows_pass_heading_matches_and_links_but_no_score_boxes
    # ports test_event_routes.py::test_unscored_pair_row_shows_dashes_and_an_enter_scores_link
    data = _data(bridge.overview(_start(FOUR_ARCHERS, total_arrows=36)))
    assert (data["pass_number"], data["n_passes"], data["match_count"], data["scored_count"]) == (1, 3, 2, 0)
    assert data["matches"][0] == {
        "index": 0, "names": ["A1", "A4"], "bye": False, "scored": False, "score": "-", "percentiles": "-", "winner": "-",
    }
    assert data["matches"][1]["names"] == ["A2", "A3"]
    assert (data["pass_complete"], data["is_last"], data["event_complete"], data["sitting_out"]) == (False, False, False, [])


@pytest.mark.parametrize("shoot_byes", [True, False], ids=["byes-shot", "byes-sat-out"])
def test_an_odd_archer_count_gives_a_solo_match_or_a_sitting_out_archer(shoot_byes):
    """Byes shot: the bye archer has a solo match after the pair. Not shot: they sit out and have no match."""
    # ports test_event_routes.py::test_overview_lists_the_bye_match_when_byes_are_shot
    # ports test_event_routes.py::test_overview_lists_sitting_out_archers_when_byes_are_not_shot
    # ports test_event_routes.py::test_match_page_shows_score_boxes_only_for_its_own_archers
    doc = _start(THREE_ARCHERS, total_arrows=24, shoot_byes="yes" if shoot_byes else "no")
    rotation = _event(doc).schedule[0]
    data = _data(bridge.overview(doc))
    pair_view = _data(bridge.match(doc, 0))
    assert (len(pair_view["archers"]), pair_view["bye"]) == (2, False)
    if shoot_byes:
        assert (data["match_count"], data["sitting_out"]) == (2, [])
        assert [m["bye"] for m in data["matches"]] == [False, True]
        assert data["matches"][1]["names"] == [THREE_ARCHERS[rotation.bye][0]]
        bye_view = _data(bridge.match(doc, 1))
        assert ([a["position"] for a in bye_view["archers"]], bye_view["bye"]) == ([rotation.bye], True)
    else:
        (sitting,) = rotation.sitting_out
        assert (data["match_count"], data["sitting_out"]) == (1, [THREE_ARCHERS[sitting][0]])
        assert _refusal(bridge.match(doc, 1), "validation") == "Pass 1 has matches 0 to 0, not 1."


def test_a_match_index_outside_the_pass_is_refused():
    """Viewing or saving an unknown match is refused."""
    # ports test_event_routes.py::test_match_index_out_of_range_redirects_to_overview
    doc = _start(FOUR_ARCHERS, total_arrows=36)
    message = "Pass 1 has matches 0 to 1, not 9."
    assert _refusal(bridge.match(doc, 9), "validation") == message
    assert _refusal(bridge.record_match(doc, 9, {"0": 1}), "validation") == message


def test_saving_a_match_records_only_that_match():
    """Saving one match stores its scores and leaves the other match awaiting scores."""
    # ports test_event_routes.py::test_saving_a_match_records_only_that_match_and_returns_to_its_page
    doc = _start(FOUR_ARCHERS, total_arrows=36)
    saved = _data(_record(doc, 0, {0: 100, 3: 60}))
    assert doc["scores"] == {}  # the input document is left as it was
    assert saved["document"]["scores"] == {"0": {"0": {"scores": {"0": 100, "3": 60}, "closest": None}}}
    first, second = _data(bridge.overview(saved["document"]))["matches"]
    assert (first["names"], first["score"]) == (["A1", "A4"], "100 - 60")
    assert (second["score"], second["percentiles"], second["winner"]) == ("-", "-", "-")
    assert (saved["match"]["scored"], saved["match"]["next_unscored_match"]) == (True, 1)


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        ("abc", "Alice's score must be a number."),
        ("-5", "Score must be between 0 and 120 for a 12-arrow pass, got -5."),
        ("121", "Score must be between 0 and 120 for a 12-arrow pass, got 121."),
        ("100.5", "Score must be a whole number, got 100.5."),
    ],
)
def test_an_invalid_score_is_refused_and_records_nothing(bad, message):
    """Each kind of invalid score is refused with its own message, and nothing is recorded."""
    # ports test_event_routes.py::test_invalid_score_on_a_match_page_shows_an_error_and_records_nothing
    doc = _start(TWO_ARCHERS, total_arrows=12)
    assert _refusal(_record(doc, 0, {0: bad, 1: 60}), "validation") == message
    assert doc["scores"] == {}
    assert _data(bridge.overview(doc))["matches"][0]["score"] == "-"


def test_resaving_a_match_replaces_its_scores_and_winner():
    """Saving a match again replaces the earlier scores, and the winner follows."""
    # ports test_event_routes.py::test_resaving_a_match_replaces_its_scores
    # ports test_event_routes.py::test_resaving_a_match_updates_its_row_and_awaiting_scores_text_is_gone
    doc = _save(_start(TWO_ARCHERS, total_arrows=12), 0, {0: 120, 1: 0})
    assert _data(bridge.overview(doc))["matches"][0]["winner"] == "Alice"
    doc = _save(doc, 0, {0: 0, 1: 120})
    row = _data(bridge.overview(doc))["matches"][0]
    assert (row["score"], row["winner"]) == ("0 - 120", "Bob")
    assert [a["score"] for a in _data(bridge.match(doc, 0))["archers"]] == [0, 120]
    assert doc["scores"]["0"] == {"0": {"scores": {"0": 0, "1": 120}, "closest": None}}


def test_advance_is_refused_until_every_match_is_scored_at_every_pass():
    """At each pass advance is refused with none or one of two matches saved; on the final pass it is refused for good."""
    # ports test_event_routes.py::test_advance_is_disabled_and_refused_until_every_match_is_scored
    # ports test_integration.py::test_advance_is_refused_until_every_match_is_scored_at_every_pass
    doc = _start(FOUR_ARCHERS, total_arrows=36)
    schedule = _event(doc).schedule
    for pass_index in range(3):
        assert _refusal(bridge.advance(doc), "state") == ADVANCE_UNSCORED
        first, second = schedule[pass_index].matches
        doc = _save(doc, 0, dict.fromkeys(first, 60))
        assert _refusal(bridge.advance(doc), "state") == ADVANCE_UNSCORED
        assert _data(bridge.overview(doc))["pass_complete"] is False
        doc = _save(doc, 1, dict.fromkeys(second, 60))
        view = _data(bridge.overview(doc))
        assert (view["pass_complete"], view["is_last"]) == (True, pass_index == 2)
        if pass_index < 2:
            doc = _advance(doc)
            assert (doc["current_pass"], _data(bridge.overview(doc))["pass_number"]) == (pass_index + 1, pass_index + 2)
    assert _refusal(bridge.advance(doc), "state") == ADVANCE_FINAL
    assert doc["status"] == "complete" and _data(bridge.overview(doc))["event_complete"] is True


def test_advancing_moves_to_the_next_passes_pairings():
    """After advancing, the overview lists pass 2's matches unscored, and they take new scores."""
    # ports test_event_routes.py::test_advancing_shows_the_next_passes_pairings_and_accepts_its_scores
    doc = _advance(_score_pass(_start(FOUR_ARCHERS, total_arrows=36)))
    view = _data(bridge.overview(doc))
    assert view["pass_number"] == 2
    expected = [[FOUR_ARCHERS[a][0], FOUR_ARCHERS[b][0]] for a, b in _event(doc).matches(1)]
    assert [m["names"] for m in view["matches"]] == expected
    assert [m["score"] for m in view["matches"]] == ["-", "-"]
    doc = _score_pass(doc)
    assert [p["pass_number"] for p in _data(bridge.results(doc))["passes"]] == [1, 2]


def test_a_single_pass_event_is_complete_once_scored_and_cannot_advance():
    """The only pass is the last; once scored the event is complete and advancing is refused."""
    # ports test_event_routes.py::test_final_pass_has_no_advance_button_and_links_to_results_when_scored
    # ports test_event_routes.py::test_advancing_past_the_final_pass_is_refused
    doc = _start(TWO_ARCHERS, total_arrows=12)
    before = _data(bridge.overview(doc))
    assert (before["pass_number"], before["n_passes"], before["is_last"], before["event_complete"]) == (1, 1, True, False)
    doc = _save(doc, 0, {0: 100, 1: 60})
    assert doc["status"] == "complete" and _data(bridge.overview(doc))["event_complete"] is True
    assert _refusal(bridge.advance(doc), "state") == ADVANCE_FINAL


def test_the_match_view_rows_are_the_events_own_results():
    """No rows before scoring; then one row per archer with the event's score, percentile, handicap and winner."""
    # ports test_event_routes.py::test_match_page_has_no_results_table_before_scoring_and_one_this_pass_table_after
    # ports test_event_routes.py::test_match_page_table_agrees_with_the_events_recorded_results
    fresh = _start(TWO_ARCHERS, total_arrows=12)
    view = _data(bridge.match(fresh, 0))
    assert (view["rows"], view["scored"]) == ([], False)
    for scores in ({0: 120, 1: 0}, {0: 100, 1: 60}, {0: 60, 1: 100}, {0: 118, 1: 119}, {0: 0, 1: 1}):
        doc = _save(fresh, 0, scores)
        rows = _data(bridge.match(doc, 0))["rows"]
        results = _event(doc).match_results(0, (0, 1))
        texts = percentile_pair_text(results[0].percentile, results[1].percentile)
        assert [(r["archer"], r["score"], r["percentile"], r["handicap"], r["winner"]) for r in rows] == [
            (
                TWO_ARCHERS[r.archer_index][0],
                str(r.score),
                text,
                "-" if r.handicap is None else f"{r.handicap:.1f}",
                "Yes" if r.won else "No",
            )
            for r, text in zip(results, texts, strict=True)
        ]
        assert all(re.fullmatch(r"\d+\.\d+%", r["percentile"]) for r in rows)
    rows = _data(bridge.match(_save(fresh, 0, {0: 120, 1: 0}), 0))["rows"]
    assert [r["winner"] for r in rows] == ["Yes", "No"]
    assert rows[0]["handicap"] != "-" and rows[1]["handicap"] == "-"  # a score of 0 has no handicap


def test_the_match_view_shows_only_this_pass_and_this_match():
    """A pair meeting again sees just the new pass's rows, and a match never lists another match's archers."""
    # ports test_event_routes.py::test_match_page_shows_only_this_pass_not_earlier_passes_of_the_same_pair
    # ports test_event_routes.py::test_match_page_never_shows_results_against_a_different_opponent
    doc = _start(TWO_ARCHERS, total_arrows=24)
    doc = _save(_advance(_save(doc, 0, {0: 100, 1: 60})), 0, {0: 91, 1: 82})
    assert [r["score"] for r in _data(bridge.match(doc, 0))["rows"]] == ["91", "82"]

    four = _start(NAMED_FOUR, total_arrows=36)
    event = _event(four)
    first, second = event.matches(0)
    four = _save(_save(four, 0, {p: 61 + p for p in first}), 1, {p: 71 + p for p in second})
    view = _data(bridge.match(four, 0))
    assert [r["archer"] for r in view["rows"]] == [event.archers[p].name for p in first]
    assert [a["position"] for a in view["archers"]] == list(first)


def test_a_bye_match_shows_its_own_result_with_no_winner():
    """A solo match has one archer and one row: percentile to one place, a handicap, and '-' as winner."""
    # ports test_event_routes.py::test_bye_match_page_shows_own_result_and_no_chart_either_way (the result)
    # ports test_event_routes.py::test_bye_match_page_has_the_bye_archers_name_only
    # ports test_event_routes.py::test_bye_match_table_has_one_row_with_a_handicap_and_no_winner
    # ports test_event_routes.py::test_bye_match_row_shows_one_score_one_percentile_and_no_winner
    doc = _start(THREE_ARCHERS, total_arrows=24, shoot_byes="yes")
    bye = _event(doc).schedule[0].bye
    name = THREE_ARCHERS[bye][0]
    assert [a["name"] for a in _data(bridge.match(doc, 1))["archers"]] == [name]
    doc = _save(doc, 1, {bye: 70})
    view = _data(bridge.match(doc, 1))
    (row,) = view["rows"]
    result = _event(doc).match_results(0, (bye, None))[0]
    percentile = f"{result.percentile * 100:.1f}%"
    assert (row["archer"], row["score"], row["percentile"], row["winner"]) == (name, "70", percentile, "-")
    assert row["handicap"] != "-" and view["decided_by_closest"] is False
    assert _data(bridge.overview(doc))["matches"][1] == {
        "index": 1, "names": [name], "bye": True, "scored": True, "score": "70", "percentiles": percentile, "winner": "-",
    }


def test_overview_rows_are_the_events_own_results_throughout_an_event():
    """After each pass is scored, every match's names, scores, percentiles and winner are the event's own."""
    # ports test_event_routes.py::test_scored_pair_row_matches_the_events_recorded_results
    # ports test_integration.py::test_overview_table_agrees_with_the_event_for_every_match_of_a_full_event
    doc = _start([(f"A{i}", "Recurve", 20 + 5 * i) for i in range(4)], total_arrows=36)
    base = {0: 95, 1: 88, 2: 101, 3: 74}
    for pass_index in range(3):
        doc = _score_pass(doc, lambda p, n=pass_index: base[p] + n)
        event = _event(doc)
        rows = _data(bridge.overview(doc))["matches"]
        for row, (a, b) in zip(rows, event.matches(pass_index), strict=True):
            result_a, result_b = event.match_results(pass_index, (a, b))
            winner = result_a if result_a.won else result_b
            assert row["names"] == [event.archers[a].name, event.archers[b].name]
            assert row["score"] == f"{result_a.score} - {result_b.score}"
            assert row["percentiles"] == " - ".join(percentile_pair_text(result_a.percentile, result_b.percentile))
            assert row["winner"] == event.archers[winner.archer_index].name
        if pass_index < 2:
            doc = _advance(doc)


def test_score_and_percentile_order_follows_the_match_order_in_every_pair():
    """In a pair listed higher position first, Score and Percentiles keep that order."""
    # ports test_event_routes.py::test_score_and_percentile_orientation_follows_the_match_column_for_every_pair
    doc = _advance(_score_pass(_start(FOUR_ARCHERS, total_arrows=36)))
    matches = _event(doc).matches(1)
    flipped = [i for i, (a, b) in enumerate(matches) if a > b]
    assert flipped, "expected a pair listed higher position first in pass 2"
    for match_index, (a, b) in enumerate(matches):
        doc = _save(doc, match_index, {a: 50 + 7 * a, b: 50 + 7 * b})
    event = _event(doc)
    rows = _data(bridge.overview(doc))["matches"]
    for i in flipped:
        a, b = matches[i]
        result_a, result_b = event.match_results(1, (a, b))
        assert rows[i]["names"] == [FOUR_ARCHERS[a][0], FOUR_ARCHERS[b][0]]
        assert rows[i]["score"] == f"{50 + 7 * a} - {50 + 7 * b}"
        assert rows[i]["percentiles"] == " - ".join(percentile_pair_text(result_a.percentile, result_b.percentile))


def test_percentiles_gain_places_only_when_one_place_would_not_tell_them_apart():
    """Very low scores show more places, the same in the overview and the match view; realistic ones keep one place."""
    # ports test_event_routes.py::test_overview_percentiles_gain_places_when_both_would_show_the_same
    # ports test_event_routes.py::test_overview_percentiles_keep_one_place_when_they_already_differ
    # ports test_event_routes.py::test_match_page_percentiles_follow_the_display_rule_and_agree_with_the_overview
    low = _save(_start(TWO_ARCHERS, total_arrows=12), 0, {0: 100, 1: 90})  # far below what 15 and 45 expect
    first, second = _data(bridge.overview(low))["matches"][0]["percentiles"].split(" - ")
    assert first != second
    assert all(len(text.split(".")[1]) > 2 for text in (first, second))  # more than "x%"
    results = _event(low).match_results(0, (0, 1))
    assert (first, second) == percentile_pair_text(results[0].percentile, results[1].percentile)
    assert [r["percentile"] for r in _data(bridge.match(low, 0))["rows"]] == [first, second]

    usual = _save(_start(TWO_ARCHERS, total_arrows=12), 0, {0: 119, 1: 100})
    assert re.fullmatch(r"\d+\.\d% - \d+\.\d%", _data(bridge.overview(usual))["matches"][0]["percentiles"])


# --- Tie-break: closest to the middle --------------------------------------------------------------


def test_a_tie_without_closest_is_refused_and_nothing_is_recorded():
    """Tied percentile and score need the closest archer: code tiebreak_required, no save, and the pass cannot advance."""
    # ports test_event_routes.py::test_a_tie_without_a_tick_is_refused_with_a_message_and_the_typed_scores_kept
    # ports test_event_routes.py::test_the_refused_tie_page_shows_the_two_boxes_the_explanation_and_the_script (the refusal)
    # ports test_integration.py::test_a_tie_is_blocked_until_a_box_is_ticked_then_the_ticked_archer_is_credited (the block)
    doc = _start(TIED_PAIR, total_arrows=24)
    message = _refusal(_record(doc, 0, {0: 90, 1: 90}), "tiebreak_required")
    assert message == bridge.TIEBREAK_MESSAGE
    assert message.startswith("Percentile and score are tied. Tick which archer")
    assert doc["scores"] == {}
    assert _refusal(bridge.advance(doc), "state") == ADVANCE_UNSCORED


def test_a_tie_with_closest_is_saved_and_decided_for_that_archer():
    """The named archer wins in the match view and the overview, and the saved view says it was decided by closest, for whom."""
    # ports test_event_routes.py::test_a_tie_with_a_tick_is_saved_and_decided_for_the_ticked_archer
    # ports test_event_routes.py::test_a_saved_tie_break_match_shows_the_boxes_ticked_so_it_can_be_corrected
    doc = _save(_start(TIED_PAIR, total_arrows=24), 0, {0: 90, 1: 90}, closest=1)
    assert doc["scores"]["0"]["0"] == {"scores": {"0": 90, "1": 90}, "closest": 1}
    view = _data(bridge.match(doc, 0))
    assert [r["winner"] for r in view["rows"]] == ["No", "Yes"]
    assert (view["decided_by_closest"], view["closest"]) == (True, 1)
    assert _data(bridge.overview(doc))["matches"][0]["winner"] == "Ben"


def test_a_closest_archer_outside_the_match_is_refused():
    """A closest archer who is not in the match is refused, and nothing is recorded."""
    # ports test_event_routes.py::test_a_closest_value_outside_the_match_is_rejected
    doc = _start(TIED_PAIR, total_arrows=24)
    assert _refusal(_record(doc, 0, {0: 90, 1: 90}, closest=7), "validation") == CLOSEST_OUTSIDE
    assert doc["scores"] == {}


@pytest.mark.parametrize("closest", [0, 1])
def test_an_unneeded_closest_archer_is_ignored_and_not_stored(closest):
    """Different scores: the percentile decides, and the closest archer is neither stored nor shown."""
    # ports test_event_routes.py::test_an_unneeded_tick_is_ignored_and_not_shown_afterwards
    # ports test_event_routes.py::test_a_forced_tick_with_no_tie_is_ignored_and_the_next_page_has_no_boxes
    # ports test_event_routes.py::test_a_normal_match_page_has_no_tie_break_boxes_text_or_script
    fresh = _start(TIED_PAIR, total_arrows=24)
    assert _data(bridge.match(fresh, 0))["decided_by_closest"] is False
    doc = _save(fresh, 0, {0: 100, 1: 60}, closest=closest)
    assert doc["scores"]["0"]["0"]["closest"] is None
    view = _data(bridge.match(doc, 0))
    assert [r["winner"] for r in view["rows"]] == ["Yes", "No"]  # the better score won, not the closest archer
    assert (view["decided_by_closest"], view["closest"]) == (False, None)


def test_resaving_a_closest_decided_match():
    """Re-saving the tie with the other archer closest flips the result; re-saving untied scores clears the tie-break."""
    # ports test_event_routes.py::test_editing_a_decided_by_closest_match_to_untied_scores_clears_the_note
    # ports test_integration.py::test_match_pages_never_show_a_handicap_or_tie_boxes_until_an_exact_tie_and_then_show_boxes (the tie-break)
    doc = _save(_start(TIED_PAIR, total_arrows=24), 0, {0: 90, 1: 90}, closest=0)
    assert _data(bridge.match(doc, 0))["closest"] == 0
    doc = _save(doc, 0, {0: 90, 1: 90}, closest=1)
    view = _data(bridge.match(doc, 0))
    assert [r["winner"] for r in view["rows"]] == ["No", "Yes"] and view["closest"] == 1
    doc = _save(doc, 0, {0: 90, 1: 95})
    view = _data(bridge.match(doc, 0))
    assert [r["winner"] for r in view["rows"]] == ["No", "Yes"]
    assert (view["decided_by_closest"], view["closest"]) == (False, None)
    assert doc["scores"]["0"]["0"]["closest"] is None


@pytest.mark.parametrize("earlier", [{0: 90, 1: 95}, {0: 100, 1: 60}])
def test_resaving_into_a_tie_without_closest_keeps_the_saved_result(earlier):
    """A refused re-save into a tie leaves the earlier result in place."""
    # ports test_event_routes.py::test_editing_a_decided_match_back_to_a_tie_without_a_tick_keeps_the_saved_result
    # ports test_event_routes.py::test_a_refused_re_save_into_a_tie_shows_the_boxes_over_a_percentile_decided_match
    doc = _save(_start(TIED_PAIR, total_arrows=24), 0, earlier)
    assert _refusal(_record(doc, 0, {0: 90, 1: 90}), "tiebreak_required") == bridge.TIEBREAK_MESSAGE
    assert [a["score"] for a in _data(bridge.match(doc, 0))["archers"]] == list(earlier.values())


def test_a_bye_match_ignores_a_closest_archer():
    """A solo match has nothing to tie with: its score errors are the usual ones, and a closest archer is never stored."""
    # ports test_event_routes.py::test_a_bye_match_page_never_has_the_boxes_even_after_a_refused_looking_post
    doc = _start(THREE_ARCHERS, total_arrows=24, shoot_byes="yes")
    bye = _event(doc).schedule[0].bye
    name = THREE_ARCHERS[bye][0]
    assert _refusal(_record(doc, 1, {bye: "abc"}, closest=0), "validation") == f"{name}'s score must be a number."
    doc = _save(doc, 1, {bye: 70}, closest=(bye + 1) % 3)
    assert doc["scores"]["0"]["1"]["closest"] is None
    assert _data(bridge.match(doc, 1))["decided_by_closest"] is False


def test_naming_both_archers_closest_is_refused_and_records_nothing():
    """Both archers named closest is refused, tied or not, and is not mistaken for a plain tie."""
    # ports test_event_routes.py::test_ticking_both_boxes_is_rejected_even_when_the_scores_are_not_tied (the refusal)
    # ports test_event_routes.py::test_the_tie_message_survives_a_rejected_tie_that_had_a_wrong_tick (not a tie refusal)
    # ports test_event_routes.py::test_both_ticked_is_rejected_with_the_boxes_shown_as_submitted (the refusal)
    doc = _start(TIED_PAIR, total_arrows=24)
    # The bridge takes one closest archer (UISpec.md 7.2: "choose exactly one of the two archers"),
    # so the message is CLOSEST_OUTSIDE rather than Flask's "Tick only one archer ..." (logbook, UI-4).
    for scores in ({0: 100, 1: 60}, {0: 90, 1: 90}):
        assert _refusal(_record(doc, 0, scores, closest=[0, 1]), "validation") == CLOSEST_OUTSIDE
    assert doc["scores"] == {}


def test_a_pass_decided_by_closest_counts_on_the_leaderboard():
    """Ben wins pass 1 on the tie-break and Ann wins pass 2 on the percentile: one point each."""
    # ports test_integration.py::test_a_tie_is_blocked_until_a_box_is_ticked_then_the_ticked_archer_is_credited
    doc = _save(_start(TIED_PAIR, total_arrows=24), 0, {0: 90, 1: 90}, closest=1)
    doc = _save(_advance(doc), 0, {0: 100, 1: 95})
    board = _data(bridge.results(doc))["leaderboard"]
    assert {row["name"]: row["points"] for row in board} == {"Ann": "1", "Ben": "1"}
    assert {r.decided_by for r in _event(doc).results} == {"closest", "percentile"}


# --- Advanced setup: each archer's own target and maximum ---------------------------------------


def test_each_archer_is_scored_against_their_own_faces_maximum():
    """A 5-zone archer tops out at 108 per 12 arrows and a 10-zone archer at 120; each percentile uses the archer's own distribution."""
    # ports test_event_routes.py::test_match_page_score_boxes_use_each_archers_own_maximum
    # ports test_event_routes.py::test_a_full_advanced_event_with_mixed_targets_plays_through_over_http
    doc = _start(FIVE_AND_TEN_ZONE, setup_mode="advanced", total_arrows=24)
    assert [a["max_score"] for a in _data(bridge.match(doc, 0))["archers"]] == [108, 120]
    for too_high in (109, 110):
        message = _refusal(_record(doc, 0, {0: too_high, 1: 100}), "validation")
        assert message == f"Score must be between 0 and 108 for a 12-arrow pass, got {too_high}."
    assert doc["scores"] == {}
    _data(_record(doc, 0, {0: 108, 1: 119}))  # each at or below their own maximum
    doc = _save(_advance(_save(doc, 0, {0: 100, 1: 110})), 0, {0: 100, 1: 110})
    assert doc["status"] == "complete"
    for command in (bridge.overview, bridge.results, bridge.archer_results, lambda d: bridge.match(d, 0)):
        _data(command(doc))
    event = _event(doc)
    results = {r.archer_index: r for r in event.results if r.rotation_index == 0}
    assert results[0].percentile == pytest.approx(stats.percentile(event.distribution_for(0), 100))
    assert results[1].percentile == pytest.approx(stats.percentile(event.distribution_for(1), 110))
    assert results[0].percentile != results[1].percentile


def test_an_advanced_events_leaderboard_follows_the_winners_after_every_pass():
    """Four archers on four targets: each score respects its own maximum, and after every pass the points are the passes won."""
    # ports test_integration.py::test_advanced_event_leaderboard_follows_the_winners_after_every_completed_pass
    doc = _start(ADVANCED_FOUR, setup_mode="advanced", total_arrows=36)
    event = _event(doc)
    max_scores = [event.max_score_for(i) for i in range(4)]
    assert max_scores == [120, 120, 108, 60]
    for pass_index in range(3):
        doc = _score_pass(doc, lambda p, n=pass_index + 1: int(max_scores[p] * 0.55) + 2 * n + p)
        results = _event(doc).results
        wins = {i: sum(1 for r in results if r.archer_index == i and r.won) for i in range(4)}
        board = _data(bridge.results(doc))["leaderboard"]
        assert {row["name"]: int(row["points"]) for row in board} == {ADVANCED_FOUR[i][0]: wins[i] for i in range(4)}
        assert [row["passes_decided"] for row in board] == [str(pass_index + 1)] * 4
        if pass_index < 2:
            doc = _advance(doc)
    assert doc["status"] == "complete"


@pytest.mark.parametrize(
    ("distance", "face_cm", "metres", "indoor"),
    [
        ("20yd", 60, 20 * 0.9144, True),
        ("18m", 40, 18, True),
        ("25yd", 60, 25 * 0.9144, True),  # 22.9 m counts as indoor
        ("30yd", 60, 30 * 0.9144, False),  # 27.4 m counts as outdoor
        ("50m", 80, 50, False),
        ("70m", 122, 70, False),
    ],
)
def test_a_simple_setup_gives_compound_the_reduced_ten_only_indoors(distance, face_cm, metres, indoor):
    """Everyone shoots the shared face; indoors Compound scores the reduced 10, outdoors every bowstyle scores the plain one."""
    # ports test_integration.py::test_indoor_mode_compound_archer_uses_compound_target
    # ports test_integration.py::test_outdoor_mode_ignores_bowstyle_for_target
    # ports test_integration.py::test_indoor_event_with_all_four_bowstyles_uses_the_right_targets
    # ports test_integration.py::test_outdoor_event_gives_every_archer_the_same_target
    # ports test_integration.py::test_outdoor_distance_event_gives_everyone_the_chosen_face_and_no_reduced_ten
    # ports test_integration.py::test_indoor_distance_event_gives_compound_the_reduced_ten_only
    # ports test_integration.py::test_imperial_distance_is_converted_and_classified_by_its_length_in_metres
    doc = _start(SAME_HANDICAP_BOWS, total_arrows=36, distance=distance, face_cm=face_cm)
    event = _event(doc)
    targets = [event.target_for(i) for i in range(4)]
    compound = "10_zone_compound" if indoor else "10_zone"
    assert [t.scoring_system for t in targets] == ["10_zone", compound, "10_zone", "10_zone"]
    assert all(t.indoor is indoor for t in targets)
    assert all(t.diameter == pytest.approx(face_cm / 100) and t.distance == pytest.approx(metres) for t in targets)
    # Same handicap and the same score: only a different scoring can give a different percentile.
    percentiles = {r.archer_index: r.percentile for r in _event(_score_pass(doc, lambda p: 100)).results}
    assert percentiles[0] == percentiles[2] == percentiles[3]
    assert (percentiles[1] != percentiles[0]) is indoor


# --- Byes and sit-outs over whole events --------------------------------------------------------


def test_an_even_event_plays_a_full_round_robin():
    """Four archers over three passes: two pairs a pass, and every pair has a pairwise result at the end."""
    # ports test_integration.py::test_even_n_archers_full_round_robin_coverage
    # ports test_integration.py::test_even_n_archers_every_pair_appears_in_the_pairwise_results
    names = [f"A{i}" for i in range(4)]
    doc = _start([(name, "Recurve", 20 + 5 * i) for i, name in enumerate(names)], total_arrows=36)
    for pass_index in range(3):
        assert [len(m["names"]) for m in _data(bridge.overview(doc))["matches"]] == [2, 2]
        doc = _score_pass(doc)
        if pass_index < 2:
            doc = _advance(doc)
    assert doc["status"] == "complete"
    data = _data(bridge.results(doc))
    assert {(p["archer_a"], p["archer_b"]) for p in data["pairwise"]} == {(a, b) for a in range(4) for b in range(a + 1, 4)}
    assert {row["name"] for row in data["leaderboard"]} == set(names)


def test_odd_archers_shooting_byes_have_one_winnerless_solo_match_per_pass():
    """Byes shot: total_arrows // n_pass passes, each with two pairs and one solo match without a winner; everyone shoots every pass."""
    # ports test_integration.py::test_odd_n_archers_each_rotation_has_exactly_one_bye
    # ports test_integration.py::test_odd_n_archers_byes_shot_has_one_winnerless_bye_match_per_pass
    names = [f"A{i}" for i in range(5)]
    doc = _start([(name, "Recurve", 20 + 5 * i) for i, name in enumerate(names)], total_arrows=60, shoot_byes="yes")
    for pass_index in range(5):
        view = _data(bridge.overview(doc))
        assert (view["pass_number"], view["n_passes"]) == (pass_index + 1, 5)
        assert sorted(len(m["names"]) for m in view["matches"]) == [1, 2, 2]
        assert {name for m in view["matches"] for name in m["names"]} == set(names)
        doc = _score_pass(doc)
        assert [m["winner"] for m in _data(bridge.overview(doc))["matches"] if m["bye"]] == ["-"]
        if pass_index < 4:
            doc = _advance(doc)
    assert doc["status"] == "complete"
    solo = [group for p in _data(bridge.results(doc))["passes"] for group in p["groups"] if len(group) == 1]
    assert len(solo) == 5
    assert {group[0]["archer"] for group in solo} == set(names)
    assert all(group[0]["winner"] == "-" for group in solo)
    assert set(Counter(r.archer_index for r in _event(doc).results).values()) == {5}


@pytest.mark.parametrize(
    ("total_arrows", "n_passes", "passes_shot"),
    [(60, 7, [5, 5, 5, 5, 6]), (48, 5, [4, 4, 4, 4, 4])],
    ids=["catch-up-pass", "no-catch-up"],
)
def test_odd_archers_sitting_out_byes(total_arrows, n_passes, passes_shot):
    """Byes not shot: sitting-out archers get no match and nobody shoots alone; a catch-up pass is added only when needed."""
    # ports test_integration.py::test_odd_n_archers_byes_not_shot_sits_archers_out_and_adds_passes
    # ports test_integration.py::test_odd_n_archers_byes_not_shot_needs_no_catch_up_when_passes_divide_evenly
    names = [f"A{i}" for i in range(5)]
    doc = _start([(name, "Recurve", 20 + 5 * i) for i, name in enumerate(names)], total_arrows=total_arrows, shoot_byes="no")
    for pass_index in range(n_passes):
        view = _data(bridge.overview(doc))
        assert view["n_passes"] == n_passes and view["sitting_out"]
        assert not any(m["bye"] for m in view["matches"])
        shooters = {name for m in view["matches"] for name in m["names"]}
        assert shooters.isdisjoint(view["sitting_out"]) and shooters | set(view["sitting_out"]) == set(names)
        doc = _score_pass(doc)
        if pass_index < n_passes - 1:
            doc = _advance(doc)
    assert doc["status"] == "complete"
    assert sorted(Counter(r.archer_index for r in _event(doc).results).values()) == passes_shot


# --- Results: leaderboard, pairwise results and pass tables --------------------------------------


def test_results_before_any_scoring_have_no_pairwise_results_or_pass_tables():
    """Before anything is scored there are no pairwise results and no pass tables."""
    # ports test_event_routes.py::test_results_page_before_any_scoring_shows_no_pairwise_results
    data = _data(bridge.results(_start(FOUR_ARCHERS, total_arrows=36)))
    assert (data["pairwise"], data["passes"]) == ([], [])
    assert (data["completed_passes"], data["n_passes"], data["current_pass_number"], data["event_complete"]) == (0, 3, 1, False)


def test_results_show_the_scored_pass_and_the_pairwise_winner():
    """A scored pass appears with both archers' scores, and the pair's result names the winner."""
    # ports test_event_routes.py::test_results_page_shows_scored_rotation
    # ports test_event_routes.py::test_results_page_shows_pairwise_result
    data = _data(bridge.results(_save(_start(TWO_ARCHERS, total_arrows=12), 0, {0: 120, 1: 0})))
    (pass_1,) = data["passes"]
    assert pass_1["pass_number"] == 1
    assert [(row["archer"], row["score"]) for row in pass_1["groups"][0]] == [("Alice", "120"), ("Bob", "0")]
    (pair,) = data["pairwise"]
    assert (pair["name_a"], pair["name_b"], pair["wins_a"], pair["wins_b"]) == ("Alice", "Bob", "1", "0")
    assert (pair["draw"], pair["result"]) == (False, "Alice wins")


def test_the_leaderboard_is_the_outputs_model_and_ranks_share_on_ties():
    """Rank, archer, points, passes decided, starting and to-date handicap equal outputs.leaderboard; equal points share a rank."""
    # ports test_event_routes.py::test_results_page_has_a_leaderboard_table_matching_the_outputs_model
    doc = _score_pass(_start(NAMED_FOUR, total_arrows=36), lambda p: 80 + p)
    board = _data(bridge.results(doc))["leaderboard"]
    assert board == [
        {
            "archer_index": r.archer_index,
            "rank": str(r.rank),
            "name": r.name,
            "points": str(r.points),
            "passes_decided": str(r.passes_decided),
            "starting_handicap": f"{r.starting_handicap:g}",
            "to_date_handicap": "-" if r.to_date_handicap is None else f"{r.to_date_handicap:.1f}",
        }
        for r in outputs.leaderboard(_event(doc))
    ]
    assert len(board) == 4 and all(row["to_date_handicap"] != "-" for row in board)
    assert sum(int(row["points"]) for row in board) == 2  # one winner in each of the two matches
    assert [row["rank"] for row in board] == ["1", "1", "3", "3"]


def test_the_leaderboard_counts_only_completed_passes():
    """After one of two matches nothing counts; once the pass is complete each winner has a point."""
    # ports test_event_routes.py::test_the_leaderboard_is_live_and_waits_for_the_whole_pass
    doc = _start(NAMED_FOUR, total_arrows=36)
    first, second = _event(doc).matches(0)
    doc = _save(doc, 0, {p: 80 + p for p in first})
    data = _data(bridge.results(doc))
    assert [row["points"] for row in data["leaderboard"]] == ["0"] * 4
    assert (data["completed_passes"], data["n_passes"]) == (0, 3)
    doc = _save(doc, 1, {p: 80 + p for p in second})
    data = _data(bridge.results(doc))
    assert sorted(int(row["points"]) for row in data["leaderboard"]) == [0, 0, 1, 1]
    assert [row["passes_decided"] for row in data["leaderboard"]] == ["1"] * 4
    assert (data["completed_passes"], data["n_passes"]) == (1, 3)


def test_a_half_scored_pass_is_left_out_of_the_outputs_and_the_exports():
    """Pass 2 with one match saved changes neither the leaderboard, the archer results nor the CSVs."""
    # ports test_integration.py::test_a_half_scored_pass_is_left_out_of_the_outputs_and_the_exports_match
    doc = _start([(f"A{i}", "Recurve", 20 + 10 * i) for i in range(4)], total_arrows=36)
    doc = _advance(_score_pass(doc, lambda p: 80 + p))
    first, _ = _event(doc).matches(1)
    doc = _save(doc, 0, {p: 85 + p for p in first})
    board = _data(bridge.results(doc))["leaderboard"]
    assert [row["passes_decided"] for row in board] == ["1"] * 4  # pass 1 only
    exported = _csv(doc, "leaderboard_csv")[1:]
    assert [row[1:4] for row in exported] == [[row["name"], row["points"], row["passes_decided"]] for row in board]
    assert len(_csv(doc, "archer_results_csv")) == 1 + 4
    assert all(len(s["rows"]) == 1 for s in _data(bridge.archer_results(doc))["sections"])


def test_results_pass_tables_group_each_match_in_match_order_with_the_events_values():
    """One table per scored pass and one group per match, in match order, with the event's own values; a pair's percentiles differ."""
    # ports test_event_routes.py::test_results_page_has_a_pass_table_per_scored_pass_in_the_match_page_format
    # ports test_event_routes.py::test_each_matchs_rows_are_a_group_with_a_double_rule_between_groups (the grouping)
    # ports test_event_routes.py::test_the_pass_table_values_are_the_events_own_under_the_display_rules
    # ports test_event_routes.py::test_results_page_headings_say_pass_and_there_is_no_opponent_or_won_column (pass numbers)
    # ports test_integration.py::test_results_page_groups_each_matchs_rows_in_overview_order_with_distinct_percentile_texts
    by_position = [118, 112, 104, 95]
    doc = _score_pass(_start([(f"A{i}", "Recurve", 20 + 10 * i) for i in range(4)], total_arrows=36), lambda p: by_position[p] - 1)
    assert [p["pass_number"] for p in _data(bridge.results(doc))["passes"]] == [1]
    doc = _score_pass(_advance(doc), lambda p: by_position[p] - 2)
    event = _event(doc)
    passes = _data(bridge.results(doc))["passes"]
    assert [(p["pass_index"], p["pass_number"]) for p in passes] == [(0, 1), (1, 2)]  # pass 3 not scored yet
    for entry in passes:
        pass_index = entry["pass_index"]
        assert [len(group) for group in entry["groups"]] == [2, 2]
        for group, match in zip(entry["groups"], event.matches(pass_index), strict=True):
            found = event.match_results(pass_index, match)
            texts = percentile_pair_text(found[0].percentile, found[1].percentile)
            assert [(r["archer"], r["score"], r["percentile"], r["handicap"], r["winner"]) for r in group] == [
                (event.archers[r.archer_index].name, str(r.score), text, f"{r.handicap:.1f}", "Yes" if r.won else "No")
                for r, text in zip(found, texts, strict=True)
            ]
            assert group[0]["percentile"] != group[1]["percentile"]


def test_a_bye_match_is_a_group_of_one_and_unscored_matches_are_left_out():
    """Byes shot: an unsaved match is not listed, and the solo match is its own group with winner '-'."""
    # ports test_event_routes.py::test_a_bye_match_is_a_group_of_one_row_and_unscored_matches_are_left_out
    doc = _start(THREE_ARCHERS, total_arrows=24, shoot_byes="yes")
    event = _event(doc)
    pair, _ = event.matches(0)
    doc = _save(doc, 0, {p: 80 + p for p in pair})  # the bye match is not scored yet
    (entry,) = _data(bridge.results(doc))["passes"]
    assert [len(group) for group in entry["groups"]] == [2]
    doc = _save(doc, 1, {event.schedule[0].bye: 90})
    (entry,) = _data(bridge.results(doc))["passes"]
    assert [len(group) for group in entry["groups"]] == [2, 1]
    assert entry["groups"][1][0]["winner"] == "-"


# --- Archer results ------------------------------------------------------------------------------


def test_archer_results_sections_are_the_outputs_model():
    """Per archer: total score, starting and to-date handicap, a row per completed pass and an Average row."""
    # ports test_event_routes.py::test_archer_results_page_has_a_section_per_archer_with_the_agreed_columns
    doc = _start(NAMED_FOUR, total_arrows=36)
    for n in (1, 2):
        doc = _advance(_score_pass(doc, lambda p, n=n: 80 + p + n))
    data = _data(bridge.archer_results(doc))
    assert (data["completed_passes"], data["n_passes"], data["show_start_handicap"]) == (2, 3, False)
    sections = outputs.archer_results(_event(doc))
    assert len(data["sections"]) == len(sections) == 4
    for shown, section in zip(data["sections"], sections, strict=True):
        assert (shown["name"], shown["total_score"], shown["starting_handicap"], shown["to_date_handicap"]) == (
            section.name, str(section.total_score), f"{section.handicap:g}", f"{section.to_date_handicap:.1f}",
        )
        assert [(r["pass_number"], r["opponent"], r["score"], r["percentile"]) for r in shown["rows"]] == [
            (str(r.pass_number), r.opponent, str(r.score), f"{r.percentile * 100:.1f}%") for r in section.rows
        ]
        assert all(r["pass_number"].isdigit() for r in shown["rows"])  # a whole number, no decimals
        averages = section.averages
        assert shown["average"] == {
            "score": f"{averages.score:.1f}",
            "percentile": f"{averages.percentile * 100:.1f}%",
            "start_handicap": f"{averages.start_handicap:.1f}",
            "handicap": f"{averages.handicap:.1f}",
        }


def test_a_zero_score_has_no_handicap_and_is_left_out_of_the_average():
    """No equivalent handicap exists for 0, so the row shows '-' and the average skips it."""
    # ports test_event_routes.py::test_a_zero_score_shows_a_dash_for_its_handicap_and_is_left_out_of_the_average
    doc = _start([("Ann", "Recurve", 20), ("Ben", "Recurve", 30)], total_arrows=24)
    doc = _save(_advance(_save(doc, 0, {0: 100, 1: 0})), 0, {0: 90, 1: 80})
    ben = _data(bridge.archer_results(doc))["sections"][1]
    second = f"{_event(doc).match_results(1, (0, 1))[1].handicap:.1f}"
    assert [r["handicap"] for r in ben["rows"]] == ["-", second]
    assert ben["average"]["handicap"] == second


@pytest.mark.parametrize("shoot_byes", [True, False], ids=["byes-shot", "byes-sat-out"])
def test_a_bye_pass_reads_bye_and_a_sat_out_pass_has_no_row(shoot_byes):
    """Byes shot: the solo pass is a row against 'bye'. Not shot: the archer who sat out has no row."""
    # ports test_event_routes.py::test_a_bye_pass_reads_bye_and_a_sat_out_pass_has_no_row
    doc = _start(THREE_ARCHERS, total_arrows=24, shoot_byes="yes" if shoot_byes else "no")
    sections = _data(bridge.archer_results(_score_pass(doc, lambda p: 80 + p)))["sections"]
    opponents = [r["opponent"] for s in sections for r in s["rows"]]
    if shoot_byes:
        assert opponents.count("bye") == 1
        assert all(len(s["rows"]) == 1 for s in sections)
    else:
        assert "bye" not in opponents
        assert sorted(len(s["rows"]) for s in sections) == [0, 1, 1]
        assert [s["average"] is None for s in sections].count(True) == 1


def test_archer_results_before_any_completed_pass_are_empty_sections():
    """Every archer has a section with total 0, to-date '-' and no rows until a pass is complete."""
    # ports test_event_routes.py::test_archer_results_before_any_completed_pass_shows_headings_and_an_empty_state
    doc = _start(NAMED_FOUR, total_arrows=36)
    first, _ = _event(doc).matches(0)
    for state in (doc, _save(doc, 0, {p: 80 + p for p in first})):  # a half-scored pass is still not complete
        data = _data(bridge.archer_results(state))
        assert data["completed_passes"] == 0
        assert [
            (s["name"], s["total_score"], s["starting_handicap"], s["to_date_handicap"], s["rows"], s["average"])
            for s in data["sections"]
        ] == [(name, "0", f"{handicap:g}", "-", [], None) for name, _, handicap in NAMED_FOUR]


# --- Handicap updating: the pass starting handicap -----------------------------------------------


def _updating_pair(update=True):
    """An advanced two-archer, three-pass event (Ann 30, Ben 40), with handicap updating on or off.

    Parameters
    ----------
    update : bool, default=True
        Whether handicaps are updated (lookback 1, start weight 2).

    Returns
    -------
    dict
        The running document on pass 1; Ann and Ben meet in match 0 of every pass.
    """
    updating = UPDATING if update else {**UPDATING, "update_handicaps": "no"}
    return _start(TWO_ADVANCED, updating, setup_mode="advanced", total_arrows=36)


@pytest.mark.parametrize("update", [True, False], ids=["updating-on", "updating-off"])
def test_the_pass_starting_handicap_is_shown_only_when_updating(update):
    """show_start_handicap follows the setting, and the archer results CSV and the PDF have the column only then."""
    # ports test_event_routes.py::test_the_match_page_table_has_a_pass_starting_handicap_column_when_updating (the column)
    # ports test_event_routes.py::test_with_updating_off_the_tables_keep_five_columns_and_no_such_text_appears
    # ports test_integration.py::test_the_same_event_with_updating_off_has_no_pass_starting_handicap_anywhere
    doc = _save(_advance(_save(_updating_pair(update), 0, {0: 80, 1: 100})), 0, {0: 100, 1: 99})
    for data in (_data(bridge.match(doc, 0)), _data(bridge.results(doc)), _data(bridge.archer_results(doc))):
        assert data["show_start_handicap"] is update
    header = _csv(doc, "archer_results_csv")[0]
    assert ("Pass starting handicap" in header) is update
    assert len(header) == (10 if update else 9)
    assert ("Pass starting handicap" in _pdf_text(doc)) is update


def test_each_pass_shows_its_own_starting_handicap_and_a_correction_never_changes_it():
    """Pass 1 starts from the entered handicaps and pass 2 from the updated ones; later passes and corrections leave a shown value alone."""
    # ports test_event_routes.py::test_the_match_page_table_has_a_pass_starting_handicap_column_when_updating
    # ports test_event_routes.py::test_the_results_page_tables_show_each_passes_own_starting_handicap_grouped_by_match
    # ports test_event_routes.py::test_a_shown_starting_handicap_never_changes_after_later_passes_or_a_correction
    # ports test_event_routes.py::test_no_scoring_page_shows_an_updated_handicap_or_the_updating_settings (handicaps as entered)
    doc = _save(_updating_pair(), 0, {0: 80, 1: 100})
    assert [r["start_handicap"] for r in _data(bridge.match(doc, 0))["rows"]] == ["30.0", "40.0"]
    doc = _save(_advance(doc), 0, {0: 100, 1: 99})
    event = _event(doc)
    pass_2 = [f"{event.handicap_for(i, 1):.1f}" for i in (0, 1)]
    assert [r["start_handicap"] for r in _data(bridge.match(doc, 0))["rows"]] == pass_2
    assert pass_2[0] != "30.0"  # Ann's poor first pass moved the handicap her second pass started from
    doc = _save(doc, 0, {0: 60, 1: 118})  # a correction to pass 2's scores
    assert [r["start_handicap"] for r in _data(bridge.match(doc, 0))["rows"]] == pass_2
    data = _data(bridge.results(doc))
    starts = [[r["start_handicap"] for group in p["groups"] for r in group] for p in data["passes"]]
    assert starts == [["30.0", "40.0"], pass_2]
    assert [len(p["groups"]) for p in data["passes"]] == [1, 1]
    assert sorted(row["starting_handicap"] for row in data["leaderboard"]) == ["30", "40"]  # as entered


def test_each_percentile_is_judged_against_the_pass_starting_handicap():
    """Every recorded percentile comes from that pass's handicap, which is not the entered one once updated."""
    # ports test_event_routes.py::test_the_percentile_in_a_row_was_judged_against_the_shown_starting_handicap
    # ports test_event_routes.py::test_an_advanced_event_with_updating_plays_through_with_percentiles_from_the_updated_handicaps
    doc = _updating_pair()
    for pass_index, scores in enumerate(({0: 80, 1: 100}, {0: 100, 1: 99}, {0: 105, 1: 104})):
        doc = _save(doc, 0, scores)
        if pass_index < 2:
            doc = _advance(doc)
    assert doc["status"] == "complete"
    for command in (bridge.overview, bridge.results, bridge.archer_results):
        _data(command(doc))
    event = _event(doc)

    def distribution(handicap, archer):
        return stats.n_pass_score_distribution(stats.per_arrow_pmf(handicap, event.target_for(archer)), 12)

    for r in event.results:
        shown = event.handicap_for(r.archer_index, r.rotation_index)
        assert r.percentile == pytest.approx(stats.percentile(distribution(shown, r.archer_index), r.score))
    ann_pass_2 = next(r for r in event.results if r.rotation_index == 1 and r.archer_index == 0)
    assert ann_pass_2.percentile != pytest.approx(stats.percentile(distribution(30, 0), 100))


def test_a_full_advanced_event_with_updating_agrees_across_outputs_and_exports():
    """Moving handicaps drive the percentiles; the to-date handicap is the whole-round one; the leaderboard, CSVs and PDF agree and carry the export time."""
    # ports test_integration.py::test_full_advanced_event_with_updating_agrees_across_pages_exports_and_archeryutils
    updating = {"update_handicaps": "yes", "n_lookback": "2", "start_weight": "3"}
    doc = _start(ADVANCED_FOUR, updating, setup_mode="advanced", total_arrows=36)
    max_scores = [_event(doc).max_score_for(i) for i in range(4)]
    doc = _play(doc, lambda p, pass_index: int(max_scores[p] * 0.6) + 3 * (pass_index + 1) + p)
    event = _event(doc)
    assert (event.update_handicaps, event.n_lookback, event.start_weight, event.is_complete) == (True, 2, 3, True)
    for r in event.results:
        expected = stats.percentile(event.distribution_for(r.archer_index, r.rotation_index), r.score)
        assert r.percentile == pytest.approx(expected)
    assert any(event.handicap_for(i, 2) != event.archers[i].handicap for i in range(4))

    sections = outputs.archer_results(event)
    for section in sections:
        whole = au_rounds.Round("whole", [au_rounds.Pass(36, event.target_for(section.archer_index))])
        expected = float(stats._AGB_SCHEME.handicap_from_score(section.total_score, whole))
        assert section.arrows_shot == 36 and section.to_date_handicap == pytest.approx(expected)

    board = outputs.leaderboard(event)
    shown = _data(bridge.results(doc))["leaderboard"]
    assert [
        (r["rank"], r["name"], r["points"], r["passes_decided"], r["starting_handicap"], r["to_date_handicap"]) for r in shown
    ] == [
        (str(r.rank), r.name, str(r.points), str(r.passes_decided), f"{r.starting_handicap:g}", f"{r.to_date_handicap:.1f}")
        for r in board
    ]
    names = [_data(bridge.export(doc, kind, NOW))["filename"] for kind in ("leaderboard_csv", "archer_results_csv", "results_pdf")]
    assert names == ["leaderboard_20261004-153012.csv", "archer-results_20261004-153012.csv", "results_20261004-153012.pdf"]
    board_rows = _csv(doc, "leaderboard_csv")
    assert board_rows[0][-1] == "Exported" and {r[-1] for r in board_rows[1:]} == {STAMP}
    assert [r[4:6] for r in board_rows[1:]] == [[f"{r.starting_handicap:g}", f"{r.to_date_handicap:.1f}"] for r in board]
    archer_rows = _csv(doc, "archer_results_csv")
    assert len(archer_rows) == 1 + 12 and {r[-1] for r in archer_rows[1:]} == {STAMP}
    pdf_text = _pdf_text(doc)
    assert f"Exported {STAMP}" in pdf_text
    for section in sections:
        mine = [r for r in archer_rows[1:] if r[0] == section.name]
        assert {(r[1], r[2]) for r in mine} == {(f"{section.handicap:g}", f"{section.to_date_handicap:.1f}")}
        assert (
            f"{section.name} - total score {section.total_score} - starting handicap {section.handicap:g}"
            f" - to-date handicap {section.to_date_handicap:.1f}"
        ) in pdf_text


def test_a_full_60_arrow_updating_event_shows_the_same_pass_starting_handicaps_everywhere():
    """Default lookback 4 and start weight 5; the final pass uses all four earlier passes; tables, CSV, PDF and legend agree."""
    # ports test_integration.py::test_full_60_arrow_updating_event_shows_the_same_pass_starting_handicaps_everywhere
    # ports test_event_routes.py::test_submitting_stage_2_with_the_defaults_untouched_stores_lookback_4_and_start_weight_5
    stage1 = _data(bridge.apply_stage1(_fresh(), _form(n_archers=4, total_arrows=60, setup_mode="advanced")))
    defaults = {"n_lookback": _data(bridge.options())["defaults"]["n_lookback"], "start_weight": stage1["passes_per_archer"]}
    assert defaults == {"n_lookback": 4, "start_weight": 5}
    updating = {"update_handicaps": "yes", **defaults}
    doc = _data(bridge.apply_stage2(stage1["document"], _rows(ADVANCED_FOUR), updating, SEED))["document"]
    doc["assignment"] = list(range(4))
    doc = _data(bridge.start_event(doc))["document"]
    assert (doc["setup"]["n_lookback"], doc["setup"]["start_weight"]) == (4, 5)
    max_scores = [_event(doc).max_score_for(i) for i in range(4)]
    doc = _play(doc, lambda p, pass_index: int(max_scores[p] * (0.5 + 0.04 * (pass_index + 1))) + p)
    event = _event(doc)
    assert len(event.schedule) == 5 and event.is_complete

    # The final pass uses every earlier pass (m = 4, weight 5): (5 H0 + 4 H_recent) / 9.
    for i in range(4):
        last_four = [r.score for r in event.results if r.archer_index == i and r.rotation_index < 4]
        assert len(last_four) == 4
        recent = stats.equivalent_handicap(sum(last_four), 48, event.target_for(i))
        expected = (5 * event.archers[i].handicap + 4 * recent) / 9
        assert event.handicap_for(i, 4) == pytest.approx(min(max(expected, 0), 150))

    def start(i, rotation):
        return f"{event.handicap_for(i, rotation):.1f}"

    names = {a.name: i for i, a in enumerate(event.archers)}
    passes = _data(bridge.results(doc))["passes"]
    assert len(passes) == 5
    for entry in passes:
        rows = [r for group in entry["groups"] for r in group]
        assert [r["start_handicap"] for r in rows] == [start(names[r["archer"]], entry["pass_index"]) for r in rows]

    shown = _data(bridge.archer_results(doc))["sections"]
    csv_rows = _csv(doc, "archer_results_csv")
    assert csv_rows[0][7] == "Pass starting handicap" and len(csv_rows) == 1 + 20
    pdf_text = _pdf_text(doc)
    assert pdf_text.count("Pass starting handicap") == 4
    for section in outputs.archer_results(event):
        i = section.archer_index
        assert [r["start_handicap"] for r in shown[i]["rows"]] == [start(i, p) for p in range(5)]
        assert [r[7] for r in csv_rows[1:] if r[0] == section.name] == [start(i, p) for p in range(5)]
        average = f"{section.averages.start_handicap:.1f}"
        assert shown[i]["average"]["start_handicap"] == average
        assert average in pdf_text

    # The chart legend shows the handicap the current pass's curve is built from.
    a, b = event.matches(4)[0]
    payload = _data(bridge.pair_chart(doc, a, b))
    assert payload["archer_a"]["legend"] == f"{event.archers[a].name} (handicap {start(a, 4)})"
    assert payload["archer_b"]["legend"] == f"{event.archers[b].name} (handicap {start(b, 4)})"


# --- Exports -------------------------------------------------------------------------------------


def test_exports_have_the_flask_file_names_types_and_header_rows():
    """Each export is named with the export time; the CSVs start with their header rows and the PDF is a PDF."""
    # ports test_integration.py::test_full_advanced_event_with_updating_agrees_across_pages_exports_and_archeryutils (file names)
    doc = _save(_start(TWO_ARCHERS, total_arrows=12), 0, {0: 100, 1: 60})
    files = {kind: _data(bridge.export(doc, kind, NOW)) for kind in ("leaderboard_csv", "archer_results_csv", "results_pdf")}
    assert [(f["filename"], f["mime_type"], f["encoding"]) for f in files.values()] == [
        ("leaderboard_20261004-153012.csv", "text/csv", "utf-8"),
        ("archer-results_20261004-153012.csv", "text/csv", "utf-8"),
        ("results_20261004-153012.pdf", "application/pdf", "base64"),
    ]
    assert base64.b64decode(files["results_pdf"]["content"]).startswith(b"%PDF-")
    assert _csv(doc, "leaderboard_csv")[0] == [
        "Rank", "Archer", "Points", "Passes decided", "Starting handicap", "To-date handicap", "Exported",
    ]
    assert _csv(doc, "archer_results_csv")[0] == [
        "Archer", "Starting handicap", "To-date handicap", "Pass", "Opponent", "Score", "Percentile (%)",
        "Handicap of score", "Exported",
    ]


def test_after_the_last_pass_every_output_and_export_agrees():
    """The leaderboard, archer results, both CSVs and the PDF all say the same thing."""
    # ports test_integration.py::test_after_the_last_pass_every_output_and_export_agrees_with_the_event
    doc = _start(ADVANCED_FOUR, setup_mode="advanced", total_arrows=36)
    max_scores = [_event(doc).max_score_for(i) for i in range(4)]
    doc = _play(doc, lambda p, pass_index: int(max_scores[p] * 0.55) + 2 * (pass_index + 1) + p)
    event = _event(doc)
    board = outputs.leaderboard(event)
    assert sum(r.points for r in board) == 6  # 2 decided matches in each of 3 passes
    expected_board = [
        [str(r.rank), r.name, str(r.points), str(r.passes_decided), f"{r.starting_handicap:g}", f"{r.to_date_handicap:.1f}"]
        for r in board
    ]
    keys = ("rank", "name", "points", "passes_decided", "starting_handicap", "to_date_handicap")
    assert [[row[k] for k in keys] for row in _data(bridge.results(doc))["leaderboard"]] == expected_board
    assert [row[:6] for row in _csv(doc, "leaderboard_csv")[1:]] == expected_board

    archer_csv = _csv(doc, "archer_results_csv")[1:]
    pdf_text = _pdf_text(doc)
    shown = _data(bridge.archer_results(doc))["sections"]
    for section, shown_section in zip(outputs.archer_results(event), shown, strict=True):
        to_date = f"{section.to_date_handicap:.1f}"
        assert (shown_section["name"], shown_section["total_score"], shown_section["to_date_handicap"]) == (
            section.name, str(section.total_score), to_date,
        )
        assert len(shown_section["rows"]) == 3 and shown_section["average"] is not None
        assert f"{section.name} - total score {section.total_score} - starting handicap" in pdf_text
        mine = [row for row in archer_csv if row[0] == section.name]
        assert {(r[1], r[2]) for r in mine} == {(f"{section.handicap:g}", to_date)}
        assert [(r[3], r[4], r[5]) for r in mine] == [(str(row.pass_number), row.opponent, str(row.score)) for row in section.rows]
        assert [r[6] for r in mine] == [f"{row.percentile * 100:.1f}" for row in section.rows]


# --- The distribution chart ----------------------------------------------------------------------


def _curve(payload, side):
    """A chart payload's curve as {score: probability}.

    Parameters
    ----------
    payload : dict
        A `pair_chart` payload.
    side : str
        "distribution_a" or "distribution_b".

    Returns
    -------
    dict[int, float]
        Score -> probability.
    """
    return {point["x"]: point["y"] for point in payload[side]}


def _differs(curve_1, curve_2):
    """Whether two curves give a different probability at some score both cover.

    The x-range grows as scores accumulate, so only the values at shared scores show whether
    the distribution itself changed.

    Parameters
    ----------
    curve_1, curve_2 : dict[int, float]
        Curves from `_curve`.

    Returns
    -------
    bool
        True if they differ at a shared score.
    """
    return any(curve_1[x] != pytest.approx(curve_2[x]) for x in curve_1.keys() & curve_2.keys())


def test_the_pair_chart_before_and_after_the_first_scored_pass():
    """Before scoring the payload has both curves and the legends with the entered handicaps; then it gains the scored pass."""
    # ports test_event_routes.py::test_graph_view_match_page_renders_chart_even_before_any_scoring
    # ports test_event_routes.py::test_graph_view_match_page_chart_gains_the_scored_pass
    # ports test_event_routes.py::test_pair_chart_page_renders_for_a_shared_pair
    # ports test_event_routes.py::test_match_page_heading_and_labels_are_names_only_and_only_the_chart_legend_has_handicaps (the legend)
    doc = _start([("Alice", "Recurve", 15), ("Bob", "Compound", 22.5)], total_arrows=12)
    before = _data(bridge.pair_chart(doc, 0, 1))
    assert before["archer_a"] == {"name": "Alice", "legend": "Alice (handicap 15)", "passes": []}
    assert before["archer_b"] == {"name": "Bob", "legend": "Bob (handicap 22.5)", "passes": []}
    assert before["distribution_a"] and before["distribution_b"]
    after = _data(bridge.pair_chart(_save(doc, 0, {0: 100, 1: 60}), 0, 1))
    assert after["archer_a"]["passes"] == [{"index": 0, "score": 100}]
    assert after["archer_b"]["passes"] == [{"index": 0, "score": 60}]
    assert after["current_pass"] == 0


def test_the_pair_chart_lists_earlier_scores_of_a_pair_that_has_not_met():
    """Pass 2's pair has not met, but both archers' pass-1 scores are listed and inside the x-range."""
    # ports test_integration.py::test_chart_shows_earlier_scores_of_a_pair_that_has_not_met_and_covers_extreme_scores
    doc = _start([(f"A{i}", "Recurve", 20 + 10 * i) for i in range(4)], total_arrows=36)
    event = _event(doc)
    first, second = event.matches(0)
    doc = _save(doc, 0, {first[0]: 5, first[1]: 118})  # far outside the curves' usual range
    doc = _advance(_save(doc, 1, {p: 90 + p for p in second}))
    a, b = event.matches(1)[0]
    assert frozenset((a, b)) not in {frozenset(m) for m in event.matches(0)}  # a genuinely new pairing
    payload = _data(bridge.pair_chart(doc, a, b))
    shown = {p["score"] for side in ("archer_a", "archer_b") for p in payload[side]["passes"]}
    expected = {r.score for r in _event(doc).results if r.archer_index in (a, b)}
    assert shown == expected and len(expected) == 2
    assert payload["current_pass"] == 1
    assert all(payload["x_min"] <= score <= payload["x_max"] for score in shown)
    assert payload["archer_a"]["legend"] == f"A{a} (handicap {20 + 10 * a})"


@pytest.mark.parametrize("update", [True, False], ids=["updating-on", "updating-off"])
def test_the_plotted_curves_and_legends_follow_each_passes_handicap(update):
    """With updating each pass's curve and legend come from that pass's handicap; without it the curve never changes."""
    # ports test_integration.py::test_with_updating_on_each_archers_plotted_curve_changes_from_pass_to_pass_and_matches_the_model
    # ports test_integration.py::test_with_updating_off_the_plotted_curve_is_the_same_in_every_pass
    # ports test_integration.py::test_the_legend_handicap_and_the_plotted_curve_always_agree
    # ports test_integration.py::test_the_pair_history_page_also_plots_the_current_passes_curve
    # ports test_integration.py::test_markers_of_earlier_passes_are_drawn_against_the_current_curve_not_the_one_they_were_judged_by
    doc = _updating_pair(update)
    payloads = []
    for pass_index, (ann, ben) in enumerate([(80, 100), (95, 99), (100, 104)]):
        payloads.append(_data(bridge.pair_chart(doc, 0, 1)))  # as the scorer sees it, before scoring the pass
        doc = _save(doc, 0, {0: ann, 1: ben})
        if pass_index < 2:
            doc = _advance(doc)
    event = _event(doc)
    assert [p["current_pass"] for p in payloads] == [0, 1, 2]
    for side, archer, name in (("a", 0, "Ann"), ("b", 1, "Ben")):
        curves = [_curve(p, f"distribution_{side}") for p in payloads]
        pairs = ((curves[0], curves[1]), (curves[1], curves[2]), (curves[0], curves[2]))
        assert [_differs(c1, c2) for c1, c2 in pairs] == [update] * 3
        for rotation, (payload, curve) in enumerate(zip(payloads, curves, strict=True)):
            handicap = event.handicap_for(archer, rotation)
            legend = f"{name} (handicap {handicap:.1f})" if update else f"{name} (handicap {handicap:g})"
            assert payload[f"archer_{side}"]["legend"] == legend
            distribution = event.distribution_for(archer, rotation)
            assert all(y == pytest.approx(distribution.get(float(x), 0.0)) for x, y in curve.items())
    # Pass 3's payload marks the scores of passes 1 and 2 against pass 3's curve, one curve per archer.
    assert [p["index"] for p in payloads[2]["archer_a"]["passes"]] == [0, 1]
    if update:
        def mean(curve):
            return sum(x * y for x, y in curve.items()) / sum(curve.values())

        # Ann scored poorly in pass 1, so her pass-2 curve sits lower (a higher handicap).
        assert mean(_curve(payloads[1], "distribution_a")) < mean(_curve(payloads[0], "distribution_a"))
        assert payloads[0]["archer_a"]["legend"] == "Ann (handicap 30.0)"
