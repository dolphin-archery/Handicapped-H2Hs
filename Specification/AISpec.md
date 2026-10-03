# AI Specification: Handicapped H2H Scoring Tool

This specification expands `Specification/humanSpec.md` into an implementable design,
using the statistical approach chosen in `Testing/idea_evaluation.md` (built on
`Testing/ideas.md`). It should be read alongside those two documents, which contain
the justification for the underlying maths; this document only restates the maths
needed to build the system, and focuses on scope, architecture, and behaviour.

## 1. Purpose

Provide a small localhost web tool that a scorer can use, during a single round,
to run fair archer-vs-archer (H2H) matches between archers of different skill
levels — without needing to give the weaker archer a flat handicap allowance,
and without collecting arrow-by-arrow data during the match. As of
`Specification/feedback.md` "Feedback 2", this covers a full event of any
number of archers, who rotate through different opponents every `n_pass`
arrows, rather than a fixed pair for the whole round. As of `Specification/
feedback.md` "Feedback 3", the event is driven one pass at a time: the scorer
enters results on a separate page per match and explicitly advances the whole
event to the next pass once every match in the current pass has been scored. As of
`Specification/feedback.md` "Feedback 4", the event is set up in three stages (the
last one lets the scorer draw, and redraw, which archers are paired when), the
shooting distance and target face size are chosen explicitly rather than via an
indoor/outdoor round mode, and the optional statistical views are called "graph
view".

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
  "Known gap" section is **not** implemented in this version. `sigma_r` itself is
  used as-is, as a pure function of handicap and distance, regardless of bowstyle —
  no statistical widening/narrowing of an archer's distribution based on bowstyle.
- **Not excluded — a different thing:** per `Specification/feedback.md` "Feedback 2",
  when shooting indoors a Compound archer's *scoring rules* differ from Recurve/
  Barebow/Longbow (only the inner X-ring scores 10, versus the whole 10-ring) — this
  is a real competition rule change to which rings score what, not a statistical
  correction to the aiming-error model, so it is in scope and implemented (see §5.2a).
  `archeryutils` already exposes this as a distinct scoring system (`10_zone_compound`
  versus `10_zone`), so an archer's bowstyle determines *which target* their PMF is
  computed against, while `sigma_r` itself remains bowstyle-blind as above. "Indoors"
  is inferred from the chosen shooting distance (§5.1, Assumption 22).

## 3. Scope

- One "event" = a fixed number of archers (`n_archers`) shooting a single round of
  `total_arrows` arrows each (default 60), split into rotations of `n_pass` arrows
  (a rotation is called a "pass" in the UI). At the start of each rotation, archers
  are paired up per a pre-computed rotation schedule (see §5.3), shoot one pass
  (`n_pass` arrows) against that opponent, then rotate to a new opponent for the
  next rotation. This replaces the earlier "one fixed pair for the whole round"
  design. With an odd `n_archers`, one archer per rotation has no opponent: the
  scorer chooses at setup whether that archer shoots anyway or sits the pass out
  (§5.1, §5.3).
- Setup chooses one shooting distance and one target face size shared by every
  archer in the event ("simple" setup, §5.1); each archer's bowstyle then only
  changes the scoring rings used on that shared face (§5.2a).
- The rotation schedule is a full round-robin (every archer paired with every other
  archer once, so far as the number of available rotations allows — see §5.3) rather
  than an arbitrary/manual pairing. Which archer fills which position in that
  schedule is drawn at random in Stage 3 and can be redrawn before the event starts
  (§5.2b).
- No arrow-by-arrow entry — only each archer's total score for each pass is entered
  by the scorer, on that match's own page, for every archer shooting in the
  rotation.
- Results are tracked at two levels (see §5.4): each individual pass's winner, and
  an aggregated pairwise win/loss/draw result for every pair of archers who shared
  at least one rotation. There is **no** event-wide leaderboard/ranking across all
  archers — that is explicitly deferred (see Out of scope).
- Single session, single machine, single user (the scorer) driving score entry for
  the whole event. No accounts, no authentication, no persistence beyond the
  running process (restarting the app clears all event state).

Out of scope for this version (may be revisited later):
- Bowstyle-specific *variance* correction (`γ_B`) — see §2's exclusion note (distinct
  from the in-scope indoor Compound scoring-system difference).
