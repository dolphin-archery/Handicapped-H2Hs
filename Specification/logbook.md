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
heading (tasks 11-14 below, added to `prd.json` per `Prompts/feedbackPrompt.md`'s
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

### Task 28: Scheduler: sitting-out rotations and the no-bye-shot schedule (complete)
`h2h/rotation.py` only. `Rotation` gained `sitting_out: tuple[int, ...] = ()` and
a `matches` property (the pairs, then `(bye, None)` for a solo bye match);
`build_schedule` and the circle-method generator are untouched. New
`build_sit_out_schedule(n_archers, passes_per_archer)` (plus a private
`_catch_up_rotation` helper): an even `n_archers` just returns `build_schedule`.
For an odd count it cycles the round-robin and stops at the largest number of
rotations R0 in which no archer exceeds their passes, i.e. the largest R with
`R - R // n <= P` (that expression is the pass count of the archers with the
fewest byes, who are the ones closest to the limit). Each bye archer sits out.
Everyone then has P or P-1 passes; if anyone has P-1, one catch-up rotation
pairs those archers (greedily, preferring opponents not yet met) and the rest
sit out. If their number is odd, the complete archer who has faced the fewest
of them (ties to lowest index) joins and shoots P+1. No issues hit. 48 odd
(n, P) combinations (n in 3..9, P in 1..12) never broke the "at least P, at most
one P+1" rule. Known cases: (5,4) -> 5 rotations, (5,5) -> 7, (3,5) -> 8,
(3,1) -> 2, (7,5) -> 6. 169 tests added (186 in test_rotation.py; whole suite
353 passing at the time).

### Task 30: Event: per-match score recording and explicit pass advance (complete)
Added the primitives the new page flow needs to `h2h.models.Event`, alongside
the existing `record_rotation` (which task 31 removes along with
`next_rotation_index`): `current_rotation_index` (starts 0), `matches(i)`
(delegates to `Rotation.matches`), `match_results`, `is_match_scored`,
`is_rotation_complete`, `record_match(scores)` and `advance()`.

- `record_match` takes a `{archer: score}` dict that must equal exactly one
  match of the *current* rotation (both archers of a pair, or just the bye
  archer), so there is no rotation-index argument to get wrong, and a
  sitting-out archer or a mix of two matches is a `ValueError`. Scores are
  validated with the existing `_validate_score` before anything is recorded.
- Re-recording a match replaces its results in place (same position in
  `results`) so the display order stays stable and pairwise results, which are
  derived from `results` on demand, automatically reflect the correction. A
  coin-flip tie-break (identical percentile and score) is re-rolled on re-save;
  that needs equal handicaps and equal scores, so it was left alone.
- The per-match result construction that `record_rotation` did inline was
  factored into `_pair_results` / `_solo_result`, now shared by both methods
  rather than copied.
- `advance()` refuses while any match is unscored and on the final rotation.
  `is_complete` is deliberately unchanged here; task 31 redefines it as "final
  rotation fully scored" when the old API goes.
- `Event.__init__`'s archer-index bounds check now goes through
  `Rotation.matches` and also covers `sitting_out`.

Tests (tests/test_event.py, 14 new, 29 total in the file): start state, one pair
scored without the rest, own-distribution percentile/handicap, bye match (no
winner, no pairwise entry), all the not-exactly-one-match rejections, a
sitting-out archer rejected, invalid scores record nothing, in-place
replacement, completeness, advance gating/final-rotation/earlier-pass-frozen,
and Event construction from a sit-out schedule (including the bounds check).
Full suite passes. No issues.

### Task 29: 'Shoot byes?' option at event setup (complete)
Stage 1 now has a "Shoot byes?" Yes/No radio (default Yes) between the archer
count and total arrows, with a short explanation that No adds passes.
`SessionState` gained `shoot_byes` (default True, restored by `reset()`) and
`start_stage1(..., shoot_byes=True)` builds the schedule with
`build_sit_out_schedule` only when `n_archers` is odd *and* `shoot_byes` is
False; every other case calls `build_schedule` exactly as before, so an even
archer count simply ignores the flag (the value is still stored and
re-rendered). The route reads `shoot_byes` as "No" only if the field is exactly
`no`, so an omitted field means Yes.

Visibility: the server renders the control hidden for an even `n_archers` and
visible for an odd one (so it is right on first load and when returning to
Stage 1), and a small inline script re-evaluates it on every `input` event of
the archer-count field (shown only for an odd value >= 3).

Verification: unit/route tests for the state logic and the posted form, plus a
real-browser check in headless Edge (delegated to a subagent). Results: the
control is hidden at the default 4, and live typing gives 5 shown, 6 hidden, 7
shown, 8 hidden, cleared hidden, 1 hidden, 3 shown, and digit-by-digit "1"
hidden then "11" shown; the Yes/No radios toggle exclusively; submitting with No
lands on Stage 2 and returning to Stage 1 shows No still selected; the only
console error was the usual unrelated favicon 404. One cosmetic oddity: typing
3.5 shows the control (`parseInt("3.5")` is 3), but the number field's
`step="1"` blocks submitting a non-integer anyway, so it was left as is.

Tooling note for future work: the subagent's `isolation: "worktree"` checkout
was based on a stale commit (the end of prd task 25), not the current HEAD, so
the agent exported the right commit with `git archive` instead. Don't rely on
the isolated worktree being current; give a browser-verification subagent the
commit hash to export.

### Task 31: Overview page, per-match pages and advance button (complete)
Done as two commits so the suite stayed green throughout. Part 1 swapped the
web flow onto the task-30 API while the old `Event` methods still existed;
part 2 then removed them.

- `/event/rotation` is now a read-only **overview** of the current pass ("Pass k
  of N"): a row per match (pair, or the bye archer's solo match when byes are
  shot) with its status ("Awaiting scores" or the entered scores and winner) and
  an "Enter scores" / "View / edit" link, a "Sitting out this pass" line when
  byes aren't shot, and an "Advance to next pass" button that is `disabled`
  until every match has scores. `POST /event/rotation` no longer exists (405).
- `POST /event/advance` calls `Event.advance()` and, if it refuses (pass
  incomplete, or already the final pass), re-renders the overview with the
  error rather than advancing - so the disabled button is a convenience and the
  rule is enforced server-side.
- `/event/match/<idx>` (new `match.html`): GET shows a score box per archer in
  that match only (one for a bye match), prefilled with any saved scores; POST
  saves through `Event.record_match` and redirects back to the same match page
  (so the result is visible straight away; the overview is one link away).
  Non-numeric input gets a per-archer message; out-of-range/non-integer input
  surfaces the existing `_validate_score` message; the form is refilled with
  what was typed and nothing is recorded. An out-of-range index redirects to
  the overview. Re-saving replaces the earlier scores (Assumption 17), and a
  small note on the page says so.
- The final pass has no advance button; once every match in it is scored the
  overview says the event is complete and links to results (it is not
  redirected away, so the last pass stays editable, Assumption 21).
- Nav gained a "Current pass" link; results.html's "Continue scoring" link now
  uses `current_rotation_index`.
- Removed `Event.record_rotation` and `Event.next_rotation_index`; `is_complete`
  is now "final rotation current and fully scored". Grep confirms no references
  remain in `h2h/` or `tests/`.
- Tests: the old rotation-scoring route tests were replaced with overview /
  match-page / advance tests (including the 405, bye and sit-out variants,
  parametrised invalid scores, re-save, advance gating at both ends, and the
  next pass's pairings appearing). `tests/helpers.py` (new) holds HTTP helpers
  that discover each pass's matches from the rendered pages
  (`score_current_pass`, `play_whole_event`, ...) plus a model-level
  `record_whole_rotation`; the old integration and event/chart tests were
  migrated onto them. Suite: 393 passed.

Process notes: two of my own mistakes surfaced in review rather than in the app
- a blanket search-and-replace in the test migration also rewrote the one
deliberate POST to the removed endpoint (caught by that very test failing), and
my page-peek script posted the wrong archer indices (the app correctly rejected
them). Neither affected shipped code. The match page currently shows only this
pass's result; history and the chart arrive in task 32.

### Task 32: Per-match results and advanced-mode charts on the match pages (complete)
Each match page now shows, below its score form, a "Results so far" table for
the pair: every pass the two archers have shared (a `Pass` column, plus score,
percentile, equivalent handicap, opponent and winner), including the current
one once saved. This uses a new `Event.pair_results(a, b)` (results where the
two are each other's opponent, ordered by pass, so a schedule that repeats a
pair lists every meeting). A bye match shows only its own pass result.

In advanced mode the page also embeds the pair's interactive distribution chart
and the maths explanation. The chart is built by the existing
`build_pair_chart_data`, which already worked for a pair with no scored pass
(empty `passes` list), so a match page charts the two distributions before the
first score is entered and gains markers once it is saved. A bye match has no
chart (nothing to compare) and says so in advanced mode; basic mode renders
none of the chart, payload or maths on any match page.

Markup de-duplication, per the task: the chart + maths block moved from
`pair_chart.html` into the `_pair_chart.html` partial (used by the match page
and the pair-history page), and the per-pass results table moved from
`results.html` into `_results_table.html` (used by the results page and the
match page, with an optional `show_pass` column). A test reads the template
sources and asserts each shared block's marker text lives in exactly one file.
Two docstrings that had gone stale (the `Event` schedule parameter, and
`build_pair_chart_data` claiming a pair must already have shared a rotation)
were corrected.

Verification: route tests (results after scoring, repeated pair lists every
pass, bye page in both modes, advanced chart present before scoring and with
the pass in the payload afterwards, basic mode has none, results/pair pages
unchanged). Real browser (headless Edge, a subagent, against the exact commit
exported with `git archive`): two archers meeting in two passes in advanced
mode. Chart datasets were 2 before scoring (Alice, Bob), 4 after saving
(`+ Alice pass 1: 100`, `+ Bob pass 1: 60`), 4 on the next pass after saving
(latest pass only), 6 with "Show previous passes' scores too" ticked and 4
again unticked; the results table listed both passes; the overview disabled
Advance until scored, then showed "Pass 2 of 2" with no Advance button on the
final pass and an "event is complete" link to results. A 3-archer event
confirmed the pair page has no chart in basic mode, the bye page has none in
either mode, and the bye result shows opponent "bye". The only console error
on any page was the favicon 404 (plus benign Edge tracking-prevention warnings
about the CDN).

**Pre-existing limitation noticed, not changed (out of scope):** the chart's
x-axis is trimmed to about the two distributions' mean +/- 4 standard
deviations (Feedback 1: "sensible axis limits") and the pass-score markers are
drawn at the raw score, so a score far outside that window (the verification
used deliberately unrealistic 60-vs-100 scores at handicaps 45/15, which is
~0.0% percentile) has its marker clipped off the chart even though it is in the
dataset list and legend. With realistic scores (e.g. 118 and 105) both markers
show. A simple fix, if wanted, is to widen the axis to include any scored
values; raised for the user rather than changed here.

### Task 33: End-to-end integration check, browser walkthrough and docs (complete)
`tests/test_integration.py` gained scenarios for the new flow, all driving the
real routes through the overview / match pages / advance via `tests/helpers.py`
(which discovers each pass's matches from the rendered pages):
- Even archers (4, three passes): every one of the 6 pairs has a pairwise result.
- Odd archers, byes shot (5): `total_arrows // n_pass` passes, exactly one solo
  result per pass, always with no winner, and every archer shoots every pass.
- Odd archers, byes **not** shot: 5 archers needing 5 passes -> 7 passes (6
  round-robin + 1 catch-up); on every pass the sitting-out archers are listed
  and are never offered a score box, nobody shoots alone, and the final counts
  are [5,5,5,5,6]; 5 archers needing 4 passes -> exactly 5 passes, everyone
  exactly 4 (no catch-up needed).
- Indoor with Recurve/Compound/Barebow/Longbow archers of equal handicap: scoring
  systems are plain/compound/plain/plain, and in one pass the three plain
  archers have identical percentiles while the Compound archer's differs.
- Outdoor with all four bowstyles: one shared non-indoor target.
- Advance refused at every pass of a full event until the whole pass is scored
  (including with one of two matches done), and refused after the final pass.
- Fresh `SessionState` sees no prior event (unchanged).
README.md now has a "Using the app" section and an updated repo structure.

Real-browser walkthrough (headless Edge via Selenium, a subagent, against the
exact commit exported with `git archive`): Stage 1 with live typing of the
archer count (control appears at 5, "No" selected), Stage 2 (all four bowstyles
offered in every row), advanced mode, then all **7 passes** by hand - on every
pass the heading, "Sitting out" line, no score inputs on the overview, Advance
disabled until the pass is fully scored (and disabled mid-pass), a match page
with "Results so far" and a chart of 4 datasets after saving, and no Advance
button on pass 7 with an "event is complete" link. Results page: 7 rotation
sections, rows per archer [5,5,5,5,6], no rank/points/total column, 10 "View
chart" links, and the first opens a working pair-history chart. The calculator
gave 54.5 for a Portsmouth 500 and 52.8 with the compound box ticked. Console:
only the favicon 404 (plus benign Edge tracking-prevention warnings about the
CDN). The pass-by-pass table from the run: sitting out Ann, Dan, Ben, Eve, Cat,
Ann, then Cat/Dan/Eve with a single Ann-Ben catch-up match.

Things worth knowing, none changed here:
- With byes not shot and more passes than a round-robin needs, earlier pairings
  repeat (pass 6 above is pass 1 again, and the catch-up pass paired two
  archers who had already met - unavoidable there since the short archer had met
  everyone). This follows the existing "cycle the schedule" rule (Assumption 13).
- The clipped-marker limitation noted under task 32 applies to unrealistic
  scores only.
- Percentiles at extreme scores display as 0.0% (noted in Feedback 2 too); the
  winner is still decided on the unrounded values.

## Feedback 3 summary (for anyone picking this up)
All of `Specification/feedback.md` "Feedback 3" is implemented (prd tasks 26-33,
all `completed`): the handicap calculator asks whether the bow is compound and
uses the matching `archeryutils` compound round; Longbow is in the bowstyle
dropdown (scored like Recurve/Barebow); scoring is no longer one page for the
whole pass - an overview of the current pass links to one page per match (score
entry, the pair's results so far, and in advanced mode their chart) and an
"Advance to next pass" button, enabled only once every match is scored, moves
the event on and updates the pairings; and an odd archer count now has a "Shoot
byes?" option (Yes: the bye archer shoots alone; No: they sit out and extra
passes are added so everyone still shoots every arrow). The one real design
decision was how many extra passes "No" needs - Assumption 15 in
`Specification/AISpec.md`; the rule lives in `h2h/rotation.py`'s
`build_sit_out_schedule` if a different one is wanted. Not touched: everything
under "Future Plans - DO NOT IMPLEMENT YET". Final suite: 410 tests passing.


## Feedback 4 - Stage 3 pairings, target setup, graph view, summary table

Scope: every item under `Specification/feedback.md`'s "Feedback 4" heading
(prd tasks 34-44); nothing under "Future Plans - DO NOT IMPLEMENT YET" other
than what Feedback 4 itself promoted out of it (the simple/advanced setup
toggle, redrawing pairings, the reset confirmation, the graph view rename and
the handicap range check). `Specification/AISpec.md` was updated first
(sections 1-6, new 5.2b and 5.8, and Assumptions 22-30; Assumptions 1 and 12 are
superseded again), then `prd.json`.

Assumptions made (full text in `Specification/AISpec.md` section 7):
- **22** - indoor vs outdoor is inferred from the distance: indoor iff <= 25 m.
  I surveyed every round in `archeryutils` as asked ("check this"): nothing
  beyond 30 m is flagged indoor (confirming the expectation), the indoor rounds
  sit at 18 m, 25 m, 20 yd and 25 yd plus one 30 m round (the 80 cm Stafford),
  and every other 30 m round is outdoor - so 30 m is genuinely ambiguous and a
  pure distance rule cannot be perfect there. Chosen: 30 m / 30 yd and up are
  outdoor.
- **23** - the compound reduced 10 applies only when the distance is indoor
  (Feedback 2's wording was "if indoor", and `archeryutils` uses
  `10_zone_compound` only for indoor rounds). Feedback 4's "still have the
  reduced size 10" could be read as "at every distance"; flagged for the user.
- **24** - the standard option lists (8 metric + 8 imperial distances, faces 40,
  60, 80, 122 cm); every combination was checked to work at handicaps 0-150.
- **25** - Stage 3's assignment is a random permutation of archers over schedule
  positions, drawn when Stage 2 is submitted and redrawn on request.
- **26** - graph view is one session-wide setting whose toggle appears only on
  match pages; the results page's "View chart" links still follow it.
- **27-30** - reset confirmation page (POST to reset), the 0-150 handicap range,
  "-" in unscored overview cells, and Advanced setup being rejected server-side.

### Task 34: Rename advanced mode to graph view; toggle only on score-input pages (complete)
`SessionState.mode` ("basic"/"advanced") became a boolean `graph_view` (default
off) with `toggle_graph_view()`; the route is now `POST /graph-view` (the old
`/mode` is gone - a test asserts 404). The context processor injects
`graph_view` instead of `mode`; the chart/explanation condition on the match
page, the chart condition in `app.py`, and the results page's "View chart" links
all read it, so behaviour is unchanged apart from the name. The toggle form moved
out of `base.html`'s nav into `match.html` (the only score-input page), reading
"Graph view: off (turn on)" / "Graph view: on (turn off)" and returning to the
page it was pressed on. Tests: the existing advanced-mode tests were renamed and
repointed, and new ones assert the toggle form is on match pages and on none of
the overview, results, Stage 1, Stage 2, calculator or pair-history pages, that
no template or rendered page says "advanced mode", "basic mode" or "Mode:", and
that toggling keeps scores and the current pass. Suite: 418 passed. The README
still describes the old nav toggle; it is rewritten with the rest of the docs in
task 44.

### Task 35: Show each archer's handicap on the match pages (complete)
The match page's heading and each score-box label now carry the archer's
handicap: "Alice (handicap 15) vs Bob (handicap 22.5)", and for a bye match
"Alice (handicap 15) - bye, no opponent". A small Jinja macro (`named`) builds
the "name (handicap N)" text once, and the number uses `%g` so a whole-number
handicap shows without ".0" (15.0 -> 15) while decimals stay in full (22.5,
7.25). Tests cover before and after scoring, the formatting, that each handicap
sits against its own archer (deliberately very different values, 5 and 120), and
the bye match. Only the match page changed; the overview and results tables are
untouched (the overview table is reworked in task 37).

### Task 36: Simplify the 'How the winner is decided' text (complete)
The explanation in the shared `_pair_chart.html` partial (shown with the chart on
match pages and the pair-history page) went from about 950 characters of
statistical prose (aiming-error standard deviation, convolution, a bowstyle
note, a reference to `humanSpec.md`) to 420 characters in two short paragraphs:
a handicap sets how well an archer is expected to shoot, the curves are the
scores each is expected to shoot and the dashed vertical lines the scores
actually shot; a percentile is the chance of scoring that much or less, and
whoever has the higher percentile did better for their handicap and wins the
pass. Tests extract the rendered block and assert it is under 650 characters,
contains none of the old jargon (convol, standard deviation, sigma, variance,
humanspec, indoor-compound, x-ring, n_pass), still states the percentile, the
higher-percentile-wins rule and the vertical lines, appears only with graph view
on (both pages), and that its wording lives in exactly one template. The
Compound scoring note was dropped from this text on purpose ("simplify"); that
rule is still stated on Stage 2.

### Task 37: Overview table: Match | Score | Percentiles | Winner | Actions (complete)
The per-pass table on `/event/rotation` now has five headed columns. Match is
unchanged ("A vs B", or "A (bye - no opponent, shoots alone)"). Score is "A - B"
in the same order as the opponents; Percentiles is "x.x% - y.y%" in that order
(each archer's percentile in their own distribution); Winner is the winner's
name; Actions is the link into the match page ("Enter scores" until scored, then
"View / edit"). Unscored matches show "-" in Score, Percentiles and Winner, and a
bye match shows its single score and percentile with "-" as Winner (no opponent).
The old "Awaiting scores" / "A 100 - 60 B (B wins)" status text is gone. Pure
template change - the route's per-match view data already carried the results.

Tests use a new `overview_table()` helper (in `tests/helpers.py`) that parses the
rendered table into headings and rows of plain text, so assertions are on whole
cells rather than substrings. Besides the headings, unscored row, scored row
(checked against the Event's own recorded scores, percentiles and winner) and bye
row, one test guards orientation: pass 2 of a 4-archer round-robin contains a pair
listed higher-index first, and its Score and Percentiles cells are checked to keep
that order (a swapped orientation would be caught); another re-saves a match with
the result reversed and checks the Winner cell follows. The existing tests that
matched the old status text were rewritten against cells. Suite: 432 passed.

### Task 38: Confirmation before resetting (complete)
`GET /reset` used to wipe the session immediately, so one stray click on the nav
link lost the whole event. It now renders a confirmation page (`reset.html`) that
says it clears the setup, every archer and every score and cannot be undone, with
a "Reset everything" button (a form POST to `/reset`) and a Cancel link that goes
back to the current pass if an event is running, otherwise to Stage 1. The reset
itself moved to `POST /reset` (`reset_confirmed`), which clears the state and
redirects to Stage 1. GET is now free of side effects, which also means link
prefetching or a browser reload can no longer reset the event. It is a separate
page rather than a JavaScript `confirm()` pop-up so it works without scripting
and is testable (Assumption 27). The nav link is unchanged. Tests: GET leaves the
event, results, archers and schedule untouched; POST resets everything (including
graph view and the byes option) and redirects to Stage 1; the cancel link target
for both cases; the nav link; and that opening the page and navigating away loses
no scores. Suite: 437 passed. Not changed (not asked): resubmitting Stage 1 or 2
still replaces an event in progress without a prompt.

### Task 39: Validate starting handicaps are in 0-150 (complete)
Stage 2 now rejects a handicap outside 0 to 150 inclusive with
"Row N: handicap must be between 0 and 150, got X.", storing nothing (the handler
validates every row before touching state, as before). The check is written as
`not MIN_HANDICAP <= handicap <= MAX_HANDICAP`, so `nan` is rejected too (every
comparison with nan is False), as are `inf`/`-inf`. The bounds are the new
`MIN_HANDICAP` / `MAX_HANDICAP` constants in `h2h.models`, imported by the route
and passed to the template for the inputs' `min`/`max` attributes, so the numbers
are defined once (a test asserts no literal "150" in `app.py` or `stage2.html`).
The existing "must be a number" and "required" messages are unchanged. Decimals
and the boundary values 0, 0.0, 150 and 149.9 are accepted.

One small addition beyond the letter of the request, in the same handler: Stage 2
used to re-render **blank** after any error, so a rejected handicap would have
wiped every typed row (up to a dozen archers). It now refills the names,
bowstyles and handicaps that were submitted (`stage2(error, values=request.form)`),
so only the offending value needs fixing. A test checks the refill. Along the way
the refill template briefly added a stray space inside the `<option>` tags, which
the existing Longbow-dropdown test caught; fixed in the template. Suite: 453 passed.

### Task 41: Target setup model: shared distance and face replace the round mode (complete)
`models.RoundMode` (indoor Portsmouth / indoor WA 18 / outdoor) and the fixed
WA720 70 m outdoor target are gone, replaced by a frozen `TargetSetup(distance,
unit, face_cm)` carrying the shared distance (metres or yards) and face size.
Derived properties: `distance_m` (yards x 0.9144), `indoor` (**distance <= 25 m**,
Assumption 22), and the form-value/label forms ("20yd" / "20 yd"). The standard
options live beside it (`STANDARD_DISTANCES_M/_YD`, `STANDARD_FACE_SIZES_CM`,
`distance_option_groups()` for the Metric/Imperial dropdown groups) with the
default `DEFAULT_TARGET_SETUP` = 20 yd / 60 cm (Portsmouth), and
`TargetSetup.parse(distance_key, face)` validates form values against them.

`resolve_target(setup, bowstyle)` now builds an `archeryutils` `Target` directly
instead of picking a ready-made round: the chosen diameter and distance, the
inferred `indoor` flag (so the existing `per_arrow_pmf` picks the 9.3 mm indoor or
5.5 mm outdoor arrow with no change to the stats engine), and the scoring system
`10_zone_compound` only for Compound at an indoor distance, `10_zone` otherwise
(Assumption 23). `Event` takes a `TargetSetup` where it took a `RoundMode`
(`event.target_setup`), and `SessionState` stores `target_setup` (reset restores
the default). The calculator keeps its Portsmouth/WA 18 choice through a tiny
`IndoorRound` enum feeding `resolve_indoor_round`; its behaviour is unchanged.

Why this is safe: before writing it I built every combination of the offered
distances x faces x (Recurve, Compound) as a `Target`, ran it through
`per_arrow_pmf`, the 12-arrow convolution and `equivalent_handicap` at handicaps
0, 40, 100 and 150 - 512 combinations, zero failures (now a test) - and confirmed
a hand-built 20 yd/60 cm Target is *equal* to archeryutils's own Portsmouth target
(and the compound, WA 18, WA 18 compound and WA720 70 m ones), so the new path
reproduces the old targets exactly (also tests).

Temporary bridge: the Stage 1 form is not rebuilt until task 42, so `app.py` maps
the old Indoor/Outdoor + Portsmouth/WA 18 fields onto a `TargetSetup`
(Portsmouth -> 20 yd/60 cm, WA 18 -> 18 m/40 cm, outdoor -> 70 m/122 cm) and back,
in two clearly marked helpers that task 42 deletes. The prd criterion about grep
was narrowed accordingly (no `RoundMode`; the lowercase form-field name survives
only in the bridge). Tests: `test_target_resolution.py` was rewritten (indoor
inference incl. the 25 m/30 m boundary and yards, unit conversion, option lists,
parse validation, resolution rules, equality with archeryutils's rounds, the
512-combination sweep); `RoundMode` uses in the event, state, chart-data and
integration tests were migrated to shared setups in `tests/helpers.py`, and new
tests cover the stored/default/reset setup and an Event using a non-default one
(including that Compound and Recurve share a distribution outdoors but not
indoors). Suite: 505 passed.

### Task 42: Stage 1: simple/advanced setup toggle with distance and face-size dropdowns (complete)
Stage 1's Indoor/Outdoor and Portsmouth/WA 18 radios are replaced by a "Setup
mode" toggle (Simple default, Advanced). Simple shows two dropdowns: Distance
(optgroups Metric and Imperial, the 16 standard options, 20 yd preselected) and
Face size (40/60/80/122 cm, 60 cm preselected), plus a one-paragraph note that
distances up to 25 m / 25 yd count as indoor and what that changes. The route
validates both against the standard lists via `TargetSetup.parse` (a forged value
gets "not one of the standard distances/face sizes" and stores nothing) and the
chosen values are re-selected when Stage 1 is revisited. Advanced shows a "TBA"
message, hides the dropdowns and disables the submit button; a forced POST is
refused server-side with the same message and, because that check now runs
before the numbers are parsed, never reports a different error. The temporary
bridge from task 41 is deleted. Stage 2's intro now says what everyone shoots
and whether it counts as indoor (with the reduced-10 note only when indoor),
replacing the old "round mode" wording.

Verified in a real browser (headless Edge via Selenium, a subagent, against the
exact commit exported with `git archive`): fresh page has Simple selected,
dropdowns shown, TBA hidden, submit enabled, and the option lists are exactly the
standard ones in the right groups; clicking Advanced hides the dropdowns, shows
the TBA text and disables submit (clicking it or pressing Enter in a field made no
request); back to Simple restores everything; choosing 50 m / 80 cm reaches Stage
2 whose intro says outdoor; returning to Stage 1 remembers 50 m / 80 cm; 20 yd /
60 cm gives an intro saying indoor with the inner-ring note; the Shoot byes control
and the arrows-per-pass slider still work (total 40 -> label 10); only the usual
favicon 404 in the console. The check found one cosmetic bug I had missed - the
intro read "at a 80 cm face" (and "a 122 cm" is wrong too) - fixed by rewording
to "with a face size of 80 cm", which is correct for every size.

Tests: 15 new route tests (toggle and defaults, the exact distance/face option
lists and groups, old radios gone, stored and remembered setup, parametrised bad
distance/face values, Advanced refused with state untouched and the page
re-rendered with Advanced selected and submit disabled, refusal precedence, TBA
text present but hidden under Simple, the Stage 2 intro for an indoor and an
outdoor setup, and a scan that no `round_mode`/`RoundMode`/bridge names remain
in `h2h/`). The shared test form helpers were switched to the new fields.
Suite: 520 passed.

### Task 43: Stage 3: random pairing assignment with redraw (complete)
Setup now has three stages. Submitting Stage 2 no longer starts the event: it
stores the archers (`SessionState.pending_archers`, entry order) and draws a
random assignment of archers to the Stage 1 schedule's positions (`assignment[
position]` = index into `pending_archers`), then redirects to `/event/stage3`.
Stage 3 lists **every pass** (Pass | Matches | Sitting out): each pairing by name,
the bye archer as "(bye - shoots alone)" when byes are shot, and the sitting-out
names when they are not. **Redraw pairings** (`POST /event/stage3/redraw`) draws
again and returns to Stage 3; **Confirm pairings and start event** (`POST
/event/stage3`) builds the `Event` from `assigned_archers()` (so `event.archers[
position]` is the assigned archer and the rest of the app is unchanged) and goes
to the overview. Reaching Stage 3 early redirects to Stage 1/2; once the event has
started the page and both buttons redirect to the overview and change nothing.
The schedule built at Stage 1 is reused untouched - only who fills each position
changes (Assumption 25).

Design points worth knowing:
- The random source is the injectable `SessionState.rng` (default
  `random.Random()`, excluded from equality/repr). Tests use `NoShuffle`
  (`tests/helpers.py`), whose shuffle does nothing, for a deterministic
  entry-order draw, and seeded `random.Random`s for the redraw tests.
- A redraw **prefers pairings that actually differ**. With 4 archers a fresh
  permutation reproduces the displayed pairings 1 time in 6 (4 permutations
  per pairing schedule), so a plain reshuffle would sometimes make the button
  look broken. `redraw_pairings` compares a hashable signature of who meets
  whom (and who byes/sits out) per pass and retries up to 50 times; with only 2
  archers there is nothing different to find and it keeps the last draw. (A
  smoke test of the real unseeded app: 6 redraws with 6 archers gave 6 distinct
  pairing sets.)

**A flaky-test lesson from this task:** after the migration the suite passed once
and then failed one test on the next run. Cause: `make_client_and_state` still built
a plain `SessionState()`, so its Stage 3 draw really was random and tests that use
archer positions (e.g. "archer 0 scores 120 and wins") passed or failed depending
on whether the two archers had been swapped. Fixed by building every
position-dependent test client from `make_state()`; the suite then ran green 8
times in a row. Any future test that refers to archers by index must use the
identity-draw state.

Tests: state tests (draw is always a permutation, injectable/seeded/identity
sources, default source really random, redraw always changes the pairings for 4
archers over 25 draws and is safe for 2, schedule structure untouched, early
calls raise, re-entering Stage 2 discards the draw and event, and the existing
Stage 2/event tests migrated to the two-step flow); route tests (Stage 2 ->
Stage 3 with no event, a rejected Stage 2 draws nothing, every pass shown with
pairings by name and a full 6-pair round-robin for 4 archers, bye and sit-out
displays, stable on reload, redraw changes the pairings, confirm starts the event
in the shown order with the overview matching Stage 3's first pass, early-access
redirects, and a started event being immune). Test helpers now run Stage 3's confirm
after Stage 2. Suite: 543 passed.

### Task 40: Fix hover tooltip over previous-pass vertical lines (complete)
Delegated to a subagent, which reproduced the bug in a real browser (headless
Edge via Selenium, ActionChains, against an exported copy of the committed
code) before changing anything, diagnosed it from the Chart.js 4.4.4 source and
in the browser, fixed it in `h2h/static/match_chart.js` only, and re-verified.
I reviewed the diff and the final file before accepting it.

**Reproduction** (Alice Recurve 15 vs Bob Compound 45, 24 arrows, 12 per pass,
x-range 92-120, pass 1 = 118/108, pass 2 = 115/100): whenever the pointer is
within half a score unit (about 16 px at 32 px per score) of *any drawn marker
line* the tooltip is wrong - its title reads "92" and its data points are the
curves' leftmost points (Alice 0.0, Bob 1e-05) instead of the score under the
pointer. Every position in that window failed (on the line, +/-1-3 px, +/-0.4
score, top and bottom of the line); +/-0.6 score and beyond were correct. It
was not specific to *previous* passes, as the feedback put it: the latest
pass's markers failed identically (unticked: 30 of 155 positions failed;
ticked: 60 of 185 - 30 for each pass), but with the checkbox unticked a previous
pass's line is not drawn, so the bug was only visible there once the box was
ticked, which is presumably why it was noticed as a previous-pass problem. A
fresh pair with no markers had 0 of 125 failures.

**Root cause** (my hypothesis, refined): Chart.js "index" interaction mode
measures the x-distance to every visible dataset's points *including the
2-point marker datasets*, keeps `items[0]`, then returns every dataset's element
at that item's data **index**. A marker's integer x lands exactly on a curve
point's x, so within half a score of the line the marker and the nearest curve
point are exactly equidistant and ties are all kept; markers have `order: 1` and
curves `order: 2`, so the marker is evaluated first and `items[0]` is the marker's
point at data index 0; index mode then returns every dataset's index-0 element.
`tooltip.filter` only removed the marker rows afterwards. Confirmed by setting the
markers' `order` to 3 at runtime, which made the hover correct. So it is a tie
broken by dataset order, not the marker being nearer.

**Fix:** a custom interaction mode, `Chart.Interaction.modes.nearestCurveX`, that
for each visible non-marker dataset returns the element whose x is nearest the
pointer (so markers can never be an active element, and never influence which
score is chosen); `interaction.mode` is now `"nearestCurveX"`. The now-redundant
`tooltip.filter` was removed. Dataset structure, legend labels, the checkbox
code and dataset counts are untouched, and a comment explains why the built-in
mode cannot be used.

**Verification** (real browser, exported HEAD with the fixed JS): for every
position, the tooltip has exactly two data points (the two curves, no markers)
whose `raw.x` is the curve x nearest the pointer and `raw.y` equals the
distribution value there, and the active elements are exactly those two points.
Default scenario: 155 positions unticked, 185 ticked, 155 unticked again, and 125
on a fresh pair with no passes - 620 positions, 0 failures (a 7.3 px grid plus
+/-3 px, +/-0.4, +/-0.6 and +/-1 score around each marker line and the top and
bottom of each line). A wider variant (Alice hc 40 / Bob hc 60, range 72-120,
other scores) gave 616 more positions (154+184+154+124), 0 failures. Dataset counts and labels
unchanged (4 unticked, 6 ticked for two passes, 2 with no passes, back to 4 when
unticked); hovering 1 px inside the left and right plot edges gives a fully
visible tooltip in all three states; the console has only the favicon 404 and
benign Edge tracking-prevention warnings about the CDN. Screenshots of the broken
and fixed hover are in the scratchpad (`hover_work/shots/`). No Python changes,
so the Python suite is unaffected.

### Task 44: End-to-end integration check, browser walkthrough and docs (complete)
`tests/test_integration.py` gained seven scenarios over the real routes: a 50 m /
80 cm event (every archer gets that distance and face, outdoors, Compound scores
plain `10_zone`, so Recurve and Compound share a distribution); an 18 m / 40 cm
event (Compound `10_zone_compound`, the others `10_zone`, distributions differ);
the imperial conversion and classification (30 yd outdoor, 25 yd indoor); the
whole setup flow (Stage 2 refuses 150.1 and stores nothing, then accepts; a
seeded Stage 3 redraw changes the pairings; confirming starts the event with
exactly the pairings shown and the assigned order); the overview table's Score,
Percentiles and Winner for every match of a full event checked against the
Event's own results; the graph view toggle living only on match pages and
switching the chart and explanation without losing scores; and reset (GET asks,
loses nothing; POST clears; Stage 3 then redirects to Stage 1). README.md was
rewritten for the three-stage setup, the setup modes, graph view and the reset
confirmation. Suite: 550 passed.

Real-browser walkthrough (headless Edge via Selenium, a subagent, against the
exact final commit exported with `git archive`) - all eight steps passed:
- **Stage 1:** Advanced shows the TBA text, hides the dropdowns and disables
  submit; Simple restores them; 50 m / 80 cm / 36 arrows with the slider on 12.
- **Stage 2:** the intro says "50 m with a face size of 80 cm, which counts as
  outdoor" with no inner-ring note; a handicap of 160 stays on Stage 2 with "Row
  4: handicap must be between 0 and 150, got 160." and every typed row refilled
  (inputs also carry min=0 max=150); correcting it moves on.
- **Stage 3:** a Pass | Matches | Sitting out table with 3 rows of two pairings;
  three redraws each differed from the draw before; the overview's pairings equal
  the last Stage 3 table's first row.
- **Overview and match pages:** the five exact headings, "-" cells and a disabled
  Advance before scoring, no graph toggle or "Mode" button anywhere on it; match
  heading and labels show handicaps ("Ben (handicap 30) vs Dan (handicap 50)");
  the toggle button reads "Graph view: off/on", the chart has 2 datasets then 4
  after saving, and the explanation is 420 characters with none of the old
  jargon; the row then reads "95 - 88", "18.6% - 98.1%", winner "Dan", "View /
  edit"; Advance enabled only after both matches were scored.
- **Reset:** the nav link opens "Reset everything?" and loses nothing (results
  and "Pass 2 of 3" intact); confirming lands on Stage 1 with no event.
- **Hover:** a 2-archer, 2-pass event with previous passes ticked (6 datasets):
  24 pointer positions on and 2 px either side of all four marker lines, at two
  heights, each gave exactly the two curve data points at the right score and
  probability, titled with the marker score and never the minimum. A negative
  control (forcing Chart.js's built-in `index` mode back on in the live page)
  returned 6 data points including marker datasets and the leftmost score, so the
  probe does detect the old bug.
- Console: only the favicon 404 (plus benign tracking-prevention warnings about
  the CDN); no server errors. (Chromium refuses port 5060 as unsafe; that was the
  test harness's port choice, not an app issue - the app's default port is fine.)
  The agent also noted that consecutive redraws can keep an individual pass the
  same: with 4 archers there are only 3 possible matchings per pass and 6 distinct
  schedules in all, so partial overlap is inherent; a redraw guarantees the whole
  set of pairings changes, not every pass.

## Feedback 4 summary (for anyone picking this up)
All of `Specification/feedback.md` "Feedback 4" is implemented (prd tasks 34-44,
all `completed`): archers' handicaps show on match pages; setup has a third stage
that draws the pairings at random with a Redraw button; Reset asks for
confirmation; the old advanced mode is "graph view", toggled only from match
pages; the chart hover bug is fixed; Stage 1 has a Simple/Advanced setup toggle
(Simple: distance and face-size dropdowns with indoor/outdoor inferred from the
distance; Advanced: TBA); starting handicaps must be 0-150; the "how the winner
is decided" text is short and plain; and the overview table is Match | Score |
Percentiles | Winner | Actions. Decisions worth a second look, all recorded in
`Specification/AISpec.md` section 7: **22** indoor iff distance <= 25 m (the
`archeryutils` survey found nothing beyond 30 m indoor; 30 m itself is ambiguous
because of the Stafford); **23** Compound's reduced 10 only when indoor (change
`resolve_target` if it should apply at every distance); **26** the results page's
"View chart" links still follow graph view. Small additions beyond the letter of
the feedback: the Stage 2 form refills after an error, and a redraw prefers
pairings that actually differ. Not touched: everything under "Future Plans - DO NOT
IMPLEMENT YET" apart from what Feedback 4 promoted out of it. Final suite: 550
tests passing.


## Feedback 5 - Graph markers, tie-break, advanced setup, outputs, calculator

Scope: every item under `Specification/feedback.md`'s "Feedback 5" heading
(prd tasks 45-56). Items that were under "Future Plans" before and are now
promoted into Feedback 5 (advanced setup, the leaderboard/per-archer results/
exports) are built; what is still under "Future Plans - DO NOT IMPLEMENT YET"
(the handicap moving average, nicer UI/maths explainer/user guide/publication)
is not touched. `Specification/AISpec.md` was updated first (sections 1-6, new
5.4a, and Assumptions 31-40; Assumptions 6, 10 and 30 are superseded), then
`prd.json`.

Assumptions made (full text in `Specification/AISpec.md` section 7):
- **31** - chart markers: every score each of the two archers has shot, against
  any opponent (the old chart used only passes the pair had shared); the
  default shows only the current pass's scores; labels are "P<n>" on the chart.
- **32** - the handicap is removed from the match page heading only; it stays
  beside the score boxes (graph view is off by default, so the legend alone
  would leave the page with no handicaps, against Feedback 4).
- **33** - tie-break: relative percentile tolerance 1e-9; two mutually exclusive
  tick boxes always shown on paired matches; an unresolved tie is rejected, not
  stored; ticks editable until the pass is advanced.
- **34** - advanced setup: "face type" = an `archeryutils` scoring system (16 of
  them, not "Custom"), "shape" read as face size; bowstyle has no effect on the
  target in advanced mode.
- **36-38** - outputs use only fully scored ("completed") passes; leaderboard
  ranks by points with shared ranks; the per-archer heading handicap is the
  entered one, and the Average row leaves Pass and Opponent blank.
- **39-40** - plain-UTF-8 CSV, `fpdf2` for the PDF; the calculator offers the AGB
  and WA indoor/outdoor rounds only.

### Task 45: Tie-break in the statistics engine and event model (complete)
`h2h.stats.decide_pass_winner` lost its `rng` parameter and the coin flip. It now
compares percentiles (tied when their *relative* difference is below 1e-9), then
raw scores, then an optional `closest` ("a"/"b"), and returns a `PassDecision`
(winner, decided_by with "percentile", "score" or "closest"). A full tie with no
`closest` raises `TieBreakRequired` (a `ValueError` subclass); an unneeded
`closest` is ignored. `PassResult` gained `decided_by` (None for a bye), and
`Event.record_match(scores, closest=None)` passes the ticked archer's index
through, validating it is one of the pair; nothing is recorded when a tie is
refused, so an earlier saved result for the match survives a rejected re-save.
`import random` is gone from `stats.py`.

The first version used an absolute tolerance of 1e-9 and 24 existing tests failed:
their scores (e.g. 60 for archers of handicap 20 and 25) sit so far in the lower
tail that both percentiles are around 1e-18, which an absolute tolerance calls a
tie. Rounding error in a sum of probabilities is relative to the sum, so the
tolerance is now relative (`math.isclose(rel_tol=1e-9, abs_tol=0)`), after which
only the intentional ties remained; the spec (Assumption 33a) and the prd test were
corrected to say so. Tests: the old coin-flip test became a refusal test, plus
tie-chain, tolerance (ties at the top end, non-ties in the lower tail, exact zeros),
determinism, `closest`-ignored, re-save and bye cases at the stats and event level.

One piece of task 47 was done here so the commit stays green: the match POST
handler now reads the `closest` tick (rejecting several ticks, or one that is not in
the match; ignoring it for a bye match) and hands it to `record_match`, and the
test helpers' `score_current_pass` resolves a tie (the mixed-bowstyle integration
tests deliberately give same-handicap archers the same score) by ticking the
lowest-numbered archer. The boxes themselves, the note, the script and their tests
are still task 47. Suite: 573 passed.

### Task 46: Match page - plain heading and a this-pass-only table (complete)
The match page's `<h1>` is now just the names ("Alice vs Bob" / "Alice - bye, no
opponent"); each handicap stays beside its own score box (Assumption 32). The
"Results so far" section (every pass the pair had shared, with Pass, Equiv.
handicap and Opponent columns) is replaced by one "This pass" table, shown once
the match has scores: Archer | Score | Percentile | Winner, one row per archer in
match order, Winner "Yes"/"No" (a bye shows "-"). Because nothing uses them any
more I removed `Event.pair_results` (and its two tests), the route's `history`
plumbing and the `show_pass` option of the shared `_results_table.html` partial;
the Results page keeps that partial unchanged. Tests: the "pair history" and
"results so far" tests were rewritten as table tests (headings, rows in match
order, values equal to the Event's results for four score pairs, only the current
pass's rows when a pair meets twice, no other match's archers), and the heading
tests now assert the names-only heading with handicaps in the score labels.
Suite: 573 passed.

### Task 47: Tie-break tick boxes on the match page (complete)
A paired match's form now has a "Tie-break: closest to the middle" fieldset with one
checkbox per archer (both named `closest`, value = archer index) and a note that
they are only used if the percentile and score are exactly tied; a bye match has
none. A small script at the end of the page clears the other box when one is
ticked; the server independently rejects two ticks ("Tick only one archer as
closest to the middle.") and a value outside the match. The route (whose
`_closest_archer` helper came with task 45) now turns `TieBreakRequired` into
"Percentile and score are tied. Tick which archer's arrow was closest to the
middle, then save again." - nothing is saved, the typed scores stay in the boxes and
the ticks are shown as submitted. A saved match decided by the tick shows that
archer's box ticked on reopening and a note under the This pass table ("Percentile
and score were tied; decided by closest to the middle."); an unneeded tick is
ignored (the model does not store it), so it is not shown again. Tests: eleven
route tests (box markup and bye, refused tie with kept scores and message, accepted
tie and winner everywhere incl. the overview, both boxes ticked, foreign archer,
unneeded tick, edit to untied scores clears the note, edit back to a tie keeps the
saved result, a tie with both ticks is rejected for the ticks, the script is
present). Suite: 583 passed. The in-browser check of the script (ticking A then B
leaves only B) is run by a subagent against this commit; its result is recorded
below before the task is marked complete.

Task 47 browser check (subagent, headless Edge 154 via an ephemeral Selenium install,
against `git archive` of commit 45be90c, port 5071): PASS on all four points. Through
the UI to /event/match/0 there are exactly two `closest` checkboxes (labelled with the
two archers); ticking A, then B, then A again leaves only the last-ticked box ticked
and unticking leaves none; entering 90 and 90 with no tick returns the page with the
"Percentile and score are tied. Tick which archer's arrow was closest to the middle,
then save again." warning, both score boxes still 90 and no table; ticking Ben and
saving shows the This pass table (Ann 90 / No, Ben 90 / Yes), the "decided by closest to
the middle" note and Ben's box ticked; the console had only the favicon 404. (The agent
noted that which archer is listed first depends on the random Stage 3 draw, so it found
the boxes by label, and that the app's single in-memory event means the server must be
restarted between runs.) Task 47 is therefore complete.

### Task 48: Per-archer target setups and per-target maximum score (complete)
`TargetSetup` gained an optional `face_type` (an `archeryutils` scoring system; None
keeps simple setup's bowstyle-based choice) and `TargetSetup.parse_advanced(distance,
face size, face type)`, which validates all three against the offered options and
names the one that is wrong (the simple `parse` is unchanged and still accepts only the
four standard sizes). `resolve_target` uses a given face type exactly (the bowstyle is
ignored, so a Compound archer can be given the plain face indoors and a Recurve one the
reduced 10). `Archer` has an optional `target_setup`; `Event` uses it if set, falls back
to the shared one, and takes `target_setup=None` when every archer has their own
(otherwise it raises, naming the archer). New options in `models.py`: `FACE_TYPES`
(all 16 non-Custom `archeryutils` scoring systems with hand-written readable names, a
system added by a future library version is still offered under its own name and a test
fails to prompt a proper one), `ADVANCED_FACE_SIZES_CM` (20, 35, 40, 50, 60, 65, 80,
122) and `DEFAULT_FACE_TYPE`. The hard-coded `MAX_SCORE_PER_ARROW = 10` is gone: new
`max_arrow_score(target)` (the highest ring, 10 / 9 for 5-zone / 11 / 5 / 1 ...) and
`Event.max_score_for(i)` feed `record_match`'s validation (each score is checked against
its own archer's maximum), the match page's score boxes (max attribute and label) and the
chart payload's x-clamp. Engine check (all 16 face types x faces 20/40/60/122 x
18 m/20 yd/50 m/100 yd x handicaps 0/50/100/150): the per-arrow PMF sums to 1, is
non-negative, scores in whole numbers, has mean equal to `archeryutils`' `arrow_score`,
and the pass distribution sums to 1 within [0, n_pass x maximum]; no engine change was
needed. Suite: 695 passed.

### Task 49: Advanced setup - per-archer face type, face size and distance (complete apart from the browser check)
Stage 1's Advanced mode is built. Selecting it still hides the simple distance and
face-size dropdowns, but now shows a note that each archer's target is chosen in
Stage 2, and Continue is never disabled; the "TBA" text and the server-side refusal
are gone, and the three TBA tests were replaced. `SessionState` gained
`setup_mode` ("simple"/"advanced", validated in `start_stage1`, restored by `reset`,
remembered when returning to Stage 1); in advanced mode the Stage 1 handler does not
validate the hidden simple fields and keeps the session's last simple distance and
face. Stage 2 in advanced mode adds three dropdown columns per archer (target face
type with the 16 readable names, face size 20 to 122 cm, and the Metric/Imperial
distance list, defaults 10 zone / 60 cm / 20 yd) and a different intro; each row is
parsed with `TargetSetup.parse_advanced` and a bad value is reported as "Row 3: ..."
with the form refilled; `start_stage2` refuses an archer without a setup in advanced
mode, and `start_event` builds the Event with no shared setup. The distance dropdown
markup is now a shared macro (`_form_macros.html`) used by Stage 1 and the Stage 2
rows. Tests: Stage 1 mode handling, rejected mode value, Stage 2 option lists and
defaults, simple Stage 2 unchanged, valid rows reaching each archer's resolved target
(a compound face for a Recurve archer's neighbour, a 5-zone archer at 50 yd, a
Worcester face), bad values per field, missing fields, and a full 2-archer event with a
5-zone and a 10-zone archer over HTTP (maximum 108 vs 120, percentiles from each own
distribution); five state tests. Suite: 712 passed.

### Task 50: Chart data - every score each archer has shot, axis limits that include them, handicaps for the legend (complete)
Root cause of "Show previous passes adds no lines in later passes": `build_pair_chart_data`
built its marker list only from passes in which *these two archers* had faced each
other (`results_a` and `results_b` keyed by opponent), so for a pair meeting for the
first time in pass 3 there was nothing earlier to show. The payload now has, for each
archer, `passes: [{index, score}]` covering every scored pass of theirs against any
opponent (a bye pass is included, a sat-out pass is absent), plus a `legend` label
("Name (handicap H)", 15.0 shown as 15) and the event's `current_pass` (the pass shown
by default); the old top-level shared `passes` list is gone. The x-range is the curves'
trimmed range widened to include every score in either list with a margin of 1, clamped
to [0, the larger archer maximum], and is one fixed range (so it does not move when the
box is ticked); curve points are listed over the final range. The pair of archers on
different faces use `max(Event.max_score_for(a), ...(b))` as the clamp (from task 48).
`match_chart.js` was changed just enough to read the new payload (markers from each
archer's own list, only `current_pass` by default, all when ticked); the on-chart labels,
the legend and the real-browser verification are task 51. Tests: `test_pair_chart_data.py`
rewritten (16 tests: scores across three different opponents, a pair that has not met
still showing earlier scores - the reported bug, bye and sit-out passes, current_pass,
far-out low and high scores widening the range, clamping at 0 and 120, an in-range event
leaving the range unchanged, the range covering an early far-out score, curve points over
the final range, legend labels, a 5-zone vs 10-zone pair, JSON-serialisable) and the two
route tests that read the payload. Suite: 726 passed.

Task 49 browser check (subagent, headless Edge 154 via an ephemeral Selenium install, against
`git archive` of commit 921ebb3, port 5072): PASS on all five points, no console errors
beyond the favicon 404. Stage 1: Simple selected initially with both dropdowns shown; choosing
Advanced hides both and shows the "each archer shoots their own target face type, face size
and distance" note with Continue still enabled; choosing Simple reverses it; "TBA" appears
nowhere. Stage 2 (3 archers, advanced): headers Name, Bowstyle, Handicap, Target face type,
Face size, Distance; each row has 16 face types ("10 zone (standard 10-ring face)" selected),
8 sizes (60 cm selected) and 16 distances in Metric/Imperial groups (20 yd selected). A mixed
event (Recurve 10 zone 40 cm 18 m; Compound 10 zone compound 40 cm 18 m; Barebow 5 zone 122
cm 50 yd) reached Stage 3 and the overview; on every match page of all three passes the
5-zone archer's box was "(0-108)" / max 108, including their bye pass, and the others
(0-120). Defaults-only submission (2 archers) also reached Stage 3 and the overview. Task 49
is therefore complete.

### Task 52: Outputs model - completed passes, leaderboard and per-archer results (complete)
New Flask-free module `h2h/outputs.py`, plus `Event.completed_passes` (the rotations in
which every match is scored). `leaderboard(event)` returns one `LeaderboardRow` per
archer (rank, name, points = passes won, passes decided = completed passes with an
opponent), ordered by points then event order, with competition ranking for ties (1, 2,
2, 4 / 1, 1, 3, 3); `archer_results(event)` returns, in event order, an `ArcherResults`
per archer: name, entered handicap, total score, a row per completed pass they shot in
(1-based pass number, opponent name or "bye", score, percentile as a 0-1 fraction,
equivalent handicap or None) and an `ArcherAverages` (mean score, percentile and
handicap ignoring a None handicap; None when there are no rows). Only completed passes
count (Assumption 36), so a half-scored pass changes nothing until its last match is
saved, a re-saved match is not counted twice (the model replaces its results), a bye pass
scores no point and is not "decided", and a sat-out pass has no row. Tests (17): empty
state, partial pass left out then included, points equal the Event's own winners over a
whole event and total one per decided match, ranking with chosen win counts (fake results
inserted directly, since the real winner depends on the maths), the bye and sit-out
cases, re-save, row contents and order, totals and averages including the None-handicap
cases, and a module-hygiene test (no Flask import, a docstring on every function).
Suite: 743 passed.

### Task 53: Results page leaderboard and per-archer results page (complete)
The Results page has a Leaderboard table (Rank | Archer | Points | Passes decided) above
the pairwise results, with a line saying only completed passes count and how many of the
event's passes that is so far ("1 of 3 so far"), and a link to the new Archer results page;
the old "not a ranked leaderboard" sentence is gone, and the pairwise and per-pass sections
are unchanged. New page `/event/archers` ("Archer results", also in the nav bar on every page)
renders, per archer in event order, the heading "<name> - total score <N> - handicap <H>" (H as
entered, 15.0 shown as 15), then a table Pass | Opponent | Score | Percentile | Handicap (an
integer pass number, the opponent's name or "bye", percentile to one decimal with a % sign,
handicap to one decimal or "-" for a score of 0) and a final Average row; an archer with no
completed pass (not yet scored, or sat out) shows "No completed pass for <name> yet", and with
no completed pass at all the page says so. Both pages redirect to Stage 1 with no event and are
recomputed on every request from `h2h.outputs`. One spec detail settled here: an average row
cannot have both "blank Pass and Opponent cells" and an "Average" label, so the label "Average"
spans the Pass and Opponent columns (colspan 2) and AISpec 5.4a, Assumption 38 and the prd 53
wording were corrected to say so. A test-writing slip worth noting: my new helper
`start_four_archer_event` had the same name as an existing one and silently replaced it for the
whole module, which broke three older tests (they saw "Ann vs Dan" for "A1 vs A4"); it was
renamed. Tests: eight new route tests (leaderboard equals the outputs model, live and waiting for
the whole pass, the per-archer sections' headings/columns/values/average row, zero-score dash
and average, bye and sat-out passes, empty state, redirects, nav link) replacing the old
"no leaderboard" test. Suite: 750 passed.

### Task 54: Exports - leaderboard and archer results as CSV, everything as PDF (complete)
Dependencies added with `uv add fpdf2` (2.8.9, pulling in Pillow and fontTools; pure-Python PDF
writer, chosen over `reportlab` for its smaller footprint and a built-in table API) and
`uv add --dev pypdf` (so the tests can read the PDF text back); both install and import on
Python 3.14. New Flask-free `h2h/exports.py` over `h2h.outputs`: `leaderboard_csv`
(`Rank,Archer,Points,Passes decided`), `archer_results_csv` (a tidy table, `Archer,Handicap,Pass,
Opponent,Score,Percentile (%),Handicap of score`, one row per archer per completed pass, no
Average rows, percentile as a plain number such as 59.8, empty handicap cell for a zero score,
standard csv quoting) and `results_pdf` (A4: title with the number of completed passes, the
leaderboard, then each archer's heading and a table with the Average row, headings repeating
across pages, built-in Helvetica with characters outside Latin-1 replaced by "?"). CSV is plain
UTF-8 with no byte-order mark so `pandas.read_csv` gets clean column names (Excel may need the
file imported as UTF-8 to show accents; Assumption 39). Routes `/event/export/leaderboard.csv`,
`/event/export/archer-results.csv` and `/event/export/results.pdf` send attachments with those
filenames (and redirect to Stage 1 without an event); a shared `_export_links.html` partial puts
the three links on the Results and Archer results pages. Note, not acted on: cell text is
user-typed names, and a name starting with = + - or @ would be read as a formula by a
spreadsheet; the scorer opens only their own export on their own machine, so no escaping was
added (it would also alter the data). Tests (19): dependency declarations, CSV headers/rows equal
to the pages' own, tidy output without Average rows, a name with a comma and a quote
round-tripping, partial pass excluded, no BOM / numeric percentile / empty zero-score handicap,
PDF validity and content read back with pypdf (title, headings, every archer once, the Average
label, multi-page flow with 8 archers, "?ukasz" for a name with a letter outside Latin-1, the
empty-state PDF), route types, filenames, redirects, links on both pages, and liveness.
Suite: 769 passed.

### Task 55: Handicap calculator - indoor/outdoor choice and every standard round (complete apart from the browser check)
The calculator form is rebuilt: Indoor/Outdoor radios (Indoor default), a round dropdown for
the chosen kind (both lists are rendered and a small script shows the matching one and shows
the compound checkbox only indoors, so with script off the page opens correctly on indoor
Portsmouth), the compound checkbox, and the score. The indoor list is every non-compound round
of `archeryutils`'s `AGB_indoor` and `WA_indoor` sets (16: Bray I and II, Stafford, Portsmouth,
Vegas, Vegas 300, WA 18m, WA 25m with their triples, Worcester and Worcester 5-Spot) and the
outdoor list every non-compound round of `AGB_outdoor_imperial`, `AGB_outdoor_metric` and
`WA_outdoor` (76), sorted by name, defaults Portsmouth and WA 70m. `IndoorRound` and
`resolve_indoor_round` were replaced in `models.py` by `calculator_rounds(kind)` and
`calculator_round(kind, codename, compound)`: an indoor round with the compound box ticked maps
to its `archeryutils` compound variant (`X_compound`, or `X_compound_triple` for a triple) where
one exists (Portsmouth, WA 18/25, Bray, Stafford, Vegas do; Worcester and Vegas 300 do not and
are used as chosen), outdoor rounds ignore the flag, and a round outside the chosen kind's list
is a ValueError. The route validates kind, round and score on the server and re-shows the
submitted choices after a result or an error. Found and fixed on the way: a score of "nan"
(which `float()` accepts) went through and would have shown "Handicap: nan"; non-finite scores
now get the same friendly "valid score" error (this gap predates Feedback 5). The earlier
leftover-names guard test forbade the string "OUTDOOR" in the app (a check for the removed
fixed outdoor target); that constant now legitimately means the calculator's outdoor kind, so
the guard checks "IndoorRound" instead. Tests (30, replacing the 13 old calculator tests): list
contents and exclusions, defaults, round lookup incl. every compound variant and the no-variant
rounds, wrong-kind and unknown rounds, page markup, archeryutils-equal results for indoor
plain/compound and for three outdoor rounds (a forced compound flag ignored), friendly errors
for bad kind and for five bad scores with and without compound, choices re-shown, and every one
of the 92 listed rounds giving a finite handicap for a mid-range score. Suite: 792 passed.

### Task 51: Chart front end - pass-number labels, handicap legend, axis from the payload (code; browser check below)
`match_chart.js` now: draws, unticked, only the markers whose pass is the payload's `current_pass`
and, ticked, every score of both archers (so later passes gain lines); labels each marker line on
the chart with its pass number ("P3": rotated text near the top of the plot, in the line's
colour) through a small inline Chart.js plugin; lists only the two curves in the legend, named
with their handicaps ("Cat (handicap 40)"); and takes the x-axis min/max from the payload. The
hover mode (`nearestCurveX`) is unchanged.

Real-browser check #1 (subagent, headless Edge 154 via Selenium, commit df6835c, Chart.js 4.4.4
from the CDN) of a 4-archer, 3-pass event and of 2-archer events: PASS for the main behaviours -
a pair that had not met in pass 1 shows, with the box ticked, both archers' pass-1 scores (0
markers unticked, 2 ticked, 0 again; then 2/4 after scoring pass 2 and 2/6 in pass 3); every
marker lies inside the x-scale (4 to 120) with scores of 5 and 118; the legend has exactly the
two "Name (handicap H)" entries and no markers; the heading has no handicap; labels P1/P2/P3
appear beside their lines in the right colours; console clean (favicon 404 and Edge
tracking-prevention warnings about the CDN only). It found two real defects, both fixed:
(1) the label of a marker at the very edge (score 5, 8.4 px past the plot's left edge; score
118, 0.7 px past the right edge) stuck out of the plot because the server's margin of one
score unit is only about 7.6 px on a 116-unit axis while a label needs about 16 px, and in a
tight chart (two lines a score apart, 7.5 px per unit) a label could sit across the neighbouring
line; the plugin now tries both sides of the line and takes the one that is inside the plot and
crosses no other marker line, falling back to stacking below an earlier label. (2) Hovering the
x=5 marker gave the tooltip x=[5, 47]: the low-handicap archer's curve had no points below 47
because zero-probability scores were left out, so the "nearest" point was 47. The curve points
are now one per whole score over the whole x-range, zero where the distribution has none, so a
curve value exists under every marker. (The other 30 of 36 hover probes had already passed, and
no probe ever returned a marker dataset.) A second browser run on the fixed commit is recorded
below.

Task 51 browser check #2 (subagent, headless Edge 154 via Selenium, commit 0654de8, port 5074):
PASS on all five points, with the previous run's scenario repeated both as it came out and in a
"swapped" orientation that reproduces the earlier failure (the first-listed archer on the
extreme low score, the second on the extreme high). Labels: with the x scale 4 to 120 and
markers at x = 5 and 118, all six label boxes are inside the chart area (the P3 label at x=5 now
sits on the right of its line, 10.7 px clear of the left edge; the one at 118 on its left, 18.3 px
clear of the right edge), none overlap, and no label box contains another marker's line. A
wide-axis case with two lines a score apart (100 and 101 at about 7.5 px per unit) puts the two
labels on opposite outer sides with no line through either, readable in the screenshot. Hover:
36 of 36 synthetic probes and 36 of 36 real-pointer probes return exactly the two curve points at
the score nearest the pointer, never a marker (0 failures, against 6 before); at the x=5 marker
the tooltip lists both archers with probability 0. Regression: marker counts 0/2 (pass 2, before
scoring), 2/4 and 2/6; legend exactly the two "Name (handicap H)" entries; h1 without a
handicap; every marker inside the axis; each curve has one point per whole score across the
x-range (117 points for 4-120, 121 for 0-120); console free of JS errors. The flat zero part of
a curve is a thin line along the axis with no fill, which reads fine. Task 51 is complete.

### Task 56: Integration checks, browser walkthrough and docs for Feedback 5 (complete)
Six scenarios were added to `tests/test_integration.py` over the real routes: a 4-archer advanced
event (Recurve and Compound on 40 cm at 18 m, a 5-zone face at 50 yd, a Worcester face; maxima
120/120/108/60) in which, after every pass, the Results page's points equal the passes each
archer has won so far; the same event after the last pass, where the leaderboard page, the Archer
results page, both CSVs and the PDF all agree with the Event and with each other (6 points in
total, one per decided match); a tie (same handicap and score) that cannot be saved until a box
is ticked and then credits the ticked archer, with a later percentile-decided pass, giving 1
point each and `decided_by` of "closest" and "percentile"; a half-scored pass that changes
neither the leaderboard nor the exports; a pair that has not met showing both archers' earlier
scores in the chart payload with an extreme score (5) inside the x-range; and the calculator
flow (indoor compound Portsmouth, outdoor WA 1440 (90m)) equal to `archeryutils`. README.md was
rewritten for advanced setup, the tie-break, the leaderboard, Archer results and exports, the
calculator and the chart's labelled markers. Suite: 798 passed.

Real-browser walkthrough (subagent, headless Edge 154 via Selenium, commit ac72561 exported with
`git archive`, port 5075, through the page's own forms and buttons): PASS on every step, no
bugs, console clean (favicon 404 and CDN tracking-prevention warnings only).
- **Advanced setup:** choosing Advanced hides the simple dropdowns with Continue enabled; Stage 2
  has the three extra dropdowns per row with the right labels; Redraw changed all three passes'
  pairings; Confirm reached the overview.
- **Match pages:** every heading is just the two names; score boxes read e.g. "Cat (handicap 35)
  score (0-108)" with max attributes 108, 120 and 60 (the 5-zone and Worcester archers); each saved
  match shows a This pass table (Archer | Score | Percentile | Winner, Yes/No).
- **Tie-break:** Ann vs Ben, both Recurve handicap 30, scoring 90 and 90 with nothing ticked gives the
  "Percentile and score are tied. Tick which archer's arrow was closest to the middle, then save
  again." warning with the scores kept; the boxes are mutually exclusive; ticking Ann and saving
  gives Ann Yes / Ben No, the "decided by closest to the middle" note and Ann's box still ticked.
- **Chart:** on a pass-2 and a pass-3 page for a pair that had not met, the ticked box shows 2 and 4
  marker lines labelled P1/P2 (0 unticked), the legend reads "Cat (handicap 35)" etc., every label
  is inside the plot, and the screenshot reads well.
- **Results:** the leaderboard (Cat 3, Dan 2, Ann 1, Ben 0; 3 of 3 passes) sums to 6 and matches the
  winners tallied from the match pages; the Archer results page has four "name - total score N -
  handicap H" sections with 3 rows and an Average row each; the tie-break pass shows as 90 / 90 for
  both. The CSVs have the agreed headers (12 rows, no Average), the right content types and
  `attachment; filename=` names, and the PDF (1 page) contains Leaderboard, every name and Average.
- **Liveness:** with one of the two matches of pass 1 saved, every archer had 0 points, 0 decided
  ("0 of 3 so far") and the CSV matched; after the second, 2 points in total, 1 decided each.
- **Calculator:** Indoor selected by default with Portsmouth and the compound box (16 indoor rounds);
  Outdoor swaps to the 76-round list with WA 70m selected and hides the compound box; York 900
  gives 40.2; indoor Portsmouth 540 gives 39.4 compound and 44.5 plain, with the choices kept.
One observation, not a bug: an archer pair with unrounded percentiles that both display as 0.0%
(e.g. 1e-20 and 1e-18) still gets a winner by percentile, because ties are judged on the unrounded
values (relative 1e-9, Assumption 33); the tie-break only applies to a genuine exact tie.
Task 55's browser check (indoor/outdoor switch, calculation) is covered by step 2 of this
walkthrough, so task 55 is complete too.

## Feedback 5 summary (for anyone picking this up)
All of `Specification/feedback.md` "Feedback 5" is implemented (prd tasks 45-56, all `completed`):
- **Graphs:** each archer's chart markers are every score they have shot, against any opponent
  (the old chart used only passes the pair had shared, which is why "show previous passes" added no
  lines in later passes), each labelled "P<n>" on the chart; the x-axis always covers every marker;
  the base handicap moved from the match heading into the chart legend (and stays beside the score
  boxes, Assumption 32).
- **Match page:** a single This pass table, Archer | Score | Percentile | Winner (Yes/No).
- **Tie-break:** percentile, then score, then "closest to the middle" ticked by the scorer in two
  mutually exclusive boxes; no coin flip; an unresolved tie is not saved.
- **Advanced setup:** per-archer face type (all 16 `archeryutils` scoring systems), face size and
  distance dropdowns; each archer's maximum score follows their own face.
- **Outputs:** leaderboard (1 point per pass won), Archer results page (name, total score,
  handicap, a table with an Average row), live and counting only completed passes; CSV (leaderboard,
  archer results) and PDF exports (`fpdf2`).
- **Calculator:** Indoor/Outdoor, a dropdown of every standard AGB/WA round, compound for indoor only.
Decisions worth a second look, all in `Specification/AISpec.md` section 7: **31** "previous passes"
means every score the two archers have shot; **32** handicap removed from the match heading only;
**33** relative 1e-9 percentile tolerance and the tie-break design; **34** "face shape" read as face
size, bowstyle has no effect on the target in advanced mode; **36** outputs use completed passes only
(the existing pairwise and per-pass sections still show saved matches at once); **37-38** leaderboard
ties share a rank, the heading handicap is the entered one, the Average row's label spans Pass and
Opponent; **39** plain-UTF-8 CSV, `fpdf2` PDF; **40** the calculator offers the AGB and WA rounds only.
Defects found by the browser checks and fixed: edge labels sticking out of the plot and a hover
that showed a far-away point; by the unit tests: absolute percentile tolerance wrongly tying
lower-tail scores, and a `nan` score accepted by the calculator (pre-existing). Not touched:
everything under "Future Plans - DO NOT IMPLEMENT YET" (the handicap moving average, nicer UI,
maths explainer, user guide, publication). Final suite: 798 tests passing.


## Feedback 6 - Handicap display, tie-break boxes, grouped results, export stamps, handicap updating

Scope: every item under `Specification/feedback.md`'s "Feedback 6" heading (prd tasks 57-66),
including the "Handicap Moving Average" that Feedback 6 promoted out of "Future Plans"; what
is still under "Future Plans - DO NOT IMPLEMENT YET" (nicer UI, maths explainer, user guide,
publication) is not touched. `Specification/AISpec.md` was updated first (sections 1-6, new
5.2c, and Assumptions 41-50; Assumption 32 is superseded), then `prd.json`.

Assumptions made (full text in `Specification/AISpec.md` section 7):
- **41** - "Do not display handicap next to archer names during score input. Ignore previous
  instructions saying to" is read as withdrawing all three earlier requests (Feedback 4's
  heading and score-box labels, Feedback 5's chart legend, Assumption 32's compromise): the
  match page shows names only, including the chart legend.
- **42** - percentiles of a pair gain decimal places (up to 20) until the two texts differ;
  a genuine tie (equal within the tie-break tolerance, e.g. both 100%) stays at one place.
- **43** - the tie-break boxes appear only after a tie is refused or when a saved result was
  decided by the tick (a tie is only known once the scores are saved).
- **44-48** - the This pass table's Handicap is the pass score's equivalent handicap; the
  grouped Results tables; the export stamp is local time (in the file name, a final CSV
  `Exported` column and the PDF); to-date handicap is the equivalent handicap of the total over
  the arrows shot in completed passes (one value per archer, also shown on the pages); the
  Stage 2 button reads "Continue to Stage 3".
- **49-50** - handicap updating: `H = (start_weight * H0 + m * H_recent) / (start_weight +
  m)`, `m = min(n_lookback, passes shot)`; both parameters default to the passes per archer
  (the feedback gives the start weight's default, not `n_lookback`'s), whole numbers >= 1; an
  advanced-setup Stage 2 setting only.

### Task 57: Percentile display rule and shared pass-table rows (complete)
`h2h/outputs.py` gained `percentile_pair_text(a, b)`: both percentiles to one decimal place
unless the texts are identical, then a place is added to both until they differ (at most 20); a
pair that is tied within `stats.PERCENTILE_REL_TOLERANCE` (both exactly 100%, both 0, equal
values), or still identical at 20 places, stays at one place. By string comparison, so 0.99996 and
0.99991 become "100.00%" and "99.99%". It also gained `PassTableRow` and `pass_table_rows(event,
results)`, which turn one match's results into the rows of the shared pass table (name, score,
percentile text under the rule, handicap to one decimal place or "-", Yes/No or "-"). The
overview's Percentiles column now uses it, and `Event.match_results` now returns results in match
order (it used to be recorded order), which let the match route drop its own reordering. Three
older tests had used unrealistically low scores whose percentiles are around 1e-18; the rule shows
many decimals for those (as the user's rule says), so they now compute the expected text through
`percentile_pair_text`. Tests: 16 unit tests (differing pairs unchanged, places added, rounding,
ties staying at one place, tiny pairs, the 20-place limit and a sweep that never raises, row
building incl. zero score and bye, match order) and two overview route tests. Suite: 816 passed.

### Task 58: Match page - names only, a Handicap column, the shared pass table (complete)
The match page no longer shows a handicap beside an archer: the score-box labels read "<name> score
(0-<max>):" (the heading was already names only), the chart's curves are named by the archer's name,
and the chart payload lost its `legend` and `handicap` keys (nothing in the page or its JSON now
contains "handicap"). The This pass table gained a Handicap column (the handicap implied by the
pass score, one decimal place, "-" for 0) between Percentile and Winner, so it reads Archer | Score
| Percentile | Handicap | Winner, and it is now rendered by a new shared partial `_pass_table.html`
that takes groups of `PassTableRow` (one group per match; a `tbody.match` per group, with a CSS rule in
`base.html` that gives every group after the first a 3px double top border) so the Results page can
reuse it in task 60. Percentiles in the table follow the display rule and match the overview's text
for the same match. The old `named` handicap macro is gone. Tests: the heading/label/legend tests
became the opposite checks (names only before and after saving, with graph view on and no
`"handicap"` in the payload, the chart script naming curves by name, a bye match), the table tests
read the five columns (rows equal to the Event's results, handicap '-' for 0, Winner in the last
column), two new tests (the percentile rule on the match page agreeing with the overview, a bye
table), a payload test replacing the legend-label tests, and the tie-break tests' column index.
One of my own prd test lines was wrong (the overview also has a "Winner" column, so that heading is
not unique to the partial); the check now uses "Handicap | Winner" together. Suite: 815 passed.

### Task 59: Tie-break boxes only when percentile and score tie (complete apart from the browser check)
The "closest to the middle" fieldset, its explanation and the exclusivity script are now rendered
only when `show_tiebreak` is true: after a save was refused because of a tie (the page asks for
the tick, keeps the typed scores and shows the two boxes, with the text "The percentile and the
score are tied, so the pass is decided by whose arrow was closest to the middle ... Tick that
archer."), after a rejected request that had a box ticked (e.g. both ticked, shown as submitted),
and whenever the saved result was decided by "closest" (so it can be corrected, with the winner's
box ticked). On any other page - a fresh match, one saved by percentile or score, a bye match, an
invalid-score error - there is no checkbox, no tie-break text and no script. A forced tick with no
tie is still accepted, ignored and not stored. A tie can only be known once the scores are saved,
so the scorer cannot pre-tick; it costs one extra click in the rare tie (Assumption 43). Tests: the
"always shown" tests became "never shown" ones (fresh and saved pages, bye page, an invalid score
on a bye) plus the cases that bring the boxes back (refused tie with explanation and script, a
saved tie-break match with the winner ticked, a refused re-save into a tie over a percentile-decided
match keeping the earlier result, both ticked), and the existing note/edit tests now expect no
boxes after the tie is gone. Suite: 820 passed. The real-browser check (no boxes on a normal page,
the boxes and message on an exact tie, exclusivity, correct saved result) is combined with the
task 60 check below.

### Task 60: Results page - per-pass results as grouped match tables (complete apart from the browser check)
The per-pass results on `/event/results` now use the match pages' table (the shared `_pass_table.html`):
for every pass with results, a "Pass N" heading (it said "Rotation N") and one table Archer | Score |
Percentile | Handicap | Winner whose rows are grouped by match in the overview's order, each match a
`<tbody class="match">` and a CSS rule (`tbody.match + tbody.match td { border-top: 3px double }`)
drawing a thick double line between one match and the next; a bye match is a group of one row with
Winner "-", unscored matches are left out, and percentiles follow the display rule. The route builds
the groups with `pass_table_rows(event, event.match_results(idx, match))`. The old
`_results_table.html` (Opponent and "Won?" columns) had no other user and was deleted. The pairwise
results and leaderboard sections are unchanged. Tests: five new route tests (a Pass 1 table in
overview order, one group per match with the stylesheet rule, values equal to the Event's results
under the display rule, a bye group and unscored matches left out, "Pass N" headings with no
Opponent/Won? columns) and two migrated ones (the page now has "Pass 2" not "Rotation 2"; the
five-bye integration test now counts the single-row groups, five of them, one per archer). Suite:
825 passed. Browser check below with task 59.

### Task 61: Stage 2 submit button renamed (complete)
The Stage 2 button (simple and advanced setup) now reads "Continue to Stage 3" instead of "Start
event", since Stage 3 (pairings) now sits between it and the start of the event; the only button that
starts the event is Stage 3's "Confirm pairings and start event". Two tests (button text in both
modes, and that no setup page other than Stage 3 says "start event"). Suite: 827 passed.

### Task 62: Starting and to-date handicap in the outputs model, leaderboard and archer results pages (complete)
`h2h/outputs.py` gained `_to_date_handicaps`: each archer's total score over the completed passes,
divided over `n_pass` times the number of passes they shot (byes included, sit-outs not), turned into a
handicap with `stats.equivalent_handicap` on their own target; None if they have no completed pass or
the total is 0. `LeaderboardRow` gained `starting_handicap` and `to_date_handicap`, and
`ArcherResults` gained `to_date_handicap` and `arrows_shot` (its `handicap` field is the starting
one). The Results page's leaderboard is now Rank | Archer | Points | Passes decided | Starting handicap
| To-date handicap (the starting one as entered, 15.0 shown as 15; the to-date one to one decimal
place or "-"), and each Archer results heading reads "<name> - total score <N> - starting handicap
<H> - to-date handicap <D>". The feedback asks for the handicaps in the exports; putting them on the
two pages too keeps pages and exports matching (Assumption 47). The to-date handicap is by
construction the full-round handicap once every arrow is shot: a test checks it against a
`handicap_from_score` over a one-pass round of all 60 arrows for two archers on different targets (a
10-zone face at 20 yd and a 5-zone face at 50 yd). Tests: to-date equals the equivalent handicap of the
total after 1, 2 and 3 passes, leaderboard and archer results agree, whole-round equality, None cases
(no pass, sat out, total 0), bye pass counted, half-scored pass changes nothing, plus the migrated page
and integration tests. Suite: 833 passed. (The CSV and PDF exports get the columns in task 63.)

### Task 63: Exports - date-time stamp and starting/to-date handicap (complete)
Every export now says when it was made and carries both handicaps. `h2h/exports.py` functions take an
optional `now` (default the current local time); `SessionState` gained an injectable `clock` (default
`datetime.now`) that the routes read once per request, so the file name and the file's contents use the
same instant and tests can fix it. Leaderboard CSV: `Rank,Archer,Points,Passes decided,Starting
handicap,To-date handicap,Exported`. Archer-results CSV: `Archer,Starting handicap,To-date
handicap,Pass,Opponent,Score,Percentile (%),Handicap of score,Exported` (the old `Handicap` column, the
entered one, is now `Starting handicap`; the two handicap columns repeat the archer's values on each of
their rows; the to-date cell is empty if there is none; `Exported` is `YYYY-MM-DD HH:MM:SS` on every
row). The PDF has "Exported YYYY-MM-DD HH:MM:SS (local time)" under its title, the two handicaps in the
leaderboard table, and "<name> - total score N - starting handicap H - to-date handicap D" as each
archer's heading. File names are `leaderboard_YYYYMMDD-HHMMSS.csv`, `archer-results_...csv` and
`results_...pdf`. I chose a final `Exported` column over a comment line at the top of the CSV so it stays
a plain table that spreadsheets and `pandas.read_csv` read without options (Assumption 46). Tests: the
export test file was rewritten for the new formats (fixed clock: header and stamp on every row,
handicaps equal to the outputs model and repeated per archer, to-date equal to the whole-round value,
awkward names, partial pass, zero total, default clock, PDF text incl. the stamp and both headings with
a note that a long heading may wrap inside its cell, filenames carrying the stamp equal to the stamp in
the contents, a real-clock filename pattern, redirects, links, liveness), and the integration test. Suite:
839 passed.

### Task 64: Handicap moving average - event model (complete)
`Event` gained `update_handicaps` (default False), `n_lookback` and `start_weight` (whole numbers >= 1,
validated with a ValueError when updating is on, ignored and not kept when off). The fixed per-archer
distributions computed at construction are gone: `Event.handicap_for(archer, rotation=None)` gives the
handicap an archer has for a pass - the entered one when updating is off or they have no earlier scored
pass, otherwise `(start_weight * H0 + m * H_recent) / (start_weight + m)` with `m = min(n_lookback, passes
they scored in earlier rotations)`, `H_recent` the equivalent handicap of their last `m` scores over `m *
n_pass` arrows on their own target (150 if that total is 0, which has none; the equivalent handicap is
cached per archer, total and `m`), clamped to 0-150 - and `Event.distribution_for(archer, rotation=None)`
builds (and caches per archer and handicap) the distribution for that handicap. `record_match` scores a
pass with the distributions of that pass's rotation, so a pass keeps the handicap it was scored with, and
because the handicap depends only on rotations before the pass, correcting the current pass's scores
never changes it. The chart payload already called `distribution_for(a)` so it follows the current
pass without a change. With updating off everything is byte-identical (all 839 earlier tests passed
unchanged before the new ones were added). Sat-out passes add nothing and bye passes count, since only
scored results are counted. Tests (25): off equals the plain distribution and the settings are ignored;
the formula for passes 1 and 2, only the last `n_lookback` passes used, fewer passes than the lookback,
the defaults reading every arrow so far; a zero total taken as 150 and the 0-150 clamp; sat-out vs bye;
two archers on different targets; the current pass's handicap unchanged by re-saving and a recorded
percentile unchanged by later passes; the percentile and the curves for a later pass using the updated
handicap; and validation. Suite: 864 passed.

Browser check of tasks 59 and 60 (subagent, headless Edge via Selenium, commit 9176374, port 5076):
- **Task 59: PASS.** A normal match page (six loaded, every pass) has 0 `closest` checkboxes and no
  "closest to the middle" or "Tie-break" text. Entering 90 and 90 for Ann and Ben (same handicap and
  bowstyle) returns the same page with "Percentile and score are tied. Tick which archer's arrow was
  closest to the middle, then save again.", both scores kept and now exactly two unticked boxes with
  the explanation; ticking Ann, then Ben, then Ann leaves only the last ticked; saving with Ann ticked
  gives the This pass table (Ann Yes, Ben No) and the "decided by closest to the middle" note with the two
  boxes visible and Ann's ticked; changing the scores to 92 and 90 removes the boxes and the note.
  Labels read "<name> score (0-120):" with no handicap, h1 names only, and the This pass table has the five
  headings with distinct percentile texts. Task 59 is complete.
- **Task 60: one real bug found, fixed.** Pass tables had the right headings and 2 `tbody.match` groups of 2
  rows, "Pass N" headings, no Opponent/Won? columns and no "Rotation"; a bye match is its own group with
  Winner "-". But the computed `border-top` showed my rule `tbody.match + tbody.match td` puts the 3px double
  line on EVERY cell of a later match, so a second double line cut between the two archers of the
  second match (Pass 1 read as {Cat/Dan} | {Ben} | {Ann}). It is now `tbody.match + tbody.match tr:first-child
  td` (only the first row of each later match), with a test that the stylesheet has that selector and not the
  old one. The corrected rule is re-verified in the browser in the final walkthrough (task 66).
- The agent also noted the Stage 2 button still read "Start event" at that commit (task 61 came after it).

### Task 65: Stage 2 toggle and parameters for updating handicaps (complete apart from the browser check)
In advanced setup only, Stage 2 has an event-wide "Update handicaps during matches" Yes/No choice (No by
default) with, while Yes is selected (a small script shows them), two number inputs "n<sub>lookback</sub>
(passes)" and "Start weight (passes)", both min 1 and defaulting to `total_arrows // n_pass` (3 for 36 arrows,
5 for 60), each with a one-line explanation; simple setup shows none of it. `SessionState` gained
`update_handicaps`, `n_lookback` and `start_weight`, set by `start_stage2(archers, update_handicaps,
n_lookback, start_weight)` (which validates them as whole numbers >= 1 only when updating applies and the
setup is advanced), cleared by `start_stage1` and `reset`, and passed to the Event by `start_event`. The route
rejects anything else with "Lookback must be a whole number of at least 1." / "Start weight must be a whole
number of at least 1." (no raw identifiers in the messages), stores nothing, and refills the form with the
typed values and the Yes choice. Posting No or omitting the field leaves updating off and ignores any
parameter text; a forced request in simple setup is ignored. Nothing on the scoring pages shows the
settings or an updated handicap (a test checks the match, overview, results and archer pages, and that the
leaderboard's starting handicaps are still the entered ones). Tests (19): the toggle and defaults for 36 and
60 arrows, simple Stage 2 without it, Yes stored and the Event's `handicap_for` moving after pass 1, No/omitted,
ten invalid-value cases with refill, reset and a new Stage 1 clearing and the defaults following the event
size, the forced simple-mode request, page visibility, and an advanced event played over HTTP whose pass-2
percentile equals the one from the updated distribution and differs from the entered-handicap one. Suite:
883 passed.

### Task 66: Integration checks, browser walkthrough and docs for Feedback 6 (complete)
Three scenarios were added to `tests/test_integration.py` over the real routes: a 4-archer advanced
event with handicap updating on (n_lookback 2, start weight 3) in which every recorded percentile equals
the one from the distribution of the handicap that pass was scored with, at least one handicap has moved by
pass 3, the to-date handicap of each archer equals `archeryutils`'s whole-round handicap for their 36-arrow
total, the leaderboard page, archer results, both CSVs and the PDF agree with the model and with each
other, and every export carries the same fixed stamp in its file name and contents; names-only match pages
with the tie boxes absent until an exact tie and present after it (and gone again once the scores are
untied); and the Results page's per-pass tables grouped in the overview's order with distinct percentile
texts for each scored pair. README.md was updated for the Stage 2 button and the updating choice (with the
formula), the names-only match pages, the Handicap column and percentile precision, tie boxes only on a
tie, grouped per-pass results, the starting and to-date handicaps and the stamped exports. Suite: 886
passed.

Real-browser walkthrough (subagent, headless Edge 154 via Selenium, commit 28f2561 exported with `git
archive`, port 5077, through the page's own forms and buttons; scenario 1 ran twice): PASS on every step, no
bugs, console clean (favicon 404 and CDN tracking-prevention warnings only).
- **Stage 2:** the button reads "Continue to Stage 3"; the "Update handicaps during matches" Yes/No radios sit
  above the archers table with No selected and both number inputs hidden; Yes shows both with 3 and 3 (36
  arrows, 12 per pass), No hides them again; Yes with lookback 1 and start weight 2 went through Stage 3.
- **Match pages:** on 12 page views the h1 is the two names, labels read "<name> score (0-120):", no handicap
  text and no `closest` checkbox until the tie; the This pass table is exactly Archer | Score | Percentile |
  Handicap | Winner (e.g. Dan 95, 1.4%, 59.3, No; Cat 105, 2.7%, 48.7, Yes).
- **Percentile display:** ordinary pairs show one decimal (1.4% / 2.7%); a pair re-saved at 100 and 95 (both
  near 0) showed "0.000%" and "0.002%" in the table and the overview, i.e. more places until they differ; a
  pair far below 1e-20 stays "0.0% / 0.0%" as specified.
- **Tie:** Ann and Ben (identical handicap and target) meeting in pass 1, scoring 100 and 100, got the tie warning
  and, for the first time on that page, the two boxes; ticking Ben saved Ben Yes / Ann No with the note and
  Ben's box ticked.
- **Results page:** the leaderboard has the six columns (e.g. Ben 3 points, starting 30, to-date 41.4); the Pass 1-3
  tables have the five columns with rows in match pairs; the computed `border-top` of the first row of the
  second match is 3px double and every other row is 1px solid in all three passes (the earlier bug is fixed);
  the screenshot reads clearly as pairs.
- **Archer results and exports:** headings such as "Ben - total score 330 - starting handicap 30 - to-date
  handicap 41.4"; downloaded files `leaderboard_20261003-214842.csv`, `archer-results_...csv` and
  `results_...pdf`, whose `Exported` column values (one per file) and PDF line "Exported 2026-10-03 21:48:47
  (local time)" equal the stamp in the file name; the CSV headers are the agreed ones; the PDF has both handicap
  headings (the leaderboard's "Starting handicap" heading wraps to two lines in its narrow column, a cosmetic
  point only).
- **Graph view:** the legend lists the two names only ("Dan", "Ben"), with no "(handicap" anywhere.
- **Simple setup:** no updating control at all, the same button text, and a tie in pass 1 brings the boxes up
  (0 before, 2 after).
Task 60's corrected double rules and task 65's toggle are verified by this walkthrough, so those tasks are
complete too.

## Feedback 6 summary (for anyone picking this up)
All of `Specification/feedback.md` "Feedback 6" is implemented (prd tasks 57-66, all `completed`):
- **Scoring pages:** no handicap beside an archer's name (labels, heading and chart legend are names only,
  Assumption 41); the This pass table gains a Handicap column (the handicap the pass score implies);
  percentiles gain decimal places until the pair's two texts differ (up to 20; a genuine tie such as both
  100% stays at one place); the tie-break boxes appear only when the percentile and score tie.
- **Results:** per-pass results use the same table as the match pages, with a thick double line between
  matches (a "Pass N" heading each); leaderboard and archer results show starting and to-date handicap (the
  to-date one is the handicap implied by the total over all arrows shot so far, equal to the full-round
  handicap after the last pass).
- **Exports:** every CSV and the PDF carry the date and time (file name, a final `Exported` CSV column, a line
  in the PDF) and both handicaps; the old CSV `Handicap` column is `Starting handicap`.
- **Stage 2:** the submit button reads "Continue to Stage 3".
- **Handicap moving average:** in advanced setup an "Update handicaps during matches" choice (default No)
  with `n_lookback` and Start weight (both default to the passes per archer); before each pass an archer's
  handicap is `(start_weight x entered + m x recent) / (start_weight + m)`, `m = min(n_lookback, passes
  shot)`, and it sets the distribution that pass is judged against; it is not displayed.
Decisions worth a second look, all in `Specification/AISpec.md` section 7 (Assumptions 41-50): **41** the
chart legend lost its handicaps too (restore the `legend` label in `h2h/chart_data.py` if wanted); **42** "both
100%" is read as a genuine tie, so a pair like 99.97 and 99.98 shows two places; **43** the tie boxes can only
appear after a tie is found on saving, so the scorer cannot pre-tick them; **44** "per pass handicap" is the
pass score's handicap, not the handicap in use for the pass; **46-47** the export stamp is local time and the
CSV carries it as a final column, and the to-date handicap is also on the pages and repeated per row in the
archer-results CSV; **49** the weighting formula and the `n_lookback` default (the feedback gives none), which
make the updating self-referential: an archer who improves faces a higher bar. A defect found by the browser
check and fixed: the double-rule CSS selector put the line on every row of a later match, not only its
first. Not touched: everything under "Future Plans - DO NOT IMPLEMENT YET" (nicer UI, maths explainer, user
guide, publication). Final suite: 886 tests passing.


## Feedback 7 - Legend handicap, per-pass starting handicap, default lookback

Scope: every item under `Specification/feedback.md`'s "Feedback 7" heading (prd tasks 67-72). Its list
numbers its items 1, 2, 2, 3; they are taken as four items (Assumption 55). `Specification/AISpec.md`
was updated first (sections 1, 5.2c, 5.3, 5.4a, 5.6 and Assumptions 51-55; Assumption 41 is partly
superseded), then `prd.json`.

Assumptions made (full text in `Specification/AISpec.md` section 7):
- **51** - the chart legend shows "Name (handicap H)" again, where H is the handicap the plotted curve is built
  from (the entered one as entered when handicaps are not updated, the current pass's one to one decimal
  place when they are); the heading and score-box labels stay names only.
- **52** - the default `n_lookback` is a fixed 4 (not "passes minus one"); the start weight's default is
  unchanged.
- **53** - when handicaps are updated, every table that shows a pass's handicap also shows a "Pass starting
  handicap" column (match page, Results page, Archer results page, archer-results CSV, PDF); with updating off
  the column is absent.
- **54** - confirmation that the plotted distributions change between passes (tests and a browser check), and
  the consequence that earlier passes' markers are drawn against the current curve.

### Task 70: Default n_lookback is 4 (complete)
`models.DEFAULT_N_LOOKBACK = 4` is what Stage 2's `n_lookback` input is pre-filled with (the Start weight
default stays `total_arrows // n_pass`: 3, 5 or 10 for 36, 60 or 120 arrows in 12-arrow passes). Nothing else
changed: the Event already caps the lookback at the passes an archer has shot (so 4 in a 36-arrow event simply
uses both earlier passes) and validation is unchanged. For a 60-arrow event of five 12-arrow passes the final
pass now has `m = 4`, every earlier pass, as the feedback wants (5 gave the same). Tests: the default-value
tests were migrated (4 for 36, 60 and 120 arrows; start weight 3, 5 and 10; the defaults follow the event size
after a new Stage 1), plus submitting the untouched defaults for 60 arrows stores 4 and 5, a custom lookback
still overrides and an invalid one is still rejected, and three model tests (the final pass of a 60-arrow event
uses all four earlier passes with weight (5 H0 + 4 H) / 9, a sixth pass with lookback 4 drops the first pass,
and in a 36-arrow event the 4 is capped at the 2 passes shot). Suite: 892 passed.

### Task 67: Chart legend shows each archer's handicap again (complete apart from the browser check)
`build_pair_chart_data` restored the `legend` string in each archer's payload entry: "Name (handicap H)", with
H the handicap the plotted curve is built from. With handicap updating off that is the entered handicap in the
Feedback 5 format (22.5 stays 22.5, 15.0 shows 15); with updating on it is `Event.handicap_for(archer)` for the
current pass to one decimal place, so the legend and the plotted curve always agree (Assumption 51). The
chart script labels each curve with that text (the marker lines are still out of the legend). The match
page's heading and score-box labels stay names only (Feedback 6). Tests: payload legends for entered handicaps
22.5, 15.0 and 7.25 and for the other archer, the updating case (the entered handicap to one decimal place
before any pass, the updated one afterwards and different), the chart script using the payload's legend text, and
the match page (graph view off: no handicap anywhere after the nav bar; graph view on: names-only heading and
labels, legends in the payload, and no "Name (handicap H)" in the page outside the payload). The earlier
names-only legend tests were replaced. Suite: 895 passed. The legend is checked in a real browser with the
rest of the Feedback 7 browser checks (tasks 71 and 72).

### Task 68: Pass starting handicap column in the match page and Results page tables (complete apart from the browser check)
`outputs.PassTableRow` gained `start_handicap` (the handicap the archer's distribution for that pass was
built from, `Event.handicap_for(archer, rotation)` to one decimal place, worked out rather than stored - it
depends only on earlier, fixed passes), and the shared `_pass_table.html` partial shows it as a "Pass starting
handicap" column between Percentile and Handicap whenever `event.update_handicaps` is on; with updating off the
partial is unchanged (Archer | Score | Percentile | Handicap | Winner). The match page's This pass table and the
Results page's per-pass tables both use it, so both get the column, and the Results page's match grouping and
double rules are untouched. Tests (8): with updating on, six headings on the match page and a pass-1 start of
the entered handicaps (30.0, 40.0) with a different pass-2 start for the archer whose pass 1 was poor; the Results
tables each showing their own pass's value, grouped by match; no column and no "Pass starting handicap" text
anywhere when updating is off; the shown value never changing after later passes or a correction to the current
pass; each row's recorded percentile equal to the one from the distribution of the shown handicap; and three
`pass_table_rows` unit tests (value filled for pairs, a bye row, and the entered handicap when updating is off).
Suite: 903 passed.

### Task 69: Pass starting handicap in the Archer results page, archer-results CSV and PDF (complete apart from the browser check)
`outputs.ArcherResultRow` gained `start_handicap` (`Event.handicap_for` for that pass) and `ArcherAverages`
gained its mean. When the event updates handicaps: the Archer results page's per-archer tables get a "Pass
starting handicap" column between Percentile and Handicap (one decimal place) and their Average row averages it;
the archer-results CSV gets a `Pass starting handicap` column between `Percentile (%)` and `Handicap of score`
(ten columns, each row's value the model's one-decimal text, the stamp unchanged in the last column); and the
PDF's per-archer tables and Average rows get the same column. With updating off all three are exactly as before
(five table columns, the previous nine CSV columns, no such text in the PDF), so the CSV's schema depends on the
event setting (Assumption 53). The leaderboard and its CSV, the to-date handicap and the stamp are unchanged.
Tests (9): the rows' values equal `handicap_for` for each pass with pass 1 equal to the entered handicap and pass
2 different, and the mean; the entered handicap with updating off; the page's headings and cells (six columns
with the label-spanning Average row showing the mean, five when off); the CSV header and values with updating on
(and exactly nine columns off, and the unchanged leaderboard CSV); the PDF text (the heading once per archer
table on, absent off) and its Average row ending with the mean start handicap then the mean handicap; and an
end-to-end route test over HTTP for an advanced updating event. Suite: 912 passed.

### Task 71: Confirm the plotted distributions change between passes when handicaps are updated (confirmed by tests; browser confirmation below)
Answer to Feedback 7 item 2: **yes.** The chart is built from `Event.distribution_for(archer)` for the current
pass, which uses `Event.handicap_for` for that pass, so with "Update handicaps during matches" on, an
archer's plotted curve is different in each pass after they have shot, and with it off it is the same in every
pass. This has been so since Feedback 6; Feedback 7 adds evidence. Five HTTP-level tests on an advanced
two-archer, three-pass event (fetching the chart payload embedded in the match page before each pass is
scored): with updating on, each archer's curve differs between pass 1, 2 and 3 on the scores both cover,
equals `Event.distribution_for(archer, that pass)` point by point, and Ann's pass-2 curve (after a poor pass 1)
sits to the left of her pass-1 curve; with updating off the curves are identical on shared scores; the legend
handicap (one decimal place) equals `Event.handicap_for` for the pass and the curve equals the distribution
built from it, so the legend and the plot cannot disagree; the pair-history page (`/event/pair/0/1`) also plots
the current pass's curve and its legend moves; and the payload carries markers for passes 1 and 2 against a
single curve built from pass 2's handicap. One detail the tests exposed: whole curves differ in length between
passes even with updating off, because the x-range grows to include every score shot so far (Feedback 5), so
"the curve changed" has to be judged on the scores both curves cover. **Worth knowing:** the vertical markers of
earlier passes (the "show previous passes" box) are drawn against the CURRENT pass's curve, not the curve each
was judged against (Assumption 54); I have not changed that, since it was not asked, but it can mislead when the
handicap has moved a lot. Suite: 917 passed. The real-browser reading of the curve datasets and legends in
successive passes is part of the Feedback 7 walkthrough (task 72).

### Task 72: Integration checks, browser walkthrough and docs for Feedback 7 (complete)
Two scenarios were added to `tests/test_integration.py` over the real routes (a 4-archer, 60-arrow advanced event
of five 12-arrow passes, the Stage 2 inputs left at whatever the page pre-fills): with updating on, the pre-filled
values are 4 and 5, the final pass's handicap for each archer is `(5 H0 + 4 H_recent) / 9` over all four earlier
passes, and the Results page's five per-pass tables, the Archer results page's four tables and Average rows, the
archer-results CSV, the PDF and the chart legend all show the pass starting handicaps that equal
`Event.handicap_for` for each pass; with updating off no "Pass starting handicap" appears in any table, the CSV
(nine columns) or the PDF and the legend shows the entered handicaps. I also mutation-checked the new tests:
removing the table cell, making the legend ignore updating, and changing the default lookback back to 5 each broke
4, 4 and 5 tests respectively (files restored). README.md was updated for the legend, the Pass starting handicap
column and the default `n_lookback` of 4. Suite: 919 passed.

Real-browser walkthrough (subagent, headless Edge 154 via Selenium, commit 9775646 exported with `git archive`,
port 5078, through the page's own forms and buttons): PASS on every step, no bugs, console clean (favicon 404 and
CDN tracking-prevention warnings only).
- **Default lookback:** after choosing Yes on a 60-arrow Stage 2 the two inputs read n lookback 4 and Start weight 5.
- **Confirmation (item 2) - the plotted distributions change between passes:** in a 5-pass event with
  Ann (handicap 30) under-shooting and Dan (handicap 55) over-shooting, the chart's curves moved every pass and
  in the expected direction (legend handicap, curve mean):

  | Pass | Ann | Dan |
  |---|---|---|
  | 1 | 30.0, 115.5 | 55.0, 99.5 |
  | 2 | 35.3, 113.2 | 52.1, 102.2 |
  | 3 | 38.9, 111.4 | 49.8, 104.1 |
  | 4 | 41.3, 110.0 | 47.8, 105.7 |
  | 5 | 43.0, 109.0 | 46.0, 107.0 |

  Within a pass the legend, mean and peak were identical after a reload and after saving the scores. With updating
  off (scenario 2) the legend read "Ann (handicap 30)" in every pass and Ann's curve mean was identical (115.51473);
  Dan's differed by 0.001 only because the chart's display window is shared by the pair and shifts with the
  opponent, not because of the handicap.
- **Legend (item 1):** every match page showed exactly two items "Name (handicap H)" (one decimal while updating,
  as entered when not).
- **Pass starting handicap (item 3):** the This pass table, the Results page's five pass tables (six headings), the
  Archer results tables (with an averaged cell, e.g. Ann's Average row 96.0, 0.1%, 37.7, 58.3) and the
  archer-results CSV (`...,Percentile (%),Pass starting handicap,Handicap of score,Exported`) all show the same
  values as the legend (Ann: 30.0, 35.3, 38.9, 41.3, 43.0); pass 5 fits `(5 x 30 + 61.9 + 60.2 + 58.4 + 56.5) / 9 =
  43.0`, i.e. all four earlier passes; the PDF has the column once per archer table (the raw text wraps it as "Pass
  starting / handicap"); the leaderboard and its CSV are unchanged; with updating off nothing of it appears on any of
  18 pages or in the exports.
- **Double rules:** still only on the first row of the second match (3px double; other rows 1px solid).
- **Markers:** ticking "Show previous passes' scores too" in pass 3 gave six markers drawn on the same current curve
  (Ann's curve mean unchanged by ticking), the behaviour noted in Assumption 54.
Tasks 67 and 71's browser confirmations are covered by this walkthrough, so those tasks are complete too.

## Feedback 7 summary (for anyone picking this up)
All of `Specification/feedback.md` "Feedback 7" is implemented (prd tasks 67-72, all `completed`):
1. **Legend handicap back:** the chart legend reads "Name (handicap H)" again, where H is the handicap the plotted
   curve is built from - as entered when handicaps are not updated, the current pass's (one decimal place) when they
   are. The heading and score-box labels stay names only.
2. **Confirmed: the plotted distributions change between passes** when handicaps are updated (and not otherwise),
   with five HTTP-level tests and the browser table above; the legend shows the change.
3. **Pass starting handicap:** when handicaps are updated, every table that shows a pass's handicap (the match page,
   the Results page's per-pass tables, the Archer results tables, the archer-results CSV and the PDF) also shows a
   "Pass starting handicap" column, the handicap that pass's distribution was built from; with updating off it is
   left out (so the CSV's columns depend on the setting).
4. **Default `n_lookback` is 4** (a fixed default; the start weight's stays the passes per archer).
Decisions worth a second look, all in `Specification/AISpec.md` section 7 (Assumptions 51-55): **51** the legend
shows the handicap the curve is built from (the current pass's updated one) rather than always the entered one;
**52** the default lookback is the fixed number 4, not "passes minus one" (the same for a 60-arrow event; a longer
one looks back over only its last four passes, a shorter one over all it has); **53** the new column is named "Pass
starting handicap" (the plain "Starting handicap" already means the entered one) and sits before "Handicap"; **54**
the confirmation, and a consequence you may want to know about: the markers of earlier passes are drawn against
the current pass's curve, not the curve each was judged against (I have not changed this); **55** the feedback
list's numbering (1, 2, 2, 3) is read as four items. Not touched: everything under "Future Plans - DO NOT
IMPLEMENT YET". Final suite: 919 tests passing.

## UI redesign planning - `UI-prd.json` created and section 8 gaps closed (2026-10-04)

Scope: `Specification/UI-prd.json` was created from `Specification/UISpec.md` section 8 (tasks UI-0 to UI-22,
with `phase`, `depends_on`, `gate`, `needs_review` and `completed` fields; `gate` only on UI-1, `needs_review`
on UI-9, UI-16 and UI-20). Reviewing it found twelve gaps or ambiguities in section 8. Each one was closed with an
assumption in both `UISpec.md` (new decisions D11-D18 in section 3, plus the affected sections) and
`UI-prd.json`. No code was changed and no implementation was started. `prd.json` is unchanged.

Assumptions made (decision numbers refer to `UISpec.md` section 3):
1. **UI-0 already partly done.** The `ui-redesign` branch and the `prototype-flask` tag already exist, so UI-0
   checks them and does not recreate them. "Docs present" means `UISpec.md`, `deploymentConstrains.md`,
   `AISpec.md` and `UI-prd.json`.
2. **Gate scope.** Every task after UI-1 depends on the gate, including the Python-only tasks UI-2 to UI-5
   (UISpec section 2 now says "before any further work").
3. **UI-1 tooling.** UI-1 creates only `web/package.json` (pinned `pyodide`) and `web/scripts/pyodide-gate/`
   (`scenario.py`, `run-gate.mjs`, committed `golden.json`), and the Vite scaffold moves to UI-6. The one
   `scenario.py` runs both natively and in Pyodide and drives the existing modules directly, because `bridge.py`
   does not exist yet.
4. **Draw function location (D17).** The draw moves to a new whitelisted module, `h2h/draw.py`, which both
   `state.py` and `bridge.py` import. The core modules stay untouched, the draw survives the retirement of
   `state.py` in UI-22, and UI-2 and UI-3 edit different files. UI-3 adds `tests/test_draw.py`. As a result,
   UI-6 now also depends on UI-3, and the bundle whitelist includes `draw.py`.
5. **Items with no owning task.** Each now has an owner:
   - Rename and `events:index` upkeep go in UI-8 (storage) and UI-9 (Home and header).
   - The corrupt-value recovery goes in UI-9.
   - The backup prompt on completion goes in UI-14: the completion alert has "Download backup" and a reminder,
     to meet deploymentConstrains 3, rule 4.
   - Two related gaps were also closed:
     - **D11:** no command set `status: complete`. `record_match` now sets it when `Event.is_complete`. The
       match route guard also allows `complete`, so final-pass matches stay editable as in the Flask app.
     - **D12:** document fields have owners. The storage layer sets `revision` and `updated_at`, the UI may
       change only `name`, and the bridge changes everything else.
   - **D13:** with several in-progress events, the Resume card shows the most recently updated one.
   - **D18:** the import size limit is 10 MB.
6. **Calculator fixtures.** UI-5 now includes `calculator` cases (indoor, indoor with compound, outdoor, one
   invalid input), and UI-10 checks against them.
7. **`markerLabelBoxes`.** No existing test uses it (it appears only in `h2h/static/match_chart.js`). UI-16
   writes new Vitest tests: labels do not overlap, sit beside their marker, and stay inside the chart area.
8. **Accessibility threshold.** The UI-19 scan (`@axe-core/playwright`) requires zero serious and zero critical
   violations.
9. **Phase 6 review ordering.** UI-20 depends on UI-19, so the Phase 6 review always covers both tasks. This is
   a phase-ordering dependency, not a code dependency.
10. **Deployment (UI-21).** UI-21 depends on UI-20, so it runs after the Phase 6 review. CI uses network access
    for Pyodide (D15: Pyodide comes from jsDelivr pinned `v314.0.7`, not self-hosted). The agent first verifies
    locally: the CI commands, and the production build served from a `/Handicapped-H2Hs/` sub-path. It then
    stops and asks the owner to push and merge, which the loop prompt forbids the agent to do itself.
11. **Retiring Flask (UI-22).** "Move or delete" becomes delete (the tag and git history keep the files). The
    files are named explicitly. In `test_handicap_calculator.py` only the Flask route tests go, and the pure
    lookup tests stay. Before each test file is deleted, the logbook must map it to the tests that cover its
    behaviours. UI-2's legacy-comparison tests in `test_bridge.py` are rewritten to build the reference `Event`
    directly.
12. **Open items in UISpec section 11.**
    - **D14:** completed events are kept until the user deletes them.
    - **D16:** `pyproject.toml` is unchanged and the lazy `fpdf` import is not part of this plan. UI-7 records
      the start-up time spent on fpdf2 so the owner can decide later.

Validation: `UI-prd.json` parses as JSON, every `depends_on` id exists, and every dependency points to an
earlier task in the file, so there are no cycles. The loop's "first eligible task in file order" rule therefore
follows file order.

## UI-0 - Baseline and docs (2026-10-04)

What changed: `.gitignore` gains `web/node_modules/`, `web/dist/` and `web/public/py/`. No application code
changed.

Verification:
- `git branch --show-current` prints `ui-redesign`; `git tag --list prototype-flask` prints `prototype-flask`
  (annotated tag on commit 6bfb59c, which is `main`'s head and an ancestor of `ui-redesign`). Both already
  existed, so neither was recreated.
- **Baseline: `uv run pytest` gives 919 passed, 0 failed (7.3 s), native Python 3.14.0.**
- `git check-ignore -v` matches `web/node_modules/x`, `web/dist/x` and `web/public/py/x` to the new rules and does
  not match `web/public/other.txt`, so other files under `web/public/` stay tracked.
- `Specification/UISpec.md`, `deploymentConstrains.md`, `AISpec.md` and `UI-prd.json` all exist.

Notes for future tasks: native Python is 3.14.0 and Pyodide v314.0.7 ships 3.14.2, so UI-1 compares across a
patch-version difference as well as the numpy difference. `/Prompts` is git-ignored (commit 6bfb59c), so
`Prompts/UILoopPrompt.md` is not in the repository even though `README.md` lists `Prompts/`; this is the owner's
choice and is left alone. `uv run` warns that the shell's `VIRTUAL_ENV` points elsewhere and uses the project
`.venv`, which is the intended behaviour.

## UI-1 - Pyodide compatibility gate (2026-10-04): PASSED

What changed (all new; no `h2h/` file touched):
- `web/package.json` (only `pyodide` pinned to `314.0.7`) and `web/package-lock.json`.
- `web/scripts/pyodide-gate/scenario.py`: runs natively (`uv run web/scripts/pyodide-gate/scenario.py` writes
  `golden.json`) and inside Pyodide (the runner imports it and calls `result_json`). It drives the existing modules
  directly: `rotation.build_schedule`, `models.Event`, `record_match` (with a tie-break, a score of 0 and a
  corrected score), `advance`, `outputs.pass_table_rows`, `leaderboard`, `archer_results`, pairwise results, both
  CSVs, the PDF, `chart_data.build_pair_chart_data`, and the calculator (`calculator_rounds`,
  `calculator_round`, `handicap_for_round_score`). It also captures the tie-break, final-pass advance and
  out-of-range score messages.
- `web/scripts/pyodide-gate/run-gate.mjs`: loads Pyodide 314.0.7 under Node, loads numpy and micropip,
  `micropip.install`s `archeryutils` and `fpdf2` at the versions recorded in `golden.json`, writes the seven
  whitelisted `h2h` modules into the Pyodide file system, runs the scenario, and compares with `golden.json`.
  It exits with 1 on any mismatch or a missing `%PDF-` header.
- `web/scripts/pyodide-gate/golden.json` (native output, committed).

Verification:
- `node web/scripts/pyodide-gate/run-gate.mjs` prints **GATE PASSED** and exits with 0:
  - Environments: native Python 3.14.0 / numpy 2.5.3 / win32; Pyodide Python 3.14.2 / numpy 2.4.6 / emscripten.
    Both have archeryutils 3.0.0 and fpdf2 2.8.9.
  - Every int, bool, string and None is equal and of the same type. **All 492 floats are bit-identical (largest
    relative difference 0)**, so there is no numeric drift from Pyodide's older numpy to record.
  - Both PDFs start with `%PDF-1.3` and have the same page count and drawn content as native.
  - Timings (Node 24.19.0, desktop, wheels cached): Pyodide loaded in 1.0 s; packages ready in 3.1 s; h2h modules
    imported in 1.4 s; scenario ran in 0.2 s; 5.6 s in total.
- The comparison was mutation-checked natively by feeding `compare_json` altered copies of the golden output:
  - Flagged: a float changed by a relative 1e-8, an int changed, an int turned into a float, a string changed,
    a list shortened and a changed PDF hash.
  - Not flagged: a float changed by 1e-10 (within tolerance) and a changed `environment` (not compared).
  - The PDF summary's decompressed stream contains the title and the export time, its hash changes when an
    archer's name changes, and it is the same on repeated runs.
- Regenerating `golden.json` natively gives a byte-identical file.
- `uv run pytest`: 919 passed. pytest does not collect anything under `web/`.

Assumptions:
1. **Two scripted 4-archer events instead of one.** One uses simple setup (shared 20 yd / 60 cm with an indoor
   Compound archer, a tie-break, a score of 0, a corrected score). The other uses advanced setup (four
   per-archer faces: 10 zone, 10 zone 6 ring, 5 zone, Worcester; 6-arrow passes; handicap updating on). One
   event cannot cover the simple and advanced paths, and the second costs almost nothing.
2. **The gate installs the exact native versions** (`archeryutils==3.0.0`, `fpdf2==2.8.9`, read from
   `golden.json`), so the comparison isolates Pyodide itself. The deployed app uses the loose bounds of UISpec
   4.3. Pyodide's own Pillow 12.2.0 and fonttools 4.62.1 differ from native (12.3.0, 4.66.1), but neither is
   used for a built-in-font PDF.
3. **The PDF is compared by summary, not raw bytes**: header, page count and SHA-256 of the decompressed
   streams. The raw bytes contain fpdf2's creation date and depend on the zlib build.
4. **The comparison runs in Python** (`scenario.compare_json`, inside Pyodide) so ints and floats stay
   distinct. Only JSON strings cross the JS/Python boundary.
5. **The modules are written with `pyodide.FS.writeFile`**, not unpacked from an archive. The result is the
   same; the hashed zip bundle arrives in UI-6.

Spec discrepancies:
- UISpec 8 says the scenario "prints one JSON result". In this design the native run writes `golden.json` and
  the Pyodide run returns its JSON to the runner, which prints the comparison report. Same outcome; no spec
  change proposed.

Notes for future tasks:
- The first run needs network access. Pyodide's own wheels (numpy, micropip, Pillow, fonttools) come from
  jsDelivr and are cached in `web/node_modules/pyodide` (git-ignored); archeryutils, fpdf2 and defusedxml come
  from PyPI on every run.
- Importing the h2h modules took 1.4 s in Pyodide, most likely archeryutils round data and fpdf2. UI-7 should
  measure the fpdf2 share (D16).
- deploymentConstrains 4, rule 2 asks for a README note pinning the Pyodide version. It belongs with the README
  rewrite (UI-22) or earlier if the owner prefers.

## UI-2 - Document and replay (2026-10-04)

What changed (new files only; no core module or existing test touched):
- `h2h/bridge.py` holds the schema-version-1 event document (described in the module docstring) and:
  - `schedule_for(setup)`, which rebuilds the schedule as `SessionState.start_stage1` does.
  - `rebuild_event(doc)`, the UISpec 5.3 replay: it builds the `Event` from `setup`, `archers` and
    `assignment`, records every stored match of each pass in match order, and advances past every pass before
    `current_pass`.
  - `validate_document(raw)`, which returns the `ok`/`error` envelope (code `validation`, message
    "Invalid event document: ..."). It checks the structure, types, ranges and stage consistency, drops unknown
    keys, then replays the scores through the core. The core's own messages therefore reject a score out of
    range, a tie with no closest archer, or an earlier pass left unscored. `status` must be `complete` exactly
    when `Event.is_complete` (D11).
  - The private envelope helpers `_ok`/`_error`, which UI-4 will reuse.
- `tests/test_bridge.py` (56 tests). It plays events through the legacy `SessionState` path (Stages 1-3 with a
  seeded draw, then `Event.record_match` and `advance`) and builds the document from the same inputs and draw. It
  then checks the replay after a JSON round trip: `Event.results`, the current pass, the archers, `is_complete`,
  the leaderboard and the archer results must all be identical. Scenarios:
  - a full simple event that includes a closest-to-the-middle tie;
  - a part-scored pass;
  - a corrected score;
  - five archers with byes sat out (sit-out schedule) and with byes shot;
  - advanced per-archer targets with updating on and off (every per-pass handicap is compared too).
  The validation tests cover valid documents at every stage (fresh, Stage 2, running, complete), returned
  unchanged and without mutating the input, plus cleaning and 41 malformed variants.

Verification:
- `uv run pytest tests/test_bridge.py`: 56 passed. `uv run pytest`: **975 passed** (919 + 56).
- Mutation check on `rebuild_event`. Each of these bugs fails at least one replay test:
  - ignoring `closest` (3 failed);
  - ignoring the assignment (7);
  - never using the sit-out schedule (1);
  - ignoring handicap updating (1);
  - replaying only the first match of each pass (7).
  The first version of the tests used draw seed 11, which shuffles 4 archers into the entry order, so the
  4-archer tests could not catch a dropped assignment (only 2 failed). The seed is now 4 (no archer keeps their
  place for 4 or 5 archers), and `_legacy` asserts that the draw is not the entry order.

Assumptions:
1. **Order of results within a pass.** The document keys scores by match index, not by the order they were
   saved in: JavaScript orders integer-like object keys numerically, so saving order could not survive anyway.
   The replay records each pass's matches in index order. If matches were saved out of order, `Event.results`
   holds the same results in a different order within a pass. No output depends on that order (outputs sort by
   pass, `match_results` by match order, pairwise results are sorted), and
   `test_saving_order_within_a_pass_changes_nothing_that_is_shown` checks it. Where matches were saved in index
   order, the results are identical lists, as UI-2 requires.
2. **Replay calls `advance()` instead of setting `current_rotation_index`** (UISpec 5.3 says set it, then
   advance). The effect is identical, and `advance` also checks that every earlier pass is fully scored.
3. **`setup.stage` is 0 to 3** (0 for a new event, 3 once Stage 3 is confirmed).
   - `status` is `setup` exactly while the stage is below 3.
   - Below stage 2, `archers` is empty, `assignment` null and handicap updating off. This mirrors
     `SessionState.start_stage1` clearing later stages.
   - Handicap updating needs advanced setup, as in `SessionState.start_stage2`, which stores the effective
     value.
4. **Strict types.** Counts, scores' keys, `face_cm` and `revision` must be JSON integers (not booleans);
   handicaps any finite number (normalised to float, since JSON from JavaScript turns 35.0 into 35); stored
   scores any number, with whole-number and range checks left to the core during the replay (normalised to int
   on success).
5. **Status consistency is rejected, not repaired.** `complete` without a complete event, or `running` with
   one, is a validation error rather than a silent fix. The only writer is the app itself, so a mismatch means
   corruption.
6. **No `(id, revision)` cache in `bridge.py`.** UISpec 5.1 forbids module-level mutable state there, so the
   performance cache of UISpec 5.3 belongs in the worker (UI-7) if it is needed.

Spec discrepancies: none beyond assumptions 1 and 2.

Notes for future tasks: UI-4 adds the commands to `bridge.py` and needs `apply_stage1` to reset `archers`,
`assignment`, updating and `stage` exactly as `validate_document` expects (assumption 3). New-document defaults:
stage 0, 4 archers, 60 arrows, 12 per pass, simple, byes shot, 20yd / 60 cm, updating off.
