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

### Task 18: Stage 1 setup UI (event configuration) (complete)
Added `SessionState.start_stage1`/`start_stage2` (validates then builds the
rotation schedule via task 15, only committing state on success -- same
validate-before-commit pattern as the original `start_matches` bug fix from
Feedback 1), and `/event/stage1` (GET+POST) + `stage1.html`. A placeholder
`/event/stage2` route was added purely so Stage 1's redirect has a valid
target; task 19 replaces it properly. n_pass is chosen via the same
range-slider-plus-JS-array pattern as the old flow, but the divisor list is
now recomputed client-side from whatever `total_arrows` currently holds
(vanilla JS `divisors(n)`), rather than a fixed server-provided list.

Verified via the real-browser method established earlier this session
(headless Edge + ephemeral Selenium) rather than assuming the JS was correct,
and this caught a genuine bug: the "snap to nearest valid n_pass" logic read
its own hidden input's live value as the "preferred" n_pass to snap towards,
so retyping a multi-digit `total_arrows` digit-by-digit (e.g. clearing and
typing "40") caused each keystroke's snapped result to feed into the next
keystroke's snap target, drifting away from the archer's actual original
preference (observed: typing "40" after a default of 12 landed on 4, not the
correct nearest-divisor-of-40-to-12 answer of 10). Fixed by tracking the
user's intended n_pass in a separate variable (`preferredNPass`), updated only
when the user moves the slider itself, never by the total_arrows-driven
snapping logic. Re-verified after the fix: typing "40" now correctly lands on
10. This is the second real bug this session's browser verification has
caught (the first was Feedback 1's session-state mutation-before-validation
bug) -- reinforces that this verification step is worth doing, not a
formality.

Tests in `tests/test_event_routes.py` (new file, kept separate from
`tests/test_app.py` since task 24 replaces that file wholesale): GET renders,
valid submission redirects, non-dividing n_pass rejected with a clear message,
changing total_arrows changes which n_pass values are accepted, n_archers<2
rejected, outdoor mode works without a meaningful indoor_round value. Full
suite 176 passed.