- Day-to-day / within-event handicap drift modelling (Bayesian filtering).
- Handicap estimation uncertainty from a single observed score.
- Arrow-by-arrow live data entry.
- Different scoring method/target face/distance per archer within the same event,
  and free entry of distances in metres or yards — explicitly deferred as the
  "advanced" setup mode in `Specification/feedback.md` "Future Plans" (the Stage 1
  toggle exists but shows only a TBA message, §5.1). The current target resolution
  (§5.2a) takes one shared target setup and resolves it per bowstyle, so a
  per-archer setup can be passed to the same function later without a rewrite.
- Event-wide leaderboard/ranking and results print-outs — explicitly deferred in
  `Specification/feedback.md` "Future Feedback".
- Multi-event history, brackets/elimination, or persistence across sessions.
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
    then coin flip).
  - This module must be independently unit-testable without the web server running.
- **Rotation scheduling** (new, `h2h/rotation.py`): a standalone, Flask- and
  stats-independent module that generates a round-robin rotation schedule (the
  standard "circle method") for `n_archers` archer positions over a requested
  number of rotations, handling an odd `n_archers` via a bye slot. For an odd
  `n_archers` whose bye archers do not shoot (§5.3), a second entry point builds
  the longer schedule that mode needs, in which sitting-out archers are recorded
  per rotation. Operates on plain archer *indices* (`0..n_archers-1`), not
  `Archer` objects — Stage 1 (§5.1) runs before archer identities are known.
- **Event orchestration** (`h2h/models.py`'s `Event`, replacing the old fixed-pair
  `Match`): holds the archers, the rotation schedule, each archer's *own*
  pre-computed score distribution (dependent on their handicap **and** their
  resolved target per §5.2a — no longer a single shared target for a pair),
  which rotation is currently being shot, records scores one *match* at a time,
  advances to the next rotation on request once the current one is fully scored,
  and derives both per-pass results and aggregated pairwise results (§5.4).
