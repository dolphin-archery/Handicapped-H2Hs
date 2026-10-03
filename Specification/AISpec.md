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
view". As of `Specification/feedback.md` "Feedback 5", a pass always has a winner
(percentile, then score, then the archers' own judgement of whose arrow was closest to
the middle, with no coin flip), the "advanced" setup mode is built (every archer can
shoot a different target face type, face size and distance), results include a live
leaderboard, a per-archer results page and PDF/CSV exports, the graph marks every
score each archer has shot so far, and the standalone calculator covers every
standard indoor and outdoor round.

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
  who over-performed their own expectation by more — wins the pass. If the two
  percentiles are equal, the higher raw score wins; if the scores are equal too, the
  archer whose arrow was closest to the middle of the target wins, as judged by the
  archers and entered by the scorer (§5.3). There is no random tie-break, so a pass
  between two archers never ends without a winner.
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
  is inferred from the chosen shooting distance (§5.1, Assumption 22). (In advanced
  setup mode the scorer instead chooses each archer's target face type directly,
  so the bowstyle no longer picks the scoring system, §5.2a.)

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
- Setup either chooses one shooting distance and one target face size shared by
  every archer in the event ("simple" setup, §5.1), in which case each archer's
  bowstyle only changes the scoring rings used on that shared face (§5.2a); or
  ("advanced" setup) gives each archer their own target face type, face size and
  distance, chosen in Stage 2 (§5.2).
- The rotation schedule is a full round-robin (every archer paired with every other
  archer once, so far as the number of available rotations allows — see §5.3) rather
  than an arbitrary/manual pairing. Which archer fills which position in that
  schedule is drawn at random in Stage 3 and can be redrawn before the event starts
  (§5.2b).
- No arrow-by-arrow entry — only each archer's total score for each pass is entered
  by the scorer, on that match's own page, for every archer shooting in the
  rotation.
- Results are tracked at three levels (see §5.4): each individual pass's winner, an
  aggregated pairwise win/loss/draw result for every pair of archers who shared at
  least one rotation, and an event-wide leaderboard (1 point per pass won). A
  per-archer results page and PDF/CSV exports (§5.4a) report them, live up to the
  last pass in which every match has been scored.
- Single session, single machine, single user (the scorer) driving score entry for
  the whole event. No accounts, no authentication, no persistence beyond the
  running process (restarting the app clears all event state).

Out of scope for this version (may be revisited later):
- Bowstyle-specific *variance* correction (`γ_B`) — see §2's exclusion note (distinct
  from the in-scope indoor Compound scoring-system difference).
- Day-to-day / within-event handicap drift modelling (Bayesian filtering), including
  the weighted moving average of the starting handicap and the handicaps shot so
  far listed under `Specification/feedback.md` "Future Plans - DO NOT IMPLEMENT YET".
- Handicap estimation uncertainty from a single observed score.
- Arrow-by-arrow live data entry.
- Free entry of distances in metres or yards, and of face sizes: advanced setup (§5.2)
  offers dropdowns of standard distances and face sizes only.
