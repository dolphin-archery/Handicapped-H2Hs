You are implementing the web UI described in `Specification/UISpec.md`, one task at a time, from `Specification/UI-prd.json`. The input parameter `N` is the maximum number of iterations to run in this session.

## Before the first iteration

1. Confirm you are on the UI branch (not `main`): run `git branch --show-current`. If it is `main`, stop and tell me. Never commit to `main`, merge, rebase, force-push or push without being asked.
2. Confirm the working tree is clean (`git status`). If it is not, stop and tell me what is uncommitted.

## Every iteration

Context may have been reset since the last iteration, so start by re-reading, in this order:
`Specification/UISpec.md`, `Specification/deploymentConstrains.md`, `README.md`, and the most recent entries of `Specification/logbook.md`. The UISpec governs the UI and architecture; `Specification/AISpec.md` section 5 governs behaviour and is never overridden.

Then:

1. **Choose the task.** Take the **first task in file order whose `completed` is false and whose `depends_on` tasks are all completed**. Do not skip ahead or reorder by your own priority. If no task is eligible, stop and say why.
2. **Break it down if it is large.** Split it into small sub-steps and complete them one at a time. Use subagents where possible, for example for independent investigation or test writing, but you remain responsible for the result. Do not use the same model an effort level as the main task unless the subtask is very complex. Use a smaller model and/or a lower effort level.
3. **Implement it** following the task's `description` and the UISpec sections it cites. Rules that always apply:
   - Python: `uv` only (never `pip` or `conda`); numpy-style docstrings on every function added or changed; surgical edits; do not change statistics, rules or output wording; do not edit `stats.py`, `models.py`, `outputs.py` or `rotation.py` except where a task explicitly says so.
   - Front end: Mantine components first (use the Mantine MCP server for component APIs and check current docs; pin versions); no server, no analytics, no third-party scripts or fonts that transmit user data; the UI shows values from the Python bridge and never recomputes or reformats statistics.
   - Do not delete existing files or tests, or change `pyproject.toml` dependencies, unless the task explicitly says so and I have approved it in chat.
4. **Verify.** Every listed test in the task must pass, and you must also run the full checks below. Fix failures; do not weaken, skip or delete tests to get green.
   - `uv run pytest` (the existing suite must stay green, plus any new tests)
   - From `web/`: type check, lint, `npm test` (Vitest) and `npm run build` once those exist
   - Playwright end-to-end tests for the task once they exist
   - **For any task that changes what the user sees:** start the app, drive it with Playwright (or the built-in browser), take screenshots at 1440x900 and 390x844 in light and dark mode, look at them, and note in the logbook what you saw and anything you fixed. A UI task is not verified by passing tests alone.
5. **Record progress** in `Specification/logbook.md`: a brief entry with the task id, what changed, how it was verified (commands run and results, screenshots reviewed), any issues, assumptions, and notes for future tasks. Log any discrepancy you find between UISpec and the real code under a "Spec discrepancies" heading, with the safest interpretation you took. Do not silently edit `UISpec.md`, `deploymentConstrains.md` or `AISpec.md`; propose changes to me instead.
6. **Update `UI-prd.json`**: set `completed` to true for the task only once everything in steps 4 and 5 is done.
7. **Commit** this task's work with a short, informative message that starts with the task id (for example `UI-11: Stage 1 form with divisor-snapping slider`). Commit regularly within a task if it is large. Do not commit `node_modules`, `web/dist`, or the generated Python bundle.
8. **Compact** the conversation using the `/compact` skill to avoid stored context becoming large and costly to usage limits over large runs.

## When to stop (finish the current iteration cleanly, then stop and report)

- **A task with `"needs_review": true` has just been completed.** Summarise what was built and how to run it, list anything I should look at, and wait for me. Do not start the next phase.
- **A task with `"gate": true` fails its verification.** Do not work around it or continue to later tasks. Report exactly what failed, with output, and your assessment.
- **You are blocked**: the same problem has resisted two serious attempts, a required tool or service is unavailable, or the task conflicts with the specification or the code. Write the details in the logbook, leave the task incomplete, and stop.
- **A decision is needed from me**: anything that touches a core file outside what a task allows, deleting files, changing dependencies in `pyproject.toml`, retiring the Flask UI (task UI-22), or choosing between two reasonable designs not settled by the spec.
- **All tasks have `completed` true**: summarise the final state against the Definition of Done in `UISpec.md` section 10 and tell me the work is complete.
- You have run `N` iterations.

At the end of the session (for any stop reason), give me a short report: tasks completed, tasks in progress or blocked, commands I can run to see the current state, and any open questions.
