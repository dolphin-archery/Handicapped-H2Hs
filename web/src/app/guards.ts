/**
 * Route guards for event views (UISpec.md 6 rule 5, 7.1 route table): pure functions of the
 * stored document, so they are unit-tested apart from React.
 */
import type { EventDocument } from "../engine/types";

export const RESULT_TABS = ["leaderboard", "pairwise", "passes", "archers"] as const;
export type ResultTab = (typeof RESULT_TABS)[number];

/** Which event view a route asks for. */
export type EventView =
  | { kind: "setup"; stage: 1 | 2 | 3 }
  | { kind: "pass" }
  | { kind: "match"; index: string }
  | { kind: "results"; tab: string };

/** The guard's verdict: show the view, or go elsewhere with a short notification. */
export type GuardResult = { allowed: true } | { allowed: false; redirect: string; message: string };

export const NOT_STARTED_MESSAGE =
  "The event has not started yet: confirm the pairings at Stage 3 first.";

/**
 * The path of an event's setup stage.
 *
 * @param id - The event id.
 * @param stage - 1, 2 or 3.
 * @returns e.g. "/e/<id>/setup/2".
 */
export function setupPath(id: string, stage: 1 | 2 | 3): string {
  return `/e/${encodeURIComponent(id)}/setup/${stage}`;
}

/**
 * Where an event opens when there is no remembered route: the next setup stage, or the current
 * pass once it has started.
 *
 * @param doc - The stored event document.
 * @returns The route path.
 */
export function eventHomePath(doc: Pick<EventDocument, "id" | "status" | "setup">): string {
  if (doc.status !== "setup") return `/e/${encodeURIComponent(doc.id)}/pass`;
  return setupPath(doc.id, Math.min(doc.setup.stage + 1, 3) as 1 | 2 | 3);
}

/**
 * Check whether a document allows a view.
 *
 * Setup stages need the earlier stages done; they stay reachable after the start, where their
 * views are read-only summaries (UISpec.md 7.3, Stage 3). The pass, match and results views need
 * a started event (status running or complete, decision D11). A results tab must be one of the
 * four; a match index must be a whole number (its range is checked by the bridge's `match`).
 *
 * @param doc - The stored event document.
 * @param view - The requested view.
 * @returns Allowed, or where to go instead and why.
 */
export function guardEventView(
  doc: Pick<EventDocument, "id" | "status" | "setup">,
  view: EventView,
): GuardResult {
  const id = encodeURIComponent(doc.id);
  if (view.kind === "setup") {
    if (view.stage > doc.setup.stage + 1) {
      return {
        allowed: false,
        redirect: setupPath(doc.id, (doc.setup.stage + 1) as 1 | 2),
        message: `Complete Stage ${doc.setup.stage + 1} first.`,
      };
    }
    return { allowed: true };
  }
  if (doc.status === "setup") {
    return { allowed: false, redirect: eventHomePath(doc), message: NOT_STARTED_MESSAGE };
  }
  if (view.kind === "results" && !(RESULT_TABS as readonly string[]).includes(view.tab)) {
    return { allowed: false, redirect: `/e/${id}/results/leaderboard`, message: "" };
  }
  if (view.kind === "match" && !/^\d+$/.test(view.index)) {
    return { allowed: false, redirect: `/e/${id}/pass`, message: "" };
  }
  return { allowed: true };
}

/**
 * Whether the event's setup can no longer be changed: it has started (status running or
 * complete). Setup then shows read-only summaries (UISpec.md 7.3, Stage 3; owner decision after
 * the UI-9 review).
 *
 * @param doc - The event document.
 * @returns True once the event has started.
 */
export function setupLocked(doc: Pick<EventDocument, "status">): boolean {
  return doc.status !== "setup";
}
