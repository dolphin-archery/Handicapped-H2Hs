"""Flask web layer for the Handicapped H2H scoring tool.

Routes only; all statistics live in `h2h.stats` and match orchestration in
`h2h.models`, both independently importable/testable without Flask running
(see AISpec.md section 4). Session state is a single in-memory `SessionState`
(see `h2h.state`) shared by all routes -- this is a single-user local tool,
not a multi-tenant service.
"""

from __future__ import annotations

from flask import Flask, Response, redirect, render_template, request, url_for

from .charts import render_pass_distributions
from .models import Archer, VALID_N_PASS
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
    def match_view(idx: int):
        m = session.matches[idx]
        next_idx = m.next_pass_index()
        return render_template(
            "match.html",
            match=m,
            idx=idx,
            archer_a=m.archer_a,
            archer_b=m.archer_b,
            next_pass_index=next_idx,
        )

    @app.post("/match/<int:idx>/pass")
    def record_pass(idx: int):
        m = session.matches[idx]
        next_idx = m.next_pass_index()
        score_a = float(request.form["score_a"])
        score_b = float(request.form["score_b"])
        m.record_pass(next_idx, score_a, score_b)
        return redirect(url_for("match_view", idx=idx))

    @app.get("/match/<int:idx>/pass/<int:pass_index>/chart.png")
    def pass_chart(idx: int, pass_index: int):
        m = session.matches[idx]
        png = render_pass_distributions(m, pass_index)
        return Response(png, mimetype="image/png")

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