- The other "Future Plans" items (a nicer UI, an in-app maths explanation and user
  guide, and publication to a web page) — not implemented.
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
    then the archer the scorer says was closest to the middle; no randomness, and an
    exact tie with no closest archer given is reported to the caller rather than
    guessed, §5.3).
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
- **Target setup** (`h2h/models.py`'s `TargetSetup` and `resolve_target`): a distance
  and face size (shared by everyone in simple setup, per archer in advanced setup,
  with a face type chosen explicitly in advanced setup), the indoor/outdoor
  inference from the distance, and the resolution of that setup plus a bowstyle into
  an `archeryutils` `Target` (§5.2a). Replaces the earlier fixed `RoundMode` enum.
  The highest score an arrow can earn on a target is read from the target's own
  scoring rings, since it differs between face types.
- **Outputs and exports** (new, `h2h/outputs.py` and `h2h/exports.py`): Flask-free
  functions that turn an `Event` into the leaderboard and per-archer results (only
  from passes in which every match is scored, §5.4a) and render them as CSV text and
  a PDF document.
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
  match page and on a read-only pair-history page. Besides the curves it marks, as
  labelled vertical lines, the scores the two archers have shot.

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
  - **Advanced:** each archer shoots their own target face type, face size and
    distance, so Stage 1 asks for none of them: selecting Advanced hides the
    distance and face-size dropdowns and shows a note that they are chosen per archer
    in Stage 2 (§5.2). Everything else on Stage 1 is unchanged. (Feedback 4 left this
    mode as a "TBA" placeholder; Feedback 5 builds it.)
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
- In **advanced** setup mode (§5.1) each row also collects, as dropdowns (each
  required, with a default pre-selected):
  - *Target face type* — every scoring system `archeryutils` offers, apart from its
    "Custom" placeholder, shown with a readable name (the full list is in
    Assumption 34). Default `10 zone` (the standard 10-ring face).
  - *Face size* — the diameters (in cm) that `archeryutils`'s standard rounds use:
    20, 35, 40, 50, 60, 65, 80 and 122. Default 60 cm.
  - *Distance* — the same grouped Metric/Imperial dropdown as simple setup (§5.1).
    Default 20 yd.
  Any combination can be chosen (a combination is not checked against a real round,
  Assumption 24). Invalid values are rejected naming the row, and nothing is stored.
- A standalone score-to-handicap conversion utility is also reachable from this
  stage (§5.5) — for working out a starting handicap, not tied to any archer's
  stored data.
- Submitting this stage stores the archers (in entry order, each with their own
  target setup in advanced mode) and proceeds to Stage 3 (§5.2b), where they are
  assigned to the schedule's positions; the event itself starts only when Stage 3
  is confirmed.

#### 5.2a Per-archer target resolution (target setup x bowstyle)

Each archer's target (and therefore their per-arrow PMF, per §2) is resolved
from a target setup (a distance and a face size) and that archer's bowstyle, by
building an `archeryutils` `Target` directly. In **simple** setup the setup is the
one chosen for the event (§5.1) and the bowstyle picks the scoring system:

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

In **advanced** setup each archer has their own setup, with a face type chosen
explicitly, and that face type is used exactly as chosen: the target is built from
the archer's own distance, face size and face type, with the `indoor` flag inferred
from the archer's own distance as in §5.1, and the bowstyle does not change the
scoring system (so a Compound archer who should score the reduced 10 is given a
Compound face type such as `10 zone, compound`). Bowstyle is still collected and
shown, and (as everywhere) never changes `sigma_r` (Assumption 34).

An archer's highest possible score for one arrow is the highest ring value on their
resolved target (10 on the 10-zone faces, but 9 on the 5-zone face, 11 on the 11-zone
faces, 1 for Beiter hit/miss, and so on), so the score an archer may enter for a
pass is limited to `n_pass` times *their own* target's maximum (replacing the earlier
fixed 10, Assumption 10). Percentiles are always taken from each archer's own score
distribution, so archers on different targets are still compared fairly.

#### 5.2b Stage 3: pairing assignment

- Stage 3 decides which archer fills which position in the Stage 1 rotation
  schedule — i.e. who is paired with whom in each pass, and who has the byes. The
  assignment is a **random permutation** of the archers over the schedule's
  positions, drawn automatically when Stage 2 is submitted (not entry order).
- The page shows the resulting pairings for **every pass** of the event (each pass's
  matches by archer name, the bye archer shooting alone or the archers sitting out,
  as per §5.3), so the scorer can see the whole draw.
- A **Redraw pairings** button draws a fresh random assignment and re-shows the page,
  as often as wanted. A redraw prefers a draw whose pairings actually differ from the
  current ones, so pressing it visibly changes the page whenever a different pairing
  exists (Assumption 25). A **Confirm pairings and start event** button builds the event
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
  single box for a bye match). The heading is just the archers' names ("A vs B");
  **each archer's handicap** is shown beside their score box, and also in the
  graph's legend (§5.6) (Feedback 5 moved it out of the heading, Assumption 32).
  Score validation is whole numbers in `[0, n_pass * m]` where `m` is the highest
  score one arrow can earn on that archer's own target (§5.2a), with friendly
  errors and integer display. Below the form, once the match has scores, one
  **table of this pass only** with the columns **Archer | Score | Percentile |
  Winner**, one row per archer in the match: Percentile as in the overview (one
  decimal place) and Winner "Yes" or "No" (a bye match, having no opponent, shows
  "-"). Earlier passes and earlier opponents are not shown here; they are in the
  per-archer results (§5.4a). Below that, in graph view, the pair's distribution chart
  (§5.6), plus a link back to the overview. Scores for all matches are **not**
  entered on one page at once.
- A paired match's form also has a **tie-break** control (see "Tie-break" below): a
  pair of tick boxes, one per archer, labelled as "closest to the middle".
