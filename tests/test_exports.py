"""Tests for h2h.exports (CSV and PDF) and the export routes."""

import csv
import io
import re
import subprocess
import sys
import tomllib
from datetime import datetime
from pathlib import Path

import pypdf
import pytest

from h2h import exports, outputs
from h2h.app import create_app
from h2h.models import Archer, Bowstyle, Event
from h2h.rotation import build_schedule
from h2h.state import SessionState

from .helpers import PORTSMOUTH, NoShuffle, score_current_pass

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 4, 15, 30, 12)
STAMP = "2026-10-04 15:30:12"
FILE_STAMP = "20261004-153012"

LEADERBOARD_HEADER = [
    "Rank", "Archer", "Points", "Passes decided", "Starting handicap", "To-date handicap", "Exported",
]
ARCHER_RESULTS_HEADER = [
    "Archer", "Starting handicap", "To-date handicap", "Pass", "Opponent", "Score",
    "Percentile (%)", "Handicap of score", "Exported",
]


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
    """All the text of a PDF (pages joined) and its page count."""
    reader = pypdf.PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() for page in reader.pages), len(reader.pages)


def to_date_cell(handicap):
    """How a CSV shows a to-date handicap: one decimal place, or empty."""
    return "" if handicap is None else f"{handicap:.1f}"


# --- dependencies ----------------------------------------------------------------------


def test_fpdf2_and_pypdf_are_declared_dependencies_and_import():
    """fpdf2 is a runtime dependency, pypdf a dev one; both import on this Python."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert any(d.startswith("fpdf2") for d in project["project"]["dependencies"])
    assert any(d.startswith("pypdf") for d in project["dependency-groups"]["dev"])
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    assert 'name = "fpdf2"' in lock and 'name = "pypdf"' in lock
    import fpdf  # noqa: F401


def test_importing_the_bridge_does_not_import_fpdf2():
    """fpdf2 is imported on the first PDF, so the browser can install it lazily (decision D16)."""
    code = "import sys, h2h.bridge; print('fpdf' in sys.modules)"
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "False"


# --- CSV ---------------------------------------------------------------------------------


def test_leaderboard_csv_has_the_header_the_handicaps_and_the_stamp_on_every_row():
    """The agreed header; each row equals the on-page leaderboard plus both handicaps and the time."""
    event = make_event(["Ann", "Ben", "Cat", "Dan"])
    play(event)
    rows = rows_of(exports.leaderboard_csv(event, NOW))
    assert rows[0] == LEADERBOARD_HEADER
    expected = [
        [str(r.rank), r.name, str(r.points), str(r.passes_decided), f"{r.starting_handicap:g}",
         to_date_cell(r.to_date_handicap), STAMP]
        for r in outputs.leaderboard(event)
    ]
    assert rows[1:] == expected and len(expected) == 4
    assert all(row[-1] == STAMP for row in rows[1:])


def test_archer_results_csv_is_a_tidy_table_with_both_handicaps_and_the_stamp():
    """One row per archer per completed pass, the two handicaps repeated, no Average rows."""
    event = make_event(["Ann", "Ben", "Cat", "Dan"])
    play(event)
    rows = rows_of(exports.archer_results_csv(event, NOW))
    assert rows[0] == ARCHER_RESULTS_HEADER
    expected = []
    for section in outputs.archer_results(event):
        for r in section.rows:
            expected.append(
                [section.name, f"{section.handicap:g}", to_date_cell(section.to_date_handicap),
                 str(r.pass_number), r.opponent, str(r.score), f"{r.percentile * 100:.1f}",
                 f"{r.handicap:.1f}", STAMP]
            )
    assert rows[1:] == expected and len(expected) == 12  # 4 archers x 3 passes
    assert not any("Average" in cell for row in rows for cell in row)
    ann = [row for row in rows[1:] if row[0] == "Ann"]
    assert len({(row[1], row[2]) for row in ann}) == 1  # the same two values on each of Ann's rows


def test_the_to_date_handicap_in_the_csv_is_the_equivalent_handicap_of_the_total():
    """After the last pass it is the whole-round handicap of the archer's total (one decimal place)."""
    event = make_event(["Ann", "Ben", "Cat", "Dan"])
    play(event)
    rows = rows_of(exports.archer_results_csv(event, NOW))[1:]
    for section in outputs.archer_results(event):
        mine = [row for row in rows if row[0] == section.name]
        assert {row[2] for row in mine} == {f"{section.to_date_handicap:.1f}"}
        assert section.arrows_shot == 36


