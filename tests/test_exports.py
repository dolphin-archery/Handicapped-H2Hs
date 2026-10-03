"""Tests for h2h.exports (CSV and PDF) and the export routes."""

import csv
import io
import re
import tomllib
from pathlib import Path

import pypdf
import pytest

from h2h import exports, outputs
from h2h.app import create_app
from h2h.models import Archer, Bowstyle, Event
from h2h.rotation import build_schedule

from .helpers import PORTSMOUTH, make_state, score_current_pass

ROOT = Path(__file__).resolve().parent.parent


def make_event(names, rotations=None, n_pass=12, handicap_step=7):
    """An Event of the named archers (distinct handicaps) with a round-robin schedule."""
    archers = [Archer(n, 20 + handicap_step * i, Bowstyle.RECURVE) for i, n in enumerate(names)]
    n = len(names)
    rotations = rotations or (n if n % 2 else n - 1)
    return Event(archers, n_pass, PORTSMOUTH, build_schedule(n, rotations))


def play(event, upto=None, score_fn=lambda archer, i: 70 + 3 * archer + i):
    """Score the first `upto` passes (default all), advancing between them."""
    upto = len(event.schedule) if upto is None else upto
    for i in range(upto):
        for match in event.matches(i):
            event.record_match({p: score_fn(p, i) for p in match if p is not None})
        if i < len(event.schedule) - 1:
            event.advance()


def rows_of(text):
    """Parse CSV text into rows, the way a spreadsheet or pandas would."""
    return list(csv.reader(io.StringIO(text, newline="")))


def pdf_text(data):
    """All the text of a PDF, page by page joined."""
    reader = pypdf.PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() for page in reader.pages), len(reader.pages)


# --- dependencies ----------------------------------------------------------------------


def test_fpdf2_and_pypdf_are_declared_dependencies_and_import():
    """fpdf2 is a runtime dependency, pypdf a dev one; both import on this Python."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert any(d.startswith("fpdf2") for d in project["project"]["dependencies"])
    assert any(d.startswith("pypdf") for d in project["dependency-groups"]["dev"])
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    assert 'name = "fpdf2"' in lock and 'name = "pypdf"' in lock
    import fpdf  # noqa: F401


# --- CSV ---------------------------------------------------------------------------------


def test_leaderboard_csv_has_the_header_and_the_leaderboards_rows():
    """Rank,Archer,Points,Passes decided, one row per archer, equal to the on-page leaderboard."""
    event = make_event(["Ann", "Ben", "Cat", "Dan"])
    play(event)
    rows = rows_of(exports.leaderboard_csv(event))
    assert rows[0] == ["Rank", "Archer", "Points", "Passes decided"]
    expected = [
        [str(r.rank), r.name, str(r.points), str(r.passes_decided)] for r in outputs.leaderboard(event)
    ]
    assert rows[1:] == expected and len(expected) == 4


def test_archer_results_csv_is_a_tidy_table_without_average_rows():
    """One row per archer per completed pass, equal to the archer results, no summary rows."""
    event = make_event(["Ann", "Ben", "Cat", "Dan"])
    play(event)
    rows = rows_of(exports.archer_results_csv(event))
    assert rows[0] == [
        "Archer", "Handicap", "Pass", "Opponent", "Score", "Percentile (%)", "Handicap of score",
    ]
    expected = []
    for section in outputs.archer_results(event):
        for r in section.rows:
            expected.append(
                [section.name, f"{section.handicap:g}", str(r.pass_number), r.opponent, str(r.score),
                 f"{r.percentile * 100:.1f}", f"{r.handicap:.1f}"]
            )
    assert rows[1:] == expected and len(expected) == 12  # 4 archers x 3 passes
    assert not any("Average" in cell for row in rows for cell in row)


def test_a_name_with_a_comma_and_a_quote_round_trips():
    """Standard CSV quoting keeps awkward names intact."""
    event = make_event(['O"Brien, Sam', "Ben"], rotations=1)
    play(event)
    parsed = rows_of(exports.archer_results_csv(event))
    assert {row[0] for row in parsed[1:]} == {'O"Brien, Sam', "Ben"}
    assert {row[3] for row in parsed[1:]} == {'O"Brien, Sam', "Ben"}
    board = rows_of(exports.leaderboard_csv(event))
    assert {row[1] for row in board[1:]} == {'O"Brien, Sam', "Ben"}


def test_a_partly_scored_pass_is_not_in_the_csv_and_an_unscored_event_gives_just_the_header():
    """Only completed passes are exported."""
    event = make_event(["Ann", "Ben", "Cat", "Dan"])
    assert len(rows_of(exports.archer_results_csv(event))) == 1
    assert [r[2] for r in rows_of(exports.leaderboard_csv(event))[1:]] == ["0", "0", "0", "0"]

    first, second = event.matches(0)
    event.record_match({p: 80 + p for p in first})
    assert len(rows_of(exports.archer_results_csv(event))) == 1  # pass 1 is still incomplete
    event.record_match({p: 80 + p for p in second})
    assert len(rows_of(exports.archer_results_csv(event))) == 1 + 4


def test_csv_is_plain_utf8_without_a_byte_order_mark_and_numbers_are_plain():
    """Clean column names for pandas; percentiles are numbers; a zero score's handicap is empty."""
    event = make_event(["Zoë", "Ben"], rotations=2)
    event.record_match({0: 100, 1: 0})
    event.advance()
    event.record_match({0: 90, 1: 80})
    text = exports.archer_results_csv(event)
    assert not text.startswith("﻿")
    assert text.encode("utf-8").decode("utf-8") == text
    assert "Zoë" in text
    rows = rows_of(text)[1:]
    for row in rows:
        assert re.fullmatch(r"\d+\.\d", row[5]), row  # 59.8, no % sign
    zero_row = next(row for row in rows if row[0] == "Ben" and row[4] == "0")
    assert zero_row[6] == ""
    assert next(row for row in rows if row[4] == "90")[6] != ""


