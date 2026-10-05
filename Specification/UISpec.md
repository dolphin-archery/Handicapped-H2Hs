# UI Specification and Implementation Plan: Handicapped H2Hs web UI

Audience: the AI agent implementing the new UI on this code base.
Companion documents (read first, in this order):

1. `Specification/deploymentConstrains.md` (hosting and architecture rules: static site, Pyodide, GitHub Pages, autosave, single-page app). Where this document is more specific because it has seen the real code, this document wins on detail; on principle the constraints document wins.
2. `Specification/AISpec.md` section 5 (functional requirements). **This is the authority on behaviour.** This document specifies presentation and architecture; it must never be used to change what the app computes or enforces.
3. `README.md` and the latest entries of `Specification/logbook.md`.

Follow the repository's existing working conventions: small commits, a logbook entry per task, tasks recorded in `prd.json` format (id, name, description, tests, completed). The tasks in section 8 are converted into `Specification/UI-prd.json`, which adds `phase`, `depends_on`, `gate` and `needs_review` fields.

Python rules from the owner: package management with `uv` only (never `pip` or `conda`), numpy-style docstrings (purpose, arguments, returns) on every function added or changed, minimal and surgical changes to existing code.

---

## 1. Goal

Replace the Flask-and-Jinja prototype with a modern, responsive single-page UI built with **React, TypeScript, Vite and Mantine**, while the existing Python calculation code runs unchanged in the browser through Pyodide. The result is a static site deployed free on GitHub Pages with no server.

Priorities, in order:

1. **Correctness parity**: every number and rule the Flask app produces is reproduced exactly.
2. **Desktop and laptop first**: the primary user is a scorer on a laptop, running an event with archers around them. Phone use must work well, but desktop layout decisions win ties.
3. **Never lose an event**: continuous autosave and resume (section 6).
4. **Simple, clean, fast UI** using Mantine components rather than custom CSS wherever possible.

Not a goal: new statistical features, accounts, sync between devices, or any server.

## 2. What the existing code base looks like (findings that shape this plan)

Read from the repository, not assumed:

| Area | Finding | Consequence |
|---|---|---|
| Core modules | `h2h/stats.py`, `rotation.py`, `models.py`, `outputs.py`, `exports.py`, `chart_data.py` import no Flask. Runtime imports are only `numpy`, `archeryutils`, `fpdf2` and the standard library. | These can run in Pyodide as they are. |
| Unused dependencies | `scipy` and `pandas` are **not imported anywhere** in `h2h/` (only mentioned in comments); `notebook` is only for `Initial Testing/`. | Do **not** ship scipy or pandas to the browser. Browser download is about 11 MB instead of about 29 MB. Do not remove them from `pyproject.toml` without the owner's approval. |
| Flask layer | `h2h/app.py` (routes), `h2h/state.py` (`SessionState`, a single in-memory global), `h2h/templates/`, `h2h/static/match_chart.js` (Chart.js). | This is what the new UI replaces. |
| State | `Event` (in `models.py`) is a stateful in-memory object holding all results. `SessionState` holds setup progress, the random pairing draw, and a `graph_view` flag. | State must become a serialisable document stored in the browser (section 5) and `Event` must be rebuilt from it. |
| Determinism | The schedule (`rotation.build_schedule` / `build_sit_out_schedule`) is deterministic. `Event` handicaps depend only on earlier passes. The only randomness is the Stage 3 draw, and the export timestamp (`datetime.now()`). | Persist the draw result (assignment); have the UI supply the export time. |
| Pre-formatted output | `outputs.pass_table_rows`, `outputs.percentile_pair_text` and the leaderboard/archer builders already produce display-ready text and numbers. | The UI shows these values. **The UI must not recompute statistics or reformat numbers.** |
| Chart | `chart_data.build_pair_chart_data` returns a JSON payload; `match_chart.js` draws it with Chart.js, including a custom interaction mode (`nearestCurveX`) and a plugin that places rotated pass labels ("P3") without overlap. | Keep Chart.js and port this code faithfully; do not rewrite the chart in another library. |
| Tests | About 16,000 lines in the repo; the pure-core tests (`test_stats`, `test_event`, `test_rotation`, `test_pair_chart_data`, `test_target_resolution` and others) are Flask-free. `test_app`, `test_event_routes` (2,544 lines), `test_integration`, `test_handicap_calculator` and `tests/helpers.py` use Flask; `test_state` tests `SessionState`. | Keep every existing test passing throughout. The Flask route tests are an excellent catalogue of behaviours to port to the new UI tests. |
| Python version | `requires-python >= 3.14`, and Pyodide `v314.0.7` ships Python 3.14.2. | No version conflict. Pyodide's numpy (2.4.6 when tested) is older than the local pin (`>=2.5.3`); see constraints section 4.3. |

Already verified in a browser (see `deploymentConstrains.md` section 2): Pyodide v314.0.7 loads numpy, installs `archeryutils` 3.0.0 and `fpdf2` 2.8.9 with `micropip`, runs handicap calculations, and builds a PDF and CSV in memory. **Not yet verified: the app's own modules (`stats.py` and friends) running in Pyodide.** Task UI-1 is a gate that proves this before any further work: every later task depends on it, including the Python-only tasks UI-2 to UI-5.

## 3. Decisions made in this specification

These are assumptions; each is easy to reverse and the owner may overrule them.