- On saving a match's scores, the system computes and displays, per archer: their
  percentile for that pass and (for paired archers) the pass winner. (The
  full-round-equivalent handicap implied by the score, formerly shown here, is now
  in the per-archer results, §5.4a.) Saving again while the pass is still current
  replaces that match's earlier scores (Assumption 17); a pass that has been advanced
  past is no longer editable.

#### Tie-break

- A paired pass is decided by, in order: the higher **percentile**; if the percentiles
  are equal, the higher **score**; if the percentiles and scores are both equal, the
  archer whose arrow was **closest to the middle** of the target, as inspected by the
  archers. This replaces the earlier coin flip, so a paired pass always has a winner.
- The closest-to-the-middle result is entered with two **mutually exclusive tick
  boxes**, one per archer ("closest to the middle"): ticking one clears the other, and
  the server rejects a form with both ticked. Ticking neither is allowed. Both boxes
  are always shown on a paired match's form, with a note that they are used only when
  the percentile and score are exactly tied.
- If the percentiles and scores are tied and neither box is ticked, the scores are
  **not saved**: the page is shown again with a message asking for the tick, and the
  entered scores kept in the form. If a box is ticked but the tie does not occur,
  the tick is ignored and not stored.
- A saved match decided by the tick shows a note under its table ("percentile and
  score were tied; decided by closest to the middle"), the tick is shown ticked when
  the match is reopened, and the overview names that winner as for any other pass.
- Percentiles are compared with a relative tolerance of 1e-9, so two mathematically
  equal percentiles (for example both 100%) are tied even if floating-point rounding
  separates them, while two very small ones (1e-18 and 1e-20) are not (Assumption 33).
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
  the schedule repeats per §5.3). This is shown per-pair.
- **Leaderboard:** the event-wide ranking across all archers (§5.4a), built from the
  per-pass results: 1 point for each pass won, 0 for a pass lost. A pass between two
  archers always has a winner (Tie-break, §5.3), so no points are shared. (A pair's
  *pairwise* result can still be a draw, when a repeated pairing is split one pass
  each.)

### 5.4a Event outputs: leaderboard, archer results and exports