# --- PDF ---------------------------------------------------------------------------------


def test_pdf_is_a_valid_pdf_with_the_title_leaderboard_and_every_archer():
    """pypdf can read it and finds the title, headings, every name and the Average label."""
    event = make_event(["Ann", "Ben", "Cat", "Dan"])
    play(event)
    data = exports.results_pdf(event)
    assert data.startswith(b"%PDF-")
    text, pages = pdf_text(data)
    assert pages >= 1
    assert "Handicapped H2H results" in text
    assert "3 of 3 passes completed" in text
    for heading in ("Rank", "Archer", "Points", "Passes decided", "Pass", "Opponent", "Score", "Percentile"):
        assert heading in text
    for section in outputs.archer_results(event):
        assert f"{section.name} - total score {section.total_score} - handicap {section.handicap:g}" in text
    assert text.count("Average") == 4


def test_a_long_pdf_flows_onto_further_pages_with_each_archer_listed_once():
    """Eight archers over seven passes: more than one page, one heading per archer."""
    names = [f"Archer{i}" for i in range(8)]
    event = make_event(names)
    play(event)
    text, pages = pdf_text(exports.results_pdf(event))
    assert pages > 1
    for name in names:
        assert len(re.findall(rf"{name} - total score", text)) == 1


def test_a_name_outside_latin1_does_not_raise_and_shows_a_question_mark():
    """The built-in font covers Latin-1 only; other characters become '?'."""
    event = make_event(["Łukasz", "Zoë"], rotations=1)
    play(event)
    text, _ = pdf_text(exports.results_pdf(event))
    assert "?ukasz - total score" in text
    assert "Łukasz" not in text


