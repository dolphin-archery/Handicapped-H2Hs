"""Pyodide compatibility gate: one scripted run of the h2h core (UISpec.md section 8, task UI-1).

The same file runs natively and inside Pyodide. Run natively from the repository root with
`uv run web/scripts/pyodide-gate/scenario.py` to (re)write `golden.json` next to this file;
`run-gate.mjs` loads it into Pyodide, calls `result_json`, and compares the two with
`compare_json`. It drives the existing modules directly (no bridge exists yet): two scripted
4-archer events (simple setup with a tie-break, a zero score and a corrected score; advanced
setup with per-archer targets and handicap updating), the leaderboard and archer results, both
CSV exports, the PDF export, a pair chart payload and the handicap calculator.
"""

from __future__ import annotations

import hashlib
import json
import math
import platform
import re
import sys
import zlib
from dataclasses import asdict
from datetime import datetime
from importlib import metadata
from pathlib import Path

try:
    import h2h  # noqa: F401  (already importable inside Pyodide, where the runner adds it)
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # native run from the repo

from h2h import chart_data, exports, models, outputs, stats
from h2h.models import Archer, Bowstyle, Event, TargetSetup
from h2h.rotation import build_schedule

# A fixed export time, so the CSVs and the PDF text are the same on every run.
EXPORT_TIME = datetime(2026, 10, 4, 15, 30, 12)

# Relative tolerance for comparing floats between native Python and Pyodide (UI-1).
REL_TOLERANCE = 1e-9

GOLDEN_PATH = Path(__file__).with_name("golden.json")

# Scripted scores per pass: one entry per match, `(scores, closest)`, in schedule order.
# The circle-method schedule for 4 archers is (0,3),(1,2) / (0,2),(3,1) / (0,1),(2,3), repeated.
SIMPLE_PASSES = [
    [({0: 100, 3: 100}, 3), ({1: 110, 2: 85}, None)],  # Ann and Dan tie: closest to the middle
    [({0: 95, 2: 90}, None), ({3: 102, 1: 112}, None)],
    [({0: 104, 1: 108}, None), ({2: 80, 3: 99}, None)],
    [({0: 98, 3: 101}, None), ({1: 113, 2: 0}, None)],  # a score of 0 has no handicap
    [({0: 91, 2: 70}, None), ({3: 100, 1: 115}, None)],
]
ADVANCED_PASSES = [
    [({0: 44, 3: 21}, None), ({1: 52, 2: 30}, None)],
    [({0: 40, 2: 33}, None), ({3: 24, 1: 55}, None)],
    [({0: 47, 1: 50}, None), ({2: 28, 3: 19}, None)],
    [({0: 38, 3: 25}, None), ({1: 56, 2: 35}, None)],
    [({0: 45, 2: 31}, None), ({3: 22, 1: 53}, None)],
]


def _pdf_summary(pdf: bytes) -> dict:
    """Summarise a PDF so it can be compared across runs and Python builds.

    The raw bytes differ between runs (fpdf2 stamps a creation date) and may differ between
    zlib builds (compressed streams), so this compares the decompressed stream contents,
    which hold every drawn character and position, instead.

    Parameters
    ----------
    pdf : bytes
        The PDF file.

    Returns
    -------
    dict
        `{"header": first 8 bytes as text, "pages": page count, "content_sha256": hex digest
        of the decompressed streams joined in file order}`.
    """
    streams = re.findall(rb"stream\r?\n(.*?)\r?\nendstream", pdf, re.DOTALL)
    content = b""
    for stream in streams:
        try:
            content += zlib.decompress(stream)
        except zlib.error:
            content += stream  # an uncompressed stream
    return {
        "header": pdf[:8].decode("latin-1"),
        "pages": len(re.findall(rb"/Type\s*/Page\b", pdf)),
        "content_sha256": hashlib.sha256(content).hexdigest(),
    }


def _pass_snapshot(event: Event) -> dict:
    """Everything the scorer sees for the event's current pass.

    Parameters
    ----------
    event : h2h.models.Event
        The event, with its current pass fully scored.

    Returns
    -------
    dict
        `{"pass_index", "handicaps": per-archer handicap for this pass, "max_scores": per-archer
        maximum pass score, "tables": one list of `PassTableRow` dicts per match}`.
    """
    r = event.current_rotation_index
    return {
        "pass_index": r,
        "handicaps": [event.handicap_for(i) for i in range(len(event.archers))],
        "max_scores": [event.max_score_for(i) for i in range(len(event.archers))],
        "tables": [
            [asdict(row) for row in outputs.pass_table_rows(event, event.match_results(r, m))]
            for m in event.matches(r)
        ],
    }


