"""The committed bridge fixtures (UISpec.md section 8, task UI-5) are what native Python produces."""

import base64
import json
import zlib

import pytest

from h2h import bridge

from .bridge_fixtures import FIXTURE_DIR, SCENARIOS, fixture_text, generate, pdf_summary


def _committed(name):
    """The committed fixture file of a scenario, decoded."""
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_regenerating_a_fixture_reproduces_the_committed_file(name):
    """Each scenario run again through bridge.call gives exactly the committed steps and results."""
    regenerated = generate(name)
    assert regenerated == _committed(name)
    assert fixture_text(regenerated) == (FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8")


def test_the_fixture_directory_holds_exactly_the_scenarios():
    """No stale fixture file is left behind and none is missing."""
    assert sorted(p.stem for p in FIXTURE_DIR.glob("*.json")) == sorted(SCENARIOS)


def test_the_fixtures_use_every_command_and_every_error_code_but_internal():
    """Together the scenarios call every bridge command and see each expected error code."""
    steps = [step for name in SCENARIOS for step in _committed(name)["steps"]]
    assert {step["command"] for step in steps} == set(bridge._COMMANDS)
    codes = {step["result"]["error"]["code"] for step in steps if not step["result"]["ok"]}
    assert codes == {"validation", "tiebreak_required", "state"}


def test_the_scenarios_cover_what_their_names_say():
    """Byes shot and sat out, updating, the tie-break, completion and the calculator cases are all present."""

    def steps(name, command):
        return [s for s in _committed(name)["steps"] if s["command"] == command]

    pairings = {name: steps(name, "pairings")[0]["result"]["data"]["passes"] for name in ("byes_shot", "byes_sat_out")}
    assert all(p["matches"][-1]["b"] is None for p in pairings["byes_shot"])
    assert all(p["sitting_out"] for p in pairings["byes_sat_out"])
    started = steps("handicap_updating", "start_event")[0]["result"]["data"]["document"]
    assert started["setup"]["update_handicaps"] is True
    assert any(not s["result"]["ok"] and s["result"]["error"]["code"] == "tiebreak_required"
               for s in steps("tie_break", "record_match"))
    assert steps("complete_event", "validate_document")[0]["result"]["ok"] is True
    for name in set(SCENARIOS) - {"calculator"}:
        last = [s for s in _committed(name)["steps"] if s["command"] == "record_match" and s["result"]["ok"]][-1]
        assert last["result"]["data"]["document"]["status"] == "complete", name
    results = [s["result"] for s in steps("calculator", "calculator")]
    assert [r["ok"] for r in results] == [True, True, True, False]
    assert results[0]["data"]["handicap"] != results[1]["data"]["handicap"]  # the compound variant differs


def test_every_scenario_exports_all_three_files_with_the_fixed_time():
    """Each event fixture holds both CSVs (with the fixed export time) and the PDF summary."""
    for name in set(SCENARIOS) - {"calculator"}:
        exports = {s["payload"]["kind"]: s["result"]["data"] for s in _committed(name)["steps"] if s["command"] == "export"}
        assert exports["leaderboard_csv"]["filename"] == "leaderboard_20261004-153012.csv"
        assert "2026-10-04 15:30:12" in exports["archer_results_csv"]["content"]
        pdf = exports["results_pdf"]["content"]
        assert pdf["header"].startswith("%PDF-") and pdf["pages"] >= 1
        assert "Exported 2026-10-04 15:30:12 (local time)" in pdf["text"]


def test_pdf_summary_reads_the_drawn_text_and_ignores_the_creation_time():
    """Two exports of the same event at different moments have equal summaries; the text is unescaped."""
    doc = next(s["payload"]["doc"] for s in _committed("simple")["steps"] if s["command"] == "export")
    first = base64.b64decode(bridge.export(doc, "results_pdf", "2026-10-04T15:30:12")["data"]["content"])
    second = base64.b64decode(bridge.export(doc, "results_pdf", "2026-10-04T15:30:12")["data"]["content"])
    assert pdf_summary(first) == pdf_summary(second)
    summary = pdf_summary(first)
    assert summary["text"][0] == "Handicapped H2H results"
    assert "(only completed passes are counted)." in summary["text"][2]  # "\(" and "\)" unescaped
    raw = zlib.compress(b"BT 1 2 Td (a \\(b\\) c\\\\d) Tj ET")
    assert pdf_summary(b"%PDF-1.3\nstream\n" + raw + b"\nendstream /Type /Page")["text"] == ["a (b) c\\d"]