- **Target setup** (`h2h/models.py`'s `TargetSetup` and `resolve_target`): the
  shared distance and face size chosen at Stage 1, the indoor/outdoor inference
  from the distance, and the resolution of that setup plus a bowstyle into an
  `archeryutils` `Target` (§5.2a). Replaces the earlier fixed `RoundMode` enum.
- **Frontend:** server-rendered HTML pages (Flask templates) with plain forms/inputs
  and a small amount of JS for sliders, the setup-mode toggle and the graph view
  toggle. No SPA framework required. Setup runs over three pages (§5.1, §5.2,
  §5.2b); the event itself is driven by an overview page (current pass's matches)
  plus one page per match (§5.3).
- **Charting (graph view only):** a single interactive chart per pair
  (`Chart.js`, loaded from a pinned CDN version), fed by a small JSON payload
  built server-side (`h2h/chart_data.py`) and rendered client-side
  (`h2h/static/match_chart.js`). Both archers' distributions are drawn as one
  smoothed, filled curve each on a shared graph, with hover tooltips (per
  Specification/feedback.md "Feedback 1"); see §5.6. The chart appears on each
  match page and on a read-only pair-history page.

## 5. Functional requirements

### 5.1 Stage 1: event setup

A single form, submitted once at the start of an event, collecting only
event-wide settings (no archer identities yet):

- `n_archers`: integer, >= 2.
- If `n_archers` is odd: exactly one archer has no opponent ("has a bye") each
  rotation, so a **"Shoot byes?"** Yes/No option is shown (hidden for an even
  `n_archers`; default Yes). Its meaning (§5.3):
  - **Yes:** every archer shoots in every pass. The archer with the bye shoots a
    "bye match" with no opponent; each archer gets one bye match per full
    round-robin cycle.
  - **No:** the archer with the bye sits that pass out and only matches with an
    opponent are shot. This changes the total number of passes the event takes,
    so that every archer still shoots `total_arrows` arrows.
- `total_arrows`: integer, default 60.
- `n_pass`: integer, default 12; must evenly divide `total_arrows` (the set of
  allowed values is recomputed as the divisors of whatever `total_arrows` is
  entered, not a fixed set — this generalises Feedback 1's fixed
  divisors-of-60 slider).
- **Setup mode** toggle: `Simple` or `Advanced` (default Simple). This replaces the
  earlier Indoor/Outdoor + Portsmouth/WA 18 choice.
  - **Simple:** every archer shoots at the same distance and face size, chosen from
    two dropdowns that are shown only in Simple mode:
    - *Distance* — the standard distances, grouped Metric (18, 25, 30, 40, 50, 60,
      70, 90 m) and Imperial (20, 25, 30, 40, 50, 60, 80, 100 yd). Default 20 yd.
    - *Face size* — the standard WA/AGB face diameters 40, 60, 80, 122 cm. Default
      60 cm. (The two defaults together are the Portsmouth round.)
    - The face is the standard single-face 10-zone target, not a 3-spot face.
    - Whether that distance counts as **indoor or outdoor** is inferred, not asked:
      indoor if the distance is at most 25 m, outdoor otherwise (so 18 m, 25 m,
      20 yd and 25 yd are indoor; 30 m / 30 yd and beyond are outdoor). This picks
      the arrow diameter used in the handicap maths (the AGB scheme's indoor 9.3 mm
      or outdoor 5.5 mm arrow) and decides whether Compound archers score the
      reduced 10 (§5.2a). Rationale and the survey behind the threshold:
      Assumption 22.
  - **Advanced:** not built yet. Selecting it hides the dropdowns, shows a "TBA"
    message and prevents submitting the form (server-side as well). It is intended
    for per-archer scoring method/face/distance later (see Out of scope, §3).
- Submitting this stage computes and stores the full rotation schedule (§5.3)
  over `n_archers` archer *positions* (not yet bound to names/handicaps), then
  proceeds to Stage 2. The schedule has `total_arrows // n_pass` rotations,
  except when byes are not shot, where it has more (§5.3).

### 5.2 Stage 2: archer details

- Exactly `n_archers` rows (fixed from Stage 1, not a generic fixed-size form),
  each collecting: `name`, `bowstyle` (dropdown: Recurve / Compound / Barebow /
  Longbow — required, no longer optional free text), `handicap`.
- `handicap` must be a number in the allowed AGB handicap range **0 to 150**
  (inclusive); anything else (including non-numeric input) is rejected with a
  message naming the row and the range, and nothing is stored.
- A standalone score-to-handicap conversion utility is also reachable from this
  stage (§5.5) — for working out a starting handicap, not tied to any archer's
  stored data.
- Submitting this stage stores the archers (in entry order) and proceeds to
  Stage 3 (§5.2b), where they are assigned to the schedule's positions; the event
  itself starts only when Stage 3 is confirmed.
- Per Specification/feedback.md: this stage's data structure should stay easy to
  extend with more advanced-mode, per-archer fields later (e.g. per-archer
  target face/distance/units) without a rewrite, but those fields are **not**
  built now (see Out of scope, §3).

#### 5.2a Per-archer target resolution (target setup x bowstyle)

Each archer's target (and therefore their per-arrow PMF, per §2) is resolved
from the event's shared target setup (a distance and a face size, §5.1) and that
archer's bowstyle, by building an `archeryutils` `Target` directly:

| Bowstyle | Scoring system | Condition |
|---|---|---|
| Compound | `10_zone_compound` (only the inner X-ring scores 10) | the distance is indoor (§5.1) |
| Compound | `10_zone` | the distance is outdoor |
| Recurve / Barebow / Longbow | `10_zone` | always |

The target's diameter and distance are the chosen face size and distance, and
its `indoor` flag is the inferred indoor/outdoor classification; the existing
`per_arrow_pmf` then picks the matching arrow diameter automatically (it reads
`target.indoor`), so no separate handling is needed for that. The reduced 10 is
applied only indoors, as in Feedback 2 ("if indoor ensure compounds are using
small 10"), and matches how `archeryutils` models compound rounds (Assumption 23).

Two choices reproduce `archeryutils`'s own rounds exactly (and are tested against
them): 20 yd / 60 cm is Portsmouth (and `portsmouth_compound` for Compound), and
18 m / 40 cm is WA 18 (and `wa18_compound`). Longbow was added by Feedback 3 and is
scored exactly like Recurve/Barebow (Assumption 18).

#### 5.2b Stage 3: pairing assignment

- Stage 3 decides which archer fills which position in the Stage 1 rotation
  schedule — i.e. who is paired with whom in each pass, and who has the byes. The
  assignment is a **random permutation** of the archers over the schedule's
  positions, drawn automatically when Stage 2 is submitted (not entry order).
- The page shows the resulting pairings for **every pass** of the event (each pass's
  matches by archer name, the bye archer shooting alone or the archers sitting out,
  as per §5.3), so the scorer can see the whole draw.
- A **Redraw pairings** button draws a fresh random assignment and re-shows the page,
  as often as wanted. A **Confirm pairings and start event** button builds the event
  from the shown assignment and goes to the overview (§5.3). Neither is available
  once the event has started (the page then redirects to the overview).
- Reaching Stage 3 without having completed Stage 2 redirects back to Stage 1/2.
- Redrawing changes which archers meet in which pass (and who has byes); the
  underlying round-robin structure of the schedule is unchanged (Assumption 25).

### 5.3 Rotation schedule, bye handling & pass flow

#### Schedule

- The rotation schedule (built at the end of Stage 1) is a round-robin ("circle
  method") over `n_archers` positions: each rotation pairs up archers such that,
  across the full schedule, every archer faces every other archer at most once,
  with one archer having no opponent (the "bye") in a rotation if `n_archers` is
  odd.
- With an even `n_archers`, or an odd `n_archers` with "Shoot byes?" = **Yes**:
  every archer shoots in every rotation and the schedule has exactly
  `total_arrows // n_pass` rotations.
  - If that is fewer than a full round-robin needs, the schedule is truncated
    (not every pair necessarily meets, and not every archer necessarily gets a
    bye match).
  - If more rotations are available than a full round-robin needs, the schedule
    repeats from the start to fill the remaining rotations (Assumption 13).
  - With byes shot, the archer with the bye shoots a **bye match**: they shoot
    the pass alone, and their score and percentile are recorded for their own
    record but produce no winner (no opponent to compare against).
- With an odd `n_archers` and "Shoot byes?" = **No:** the bye archer sits that
  rotation out (no score entered, no match). Each archer must still shoot
  `total_arrows // n_pass` passes, so more rotations are scheduled than that
  (Assumption 15): the round-robin is run for as long as no archer would
  exceed their passes, then one final catch-up rotation pairs up the archers
  who are exactly one pass short, with everyone else sitting that rotation out.
  The bye archer's seat in each rotation, and everyone not in the catch-up
  rotation's matches, is recorded as "sitting out" and shown as such.

#### Pass flow: overview page and per-match pages

- The event is driven one **pass** (rotation) at a time. The **overview page**
  shows the current pass ("Pass k of N"): every match in it (each pair, plus the
  bye archer's solo match if byes are shot), the archers sitting out (if any),
  and a link into each match.
- The overview lists the matches in a table with the columns
  **Match | Score | Percentiles | Winner | Actions** (each with a heading):
  - *Match* — the opponents, "A vs B" (a bye match reads "A (bye - no opponent,
    shoots alone)").
  - *Score* — "A - B", the two integer scores in the same order as the opponents
    in the Match column (a bye match shows just the one score).
  - *Percentiles* — each archer's percentile for that pass **in their own
    distribution**, as "A% - B%" to one decimal place, in the same order (a bye
    match shows just the one percentile).
  - *Winner* — the name of the archer who won the pass (none for a bye match).
  - *Actions* — the link into the match's own page ("Enter scores" until the match
    is scored, "View / edit" after).
  - Until a match is scored its Score, Percentiles and Winner cells show "-".
- Each match has its **own page**, reached from the overview, where the scorer
  enters that match's scores: one score-entry box per archer in the match (a
  single box for a bye match). The page shows **each archer's handicap**, in the
  heading and beside their score box. Score validation is unchanged from Feedback
  1: whole numbers in `[0, n_pass * MAX_SCORE_PER_ARROW]`, friendly errors, integer
  display. The page also shows the match's results so far (§5.4: every pass this
  pair has shared, including the current one) and, in graph view, the pair's
  distribution chart (§5.6), plus a link back to the overview. Scores for all
  matches are **not** entered on one page at once.
- On saving a match's scores, the system computes and displays, per archer: their
  percentile for that pass, the full-round-equivalent handicap implied by their
  score, and (for paired archers) the pass winner. Saving again while the pass
  is still current replaces that match's earlier scores (Assumption 17); a pass
  that has been advanced past is no longer editable.
- The overview has an **Advance to next pass** button, enabled only once every
  match in the current pass has scores (also enforced server-side). Pressing it
  makes the next rotation current: the overview then shows the new pairings and
  the match pages accept the next pass's scores. On the final pass there is no
  advance button: once every match in it is scored, the event is complete and
  the overview links to the final results.

### 5.4 Results tracking

Two levels are tracked, per the resolution of Feedback 2's "match model" question:

- **Per-pass results:** every scored pass records both participants' scores,
  percentiles, equivalent handicaps, and (if paired) a winner — as in Feedback 1,
  now scoped to a rotation's pairs rather than one fixed pair.
- **Pairwise results:** for every unique pair of archers who have shared at
  least one rotation so far, an aggregated result (win/loss/draw) derived from
  however many passes that specific pair has shared (typically one, but more if
  the schedule repeats per §5.3). This is shown per-pair, not as a single
  ranked leaderboard across all archers (that is explicitly out of scope, §3).

### 5.5 Static handicap conversion tool

- A small, standalone page/widget (reachable from Stage 2 and at any other
  time): pick a round (`Portsmouth` or `WA 18`), say whether it was shot with a
  compound bow (Yes/No, default No), enter a full-round score, and see the
  resulting AGB handicap to 1 decimal place.
- Uses `archeryutils`'s real round objects directly (not a synthetic partial
  round) via the same `handicap_from_score` rootfinder used elsewhere: the plain
  `Portsmouth`/`WA18` round for a non-compound bow, or the `portsmouth_compound`/
  `wa18_compound` round (same face and distance, only the X-ring scores 10) for a
  compound bow — the same indoor-compound distinction as §5.2a, and needed
  because the same score implies a different handicap under the compound scoring
  system. Purely a convenience calculator — its result is never stored
  against an archer or otherwise wired into the event, and it is independent of the
  event's target setup (§5.1): it always offers just these two named rounds.