def _run_event(event: Event, passes: list, chart_pair: tuple[int, int]) -> dict:
    """Score a scripted event pass by pass and collect every output.

    Parameters
    ----------
    event : h2h.models.Event
        A freshly built event.
    passes : list[list[tuple[dict[int, int], int | None]]]
        Per pass, one `(scores, closest)` per match. A match with `closest` set is first
        recorded without it (which must raise `TieBreakRequired`), then with it.
    chart_pair : tuple[int, int]
        The two archers whose pair chart payload is built at the end.

    Returns
    -------
    dict
        The schedule, the tie-break and validation messages, a snapshot of every pass, the
        recorded results, the outputs, both CSVs, the PDF summary and the chart payload.
    """
    found: dict = {"schedule": [asdict(rotation) for rotation in event.schedule]}
    snapshots = []
    for index, matches in enumerate(passes):
        for scores, closest in matches:
            if closest is not None:
                try:
                    event.record_match(scores)
                except stats.TieBreakRequired as error:
                    found["tie_break_message"] = str(error)
                else:
                    raise AssertionError("The scripted tie did not require a tie-break.")
            event.record_match(scores, closest=closest)
        if index == len(passes) - 1:
            # Correct the first match of the final pass, as a scorer fixing a typo would.
            first = dict(matches[0][0])
            first[next(iter(first))] -= 1
            event.record_match(first, closest=matches[0][1])
        snapshots.append(_pass_snapshot(event))
        if index < len(passes) - 1:
            event.advance()

    try:
        event.advance()
    except ValueError as error:
        found["advance_message"] = str(error)
    try:
        event.record_match({p: 10_000 for p in event.matches(event.current_rotation_index)[0]})
    except ValueError as error:
        found["invalid_score_message"] = str(error)

    found.update(
        passes=snapshots,
        is_complete=event.is_complete,
        completed_passes=event.completed_passes,
        results=[asdict(r) for r in event.results],
        pairwise=[{**asdict(p), "outcome": p.outcome} for p in event.all_pairwise_results()],
        leaderboard=[asdict(row) for row in outputs.leaderboard(event)],
        archer_results=[asdict(section) for section in outputs.archer_results(event)],
        leaderboard_csv=exports.leaderboard_csv(event, EXPORT_TIME),
        archer_results_csv=exports.archer_results_csv(event, EXPORT_TIME),
        pdf=_pdf_summary(exports.results_pdf(event, EXPORT_TIME)),
        pair_chart=chart_data.build_pair_chart_data(event, *chart_pair),
    )
    return found


