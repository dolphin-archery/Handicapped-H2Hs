"""Flask web layer for the Handicapped H2H scoring tool.

Routes only; all statistics live in `h2h.stats` and match orchestration in
`h2h.models`, both independently importable/testable without Flask running
(see AISpec.md section 4). Session state is a single in-memory `SessionState`
(see `h2h.state`) shared by all routes -- this is a single-user local tool,
not a multi-tenant service.
"""

from __future__ import annotations

from flask import Flask, redirect, render_template, request, url_for

from .chart_data import build_match_chart_data
from .models import VALID_N_PASS, Archer, RoundMode
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
    def stage2():
        # Placeholder until prd task 19 builds this out; stage1 just needs a
        # valid redirect target to exist.
        if session.schedule is None:
            return redirect(url_for("stage1"))
        return "Stage 2 placeholder"

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
