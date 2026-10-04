"""Golden bridge fixtures for the parity tests (UISpec.md section 8, task UI-5).

Each scenario drives an event through `h2h.bridge.call` exactly as the browser will (JSON text in
and out), with a fixed draw seed and a fixed export time, and records every step as
`{"command", "payload", "result"}`. `tests/test_bridge_fixtures.py` regenerates them and
compares them with the committed files in `tests/fixtures/bridge/`; the Pyodide parity tests
(UI-7), the calculator view (UI-10) and the exports (UI-18) replay the same payloads and compare
their results with these.

One normalisation applies to results, wherever they are compared: a successful `export` of kind
`results_pdf` has its `content` (base64 PDF bytes, which carry fpdf2's creation time and depend
on the zlib build) replaced by `pdf_summary` of those bytes: `{"header", "pages", "text"}`,
where `text` lists every string the PDF draws with `Tj`, in order.

Regenerate the files from the repository root with `uv run python -m tests.bridge_fixtures`.
"""

from __future__ import annotations

import base64
import json
import re
import zlib
from pathlib import Path

from h2h import bridge

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "bridge"
NOW = "2026-10-04T15:30:12"  # the fixed creation and export time
SEED = 4  # the fixed draw seed; a redraw uses SEED + 1

_STREAM = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.DOTALL)
_SHOWN_TEXT = re.compile(rb"\(((?:\\.|[^\\)])*)\)\s*Tj")
_ESCAPE = re.compile(rb"\\([()\\r])")

NO_UPDATING = {"update_handicaps": False}
SIMPLE_ROWS = [
    {"name": "Ann", "bowstyle": "Recurve", "handicap": "35"},
    {"name": "Ben", "bowstyle": "Compound", "handicap": "20"},
    {"name": "Cat", "bowstyle": "Barebow", "handicap": "50"},
    {"name": "Dan", "bowstyle": "Recurve", "handicap": "35"},
]
EVE = {"name": "Eve", "bowstyle": "Longbow", "handicap": "80"}
ADVANCED_ROWS = [
    {"name": "Ann", "bowstyle": "Recurve", "handicap": "40", "distance": "70m", "face_cm": "122", "face_type": "10_zone"},
    {"name": "Ben", "bowstyle": "Compound", "handicap": "25", "distance": "50m", "face_cm": "80",
     "face_type": "10_zone_6_ring"},
    {"name": "Cat", "bowstyle": "Longbow", "handicap": "70", "distance": "60yd", "face_cm": "122", "face_type": "5_zone"},
    {"name": "Dan", "bowstyle": "Barebow", "handicap": "55", "distance": "20yd", "face_cm": "40", "face_type": "Worcester"},
]
# Scores per pass by archer name: 12-arrow passes on the 20 yd simple setup ...
SIMPLE_SCORES = {
    "Ann": [100, 95, 104, 98, 91],
    "Ben": [110, 112, 108, 113, 115],
    "Cat": [85, 90, 80, 0, 70],
    "Dan": [100, 95, 104, 98, 91],
    "Eve": [60, 72, 55, 64, 70, 58],
}
# ... and 6-arrow passes on the advanced targets (maxima 60, 60, 54 and 30).
ADVANCED_SCORES = {
    "Ann": [44, 40, 47, 38, 45],
    "Ben": [52, 55, 50, 56, 53],
    "Cat": [30, 33, 28, 35, 31],
    "Dan": [21, 0, 19, 25, 22],
}


def pdf_summary(pdf: bytes) -> dict:
    """Summarise a PDF so that runs at different times and on different builds compare equal.

    Parameters
    ----------
    pdf : bytes
        The PDF file.

    Returns
    -------
    dict
        `{"header": the first 8 bytes as text, "pages": the page count, "text": every string
        drawn with the `Tj` operator, in file order, unescaped and decoded as Latin-1}`.
    """
    text = []
    for stream in _STREAM.findall(pdf):
        try:
            content = zlib.decompress(stream)
        except zlib.error:
            content = stream  # an uncompressed stream
        for shown in _SHOWN_TEXT.findall(content):
            unescaped = _ESCAPE.sub(lambda m: b"\r" if m.group(1) == b"r" else m.group(1), shown)
            text.append(unescaped.decode("latin-1"))
    return {
        "header": pdf[:8].decode("latin-1"),
        "pages": len(re.findall(rb"/Type\s*/Page\b", pdf)),
        "text": text,
    }


