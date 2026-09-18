# Handicapped H2Hs

**Status: under active development, not yet feature-complete.**

A localhost web tool for running fair head-to-head (H2H) archery matches
between archers of different skill levels and bowstyles, using the Archery GB
handicap system rather than a flat score allowance. See
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

## Repo structure

```
main.py                 Entry point -- run this to start the app
h2h/                    Application package
  stats.py                Core statistics engine (handicap -> score
                           distributions -> percentiles). No Flask
                           dependency; independently testable.
  models.py                Archer/Pass/Match data model, orchestrates
                            stats.py over a 60-arrow round split into
                            n_pass-arrow passes.
  chart_data.py            Builds the JSON payload for the advanced-mode
                            interactive distribution chart.
  state.py                 In-memory session state (single-user, no database).
  app.py                   Flask routes.
  templates/                Jinja2 HTML templates.
  static/                   Client-side JS (Chart.js rendering).
tests/                  pytest test suite (mirrors the h2h/ modules above).
Specification/          Design documents driving development:
  humanSpec.md             One-line brief for the current version.
  AISpec.md                Detailed specification expanded from humanSpec.md.
  prd.json                 Task breakdown with pass/fail tests, tracked as
                            work progresses.
  feedback.md               Rounds of feedback on the running app.
  logbook.md                Implementation history, assumptions, and notes.
  loopPrompt.md / feedbackPrompt.md
                             Process instructions used to drive development.
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
(for this version) are listed in `Specification/AISpec.md`.