def test_a_name_with_a_comma_and_a_quote_round_trips():
    """Standard CSV quoting keeps awkward names intact."""
    event = make_event(['O"Brien, Sam', "Ben"], rotations=1)
    play(event)
    parsed = rows_of(exports.archer_results_csv(event, NOW))
    assert {row[0] for row in parsed[1:]} == {'O"Brien, Sam', "Ben"}
    assert {row[4] for row in parsed[1:]} == {'O"Brien, Sam', "Ben"}
    board = rows_of(exports.leaderboard_csv(event, NOW))
    assert {row[1] for row in board[1:]} == {'O"Brien, Sam', "Ben"}


def test_a_partly_scored_pass_is_not_in_the_csv_and_an_unscored_event_gives_just_the_header():
    """Only completed passes are exported; no completed pass means an empty to-date handicap."""
    event = make_event(["Ann", "Ben", "Cat", "Dan"])
    assert len(rows_of(exports.archer_results_csv(event, NOW))) == 1
    board = rows_of(exports.leaderboard_csv(event, NOW))[1:]
    assert [r[2] for r in board] == ["0", "0", "0", "0"]
    assert [r[5] for r in board] == ["", "", "", ""]  # no to-date handicap yet

    first, second = event.matches(0)
    event.record_match({p: 80 + p for p in first})
    assert len(rows_of(exports.archer_results_csv(event, NOW))) == 1  # pass 1 is still incomplete
    event.record_match({p: 80 + p for p in second})
    assert len(rows_of(exports.archer_results_csv(event, NOW))) == 1 + 4


def test_csv_is_plain_utf8_without_a_byte_order_mark_and_numbers_are_plain():
    """Clean column names for pandas; percentiles are numbers; a zero score's handicap is empty."""
    event = make_event(["Zoë", "Ben"], rotations=2)
    event.record_match({0: 100, 1: 0})
    event.advance()
    event.record_match({0: 90, 1: 80})
    text = exports.archer_results_csv(event, NOW)
    assert not text.startswith("﻿")
    assert text.encode("utf-8").decode("utf-8") == text
    assert "Zoë" in text
    rows = rows_of(text)[1:]
    for row in rows:
        assert re.fullmatch(r"\d+\.\d", row[6]), row  # 59.8, no % sign
    zero_row = next(row for row in rows if row[0] == "Ben" and row[5] == "0")
    assert zero_row[7] == ""
    assert next(row for row in rows if row[5] == "90")[7] != ""


def test_a_zero_total_leaves_the_to_date_cell_empty():
    """A total of 0 has no handicap: empty, not 'None' or '-'."""
    event = make_event(["Ann", "Ben"], rotations=1)
    event.record_match({0: 0, 1: 5})
    rows = rows_of(exports.archer_results_csv(event, NOW))[1:]
    assert next(r for r in rows if r[0] == "Ann")[2] == ""
    assert next(r for r in rows if r[0] == "Ben")[2] != ""


def test_the_default_export_time_is_now():
    """Without a clock argument the stamp is the current local time (to the second)."""
    event = make_event(["Ann", "Ben"], rotations=1)
    before = datetime.now().replace(microsecond=0)
    stamp = rows_of(exports.leaderboard_csv(event))[1][-1]
    after = datetime.now()
    assert before <= datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S") <= after


def test_stamp_helpers_format_the_time_for_a_file_and_for_a_filename():
    """2026-10-04 15:30:12 and 20261004-153012."""
    assert exports.timestamp_text(NOW) == STAMP
    assert exports.filename_stamp(NOW) == FILE_STAMP