def normalise_result(command: str, payload: dict, result: dict) -> dict:
    """Apply the fixtures' one normalisation (see the module docstring) to a command's result.

    Parameters
    ----------
    command : str
        The command name.
    payload : dict
        Its arguments.
    result : dict
        The decoded envelope it returned.

    Returns
    -------
    dict
        `result`, with a PDF export's `content` replaced by its `pdf_summary`; otherwise
        unchanged.
    """
    if command == "export" and payload.get("kind") == "results_pdf" and result["ok"]:
        data = dict(result["data"])
        data["content"] = pdf_summary(base64.b64decode(data["content"]))
        return {**result, "data": data}
    return result


class _Recorder:
    """Calls bridge commands through `bridge.call` and records each step."""

    def __init__(self) -> None:
        """Start with no steps."""
        self.steps: list[dict] = []

    def __call__(self, command: str, **payload: object) -> dict:
        """Run and record one command.

        Parameters
        ----------
        command : str
            The command name.
        **payload : object
            Its keyword arguments.

        Returns
        -------
        dict
            The decoded envelope (before normalisation).

        Raises
        ------
        AssertionError
            If the command failed with an `internal` error (a bug, never a scripted outcome).
        """
        result = json.loads(bridge.call(command, json.dumps(payload, allow_nan=False)))
        if not result["ok"] and result["error"]["code"] == bridge.INTERNAL:
            raise AssertionError(f"{command} failed: {result['error']['message']}")
        self.steps.append({"command": command, "payload": payload, "result": normalise_result(command, payload, result)})
        return result


def _peek(command: str, **payload: object) -> dict:
    """Run a command without recording it (to look up positions while scripting)."""
    return json.loads(bridge.call(command, json.dumps(payload)))["data"]


def _start(rec: _Recorder, name: str, form: dict, rows: list[dict], updating: dict = NO_UPDATING) -> dict:
    """Record Stages 1 to 3 of an event: new document, both forms (with Stage 2's values), a redraw, the
    pairings and the start.

    Parameters
    ----------
    rec : _Recorder
        The recorder.
    name : str
        The scenario name (the event id is "fixture-<name>").
    form : dict
        The Stage 1 form.
    rows : list[dict]
        The Stage 2 rows.
    updating : dict, default=NO_UPDATING
        The handicap-updating choice.

    Returns
    -------
    dict
        The started event document.
    """
    doc = rec("new_document", event_id=f"fixture-{name}", now_iso=NOW)["data"]
    doc = rec("apply_stage1", doc=doc, form=form)["data"]["document"]
    rec("stage2_info", doc=doc)
    doc = rec("apply_stage2", doc=doc, archers=rows, updating=updating, seed=SEED)["data"]["document"]
    doc = rec("redraw", doc=doc, seed=SEED + 1)["data"]["document"]
    rec("pairings", doc=doc)
    return rec("start_event", doc=doc)["data"]["document"]


def _save(rec: _Recorder, doc: dict, match_index: int, by_name: dict[str, list[int]]) -> dict:
    """Record saving one match with the scripted scores, breaking a tie for the lower position.

    A tie is recorded as the refused save (`tiebreak_required`) followed by the save naming the
    lower position closest to the middle.

    Parameters
    ----------
    rec : _Recorder
        The recorder.
    doc : dict
        A started event document.
    match_index : int
        The match in the current pass.
    by_name : dict[str, list[int]]
        Each archer's score in every pass, by name.

    Returns
    -------
    dict
        The document after the save.
    """
    view = _peek("match", doc=doc, match_index=match_index)
    scores = {str(a["position"]): by_name[a["name"]][view["pass_index"]] for a in view["archers"]}
    result = rec("record_match", doc=doc, match_index=match_index, scores=scores, closest=None)
    if not result["ok"]:
        result = rec("record_match", doc=doc, match_index=match_index, scores=scores,
                     closest=min(a["position"] for a in view["archers"]))
    return result["data"]["document"]


def _play(rec: _Recorder, doc: dict, by_name: dict[str, list[int]]) -> dict:
    """Record a whole event: per pass the overview, one match view, every save, and the advance.

    Parameters
    ----------
    rec : _Recorder
        The recorder.
    doc : dict
        A started event document.
    by_name : dict[str, list[int]]
        Each archer's score in every pass, by name.

    Returns
    -------
    dict
        The document with every pass scored (status "complete").
    """
    while True:
        overview = rec("overview", doc=doc)["data"]
        rec("match", doc=doc, match_index=0)
        for i in range(overview["match_count"]):
            doc = _save(rec, doc, i, by_name)
        if overview["is_last"]:
            rec("overview", doc=doc)
            return doc
        doc = rec("advance", doc=doc)["data"]["document"]


