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