# --- PDF ---------------------------------------------------------------------------------


def test_pdf_is_a_valid_pdf_with_the_stamp_the_handicaps_and_every_archer():
    """pypdf reads it and finds the title, the stamp, both handicap headings and each archer's heading."""
    event = make_event(["Ann", "Ben", "Cat", "Dan"])
    play(event)
    data = exports.results_pdf(event, NOW)
    assert data.startswith(b"%PDF-")
    text, pages = pdf_text(data)
    assert pages >= 1
    assert "Handicapped H2H results" in text
    assert f"Exported {STAMP}" in text
    assert "3 of 3 passes completed" in text
    flat = " ".join(text.split())  # a long column heading may wrap inside its cell
    for heading in ("Rank", "Archer", "Points", "Passes decided", "Starting handicap", "To-date handicap",
                    "Pass", "Opponent", "Score", "Percentile"):
        assert heading in flat, heading
    for section in outputs.archer_results(event):
        heading = (
            f"{section.name} - total score {section.total_score} - starting handicap "
            f"{section.handicap:g} - to-date handicap {section.to_date_handicap:.1f}"
        )
        assert heading in " ".join(text.split())
    assert text.count("Average") == 4


def test_a_long_pdf_flows_onto_further_pages_with_each_archer_listed_once():
    """Eight archers over seven passes: more than one page, one heading per archer."""
    names = [f"Archer{i}" for i in range(8)]
    event = make_event(names)
    play(event)
    text, pages = pdf_text(exports.results_pdf(event, NOW))
    assert pages > 1
    for name in names:
        assert len(re.findall(rf"{name} - total score", text)) == 1


def test_a_name_outside_latin1_does_not_raise_and_shows_a_question_mark():
    """The built-in font covers Latin-1 only; other characters become '?'."""
    event = make_event(["Łukasz", "Zoë"], rotations=1)
    play(event)
    text, _ = pdf_text(exports.results_pdf(event, NOW))
    assert "?ukasz - total score" in text
    assert "Łukasz" not in text


def test_pdf_for_an_event_with_nothing_scored_still_builds_with_a_dash_for_to_date():
    """Headings and an empty state rather than an error."""
    event = make_event(["Ann", "Ben", "Cat", "Dan"])
    text, _ = pdf_text(exports.results_pdf(event, NOW))
    assert "0 of 3 passes completed" in text
    assert text.count("No completed pass yet.") == 4
    assert "to-date handicap -" in " ".join(text.split())


# --- routes ------------------------------------------------------------------------------


def started_client(clock=lambda: NOW):
    """A test client with a 4-archer event started over HTTP and a fixed export clock."""
    state = SessionState(rng=NoShuffle(), clock=clock)
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
        ("/event/export/leaderboard.csv", "text/csv", f"leaderboard_{FILE_STAMP}.csv"),
        ("/event/export/archer-results.csv", "text/csv", f"archer-results_{FILE_STAMP}.csv"),
        ("/event/export/results.pdf", "application/pdf", f"results_{FILE_STAMP}.pdf"),
    ],
)
def test_each_export_route_serves_the_right_type_and_a_stamped_filename(path, content_type, filename):
    """Content type and an attachment disposition naming the file with the export time."""
    client, _ = started_client()
    score_current_pass(client, lambda archer: 80 + archer)
    resp = client.get(path)
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith(content_type)
    assert resp.headers["Content-Disposition"] == f"attachment; filename={filename}"