All outputs are **live**: they are recomputed on every request, and use only the
passes up to the last one in which **every match has been scored** (a "completed
pass"; Assumption 36). The pass currently being scored is left out until its last
match is saved, and the outputs update when it is. With no completed pass yet they
show an empty state (every archer on 0 points, no result rows).

- **Leaderboard** (on the Results page, above the pairwise results): a table with
  **Rank | Archer | Points | Passes decided**, ordered by points, highest first.
  Points are passes won; "Passes decided" is the number of the archer's completed
  passes that had an opponent (bye passes have no winner and score nothing).
  Archers on equal points share a rank (1, 2, 2, 4) and are listed in event order
  (Assumption 37).
- **Archer results page** (a page of its own, linked from the nav bar and the
  Results page): for every archer, in event order, a heading of **name, total score
  and handicap** (the total of their scores over the completed passes, and the
  handicap they entered at Stage 2), then a table with the columns
  - **Pass** — the pass number, an integer;
  - **Opponent** — the opponent's name for that pass ("bye" when they shot alone);
  - **Score** — the score they shot in that pass;
  - **Percentile** — that score's percentile in their own distribution, as a
    percentage to one decimal place;
  - **Handicap** — the handicap implied by that score (the "equivalent handicap":
    the handicap whose average score over a pass on their target is the score shot;
    "-" for a score of 0, which has none), to one decimal place;
  with one row per completed pass in which they shot (a pass they sat out has no row)
  and a final **Average** row giving the mean Score, Percentile and Handicap (the
  Handicap mean ignores "-"; it is "-" if there are none). The row's label "Average"
  runs across the Pass and Opponent columns, which have no value of their own since
  an average of pass numbers or of names means nothing (Assumption 38).
- **Exports** (links on the Results page and the Archer results page), each built from
  the same data as the pages and so equally live:
  - the **leaderboard as CSV** (`Rank,Archer,Points,Passes decided`);
  - the **archer results as CSV**, one tidy table with a row per archer per completed
    pass (`Archer,Handicap,Pass,Opponent,Score,Percentile (%),Handicap of score`),
    without the Average rows, which a spreadsheet can compute;
  - one **PDF report** of everything: a title, the leaderboard and then each archer's
    heading and table including its Average row.
  CSV is UTF-8 without a byte-order mark, comma-separated, with a header row (and
  numbers written plainly, not as text, e.g. `18.6`). The PDF is A4 with plain tables
  and uses a built-in font, so characters outside Latin-1 in a name are replaced by
  `?` (Assumption 39). Files are named after what they contain
  (`leaderboard.csv`, `archer-results.csv`, `results.pdf`).

### 5.5 Static handicap conversion tool

- A small, standalone page/widget (reachable from Stage 2 and at any other time) for
  working out a starting handicap from a full-round score. The steps, top to bottom:
  1. **Indoor or outdoor** (radio buttons, default Indoor).
  2. A **round** dropdown listing every standard round of the chosen kind (the lists
     are in Assumption 40); changing step 1 swaps the list. Portsmouth is selected by
     default indoors and WA 70m outdoors.
  3. **Shot with a compound bow** (Yes/No checkbox, default No), shown **only when
     Indoor is selected** (outdoors, compound scoring is the same as everyone's).
  4. The **full-round score**, and a Calculate button showing the resulting AGB
     handicap to 1 decimal place.
- Uses `archeryutils`'s real round objects directly (not a synthetic partial round)
  via the same `handicap_from_score` rootfinder used elsewhere. For a compound bow
  indoors it uses the round's compound variant (the same face and distance, with only
  the X-ring scoring 10 — the indoor-compound distinction of §5.2a, needed because
  the same score implies a different handicap under the compound scoring system),
  where `archeryutils` has one (Portsmouth, WA 18, WA 25, Bray I and II, Stafford and
  Vegas do; Worcester and Vegas 300 do not, and use the same round for compound). The
  dropdown lists each round once, not its compound variant.
- The server checks the choice, not just the page: a round that is not in the chosen
  kind's list, or a score that is not valid for the round, shows an error and no
  handicap. Purely a convenience calculator — its result is never stored against an
  archer or otherwise wired into the event, and it is independent of the event's target
  setup (§5.1).

### 5.6 Graph view

`Specification/feedback.md` "Feedback 4" renamed the earlier "advanced mode" to
**graph view**, because a different "advanced mode" (the Stage 1 setup mode, §5.1,
built by Feedback 5) exists.

- **Graph view off (default):** archer names/handicaps, score entry boxes, pass/
  pairwise winners and running scores only. No charts or explanatory text.
- **Graph view on:** everything above, plus, on each match page (for the match's
  pair) and on the read-only pair-history page linked from the results page, a
  single interactive chart showing both archers' handicap-implied pass-score
  distributions as smoothed, shaded curves on one shared graph (not discretised
  bars, and not two separate charts), trimmed to a sensible x-range rather than the
  full achievable score range.
  - **Legend:** each curve is listed with its archer's name and handicap, e.g.
    "Alice (handicap 30)". (This is where the handicap now appears instead of in the
    page heading, §5.3.) The marker lines below are not listed in the legend.
  - **Score markers:** the scores the archers have shot are marked as vertical dashed
    lines in the archer's colour, **each labelled on the chart with its pass number**
    (e.g. "P3" beside the line). A marker is drawn for **every pass the archer has scored so
    far, whoever their opponent was** (including a bye pass shot alone) — not only for
    passes shared with the opponent on this page (a bug fixed by Feedback 5). By
    default only the scores of the pass currently being scored are shown (none until
    that match has scores); a "Show previous passes' scores too" checkbox adds the
    earlier passes' scores for both archers, so the number of lines grows as the event
    goes on (Assumption 31).
  - **Axis limits:** the x-axis always covers every score marker the chart can show,
    with a small margin, widening beyond the trimmed range of the curves when a score
    falls outside it (so no line is drawn outside the plot). The range is computed once
    from all of both archers' scores, so it does not move when the checkbox is ticked.
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
    convolution) or repeat the bowstyle note. (It does not describe the tie-break,
    which only arises when percentile and score are both exactly equal.)
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
  `Barebow` | `Longbow`, affects target resolution per §5.2a in simple setup when
  indoor), `target_setup: TargetSetup | None` (the archer's own setup in advanced
  mode; `None` in simple mode, where the event's shared setup is used).
- `TargetSetup`: `distance` and its unit (`metre` | `yard`), `face_cm`, and an optional
  `face_type` (an `archeryutils` scoring system; `None` means "chosen from the
  bowstyle", as in simple mode). Derived: the distance in metres, and `indoor`
  (distance <= 25 m, §5.1). The standard distance, face-size and face-type options
  are defined alongside it.
- `Rotation` and `Event` are as below; `Event` takes the shared `TargetSetup` (or
  `None` in advanced mode, where every archer carries their own).
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
  (equivalent), and (if paired) `winner` plus `decided_by` (`percentile` | `score` |
  `closest to the middle`, saying which step of the tie-break chain, §5.3, decided
  it).
- `LeaderboardRow` and the per-archer results (`h2h/outputs.py`): derived from the
  `PassResult`s of completed passes only (§5.4a); nothing is stored.
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
6. ~~Pass-winner tie-break (equal percentile, which can occur at score/handicap
   extremes) is: compare raw scores, then coin flip if still equal.~~ Superseded by
   Feedback 5: percentile, then score, then the archers' judgement of whose arrow was
   closest to the middle, entered by the scorer; no coin flip (§5.3, Assumption 33).
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
10. ~~`MAX_SCORE_PER_ARROW` is hard-coded to 10 rather than derived from the
    target's actual max ring value, per Specification/feedback.md "Feedback 1"
    ("hard code max score per arrow to 10 for now"). Confirmed still valid for
    every round/scoring-system combination in scope (Portsmouth, WA18, their
    compound variants, and the chosen outdoor target all top out at 10/arrow).~~
    Superseded by Feedback 5: advanced setup offers faces whose top ring is not 10
    (5-zone 9, 11-zone 11, field faces 5 or 6, Beiter hit/miss 1), so the maximum is
    read per archer from their own target (§5.2a).
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
    full round-robin every pair still meets once). A redraw prefers pairings that
    differ from the current ones (a plain reshuffle repeats the displayed pairings
    1 time in 6 with four archers, which would make the button look broken): it
    draws again, up to 50 times, until the who-meets-whom summary of every pass
    (including byes and sit-outs, ignoring the order within a pair) changes, and
    otherwise keeps the last draw. With only two archers there is one possible
    pairing and redrawing changes nothing. A random source can be injected, for
    tests.
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
30. ~~**Advanced setup selection cannot be submitted.** Choosing Advanced at Stage 1
    shows the TBA message and disables the submit button; a forced POST is rejected
    with the same message rather than falling back to Simple.~~ Superseded by
    Feedback 5: advanced setup is built (Assumption 34).
31. **Chart score markers (Feedback 5).** "Show previous passes" is read as: show every
    score each of the two archers has shot in an earlier pass, whoever the opponent was
    (the old chart used only passes the pair had shared, so a pair that has not met
    before showed nothing). "Latest" is the pass currently being scored, so by default
    a match page shows just this pass's two scores (none before they are saved), and
    the pair-history page, which has no match being scored, shows the current pass's
    scores of the two archers too. Pass labels are drawn on the chart as "P" and the
    pass number, rotated beside the line near its top, in the archer's colour. The
    pair-history page and the match page share the one chart and payload.
32. **Handicap moved out of the match heading only.** Feedback 5 says to remove the base
    handicap "from title of score input pages and instead add it to legend", which
    could mean removing it from the page entirely. It is removed from the heading, and
    shown in the legend when graph view is on, but kept beside each archer's score
    box, because with graph view off (the default) the legend does not exist and
    Feedback 4 asked for handicaps to be visible on the match page.
33. **Tie-break details.** (a) Two percentiles are tied if they differ by a relative amount
    below 1e-9: a percentile is a sum of probabilities, so (for example) the percentile of
    a score at or above an archer's maximum is 1 only to within rounding, and exact
    floating-point equality would let rounding noise decide a pass. The tolerance is
    relative because rounding error in a sum is relative to the sum, and scores far in
    the lower tail have percentiles around 1e-18, where an absolute 1e-9 would wrongly
    call every pair tied. (b) "Closest to the middle" is entered as two
    mutually exclusive tick boxes shown always on paired matches (the scorer cannot
    know in advance that a tie will occur, and the percentile is not known until the
    scores are saved), made exclusive by script on the page and by the server. (c) A
    tie that is not resolved is rejected rather than stored, so a pass is never saved
    without a winner; it needs no extra state (no "pending" pass), and the entered
    scores stay in the form. (d) A tie-break tick can be edited like any score until
    the pass is advanced (Assumption 17).
34. **Advanced setup.** (a) Face type means an `archeryutils` scoring system, because
    that is what `archeryutils` offers for the "face type" and what sets the
    ring scores. Feedback 5 says "target face type and shape"; `archeryutils` has no
    non-circular faces, so "shape" is read as the face size, which is a separate dropdown.
    The face types offered are all of: `5_zone`, `10_zone`, `10_zone_compound`,
    `10_zone_6_ring`, `10_zone_5_ring`, `10_zone_5_ring_compound`, `11_zone`,
    `11_zone_6_ring`, `11_zone_5_ring`, `WA_field`, `IFAA_field`, `IFAA_field_expert`,
    `AA_national_field`, `Beiter_hit_miss`, `Worcester` and `Worcester_2_ring` (not the
    "Custom" placeholder, which needs ring data a dropdown cannot supply), with a readable
    name for each. (b) Face sizes: the diameters used by `archeryutils`'s standard rounds,
    20, 35, 40, 50, 60, 65, 80 and 122 cm (the Worcester face's 16 inches is offered as the
    nearest, 40 cm), including ones too small for the standard 10-zone faces; any
    combination is allowed (Assumption 24). (c) Distances: the simple-setup list (Assumption
    24), which excludes the unusual distances used by field and some novelty rounds. (d)
    Bowstyle is still required, but has no effect on the target in advanced mode: the
    scorer's chosen face type is used as given (so the reduced 10 for Compound indoors is
    chosen by picking a compound face type). (e) Each archer's indoor flag comes from
    their own distance (Assumption 22). (f) The statistical engine needed no change:
    for every face type, at seven face sizes, four distances and handicaps 0, 50, 100
    and 150 the per-arrow distribution sums to 1 and its mean equals `archeryutils`'s
    own `arrow_score`, and every face scores in whole numbers. (g) The advanced
    per-archer fields default to a standard 10-zone 60 cm face at 20 yd.