### 5.6 Graph view

`Specification/feedback.md` "Feedback 4" renamed the earlier "advanced mode" to
**graph view**, because a different "advanced mode" (the Stage 1 setup mode, §5.1)
is coming.

- **Graph view off (default):** archer names/handicaps, score entry boxes, pass/
  pairwise winners and running scores only. No charts or explanatory text.
- **Graph view on:** everything above, plus, on each match page (for the match's
  pair, with whatever history that pair has so far — none before their first scored
  pass) and on the read-only pair-history page linked from the results page, a
  single interactive chart showing both archers' handicap-implied pass-score
  distributions as smoothed, shaded curves on one shared graph (not discretised
  bars, and not two separate charts), trimmed to a sensible x-range rather than the
  full achievable score range. Each scored pass's actual scores are marked as
  vertical lines; by default only the most recent pass's markers are shown, with a
  checkbox to reveal every previous pass's markers too.
  - **Hovering** the chart shows both archers' probability values at the score under
    the pointer, wherever the pointer is — including over or next to a vertical
    score marker, shown for the latest pass or any previous pass. (A bug where
    hovering over a previous pass's marker line broke those values is fixed by
    Feedback 4.)
  - A bye match (one archer, no opponent) has no chart.
  - A short **"How the winner is decided"** explanation is shown with the chart. It
    is deliberately plain and brief: it says that a handicap sets how well an
    archer is expected to shoot, that a percentile says how good a score is for that
    handicap (the chance of scoring that much or less), and that whoever has the
    higher percentile wins the pass; and that the curves show the scores each archer
    is expected to shoot while the vertical lines are the scores actually shot. It
    does not use the statistical terms of §2 (aiming-error standard deviation,
    convolution) or repeat the bowstyle note.
