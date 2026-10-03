"""Flask web layer for the Handicapped H2H scoring tool.

Routes only; all statistics live in `h2h.stats` and event orchestration in
`h2h.models`/`h2h.rotation`, all independently importable/testable without
Flask running (see AISpec.md section 4). Session state is a single in-memory
`SessionState` (see `h2h.state`) shared by all routes -- this is a
single-user local tool, not a multi-tenant service.
"""

from __future__ import annotations

import math

from flask import Flask, Response, redirect, render_template, request, url_for

from . import exports, outputs, stats
from .chart_data import build_pair_chart_data
from .models import (
    ADVANCED_FACE_SIZES_CM,
    DEFAULT_CALCULATOR_ROUND,
    DEFAULT_FACE_TYPE,
    DEFAULT_TARGET_SETUP,
    FACE_TYPES,
    INDOOR,
    MAX_HANDICAP,
    MIN_HANDICAP,
    OUTDOOR,
    STANDARD_FACE_SIZES_CM,
    Archer,
    Bowstyle,
    TargetSetup,
    calculator_round,
    calculator_rounds,
    distance_option_groups,
)
from .state import ADVANCED, SIMPLE, SessionState


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
    def inject_graph_view():
        return {"graph_view": session.graph_view}

    @app.get("/")
    def index():
        return redirect(url_for("stage1"))

    @app.get("/event/stage1")
    def stage1(error: str | None = None, setup_mode: str | None = None):
        """Event setup form (Stage 1).

        Parameters
        ----------
        error : str | None, default=None
            Message to show above the form (a rejected submission).
        setup_mode : str | None, default=None
            Which setup mode to show selected, "simple" or "advanced"; defaults
            to the session's current mode.

        Returns
        -------
        str
            The rendered form.
        """
        return render_template(
            "stage1.html",
            n_archers=session.n_archers or 4,
            total_arrows=session.total_arrows,
            n_pass=session.n_pass,
            setup_mode=setup_mode or session.setup_mode,
            distance_groups=distance_option_groups(),
            face_sizes=STANDARD_FACE_SIZES_CM,
            selected_distance=session.target_setup.distance_key,
            selected_face=session.target_setup.face_cm,
            shoot_byes=session.shoot_byes,
            error=error,
        )

    @app.post("/event/stage1")
    def stage1_submit():
        setup_mode = request.form.get("setup_mode", SIMPLE)
        try:
            n_archers = int(request.form["n_archers"])
            total_arrows = int(request.form["total_arrows"])
            n_pass = int(request.form["n_pass"])
            if setup_mode == ADVANCED:
                # Each archer's target is chosen at Stage 2; keep the last simple choice.
                target_setup = session.target_setup
            else:
                target_setup = TargetSetup.parse(
                    request.form.get("distance", ""), request.form.get("face_cm", "")
                )
            shoot_byes = request.form.get("shoot_byes", "yes") != "no"
            session.start_stage1(
                n_archers, total_arrows, n_pass, target_setup, shoot_byes, setup_mode
            )
        except (ValueError, KeyError) as exc:
            return stage1(
                error=str(exc) or "Invalid input.",
                setup_mode=setup_mode if setup_mode in (SIMPLE, ADVANCED) else None,
            )
        return redirect(url_for("stage2"))

    @app.get("/event/stage2")
    def stage2(error: str | None = None, values: dict[str, str] | None = None):
        """Archer details form.

        Parameters
        ----------
        error : str | None, default=None
            Message to show above the form (a rejected submission).
        values : dict[str, str] | None, default=None
            The previously submitted form fields (`name_i`, `bowstyle_i`,
            `handicap_i`, and in advanced setup `face_type_i`, `face_cm_i`,
            `distance_i`), used to refill the form after a rejected
            submission so nothing has to be retyped.

        Returns
        -------
        flask.Response | str
            The rendered form, or a redirect to Stage 1 if Stage 1 has not
            been completed.
        """
        if session.schedule is None or session.n_archers is None:
            return redirect(url_for("stage1"))
        return render_template(
            "stage2.html",
            n_archers=session.n_archers,
            setup=session.target_setup,
            advanced=session.setup_mode == ADVANCED,
            face_types=FACE_TYPES,
            face_sizes=ADVANCED_FACE_SIZES_CM,
            distance_groups=distance_option_groups(),
            default_face_type=DEFAULT_FACE_TYPE,
            default_face_cm=DEFAULT_TARGET_SETUP.face_cm,
            default_distance=DEFAULT_TARGET_SETUP.distance_key,
            bowstyles=list(Bowstyle),
            min_handicap=MIN_HANDICAP,
            max_handicap=MAX_HANDICAP,
            values=values or {},
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
                if not MIN_HANDICAP <= handicap <= MAX_HANDICAP:  # also rejects nan
                    msg = (
                        f"Row {i + 1}: handicap must be between {MIN_HANDICAP} and "
                        f"{MAX_HANDICAP}, got {handicap_raw}."
                    )
                    raise ValueError(msg)
                target_setup = None
                if session.setup_mode == ADVANCED:
                    try:
                        target_setup = TargetSetup.parse_advanced(
                            request.form.get(f"distance_{i}", ""),
                            request.form.get(f"face_cm_{i}", ""),
                            request.form.get(f"face_type_{i}", ""),
                        )
                    except ValueError as exc:
                        msg = f"Row {i + 1}: {exc}"
                        raise ValueError(msg) from None
                archers.append(
                    Archer(name=name, handicap=handicap, bowstyle=bowstyle, target_setup=target_setup)
                )
            session.start_stage2(archers)
        except ValueError as exc:
            return stage2(error=str(exc), values=request.form)
        return redirect(url_for("stage3"))

    def _closest_archer(ticked: list[str], match_archers: list[int]) -> int | None:
        """The archer ticked as closest to the middle, validated against the match.

        Parameters
        ----------
        ticked : list[str]
            The submitted values of the `closest` tick boxes (archer indices).
        match_archers : list[int]
            The archer indices in the match being saved.

        Returns
        -------
        int | None
            The ticked archer, or None if none was ticked or the match has no
            opponent (a bye match has no tie-break).

        Raises
        ------
        ValueError
            If more than one box is ticked, or the value is not one of the
            match's two archers.
        """
        if len(match_archers) < 2 or not ticked:
            return None
        if len(ticked) > 1:
            msg = "Tick only one archer as closest to the middle."
            raise ValueError(msg)
        if ticked[0] not in {str(i) for i in match_archers}:
            msg = "The archer closest to the middle must be one of the two in this match."
            raise ValueError(msg)
        return int(ticked[0])

    def _stage3_redirect():
        """The redirect a Stage 3 page needs instead of acting, or None if it may proceed.

        Returns
        -------
        flask.Response | None
            To the overview if the event has already started, back to Stage 2
            (or Stage 1) if the archers have not been entered yet, else None.
        """
        if session.event is not None:
            return redirect(url_for("event_rotation"))
        if session.pending_archers is None:
            return redirect(url_for("stage2" if session.schedule is not None else "stage1"))
        return None

    @app.get("/event/stage3")
    def stage3():
        """Pairing assignment: every pass's pairings for the current random draw.

        Returns
        -------
        flask.Response | str
            The rendered page, or the redirect from `_stage3_redirect`.
        """
        redirect_to = _stage3_redirect()
        if redirect_to is not None:
            return redirect_to
        archers = session.assigned_archers()
        passes = [
            {
                "matches": [
                    (archers[a].name, None if b is None else archers[b].name)
                    for a, b in rotation.matches
                ],
                "sitting_out": [archers[i].name for i in rotation.sitting_out],
            }
            for rotation in session.schedule
        ]
        return render_template("stage3.html", passes=passes)

    @app.post("/event/stage3/redraw")
    def stage3_redraw():
        """Draw a fresh random assignment and show Stage 3 again."""
        redirect_to = _stage3_redirect()
        if redirect_to is not None:
            return redirect_to
        session.redraw_pairings()
        return redirect(url_for("stage3"))

    @app.post("/event/stage3")
    def stage3_confirm():
        """Confirm the drawn pairings and start the event."""
        redirect_to = _stage3_redirect()
        if redirect_to is not None:
            return redirect_to
        session.start_event()
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
                    "percentiles": [row.percentile for row in outputs.pass_table_rows(event, results)],
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
        form_closest: list[int] | None = None,
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
        form_closest : list[int] | None, default=None
            The "closest to the middle" boxes to show ticked after a rejected
            submission; defaults to the archer a saved tie was decided for.

        Returns
        -------
        flask.Response | str
            The rendered match page (this pass's score form, a table of this
            pass's results, and with graph view on the pair's distribution
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
        results = event.match_results(idx, (a, b))  # in match order
        if form_scores is None:
            form_scores = {r.archer_index: r.score for r in results}
        if form_closest is None:
            form_closest = [r.archer_index for r in results if r.won and r.decided_by == "closest"]

        # A bye match has no opponent, so no chart.
        chart_data = None
        if b is not None and session.graph_view:
            chart_data = build_pair_chart_data(event, a, b)
        return render_template(
            "match.html",
            event=event,
            rotation_index=idx,
            match_index=match_index,
            a=a,
            b=b,
            results=results,
            chart_data=chart_data,
            form_scores=form_scores,
            ticked_closest=form_closest,
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
        ticked = request.form.getlist("closest")
        form_closest = [int(v) for v in ticked if v.isdigit()]
        try:
            closest = _closest_archer(ticked, archers)
            scores = {}
            for archer_idx, raw in form_scores.items():
                try:
                    scores[archer_idx] = float(raw)
                except ValueError:
                    msg = f"{event.archers[archer_idx].name}'s score must be a number."
                    raise ValueError(msg) from None
            event.record_match(scores, closest=closest)
        except stats.TieBreakRequired:
            msg = (
                "Percentile and score are tied. Tick which archer's arrow was closest "
                "to the middle, then save again."
            )
            return event_match(
                match_index, error=msg, form_scores=form_scores, form_closest=form_closest
            )
        except ValueError as exc:
            return event_match(
                match_index, error=str(exc), form_scores=form_scores, form_closest=form_closest
            )
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
            leaderboard=outputs.leaderboard(event),
            completed_passes=len(event.completed_passes),
        )

    @app.get("/event/archers")
    def archer_results():
        """Per-archer results (name, total score, handicap, a table of passes and averages).

        Live: recomputed on every request from the completed passes only.

        Returns
        -------
        flask.Response | str
            The rendered page, or a redirect to Stage 1 if no event exists.
        """
        if session.event is None:
            return redirect(url_for("stage1"))
        event = session.event
        return render_template(
            "archer_results.html",
            event=event,
            sections=outputs.archer_results(event),
            completed_passes=len(event.completed_passes),
        )

    def _download(body: str | bytes, mimetype: str, filename: str) -> Response:
        """A file download response.

        Parameters
        ----------
        body : str | bytes
            The file contents.
        mimetype : str
            The content type, e.g. "text/csv" or "application/pdf".
        filename : str
            The name the browser should save it as.

        Returns
        -------
        flask.Response
            The response, with an attachment Content-Disposition.
        """
        return Response(
            body, mimetype=mimetype, headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    @app.get("/event/export/leaderboard.csv")
    def export_leaderboard_csv():
        """The leaderboard as a CSV download (live, completed passes only)."""
        if session.event is None:
            return redirect(url_for("stage1"))
        return _download(exports.leaderboard_csv(session.event), "text/csv", "leaderboard.csv")

    @app.get("/event/export/archer-results.csv")
    def export_archer_results_csv():
        """Every archer's results as one tidy CSV download (live, completed passes only)."""
        if session.event is None:
            return redirect(url_for("stage1"))
        return _download(exports.archer_results_csv(session.event), "text/csv", "archer-results.csv")

    @app.get("/event/export/results.pdf")
    def export_results_pdf():
        """The leaderboard and every archer's results as one PDF download."""
        if session.event is None:
            return redirect(url_for("stage1"))
        return _download(exports.results_pdf(session.event), "application/pdf", "results.pdf")

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
    def handicap_calculator(
        result: float | None = None, error: str | None = None, choice: dict | None = None
    ):
        """The standalone score-to-handicap calculator form (and its result).

        Parameters
        ----------
        result : float | None, default=None
            The handicap to show, to one decimal place.
        error : str | None, default=None
            Message to show above the form (a rejected submission).
        choice : dict | None, default=None
            The submitted choices to show again (`kind`, `round_indoor`,
            `round_outdoor`, `compound`, `score`); defaults to indoor Portsmouth.

        Returns
        -------
        str
            The rendered page.
        """
        choice = choice or {
            "kind": INDOOR,
            "round_indoor": DEFAULT_CALCULATOR_ROUND[INDOOR],
            "round_outdoor": DEFAULT_CALCULATOR_ROUND[OUTDOOR],
            "compound": False,
            "score": "",
        }
        return render_template(
            "handicap_calculator.html",
            result=result,
            error=error,
            choice=choice,
            round_options={
                kind: [(codename, rnd.name) for codename, rnd in calculator_rounds(kind).items()]
                for kind in (INDOOR, OUTDOOR)
            },
        )

    @app.post("/event/handicap-calculator")
    def handicap_calculator_submit():
        """Work out the handicap for the chosen round and score."""
        kind = request.form.get("kind", INDOOR)
        choice = {
            "kind": kind if kind in (INDOOR, OUTDOOR) else INDOOR,
            "round_indoor": request.form.get(
                "round_indoor", DEFAULT_CALCULATOR_ROUND[INDOOR]
            ),
            "round_outdoor": request.form.get(
                "round_outdoor", DEFAULT_CALCULATOR_ROUND[OUTDOOR]
            ),
            "compound": request.form.get("compound") == "yes",
            "score": request.form.get("score", ""),
        }
        try:
            rnd = calculator_round(
                kind, request.form.get(f"round_{kind}", ""), compound=choice["compound"]
            )
        except ValueError as exc:
            return handicap_calculator(error=str(exc), choice=choice)
        try:
            score = float(choice["score"])
            if not math.isfinite(score):  # "nan" and "inf" parse as floats but are not scores
                raise ValueError(choice["score"])
            handicap = stats.handicap_for_round_score(score, rnd)
        except ValueError:
            return handicap_calculator(
                error="Enter a valid score for the chosen round.", choice=choice
            )
        return handicap_calculator(result=round(handicap, 1), choice=choice)

    @app.post("/graph-view")
    def toggle_graph_view():
        session.toggle_graph_view()
        return redirect(request.form.get("next") or url_for("stage1"))

    @app.get("/reset")
    def reset():
        """Ask for confirmation before clearing the event; changes nothing itself.

        Returns
        -------
        str
            The confirmation page, whose cancel link goes back to the current
            pass if an event is running, otherwise to Stage 1.
        """
        cancel_url = url_for("event_rotation" if session.event else "stage1")
        return render_template("reset.html", cancel_url=cancel_url)

    @app.post("/reset")
    def reset_confirmed():
        """Clear all setup and scores (the confirmed reset).

        Returns
        -------
        flask.Response
            A redirect to Stage 1.
        """
        session.reset()
        return redirect(url_for("stage1"))

    return app
