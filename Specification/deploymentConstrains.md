# Deployment constraints: static site with Python in the browser (Pyodide) on GitHub Pages

Audience: the AI agent designing the UI, front-end, and dependencies of the deployed app.
Status: these are requirements, not suggestions, unless marked "recommended" or "open item".

## 1. Context

- The app (`handicapped-h2hs`) is currently a Flask prototype. Flask was chosen only to get a minimum viable app running; the UI will be substantially redesigned.
- The final app will be deployed as a free **static website on GitHub Pages**. There will be **no backend server**.
- All Python (archeryutils calculations, data processing, PDF/CSV export) will run **in the user's browser via Pyodide** (CPython compiled to WebAssembly).
- Usage profile: roughly 20 users in total, at most 5 concurrent. User data is **private to each user**. Nothing is shared between users.
- Interaction pattern: batch, not keystroke-live. The user submits a set of inputs, calculations run, outputs are displayed, and this repeats several times before final outputs. At the end of a session the user exports **PDF and CSV** files.
- The Flask app is a throwaway prototype. Do not preserve Flask routes, templates, or server-side session handling in the deployed design. The prototype's multiple `.html` pages become views of a single-page app (section 3, rule 7).
- An "event" is a multi-step session. It must survive accidental tab closure, reloads, and crashes by being saved to browser storage continuously (section 3, rule 4).
- The app must work on phones as well as laptops.

## 2. Verified compatibility (tested 2026-10-03)

A smoke test was run in a browser using Pyodide `v314.0.7` loaded from `https://cdn.jsdelivr.net/pyodide/v314.0.7/full/`, served over plain static HTTP with no special headers.

