# AI Specification: Handicapped H2H Scoring Tool

This specification expands `Specification/humanSpec.md` into an implementable design,
using the statistical approach chosen in `Testing/idea_evaluation.md` (built on
`Testing/ideas.md`). It should be read alongside those two documents, which contain
the justification for the underlying maths; this document only restates the maths
needed to build the system, and focuses on scope, architecture, and behaviour.

## 1. Purpose

Provide a small localhost web tool that a scorer can use, during a single indoor
60-arrow round, to run fair archer-vs-archer (H2H) matches between archers of
different skill levels — without needing to give the weaker archer a flat handicap
allowance, and without collecting arrow-by-arrow data during the match.

## 2. Statistical model (summary — see `Testing/idea_evaluation.md` for full derivation)

- Each archer supplies their current AGB handicap `h` before the round starts. This is
  the only per-archer skill input.
- The AGB 2023 handicap scheme (as implemented in `archeryutils`) defines an angular
  aiming-error standard deviation `sigma_r(h, distance)` for that archer. This
  determines, for a given target face, the probability an arrow lands in each scoring
  ring — i.e. a full per-arrow score probability mass function (PMF), not just its
  mean (which is all `archeryutils` exposes directly today).
- Convolving that per-arrow PMF with itself `n_pass` times gives the exact probability
  distribution of an archer's total score over one `n_pass`-arrow pass.
- To decide the winner of a pass fairly (accounting for each archer's own variance,
  not just their mean), convert each archer's actual pass score into a **percentile**:
  the probability, under their own handicap-implied distribution, of scoring at or
  below what they actually shot. The archer with the higher percentile — i.e. the one
  who over-performed their own expectation by more — wins the pass.
- **Explicit exclusion (per `Specification/humanSpec.md`):** the bowstyle-variance
  correction (`γ_B` inflation factor) described in `Testing/idea_evaluation.md`'s
  "Known gap" section is **not** implemented in this version. `sigma_r` is used as-is,
  as a pure function of handicap and distance, regardless of bowstyle. Bowstyle may
  still be recorded against an archer for display purposes but must not affect any
  calculation.

## 3. Scope

- One "set of matches" = one 60-arrow indoor round (default: Portsmouth), run once,
  covering all archer pairs entered by the scorer for that session.
- Archers are paired sequentially in the order entered (archer 1 vs 2, archer 3 vs 4,
  etc.). No brackets, no multi-round elimination, no ranking across separate rounds.
- The round is split into equal passes of `n_pass` arrows each, where `n_pass` is a
  parameter the scorer can adjust before/at the start of a session (see §5.3). No
  arrow-by-arrow entry — only each archer's total score for each pass is entered by
  the scorer.
- Single session, single machine, single user (the scorer) driving score entry for
  all matches. No accounts, no authentication, no persistence beyond the running
  process (restarting the app clears all match state).

Out of scope for this version (may be revisited later, see `idea_evaluation.md`):
- Bowstyle-specific variance correction (`γ_B`).
- Day-to-day / within-event handicap drift modelling (Bayesian filtering).
- Handicap estimation uncertainty from a single observed score.
- Arrow-by-arrow live data entry.
- Multi-round events, brackets, or persistence across sessions.
- User accounts / multi-scorer concurrent access.

## 4. Architecture

- **Language/runtime:** Python (project already targets `>=3.14`, managed via `uv`).
- **Backend:** a lightweight local web server (Flask), started by running `main.py`,
  serving the UI and holding all match state in memory for the process lifetime.
- **Statistics engine:** a standalone Python module (no web dependencies) that:
  - wraps `archeryutils.handicaps.handicap_scheme("AGB")` for `sigma_r`;
  - derives the per-arrow PMF from a target's `face_spec` and `sigma_r` (reusing the
    same ring-probability terms `archeryutils` computes internally for `arrow_score`);
  - convolves the PMF `n_pass` times to get the pass-score distribution (exact
    discrete convolution via `numpy`/`scipy`, not Monte Carlo — `n_pass` values here
    are small enough that this is cheap and exact);
  - computes an archer's percentile for an observed pass score;
  - decides a pass winner (percentile comparison, with tie-break: higher raw score,
    then coin flip) and an overall match winner (majority of passes; if the pass
    count is even and passes are split evenly, the match is declared a draw — no
    further tie-break is implemented in this version).
  - This module must be independently unit-testable without the web server running.