def test_the_stamp_in_the_filename_equals_the_stamp_inside_the_file():
    """One request, one clock reading: the name and the contents agree."""
    times = iter([datetime(2026, 1, 2, 3, 4, 5), datetime(2027, 6, 7, 8, 9, 10), datetime(2028, 11, 12, 13, 14, 15)])
    client, _ = started_client(clock=lambda: next(times))
    score_current_pass(client, lambda archer: 80 + archer)

    board = client.get("/event/export/leaderboard.csv")
    assert "leaderboard_20260102-030405.csv" in board.headers["Content-Disposition"]
    assert {row[-1] for row in rows_of(board.data.decode())[1:]} == {"2026-01-02 03:04:05"}

    results = client.get("/event/export/archer-results.csv")
    assert "archer-results_20270607-080910.csv" in results.headers["Content-Disposition"]
    assert {row[-1] for row in rows_of(results.data.decode())[1:]} == {"2027-06-07 08:09:10"}

    pdf = client.get("/event/export/results.pdf")
    assert "results_20281112-131415.pdf" in pdf.headers["Content-Disposition"]
    assert "Exported 2028-11-12 13:14:15" in pdf_text(pdf.data)[0]


def test_the_default_clock_gives_a_filename_stamp_of_eight_digits_dash_six_digits():
    """Without an injected clock the name still carries the real time."""
    state = SessionState(rng=NoShuffle())
    client = create_app(state=state).test_client()
    client.post("/event/stage1", data={"n_archers": "2", "total_arrows": "12", "n_pass": "12",
                                       "setup_mode": "simple", "distance": "20yd", "face_cm": "60"})
    client.post("/event/stage2", data={"name_0": "A", "bowstyle_0": "Recurve", "handicap_0": "20",
                                       "name_1": "B", "bowstyle_1": "Recurve", "handicap_1": "30"})
    client.post("/event/stage3")
    for path, pattern in (
        ("/event/export/leaderboard.csv", r"leaderboard_\d{8}-\d{6}\.csv"),
        ("/event/export/archer-results.csv", r"archer-results_\d{8}-\d{6}\.csv"),
        ("/event/export/results.pdf", r"results_\d{8}-\d{6}\.pdf"),
    ):
        assert re.search(pattern, client.get(path).headers["Content-Disposition"])


def test_the_pdf_route_returns_a_pdf_and_the_csv_routes_return_parseable_csv():
    """The bodies are what the exports module produces."""
    client, state = started_client()
    score_current_pass(client, lambda archer: 80 + archer)
    assert client.get("/event/export/results.pdf").data.startswith(b"%PDF-")
    board = rows_of(client.get("/event/export/leaderboard.csv").data.decode("utf-8"))
    assert board[0] == LEADERBOARD_HEADER and len(board) == 5
    assert client.get("/event/export/leaderboard.csv").data.decode() == exports.leaderboard_csv(state.event, NOW)
    assert not client.get("/event/export/archer-results.csv").data.startswith(b"\xef\xbb\xbf")


@pytest.mark.parametrize(
    "path",
    ["/event/export/leaderboard.csv", "/event/export/archer-results.csv", "/event/export/results.pdf"],
)
def test_exports_redirect_to_stage_1_without_an_event(path):
    """Nothing to export before an event exists."""
    resp = create_app(state=SessionState(rng=NoShuffle())).test_client().get(path)
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
    assert {row[2] for row in rows_of(after)[1:]} != {""}  # every archer now has a to-date handicap


# --- Feedback 7: Pass starting handicap in the archer-results CSV and the PDF ---------------------


def make_updating_event(update=True, rotations=3):
    """Four archers over a round robin, handicap updating on (lookback 1, start weight 2) or off."""
    archers = [Archer(n, 20 + 7 * i, Bowstyle.RECURVE) for i, n in enumerate(["Ann", "Ben", "Cat", "Dan"])]
    event = Event(
        archers, 12, PORTSMOUTH, build_schedule(4, rotations), update_handicaps=update,
        n_lookback=1 if update else None, start_weight=2 if update else None,
    )
    for i in range(rotations):
        for match in event.matches(i):
            event.record_match({p: 80 + 8 * i + 3 * p for p in match})
        if i < rotations - 1:
            event.advance()
    return event


UPDATING_ARCHER_HEADER = [
    "Archer", "Starting handicap", "To-date handicap", "Pass", "Opponent", "Score",
    "Percentile (%)", "Pass starting handicap", "Handicap of score", "Exported",
]


