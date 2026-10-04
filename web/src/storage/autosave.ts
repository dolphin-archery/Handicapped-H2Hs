/**
 * Device records kept beside the event documents (UISpec.md section 6): unsaved form drafts
 * (`draft:<id>`, written on a short debounce and discarded when the command succeeds, rule 8),
 * the last route of each event (`session:<id>`, for Resume, rule 4) and device settings
 * (`settings`: colour scheme, graph view and the last opened event; decisions D5 and D8).
 *
 * These are conveniences: a failed read gives the default and a failed write returns false
 * without changing the save status, which tracks the event documents only.
 */
import { draftKey, isRecord, sessionKey, SETTINGS_KEY, type EventStore } from "./db";

/** Debounce delay for drafts, in ms (UISpec.md section 6: "about 500 ms"). */
export const DRAFT_DELAY_MS = 500;

export type ColorScheme = "light" | "dark" | "auto";

export interface Settings {
  color_scheme: ColorScheme;
  graph_view: boolean;
  last_event_id: string | null;
}

export const DEFAULT_SETTINGS: Readonly<Settings> = {
  color_scheme: "auto",
  graph_view: false,
  last_event_id: null,
};

const COLOR_SCHEMES: readonly unknown[] = ["light", "dark", "auto"] satisfies ColorScheme[];

/**
 * An event's unsaved form draft.
 *
 * @param store - The storage layer.
 * @param eventId - The event id.
 * @returns The draft as it was stored, or undefined if there is none.
 */
export function getDraft(store: EventStore, eventId: string): Promise<unknown> {
  return store.getValue(draftKey(eventId));
}

/**
 * Store an event's form draft at once (the `DraftSaver` debounces this).
 *
 * @param store - The storage layer.
 * @param eventId - The event id.
 * @param draft - The form's values (any JSON value).
 * @returns True if it was stored.
 */
export function setDraft(store: EventStore, eventId: string, draft: unknown): Promise<boolean> {
  return store.putValue(draftKey(eventId), draft);
}

/**
 * Discard an event's draft, after the command it was for succeeded (UISpec.md section 6, rule 8).
 *
 * @param store - The storage layer.
 * @param eventId - The event id.
 * @returns True if the delete succeeded (also when there was no draft).
 */
export function deleteDraft(store: EventStore, eventId: string): Promise<boolean> {
  return store.deleteValue(draftKey(eventId));
}

/** Writes an event's draft once the form has been still for `delayMs`. */
export class DraftSaver {
  private readonly store: EventStore;
  private readonly eventId: string;
  private readonly delayMs: number;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private pending: { draft: unknown } | null = null;

  /**
   * @param store - The storage layer.
   * @param eventId - The event whose draft this saves.
   * @param delayMs - The debounce delay (default `DRAFT_DELAY_MS`).
   */
  constructor(store: EventStore, eventId: string, delayMs: number = DRAFT_DELAY_MS) {
    this.store = store;
    this.eventId = eventId;
    this.delayMs = delayMs;
  }

  /**
   * Save this draft after the delay, replacing any draft still waiting.
   *
   * @param draft - The form's current values.
   */
  schedule(draft: unknown): void {
    this.pending = { draft };
    clearTimeout(this.timer);
    this.timer = setTimeout(() => void this.flush(), this.delayMs);
  }

  /**
   * Write the waiting draft now (e.g. when the form unmounts).
   *
   * @returns True if it was stored or nothing was waiting.
   */
  flush(): Promise<boolean> {
    clearTimeout(this.timer);
    this.timer = undefined;
    const pending = this.pending;
    this.pending = null;
    return pending === null
      ? Promise.resolve(true)
      : setDraft(this.store, this.eventId, pending.draft);
  }

  /** Drop the waiting draft without writing it (call before `deleteDraft` once a command succeeds). */
  cancel(): void {
    clearTimeout(this.timer);
    this.timer = undefined;
    this.pending = null;
  }
}

/**
 * The route the user was last on in an event, for Resume.
 *
 * @param store - The storage layer.
 * @param eventId - The event id.
 * @returns The route (e.g. "/event/<id>/pass"), or null if none is stored.
 */
export async function getSessionRoute(store: EventStore, eventId: string): Promise<string | null> {
  const route = await store.getValue(sessionKey(eventId));
  return typeof route === "string" ? route : null;
}

/**
 * Remember the route the user is on in an event.
 *
 * @param store - The storage layer.
 * @param eventId - The event id.
 * @param route - The route.
 * @returns True if it was stored.
 */
export function setSessionRoute(
  store: EventStore,
  eventId: string,
  route: string,
): Promise<boolean> {
  return store.putValue(sessionKey(eventId), route);
}

/**
 * The device settings, with the default for any field that is missing or ill-typed.
 *
 * @param store - The storage layer.
 * @returns The settings.
 */
export async function getSettings(store: EventStore): Promise<Settings> {
  const stored = await store.getValue(SETTINGS_KEY);
  const value = isRecord(stored) ? stored : {};
  return {
    color_scheme: COLOR_SCHEMES.includes(value.color_scheme)
      ? (value.color_scheme as ColorScheme)
      : DEFAULT_SETTINGS.color_scheme,
    graph_view:
      typeof value.graph_view === "boolean" ? value.graph_view : DEFAULT_SETTINGS.graph_view,
    last_event_id:
      typeof value.last_event_id === "string"
        ? value.last_event_id
        : DEFAULT_SETTINGS.last_event_id,
  };
}

/**
 * Change some settings and store them.
 *
 * @param store - The storage layer.
 * @param changes - The fields to change.
 * @returns The merged settings, also when the write failed (so the UI can still apply them
 *   for this visit).
 */
export async function updateSettings(
  store: EventStore,
  changes: Partial<Settings>,
): Promise<Settings> {
  const settings = { ...(await getSettings(store)), ...changes };
  await store.putValue(SETTINGS_KEY, settings);
  return settings;
}