def _outputs(rec: _Recorder, doc: dict, pair: tuple[int, int] = (0, 1)) -> None:
    """Record the results, the archer results, one pair chart and the three exports.

    Parameters
    ----------
    rec : _Recorder
        The recorder.
    doc : dict
        A started event document.
    pair : tuple[int, int], default=(0, 1)
        The two positions charted.
    """
    rec("results", doc=doc)
    rec("archer_results", doc=doc)
    rec("pair_chart", doc=doc, a=pair[0], b=pair[1])
    for kind in ("leaderboard_csv", "archer_results_csv", "results_pdf"):
        rec("export", doc=doc, kind=kind, now_iso=NOW)


def _simple_form(**changes: object) -> dict:
    """The Stage 1 form for 4 archers, 60 arrows in 12-arrow passes at 20 yd on a 60 cm face, with changes."""
    form = {"n_archers": "4", "total_arrows": "60", "n_pass": "12", "setup_mode": "simple",
            "distance": "20yd", "face_cm": "60", "shoot_byes": True}
    return {**form, **changes}


def simple(rec: _Recorder) -> None:
    """Simple setup: 4 archers, 36 arrows in 12-arrow passes (3 passes), one shared target."""
    doc = _play(rec, _start(rec, "simple", _simple_form(total_arrows="36"), SIMPLE_ROWS), SIMPLE_SCORES)
    _outputs(rec, doc)


def advanced(rec: _Recorder) -> None:
    """Advanced setup: per-archer face types, sizes and distances, 18 arrows in 6-arrow passes, no updating."""
    form = _simple_form(total_arrows="18", n_pass="6", setup_mode="advanced")
    doc = _play(rec, _start(rec, "advanced", form, ADVANCED_ROWS), ADVANCED_SCORES)
    _outputs(rec, doc, (1, 2))


def byes_shot(rec: _Recorder) -> None:
    """Five archers shooting byes: one solo match (no winner) in every pass."""
    form = _simple_form(n_archers="5", total_arrows="24", shoot_byes=True)
    doc = _play(rec, _start(rec, "byes_shot", form, [*SIMPLE_ROWS, EVE]), SIMPLE_SCORES)
    _outputs(rec, doc)


def byes_sat_out(rec: _Recorder) -> None:
    """Five archers sitting out their byes: the sit-out schedule, with its catch-up pass."""
    form = _simple_form(n_archers="5", total_arrows="24", shoot_byes="no")
    doc = _play(rec, _start(rec, "byes_sat_out", form, [*SIMPLE_ROWS, EVE]), SIMPLE_SCORES)
    _outputs(rec, doc)


def handicap_updating(rec: _Recorder) -> None:
    """Advanced setup with handicap updating (lookback 4, start weight 5) over 5 passes, with a score of 0."""
    form = _simple_form(total_arrows="30", n_pass="6", setup_mode="advanced")
    updating = {"update_handicaps": True, "n_lookback": "4", "start_weight": "5"}
    doc = _start(rec, "handicap_updating", form, ADVANCED_ROWS, updating)
    _outputs(rec, _play(rec, doc, ADVANCED_SCORES), (0, 3))


def tie_break(rec: _Recorder) -> None:
    """Two archers with the same handicap: a refused tie, the closest archer, re-saves, an unneeded closest."""
    rows = [{"name": "Ann", "bowstyle": "Recurve", "handicap": "30"}, {"name": "Ben", "bowstyle": "Recurve", "handicap": "30"}]
    doc = _start(rec, "tie_break", _simple_form(n_archers="2", total_arrows="36"), rows)
    tied = {"0": 90, "1": 90}
    rec("record_match", doc=doc, match_index=0, scores=tied, closest=None)  # refused: tiebreak_required
    rec("record_match", doc=doc, match_index=0, scores=tied, closest=7)  # refused: not in the match
    doc = rec("record_match", doc=doc, match_index=0, scores=tied, closest=1)["data"]["document"]
    rec("match", doc=doc, match_index=0)  # the saved tie-break stays shown
    untied = rec("record_match", doc=doc, match_index=0, scores={"0": 91, "1": 90}, closest=1)["data"]["document"]
    rec("match", doc=untied, match_index=0)  # no longer decided by the tie-break
    doc = rec("advance", doc=doc)["data"]["document"]
    doc = rec("record_match", doc=doc, match_index=0, scores={"0": 80, "1": 85}, closest=0)["data"]["document"]
    doc = rec("advance", doc=doc)["data"]["document"]
    doc = rec("record_match", doc=doc, match_index=0, scores={"0": 100, "1": 100}, closest=0)["data"]["document"]
    _outputs(rec, doc)