def run_scenario() -> dict:
    """Run both scripted events and the calculator cases.

    Returns
    -------
    dict
        `{"environment": versions (not compared), "outputs": {"simple": ..., "advanced": ...,
        "calculator": ...}}`.
    """
    simple = Event(
        [
            Archer("Ann", 35.0, Bowstyle.RECURVE),
            Archer("Ben", 20.0, Bowstyle.COMPOUND),
            Archer("Cat", 50.0, Bowstyle.BAREBOW),
            Archer("Dan", 35.0, Bowstyle.RECURVE),
        ],
        12,
        TargetSetup.parse("20yd", 60),
        build_schedule(4, 60 // 12),
    )
    advanced = Event(
        [
            Archer("Ann", 40.0, Bowstyle.RECURVE, TargetSetup.parse_advanced("70m", 122, "10_zone")),
            Archer("Ben", 25.0, Bowstyle.COMPOUND, TargetSetup.parse_advanced("50m", 80, "10_zone_6_ring")),
            Archer("Cat", 70.0, Bowstyle.LONGBOW, TargetSetup.parse_advanced("60yd", 122, "5_zone")),
            Archer("Dan", 55.0, Bowstyle.BAREBOW, TargetSetup.parse_advanced("20yd", 40, "Worcester")),
        ],
        6,
        None,
        build_schedule(4, 30 // 6),
        update_handicaps=True,
        n_lookback=models.DEFAULT_N_LOOKBACK,
        start_weight=5,
    )
    calculator = {
        "rounds": {kind: list(models.calculator_rounds(kind)) for kind in (models.INDOOR, models.OUTDOOR)},
        "portsmouth_compound_570": stats.handicap_for_round_score(
            570, models.calculator_round(models.INDOOR, "portsmouth", True)
        ),
        "wa720_70_600": stats.handicap_for_round_score(
            600, models.calculator_round(models.OUTDOOR, "wa720_70", False)
        ),
    }
    return {
        "environment": {
            "python": platform.python_version(),
            "platform": sys.platform,
            "numpy": metadata.version("numpy"),
            "archeryutils": metadata.version("archeryutils"),
            "fpdf2": metadata.version("fpdf2"),
        },
        "outputs": {
            "simple": _run_event(simple, SIMPLE_PASSES, (0, 3)),
            "advanced": _run_event(advanced, ADVANCED_PASSES, (1, 2)),
            "calculator": calculator,
        },
    }


def result_json() -> str:
    """str: `run_scenario()` as JSON text (NaN and infinity are refused)."""
    return json.dumps(run_scenario(), indent=1, allow_nan=False)


def _compare(golden: object, actual: object, where: str, report: dict) -> None:
    """Compare two decoded JSON values recursively, recording every difference in `report`.

    Booleans, integers, strings and None must be equal and of the same type; floats must
    agree within `REL_TOLERANCE` (relative, no absolute tolerance).

    Parameters
    ----------
    golden, actual : object
        The values to compare (dicts, lists, str, int, float, bool or None).
    where : str
        The path to these values, for messages, e.g. "outputs.simple.results[3].percentile".
    report : dict
        Updated in place: `mismatches` (list[str]) is appended to, `floats_compared` (int) and
        `max_relative_difference` (float) are updated.
    """
    if type(golden) is not type(actual):
        report["mismatches"].append(f"{where}: type {type(golden).__name__} != {type(actual).__name__}")
    elif isinstance(golden, dict):
        if list(golden) != list(actual):
            report["mismatches"].append(f"{where}: keys {list(golden)} != {list(actual)}")
        for key in golden:
            if key in actual:
                _compare(golden[key], actual[key], f"{where}.{key}", report)
    elif isinstance(golden, list):
        if len(golden) != len(actual):
            report["mismatches"].append(f"{where}: length {len(golden)} != {len(actual)}")
        for i, (g, a) in enumerate(zip(golden, actual)):
            _compare(g, a, f"{where}[{i}]", report)
    elif isinstance(golden, float):
        report["floats_compared"] += 1
        if golden != actual:
            scale = max(abs(golden), abs(actual))
            relative = abs(golden - actual) / scale
            report["max_relative_difference"] = max(report["max_relative_difference"], relative)
            if not math.isclose(golden, actual, rel_tol=REL_TOLERANCE, abs_tol=0.0):
                report["mismatches"].append(f"{where}: {golden!r} != {actual!r} (relative {relative:.3g})")
    elif golden != actual:
        report["mismatches"].append(f"{where}: {golden!r} != {actual!r}")


def compare_json(golden_text: str, actual_text: str) -> str:
    """Compare the `outputs` of two scenario results.

    Parameters
    ----------
    golden_text, actual_text : str
        `result_json()` output of the native run (golden) and of the run being checked.

    Returns
    -------
    str
        JSON text of `{"mismatches": list[str], "floats_compared": int,
        "max_relative_difference": float, "golden_environment": dict,
        "actual_environment": dict}`; the gate passes when `mismatches` is empty.
    """
    golden = json.loads(golden_text)
    actual = json.loads(actual_text)
    report = {"mismatches": [], "floats_compared": 0, "max_relative_difference": 0.0}
    _compare(golden["outputs"], actual["outputs"], "outputs", report)
    report["golden_environment"] = golden["environment"]
    report["actual_environment"] = actual["environment"]
    return json.dumps(report, indent=1)


if __name__ == "__main__":
    text = result_json()
    GOLDEN_PATH.write_text(text + "\n", encoding="utf-8", newline="\n")
    print(f"Wrote {GOLDEN_PATH} ({len(text)} characters).")