- **Frontend:** server-rendered HTML pages (Flask templates) with plain forms/inputs
  and a small amount of JS for the slider and the basic/advanced toggle. No SPA
  framework required.
- **Charting (advanced mode only):** `matplotlib`, rendered server-side to static
  images (e.g. PNG embedded as base64) and returned as part of the page — avoids
  pulling in a JS charting library or exposing a chart-data API.

## 5. Functional requirements

### 5.1 Match setup

- The scorer enters, for a single session: a list of archers, each with a name and
  current AGB handicap (decimal or integer). Bowstyle is an optional free-text/label
  field per archer, stored but unused in calculations.
- Archers are paired in entry order into matches (odd one out, if any, is flagged and
  excluded from pairing — not scored).
- The round is fixed to a standard 60-arrow indoor round; default Portsmouth. (See
  Assumptions — a round-selection dropdown may be added but is not required for v1.)

### 5.2 Pass score entry

- For each match and each pass in turn, the UI presents one input box per archer for
  that pass's total score (not individual arrows).
- On submission of both archers' scores for a pass, the system immediately computes
  and displays: each archer's percentile for that pass, the pass winner, and the
  running match score (passes won so far).
- After all `60 / n_pass` passes are entered for a match, the system displays the
  overall match winner (or draw).

### 5.3 `n_pass` control

- A slider (or equivalent control) lets the scorer choose `n_pass` before scoring
  starts for a session. It must only allow values that divide 60 evenly:
  `{1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60}`. Default: `12` (5 passes per round).
- Changing `n_pass` after a match has started resets that match's entered pass scores
  (changing pass structure mid-match is not supported — see Assumptions).

### 5.4 Basic vs Advanced UI toggle

- A visible toggle switches between:
  - **Basic mode:** archer names/handicaps, score entry boxes, pass/match winners and
    running score only. No statistical detail shown.
  - **Advanced mode:** everything in Basic mode, plus for each scored pass: a plot of
    each archer's handicap-implied pass-score distribution with their actual score
    and percentile marked, and a short in-UI explanation of the underlying maths
    (summarising §2 above, not a full re-derivation).
- The toggle applies globally to the session and can be switched at any time without
  losing entered scores.

### 5.5 Assumption logging

- Any assumption made while implementing this spec that is not fully determined by
  this document must be recorded in `Specification/logbook.md` under "Assumptions",
  not silently decided and left undocumented.

## 6. Data model (indicative)

- `Archer`: `name`, `handicap`, `bowstyle` (optional, display-only).
- `Match`: `archer_a`, `archer_b`, `n_pass`, `passes: list[Pass]`.
- `Pass`: `pass_index`, `score_a`, `score_b`, `percentile_a`, `percentile_b`, `winner`.
- `Round`: fixed metadata for the 60-arrow round in use (name, target face, distance,
  arrow count) — sourced from `archeryutils.load_rounds`.

## 7. Assumptions made in this specification

(Also recorded in `Specification/logbook.md`.)

1. Default round is a Portsmouth (60 arrows, single distance/face) rather than a WA18
   — both are valid per `Testing/ideas.md`; Portsmouth is chosen as the more common
   AGB club round. A round-selection control is a reasonable future enhancement, not
   required for v1.
2. Handicap scheme fixed to `"AGB"` (2023 scheme) rather than `"AGBold"`/`"AA"`/`"AA2"`.
3. `n_pass` is restricted to exact divisors of 60 so every pass is the same length and
   the round divides evenly; a slider with these snap points is assumed sufficient
   (no free-text entry of arbitrary `n_pass`).
4. Archers are paired strictly in entry order; no re-pairing/bracket UI is provided.
5. Overall match tie-break: majority of passes decides the match; an even split with
   no majority is shown as a draw. No sudden-death pass or other tie-break mechanism
   is implemented in this version.
6. Pass-winner tie-break (equal percentile, which can occur at score/handicap
   extremes) is: compare raw scores, then coin flip if still equal.
7. All match state is in-memory only; there is no database and no persistence across
   process restarts.
8. Charting uses `matplotlib` static images rather than an interactive JS charting
   library, to keep the dependency footprint small for a local single-user tool.
9. Bowstyle is collected only for display/record-keeping and never enters any
   calculation, consistent with the explicit exclusion of the bowstyle-variance
   correction in `Specification/humanSpec.md`.