def test_pdf_for_an_event_with_nothing_scored_still_builds():
    """Headings and an empty state rather than an error."""
    event = make_event(["Ann", "Ben", "Cat", "Dan"])
    text, _ = pdf_text(exports.results_pdf(event))
    assert "0 of 3 passes completed" in text
    assert text.count("No completed pass yet.") == 4


# --- routes ------------------------------------------------------------------------------


def started_client():
    """A test client with a 4-archer event started over HTTP; returns (client, state)."""
    state = make_state()
    client = create_app(state=state).test_client()
    client.post(
        "/event/stage1",
        data={"n_archers": "4", "total_arrows": "36", "n_pass": "12", "setup_mode": "simple",
              "distance": "20yd", "face_cm": "60"},
    )
    form = {}
    for i, name in enumerate(("Ann", "Ben", "Cat", "Dan")):
        form.update({f"name_{i}": name, f"bowstyle_{i}": "Recurve", f"handicap_{i}": str(20 + 10 * i)})
    client.post("/event/stage2", data=form)
    client.post("/event/stage3")
    return client, state


@pytest.mark.parametrize(
    ("path", "content_type", "filename"),
    [
        ("/event/export/leaderboard.csv", "text/csv", "leaderboard.csv"),
        ("/event/export/archer-results.csv", "text/csv", "archer-results.csv"),
        ("/event/export/results.pdf", "application/pdf", "results.pdf"),
    ],
)
def test_each_export_route_serves_the_right_type_and_filename(path, content_type, filename):
    """Content type and an attachment disposition naming the file."""
    client, _ = started_client()
    score_current_pass(client, lambda archer: 80 + archer)
    resp = client.get(path)
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith(content_type)
    assert resp.headers["Content-Disposition"] == f"attachment; filename={filename}"


def test_the_pdf_route_returns_a_pdf_and_the_csv_routes_return_parseable_csv():
    """The bodies are what the exports module produces."""
    client, state = started_client()
    score_current_pass(client, lambda archer: 80 + archer)
    assert client.get("/event/export/results.pdf").data.startswith(b"%PDF-")
    board = rows_of(client.get("/event/export/leaderboard.csv").data.decode("utf-8"))
    assert board[0] == ["Rank", "Archer", "Points", "Passes decided"] and len(board) == 5
    assert client.get("/event/export/leaderboard.csv").data.decode() == exports.leaderboard_csv(state.event)
    assert not client.get("/event/export/archer-results.csv").data.startswith(b"\xef\xbb\xbf")


@pytest.mark.parametrize(
    "path",
    ["/event/export/leaderboard.csv", "/event/export/archer-results.csv", "/event/export/results.pdf"],
)
def test_exports_redirect_to_stage_1_without_an_event(path):
    """Nothing to export before an event exists."""
    resp = create_app(state=make_state()).test_client().get(path)
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/event/stage1")


def test_the_results_and_archer_results_pages_link_to_all_three_exports():
    """Download links on both pages."""
    client, _ = started_client()
    for page in ("/event/results", "/event/archers"):
        html = client.get(page).data.decode()
        for target in ("/event/export/leaderboard.csv", "/event/export/archer-results.csv",
                       "/event/export/results.pdf"):
            assert f'href="{target}"' in html, (page, target)


def test_exports_are_live_saving_the_last_match_of_a_pass_changes_them():
    """The next request after saving reflects the new completed pass."""
    client, state = started_client()
    first, second = state.event.matches(0)
    client.post("/event/match/0", data={f"score_{p}": str(80 + p) for p in first})
    before = client.get("/event/export/archer-results.csv").data.decode()
    assert len(rows_of(before)) == 1  # the pass is not complete yet

    client.post("/event/match/1", data={f"score_{p}": str(80 + p) for p in second})
    after = client.get("/event/export/archer-results.csv").data.decode()
    assert len(rows_of(after)) == 1 + 4
    assert client.get("/event/export/leaderboard.csv").data.decode() != exports.leaderboard_csv(
        make_event(["Ann", "Ben", "Cat", "Dan"])
    )
