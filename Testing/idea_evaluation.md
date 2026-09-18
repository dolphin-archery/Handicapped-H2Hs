# Evaluation of H2H Fairness Ideas

## TL;DR

None of the three ideas as written are quite right, but Idea 1 is aiming at the correct
target. Idea 1 Method 1 (fit priors from scraped data) is solving a problem that has
already been solved: the AGB 2023 handicap system (as implemented in `archeryutils`)
is *itself* built on an explicit generative model of per-arrow scores — a 2D Gaussian
aiming-error model with a standard deviation that is a known function of handicap. That
model can be used directly to derive an exact per-arrow score distribution, and hence
an exact (or Monte Carlo) distribution of an `n_pass`-arrow score, for any handicap,
with no data scraping required. See **Recommendation** below.

## The model already underlying AGB handicaps

`archeryutils` (`HandicapScheme.sigma_r`, `HandicapScheme.arrow_score`, in
`handicaps/handicap_scheme.py` / `handicap_scheme_agb.py`) implements the model
described by Atkinson ([jackatkinson.net/post/archery_handicap](https://jackatkinson.net/post/archery_handicap/))
and, before him, Lane (2013), and Park (2014) (both cited in the package
docstrings):

- An archer's arrow lands at a radial distance `r` from the centre that follows a
  **Rayleigh distribution** (i.e. `x`/`y` deviations are independent, identically
  distributed Gaussians) with scale `sigma_r(handicap, distance)`.
- `sigma_r` is a deterministic, monotonic function of handicap alone (plus distance
  and arrow diameter) — `sigma_r(h) = ang_0 · (1 + step/100)^(h + datum) · dist`. One
  handicap point is defined as a fixed ~3.5% change in group size.
- The probability an arrow lands in a given scoring ring is the difference of two Gaussian
  tail terms (`exp(-((arrow_radius + ring_radius)/sigma_r)^2)`), and `archeryutils`
  already computes these terms internally to get the *expected* score (`_s_bar`); it
  just doesn't expose the full per-ring probability mass function (PMF), only its
  expectation.
- Critically, **this model does not have a bowstyle term.** `arw_d` (arrow diameter)
  varies with indoor/outdoor and can be overridden, but is not bowstyle-specific. Under
  the model the AGB handicap number is already claimed to fully capture an archer's
  scoring distribution, regardless of bowstyle — bowstyle differences show up
  elsewhere (classification score tables use different thresholds per bowstyle) but
  not as a separate variance term for a given handicap.

This matters a lot for judging Idea 1.

## Idea 1: prior distribution of per-arrow/per-pass score as f(bowstyle, handicap)

### Method 1 — scrape data, fit empirical distributions per (bowstyle, handicap) bucket

- **Data availability, revised:** you've noted you can in fact get a lot of
  arrow-by-arrow data — that removes the objection above, so this option is more
  viable than I initially assumed. However, availability doesn't fix the remaining
  statistical issues below, and the recommended approach still gets you further for
  less effort.
- **Where this data is genuinely useful is validation, not construction.** Rather than
  fitting a prior from scratch per (bowstyle × handicap) bucket, use the data to
  *test the existing AGB model's assumptions*: take archers' real arrow-by-arrow
  results, compare the empirical per-arrow score distribution at their recorded
  handicap against the analytic isotropic-Gaussian prediction from `sigma_r`, and
  check residuals by bowstyle. This is a much smaller, better-posed task than
  fitting an entire prior, answers the real open question (does bowstyle add
  anything beyond handicap?), and still leaves you with survivorship bias to
  contend with — an archer's *recorded* handicap is usually their best recent
  round, so arrow data pooled under "handicap 25" over-represents good days
  relative to that archer's true average dispersion. That bias affects a
  validation exercise less than a from-scratch fit (you're comparing shapes, not
  relying on the bias-affected mean), but it doesn't disappear.
- **It duplicates a model that already exists and is publicly specified.** As above,
  the AGB handicap scheme *is* a generative per-arrow score model. Fitting your own
  empirical distribution from scraped data is redundant work, and your fit would be
  noisier than the analytic one (small buckets, self-reported/rolling-best handicaps
  causing survivorship bias — archers' recorded handicap is their *best* recent
  round, so arrow data pooled under "handicap 25" over-represents good days).
- **The bowstyle axis is not well-motivated by the existing model** (see above) — it's
  a reasonable thing to *test for* as a refinement (e.g. longbow/barebow trajectories
  might be non-Gaussian or have different horizontal/vertical spread), but building
  the whole prior around it from scratch, before checking whether the existing
  isotropic-Gaussian assumption is already adequate, is solving a harder problem than
  necessary.
- **Verdict:** not recommended as the primary method even with data access, but
  keep it in your back pocket as a calibration/validation check on the analytic
  model (see Recommendation) rather than discarding the data entirely.

### Method 2 — classification-based scoring

- Classifications are coarse (8–9 bins) and were fitted to distributions of **full
  round totals** (e.g. 60 arrows for a Portsmouth, hundreds for outdoor rounds), not
  to short bursts of `n_pass` (likely 3–6) arrows. Extrapolating a classification
  boundary — built for a much larger sample where variance has mostly averaged out —
  down to a handful of arrows is a category error: the classification tables assume a
  level of statistical convergence that a 3–6 arrow pass simply doesn't have.
- Practically, most `n_pass` results won't move an archer's numeric classification
  index at all, so the "difference in classification" will be zero for the vast
  majority of passes, and ties will dominate. This gives essentially no resolving
  power at the pass level.
- **Verdict: statistically unsound for this use case. Reject.**

## Idea 2: bootstrap from 60-arrow personal history, z-score per pass

**Strength:** it's the only idea that avoids population-level data entirely — each
archer supplies their own history. It correctly identifies that comparing standardised
(z-score) performance, not raw score + fixed handicap allowance, is what accounts for
different variances.

**Weaknesses:**
- 60 arrows is a small sample to estimate the tail behaviour of an `n_pass`-arrow sum
  by bootstrap resampling; it captures only that day's specific variability (weather,
  fatigue trend across the round, form on the day) and won't generalise to a different
  session. Bootstrapping from a single round also assumes the 60 arrows are
  i.i.d., which end-to-end archery data usually isn't (fatigue/settling-in effects
  create serial correlation).