- The graph view setting applies globally to the session. Its toggle **button is
  shown only on score-input (match) pages**, not on summary pages (overview, results,
  setup, calculator); the chart-related links on the results page (the "View chart"
  links) follow the same setting (Assumption 26).
- Any underscore-separated identifier shown in user-facing text (e.g. `n_pass`,
  `sigma_r`) is typeset with a proper subscript (`n<sub>pass</sub>`,
  `σ<sub>r</sub>`) rather than displaying the literal underscore. This applies
  to labels and explanatory text; it does not apply to internal error messages,
  which are instead worded to avoid the raw identifier entirely.

### 5.7 Assumption logging

- Any assumption made while implementing this spec that is not fully determined by
  this document must be recorded in `Specification/logbook.md` under "Assumptions",
  not silently decided and left undocumented.

### 5.8 Resetting the event

- The **Reset** link clears all setup and every score, so it requires confirmation:
  it opens a confirmation page that explains what will be lost and offers a
  **Reset everything** button and a cancel link back. Only that button (a form POST)
  performs the reset; opening the page, or following the link, changes nothing.

## 6. Data model (indicative)

- `Archer`: `name`, `handicap` (0-150), `bowstyle` (`Recurve` | `Compound` |
  `Barebow` | `Longbow`, affects target resolution per §5.2a when indoor).
- `TargetSetup`: `distance` and its unit (`metre` | `yard`), and `face_cm`. Derived:
  the distance in metres, and `indoor` (distance <= 25 m, §5.1). The standard
  distance and face-size options offered at Stage 1 are defined alongside it. Kept
  separate from `Archer` so a per-archer setup can be added later (§3).
- `Rotation` and `Event` are as below; `Event` takes a `TargetSetup` where it
  previously took a round mode.