| Item | Result |
|---|---|
| Python in Pyodide | 3.14.2 |
| numpy / pandas / scipy | 2.4.6 / 3.0.2 / 1.18.0 (Pyodide's own builds, loaded with `pyodide.loadPackage`) |
| archeryutils | 3.0.0, installed with `micropip` (pure-Python wheel, depends only on numpy) |
| fpdf2 | 2.8.9, installed with `micropip` (pulls in pillow and fonttools, both available) |
| archeryutils calculations | `HandicapAGB().score_for_round(30.0, rnd)` and `.handicap_from_score(900, rnd)` worked; round data loads via `load_rounds.WA_outdoor.wa1440_90` |
| scipy | `optimize.brentq` around archeryutils calls worked and agreed with `handicap_from_score` (49.306 vs 49.3055) |
| pandas | DataFrame build and `to_csv` worked |
| fpdf2 | produced valid PDF bytes (`%PDF-` header) entirely in memory |
| Performance | one calculation about 3 ms; 100 handicap calculations about 170 ms (main thread, desktop, warm) |
| Startup | about 9.5 s from page load to "ready" (fast connection, nothing cached) |
| First-load download | 28.6 MB total (details in section 6) |

Not tested (treat as open items, verify early): Web Worker execution, IndexedDB/localStorage persistence, mobile and iOS Safari memory behaviour, and the app's own code. I have not seen the application code, only the dependency list.

Conclusion: the dependency stack (archeryutils, numpy, pandas, scipy, fpdf2) runs under Pyodide. The batch-submit workflow and PDF/CSV export need nothing a browser cannot provide.

## 3. Architecture rules

1. **No server, no network calls to our own backend.** Everything must work as static files. No Flask in the deployed artefact, no `fetch('/api/...')` to a server we run, no API keys or secrets (everything shipped to the browser is public).
2. **Separate core logic from UI.**
   - Put all calculation, validation, and export code in a plain Python package (for example `core/`) that imports **no web framework** and no browser APIs.
   - Public functions take and return plain data (dicts, lists, numbers, strings, `bytes`). They must be JSON-serialisable on the way in and out, so the JS/Python boundary stays simple. Convert numpy and pandas types to native Python types at the boundary.
   - Functions should be stateless (state is passed in), or state must be explicitly serialisable. The UI owns state, not Python module globals. This also keeps the calculation layer testable natively with `pytest`.
3. **Run Pyodide in a Web Worker**, not the main thread, so loading and calculation never freeze the UI. The UI talks to the worker with a small message protocol (request id, function name, JSON args, then result or error). Show a clear loading state during the initial roughly 10 s startup and a visible error state if loading fails (for example offline).
4. **Persistence is browser-only, and an accidental tab close must never lose an event.**
   - **Save on every state change that matters, not at the end.** After every submit-and-calculate cycle (and after any edit to event setup), write the full event state to browser storage before showing the result. Closing the tab, a browser crash, a phone killing the tab, or a page reload at any moment must lose at most the input the user was currently typing (and ideally not even that: save drafts of in-progress form input on a short debounce).
   - **The UI-side event state is the single source of truth**, held as one serialisable object and mirrored to storage. Python holds no state between calls (rule 2), so a restarted Pyodide worker loses nothing.
   - **Resume on load.** On startup, check storage for an in-progress event. If found, restore it and take the user back to where they were (the view and step), with a clear "Resume event" prompt that also offers "Start new event" (confirm before discarding). Never silently overwrite or discard a saved in-progress event.
   - Store data in IndexedDB (recommended for structured data) or localStorage (acceptable for small data). Writes should be atomic (write the whole new state in one transaction; do not leave half-written state). Keep the previous good state until the new write succeeds. Include a schema version field and a migration path.
   - Support **multiple saved events** or at least completed-vs-in-progress events, and let users delete old ones.
   - Request **persistent storage** with `navigator.storage.persist()` where available, which reduces the chance of the browser evicting data under storage pressure. It is a request that the browser may refuse, so do not rely on it.
   - Provide **export/import of a full backup as JSON**, including a prompt to export when an event is completed. Browser storage can be cleared by the user or the browser (Safari may delete site data after a period without visits), and data does not sync between devices. Tell users this in the UI.
   - Do not rely on Pyodide's in-memory filesystem for persistence. It is lost on page reload.
   - Handle storage failure gracefully (private browsing, quota, disabled storage). If saving fails, show a persistent warning that the event is **not** being saved and prompt the user to export a backup, rather than failing silently.
   - Optionally add a `beforeunload` warning when there are unsaved edits, but do not use it as the main protection. It is unreliable on mobile.
5. **Exports are generated client-side.**
   - Python builds the PDF (`fpdf2`) and CSV in memory and returns `bytes`/`str` to JS. JS offers them via a `Blob` plus a temporary `<a download>` link.
   - Do not write exports to a server or depend on a temp-directory file that outlives the call.
6. **Privacy by construction.** No user data leaves the device. Do not add analytics, error reporting, or fonts/scripts that transmit user data. State this in the UI footer or about page.
7. **Single-page application (SPA), one `index.html`.** The prototype's separate `.html` pages become **views** inside one page, switched by JavaScript.
   - Reason: every navigation to a separate `.html` file reloads the page, which restarts Pyodide (several seconds) and discards in-memory state. In an SPA, Pyodide loads once into one worker and views switch instantly.
   - Use **hash-based routing** (`#/setup`, `#/round/2`, `#/results`) so refresh, back/forward, and bookmarks work. GitHub Pages has no SPA fallback, so history-API routing (`/results`) would 404 on refresh.
   - **Guard every route against missing state.** If someone opens `#/results` with no matching saved event, redirect to the start view with a short message. Unknown hashes also fall back to the start view.
   - Provide a root-level **`404.html`** with a friendly message and a link back to the app, for invalid real URLs. GitHub Pages serves it automatically for missing paths.
   - The site is served under `/<repo-name>/` unless a custom domain is used, so **use relative asset URLs**, not root-absolute ones (`/static/...`).
   - Views must be **responsive**, usable at phone widths as well as on a laptop (see section 9).
   - The loading state during first startup must not block read-only use of saved data where possible (for example, show a saved event's stored results while the worker starts).
8. **Build and deploy** as static output only, deployed with a GitHub Actions workflow to GitHub Pages. Any front-end toolchain is acceptable (plain JS, Vite, a framework) provided the output is static files. No server-side rendering.

## 4. Dependency rules

1. **Browser runtime dependencies are only:** packages bundled with Pyodide (loaded with `loadPackage`), or pure-Python wheels from PyPI (installed with `micropip`). Anything with compiled extensions not shipped with Pyodide will not work.
2. **Pin the Pyodide version explicitly** in code and in a README note (currently `v314.0.7`, Python 3.14). Never use a floating "latest". Upgrading Pyodide changes the Python, numpy, pandas, and scipy versions, so treat it as a deliberate change that needs retesting.
3. **Version mismatch with the local environment.** The prototype's `pyproject.toml` pins higher versions (`numpy>=2.5.3`, `pandas>=3.0.5`, `scipy>=1.18.1`) than Pyodide provides (2.4.6, 3.0.2, 1.18.0). Consequences:
   - Do **not** `micropip.install` the app with its `pyproject.toml` pins. Resolution will fail or fight Pyodide's builds.
   - Load the app's own Python package into Pyodide as plain source files or a zip (`pyodide.unpackArchive` or writing files into the Pyodide filesystem), or as a pure-Python wheel installed with `deps=False`.
   - Keep the **browser** dependency list separate from the **local dev** list, with loose lower bounds (for example `numpy>=2.0`) in anything the browser build reads.
   - Run the tests against **both** native Python (pytest) and Pyodide, because numerical results or API behaviour could differ across versions.
4. **Remove `notebook` from the runtime dependencies** (dev only, not used in the browser). `pypdf` and `pytest` stay in the dev group.
5. **Avoid in browser code:** `flask`, `requests`/`urllib` to external hosts (use JS `fetch` or `pyodide.http`, and expect CORS limits), `threading`/`multiprocessing`, `subprocess`, sockets, blocking `time.sleep`, and any dependence on the real filesystem.
6. **Prefer pure-Python or Pyodide-bundled packages when adding anything new.** Before adding a library, check it is in [Pyodide's package list](https://pyodide.org/en/stable/usage/packages-in-pyodide.html) or has a `py3-none-any` wheel on PyPI.
7. Follow the user's coding conventions in all Python: docstrings on every function covering purpose, argument names/types/structure, and return type/structure. Keep dev tooling on `uv`.

## 5. Size and loading budget

Measured first-load download (compressed bytes transferred): **28.6 MB**. The largest items:

| Package | Approx. size |
|---|---|
| scipy | 13.5 MB |
| pandas | 4.1 MB |
| Pyodide core (wasm) | 3.4 MB |
| numpy | 2.9 MB |
| Python stdlib zip | 2.4 MB |
| fonttools + pillow (fpdf2 dependencies) | about 2.1 MB |

Guidance:

- Browsers cache these files, so repeat visits are much faster (repeat-load timing was not measured).
- **Recommended:** check whether `scipy` and `pandas` are actually essential. In the smoke test, `scipy.optimize.brentq` merely duplicated what archeryutils's `handicap_from_score` already does. If the final app only uses them for trivial tasks, dropping them cuts the download from about 29 MB to about 11 MB and reduces memory use. Pure-Python `csv` can replace `DataFrame.to_csv` for simple exports.
- If scipy or pandas are kept, **load them lazily** (only when a view needs them), and load numpy plus archeryutils first so the app becomes usable sooner.
- Show progress during loading. GitHub Pages limits (1 GB site, 100 GB/month soft bandwidth) are not a concern at about 20 users. If Pyodide is loaded from jsDelivr, those downloads do not count against GitHub bandwidth. Self-hosting Pyodide inside the repo is possible but would use repo and site size.

## 6. GitHub Pages terms to respect

Per [GitHub's published limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits): published site at most 1 GB, soft bandwidth limit 100 GB/month, soft limit of 10 builds per hour (not applicable with a custom Actions workflow). Pages must not be used as free hosting for commercial purposes (e-commerce, SaaS), and sites should not handle sensitive data such as passwords or payment details. This app (free, local-only, no accounts) is consistent with that, but do not add logins, payments, or commercial features without revisiting the hosting choice.

Open question for the user: whether the free GitHub plan allows Pages from a private repository (not confirmed). Assume a public repository unless told otherwise. Do not commit anything private to it.

## 7. Suggested structure (adapt as needed)

```
repo/
  core/                  # pure Python, no web imports, plain-data in/out
    __init__.py
    calculations.py
    exports.py           # returns CSV text and PDF bytes
  web/                   # static front end (HTML/JS/CSS or built output)
    index.html           # the single page; all views live here
    404.html             # friendly fallback for invalid URLs
    worker.js            # loads Pyodide, loads core/, exposes message API
    storage.js           # IndexedDB wrapper, autosave, resume, JSON backup/restore
    router.js            # hash routing + route guards
    ui/...               # one module per view
  tests/                 # pytest on core/; plus a Pyodide smoke test
  pyodide-requirements.txt   # loose, browser-only
  pyproject.toml         # local dev (uv), may stay stricter
  .github/workflows/pages.yml
```

Worker message sketch: `{id, fn: "calculate_round", args: {...}}` then `{id, ok: true, result: {...}}` or `{id, ok: false, error: "..."}`.

## 8. Testing expectations

1. `pytest` on `core/` natively, as now.
2. A Pyodide smoke test run in CI (for example with the `pyodide` npm package under Node, or a headless browser) that loads `core/` against the pinned Pyodide and runs the main calculations and both exports. This catches version drift.
3. Persistence tests (automated where possible): close and reopen the tab mid-event and confirm the event resumes at the right view with no lost cycles; reload during a calculation; simulate a failed storage write and confirm the warning appears; confirm backup export then import restores an identical event; confirm opening a hash route with no saved event redirects safely.
4. Manual checks before release: Chrome, Firefox, Safari, plus one real phone (Android and iOS if possible). Verify memory behaviour on iOS Safari if scipy and pandas are retained (unverified risk), IndexedDB persistence across reloads, force-quitting the browser mid-event, and PDF/CSV downloads (on iOS these open in a viewer or share sheet rather than saving directly).

## 9. Open items to resolve early

1. Confirm a Web Worker can load Pyodide and the app package under the chosen front-end tooling.
2. Confirm which pandas/scipy features the app actually needs (see section 5).
3. Measure calculation time on a mid-range phone, since desktop timings above are optimistic.
4. Decide the storage schema and its versioning/migration approach, including how "current view and step" is stored for resume.
5. Phone considerations (not yet tested): first load of 29 MB over mobile data is slow, phone CPUs are several times slower than the desktop timings in section 2, and iOS Safari may kill tabs that use a lot of memory. Layouts must be responsive, and the autosave rule above is what makes a killed tab recoverable.
6. Decide whether to self-host Pyodide or use the jsDelivr CDN (CDN is simpler; self-hosting removes a third-party dependency at the cost of repo size).