- Comparing raw z-scores between two archers is only valid if both archers'
  `n_pass`-sum distributions are approximately the same shape (ideally Gaussian). For
  a handful of arrows this is often not true, especially for high-skill archers
  shooting compound/recurve on an easy face: their score distribution is heavily
  left-skewed and ceiling-truncated (e.g. mostly 10s/Xs, capped at a perfect score),
  while a weaker or longbow archer's distribution is closer to symmetric. Two
  distributions with different skew are not comparable via z-score in a way that's
  fair in both tails — a z-score of "+1" doesn't mean the same probability of
  occurrence for a near-perfect compound shooter as for a mid-table recurve shooter.
- You've clarified recalibration would only happen between event days, not live
  during a match — that resolves the "needs arrow-level data during matches"
  objection. It doesn't resolve the two statistical objections above though: a
  fresh 60-arrow round each day is still a small sample for estimating
  `n_pass`-sum tail behaviour, and the shape-mismatch problem between differently
  skewed archers' distributions is unaffected by recalibration frequency.
- **Alternative (convert `n_pass` sum to a handicap, distribution over handicaps):**
  this doesn't fix anything — inverting a handful of arrows into a handicap amplifies
  noise rather than reducing it (`handicap_from_score` assumes convergence to the mean
  behaviour of a full round; on 3–6 arrows the implied handicap will swing wildly),
  and then modelling *that* adds an unnecessary intermediate transform.
- **Verdict:** the standardisation logic is right in spirit, but personal bootstrapped
  histories are a noisier and more administratively demanding way to get a
  standard deviation than simply computing it analytically from handicap (see
  Recommendation) — and the skewed/truncated-distribution problem needs an exact
  discrete distribution, not a z-score, to handle correctly.

## Idea 3: per-pass handicap + Gaussian process

