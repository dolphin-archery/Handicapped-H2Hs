# Logbook
For AI agents to note their work

# Assumtions

The following assumptions were made when turning `Specification/humanSpec.md` into
`AISpec.md` / `prd.json`, since they were not fully specified by the human spec:

1. Default round is a Portsmouth (60 arrows) rather than a WA18; a round-selection
   control is a reasonable future enhancement but not required for v1.
2. Handicap scheme fixed to `"AGB"` (2023 scheme) rather than `"AGBold"`/`"AA"`/`"AA2"`.
3. `n_pass` is restricted to exact divisors of 60 (`1,2,3,4,5,6,10,12,15,20,30,60`), so
   every pass is the same length and the round divides evenly. Default `n_pass = 12`.
4. Archers are paired strictly in entry order (1v2, 3v4, ...); no bracket/re-pairing UI.
5. Overall match tie-break: majority of passes wins; an even split is shown as a draw,
   with no further tie-break (e.g. sudden-death pass) implemented.
6. Pass-winner tie-break (equal percentile) is: compare raw scores, then coin flip.
7. All match state is in-memory only; no database, no persistence across restarts.
8. Charting (advanced mode) uses `matplotlib` static images rather than a JS charting
   library, to minimise dependencies for a local single-user tool.
9. Bowstyle is collected for display/record-keeping only and never enters any
   calculation, per the explicit exclusion of the bowstyle-variance correction in
   `Specification/humanSpec.md`.
10. The setup form shows a fixed 20 archer rows rather than a dynamic "add more"
    control, to avoid losing already-typed rows on a page reload without adding
    client-side JS state management.

Assumptions 1, 3, 4, 5, 9, and 10 above are superseded by Feedback 2 (see
`Specification/AISpec.md` section 7 for the full, current list, numbered 1-14 -
superseded ones are struck through there with a note on what replaced them,
rather than deleted, so the history of why is kept). New assumptions from
Feedback 2 worth calling out here:

