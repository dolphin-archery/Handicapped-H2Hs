# Handicapped H2Hs

**Status: the Flask prototype is feature-complete; UI polish and deployment are pending.**

The localhost app covers everything specified so far (three-stage setup, simple
and advanced target setup, per-pass scoring with tie-break, optional handicap
updating, graph view, leaderboard, per-archer results, CSV/PDF exports and the
handicap calculator), with 900+ automated tests and real-browser verification.
Still to do (see "Future Plans" in `Specification/feedback.md`): a nicer UI
(likely a proper front-end design system rather than hand-written Flask
templates), an in-app explanation of the maths, a user guide, and publication
to an existing web page / GitHub Pages. Persistence is deliberately absent:
state lives in memory for a single scorer on one machine.

A localhost web tool for running fair head-to-head (H2H) archery matches
between archers of different skill levels and bowstyles (Recurve, Compound,
Barebow, Longbow), using the Archery GB handicap system rather than a flat
score allowance. Archers rotate through different opponents every
`n_pass` arrows (a "pass"). See
[`Specification/AISpec.md`](Specification/AISpec.md) for the full design and
[`Specification/logbook.md`](Specification/logbook.md) for a detailed history
of what has been built and why.

## How it works (short version)

Each archer supplies their current AGB handicap. That handicap implies an
aiming-error distribution (via the same model the official AGB handicap
tables are built on), from which the exact probability distribution of an
archer's score over a pass of `n_pass` arrows can be derived. A pass is won
by whichever archer's actual score is more improbable given their own
distribution (i.e. who over-performed their own handicap by more), which
fairly accounts for archers having different score variability, not just
different average scores. Full reasoning and the statistical justification
are in [`Initial Testing/idea_evaluation.md`](Initial%20Testing/idea_evaluation.md).

Note: a bowstyle-specific variance correction was identified as a
theoretical improvement but is deliberately **not** implemented in the
current version (see `Specification/humanSpec.md` and the "Known gap"
section of `Initial Testing/idea_evaluation.md`).

## Using the app

Setup has three stages, then you score the event one pass at a time.

1. **Stage 1 - event setup:** number of archers, total arrows (default 60),
   arrows per pass (`n_pass`, default 12), and the setup mode.
   - *Simple* setup puts every archer on the same distance and target face:
     pick a distance (standard metric 18-90 m or imperial 20-100 yd, default
     20 yd) and a face size (40, 60, 80 or 122 cm, default 60 cm). Whether that
     counts as indoor or outdoor is worked out from the distance (up to 25 m /
     25 yd is indoor) and sets the arrow size used in the handicap maths; indoors,
     Compound archers score only the inner ring as 10.
   - *Advanced* setup gives every archer their own target: you choose a target
     face type (every scoring system `archeryutils` has, e.g. 10 zone, 10 zone
     compound, 5 zone, 11 zone, Worcester), a face size and a distance for each
     archer in Stage 2. The face type is used exactly as chosen, so a Compound
     archer who should score only the inner ring as 10 needs a compound face type.
     Each archer's highest possible score follows their own face (for example 9 per
     arrow on a 5-zone face), and percentiles come from each archer's own
     distribution, so mixed targets are still compared fairly.
   - With an odd number of archers one archer has no opponent each pass, so a
     **Shoot byes?** option appears: *Yes* means that archer shoots alone
     (recorded, but no win/loss); *No* means they sit the pass out, which adds
     passes so that everyone still shoots all their arrows.