| # | Decision | Reason |
|---|---|---|
| D1 | Browser stack: React + TypeScript + Vite + Mantine (current stable major; pin it). Use the Mantine MCP server and official docs for component APIs. | Owner's choice of Mantine. React and TypeScript are what agents write most reliably. |
| D2 | Hash routing (`#/...`) via React Router's hash router. | GitHub Pages cannot serve deep links. |
| D3 | Saved events are listed on a Home view; the user can hold several (in progress and completed) and delete them. | Cheap once storage is keyed by event id; lets finished events be re-exported later. Replaces the old global "Reset". |
| D4 | "Results" and "Archer results" become **one Results view with tabs** (Leaderboard, Pairwise, Passes, Archers). | Desktop screens can hold this comfortably; fewer pages. All information of the old pages is kept. |
| D5 | "Graph view" is a **device-level display preference** (a switch in the header or match view), not part of the saved event. | It only affects display. |
| D6 | The handicap calculator exists both as its own route and as a drawer opened from Stage 2, so users do not leave the archers form to use it. | The single-page app preserves form state either way, but a drawer is smoother. |
| D7 | Advancing to the next pass asks for confirmation. | Advancing locks the previous pass's scores. The old app had no prompt. |
| D8 | Light, dark and automatic colour schemes via Mantine. | Nearly free with Mantine. |
| D9 | Chart.js is installed from npm and tree-shaken, not loaded from a CDN. | Fewer third-party requests; consistent with the privacy rule. |
| D10 | Names are not checked for uniqueness. | Not in AISpec; do not add rules to the specification. Raise as an open question if it causes confusion. |
| D11 | `record_match` sets `status` to `complete` when `Event.is_complete` is true (final pass reached and every match in it scored), otherwise leaves it `running`. Matches on the final pass stay editable after completion. | No command in section 5.4 set `complete`. The Flask app never blocks editing the final pass, and "saving again replaces scores until the event advances" applies (the final pass never advances). |
| D12 | Field ownership in the event document: the storage layer sets `revision` and `updated_at` on every write; the UI may change `name` directly (rename); every other field changes only through a bridge command. | Rename is a label change with no rules, so a bridge round trip adds nothing; everything else keeps Python as the authority. |
| D13 | When more than one event is in progress (status `setup` or `running`), the Resume card shows the most recently updated one; the others are listed on Home. | Section 6, rule 4 assumed a single in-progress event. |
| D14 | Completed events are kept until the user deletes them; no auto-archive. | Closes the open question in section 11; the simplest behaviour, and backups cover eviction. |
| D15 | Pyodide (runtime and its numpy) is loaded from jsDelivr pinned to `v314.0.7`, and `archeryutils` and `fpdf2` from PyPI via `micropip`; Pyodide is not self-hosted. CI uses network access for these. | Matches the verified smoke test (deploymentConstrains 2) and keeps the repository small. The requests carry no user data. |
| D16 | No dependency changes to `pyproject.toml` in this plan. The `fpdf` import in `exports.py` is lazy (inside `results_pdf`, approved by the owner after the UI-9 review): the engine host installs fpdf2 on the first `export` with kind `results_pdf`, not at start-up. | Dependency changes need owner approval (section 11, section 12). The lazy import cuts the first load by about 2.5 MB at the cost of a few seconds on the first PDF export. |
| D17 | The Stage 3 draw moves into a new module `h2h/draw.py` (whitelisted for the browser) that both `state.py` and `bridge.py` import. | Keeps the core modules (`stats`, `models`, `outputs`, `rotation`) untouched, keeps the draw available after `state.py` is retired (UI-22), and lets UI-2 and UI-3 edit different files. |
| D18 | Backup import rejects files larger than 10 MB. | Section 6, rule 7 asked for a size limit without a value; one event document is a few tens of kB, so 10 MB holds hundreds of events. |

## 4. Target architecture

```
Browser tab
 +-----------------------------------------------------------+
 |  React + Mantine UI (main thread)                          |
 |    router (hash) | forms | tables | chart | storage layer  |
 |         |                                   ^              |
 |         | postMessage (JSON strings)        | IndexedDB    |
 |         v                                   |              |
 |  Web Worker: Pyodide + h2h core + bridge    |              |
 +-----------------------------------------------------------+
```

The UI holds the event document (section 5) as its single source of truth and mirrors it to IndexedDB. Python holds **no state between calls**: every call receives the document and returns plain data.

### 4.1 Repository layout

```
h2h/                      existing core (core modules unchanged; new files from UI-2, UI-3, UI-4)
  bridge.py               NEW: pure functions, JSON in / JSON out (section 5)
  draw.py                 NEW: pure Stage 3 draw function (UI-3, decision D17)
  app.py, state.py, templates/, static/   legacy Flask; leave working until UI-22 (state.py calls draw.py after UI-3)
web/                      NEW: the front end
  index.html  404.html
  package.json  vite.config.ts  tsconfig.json  postcss.config.cjs
  public/py/              generated Python bundle (git-ignored, built by a script)
  scripts/build-py-bundle.mjs   zips whitelisted h2h modules into public/py
  scripts/pyodide-gate/   UI-1 gate: scenario.py, run-gate.mjs, golden.json
  src/
    main.tsx  App.tsx  theme.ts
    engine/               worker.ts, client.ts (typed request/response wrapper), types.ts
    storage/              db.ts (IndexedDB), autosave.ts, backup.ts, migrations.ts
    routes/               one module per view (section 7)
    components/           shared pieces (PassTable, DistanceSelect, SaveIndicator ...)
    chart/                MatchChart.tsx and the ported plugin code
  tests/                  Vitest unit tests; Playwright e2e in web/e2e/
tests/                    existing pytest suite + new test_bridge.py, test_draw.py, fixtures/ (UI-5)
.github/workflows/        ci.yml (tests) and pages.yml (deploy)
```

### 4.2 Technology table