def test_the_archer_results_csv_gains_the_pass_starting_handicap_column_when_updating():
    """The agreed ten columns, each row's value equal to the model's one-decimal text."""
    event = make_updating_event()
    rows = rows_of(exports.archer_results_csv(event, NOW))
    assert rows[0] == UPDATING_ARCHER_HEADER
    for section in outputs.archer_results(event):
        mine = [row for row in rows[1:] if row[0] == section.name]
        assert [row[7] for row in mine] == [f"{r.start_handicap:.1f}" for r in section.rows]
        assert mine[0][7] == f"{event.archers[section.archer_index].handicap:.1f}"  # pass 1: as entered
        assert mine[1][7] != mine[0][7]  # the handicap moved
        assert {row[-1] for row in mine} == {STAMP}
        assert [row[8] for row in mine] == [f"{r.handicap:.1f}" for r in section.rows]  # Handicap of score


def test_with_updating_off_the_archer_results_csv_is_exactly_the_previous_nine_columns():
    """Header and rows unchanged."""
    event = make_updating_event(update=False)
    rows = rows_of(exports.archer_results_csv(event, NOW))
    assert rows[0] == ARCHER_RESULTS_HEADER and all(len(row) == 9 for row in rows)
    assert "Pass starting handicap" not in exports.archer_results_csv(event, NOW)


def test_the_leaderboard_csv_is_unchanged_by_updating():
    """Only the per-pass tables gain the column."""
    event = make_updating_event()
    assert rows_of(exports.leaderboard_csv(event, NOW))[0] == LEADERBOARD_HEADER


def test_the_pdf_has_the_pass_starting_handicap_in_the_archer_tables_only_when_updating():
    """Heading and averages with updating on; none of that text with it off."""
    on = pdf_text(exports.results_pdf(make_updating_event(), NOW))[0]
    flat = " ".join(on.split())
    assert flat.count("Pass starting handicap") == 4  # one table per archer
    off = pdf_text(exports.results_pdf(make_updating_event(update=False), NOW))[0]
    assert "Pass starting handicap" not in " ".join(off.split())


def test_the_pdf_average_row_includes_the_mean_pass_starting_handicap():
    """Each archer's Average row ends with the mean start handicap, then the mean handicap."""
    event = make_updating_event()
    text = pdf_text(exports.results_pdf(event, NOW))[0]
    for section in outputs.archer_results(event):
        average = section.averages
        expected = (
            f"Average {average.score:.1f} {average.percentile * 100:.1f}% "
            f"{average.start_handicap:.1f} {average.handicap:.1f}"
        )
        assert expected in " ".join(text.split())


def test_the_export_route_serves_the_wider_csv_for_an_updating_event():
    """Over HTTP: an advanced updating event's archer-results CSV has the extra column."""
    state = SessionState(rng=NoShuffle(), clock=lambda: NOW)
    client = create_app(state=state).test_client()
    client.post("/event/stage1", data={"n_archers": "2", "total_arrows": "24", "n_pass": "12",
                                       "setup_mode": "advanced"})
    form = {"update_handicaps": "yes", "n_lookback": "1", "start_weight": "2"}
    for i, (name, handicap) in enumerate((("Ann", "30"), ("Ben", "40"))):
        form.update({f"name_{i}": name, f"bowstyle_{i}": "Recurve", f"handicap_{i}": handicap,
                     f"face_type_{i}": "10_zone", f"face_cm_{i}": "60", f"distance_{i}": "20yd"})
    assert client.post("/event/stage2", data=form).status_code == 302
    client.post("/event/stage3")
    for scores in ({0: 80, 1: 100}, {0: 100, 1: 99}):
        client.post("/event/match/0", data={f"score_{k}": str(v) for k, v in scores.items()})
        if state.event.current_rotation_index == 0:
            client.post("/event/advance")
    rows = rows_of(client.get("/event/export/archer-results.csv").data.decode())
    assert rows[0] == UPDATING_ARCHER_HEADER and len(rows) == 1 + 4
    ann = [r for r in rows[1:] if r[0] == "Ann"]
    assert [r[7] for r in ann][0] == "30.0" and [r[7] for r in ann][1] != "30.0"