- `Rotation`: `pairs: list[tuple[int, int]]` (archer-index pairs facing off this
  rotation), `bye: int | None` (archer index shooting alone with no opponent this
  rotation — only when byes are shot), `sitting_out: tuple[int, ...]` (archer
  indices not shooting this rotation — only when byes are not shot). Its
  `matches` are the pairs followed by the bye archer's solo match, if any.
- `Event` (replaces the old fixed-pair `Match`): `archers: list[Archer]` (in
  schedule-position order, i.e. after the Stage 3 assignment),
  `total_arrows`, `n_pass`, `target_setup: TargetSetup`, `schedule: list[Rotation]`,
  `current_rotation_index` (the pass being shot), and `results: list[PassResult]`
  recorded so far. Precomputes each archer's own score distribution once
  (handicap + resolved target), independent of opponent. Scores are recorded one
  match at a time, and the event moves to the next rotation only on an explicit
  advance once the current rotation's matches are all scored.
- `PassResult`: per archer per rotation: `score`, `percentile`, `handicap`
  (equivalent), and (if paired) `winner`.
- `PairwiseResult`: for a given pair of archer indices, the aggregated win/loss/
  draw derived from every pass that pair has shared.

## 7. Assumptions made in this specification

(Also recorded in `Specification/logbook.md`.)