| Concern | Choice | Notes |
|---|---|---|
| UI components | `@mantine/core`, `@mantine/hooks`, `@mantine/form`, `@mantine/notifications`, `@mantine/modals` | Start from Mantine's official Vite setup (check current docs via the MCP). Pin versions and commit the lockfile. |
| Routing | `react-router` hash router | Section 7.1 |
| State | React context plus a reducer, or `zustand`; agent's choice; keep it small | Document is the one source of truth |
| Persistence | IndexedDB through `idb-keyval` or `idb` | Section 6 |
| Python in browser | `pyodide` npm package, pinned to the same version as the `indexURL` (currently `v314.0.7`), run in a module Web Worker | Verify the loading method for module workers in current Pyodide docs |
| Chart | `chart.js` (tree-shaken) | Port `match_chart.js` |
| Unit and component tests | Vitest, React Testing Library, `fake-indexeddb` | |
| End-to-end tests | Playwright (Chromium, WebKit, mobile emulation) | |
| Python tests | existing pytest plus new `tests/test_bridge.py` | |

### 4.3 Python packaging for the browser

- Browser runtime Python packages: **numpy** (Pyodide package), **archeryutils** and **fpdf2** (via `micropip`; fpdf2 pulls in pillow and fonttools, which are available). Nothing else.
- Do not `micropip.install` this project from `pyproject.toml` (its pins exceed Pyodide's numpy). Instead the build script zips only these modules into a bundle that the worker fetches and unpacks into the Pyodide filesystem: `__init__.py`, `stats.py`, `rotation.py`, `models.py`, `outputs.py`, `exports.py`, `chart_data.py`, `draw.py`, `bridge.py`. Exclude `app.py`, `state.py`, `templates/`, `static/`.
- Add `web/pyodide-requirements.txt` with loose bounds for the browser (`archeryutils>=3.0.0`, `fpdf2>=2.8.9`); numpy comes from Pyodide.
- Stamp the bundle file name with a content hash so a deployment always loads matching code.
- Decision D16: `exports.py` imports `fpdf` inside `results_pdf`, so fpdf2, pillow and fonttools (about 2.5 MB) are installed by the engine host on the first PDF export instead of at start-up; importing `h2h.bridge` does not import `fpdf` (tested). The first load is about 9.7 MB.

## 5. The Python bridge (`h2h/bridge.py`) and the event document

### 5.1 Contract rules

- One module, pure functions, no Flask import, no module-level mutable state, no file or network access.
- Cross the JS/Python boundary as **JSON strings** (`json.dumps(..., allow_nan=False)` so a stray `nan` fails loudly in tests rather than corrupting data). Do not pass Pyodide proxy objects around.
- JSON keys are `snake_case` end to end (matching existing Python names); TypeScript types in `web/src/engine/types.ts` mirror them.
- Every function returns `{"ok": true, "data": ...}` or `{"ok": false, "error": {"code": "...", "message": "..."}}`. Codes: `validation` (bad input; message reuses the existing `ValueError` text, which the current tests assert on), `tiebreak_required` (from `stats.TieBreakRequired`), `state` (action not allowed in the current state), `internal`.
- Reuse existing builders (`outputs`, `exports`, `chart_data`, `models`) and serialise dataclasses with `dataclasses.asdict`. Do not copy logic.
- Mutating commands are functional: they take a document and return a **new** document.
- Docstrings in the repository's numpy style on every function.

### 5.2 Event document (schema version 1)

```jsonc
{
  "schema_version": 1,
  "id": "uuid",
  "name": "Club night 3 Oct",          // user-editable label
  "created_at": "ISO-8601", "updated_at": "ISO-8601",
  "revision": 17,                        // incremented on every write (section 6)
  "status": "setup" | "running" | "complete",
  "setup": {
    "stage": 1,                          // furthest stage completed, for guards and resume
    "n_archers": 4, "total_arrows": 60, "n_pass": 12,
    "setup_mode": "simple" | "advanced",
    "shoot_byes": true,
    "target": { "distance_key": "20yd", "face_cm": 60 },   // simple mode
    "update_handicaps": false, "n_lookback": null, "start_weight": null
  },
  "archers": [                           // entry order (Stage 2)
    { "name": "...", "bowstyle": "Recurve", "handicap": 45.0,
      "target": null | { "distance_key": "...", "face_cm": 60, "face_type": "10_zone" } }
  ],
  "assignment": [2, 0, 3, 1] | null,     // schedule position -> index into archers (Stage 3 draw)
  "scores": {                            // keyed by pass index then match index (as strings)
    "0": { "0": { "scores": {"0": 280, "1": 301}, "closest": null } }
  },
  "current_pass": 0
}
```

Notes the agent must respect:

- After the draw, `Event` archer indices are **schedule positions**: event archer `p` is `archers[assignment[p]]`. `scores` keys use these positions.
- The schedule is **not stored**; it is rebuilt from `n_archers`, `total_arrows // n_pass` and `shoot_byes` using the existing builders (deterministic).
- `graph_view` is not in the document (decision D5).
- Persist only inputs, never computed results. Anything computed (percentiles, handicaps, winners) is derived on demand, so a code fix can never leave stale numbers in storage.

### 5.3 Rebuild rule (replay)

`rebuild_event(doc) -> Event`:

1. Build the schedule and the `Event` from `setup`, `archers` and `assignment`.
2. For each pass `r` from 0 to `current_pass`: set `event.current_rotation_index = r`, call `event.record_match(scores, closest=...)` for each stored match, then call `event.advance()` if `r < current_pass`.

This is valid because a pass's handicaps depend only on earlier passes (`Event.handicap_for`). Cache the rebuilt `Event` inside the worker keyed by `(id, revision)`; this is a performance cache only, not state the UI relies on.

### 5.4 Commands

All take the document (except where noted) and return `ok/data` or `ok/error`.

| Command | Purpose | Replaces |
|---|---|---|
| `options()` | Static lists: distance groups, face sizes (standard and advanced), face types, bowstyles, handicap min/max, defaults (`DEFAULT_N_LOOKBACK`, face type, distance, 60 cm), calculator rounds per kind and defaults | Values passed to templates |
| `new_document(id, now_iso)` | A fresh document with defaults | `SessionState()` |
| `apply_stage1(doc, form)` | Validates; sets `setup`; builds the schedule to check it; clears later stages | `session.start_stage1` and `stage1_submit` |
| `apply_stage2(doc, archers, updating)` | Validates every archer and the updating parameters (row-numbered messages); stores them; draws the first assignment | `stage2_submit`, `session.start_stage2` |
| `redraw(doc, seed)` | New assignment, preferring one whose pairings differ from the current one | `session.redraw_pairings` |
| `stage2_info(doc)` | Read-only Stage 2 defaults derived from `setup`: the default start weight (passes per archer) and the target description | New (UI-12) |
| `pairings(doc)` | Per pass: matches by name, byes, sitting out | `stage3` |
| `start_event(doc)` | Builds the event, sets status `running` | `session.start_event` |
| `overview(doc)` | Current pass: per match names, scored flag, scores, percentile text, winner; sitting out; complete / is_last | `event_rotation` |
| `match(doc, match_index)` | Names, per-archer score maximum, existing scores, pass table rows, tie-break flag | `event_match` |
| `record_match(doc, match_index, scores, closest)` | Validates and records; sets `status` to `complete` when the event is complete (D11); returns the new document plus the match view; `tiebreak_required` error if tied | `event_match_submit` |
| `advance(doc)` | Moves to the next pass; refuses if incomplete or last | `event_advance` |
| `results(doc)` | Leaderboard, pairwise, per-pass groups, completed pass count | `event_results` |
| `archer_results(doc)` | Per-archer sections | `archer_results` |
| `pair_chart(doc, a, b)` | `build_pair_chart_data` payload | `pair_chart` and chart in `match` |
| `export(doc, kind, now_iso)` | `kind` is `leaderboard_csv`, `archer_results_csv` or `results_pdf`; returns text or base64 bytes plus the file name | `export_*` routes |
| `calculator(kind, round, compound, score)` | Handicap rounded to 1 decimal | `handicap_calculator_submit` |
| `validate_document(raw)` | Checks and migrates an imported or stored document; never trusts input | New (backup import, schema upgrades) |

Pass the export time in as an ISO string from JavaScript (`now_iso`); do not rely on `datetime.now()` in the browser. Use the repository's `exports.filename_stamp` and timestamp helpers unchanged.

The Stage 3 draw randomness comes from a seed supplied by JavaScript (`crypto.getRandomValues`); the bridge uses `random.Random(seed)`. To keep behaviour identical, move the draw logic out of `SessionState.redraw_pairings` into a small pure function in `h2h/draw.py` (decision D17) that takes the schedule, the number of archers, a `random.Random` and the current assignment, and that both `SessionState` (passing its own `rng`) and the bridge call (task UI-3); `SessionState` behaviour and `test_state.py` must be unchanged.

## 6. Persistence, autosave and resume (implements constraints section 3, rule 4)

Storage layout in IndexedDB (one database, keyed values):

- `event:<id>` full event document; `events:index` a list of `{id, name, status, updated_at, n_archers}` for the Home view.
- `settings` device preferences: colour scheme, graph view, last opened event id.
- `draft:<id>` unsaved form drafts (current stage's fields, match score boxes), saved on a short debounce (about 500 ms).
- `session:<id>` last route, so a reopened tab returns to where the user was.

Rules:

1. **Write before you show.** After every command that changes the document (stage submit, redraw, record_match, advance, rename), write to IndexedDB first, then update the screen. If the write fails, show a persistent red alert (not a toast): "This event is NOT being saved" with a "Download backup" button.
2. **Atomic and revisioned.** Each write is a single transaction that replaces the whole document and increments `revision`. Before writing, check the stored `revision` equals the one the UI loaded; if not (another tab changed it), show a modal: "This event changed in another tab", with "Load latest" and "Overwrite with this tab". Running the same event in several tabs or windows at once is not supported; this check is only a safety net against losing data.
3. **Save indicator** in the header: "Saved HH:MM", "Saving...", or the error state.
4. **Startup:** if the app is opened at its bare URL (no hash) and an in-progress event exists, show a "Resume event" card (event name, stage, pass) and a "Start new event" option; never silently discard an event. Resume restores `last route` for that event. With several in-progress events, the card shows the most recently updated one (decision D13).
5. **Route guards:** each event route checks the document's `setup.stage` and `status`; if not allowed, redirect to the correct earlier route with a short Mantine notification. Unknown event id gives a friendly "Event not found" view with a link Home.
6. **Persistent storage:** call `navigator.storage.persist()` after the first successful save; do not depend on the result.
7. **Backup and restore:** "Download backup" exports one or all events as JSON; "Import backup" passes the file through `validate_document` (size limit of 10 MB per decision D18, schema check, migration) before storing; it never overwrites an existing event with the same id without asking. When an event becomes complete, the completion alert on the pass overview reminds the user that data stays only in this browser and offers "Download backup" (deploymentConstrains 3, rule 4).
8. **Drafts:** drafts are discarded when the corresponding command succeeds.
9. **Schema migrations** live in `bridge.validate_document` (Python knows the semantics); the UI never edits stored documents by hand, except for the fields listed in decision D12 (`name`, set by the UI; `revision` and `updated_at`, set by the storage layer).

Failure modes to handle explicitly: IndexedDB unavailable (private mode), quota exceeded, a corrupt stored value (offer to export what can be read, then delete), and the Python engine crashing (stored data is unaffected; show a Reload button).

## 7. UI specification

### 7.1 Shell, navigation and routes

Desktop (Mantine `md` breakpoint and up, about 992 px): `AppShell` with a **left navbar** (always visible), a slim **header**, and a content area with a maximum width of about 1200 px. Below `md`: the navbar collapses into a burger-triggered drawer; content is single column; primary actions move to a sticky bottom bar.

Header contents: app title, event name (editable via a small menu), save indicator, Graph view switch (visible when an event is running), colour scheme toggle, event menu (Download backup, Delete event).

Navbar items: Home; for the current event: Setup (with stage progress), Current pass, Results; then Handicap calculator and About. Items that are not yet reachable are disabled (not hidden) with a tooltip saying why.

Footer / About: one line stating that all data stays in this browser, and a backup reminder.

| Route (hash) | View | Guard |
|---|---|---|
| `#/` | Home: saved events, New event, Import backup, Resume prompt | none |
| `#/e/:id/setup/1` | Stage 1 | event exists |
| `#/e/:id/setup/2` | Stage 2 | stage 1 done |
| `#/e/:id/setup/3` | Stage 3 | stage 2 done and not started |
| `#/e/:id/pass` | Current pass overview | status running or complete |
| `#/e/:id/pass/match/:i` | Match scoring | running or complete (D11); `:i` valid |
| `#/e/:id/results/:tab` | Results tabs: `leaderboard`, `pairwise`, `passes`, `archers` | running or complete |
| `#/calculator` | Standalone handicap calculator | none |
| `#/about` | Privacy, storage, backup help | none |
| anything else | Redirect to `#/` | |

Also provide a root `404.html` for invalid real URLs (friendly message and link to the app).

### 7.2 Behaviours that must be preserved (from README and AISpec; not exhaustive, section 5 of AISpec governs)

- Stage 1: archers at least 2; total arrows default 60; arrows per pass default 12 and must **divide total arrows**; the n_pass control offers only divisors of the total, tracks the user's last intended value, and snaps to the nearest valid divisor when the total changes (see the old script in `stage1.html`); "Shoot byes?" appears only for an odd number of archers of at least 3; Simple vs Advanced mode; Simple shows a distance (grouped Metric / Imperial, default 20 yd) and face size (40, 60, 80, 122 cm, default 60); distances up to 25 m / 25 yd count as indoor.
- Stage 2: name, bowstyle (Recurve, Compound, Barebow, Longbow) and handicap 0-150 (step 0.1) per archer; advanced adds face type, face size (20, 35, 40, 50, 60, 65, 80, 122 cm) and distance per archer; "Update handicaps during matches" (advanced only, default No) reveals n_lookback (default 4) and start weight (default passes per archer); errors are row-numbered and **nothing typed is lost** on a rejected submit; link to the calculator.
- Stage 3: show every pass's pairings, byes ("shoots alone") and sitting-out archers; Redraw as often as wanted; Confirm starts the event.
- Overview: columns Match | Score | Percentiles | Winner | Actions; "Enter scores" or "View / edit"; **Advance to next pass** disabled until every match is scored, with the reason shown; final pass shows completion and a link to results instead of Advance.
- Match page: **no handicap is shown beside archer names while entering scores**; score boxes accept whole numbers from 0 to that archer's own maximum (varies by target face); saving again replaces scores until the event advances; after saving, a table shows only this pass (Archer, Score, Percentile, [Pass starting handicap when updating is on], Handicap, Winner); the **tie-break** control (closest to the middle, choose exactly one of the two archers) appears only when percentile and score are tied (or when a saved result was decided by it, so it can be corrected); scores are kept when the tie-break is requested; there is no coin flip; a bye match has no winner and no chart.
- Chart: both curves, legend with name and the handicap the curve was built from, vertical dashed score markers labelled "P<n>", this pass's markers by default with a checkbox for earlier passes, axis widened to include every marker.
- Results: leaderboard (rank with ties sharing a rank, points, passes decided, starting and to-date handicap, only completed passes count), pairwise results with "View chart" when graph view is on, per-pass tables with a clear visual separation between matches, archer sections with an Average row; CSV and PDF downloads carry the export date and time.
- Calculator: Indoor or Outdoor, round list per kind, compound checkbox for indoor only, score in, handicap out, not stored.
- Percentile text uses `outputs.percentile_pair_text` behaviour (extra decimals until two percentiles differ).

### 7.3 View specifications

All views: Mantine components, no custom CSS beyond theme tokens and small utility styles. Every input has a visible label and error text (Mantine `error` prop). Primary action is a filled `Button`; destructive actions are red and confirmed with a modal. Network-independent: no view fetches anything from a server we run.

**Home.** Title, "New event" (primary), "Import backup". List of saved events as cards or a table (name, status badge, archers, last updated), each with Open, Rename, Download backup, Delete (confirm). If an in-progress event exists, a prominent "Resume" card at the top. Empty state explains what the app does in two sentences.

**Setup shell (stages 1-3).** A Mantine `Stepper` across the top (Event, Archers, Pairings); content in a centred card (max about 760 px for Stage 1 and 3, full content width for Stage 2).

**Stage 1.** Fields in a two-column grid on desktop (single column below `sm`): number of archers (`NumberInput`), total arrows (`NumberInput`), arrows per pass (`Slider` over divisor indices with the current value shown, plus `marks`), setup mode (`SegmentedControl` Simple / Advanced), shoot byes (`SegmentedControl` Yes / No, shown only when applicable, with the explanation as description text), and in Simple mode distance (grouped `Select`, searchable) and face size (`Select`). A derived summary line ("5 passes per archer") is welcome but must come from Python values, not duplicated logic. Submit = "Continue" (loading state while the engine is starting).

**Stage 2.** Desktop: a `Table` with one row per archer and input cells (Name, Bowstyle, Handicap; Advanced adds Face type, Face size, Distance), Enter moves to the next row's name. Below `sm`: one `Card` per archer with stacked fields. In Advanced mode, an "Update handicaps during matches" `SegmentedControl` reveals the two numeric parameters with their descriptions. A "Handicap calculator" button opens a drawer (decision D6). Errors: an `Alert` with the bridge message at the top plus the offending row highlighted (derive the row from the message's row number, or have the bridge return `row` and `field`; prefer returning them). Drafts are saved as the user types.

**Stage 3.** A `Table` of passes (Pass | Matches | Sitting out). Buttons: "Redraw pairings" (secondary) and "Confirm pairings and start event" (primary). Back to Stage 2 stays available until confirmation; after confirmation Stage 1-3 are read-only summaries in the Setup menu (the old app redirected away).

**Current pass (overview).** Header "Pass 3 of 5" with a `Progress` bar showing matches scored. `Table`: Match, Score (A - B), Percentiles (A - B), Winner, status `Badge`, action `Button` ("Enter scores" or "View / edit"). Clicking a row also opens the match. Sitting-out note. "Advance to next pass" (primary, disabled until complete, with a hint); on click, confirm modal (D7). On the final pass and complete: a success `Alert` with "View results", the export download buttons, and a "Download backup" button with a one-line reminder that data stays only in this browser (section 6, rule 7).

**Match.** Desktop: two columns. Left column: a card with a score `NumberInput` per archer (label "<name> score (0-<max>)", `inputMode="numeric"`, integers only, first field autofocused, Enter saves), the tie-break control when required, and a Save button; below it the "This pass" results table when scores exist. Right column: the distribution chart panel when Graph view is on, or a muted hint that Graph view is off. Mobile: single column, chart below. After a successful save show an inline confirmation and two buttons: "Next unscored match" and "Back to overview". On a refused tie, keep the typed scores, show the tie-break control and an `Alert` with the existing message. A bye match shows one input and no chart.

**Chart component.** Port `match_chart.js` into `MatchChart.tsx` using Chart.js directly, keeping `nearestCurveX`, the label-placement plugin and all behaviours, including `chart.markerLabelBoxes` (the placed label boxes, kept for tests; no existing test uses it, so UI-16 writes new ones). Source colours from the theme for dark mode but keep the two series clearly distinct (current blue `#4c72b0` and red `#c44e52`; colour-blind safe). Responsive container, redraws on theme change. Includes the "Show previous passes' scores too" checkbox and the "How the winner is decided" explanation in a collapsible `Accordion` or `Collapse` below the chart.

**Results (tabs).**
- Leaderboard: `Table` with rank, archer, points, passes decided, starting handicap, to-date handicap; a caption stating how many passes are completed; a "Download" `Menu` (Leaderboard CSV, Archer results CSV, Full report PDF).
- Pairwise: `Table`; "View chart" opens the pair chart in a `Modal` or `Drawer` when Graph view is on.
- Passes: an `Accordion` with one item per scored pass (latest open); each contains the pass table with the match separation (use a visible thick border between matches, via a small style rule).
- Archers: one `Card` per archer, heading line (name, total score, starting handicap, to-date handicap) plus the passes table with an Average row; handles "no completed pass yet" text.
- Show the same Download menu on this view's header.

**Calculator.** `SegmentedControl` Indoor / Outdoor, searchable `Select` of rounds, compound `Checkbox` (indoor only, with the explanation), `NumberInput` score, "Calculate" button; result shown prominently ("Handicap: 49.3"). Invalid input shows the existing message.

**Delete event / reset.** Menu action with confirm modal naming the event ("This permanently deletes the event and all its scores from this browser").

### 7.4 Responsive rules

- Design and review at 1440 x 900 and 1280 x 720 first, then 768 and 390 px wide.
- Tables wrap in `Table.ScrollContainer` rather than breaking layout; tables with five or fewer columns should fit at 390 px by using compact sizing.
- Touch targets at least 44 px on mobile; use Mantine `size="md"` or larger for inputs on small screens and **keep input font size at 16 px or more on mobile** (iOS Safari zooms smaller inputs).
- Numeric inputs use `inputMode` so phones show the right keypad.
- Use `visibleFrom` / `hiddenFrom` or `useMediaQuery` for the table-versus-cards switch in Stage 2.
- No horizontal page scroll at any width.

### 7.5 Accessibility and polish

Labels on every input; logical tab order; visible focus; colour is never the only signal (winner shown as text plus badge); sufficient contrast in both colour schemes; `aria-live` for save status and errors; headings in order; respects `prefers-reduced-motion`; page `<title>` updates per route; English only.

### 7.6 Loading, errors and offline

- Engine start (about 10 s on first visit, faster when cached): a non-blocking banner with progress; Home and the Stage 1/2 forms are usable while it loads; actions that need Python show a loading state until ready.
- Engine failure (for example offline on the very first visit): clear message, Retry button, stored data untouched.
- No service worker is required. Do not add one without checking cache-invalidation against the hashed Python bundle.

## 8. Implementation plan

Work on a dedicated branch (suggested `ui-redesign`) from an unchanged `main`; tag the current prototype first (`git tag prototype-flask`). Keep the Flask app working and all existing pytest tests green until task UI-22. Commit per task with the task id in the message; add a short logbook entry per task.

Each task lists **Verify** criteria; a task is complete only when they pass.

**Phase 0 - Baseline**

- **UI-0 Baseline and docs.** Create the branch and tag if they do not already exist (both existed on 2026-10-04: check rather than recreate). Run `uv run pytest`; record the pass count in the logbook. Add `.gitignore` entries for `web/node_modules`, `web/dist`, `web/public/py`. Verify: baseline green; `UISpec.md`, `deploymentConstrains.md`, `AISpec.md` and `UI-prd.json` present in `Specification/`.

**Phase 1 - Python in the browser, no UI**

- **UI-1 Pyodide compatibility gate.** Create a minimal `web/package.json` (only the pinned `pyodide` npm package; the Vite scaffold is UI-6) and, in `web/scripts/pyodide-gate/`, a Python scenario `scenario.py` plus a Node runner `run-gate.mjs`. The runner loads numpy, installs `archeryutils` and `fpdf2`, unpacks the existing whitelisted h2h modules (`bridge.py` and `draw.py` do not exist yet), and runs `scenario.py`: a scripted 4-archer event end to end using the existing modules directly (`rotation` schedule, `models.Event`, `record_match`, `advance`, the leaderboard builder, both CSVs, the PDF, one `chart_data` payload), printing one JSON result. The same `scenario.py` run natively with `uv run` produces `golden.json`; compare the two. Keep these files (they are not deleted without owner approval). Verify: all values match (ints and strings exactly, floats within a relative tolerance of 1e-9; record any larger numeric differences caused by the older Pyodide numpy and report them before continuing). **Stop and report to the owner if this gate fails.**
- **UI-2 Document and replay.** Implement the event document schema, `rebuild_event`, and `validate_document` in `h2h/bridge.py`. Verify: pytest golden tests: an event built through the legacy `SessionState` path and the same inputs replayed from a document produce identical `Event.results`; replay after correcting a score, after sit-out schedules, with and without handicap updating.
- **UI-3 Draw refactor.** Extract the Stage 3 draw logic (including the pairings-signature comparison) from `SessionState.redraw_pairings` into a pure function in the new module `h2h/draw.py` (decision D17), called by `SessionState` now and by the bridge in UI-4. Add `tests/test_draw.py` testing the function directly, so the draw stays covered after `test_state.py` is retired in UI-22. Verify: `tests/test_state.py` and the Flask tests unchanged and green; `tests/test_draw.py` green; the same seed gives the same assignment through `SessionState` and through the function.
- **UI-4 Bridge commands.** Implement every command in section 5.4 with the `ok/error` envelope. Verify: new `tests/test_bridge.py` covers each command (happy path, validation errors with the existing messages, `tiebreak_required`, state errors) and asserts every output passes `json.dumps(..., allow_nan=False)`. Port relevant assertions from `tests/test_event_routes.py` and `tests/test_integration.py` as bridge-level tests.
- **UI-5 Parity fixtures.** Generate golden outputs for several scripted scenarios (simple and advanced setup, odd archers with byes shot and not shot, handicap updating, a tie-break, a final complete event) from native Python, plus a set of `calculator` cases (indoor with and without compound, outdoor, and one invalid input) used by UI-10. Use a fixed draw seed and a fixed `now_iso`. Verify: committed fixtures; a pytest test regenerates and compares them.

**Phase 2 - Front-end foundation**

- **UI-6 Web scaffold.** Vite + React + TypeScript + Mantine with the official setup, ESLint, Prettier, Vitest, Playwright. Build script for the Python bundle. Verify: `npm run build` succeeds from a clean checkout; bundle contains only the whitelisted modules.
- **UI-7 Engine worker and client.** Module Web Worker with Pyodide, typed `call(command, payload)` wrapper with request ids, timeouts, load-progress events, and restart on crash. Verify: Vitest (Node Pyodide) runs the UI-5 fixtures through the client and matches; the first-load transfer size is measured and logged (target about 11 MB or less, report if over), together with the engine start time and the part of it spent loading fpdf2 (decision D16).
- **UI-8 Storage layer.** IndexedDB wrapper, revisioned atomic writes (storage sets `revision` and `updated_at`, D12), index (kept in step with every write, rename and delete), rename, drafts, session route, settings, backup export and import with `validate_document` and the 10 MB limit (D18), storage-failure state. Verify: Vitest with `fake-indexeddb` for write conflicts, corrupt values, quota failure, import validation, rename updating the index.
- **UI-9 App shell.** AppShell, navbar, header (including rename), save indicator, theme toggle, hash router, guards, Home (including Rename and the corrupt-value recovery from section 6), Resume prompt (D13), About, `404.html`. Verify: Playwright: a guarded route redirects; Resume appears after reopening the tab and restores the last route; unknown hash goes Home; rename shows on Home and in the header after a reload.

**Phase 3 - Setup and calculator**

- **UI-10 Handicap calculator** (route and drawer). Verify: results equal the UI-5 calculator fixtures; invalid input shows existing messages.
- **UI-11 Stage 1.** Verify: Playwright: divisor snapping behaves as the old script; byes control shows only for odd counts of 3 or more; draft survives a reload; validation messages match.
- **UI-12 Stage 2.** Both modes, row cards on mobile, updating options, row-level errors, draft persistence, calculator drawer. Verify: a rejected submit keeps every typed value; advanced mode requires target fields.
- **UI-13 Stage 3.** Redraw and confirm. Verify: redraw changes pairings when possible; the draw survives a reload; confirm starts the event and locks setup.

**Phase 4 - Scoring**

- **UI-14 Pass overview.** Verify: Advance disabled until complete; confirm modal; final pass shows completion with the backup reminder and "Download backup" (section 6, rule 7); the stored status becomes `complete` (D11).
- **UI-15 Match view without chart.** Score entry, validation, tie-break flow, bye match, this-pass table. Verify: Playwright reproduces tie-break scenarios from `test_event_routes.py`; reload mid-entry restores the draft; saved scores survive closing and reopening the tab.
- **UI-16 Chart.** Port `match_chart.js`; Graph view switch; previous-passes checkbox; explanation. Verify: new Vitest unit tests for marker-label placement using `chart.markerLabelBoxes` (no existing tests use it): labels do not overlap one another, sit beside their marker line, and stay inside the chart area; visual check at desktop and phone widths in both colour schemes; chart payload comes only from `pair_chart`.

**Phase 5 - Results and exports**

- **UI-17 Results tabs.** Leaderboard, Pairwise (with chart modal), Passes, Archers. Verify: displayed values equal the bridge output exactly (no reformatting in TypeScript).
- **UI-18 Exports.** CSV and PDF through the bridge and a `Blob` download; export time from the browser clock. Verify: Playwright downloads; file names and contents match the fixtures except for the timestamp; PDF opens (check `%PDF-` header and use the existing `pypdf` dev dependency in a Python test of the bridge export).

**Phase 6 - Polish and hardening**

- **UI-19 Responsive and accessibility pass.** Verify against section 7.4 and 7.5 using Playwright mobile and WebKit projects plus an automated accessibility scan (`@axe-core/playwright`); zero serious and zero critical violations.
- **UI-20 Resilience tests** (after UI-19, so the Phase 6 review covers both). Close and reopen the tab at each stage and mid-score; force-reload during a command; two-tab conflict; storage-disabled mode; engine failure. Verify: no scenario loses a saved score; every failure shows the specified message.

**Phase 7 - Deployment**

- **UI-21 CI and GitHub Pages** (after the Phase 6 review). `ci.yml` runs pytest, Vitest, build, and Playwright on every push and pull request, with network access for Pyodide and its packages (D15); `pages.yml` builds and deploys on `main` only. Vite `base` must work under `/<repo-name>/` (relative base). The agent verifies locally first: the same commands as `ci.yml` pass, and the production build served from a `/Handicapped-H2Hs/` sub-path runs a full event in Playwright. Pushing the branch and merging to `main` are the owner's actions: the agent then stops and asks. Verify (after the owner pushes and merges): CI green on GitHub; deployed site loads from the Pages URL, runs a full event, exports files, and survives a reload; record first-load size and time.
- **UI-22 Retire the Flask UI (only after the owner approves in chat).** Delete (the `prototype-flask` tag and git history keep them) `app.py`, `state.py`, `templates/`, `static/`, `main.py`, `tests/helpers.py`, `test_app.py`, `test_event_routes.py`, `test_integration.py` and `test_state.py`. In `test_handicap_calculator.py`, delete only the Flask route tests and keep the tests of the pure lookup functions. Before deleting each test file, record in the logbook which bridge, draw or e2e tests cover its behaviours; anything not covered is ported first. Tests in `test_bridge.py` that compare against the legacy `SessionState` path (UI-2) are changed to build the reference `Event` directly with `models.Event` and the `rotation` builders. Update `README.md`; keep the `prototype-flask` tag. Verify: remaining pytest suite green; no remaining import of Flask in `h2h/` or `tests/`; README run instructions updated; owner sign-off.

## 9. Testing strategy (summary)

| Layer | Tool | What it proves |
|---|---|---|
| Core logic | existing pytest (unchanged) | Statistics and rules untouched |
| Bridge | pytest (`tests/test_bridge.py`) and golden fixtures | Contract, error codes, JSON safety, replay equals legacy |
| Pyodide parity | Vitest in Node with the `pyodide` package | Browser Python gives the same numbers as native Python (within tolerance) |
| Components and storage | Vitest, Testing Library, `fake-indexeddb` | Forms, guards, autosave, conflicts |
| End to end | Playwright (Chromium, WebKit, mobile emulation) | Full event, resume after closing, tie-break, exports, responsive layout |
| Manual | One real phone (Android and iOS if possible) | Memory, downloads, touch targets |

## 10. Definition of done

1. A complete event (simple and advanced, odd and even archers, handicap updating on and off, tie-break) runs in the browser with outputs identical to the Flask app's for the same inputs.
2. Closing, reloading or crashing the tab at any moment loses no saved score, and the app resumes at the right place.
3. CSV and PDF exports download and match the legacy content.
4. The site is deployed on GitHub Pages and works on a laptop and a phone.
5. All existing Python tests pass (or, after UI-22, the remaining ones), new bridge, unit and end-to-end tests pass in CI.
6. `README.md` describes the new run, test and deploy steps; the logbook records assumptions and results.

## 11. Risks and open items

- **Pyodide numeric drift.** Pyodide's numpy is older than the local pin; tolerance-based parity tests (UI-1, UI-5) catch this early.
- **Replay cost.** Rebuilding an `Event` re-runs root finding for equivalent handicaps; measure on a 12-archer, 12-pass scenario on a mid-range phone and cache by `(id, revision)` if needed.
- **First load.** About 11 MB expected once scipy and pandas are excluded (estimate from earlier measurements; verify in UI-7). Phone data use and startup time are the main user-visible costs.
- **iOS Safari.** Memory limits and storage eviction (data can be removed after a long period without visits); backups and the "Download backup" prompts are the mitigation. Test on a real device.
- **Mantine and Pyodide version drift.** Pin both; upgrade deliberately, with tests.
- **Module Web Worker loading of Pyodide.** Confirm the supported pattern in current Pyodide docs during UI-1/UI-7.
- **Dependency housekeeping** (removing scipy, pandas, notebook from `pyproject.toml`): not part of this plan (D16); ask the owner first; `notebook` is used by `Initial Testing/examples.ipynb`. Flask itself stays a dependency until the owner decides after UI-22.
- **Event retention:** resolved as decision D14 (keep until the user deletes them). The owner may still choose auto-archiving later.

## 12. Out of scope and rules for the agent

- Do not change statistics, rules or output wording. If a UI need seems to require changing `stats.py`, `models.py`, `outputs.py` or `rotation.py`, stop and ask. No core module edits are planned: UI-3 changes only `state.py` and adds `draw.py` (D17), and `exports.py` imports `fpdf` lazily (D16, approved by the owner).
- Do not add a server, accounts, analytics, error-reporting services, or third-party scripts and fonts that transmit user data.
- Do not add features not in `AISpec.md` or this document (for example name uniqueness rules, new scoring modes, charts beyond the pair chart).
- Do not use `pip` or `conda`; do not commit `node_modules`, build output, or the generated Python bundle.
- Ask the owner before deleting any existing file or test; the Flask UI stays until UI-22.
- When something here conflicts with what the code actually does, trust the code, flag the discrepancy in the logbook, and continue with the safest interpretation.