35. **Chart axes with different faces.** Archers on different faces have different score
    ranges, so the chart's x-range is a single window that covers both archers'
    distributions and every score marker, and the y-axis is shared, as before.
36. **"Completed pass".** "Live up to the last completed pass with all results inputted"
    is read as: the leaderboard, the per-archer results and the exports use only passes
    in which every match has been scored. A partly scored pass is left out until its
    last match is saved, so a leaderboard is never based on only some of a pass's
    matches. This applies to the new outputs only: the existing Results page sections
    (pairwise results and per-pass results) still show matches as soon as they are
    saved. A bye (solo) match counts as scored when its score is saved. A pass in
    which an archer sat out has no row for them.
37. **Leaderboard ranking.** Ordered by points (passes won). Archers on equal points get
    the same rank (competition ranking: 1, 2, 2, 4) and stay in event order, because
    Feedback 5 specifies no further tie-break. A "Passes decided" column is added so
    that an archer with fewer decided passes (a bye or sit-out) is not mistaken for a
    weaker one; ranking by points alone is as specified.
38. **Per-archer results page.** The heading's "handicap" is the handicap entered at
    Stage 2 (the "base" handicap), as distinct from the per-pass "Handicap" column,
    which is the handicap implied by that pass's score. The "total score" is the sum of
    the archer's scores in the completed passes. The average row averages the three
    numeric measures (Score, Percentile, Handicap) and has no value for Pass and
    Opponent (its label "Average" spans those two columns): Pass is an integer but
    averaging pass numbers is meaningless.