- This conflates two different problems. A GP over an archer's own sequence of
  per-pass implied handicaps could be a reasonable way to model *drift* in their form
  over the course of a long event (warm-up, fatigue), but it says nothing by itself
  about how to compare two different archers' passes to decide a winner — you'd still
  need a Idea-2-style standardisation step on top.
- It inherits Idea 2's "handicap from a handful of arrows is noisy" problem, and adds
  a fitting procedure (GP hyperparameters, kernel choice) that is hard to justify
  for a live H2H scoring format.
- **Verdict:** interesting as a possible v2 feature for tracking within-event drift,
  but overkill as a primary solution, and doesn't itself resolve the fairness problem.

## Recommendation

Assumption: you're planning `n_pass = 12` arrows per pass (5 passes covering a
standard 60-arrow round, e.g. Portsmouth/WA18) — noted below where it changes the
analysis.

Build the comparison directly on the AGB handicap model's own generative assumptions,
which `archeryutils` already implements (`sigma_r`), rather than on scraped data,
personal bootstraps, or classification bins:

1. **Per-arrow score PMF from handicap (analytic, no data collection):** using the
   same terms `archeryutils` computes internally for `arrow_score`
   (`exp(-((arrow_radius + ring_radius)/sigma_r(h))**2)`), construct the full
   probability mass function over ring values for a given handicap and target face,
   not just its mean. This is a small addition on top of existing, tested code — you
   are decomposing `_s_bar` into its per-ring terms instead of summing them.
2. **Distribution of an `n_pass`-arrow score:** convolve that per-arrow PMF with
   itself `n_pass` times. At `n_pass = 12` this is still cheap and exact (a handful
   of ring values convolved 12 times is a trivial computation, nowhere near needing
   Monte Carlo). Prefer the exact convolution over a Gaussian/CLT approximation even
   at this size: 12 arrows is enough to shrink but not eliminate skew for strong
   archers on an easy face (a high-skill archer shooting mostly 10s/Xs over 12
   arrows is still meaningfully ceiling-truncated relative to a Normal), and the
   exact approach costs nothing extra to get right.
3. **Decide a match by comparing quantiles, not raw z-scores or raw scores:** for each
   archer, compute the probability (from their own handicap-implied distribution) of
   scoring at or below what they actually shot in that pass — i.e. a per-archer
   p-value/percentile of their own performance. Whoever over-performed their own
   model by the larger margin (higher percentile) wins the pass. This is exactly
   the "p-value" method your Idea 1 write-up gestured at, but grounded in the correct,
   already-validated generative model instead of an empirical fit, and it naturally
   handles different variances and different skew/ceiling behaviour per archer,
   since each archer is only ever compared to their own distribution.
4. **Only needs each archer's current handicap** (already recorded, no arrow-by-arrow
   data collection during matches) and the target/round details already known before
   the match — satisfying your administrative constraint.

### Why this is better than the ideas in the README

- No data-scraping or arrow-by-arrow personal-history collection needed (unlike Idea
  1 Method 1 and Idea 2).
