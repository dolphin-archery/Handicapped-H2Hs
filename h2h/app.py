"""Flask web layer for the Handicapped H2H scoring tool.

Routes only; all statistics live in `h2h.stats` and match orchestration in
`h2h.models`, both independently importable/testable without Flask running
(see AISpec.md section 4). Session state is a single in-memory `SessionState`
(see `h2h.state`) shared by all routes -- this is a single-user local tool,
not a multi-tenant service.
"""

from __future__ import annotations

from archeryutils import load_rounds
from flask import Flask, redirect, render_template, request, url_for

from . import stats
from .chart_data import build_match_chart_data
from .models import VALID_N_PASS, Archer, Bowstyle, RoundMode
from .state import SessionState

NUM_SETUP_ROWS = 20


def create_app(state: SessionState | None = None) -> Flask:
    """Build and return the Flask application.

    Parameters
    ----------
    state : h2h.state.SessionState | None, default=None
        Session state to use; defaults to a fresh `SessionState()`. Exposed
        as a parameter so tests can inject an isolated state instead of
        sharing the process-wide default.

    Returns
    -------
    flask.Flask
        Configured Flask app, not yet run.
    """
    app = Flask(__name__)
    session = state if state is not None else SessionState()

    @app.context_processor
    def inject_mode():
        return {"mode": session.mode}

    @app.get("/")
    def setup(error: str | None = None):
        return render_template(
            "setup.html",
            num_rows=NUM_SETUP_ROWS,
            valid_n_pass=list(VALID_N_PASS),
            n_pass=session.n_pass,
            error=error,
        )

    @app.post("/start")
    def start():
        archers = []
        for i in range(NUM_SETUP_ROWS):
            name = request.form.get(f"name_{i}", "").strip()
            handicap_raw = request.form.get(f"handicap_{i}", "").strip()
            if not name or not handicap_raw:
                continue
            bowstyle = request.form.get(f"bowstyle_{i}", "").strip() or None
            archers.append(Archer(name=name, handicap=float(handicap_raw), bowstyle=bowstyle))

        n_pass = int(request.form.get("n_pass", session.n_pass))
        try:
            session.start_matches(archers, n_pass)
        except ValueError as exc:
            return setup(error=str(exc))
        return redirect(url_for("matches"))

    @app.get("/matches")
    def matches():
        match_views = [
            {
                "idx": idx,
                "archer_a": m.archer_a.name,
                "archer_b": m.archer_b.name,
                "handicap_a": m.archer_a.handicap,
                "handicap_b": m.archer_b.handicap,
                "n_pass": m.n_pass,
                "status": _match_status(m),
            }
            for idx, m in enumerate(session.matches)
        ]
        return render_template(
            "matches.html", match_views=match_views, unpaired=session.unpaired
        )

    @app.get("/match/<int:idx>")
    def match_view(idx: int, error: str | None = None):
        m = session.matches[idx]
        next_idx = m.next_pass_index()
        return render_template(
            "match.html",
            match=m,
            idx=idx,
            archer_a=m.archer_a,
            archer_b=m.archer_b,
            next_pass_index=next_idx,
            chart_data=build_match_chart_data(m),
            error=error,
        )

    @app.post("/match/<int:idx>/pass")
    def record_pass(idx: int):
        m = session.matches[idx]
        next_idx = m.next_pass_index()
        try:
            try:
                score_a = float(request.form["score_a"])
                score_b = float(request.form["score_b"])
            except ValueError:
                raise ValueError("Scores must be numbers.") from None
            m.record_pass(next_idx, score_a, score_b)
        except ValueError as exc:
            return match_view(idx, error=str(exc))
        return redirect(url_for("match_view", idx=idx))

    @app.get("/event/stage1")
    def stage1(error: str | None = None):
        return render_template(
            "stage1.html",
            n_archers=session.n_archers or 4,
            total_arrows=session.total_arrows,
            n_pass=session.n_pass,
            round_mode=session.round_mode.value,
            error=error,
        )

    @app.post("/event/stage1")
    def stage1_submit():
        try:
            n_archers = int(request.form["n_archers"])
            total_arrows = int(request.form["total_arrows"])
            n_pass = int(request.form["n_pass"])
            if request.form.get("round_mode") == "outdoor":
                round_mode = RoundMode.OUTDOOR
            elif request.form.get("indoor_round") == "wa18":
                round_mode = RoundMode.INDOOR_WA18
            else:
                round_mode = RoundMode.INDOOR_PORTSMOUTH
            session.start_stage1(n_archers, total_arrows, n_pass, round_mode)
        except (ValueError, KeyError) as exc:
            return stage1(error=str(exc) or "Invalid input.")
        return redirect(url_for("stage2"))

    @app.get("/event/stage2")
    def stage2(error: str | None = None):
        if session.schedule is None or session.n_archers is None:
            return redirect(url_for("stage1"))
        return render_template(
            "stage2.html",
            n_archers=session.n_archers,
            bowstyles=list(Bowstyle),
            error=error,
        )

    @app.post("/event/stage2")
    def stage2_submit():
        if session.schedule is None or session.n_archers is None:
            return redirect(url_for("stage1"))
        try:
            archers = []
            for i in range(session.n_archers):
                name = request.form.get(f"name_{i}", "").strip()
                handicap_raw = request.form.get(f"handicap_{i}", "").strip()
                bowstyle_raw = request.form.get(f"bowstyle_{i}", "").strip()
                if not name or not handicap_raw or not bowstyle_raw:
                    msg = f"Row {i + 1}: name, handicap, and bowstyle are all required."
                    raise ValueError(msg)
                try:
                    bowstyle = Bowstyle(bowstyle_raw)
                except ValueError:
                    msg = f"Row {i + 1}: '{bowstyle_raw}' is not a valid bowstyle."
                    raise ValueError(msg) from None
                try:
                    handicap = float(handicap_raw)
                except ValueError:
                    msg = f"Row {i + 1}: handicap must be a number."
                    raise ValueError(msg) from None
                archers.append(Archer(name=name, handicap=handicap, bowstyle=bowstyle))
            session.start_stage2(archers)
        except ValueError as exc:
            return stage2(error=str(exc))
        return redirect(url_for("event_rotation"))

    @app.get("/event/rotation")
    def event_rotation(error: str | None = None):
        if session.event is None:
            return redirect(url_for("stage1"))
        event = session.event
        idx = event.next_rotation_index()
        if idx is None:
            return redirect(url_for("event_results"))
        rotation = event.schedule[idx]
        return render_template(
            "rotation.html",
            event=event,
            rotation_index=idx,
            rotation=rotation,
            error=error,
        )

    @app.post("/event/rotation")
    def event_rotation_submit():
        if session.event is None:
            return redirect(url_for("stage1"))
        event = session.event
        idx = event.next_rotation_index()
        if idx is None:
            return redirect(url_for("event_results"))
        rotation = event.schedule[idx]
        participants = [p for pair in rotation.pairs for p in pair]
        if rotation.bye is not None:
            participants.append(rotation.bye)

        try:
            scores = {}
            for archer_idx in participants:
                raw = request.form.get(f"score_{archer_idx}", "")
                try:
                    scores[archer_idx] = float(raw)
                except ValueError:
                    name = event.archers[archer_idx].name
                    msg = f"{name}'s score must be a number."
                    raise ValueError(msg) from None
            event.record_rotation(idx, scores)
        except ValueError as exc:
            return event_rotation(error=str(exc))
        return redirect(url_for("event_rotation"))

    @app.get("/event/results")
    def event_results():
        if session.event is None:
            return redirect(url_for("stage1"))
        event = session.event

        rotations_view = []
        for idx in range(len(event.schedule)):
            rotation_results = [r for r in event.results if r.rotation_index == idx]
            if rotation_results:
                rotations_view.append({"index": idx, "results": rotation_results})

        return render_template(
            "results.html",
            event=event,
            rotations_view=rotations_view,
            pairwise=event.all_pairwise_results(),
        )

    @app.get("/event/handicap-calculator")
    def handicap_calculator(result: float | None = None, error: str | None = None):
        return render_template(
            "handicap_calculator.html", result=result, error=error
        )

    @app.post("/event/handicap-calculator")
    def handicap_calculator_submit():
        round_choice = request.form.get("round", "portsmouth")
        rnd = (
            load_rounds.AGB_indoor.portsmouth
            if round_choice == "portsmouth"
            else load_rounds.WA_indoor.wa18
        )
        try:
            score = float(request.form.get("score", ""))
            handicap = stats.handicap_for_round_score(score, rnd)
        except ValueError:
            return handicap_calculator(error="Enter a valid score for the chosen round.")
        return handicap_calculator(result=round(handicap, 1))

    @app.post("/mode")
    def toggle_mode():
        session.toggle_mode()
        return redirect(request.form.get("next") or url_for("setup"))

    @app.get("/reset")
    def reset():
        session.reset()
        return redirect(url_for("setup"))

    def _match_status(m) -> str:
        if m.is_complete:
            result = m.result()
            if result == "draw":
                return "Complete: draw"
            winner = m.archer_a.name if result == "a" else m.archer_b.name
            return f"Complete: {winner} wins"
        scored = sum(1 for p in m.passes if p.is_scored)
        return f"{scored}/{len(m.passes)} passes scored"

    return app
