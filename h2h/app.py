"""Flask web layer for the Handicapped H2H scoring tool.

Routes only; all statistics live in `h2h.stats` and event orchestration in
`h2h.models`/`h2h.rotation`, all independently importable/testable without
Flask running (see AISpec.md section 4). Session state is a single in-memory
`SessionState` (see `h2h.state`) shared by all routes -- this is a
single-user local tool, not a multi-tenant service.
"""

from __future__ import annotations

from flask import Flask, redirect, render_template, request, url_for

from . import stats
from .chart_data import build_pair_chart_data
from .models import Archer, Bowstyle, RoundMode, resolve_indoor_round
from .state import SessionState


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
    def index():
        return redirect(url_for("stage1"))

    @app.get("/event/stage1")
    def stage1(error: str | None = None):
        return render_template(
            "stage1.html",
            n_archers=session.n_archers or 4,
            total_arrows=session.total_arrows,
            n_pass=session.n_pass,
            round_mode=session.round_mode.value,
            shoot_byes=session.shoot_byes,
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
            shoot_byes = request.form.get("shoot_byes", "yes") != "no"
            session.start_stage1(n_archers, total_arrows, n_pass, round_mode, shoot_byes)
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
        """Overview of the current pass: every match, its status, and the advance button.

        Parameters
        ----------
        error : str | None, default=None
            Message to show above the matches (e.g. a refused advance).

        Returns
        -------
        flask.Response | str
            The rendered overview page, or a redirect to Stage 1 if no event
            has been set up yet.
        """
        if session.event is None:
            return redirect(url_for("stage1"))
        event = session.event
        idx = event.current_rotation_index
        rotation = event.schedule[idx]

        matches_view = []
        for i, match in enumerate(event.matches(idx)):
            results = event.match_results(idx, match)
            matches_view.append(
                {
                    "index": i,
                    "a": match[0],
                    "b": match[1],
                    "scored": bool(results),
                    "results": {r.archer_index: r for r in results},
                }
            )
        return render_template(
            "rotation.html",
            event=event,
            rotation_index=idx,
            rotation=rotation,
            matches=matches_view,
            sitting_out=[event.archers[i].name for i in rotation.sitting_out],
            complete=event.is_rotation_complete(idx),
            is_last=idx == len(event.schedule) - 1,
            error=error,
        )

    @app.post("/event/advance")
    def event_advance():
        """Advance the event to the next pass once every match in this one is scored.

        Returns
        -------
        flask.Response | str
            A redirect to the overview on success; the overview re-rendered
            with an error if the pass is not fully scored (or is the last);
            or a redirect to Stage 1 if no event exists.
        """
        if session.event is None:
            return redirect(url_for("stage1"))
        try:
            session.event.advance()
        except ValueError as exc:
            return event_rotation(error=str(exc))
        return redirect(url_for("event_rotation"))

    @app.get("/event/match/<int:match_index>")
    def event_match(
        match_index: int,
        error: str | None = None,
        form_scores: dict[int, str] | None = None,
    ):
        """One match of the current pass: score entry plus that match's results.

        Parameters
        ----------
        match_index : int
            Position of the match in the current pass's matches (pairs first,
            then the bye archer's solo match if byes are shot).
        error : str | None, default=None
            Message to show above the form (a rejected submission).
        form_scores : dict[int, str] | None, default=None
            Raw text to refill the score boxes with after a rejected
            submission, keyed by archer index; defaults to the match's
            already-saved scores, if any.

        Returns
        -------
        flask.Response | str
            The rendered match page (this pass's score form, the pair's
            results so far, and in advanced mode the pair's distribution
            chart), or a redirect to the overview if
            `match_index` is not a match of the current pass (or to Stage 1 if
            no event exists).
        """
        if session.event is None:
            return redirect(url_for("stage1"))
        event = session.event
        idx = event.current_rotation_index
        matches = event.matches(idx)
        if not 0 <= match_index < len(matches):
            return redirect(url_for("event_rotation"))
        a, b = matches[match_index]
        results = event.match_results(idx, (a, b))
        if form_scores is None:
            form_scores = {r.archer_index: r.score for r in results}

        # A pair's history spans every pass the two have shared; a bye match has
        # only this pass's result and, with no opponent, no chart.
        history = results if b is None else event.pair_results(a, b)
        chart_data = None
        if b is not None and session.mode == "advanced":
            chart_data = build_pair_chart_data(event, a, b)
        return render_template(
            "match.html",
            event=event,
            rotation_index=idx,
            match_index=match_index,
            a=a,
            b=b,
            results=results,
            history=history,
            chart_data=chart_data,
            form_scores=form_scores,
            error=error,
        )

    @app.post("/event/match/<int:match_index>")
    def event_match_submit(match_index: int):
        """Save one match's scores (replacing earlier ones) and show its page again.

        Parameters
        ----------
        match_index : int
            Position of the match in the current pass's matches.

        Returns
        -------
        flask.Response | str
            A redirect back to the match page on success; the match page
            re-rendered with an error (nothing recorded) if a score is
            non-numeric or invalid.
        """
        if session.event is None:
            return redirect(url_for("stage1"))
        event = session.event
        matches = event.matches(event.current_rotation_index)
        if not 0 <= match_index < len(matches):
            return redirect(url_for("event_rotation"))
        archers = [p for p in matches[match_index] if p is not None]

        form_scores = {i: request.form.get(f"score_{i}", "") for i in archers}
        try:
            scores = {}
            for archer_idx, raw in form_scores.items():
                try:
                    scores[archer_idx] = float(raw)
                except ValueError:
                    msg = f"{event.archers[archer_idx].name}'s score must be a number."
                    raise ValueError(msg) from None
            event.record_match(scores)
        except ValueError as exc:
            return event_match(match_index, error=str(exc), form_scores=form_scores)
        return redirect(url_for("event_match", match_index=match_index))

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

    @app.get("/event/pair/<int:a>/<int:b>")
    def pair_chart(a: int, b: int):
        if session.event is None:
            return redirect(url_for("stage1"))
        event = session.event
        if event.pairwise_result(a, b) is None:
            return redirect(url_for("event_results"))
        return render_template(
            "pair_chart.html",
            event=event,
            a=a,
            b=b,
            chart_data=build_pair_chart_data(event, a, b),
        )

    @app.get("/event/handicap-calculator")
    def handicap_calculator(result: float | None = None, error: str | None = None):
        return render_template(
            "handicap_calculator.html", result=result, error=error
        )

    @app.post("/event/handicap-calculator")
    def handicap_calculator_submit():
        round_mode = (
            RoundMode.INDOOR_PORTSMOUTH
            if request.form.get("round", "portsmouth") == "portsmouth"
            else RoundMode.INDOOR_WA18
        )
        rnd = resolve_indoor_round(round_mode, compound=request.form.get("compound") == "yes")
        try:
            score = float(request.form.get("score", ""))
            handicap = stats.handicap_for_round_score(score, rnd)
        except ValueError:
            return handicap_calculator(error="Enter a valid score for the chosen round.")
        return handicap_calculator(result=round(handicap, 1))

    @app.post("/mode")
    def toggle_mode():
        session.toggle_mode()
        return redirect(request.form.get("next") or url_for("stage1"))

    @app.get("/reset")
    def reset():
        session.reset()
        return redirect(url_for("stage1"))

    return app