### Task 19: Stage 2 setup UI (archer details) (complete)
Added `/event/stage2` (GET renders exactly `session.n_archers` rows; redirects
to Stage 1 if Stage 1 hasn't been completed) and its POST handler, which
validates every row (name/bowstyle/handicap all required, bowstyle must be one
of the three `Bowstyle` values, handicap must parse as a number) before
calling `SessionState.start_stage2` to bind archers to the Stage 1 schedule
and build the `Event`. Bowstyle uses a real `<select>` dropdown (not free
text), matching AISpec.md section 5.2's requirement.

Added placeholder routes for `/event/rotation` (task 20) and
`/event/handicap-calculator` (task 22) purely so Stage 1 -> Stage 2 -> "start
event" redirects, and Stage 2's link to the calculator, have valid targets
before those tasks build them out properly -- same pattern used for Stage 2's
own placeholder in task 18's commit.

Tests in `tests/test_event_routes.py`: exactly n_archers rows rendered,
reaching Stage 2 without Stage 1 redirects back, valid submission creates the
event, missing/invalid bowstyle rejected with a clear error. Full suite 180
passed. No issues.

### Task 20: Rotation scoring UI (complete)
Added `/event/rotation` (GET+POST) + `rotation.html`, replacing the task-19
placeholder. GET reads `event.next_rotation_index()`: if the event is already
complete it redirects to `/event/results` (task 21, itself placeholdered here
the same way stage2/rotation were placeholdered by earlier tasks); otherwise
it shows one score box per pair (grouped under a heading) plus a single box
for the bye archer if there is one. POST reads exactly the current rotation's
participant indices from the form, converts each to float (a friendly
per-archer error, e.g. "Bob's score must be a number.", if that fails) and
hands the whole dict to `Event.record_rotation` in one call, so an invalid
score anywhere is rejected before anything is recorded -- same pattern as
`Event.record_rotation`'s own internal validate-then-commit ordering.

Tests in `tests/test_event_routes.py`: a paired rotation shows exactly the
right score boxes; an odd-archer event's bye rotation shows the bye archer's
single box; submitting valid scores advances to the next rotation; an invalid
score is rejected with a clear message; once the event is complete,
`/event/rotation` redirects onward instead of prompting for a rotation that
doesn't exist. Full suite 185 passed. No issues.

### Task 21: Per-pass and pairwise results display (complete)
Replaced the `/event/results` placeholder with a real view: a pairwise-
results table (one row per pair that has shared >=1 rotation, from
`Event.all_pairwise_results()`) and, below it, a per-rotation breakdown of
every scored pass (grouped by rotation, from `Event.results` filtered by
`rotation_index`). Deliberately no ranking/points-total column anywhere, per
AISpec.md section 5.4's explicit exclusion of a leaderboard.

Caught a self-inflicted false-positive while testing: an early version of
`test_results_page_does_not_show_a_ranked_leaderboard` did a naive substring
search for the word "leaderboard", which failed against the page's own
prose ("a set of head-to-head results, not a ranked leaderboard") -- that
sentence is deliberate, helpful UX clarifying what the view is/isn't, not an
actual leaderboard feature. Fixed the test to check for real leaderboard
markers (a "Rank"/"Points"/"Total" table header) instead of the word itself.

Tests in `tests/test_event_routes.py`: a scored rotation's results appear on
the page; a pairwise result appears once a pair has shared a pass; no
pairwise results are shown before any scoring; no ranking/points table is
rendered. Full suite 189 passed. No outstanding issues.

### Task 22: Static handicap conversion tool (complete)
Replaced the `/event/handicap-calculator` placeholder with a real tool: pick
Portsmouth or WA18, enter a full-round score, get the AGB handicap to 1dp.
Added `h2h.stats.handicap_for_round_score(score, rnd)` -- a thin public
wrapper distinct from `equivalent_handicap` (which builds a synthetic partial
round for a single pass): this one takes a real, complete
`archeryutils.rounds.Round` directly, per AISpec.md section 5.5's explicit
"not a synthetic partial round" requirement. Added to expose the
functionality without reaching into `stats`'s private `_AGB_SCHEME` from
`app.py`. The result is never stored against an archer or wired into the
event -- it's a standalone GET+POST pair with no session-state involvement
beyond rendering the form.

Tests in `tests/test_handicap_calculator.py`: the wrapper matches calling
archeryutils directly on both real rounds; valid Portsmouth/WA18 scores return
the correct handicap; invalid input shows a friendly error, not a 500; the
page is reachable with no event set up at all (independent of setup
progress). Full suite 196 passed. No issues.

### Task 23: Adapt advanced-mode charts to per-pair-with-shared-history (complete)
Added `h2h.chart_data.build_pair_chart_data(event, a, b)` alongside (not
replacing yet -- task 24 removes the old one) `build_match_chart_data`,
sharing the same `_mean_and_std`/`_display_range` trimming logic. Sources
each archer's distribution from `Event.distribution_for` (so different
bowstyles indoors correctly produce different curves) and each shared pass
from `Event.results`, matching up the two `PassResult`s for a given
`rotation_index` (one from each archer's perspective) into a single
`{score_a, score_b}` entry. Added `/event/pair/<a>/<b>` + `pair_chart.html`
(redirects to results if that pair hasn't shared a rotation yet), reusing
`h2h/static/match_chart.js` unchanged -- it was already generic (reads
`window.MATCH_CHART_DATA`, looks for `#match-chart`/`#show-previous-passes`)
so no JS changes were needed, only a new server-side payload source. Linked
from `results.html`'s pairwise table via a "View chart" column, shown only in
advanced mode.

Re-verified the checkbox behaviour in a real browser as this task's own test
criteria required (not just trusting the JS is unchanged so "it must still
work"), and hit a genuine detour: an early verification script used a generic
`"form button"` CSS selector to click the rotation-scoring form's submit
button, which actually matched the *nav's mode-toggle form* instead (the
first `<form><button>` in DOM order, since the nav sits above the page
content in `base.html`) -- so the "score submission" was silently just
toggling mode, the rotation was never recorded, and the results page
correctly (if confusingly) reported "no pairs have shared a rotation yet".
Traced this step-by-step (printing mode state after every click) before
concluding it was the test script's selector specificity at fault, not an
app bug -- fixed by scoping the selector to
`form[action='/event/rotation'] button`. With that fix, re-verified
end-to-end: Stage 1 -> Stage 2 -> two scored rotations -> advanced mode ->
results page's "View chart" link -> pair chart page showing 4 datasets
(2 curves + latest pass's markers) before the checkbox and 6 after, no
console errors. Worth remembering for future verification work in this
codebase: `nav` renders before `{% block content %}`, so any CSS selector
meant for a content-area form/button must be scoped past the nav, not just
"the first form/button on the page".

Tests in `tests/test_pair_chart_data.py` (payload correctness) and
`tests/test_event_routes.py` (route behaviour, link visibility only in
advanced mode). Full suite 204 passed. No outstanding issues.

### Task 24: Retire the old fixed-pair flow and migrate tests (complete)
Removed everything specific to the old single-pair flow, now fully
superseded by tasks 15-23:
- `h2h/models.py`: deleted `Match`, `Pass`, `default_round()`, and the
  fixed-60 constants `TOTAL_ARROWS`/`VALID_N_PASS`/`DEFAULT_N_PASS` (all
  exclusively used by the old flow -- confirmed by grep before deleting, not
  assumed). Kept `_validate_score`/`MAX_SCORE_PER_ARROW` (used by `Event`
  too) and dropped the now-unused `archeryutils.rounds` import.
- `h2h/chart_data.py`: deleted `build_match_chart_data` and the `Match`
  import; `build_pair_chart_data` and its shared `_mean_and_std`/
  `_display_range` helpers remain.
- `h2h/state.py`: deleted `matches`/`unpaired` fields and `start_matches`.
- `h2h/app.py`: deleted the old `/`, `/start`, `/matches`, `/match/<idx>`,
  `/match/<idx>/pass` routes and the `_match_status` helper. `/` now
  redirects to `/event/stage1` (the new flow's natural front door) instead
  of serving the old setup page. `toggle_mode`/`reset` now fall back to/
  redirect to `stage1` instead of the removed `setup` endpoint.
- Deleted `h2h/templates/setup.html`, `matches.html`, `match.html`.
- `h2h/templates/base.html`: nav now links to Stage 1 setup, event results,
  and the handicap calculator (previously: the old setup/matches pages).
- Deleted `tests/test_models.py` (old `Match`/`Pass` tests, superseded by
  `tests/test_event.py`), `tests/test_chart_data.py` (superseded by
  `tests/test_pair_chart_data.py`), and `tests/test_integration.py` (old-flow
  end-to-end test; task 25 adds its rotation-based replacement). Reduced
  `tests/test_app.py` to the two truly generic infra checks (index redirects
  to Stage 1; stats importable without Flask) since everything else it used
  to cover now lives in `tests/test_event_routes.py`.

Verified via grep for every old-flow symbol/endpoint name
(`Match`, `build_match_chart_data`, `default_round`, `VALID_N_PASS`,
`TOTAL_ARROWS`, `NUM_SETUP_ROWS`, and `url_for` calls to the removed
endpoints) across both `.py` and `.html` files: zero hits, confirming no dead
references were left behind. Full suite passed immediately after the
cleanup (166 tests, down from 204 -- the difference is entirely the deleted
old-flow test files, not a loss of coverage of anything still in the
codebase). Also re-ran a full curl-based smoke test of `uv run main.py`
end-to-end (stage1 -> stage2 -> score a rotation -> results shows the
pairwise outcome) to confirm the live app still works after the cleanup, not
just the test suite.

### Task 25: End-to-end integration check for the rotation flow (complete)
Wrote a fresh `tests/test_integration.py` exercising the full HTTP flow for
the scenarios prd.json specified:
- Even `n_archers` (4): runs a full round-robin through the real routes and
  confirms every archer appears in the final results.
- Odd `n_archers` (5): walks all 5 rotations of the full round-robin,
  asserting each rotation's scoring page shows exactly 5 participant boxes
  (2 pairs + 1 bye) and the word "bye" appears, then confirms the results
  page shows a bye-labelled opponent for each of the 5 rotations.
- Indoor mode with mixed bowstyles: confirms directly via `resolve_target`
  that Compound resolves to the `10_zone_compound` system while Recurve
  resolves to `10_zone` for the same round, then exercises the same setup
  through the HTTP flow.
- Outdoor mode: confirms every `Bowstyle` resolves to the identical target
  (system and distance) via `resolve_target`.
- Fresh app/state: a second, independently-constructed client never sees the
  first client's event (the in-memory analogue of a restart, per Assumption 7).

A generic HTML-parsing helper (`run_full_event`) discovers each rotation's
actual participant indices from the rendered scoring page rather than
hard-coding them, so tests stay correct regardless of exactly how the
scheduler orders things. Caught and fixed a bug in that helper while writing
it: the first attempt double-split on `"_"` after already isolating the
`score_<i>` value, which crashed with an `IndexError` for any single-digit
archer index (no second `"_"` left to split on) -- simplified to a single
`split('"')[0]` once the correct substring was already isolated.

Final suite for all of Feedback 2: 171 tests passing. All 25 prd.json tasks
now `"completed": true`.

**Summary of what Feedback 2 delivered, for anyone picking this up later:**
archers now rotate through a round-robin schedule (built at Stage 1, before
names are known) instead of one fixed pair for the whole round; a two-stage
setup separates event-wide config from per-archer details; an indoor/outdoor
round-mode toggle exists, with indoor Compound archers correctly using
`archeryutils`'s indoor-compound scoring variant; results are tracked both
per-pass and as aggregated pairwise outcomes (deliberately no leaderboard);
the interactive distribution chart now works per-pair against the `Event`
model; and a standalone score-to-handicap calculator was added. Explicitly
not built (see AISpec.md Assumption 14 and the "Out of scope" list): the
alternative "sit out + additional rotation" bye mode and its toggle, and
everything under `Specification/feedback.md`'s "Future Feedback" heading
(per-archer scoring method/face/distance, a leaderboard, results print-outs,
UI redesign, and publication/deployment).

## Feedback 3 - Page flow, byes, longbow, compound calculator

Scope: every item under `Specification/feedback.md`'s "Feedback 3" heading
(prd tasks 26-33); nothing under "Future Plans - DO NOT IMPLEMENT YET".
`Specification/AISpec.md` was updated first (sections 1, 3, 4, 5.1-5.6, 6 and
new Assumptions 15-21; Assumption 14 is now superseded), then `prd.json`.

Assumptions made (full text in `Specification/AISpec.md` section 7):
- **15** - the rule for how many extra passes "Shoot byes? = No" needs, which
  the feedback leaves open ("this will change the total number of passes").
  Chosen: run the round-robin for as long as no archer would exceed their
  passes, then add one catch-up pass for archers one pass short (one extra
  already-complete archer joins if their number is odd, because exactly equal
  pass counts are impossible when the archer count and pass count are both
  odd). Flagged here because it is a genuine design choice, not derivable from
  the feedback.
- **16** - the Shoot byes? control only appears for an odd archer count, default Yes.
- **17** - scores can be corrected (re-saved) until the pass is advanced.
- **18** - Longbow scores like Recurve/Barebow.
- **19** - the calculator's compound option is a Yes/No checkbox.
- **20/21** - match pages are addressed by position in the current pass; the event
  completes as soon as the final pass is fully scored.

### Task 26: Add Longbow to the bowstyle dropdown (complete)
Added `Bowstyle.LONGBOW`. Stage 2's dropdown iterates `list(Bowstyle)`, so it
appears in every row with no template change. `resolve_target` needed no code
change either: it only special-cases Compound, so Longbow falls through to the
plain scoring variant indoors and the single fixed target outdoors (AISpec
Assumption 18). Updated the `Bowstyle`/`resolve_target` docstrings, widened the
two existing "plain variant" resolution tests to include Longbow, and added
tests that Longbow resolves identically to Recurve in every round mode, gives
an identical indoor score distribution to a same-handicap Recurve archer, and
appears in all rows of the Stage 2 dropdown (and can start an event). The
existing outdoor test already iterates the whole enum, so it covers Longbow
for free. No issues.

### Task 27: Compound option in the handicap calculator (complete)
The standalone calculator gained a "Shot with a compound bow" checkbox
(default unticked), posted as `compound=yes`. To honour "reuse rather than
duplicate", the indoor-round lookup that `resolve_target` already did inline
(Portsmouth/WA18 x compound/plain -> the real `archeryutils` round) was
extracted into `models.resolve_indoor_round(round_mode, compound)`, and both
`resolve_target` and the calculator route now call it; the calculator's old
inline Portsmouth/WA18 lookup (and its now-unused `load_rounds` import in
`app.py`) were removed. `resolve_indoor_round` raises `ValueError` for an
outdoor mode, since there is no outdoor "indoor round" to return.

Why it matters (and is tested to matter): the same score implies a different
handicap under the compound scoring system (only the inner ring counts 10),
so a test asserts the compound and plain 1dp handicaps for a Portsmouth 500 are
actually different before checking the page shows the compound one. Also
covered: WA 18 compound, no `compound` field -> plain round (existing
behaviour unchanged), a bad score with compound ticked -> friendly error, the
control renders, and `resolve_indoor_round` returns the real archeryutils round
objects. The checkbox state is not remembered after calculating (the existing
round radio isn't either); left as is since it wasn't asked for. No issues.