2. **Stage 2 - archers:** name, bowstyle (Recurve, Compound, Barebow, Longbow)
   and handicap (0-150) for each archer (plus the three target dropdowns in
   advanced setup, and an "Update handicaps during matches" choice, below). A
   score-to-handicap calculator is linked from here and from the nav bar, for working
   out starting handicaps. The button reads **Continue to Stage 3**.
   - *Update handicaps during matches* (advanced setup only, default No): No keeps
     every archer's handicap as entered for every pass. Yes updates it before each
     pass to a weighted average of the entered handicap and the handicap implied by
     the archer's recent shooting: `(start_weight x entered + m x recent) /
     (start_weight + m)`, where `m` is the number of their latest passes used
     (`n_lookback`, or fewer if they have shot fewer) and *recent* is the handicap
     their total score over those `m` passes implies. `n_lookback` is how many passes
     back to look (1 = only the previous pass); *Start weight* is how many passes'
     worth of arrows the entered handicap counts for. Both are whole numbers of at
     least 1. `n_lookback` defaults to 4 (so the final pass of a 60-arrow round of
     12-arrow passes is based on every arrow shot so far in the round; a shorter event
     just uses all the passes it has) and the start weight to the number of passes each
     archer shoots (5 for 60 arrows in 12-arrow passes). The updated handicap sets the
     distribution a pass is judged against, so the percentiles and the chart's curves
     change from pass to pass. While handicaps are being updated, the tables that show a
     pass's handicap also show a **Pass starting handicap** column: the handicap that
     pass's distribution was built from, beside the handicap the pass score implies.
3. **Stage 3 - pairings:** the archers are drawn at random into the round-robin,
   and every pass's pairings are shown. Press **Redraw pairings** for a fresh draw
   as often as you like, then **Confirm pairings and start event**.
4. **Scoring:** the **overview** page shows the current pass as a table of
   Match | Score | Percentiles | Winner | Actions. Open each match to enter its
   scores on its own page. No handicap is shown beside an archer's name while scoring;
   once saved, a table shows just this pass (Archer | Score | Percentile | Handicap |
   Winner, the handicap being the one the pass score implies; with handicap updating
   on, a Pass starting handicap column sits before it). Where two percentiles
   would look the same at one decimal place, more places are shown until they differ.
   Once every match has scores, press **Advance to next pass**.
   - *Tie-break:* a pass is won by the higher percentile, then the higher score,
     then whichever archer's arrow was **closest to the middle**, which the archers
     judge and you enter with two "closest to the middle" tick boxes (only one can be
     ticked). The boxes appear only when the percentile and score are exactly tied:
     save the scores, and if they tie the page asks for the tick and shows the boxes
     (with the scores kept). There is no coin flip.
5. **Results:** the **Results** page has a **leaderboard** (1 point per pass won,
   archers on equal points share a rank, with each archer's starting and to-date
   handicap), the head-to-head result for every pair that has met, and the per-pass
   results, shown in the same format as the match pages with a thick double line
   between one match and the next so it is clear who was paired with whom. The
   **Archer results** page has, for each archer, a heading (name, total score,
   starting handicap, to-date handicap) and a table of their passes (Pass | Opponent |
   Score | Percentile | Handicap) with an Average row. The to-date handicap is the
   handicap implied by the archer's total score over all the arrows shot so far; after
   the last pass it is the full-round handicap of their whole score. The leaderboard
   and archer results count only **completed passes** (every match in the pass scored)
   and update live. Both pages offer downloads: the leaderboard and the archer results
   as **CSV**, and a full report as **PDF** (`fpdf2` is used for the PDF). Every export
   carries the date and time it was made (in the file name, in a final `Exported`
   column of the CSVs, and under the PDF's title) and both handicaps.

Graph view (a button on the match pages) shows or hides the interactive
distribution chart and a short explanation of how the winner is decided. The chart
names each curve with its archer's name and handicap (the handicap the curve is
built from, so it moves between passes when handicaps are updated), marks every score either archer has
shot so far (against any opponent) with a vertical line labelled with its pass
number ("P3"; by default only this pass's scores, with a tick box for the earlier
ones), and widens its axis if a score falls outside the usual range.
**Reset** in the nav bar asks for confirmation before clearing everything.

**Handicap calculator:** choose Indoor or Outdoor, pick the round from the list of
standard AGB and WA rounds of that kind, tick "shot with a compound bow" (indoor
rounds only) if it applies, and enter the score to get the AGB handicap.

## Repo structure

```
main.py                 Entry point -- run this to start the app
h2h/                    Application package
  stats.py                Core statistics engine (handicap -> score
                           distributions -> percentiles). No Flask
                           dependency; independently testable.
  rotation.py              Round-robin rotation scheduler, including the
                            sit-out schedule used when byes are not shot.
                            Independent of Flask and the stats engine.
  models.py                Archer/Event data model: the distance/face/face-type
                            setup (TargetSetup, shared or per archer) and how each
                            archer's target follows from it and their bowstyle,
                            recording scores one match at a time (with the
                            tie-break), advancing pass by pass, and the
                            calculator's standard rounds.
  chart_data.py            Builds the JSON payload for the graph view's
                            interactive distribution chart.
  outputs.py                Leaderboard and per-archer results, from completed
                            passes only. No Flask dependency.
  exports.py                CSV and PDF renderings of those outputs (fpdf2).
                            No Flask dependency.
  state.py                 In-memory session state (single-user, no database).
  app.py                   Flask routes.
  templates/                Jinja2 HTML templates (underscore-prefixed files
                            are shared partials).
  static/                   Client-side JS (Chart.js rendering).
tests/                  pytest test suite (mirrors the h2h/ modules above).
Specification/          Design documents driving development:
  humanSpec.md             One-line brief for the current version.
  AISpec.md                Detailed specification expanded from humanSpec.md.
  prd.json                 Task breakdown with pass/fail tests, tracked as
                            work progresses.
  feedback.md               Rounds of feedback on the running app.
  logbook.md                Implementation history, assumptions, and notes.
  UISpec.md                 Specification for the planned UI redesign.
  deploymentConstrains.md   Hosting constraints for the static (Pyodide,
                             GitHub Pages) deployment.
Prompts/                Process instructions used to drive development
                         (loopPrompt.md, feedbackPrompt.md, UILoopPrompt.md).
Initial Testing/        Original problem write-up (ideas.md), the statistical
                         evaluation that the current design is based on
                         (idea_evaluation.md), and an exploratory notebook for
                         the archeryutils dependency (examples.ipynb).
```

## Setup on a new device

Assumes `git` and [`uv`](https://docs.astral.sh/uv/) are already installed.

```bash
git clone <repo-url>
cd Handicapped-H2Hs
uv sync
```

`uv sync` creates a local virtual environment and installs all dependencies
pinned in `uv.lock`.

## Running the app

```bash
uv run main.py
```

This starts a local Flask development server (default:
`http://127.0.0.1:5000`). Open that address in a browser to set up archers
and run matches.

## Running the tests

```bash
uv run pytest
```

## Contributing / continuing development

Before making changes, read `Specification/AISpec.md` and the most recent
entries in `Specification/logbook.md` to understand current scope and
decisions already made. Known limitations and explicitly out-of-scope items
(for this version) are listed in `Specification/AISpec.md`. The next phase
(UI and deployment) is described under "Future Plans" in
`Specification/feedback.md`; deploying beyond localhost will need persistence
and multi-user handling, which the prototype intentionally does not have.