- No coarse-binning/resolution problems (unlike Idea 1 Method 2).
- No small-sample handicap inversion noise, because you go handicap → score
  distribution, not score → handicap (unlike Idea 2's alternative and Idea 3).
- Internally consistent with the handicap system archers already trust and
  understand, since it's the exact same model, not a new empirical model layered on
  top of it.

### What "distribution of scores" does and doesn't mean here

Concretely: score 550 → `handicap_from_score` → `h` → `sigma_r(h)` → per-arrow PMF →
convolve → a full distribution over round scores (e.g. P(500 ≤ score ≤ 575)). This
works, and is exactly step 1–2 above applied to a full round instead of a pass.

But note what that distribution conditions on: it's the spread of scores you'd expect
from a shooter whose dispersion is *exactly* `sigma_r(h)` — i.e. it treats the single
550 as if it perfectly revealed your true skill. It does not account for the fact
that 550 is itself only one noisy draw from your own score distribution — you could
easily have shot 540 or 560 on a slightly different day with identical true skill, so
there's additional uncertainty in *what your true `h` is* that a single score doesn't
resolve. The model as implemented gives you the first layer (shot noise given a known,
fixed skill level) for free; it does not give you the second layer (uncertainty about
your skill level itself, given a limited number of observations of it). That second
layer would require an explicit Bayesian step — treat `h` as unknown with a prior
(e.g. centred on your longer-run recorded handicap), and update it using the
likelihood of the observed score under each candidate `h`. This is the same kind of
extension noted above for day-to-day drift, just applied to estimation uncertainty
from a single observation rather than to genuine day-to-day variation in ability —
worth building if you want your comparison to reflect how *reliable* an archer's
quoted handicap is (e.g. one based on many rounds vs. one based on a single recent
score), not necessary for the core H2H comparison if you're happy to treat each
archer's currently-recorded handicap as ground truth for the match.

### Known gap: same-handicap archers of different bowstyles need not have the same variance

`sigma_r(h)` is a single free parameter that determines *both* an archer's mean score
and their score spread — the model has no way to represent "same mean score,
different variance" for two archers. So if a longbow archer and a recurve archer both
score 400 on a Portsmouth, `handicap_from_score` assigns them roughly the same `h`,
and the model then predicts they have the *same* per-end/per-dozen variance — even if
that's empirically false (e.g. if longbow's unsighted aiming, arc-dependent
trajectory, or form-consistency sensitivity genuinely produces more spread at a given
mean score than recurve does). This is a real limitation, not a subtlety that
resolves itself: if the isotropic-Gaussian assumption's variance-vs-mean relationship
differs by bowstyle, the shared one-parameter family cannot capture it.

The fix does not require going back to Idea 1's full empirical-prior approach.
Instead, use the arrow-by-arrow data to fit a much smaller correction: a per-bowstyle
inflation factor `γ_B`, calibrated by comparing empirical score variance at a given
handicap against the model's predicted variance, separately per bowstyle. Then build
each archer's per-arrow PMF using `γ_B · sigma_r(h)` instead of raw `sigma_r(h)`. This
is one scalar per bowstyle (not a full distribution per bowstyle × handicap bucket),
directly testable with the data you have access to, and preserves the rest of the
recommended approach (handicap-based, no live arrow data, no per-archer bootstrapping)
while fixing exactly this failure mode.

### Caveats to flag before implementing

- **Does the handicap model give a probability of shooting at a different handicap on
  a given day? No.** `sigma_r(handicap, distance)` treats the handicap as a *fixed,
  known* quantity that sets an archer's shot-to-shot dispersion; the only randomness
  in the model is shot-to-shot aiming error at that fixed dispersion. There is no
  second layer representing day-to-day variation in an archer's *true* underlying
  ability (no `P(shoots like handicap h' today | recorded handicap h)`). So this
  recommendation implicitly treats each archer's dispersion as fixed at
  `sigma_r(h_current)` for the whole event — it does not, by itself, model "some
  days I really do shoot like a better/worse handicap." Your Idea 2-style
  between-day recalibration is an informal, empirical way of updating "current form"
  to compensate for exactly this gap; if you want it modelled explicitly (e.g. a
  prior over an archer's effective handicap for the day, updated as passes come in),
  that's a legitimate v2 extension (essentially a Bayesian filter/state-space model
  on top of the per-pass PMF from step 1), not something the base AGB model gives
  you for free.
- This also inherits any weaknesses of the AGB model itself around bowstyle: it
  assumes the isotropic-Gaussian aiming-error model is adequate regardless of
  bowstyle. If your arrow-by-arrow data (see Idea 1 Method 1, revised) shows
  recurring bowstyle-specific deviations from this model (e.g. longbow groups being
  non-circular), that's a legitimate reason to revisit a bowstyle-conditioned
  correction — but test it against the analytic model's residuals first, rather than
  assuming it and fitting a prior from scratch.
- At `n_pass = 12`, exact-tie collisions in percentile are much rarer than at 3–6
  arrows, but still possible at the extremes (e.g. two strong archers both shooting
  a perfect 120). Still worth a defined tie-break rule (e.g. compare raw score, then
  coin flip) for completeness.
