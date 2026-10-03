# The Maths Behind Handicapped H2Hs

This document explains, step by step, the mathematics that turns an archer's
**handicap number** into a **probability distribution of scores**, and then into
a **fair winner** for each head-to-head (H2H) pass. It assumes GCSE-level maths
(squares, powers, percentages, probability, and a calculator's `exp` button).
Anything beyond that is explained when it first appears, and the few
calculus-flavoured justifications are marked *optional*.

Equations are written in LaTeX (`$...$`), which GitHub and VS Code's Markdown
preview both render.

## Contents

1. [The big picture](#1-the-big-picture)
2. [Handicap to group size](#2-handicap-to-group-size)
3. [Where one arrow lands: the aiming-error model](#3-where-one-arrow-lands-the-aiming-error-model)
4. [Rings, arrow thickness and scoring](#4-rings-arrow-thickness-and-scoring)
5. [Score distribution for one arrow, as a function of handicap](#5-score-distribution-for-one-arrow-as-a-function-of-handicap)
6. [Score distribution for a whole pass (many arrows)](#6-score-distribution-for-a-whole-pass-many-arrows)
7. [Deciding who wins a pass](#7-deciding-who-wins-a-pass)
8. [Going backwards: score to handicap](#8-going-backwards-score-to-handicap)
9. [Assumptions and limitations](#9-assumptions-and-limitations)
10. [Sources and where this lives in the code](#10-sources-and-where-this-lives-in-the-code)

---

## 1. The big picture

The whole system is a chain of five steps. Each step is a short formula, and
each is covered by one section below.

```
handicap h
   |  (section 2)  fixed formula
   v
group size  sigma_r         "how spread out are this archer's arrows?"
   |  (sections 3-4)  aiming-error model + target ring sizes
   v
per-arrow score probabilities   P(10), P(9), P(8), ...
   |  (section 6)  add up n arrows
   v
n-arrow pass score distribution   P(total = 108), ...
   |  (section 7)  compare each archer to *their own* distribution
   v
percentile of the score actually shot  ->  who wins the pass
```

The key idea is that **a handicap is not just an "average score". It is a
statement about how accurate the archer is, and accuracy fixes the whole
distribution of scores, not only the average.** Once the distribution is known
we can ask "how impressive was that pass, *for that archer*?", which is a much
fairer question than "who scored more?".

---

## 2. Handicap to group size

### 2.1 The formula

The Archery GB handicap scheme (2023 version, designed by Jack Atkinson,
building on David Lane's original 1970s system) says that an archer of
handicap $h$ shooting at a target a distance $d$ metres away has an
**angular deviation**

$$
\sigma_\theta(h, d) \;=\; \underbrace{5\times10^{-4}}_{\text{base angle}}
\;\times\; 1.035^{\,h+6} \;\times\; e^{\,0.00365\,d}
$$

where $\sigma_\theta$ is measured in **radians** (a radian is an angle
measure; for small angles, an angle of $\sigma_\theta$ radians moves the
arrow's landing point by $\sigma_\theta$ metres for every metre of distance).

Multiplying by the distance converts the angle into a **spread on the target**,
measured in metres:

$$
\boxed{\;\sigma_r(h, d) \;=\; d \times 5\times10^{-4} \times 1.035^{\,h+6} \times e^{\,0.00365\,d}\;}
$$

(`archeryutils` implements this as `HandicapAGB.sigma_t` and
`HandicapScheme.sigma_r`.) I will refer to $\sigma_r$ as the archer's
**group size parameter**. Section 3 pins down exactly what it means.

### 2.2 What each piece does

| Piece | Meaning |
|---|---|
| $5\times10^{-4}$ | The baseline angular error (0.5 milliradians, about 0.029 degrees). It sets the overall scale. |
| $1.035^{\,h+6}$ | **Each handicap point makes the group 3.5% bigger.** Multiplying by 1.035 once per handicap point is a *geometric* (compound-interest) scale: handicap 40 is $1.035^{10}\approx1.41$ times as spread out as handicap 30, and the group size **doubles every $\ln 2 / \ln 1.035 \approx 20.1$ handicap points**. Over the whole range 0 to 100 the group grows by a factor $1.035^{100}\approx 31$. |
| the "+6" | A fixed offset, the "datum". It decides which handicap number counts as "scratch" (handicap 0). It is a bookkeeping choice, not a physical quantity. The older scheme used an offset of 12.9, chosen so that handicap 0 corresponded to about 1400 on a WA1440 at 90 m (Atkinson, *Handicap System Maths*). |
| $d$ (the multiplication by distance) | Angular error converts to a physical spread in proportion to distance: the same wobble at the bow gives twice the miss at twice the range. |
| $e^{\,0.00365\,d}$ | **Excess dispersion**. Real archers do slightly worse than pure angular geometry predicts at long range (the older scheme attributed this partly to slower arrows from higher-handicap archers; wind and drag plausibly contribute too). This factor is 1.07 at 18 m and 1.29 at 70 m. |

### 2.3 Where do the constants come from?

Being honest about this matters, because the reader will otherwise assume the
numbers fall out of physics.

* The **structure** (a geometric scale in $h$, angle times distance, plus an
  extra distance term) is the modelling idea of Lane (2013).
* The **constants** (3.5%, 0.5 mrad, 0.00365, offset 6) are **design
  choices**, not quantities derived from first principles. The sources I
  consulted describe what each constant does (for example, the offset sets the
  scratch point) but I did not find a derivation of the specific values, and I
  have not tried to reconstruct one. They are the part of the system you are
  trusting when you use a handicap.
* The 2023 scheme replaced the earlier distance term
  $1+1.429\times10^{-6}\times1.07^{h+4.3}d^2$ (which grew with the square of
  the distance and depended on $h$) by the simpler $e^{0.00365d}$, changed the
  step from 3.6% to 3.5%, and extended the scale from 0-100 to 0-150
  (archerygeekery.co.uk, *Handicap System Maths*).

### 2.4 A worked example

An archer with handicap 30 shooting a WA 18 m indoor target:

$$
\sigma_\theta = 5\times10^{-4}\times 1.035^{36}\times e^{0.00365\times18}
= 5\times10^{-4}\times 3.450 \times 1.068 = 1.842\times10^{-3}\ \text{rad}
$$

$$
\sigma_r = 18 \times 1.842\times10^{-3} = 0.0332\ \text{m} \approx 3.3\ \text{cm}
$$

| Handicap | $\sigma_r$ at 18 m |
|---|---|
| 10 | 1.67 cm |
| 30 | 3.32 cm |
| 50 | 6.60 cm |

---

## 3. Where one arrow lands: the aiming-error model

### 3.1 The assumptions

The model treats every shot as an independent random draw:

1. The archer aims at the centre of the gold.
2. The horizontal miss $x$ and the vertical miss $y$ are **independent** and
   each follows a **normal (Gaussian, "bell curve") distribution** centred on
   zero, with the same spread $s$ in both directions.

Why a bell curve? Each shot's error is the sum of many small independent
wobbles (release, bow arm, sight alignment, wind, ...). A classic result in
statistics (the *central limit theorem*) says that sums of many small
independent effects end up looking bell-shaped. This is a modelling
assumption, not something the handicap system proves.

The normal curve with spread (standard deviation) $s$ has the density

$$
f(x) = \frac{1}{s\sqrt{2\pi}}\,e^{-x^2/(2s^2)}
$$

About 68% of shots land within $\pm s$ of the centre, about 95% within $\pm 2s$.

### 3.2 From (x, y) to the distance from the centre

Scoring only cares about the **distance from the centre**,
$r=\sqrt{x^2+y^2}$ (Pythagoras). What is the probability that an arrow lands
**further out than** some radius $R$? The answer has a very clean form:

$$
\boxed{\;P(r > R) \;=\; \exp\!\left(-\frac{R^2}{\sigma_r^{\,2}}\right)\;}
\qquad\text{where}\qquad \sigma_r^{\,2} = 2s^2 .
$$

Equivalently the distance $r$ follows a **Rayleigh distribution** with density

$$
p(r) = \frac{2r}{\sigma_r^{\,2}}\,e^{-r^2/\sigma_r^{\,2}} .
$$

Two important remarks:

* **$\sigma_r$ is not the per-axis spread.** It equals $\sqrt{2}\,s$. The
  `archeryutils` docstring calls it a "standard deviation of group size",
  which is loose wording; the parameter is the Rayleigh scale. I checked this
  numerically: simulating 5 million arrows with horizontal and vertical spread
  $s=\sigma_r/\sqrt2$ reproduces the expected score from the formula above to
  within simulation noise (9.2370 simulated, with a standard error of 0.0003,
  vs 9.2375 from the formula, at handicap 30 and 18 m).
* **Sanity check.** At $R=\sigma_r$ the formula gives $e^{-1}\approx 37\%$
  of arrows outside; at $R=2\sigma_r$, $e^{-4}\approx1.8\%$; at $R=3\sigma_r$,
  $e^{-9}\approx0.01\%$. So $\sigma_r$ is "the radius that a bit under two
  thirds of arrows land inside", and almost nothing lands beyond three times
  that.

### 3.3 Why that formula (optional)

*Skip this subsection if you are happy to trust the boxed result.*

Because $x$ and $y$ are independent, their joint density is the product of two
bell curves:

$$
\frac{1}{2\pi s^2}\,e^{-x^2/(2s^2)}\,e^{-y^2/(2s^2)}
= \frac{1}{2\pi s^2}\,e^{-(x^2+y^2)/(2s^2)}
= \frac{1}{2\pi s^2}\,e^{-r^2/(2s^2)} .
$$

This depends only on $r$ (the target is circularly symmetric). The area of a thin
ring of radius $r$ and width $dr$ is $2\pi r\,dr$, so the probability of landing
in that ring is

$$
\frac{1}{2\pi s^2}\,e^{-r^2/(2s^2)} \times 2\pi r\,dr
= \frac{r}{s^2}\,e^{-r^2/(2s^2)}\,dr .
$$

Substituting $\sigma_r^2 = 2s^2$ gives the Rayleigh density $p(r)$ above. To
get "probability of being beyond $R$" we add up (integrate) this from $R$ to
infinity. Since differentiating $-e^{-r^2/\sigma_r^2}$ gives exactly
$\frac{2r}{\sigma_r^2}e^{-r^2/\sigma_r^2}$, the total is

$$
\left[-e^{-r^2/\sigma_r^2}\right]_R^\infty = e^{-R^2/\sigma_r^2}.
$$

---

## 4. Rings, arrow thickness and scoring

### 4.1 The target face

A target face is a set of concentric rings. In the code each face is stored as
a map from **ring diameter** to **points** (`Target.face_spec` in
`archeryutils`). For a standard 10-zone face of overall diameter $D$, ring
number $n$ ($n = 1,\dots,10$) has diameter $nD/10$ and is worth $11-n$ points.

For the 40 cm WA 18 m indoor face:

| Points | 10 | 9 | 8 | 7 | 6 | 5 | 4 | 3 | 2 | 1 |
|---|---|---|---|---|---|---|---|---|---|---|
| Ring diameter (cm) | 4 | 8 | 12 | 16 | 20 | 24 | 28 | 32 | 36 | 40 |

**Compound** archers shoot the same face but with a smaller "inner 10"
(diameter $D/20$, i.e. 2 cm here): only arrows inside that smaller ring score
10, and the area between the inner 10 and the 8 cm ring scores 9. This is what
`resolve_target` selects in `h2h/models.py` for indoor compound archers.
Outdoors, the code uses a single fixed target (WA720: 70 m, 122 cm face).

### 4.2 Arrow thickness: the line-cutter rule

An arrow scores the **higher** ring if it touches the line. So the arrow's
*centre* only has to land within the ring's radius **plus the arrow's own
radius** $a$. The scheme's arrow diameters are:

* indoor: 9.3 mm, so $a = 4.65$ mm
* outdoor: 5.5 mm, so $a = 2.75$ mm

(The old scheme used 7.14 mm for both.)

So for a ring of diameter $\delta_k$, the **effective scoring radius** is

$$
R_k = a + \frac{\delta_k}{2}.
$$

### 4.3 "Probability of being worse than ring $k$"

Combine sections 3 and 4.2. The arrow scores *worse* than ring $k$ exactly when
its centre is further out than $R_k$, which has probability

$$
T_k = P(r > R_k) = \exp\!\left(-\left(\frac{a + \delta_k/2}{\sigma_r}\right)^{2}\right).
$$

This single "tail" quantity is the building block of everything that follows.
It is exactly the term `np.exp(-((arw_rad + diam/2)/sig_r)**2)` in
`archeryutils` (`HandicapScheme._s_bar`) and in `h2h/stats.py`.

---

## 5. Score distribution for one arrow, as a function of handicap

This is the heart of the system, so here is the whole chain in one place.

$$
h \xrightarrow{\ \text{section 2}\ } \sigma_r(h,d)
\xrightarrow{\ \text{section 4.3}\ } T_k(\sigma_r)
\xrightarrow{\ \text{this section}\ } P(\text{score}=s).
$$

Number the rings from the inside out, $k=1,\dots,K$, with scores
$s_1 > s_2 > \dots > s_K$ and $T_0 \equiv 1$.

* The arrow scores $s_k$ if it landed **beyond ring $k-1$** (probability
  $T_{k-1}$) but **not beyond ring $k$**, i.e. in the band between the two.
  Landing beyond ring $k$ is a subset of landing beyond ring $k-1$, so the
  probability of the band is a simple subtraction.
* So

$$
\boxed{\;P(\text{score} = s_k) \;=\; T_{k-1} - T_k, \qquad
P(\text{score} = 0) \;=\; T_K\;}
$$

The first line is "probability of getting beyond ring $k-1$, minus probability
of getting beyond ring $k$", i.e. landing in the band between them. The second
is a miss: further out than the outermost ring. By construction the
probabilities add up to exactly 1. In `h2h/stats.py` this is `per_arrow_pmf`
(PMF = probability mass function, the probability of each possible score).

### 5.1 Worked example: handicap 30 at 18 m (recurve, WA 18)

From section 2.4, $\sigma_r = 3.316$ cm; the indoor arrow radius is
$a=0.465$ cm.

| Ring (points) | Effective radius $R_k$ (cm) | $R_k/\sigma_r$ | $T_k=e^{-(R_k/\sigma_r)^2}$ | $P(\text{score}=s_k)=T_{k-1}-T_k$ |
|---|---|---|---|---|
| 10 | 2 + 0.465 = 2.465 | 0.743 | 0.5754 | 1 - 0.5754 = **0.4246** |
| 9 | 4 + 0.465 = 4.465 | 1.347 | 0.1632 | 0.5754 - 0.1632 = **0.4122** |
| 8 | 6 + 0.465 = 6.465 | 1.950 | 0.0224 | 0.1632 - 0.0224 = **0.1408** |
| 7 | 8 + 0.465 = 8.465 | 2.553 | 0.0015 | 0.0224 - 0.0015 = **0.0209** |
| 6 | 10 + 0.465 = 10.465 | 3.156 | 0.00005 | **0.0014** |
| 5 or less | | | | about 0.00005 in total |

So a handicap-30 archer shoots about 42% tens, 41% nines, 14% eights, 2%
sevens and almost nothing lower. (These match the program's output.)

How the distribution changes with handicap (same target, same 18 m):

| Handicap | P(10) | P(9) | P(8) | P(7) | P(6) | P(5) | P(4 or less) | Mean score per arrow |
|---|---|---|---|---|---|---|---|---|
| 10 | 0.888 | 0.111 | 0.001 | 0 | 0 | 0 | 0 | 9.887 |
| 30 | 0.425 | 0.412 | 0.141 | 0.021 | 0.001 | 0 | 0 | 9.237 |
| 50 | 0.130 | 0.237 | 0.250 | 0.190 | 0.112 | 0.053 | 0.028 | 7.802 |

Notice that the **spread** of the distribution also depends on handicap: at
handicap 10 almost every arrow is a 10 or 9, while at handicap 50 the arrows
are spread over six or seven scores. That is precisely the information a flat
score allowance throws away.

### 5.2 The expected score (what the handicap tables list)

The expected (average) arrow score is $\bar S=\sum_k s_k\,P(\text{score}=s_k)$.
A little rearranging (each ring boundary you cross, going outwards, costs the
difference in points between the two rings) gives a neat shortcut:

$$
\bar S \;=\; S_{\max} \;-\; \sum_{k=1}^{K} \Delta_k\, T_k ,
\qquad \Delta_k = s_k - s_{k+1},\ \ s_{K+1}=0 .
$$

For the 10-zone face every $\Delta_k = 1$, so $\bar S = 10 - \sum_{n=1}^{10} T_n$,
which is the formula quoted on archerygeekery.co.uk (there $T_n$ is written
$\exp(-(nD/20+0.357)^2/\sigma_r^2)$ in cm; $0.357$ cm is the old scheme's arrow
radius $7.14/2$ mm, which this repo's 2023 scheme replaces by 0.465 cm indoors
and 0.275 cm outdoors). The compound inner-10 face also has ten scoring rings
with every $\Delta_k=1$, so the same sum applies; its first ring is simply
smaller (2 cm instead of 4 cm across), which makes $T_1$ larger and the mean
lower.

Check against the program: for handicap 30,
$\bar S = 10\times0.4246 + 9\times0.4122 + 8\times0.1408 + 7\times0.0209 + 6\times0.0014 = 9.237$.
This is the value `archeryutils` returns from `arrow_score`, and its
`score_for_round` simply multiplies $\bar S$ by the arrows in each pass and sums
over passes. **The published handicap tables are therefore just the mean of the
distribution built here.** This repo keeps the *whole* distribution instead of
throwing away everything except the mean.

---

## 6. Score distribution for a whole pass (many arrows)

A pass has $n$ arrows (the app's default is 12). If the arrows are
independent and identically distributed, the total score distribution comes
from combining the single-arrow distribution with itself.

### 6.1 Two arrows

The total is $t$ if the first arrow scores $s$ and the second scores $t-s$.
For independent events we multiply probabilities, and then add over all ways
of reaching the same total:

$$
P(T_2 = t) = \sum_{s} P(S=s)\,P(S=t-s).
$$

This operation is called a **convolution**. Toy example using the (rounded)
handicap-30 values 10: 0.42, 9: 0.41, 8: 0.14, 7: 0.03:

| Total | Ways to make it | Probability |
|---|---|---|
| 20 | 10+10 | $0.42^2 = 0.1764$ |
| 19 | 10+9, 9+10 | $2\times0.42\times0.41 = 0.3444$ |
| 18 | 10+8, 8+10, 9+9 | $2\times0.42\times0.14+0.41^2 = 0.2857$ |
| 17 | 10+7, 7+10, 9+8, 8+9 | $2\times0.42\times0.03+2\times0.41\times0.14 = 0.1400$ |
| 16 | 9+7, 7+9, 8+8 | $2\times0.41\times0.03+0.14^2 = 0.0442$ |
| 15 | 8+7, 7+8 | $2\times0.14\times0.03=0.0084$ |
| 14 | 7+7 | $0.03^2=0.0009$ |

These sum to 1.0000, as they must.

### 6.2 $n$ arrows

For three arrows, convolve the two-arrow distribution with the single-arrow
one again, and so on $n-1$ times. This is what `n_pass_score_distribution`
does (`numpy.convolve` in a loop). Unlike a Monte Carlo simulation or a
bell-curve approximation, **the result is exact** and costs essentially nothing
for a dozen arrows.

An exact answer matters because a pass distribution is **not** a symmetric bell
curve for good archers: scores are capped at $10n$, so the distribution is
squashed against that ceiling and skewed to the left. For handicap 30 over
12 arrows the maximum possible 120 has a probability of only about 0.003%, yet
the mean is 110.85.

### 6.3 Mean and spread of a pass

Two useful shortcuts, true for independent arrows:

* mean of pass = $n\times$ mean of one arrow (here $12\times9.237 = 110.85$);
* variance of pass = $n\times$ variance of one arrow, so the standard
  deviation grows like $\sqrt n$ (here $0.778\times\sqrt{12} = 2.70$).

So the pass total of a handicap-30 archer is typically $110.85\pm2.7$,
whereas a handicap-50 archer averages $93.6$ with a spread of $\pm5.3$. Note
that the worse archer is both lower **and** about twice as variable.

---

## 7. Deciding who wins a pass

### 7.1 Why not compare raw scores?

If A (handicap 30, mean 110.9) and B (handicap 50, mean 93.6) simply compare
totals, A wins about **99.9%** of the time. No contest. A flat points
allowance would fix the *average* gap, but cannot fix the different
**variability** (B's spread is twice as wide, so B's good days are far more
extreme in absolute terms, and A's range is squeezed against the ceiling).

### 7.2 The percentile method

For each archer, use *their own* pass distribution $F$ (section 6) and compute
the **percentile** of the score $x$ they actually shot:

$$
\text{pct}(x) \;=\; P(T \le x) \;=\; \sum_{t \le x} P(T=t).
$$

This answers "what fraction of the time would an archer of this handicap
shoot this score or worse?". The archer with the **higher percentile** (the one
who over-performed their own handicap by more) wins the pass. This is
`percentile` and `decide_pass_winner` in `h2h/stats.py`.

**Worked example.** A (handicap 30) and B (handicap 50), 12 arrows at 18 m:

| A shoots | B shoots | A's percentile | B's percentile | Winner | Raw-score winner |
|---|---|---|---|---|---|
| 108 | 95 | 0.189 | 0.626 | **B** | A |
| 108 | 90 | 0.189 | 0.273 | **B** | A |
| 110 | 100 | 0.434 | 0.905 | **B** | A |
| 105 | 100 | 0.029 | 0.905 | **B** | A |

In the first row, A's 108 is below A's own average of 110.9 (only 19% of A's
passes are that bad or worse), while B's 95 is a little above B's average of
93.6, so B had the better day *relative to their handicap*.

### 7.3 Why this is fair

If every archer shoots exactly as their handicap predicts, then their percentile
is (for a continuous measurement) **uniformly distributed between 0 and 1**,
regardless of the handicap. Two such archers therefore each have a 50% chance of
the higher percentile, however different their handicaps are. A pass is won by
over-performing your own expectation, not by having a better handicap.
Because pass scores are whole numbers the percentile is only approximately
uniform, which is why a tie-break is still needed.

### 7.4 Ties

If the two percentiles are equal, the winner is the higher raw score; if that
is also equal, a fair coin flip decides. Ties do arise: a perfect score has
percentile exactly 1 for any archer, and two perfect passes are a genuine tie.

### 7.5 Over a whole event

Every archer shoots one pass against each opponent in turn (a round-robin
built with the "circle method" in `h2h/rotation.py`; an odd number of archers
gives one bye per rotation, in which the archer shoots alone with no
comparison). The H2H result between two archers is simply the count of passes
each won; if they share more than one pass and the counts are equal, it is a
draw (`Event.pairwise_result`). Each archer's distribution depends only on
their own handicap and target, so it is computed once at the start
(`Event.__init__`).

---

## 8. Going backwards: score to handicap

The app also shows, beside each pass score, an **equivalent handicap**, and the
standalone calculator turns a full-round score into a handicap. This reverses
section 5.2: expected score $\bar S(h)$ falls steadily as $h$ rises, so for a
target score $S^*$ we look for the $h$ with $\bar S_{\text{round}}(h) = S^*$.

`archeryutils` does this by **root-finding** (it uses Brent's method, a robust
variant of "guess, check, narrow down the interval"). The method repeatedly
evaluates the round's expected score at trial handicaps until the difference
from $S^*$ is essentially zero. The official handicap tables use whole numbers
and round the expected score *up*; the code reproduces that convention with
`ceil` when integer handicaps are requested.

**Caveat.** For a single 12-arrow pass the resulting equivalent handicap is
very noisy: the pass is one random draw (spread $\pm2.7$ points even at
handicap 30), whereas handicap is defined from the average of whole rounds. It
is displayed for interest only. It plays **no role** in deciding winners, which
goes handicap to distribution to percentile and never the other way round.

---

## 9. Assumptions and limitations

Being explicit about these is part of using the system honestly.

1. **One number sets everything.** Both the mean and the spread come from a
   single $\sigma_r$. The model cannot represent two archers with the same
   average but different consistency. In particular it has **no bowstyle
   term**: a longbow and a recurve archer at the same handicap are modelled as
   equally consistent (flagged in `Initial Testing/idea_evaluation.md`).
2. **Circular Gaussian aiming error**, centred on the gold. Real groups can be
   off-centre (a sight set slightly wrong), taller than wide (arrow drop,
   vertical fatigue) or heavy-tailed (the occasional wild arrow).
3. **Arrows are independent and identically distributed.** No warming up,
   fatigue, momentum, or "bad end" effects. This is what lets us convolve and
   use $\sqrt n$ scaling.
4. **The handicap is treated as exactly known and constant.** The model has no
   day-to-day variation in true ability and no uncertainty about the stated
   handicap (a handicap from one lucky round is treated like one from fifty).
5. **The constants (3.5%, 0.5 mrad, 0.00365, offset 6) are calibrated, not
   derived** (section 2.3).
6. **Percentile comparison is approximately, not exactly, fair for discrete
   scores** (section 7.3), and perfect or near-ceiling passes tie, which is
   resolved by raw score and then a coin flip.
7. **Scoring faces come from `archeryutils`.** Whole-number scores only; a
   single "10" (no separate X), and a hard-coded maximum of 10 per arrow in
   `h2h/models.py`.

---

## 10. Sources and where this lives in the code

### Sources

* Lane, D. (2013). *The Construction of the Graduated Handicap Tables for
  Target Archery.* <https://www.jackatkinson.net/files/Handicap_Tables_2013.pdf>
  (the original derivation of the tables, cited in the `archeryutils`
  docstrings; I used it only via those citations and secondary sources, not by
  reading the full paper).
* Atkinson, J. *Handicap System Maths*, Archery Geekery, 2 December 2024.
  <https://archerygeekery.co.uk/2024/12/02/handicap-system-maths/>
  (equations for $\sigma_\theta$, $\sigma_r$, the Rayleigh density and the
  expected-score sum; the old-vs-new scheme comparison).
* Atkinson, J. *archeryutils* (Python package), source files
  `handicaps/handicap_scheme.py`, `handicaps/handicap_scheme_agb.py` and
  `targets.py`. <https://github.com/jatkinson1000/archeryutils>
* Park, J. (2014). *Modelling archers' scores at different distances to quantify
  score loss due to equipment selection and technique errors.*
  <https://doi.org/10.1177%2F1754337114539308> (cited in the `archeryutils`
  docstrings; not consulted directly).

### Code map

| Maths | Section | Where |
|---|---|---|
| $\sigma_\theta$, $\sigma_r$ from handicap | 2 | `HandicapAGB.sigma_t`, `HandicapScheme.sigma_r` (archeryutils) |
| Tail probabilities $T_k$, expected score $\bar S$ | 4.3, 5.2 | `HandicapScheme._s_bar` (archeryutils) |
| Per-arrow probabilities $P(\text{score}=s_k)$ | 5 | `per_arrow_pmf` in `h2h/stats.py` |
| $n$-arrow convolution | 6 | `n_pass_score_distribution` in `h2h/stats.py` |
| Percentile and winner | 7 | `percentile`, `decide_pass_winner` in `h2h/stats.py` |
| Target face selection (compound inner-10, outdoor) | 4.1 | `resolve_target` in `h2h/models.py` |
| Round-robin pairing | 7.5 | `h2h/rotation.py` |
| Score to handicap | 8 | `equivalent_handicap`, `handicap_for_round_score` in `h2h/stats.py` |