39. **Exports.** CSV is plain UTF-8 (no byte-order mark, so that `pandas.read_csv` gets
    clean column names; Excel may need the file imported as UTF-8 to show accents). The
    PDF is generated with `fpdf2` (a small, pure-Python library, chosen over
    `reportlab` for its smaller footprint) using its built-in Helvetica font, which
    covers Latin-1 only, so other characters are replaced by `?`. "Exports of all" is
    read as every output being exportable: the leaderboard and the archer results as CSV
    (two files, since two tables do not share a tidy layout), and everything in one PDF.
    The per-archer CSV omits the Average rows.
40. **Calculator rounds.** "All standard indoor/outdoor rounds" is read as the rounds the
    AGB handicap scheme is built for: indoor = `archeryutils`'s `AGB_indoor` and
    `WA_indoor` sets (Bray I and II, Stafford, Portsmouth, Worcester, Vegas, Vegas 300,
    WA 18 m and WA 25 m, with their triple-spot variants); outdoor = `AGB_outdoor_imperial`,
    `AGB_outdoor_metric` and `WA_outdoor` (York, Hereford, Bristol, ..., Metric, Short and
    Long Metric, WA 1440, WA 70 m, ...). Left out: the Australian (AA) sets, the
    visually-impaired sets, field and IFAA rounds, the experimental WA 660 rounds and the
    miscellaneous set. The compound variants are not listed separately: the compound
    checkbox, shown only for indoor rounds, switches the chosen round to its compound
    variant where `archeryutils` defines one.