1. ~~Default round is a Portsmouth (60 arrows, single distance/face) rather than a
   WA18~~ Superseded by Feedback 2: round is now chosen per event (indoor:
   Portsmouth or WA18; outdoor: Assumption 12's fixed target), defaulting to
   indoor Portsmouth if the scorer doesn't change it. Superseded again by
   Feedback 4: the round mode is replaced by a distance and a face-size choice
   (§5.1), defaulting to 20 yd / 60 cm, which is the Portsmouth round.
2. Handicap scheme fixed to `"AGB"` (2023 scheme) rather than `"AGBold"`/`"AA"`/`"AA2"`.
3. ~~`n_pass` is restricted to exact divisors of 60~~ Superseded by Feedback 2:
   `total_arrows` is now itself a Stage 1 input (default 60), and `n_pass` is
   restricted to the divisors of whatever `total_arrows` is chosen, not a fixed
   set. The mechanism (snap-point control, no free-text arbitrary `n_pass`) is
   unchanged.
4. ~~Archers are paired strictly in entry order; no re-pairing/bracket UI is
   provided.~~ Superseded by Feedback 2: archers are now paired by a round-robin
   rotation schedule (Assumption 13) computed at Stage 1, not fixed entry-order
   pairs.
5. ~~Overall match tie-break: majority of passes decides the match~~ Superseded
   by Feedback 2: there is no longer one "match" per pair spanning the whole
   event (pairs now typically share only one pass under the rotation schedule).
   Each pairwise result (§5.4) is simply that pair's aggregate win/loss/draw
   across whatever passes they shared; with typically one shared pass, "majority
   of passes" and "single pass result" coincide. If the schedule ever gives a
   pair more than one shared pass (Assumption 13) and it ties evenly, that
   pairwise result is a draw, with no further tie-break.
6. Pass-winner tie-break (equal percentile, which can occur at score/handicap
   extremes) is: compare raw scores, then coin flip if still equal. Unchanged.
7. All event state is in-memory only; there is no database and no persistence across
   process restarts.
8. ~~Charting uses `matplotlib` static images rather than an interactive JS charting
   library, to keep the dependency footprint small for a local single-user tool.~~
   Superseded by Specification/feedback.md "Feedback 1": charting now uses
   Chart.js (interactive, hover tooltips) per section 4/5.6 above.
9. ~~Bowstyle is collected only for display/record-keeping and never enters any
   calculation~~ Superseded by Feedback 2: bowstyle now determines which target
   an archer's PMF is computed against when indoor (§5.2a) — a real scoring-rule
   difference, not the excluded statistical variance correction (see §2's
   clarified exclusion note). Bowstyle still never affects `sigma_r` itself.
10. `MAX_SCORE_PER_ARROW` is hard-coded to 10 rather than derived from the
    target's actual max ring value, per Specification/feedback.md "Feedback 1"
    ("hard code max score per arrow to 10 for now"). Confirmed still valid for
    every round/scoring-system combination in scope (Portsmouth, WA18, their
    compound variants, and the chosen outdoor target all top out at 10/arrow).
11. The setup form's earlier fixed-20-rows / dynamic-add-more assumption is
    superseded: Stage 2 now shows exactly `n_archers` rows, since `n_archers` is
    fixed by Stage 1 before Stage 2 is shown.
12. ~~**Outdoor target** is a single fixed reference round for every bowstyle:
    `WA720`'s 70m distance / 122cm 10-zone face.~~ Superseded by Feedback 4: there
    is no longer a fixed outdoor target. The scorer chooses the distance and face
    size (§5.1), and every bowstyle shoots that same distance and face. (The
    reasoning that real WA rules give Compound and Barebow different outdoor
    distances/faces to Recurve still holds; modelling that is the deferred
    "advanced" setup mode, §3.)
13. **Rotation schedule generation:** a standard round-robin "circle method" is
    used, producing `n_archers - 1` rotations (even `n_archers`) or `n_archers`
    rotations with one bye each (odd `n_archers`) in which every archer faces
    every other archer exactly once. If `total_arrows // n_pass` is smaller than
    that, the schedule is truncated (partial coverage — some pairs never meet).
    If it's larger, the schedule repeats from the start to fill the remaining
    rotations (so later rotations can repeat earlier pairings rather than being
    left unscheduled).
14. ~~**Bye handling:** only the "shoot alone, no comparison" bye mode is
    implemented; the "sit out + additional rotation" mode and its toggle are not
    built.~~ Superseded by Feedback 3: both modes are now implemented behind a
    "Shoot byes?" Yes/No option (§5.1, §5.3). The mechanics of "No" are
    Assumption 15; "Yes" is the earlier behaviour (the bye archer shoots alone,
    recorded but with no win/loss), unchanged.
15. **Rotation count and catch-up rule when byes are not shot** (odd
    `n_archers`, "Shoot byes?" = No). `Specification/feedback.md` Feedback 3 says
    only that archers with byes sit that pass out and that "this will change the
    total number of passes it takes to shoot the full round" — it does not say by
    how much, so this rule is an assumption. Let `P = total_arrows // n_pass` be
    the passes each archer must shoot. The round-robin is run (cycling, as in
    Assumption 13) for the *largest* number of rotations `R` in which no archer
    would shoot more than `P` passes, with each rotation's bye archer sitting
    out. Byes are shared out as evenly as possible, so at that point every archer
    has shot either `P` passes or `P - 1`. If any archer has shot only `P - 1`,
    one final catch-up rotation is added in which just those archers are paired
    with each other (preferring opponents they have not yet faced) and everyone
    else sits out. Giving every archer *exactly* `P` passes is impossible when
    `n_archers` and `P` are both odd (every rotation has an even number of
    shooters, so the total number of passes shot is even, but `n_archers * P` is
    odd), so if the number of short archers is odd, one archer who already has `P`
    passes is added to the catch-up rotation as a partner and shoots `P + 1`.
    Rationale: this is the smallest schedule in which every archer shoots at
    least their full `total_arrows`, with the fewest "extra" passes. Example: 5
    archers, `P = 5` -> 7 rotations (6 round-robin rotations plus one catch-up
    rotation of two archers), 4 archers shoot 5 passes and 1 archer shoots 6.
    Revisit if a different compensation is wanted.
16. **"Shoot byes?" is shown only for an odd `n_archers`, and defaults to Yes** (the
    previously implemented behaviour). For an even `n_archers` the option is
    hidden and ignored, since there are no byes.
17. **Scores can be corrected until the pass is advanced.** Feedback 3 does not
    mention editing, but with scores now saved per match a mistyped score would
    otherwise be unrecoverable short of resetting the whole event. Saving a match
    again while its pass is current replaces its earlier results (recomputing
    percentile, equivalent handicap and winner); once the event advances, that
    pass is read-only.
18. **Longbow is scored exactly like Recurve/Barebow** (the plain scoring system
    for indoor rounds; the same fixed target outdoors), and like every bowstyle
    does not affect `sigma_r` (Assumption 9). Only Compound has a distinct indoor
    scoring variant.
19. **The handicap calculator's compound option is a Yes/No checkbox**, not the full
    bowstyle dropdown, because Feedback 3 only asks whether the round was shot
    "with a compound bow or not" — Recurve, Barebow and Longbow all score
    identically indoors.
20. **Match pages are addressed by position in the current pass.** A match's URL
    indexes the current rotation's matches (pairs first, then the bye archer's
    solo match if byes are shot), so the same URL refers to a different match
    after advancing. The overview page is the only supported entry point to them.
21. **No separate "finish" step.** The event is complete as soon as every match in
    the final pass has been scored (there is no advance button on the last pass),
    rather than requiring an extra confirmation click.