def complete_event(rec: _Recorder) -> None:
    """A full 5-pass event with refusals along the way, completion, a re-save and a validated document."""
    doc = rec("new_document", event_id="fixture-complete_event", now_iso=NOW)["data"]
    rec("overview", doc=doc)  # refused: not started
    rec("apply_stage1", doc=doc, form=_simple_form(n_pass="7"))  # refused: does not divide
    doc = rec("apply_stage1", doc=doc, form=_simple_form())["data"]["document"]
    bad_rows = [dict(row) for row in SIMPLE_ROWS]
    bad_rows[1]["handicap"] = "151"
    rec("apply_stage2", doc=doc, archers=bad_rows, updating=NO_UPDATING, seed=SEED)  # refused: row 2
    doc = rec("apply_stage2", doc=doc, archers=SIMPLE_ROWS, updating=NO_UPDATING, seed=SEED)["data"]["document"]
    rec("pairings", doc=doc)
    doc = rec("start_event", doc=doc)["data"]["document"]
    rec("advance", doc=doc)  # refused: pass not scored
    view = _peek("match", doc=doc, match_index=0)
    rec("record_match", doc=doc, match_index=0, scores={str(a["position"]): "121" for a in view["archers"]},
        closest=None)  # refused: out of range
    doc = _play(rec, doc, SIMPLE_SCORES)
    rec("advance", doc=doc)  # refused: final pass
    doc = _save(rec, doc, 1, {name: [s - 3 for s in scores] for name, scores in SIMPLE_SCORES.items()})
    rec("validate_document", raw=doc)
    _outputs(rec, doc)


def calculator(rec: _Recorder) -> None:
    """The options, then the calculator indoors, indoors with a compound bow, outdoors, and invalid input."""
    rec("options")
    rec("calculator", kind="indoor", round_codename="portsmouth", compound=False, score="550")
    rec("calculator", kind="indoor", round_codename="portsmouth", compound=True, score="570")
    rec("calculator", kind="outdoor", round_codename="wa720_70", compound=False, score="600")
    rec("calculator", kind="indoor", round_codename="portsmouth", compound=False, score="abc")


SCENARIOS = {
    "simple": simple,
    "advanced": advanced,
    "byes_shot": byes_shot,
    "byes_sat_out": byes_sat_out,
    "handicap_updating": handicap_updating,
    "tie_break": tie_break,
    "complete_event": complete_event,
    "calculator": calculator,
}


def generate(name: str) -> dict:
    """Run one scenario and return its fixture.

    Parameters
    ----------
    name : str
        A key of `SCENARIOS`.

    Returns
    -------
    dict
        `{"scenario", "description", "now_iso", "seed", "steps": [{"command", "payload",
        "result"}]}`, JSON-serialisable.
    """
    rec = _Recorder()
    SCENARIOS[name](rec)
    fixture = {
        "scenario": name,
        "description": SCENARIOS[name].__doc__,
        "now_iso": NOW,
        "seed": SEED,
        "steps": rec.steps,
    }
    return json.loads(json.dumps(fixture, allow_nan=False))  # plain JSON values, as read back from the file


def fixture_text(fixture: dict) -> str:
    """str: a fixture as the file's text (indented JSON with a final newline)."""
    return json.dumps(fixture, indent=1, ensure_ascii=False) + "\n"


def write_all() -> list[Path]:
    """(Re)write every fixture file.

    Returns
    -------
    list[pathlib.Path]
        The files written.
    """
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for name in SCENARIOS:
        path = FIXTURE_DIR / f"{name}.json"
        path.write_text(fixture_text(generate(name)), encoding="utf-8", newline="\n")
        written.append(path)
    return written


if __name__ == "__main__":
    for path in write_all():
        print(f"Wrote {path} ({path.stat().st_size} bytes).")