11. Outdoor mode uses one single fixed target (WA720's 70m/122cm face) for every
    bowstyle, rather than modelling the real per-bowstyle outdoor distance
    differences (e.g. Compound at 50m) - that would require "different distance
    per archer", which `Specification/feedback.md` explicitly defers to a future
    "Advanced mode".
12. Rotation scheduling uses the standard round-robin "circle method"; if fewer
    rotations are available than a full round-robin needs the schedule is
    truncated, if more are available it repeats from the start.
13. Of the two bye-handling modes `Specification/feedback.md` asked to toggle
    between, only "shoot alone, no comparison" is implemented (confirmed via
    clarifying question); the "sit out + additional rotation" alternative's
    fairness mechanics were never fully specified, so it -- and the toggle
    itself -- are not built. Flagged prominently in case the toggle was actually
    wanted now.

# Implementation History

## Task 1: Project scaffolding and dependencies (complete)
Added Flask, numpy, scipy, matplotlib, pytest via `uv add`. Created `h2h/` package
(`app.py` with a `create_app()` factory, placeholder `stats.py` to be filled in by
task 2) and root `main.py` entry point. Verified `uv run main.py` starts a real
server and `GET /` returns 200; verified `h2h.stats` imports without Flask. Tests in
`tests/test_app.py`. No issues.

## Task 2: Per-arrow score PMF from handicap (complete)
Implemented `h2h.stats.per_arrow_pmf`, decomposing the same ring-tail terms
`archeryutils.HandicapScheme._s_bar` uses internally (`exp(-((arrow_radius +
ring_radius)/sigma_r)**2)`) into per-ring hit probabilities instead of just their
mean, by taking successive differences of the ring "tail" (miss-beyond-this-ring)
probabilities. Verified against archeryutils across 5 handicaps x 2 target faces
(Portsmouth, WA18): PMF sums to 1, all probabilities >= 0, and
`sum(score*prob) == archeryutils.arrow_score(handicap, target)` to within 1e-6 -
this numerically confirms the hand-derived telescoping-sum decomposition is
correct. Tests in `tests/test_stats.py`. No issues.

## Task 3: n_pass score distribution via convolution (complete)
Implemented `h2h.stats.n_pass_score_distribution` via exact discrete
self-convolution (`numpy.convolve`) of the per-arrow PMF, n_pass-1 times. Verified
sums to 1, mean scales linearly with n_pass (matches n_pass * archeryutils mean),
n_pass=1 reproduces the input PMF exactly, and n_pass<1 raises ValueError. Tested
at n_pass in {1, 6, 12, 60} (60 being the full round) - even at 60 arrows this is
computationally trivial, so no need for a Gaussian/CLT approximation or Monte
Carlo fallback. Tests in `tests/test_stats.py`. No issues.

## Task 4: Percentile computation and pass-winner decision (complete)
`percentile` (already added in task 2's commit) and the new `decide_pass_winner`
implement the comparison method from Testing/idea_evaluation.md: compare each
archer's percentile under their own distribution, tie-break on raw score, then on
a coin flip (injectable `random.Random` for deterministic testing). Verified
percentiles are bounded in [0,1] and hit their expected extremes, winner-decision
picks the higher percentile, falls back to raw score on a tie, and produces both
outcomes over repeated calls when fully tied. Tests in `tests/test_stats.py`. No
issues.

## Task 5: Match/round data model and orchestration (complete)
Added `h2h/models.py` with `Archer`, `Pass`, `Match`, and `default_round()`
(Portsmouth, per Assumption 1). `Match` validates `n_pass` against the full set of
divisors of 60, pre-computes both archers' n_pass score distributions at
construction time (cheap per task 3), and exposes `record_pass`/`result`/`pass_wins`.
Overall result is majority-of-passes, draw on an even split, per Assumptions 4-5.
Verified invalid n_pass rejection, correct pass count for n_pass=12, tally
updates, majority-wins and even-split-draw outcomes, and that `result()` before
completion raises. Tests in `tests/test_models.py`. No issues; `models.py` is the
first module to depend on `stats.py`, and both remain Flask-independent.

## Tasks 6-9: Web UI - setup, scoring, mode toggle, advanced charts (complete)
Implemented together since the templates are cross-referential (base.html's nav
needs the toggle route to exist to build its `url_for`, matches.html needs
match_view to exist once any match is created, etc.), but verified and logged
against each task's own criteria:

- **Task 6** (`h2h/state.py` `SessionState`, `/`, `/start`, `/matches` routes,
  `setup.html`/`matches.html`): archers entered via a fixed 20-row form (simpler
  than dynamic add-row JS for a v1, per Assumption below); n_pass chosen via a
  real `<input type=range>` slider whose JS snaps across the exact divisor-of-60
  values (`VALID_N_PASS`), with server-side re-validation in `/start` as a
  defence in depth (caught a real bug here: `SessionState.start_matches` was
  mutating `self.n_pass`/`self.matches` *before* constructing the `Match`
  objects, so an invalid n_pass left the session half-updated and crashed the
  next page render — fixed by validating/building all matches into a local list
  first and only committing to state once construction succeeds). Odd archer
  counts flag the last archer as unpaired without crashing.
- **Task 7** (`/match/<idx>`, `/match/<idx>/pass`, `match.html`): one score box
  per archer per pass; submitting shows that pass's winner, running pass tally,
  and (once complete) the overall result, all read directly from the `Match`
  object so the UI can't drift from the stats engine's decision.
- **Task 8** (`/mode` route, nav toggle in `base.html`): toggles a single
  `SessionState.mode` field; since match/pass state lives separately from mode,
  toggling never touches entered scores. Verified via a test that scores a pass,
  toggles mode, and confirms the score is still shown.
- **Task 9** (`h2h/charts.py` + `/match/<idx>/pass/<n>/chart.png`): renders a
  two-panel matplotlib bar chart (per archer) of their n_pass distribution with
  their actual score marked, returned as a real PNG response; the maths
  explanation and the bowstyle-exclusion note are in `match.html`, shown only
  when `mode == 'advanced'`.

Verified with a full Flask test-client suite (`tests/test_app.py`, isolated
`SessionState` per test) covering all of the above, plus a manual smoke test of
the real `uv run main.py` server via curl for the full flow (setup -> start ->
score a pass -> toggle mode -> view chart). No outstanding issues.

Assumption added beyond `AISpec.md`: the setup form uses a fixed 20 rows rather
than a dynamic "add more archers" control, to avoid either losing already-typed
rows on a page reload or adding client-side JS state management for something
not required by `Specification/humanSpec.md`. Sufficient for a single club-night
session; revisit if more than 20 archers are needed.

## Task 10: End-to-end integration check (complete)
Added `tests/test_integration.py`, exercising the full HTTP flow (setup -> start
-> score every pass -> result) against the real Flask app rather than calling
`h2h.models`/`h2h.stats` directly, since those were already verified in isolation
by tasks 2-5. Covers the three criteria in prd.json:
- Full session completes without error for 2 archers over a full n_pass=12 round.
- A directional worked example (one archer scoring the maximum possible pass
  score every pass, the other scoring zero every pass) always produces that
  archer as the overall winner -- this holds for any pair of handicaps because
  `percentile` is a CDF and therefore monotonic in score, so it's a valid
  "independently computed expectation" without needing to hand-derive the
  underlying Gaussian-model probabilities again (already cross-checked against
  archeryutils's own numbers in `tests/test_stats.py`).
- Because there is no persistence layer (Assumption 7), "restarting clears
  state" is verified as: a second, independently-constructed app/`SessionState`
  never sees a first instance's matches.

Final full suite: 101 tests passing (`h2h/stats.py`, `h2h/models.py`,
`h2h/state.py`, `h2h/charts.py`, `h2h/app.py` routes, and this integration
suite). All 10 prd.json tasks are now `"completed": true`. Also re-ran a manual
smoke test of the real `uv run main.py` server via curl (setup, start, score a
pass, toggle to advanced mode, fetch the chart PNG) to confirm behaviour matches
the test-client results outside of Flask's test harness.

Suggested follow-ups (out of scope for this prd, listed for awareness):
`Testing/idea_evaluation.md`'s "Known gap" (bowstyle-variance correction) remains
deliberately unimplemented per `Specification/humanSpec.md`; a round-selection
dropdown (currently Portsmouth-only, Assumption 1) and a dynamic archer-count
setup form (Assumption 10) would be reasonable v2 additions.

## Feedback 1 - Base Functionality

Scope: implemented every item under `Specification/feedback.md`'s "Feedback 1"
heading (tasks 11-14 below, added to `prd.json` per `Specification/feedbackPrompt.md`'s
process); explicitly did not touch anything under its "Future Feedback - DO NOT
IMPLEMENT YET" heading (UI redesign, rotations/brackets, overall scoring system,
results printouts, publication).

### Task 11: Pass score validation and integer display (complete)
Added `h2h.models.MAX_SCORE_PER_ARROW = 10` (hard-coded per the feedback) and
`_validate_score`, used by `Match.record_pass` so validation applies regardless
of caller (web or tests). Rejects non-whole numbers and anything outside
`[0, n_pass * 10]`, with a message naming the actual bound (e.g. "Score must be
between 0 and 120 for a 12-arrow pass, got 121."). `h2h/app.py`'s `record_pass`
route catches `ValueError` and re-renders the match page with the message
instead of a 500; a separate non-numeric-input case ("abc") is caught before it
reaches validation and given its own message. `Pass.score_a`/`score_b` are now
`int` (coerced in `_validate_score`), so they render without a trailing ".0" --
no template changes needed once the underlying type was fixed. Tested via
`tests/test_models.py` (validation logic) and `tests/test_app.py` (HTTP-layer
error messages), plus a manual curl check of all four error paths against the
real server.

### Task 12: Per-pass equivalent handicap (complete)
Added `h2h.stats.equivalent_handicap`, which builds a one-off
`archeryutils.rounds.Round` of `n_pass` arrows at the match's target and calls
`archeryutils`'s own `handicap_from_score` rootfinder -- reusing existing,
tested machinery rather than inventing a new estimator. Returns `None` for a
zero score (undefined handicap). New `Pass.handicap_a`/`handicap_b` fields,
computed in `record_pass`, shown as new table columns in `match.html`. Verified
this saturates in a documented, expected way for very low handicaps whose
expected score rounds to the round's maximum (excluded from the round-trip test
with a comment explaining why, not silently ignored). Tests in
`tests/test_stats.py` and `tests/test_models.py`.

### Task 13: Interactive single-graph distribution chart (complete)
Reworked charts from static per-pass PNGs to one interactive graph. Removed
`h2h/charts.py` (matplotlib) and its `/match/<idx>/pass/<n>/chart.png` route
and the `matplotlib` dependency entirely (`uv remove matplotlib`), since the
feedback's requirements -- hover tooltips, smoothed curves, both archers on one
graph, toggleable historical markers -- need real interactivity that a static
image can't provide. Replaced with:
- `h2h/chart_data.py`: pure-Python, Flask-independent builder for a JSON
  payload (both archers' distribution points trimmed to a sensible x-range, a
  shared y-axis ceiling, and every scored pass's raw scores). The x-range is
  centred on both distributions' combined mean +/- 4 standard deviations,
  shifted (not shrunk) to fit `[0, n_pass*10]` so a distribution whose mean
  sits at the very top of the range (e.g. a very low handicap) still gets a
  full-width window rather than being clipped -- caught by a test with two
  handicap-0 archers before fixing the range calculation.
- `h2h/static/match_chart.js`: renders both archers' distributions as one
  Chart.js line chart (`tension: 0.35`, filled, so a discrete PMF still reads
  as a smooth shaded curve without fabricating a different underlying
  distribution), using `interaction: {mode: 'index'}` for the "hover to see
  both archers' values" requirement. Each pass's actual scores are drawn as
  two-point vertical dashed "marker" datasets (a lightweight trick avoiding a
  second charting plugin); a `tooltip.filter` callback hides marker datasets
  from the hover tooltip so it only shows the two PDFs. Only the latest pass's
  markers are shown by default; a checkbox (`#show-previous-passes`) swaps in
  every scored pass's markers on change. Chart.js is loaded from a pinned CDN
  version (`chart.js@4.4.4`, confirmed reachable).
- `match.html`'s advanced-mode block now renders a `<canvas id="match-chart">`
  plus the checkbox, with the chart payload embedded via
  `window.MATCH_CHART_DATA = {{ chart_data|tojson }}`.

**Verification limitation:** no headless-browser tool (chromium-cli,
Playwright, etc.) is available in this Windows environment (checked: not on
`PATH`), so the actual JS rendering, tooltip behaviour, and checkbox
interaction could not be visually confirmed in a real browser. What was
verified: `chart_data.py`'s output via unit tests (`tests/test_chart_data.py`);
the rendered page's HTML/JSON via a live `uv run main.py` server and curl
(correct script ordering, valid embedded JSON, canvas/checkbox present, static
JS served at `/static/match_chart.js`); and manual review of `match_chart.js`
against the documented Chart.js v4 API (`parsing:false` with `{x,y}` points,
linear scale, `interaction.mode: 'index'`, `tooltip.filter`). **The user should
open `/match/<idx>` in advanced mode in an actual browser to confirm the
interactive behaviour before relying on it.**

### Task 14: Subscript typesetting for underscore identifiers (complete)
Replaced user-visible "n_pass" text with `n<sub>pass</sub>` in `setup.html`,
`matches.html`, and `match.html`, and "sigma_r" with `&sigma;<sub>r</sub>` in
the maths explanation. Also reworded the invalid-`n_pass` `ValueError` message
in `h2h/models.py` to avoid the raw identifier entirely ("Arrows per pass must
be one of ..." rather than "n_pass=7 does not..."), since that message is shown
as plain (HTML-escaped) text on the setup page and couldn't otherwise carry a
`<sub>` tag. Verified no user-facing "n_pass" (or "(n_pass)") text remains via
a dedicated test and a template grep.

Final suite after all of Feedback 1: 126 tests passing.

## Feedback 2 kickoff: clarifying questions + checkbox re-verification

`Specification/feedback.md`'s "Feedback 2" section opens with an explicit
instruction to ask before implementing anything unclear. Before touching
`AISpec.md`, asked four clarifying questions (via AskUserQuestion) covering the
biggest architecture-affecting ambiguities: how results should be tracked once
archers rotate opponents (answer: per-pass wins AND aggregated pairwise
results); what a bye archer's pass means (answer: shoot alone, no comparison);
what the indoor/outdoor toggle should actually cover (answer: indoor Compound
must use archeryutils's compound scoring variant, and confirmed the arrow-
diameter difference archeryutils already handles); and whether the "add toggle
to plot all ends" note was the same checkbox already built in Feedback 1 or
something new (the user said they hadn't seen it working, might be missing).

That last point was worth investigating properly rather than re-asserting the
same "couldn't verify, no browser tool" caveat as Feedback 1's task 13 note.
Found Microsoft Edge is actually installed on this machine
(`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`), so drove it
headlessly via an ephemeral Selenium install (`uv run --with selenium --with
webdriver-manager python ...` -- not added to the project's own dependencies).
This confirmed the checkbox genuinely works: unchecked, the chart has 4
datasets (2 curves + latest pass's 2 markers); checked, it grows to 6 (adds the
previous pass's 2 markers); a screenshot showing both states was captured; no
JS console errors occurred (aside from an unrelated favicon 404). Updated
prd.json task 13's note accordingly. Lesson for future verification work in
this environment: check for an installed browser binary before assuming
headless browser testing is impossible.

Also independently verified (given the surprising-looking result of a much
stronger archer "losing" a pass with a much higher raw score) that the
percentile-based decision is working as intended, not a tie-break bug: two
percentiles that both display as "0.0%" (rounding) were confirmed via direct
computation to be genuinely different (6.0e-39 vs 8.8e-15), so the system
correctly picked the less-improbable performance as the winner. This is a
cosmetic display-precision point (very extreme percentiles are indistinguishable
at 1 decimal place), not a defect, and wasn't something Feedback 2 asked to fix,
so left as-is -- noted here in case it's raised again later.

### Task 15: Round-robin rotation scheduler (complete)
Added `h2h/rotation.py` (`Rotation` dataclass, `build_schedule`), independent
of both Flask and the stats engine. Uses the standard "circle method": fix
position 0, pair position i with position (n-1-i), rotate the rest each round
(`arr = [arr[0], arr[-1], *arr[1:-1]]`). Odd `n_archers` gets a `None` bye
placeholder appended before scheduling. `build_schedule` truncates or cycles a
full round-robin to the requested rotation count (Assumption 12/13 in this
file / AISpec.md Assumption 13). Verified full pair-coverage-exactly-once for
even (no byes) and odd (one bye each, byes distributed one per archer) archer
counts from 3-8, no self-pairing/duplicates within a rotation, truncation is a
prefix, cycling repeats from the start, n_archers=2 gives one pair no bye, and
invalid inputs (n_archers<2, negative rotations) raise. Tests in
`tests/test_rotation.py`; all 17 passed first run (hand-derivation of the
circle method traced through by hand for n=3 and n=4 before coding matched the
test results exactly). No issues.

### Task 16: Per-archer target resolution (round mode x bowstyle) (complete)
Added `Bowstyle` and `RoundMode` enums and `resolve_target` to `h2h/models.py`.
Confirmed via a quick archeryutils inspection first (documented in this
session): `portsmouth_compound`/`wa18_compound` have the *same* diameter/
distance/indoor flag as their plain counterparts, only `scoring_system`
differs (`10_zone` vs `10_zone_compound`), so the arrow-diameter difference
(indoor vs outdoor) is already handled automatically by `per_arrow_pmf`
reading `target.indoor` -- no extra work needed for that part of the feedback.
Outdoor mode always resolves to the same fixed target (`wa720_70`'s, per
Assumption 12) regardless of bowstyle. Verified all combinations in the
resolution table match archeryutils's real round objects, and outdoor mode
truly ignores bowstyle. Tests in `tests/test_target_resolution.py`; full
suite still green (150 passed) after this change. No issues; `default_round()`
(used only by the soon-to-be-retired `Match`, task 24) was left alone rather
than refactored now, to avoid touching code this task doesn't need to.

### Task 17: Event data model (complete)
Added `Event`, `PassResult`, `PairwiseResult` to `h2h/models.py`. `Event`
precomputes each archer's own distribution at construction (handicap + task
16's `resolve_target`), validates the schedule's archer indices are in range,
and `record_rotation` validates all of a rotation's scores atomically before
recording anything (mirroring the old `Match.record_pass` pattern) then
derives per-archer `PassResult`s (percentile, equivalent handicap, and
winner/None) plus updates queryable pairwise results. `pairwise_result(a, b)`
returns `None` until that pair has shared a rotation, then aggregates wins
across however many passes they've actually shared -- this generalises the old
`Match.result()` without needing a separate "match" object per pair.
`Archer.bowstyle`'s type was widened from `str | None` to `Bowstyle | None`
(still optional at the dataclass level, since the old `Match` flow never reads
it; Stage 2's form, task 19, is what will actually enforce a valid selection).

Caught and fixed one design mistake while writing `Event.__init__`: an early
draft tried to compute the schedule's max archer index in one overly clever
one-line conditional expression indexing `r.pairs[0]` directly, which was both
hard to read and fragile (would break if a rotation ever had zero pairs);
replaced with a plain loop over every rotation's full participant list before
writing any tests against it.

Verified: each archer's distribution sums to 1 and is precomputed
independently; an out-of-range schedule index is rejected; recording a
rotation computes percentiles from each archer's own distribution; missing or
extra archers in a submitted score set are rejected; a bye archer's pass is
recorded with `won=None` and never appears in any pairwise result; pairwise
results are `None` before a shared rotation and correctly reflect the winner
after one; `all_pairwise_results()` only grows as rotations are actually
scored; `next_rotation_index`/`is_complete` advance correctly; an invalid
score in a batch leaves the whole rotation unrecorded; same handicap +
different bowstyle gives different distributions indoors but identical ones
outdoors (task 16 correctly wired through). Tests in `tests/test_event.py`;
full suite 162 passed. No outstanding issues.