22. **Indoor/outdoor is inferred from the distance: indoor if at most 25 m, else
    outdoor.** Feedback 4 asked for this to be inferred ("I think all distances >30m
    class as outdoor though check this"). Surveying every round in `archeryutils`
    (its AGB, WA, AA and IFAA sets): no round beyond 30 m is flagged indoor, which
    confirms that expectation. The indoor-flagged rounds are at 18 m, 25 m (WA 25m,
    Australian Indoor 2), 20 yd (Portsmouth), 25 yd (Bray II) and one 30 m round, the
    80 cm Stafford. At 30 m the sets disagree (the Stafford is indoor, but every
    other 30 m round is outdoor), so a pure distance rule cannot match every round
    there. The rule chosen, **indoor iff distance <= 25 m** (25 yd is about 22.9 m),
    classifies 18 m, 25 m, 20 yd and 25 yd as indoor and 30 m, 30 yd and beyond as
    outdoor, which matches the dominant usage at every offered distance. The cost: a
    scorer shooting the Stafford is given the outdoor arrow (5.5 mm instead of
    9.3 mm), a small effect on the handicap maths, and no reduced 10 for Compound.
    Revisit when the advanced setup mode lets the scorer state indoor/outdoor.
    Arrow diameters are the AGB handicap scheme's own (indoor 9.3 mm, outdoor 5.5 mm),
    chosen by the existing `per_arrow_pmf` from `target.indoor`.
23. **Compound's reduced 10 is applied only when the distance is indoor.**
    Feedback 4 says compound archers must "still have the reduced size 10"; the
    earlier requirement (Feedback 2) was explicitly "if indoor ensure compounds are
    using small 10", and `archeryutils` uses `10_zone_compound` only for indoor
    rounds (its outdoor compound rounds use plain `10_zone`). "Still" is read as
    continuing that behaviour, so an outdoor Compound archer scores the plain
    `10_zone` face. If the reduced 10 was wanted at every distance, drop the indoor
    condition in `resolve_target`.
24. **Standard options.** Distances: 18, 25, 30, 40, 50, 60, 70, 90 m and 20, 25,
    30, 40, 50, 60, 80, 100 yd. Faces: 40, 60, 80, 122 cm. These are the
    distances/diameters that occur in `archeryutils`'s standard single-face 10-zone
    rounds. Any combination can be chosen (e.g. a 122 cm face at 18 m), without
    checking that it corresponds to a real round; every combination was checked to
    work through the statistics engine at handicaps 0 to 150. Faces are given in cm
    for both unit systems (the imperial 4 ft face is the 122 cm face). 20 m was left
    out as it is not a standard WA/AGB target distance (it occurs only in junior
    and field rounds).
25. **Stage 3 pairing assignment.** The assignment is a uniformly random permutation
    of the archers over the schedule's positions, first drawn when Stage 2 is
    submitted so that reloading Stage 3 does not change it, and redrawn on request.
    The round-robin structure is unchanged, so redrawing changes which archers meet
    in which pass and who gets the byes, not the set of pairings overall (with a
    full round-robin every pair still meets once). With only two archers there is
    one possible pairing and redrawing changes nothing. A random source can be
    injected, for tests.
26. **Graph view is one global setting, with its toggle on score-input pages only.**
    Feedback 4 says to "only display [the] button on score input pages, not summary
    pages", so the setting can only be changed from a match page. It still persists
    for the session, so the results page's "View chart" links (and the chart on the
    pair-history page's route) keep following it; they were not removed from the
    results page. If the links should always show, drop the condition in
    `results.html`.
27. **Reset confirmation.** The Reset link opens a confirmation page; only a POST from
    that page resets. It is a separate page rather than a browser pop-up, so it
    works without JavaScript. Resubmitting Stage 1 or Stage 2 still discards an
    event in progress without a confirmation (unchanged; not asked for).
28. **Handicap range.** 0 to 150 inclusive, as stated in Feedback 4; decimals are
    allowed (the field has a step of 0.1). Validation is in the Stage 2 form handler,
    next to the existing name/bowstyle/number checks.
29. **Unscored rows in the overview table** show "-" in the Score, Percentiles and
    Winner columns; the Actions text ("Enter scores" / "View / edit") is what shows
    whether a match has been scored. The earlier "Awaiting scores" status text is
    gone.
30. **Advanced setup selection cannot be submitted.** Choosing Advanced at Stage 1
    shows the TBA message and disables the submit button; a forced POST is rejected
    with the same message rather than falling back to Simple.
