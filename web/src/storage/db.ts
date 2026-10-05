/**
 * The IndexedDB storage layer (UISpec.md section 6; decisions D3, D12, D13, D14).
 *
 * One database holds keyed values: `event:<id>` (the whole event document), `events:index` (the
 * Home list), `settings`, `draft:<id>` and `session:<id>`. Every change to an event is one
 * readwrite transaction that checks the revision the UI loaded, replaces the whole document, sets
 * `revision` and `updated_at` (this layer is the only code that sets them, D12) and updates the
 * index, so a failed write leaves the previous document and index as they were. Nothing here
 * throws: every operation returns a result for the UI, and failures also show in `status`.
 *
 * Full document validation is the Python engine's job (`validate_document`, run by the UI when
 * an event is opened); this module only tells a plausible document from a corrupt value.
 */
import { openDB, type IDBPDatabase, type IDBPObjectStore } from "idb";
import type { EventDocument, EventStatus } from "../engine/types";
import { DB_NAME, DB_VERSION, STORE, upgradeDatabase, type StorageSchema } from "./migrations";
import { StatusStore, describeFailure, unavailableFailure, type StorageFailure } from "./status";

export const INDEX_KEY = "events:index";
export const SETTINGS_KEY = "settings";
const EVENT_PREFIX = "event:";
const STATUSES: readonly unknown[] = ["setup", "running", "complete"] satisfies EventStatus[];

/**
 * The key of an event document.
 *
 * @param id - The event id.
 * @returns `event:<id>`.
 */
export function eventKey(id: string): string {
  return `${EVENT_PREFIX}${id}`;
}

/**
 * The key of an event's unsaved form draft.
 *
 * @param id - The event id.
 * @returns `draft:<id>`.
 */
export function draftKey(id: string): string {
  return `draft:${id}`;
}

/**
 * The key of an event's last route.
 *
 * @param id - The event id.
 * @returns `session:<id>`.
 */
export function sessionKey(id: string): string {
  return `session:${id}`;
}

/** One row of `events:index`, the Home list (UISpec.md section 6). */
export interface IndexEntry {
  id: string;
  name: string;
  status: EventStatus;
  updated_at: string;
  n_archers: number;
}

/** A save or rename: the written document, a conflict, or a storage failure. */
export type SaveResult =
  | { status: "saved"; document: EventDocument }
  /**
   * The stored revision is not the one the UI loaded (another tab wrote it). `current` is the
   * stored document, or null when none is stored (deleted elsewhere) or the stored value is
   * corrupt (`loadEvent` then reports it).
   */
  | { status: "conflict"; current: EventDocument | null }
  | { status: "failed"; failure: StorageFailure };

export type LoadResult =
  | { status: "found"; document: EventDocument }
  | { status: "missing" }
  /** Not a plausible event document; `raw` is the stored value, for export before deletion. */
  | { status: "corrupt"; raw: unknown }
  | { status: "failed"; failure: StorageFailure };

export type ListResult =
  { status: "ok"; events: IndexEntry[] } | { status: "failed"; failure: StorageFailure };

export type DeleteResult = { status: "deleted" } | { status: "failed"; failure: StorageFailure };

export type ImportWriteResult =
  | { status: "imported"; document: EventDocument }
  /** A value is already stored under this id and overwriting was not confirmed. */
  | { status: "exists" }
  | { status: "failed"; failure: StorageFailure };

export type ReadValuesResult =
  { status: "ok"; values: unknown[] } | { status: "failed"; failure: StorageFailure };

type KeyvalStore<Mode extends IDBTransactionMode> = IDBPObjectStore<
  StorageSchema,
  [typeof STORE],
  typeof STORE,
  Mode
>;
type Outcome<T> = { ok: true; value: T } | { ok: false; failure: StorageFailure };

/**
 * Whether a value is a plain object (not null, not an array).
 *
 * @param value - Any value.
 * @returns True for an object that can hold named fields.
 */
export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Whether a value is a plausible event document: an object with a whole-number `schema_version`
 * and `revision`, a non-empty string `id`, a known `status` and an object `setup`, plus the
 * fields this layer reads for the index (`name`, `updated_at`, `setup.n_archers`). This only
 * separates documents from corrupt values; `validate_document` does the real checking.
 *
 * @param value - A stored or imported value.
 * @returns True if the value looks like an event document.
 */
export function looksLikeEventDocument(value: unknown): value is EventDocument {
  return (
    isRecord(value) &&
    Number.isInteger(value.schema_version) &&
    typeof value.id === "string" &&
    value.id !== "" &&
    Number.isInteger(value.revision) &&
    STATUSES.includes(value.status) &&
    isRecord(value.setup) &&
    typeof value.setup.n_archers === "number" &&
    typeof value.name === "string" &&
    typeof value.updated_at === "string"
  );
}

/** The storage layer: one IndexedDB connection, opened on first use, and the save status. */
export class EventStore {
  /** Save state for the save indicator and the "This event is NOT being saved" alert. */
  readonly status = new StatusStore();
  private connection: Promise<IDBPDatabase<StorageSchema>> | null = null;
  private persistRequested = false;

  /**
   * The Home list, rebuilt from the `event:*` records if the index is missing or unreadable
   * (corrupt event values are left out of a rebuilt list).
   *
   * @returns The entries, most recently updated first, so the first entry whose status is not
   *   "complete" is the Resume card's event (D13); or a failure.
   */
  async listEvents(): Promise<ListResult> {
    const outcome = await this.transact("readonly", readIndex);
    if (!outcome.ok) return { status: "failed", failure: outcome.failure };
    return { status: "ok", events: [...outcome.value].sort(newestFirst) };
  }

  /**
   * Read one event document.
   *
   * @param id - The event id.
   * @returns "found" with the document, "missing", "corrupt" with the raw stored value (not a
   *   plausible document, or stored under another id), or a failure.
   */
  async loadEvent(id: string): Promise<LoadResult> {
    const outcome = await this.transact("readonly", (store) => store.get(eventKey(id)));
    if (!outcome.ok) return { status: "failed", failure: outcome.failure };
    const raw = outcome.value;
    if (raw === undefined) return { status: "missing" };
    return isStoredDocument(raw, id)
      ? { status: "found", document: raw }
      : { status: "corrupt", raw };
  }

  /**
   * The raw stored values of one or all events (corrupt ones included), for a backup.
   *
   * @param id - One event id, or undefined for every event.
   * @returns The values (empty if the one event is missing), or a failure.
   */
  async readEventValues(id?: string): Promise<ReadValuesResult> {
    const outcome = await this.transact("readonly", async (store): Promise<unknown[]> => {
      if (id === undefined) return store.getAll(eventRange());
      const value = await store.get(eventKey(id));
      return value === undefined ? [] : [value];
    });
    return outcome.ok
      ? { status: "ok", values: outcome.value }
      : { status: "failed", failure: outcome.failure };
  }

  /**
   * Write a whole event document after a command changed it (UISpec.md section 6, rules 1-2).
   *
   * @param doc - The document to store, keyed by `doc.id`.
   * @param expectedRevision - The revision the UI loaded, or null for a brand-new event.
   * @param nowIso - The time to store as `updated_at`.
   * @returns "saved" with the stored document (`revision` one more than the stored one, or
   *   `doc.revision + 1` for a new event; `updated_at` set to `nowIso`); "conflict" if the
   *   stored revision differs, the event was deleted or created elsewhere, or the stored value
   *   is corrupt (nothing is written); or a failure (nothing is written).
   */
  saveEvent(
    doc: EventDocument,
    expectedRevision: number | null,
    nowIso: string,
  ): Promise<SaveResult> {
    return this.writeDocument(doc.id, expectedRevision, nowIso, () => doc);
  }

  /**
   * Change an event's name, the one field the UI edits directly (D12).
   *
   * @param id - The event id.
   * @param name - The new name, stored as given.
   * @param expectedRevision - The revision the UI loaded.
   * @param nowIso - The time to store as `updated_at`.
   * @returns As `saveEvent`: only `name`, `revision` and `updated_at` change.
   */
  renameEvent(
    id: string,
    name: string,
    expectedRevision: number,
    nowIso: string,
  ): Promise<SaveResult> {
    return this.writeDocument(id, expectedRevision, nowIso, (current) =>
      current === null ? null : { ...current, name },
    );
  }

  /**
   * Delete an event with its draft, its last route and its index entry, in one transaction.
   *
   * @param id - The event id.
   * @returns "deleted" (also when there was nothing to delete), or a failure.
   */
  async deleteEvent(id: string): Promise<DeleteResult> {
    const outcome = await this.transact("readwrite", async (store) => {
      await store.delete(eventKey(id));
      await store.delete(draftKey(id));
      await store.delete(sessionKey(id));
      const index = await readIndex(store);
      await store.put(
        index.filter((entry) => entry.id !== id),
        INDEX_KEY,
      );
    });
    return outcome.ok ? { status: "deleted" } : { status: "failed", failure: outcome.failure };
  }

  /**
   * Store an imported, already validated document (UISpec.md section 6, rule 7).
   *
   * A new id is stored exactly as given, keeping the backup's `revision` and `updated_at`, so a
   * restore is identical. An existing id is replaced only when `overwrite` is true, and then gets
   * a `revision` above both the stored and the imported one and `updated_at` = `nowIso`, so a tab
   * still holding the old document sees a conflict.
   *
   * @param doc - The document returned by `validate_document`.
   * @param overwrite - True only if the user confirmed replacing an existing event with this id.
   * @param nowIso - The time to store as `updated_at` when overwriting.
   * @returns "imported" with the stored document, "exists" (nothing written), or a failure.
   */
  async importEvent(
    doc: EventDocument,
    overwrite: boolean,
    nowIso: string,
  ): Promise<ImportWriteResult> {
    const outcome = await this.transact("readwrite", async (store) => {
      const stored = await store.get(eventKey(doc.id));
      if (stored !== undefined && !overwrite) return { status: "exists" } as const;
      const document =
        stored === undefined
          ? doc
          : {
              ...doc,
              revision: Math.max(storedRevision(stored), doc.revision) + 1,
              updated_at: nowIso,
            };
      await putDocument(store, document);
      return { status: "imported", document } as const;
    });
    if (!outcome.ok) return { status: "failed", failure: outcome.failure };
    if (outcome.value.status === "imported") this.requestPersistence();
    return outcome.value;
  }

  /**
   * Read a device record (`settings`, `draft:<id>`, `session:<id>`); see autosave.ts. Event
   * documents and the index are read through the event methods only.
   *
   * @param key - The record's key.
   * @returns The stored value, or undefined if there is none or storage failed.
   */
  async getValue(key: string): Promise<unknown> {
    const outcome = await this.transact("readonly", (store) => store.get(key));
    return outcome.ok ? outcome.value : undefined;
  }

  /**
   * Write a device record (`settings`, `draft:<id>`, `session:<id>`); never an event or the
   * index, which change through the event methods only (D12).
   *
   * @param key - The record's key.
   * @param value - Any structured-cloneable value (JSON in practice).
   * @returns True if it was stored.
   */
  async putValue(key: string, value: unknown): Promise<boolean> {
    return (await this.transact("readwrite", (store) => store.put(value, key))).ok;
  }

  /**
   * Delete a device record (`settings`, `draft:<id>`, `session:<id>`).
   *
   * @param key - The record's key.
   * @returns True if the delete succeeded (also when there was nothing to delete).
   */
  async deleteValue(key: string): Promise<boolean> {
    return (await this.transact("readwrite", (store) => store.delete(key))).ok;
  }

  /** Close the connection; the next operation opens a new one. */
  close(): void {
    const connection = this.connection;
    this.connection = null;
    connection?.then(
      (db) => db.close(),
      () => undefined,
    );
  }

  /**
   * The shared write path of save and rename: check the revision, write, update the index and
   * the status, all-or-nothing. A failed write leaves the document it was writing in the failed
   * status (`unsaved`).
   *
   * @param id - The event id.
   * @param expectedRevision - The revision the UI loaded, or null for a brand-new event.
   * @param nowIso - The time to store as `updated_at`.
   * @param change - Builds the document to write from the stored one (null when none is
   *   stored); returning null reports a conflict.
   * @returns The save result.
   */
  private async writeDocument(
    id: string,
    expectedRevision: number | null,
    nowIso: string,
    change: (current: EventDocument | null) => EventDocument | null,
  ): Promise<SaveResult> {
    const previous = this.status.getSnapshot();
    this.status.set({ state: "saving" });
    const outcome = await this.transact("readwrite", async (store): Promise<SaveResult> => {
      const stored = await store.get(eventKey(id));
      const current = isStoredDocument(stored, id) ? stored : null;
      const unchanged =
        stored === undefined ? expectedRevision === null : current?.revision === expectedRevision;
      const next = unchanged ? change(current) : null;
      if (next === null) return { status: "conflict", current };
      const revision = (current?.revision ?? next.revision) + 1;
      const document: EventDocument = { ...next, revision, updated_at: nowIso };
      await putDocument(store, document);
      return { status: "saved", document };
    });
    if (!outcome.ok) {
      // Keep what could not be written, for "Download backup" (a rename needs the stored copy,
      // so it has none).
      const unsaved = change(null) ?? undefined;
      this.status.set({ state: "failed", ...outcome.failure, unsaved });
      return { status: "failed", failure: outcome.failure };
    }
    if (outcome.value.status === "saved") {
      this.status.set({ state: "saved", savedAt: nowIso });
      this.requestPersistence();
    } else {
      this.status.set(previous);
    }
    return outcome.value;
  }

  /**
   * Run one transaction on the store. Any error aborts it, so nothing it wrote is kept.
   *
   * @param mode - "readonly" or "readwrite".
   * @param body - The work; it must only await requests on `store` (awaiting anything else
   *   would let the transaction commit early).
   * @returns The body's value once the transaction has committed, or the failure (an
   *   "unavailable" failure if the database cannot be opened, which also sets `status`).
   */
  private async transact<T, Mode extends "readonly" | "readwrite">(
    mode: Mode,
    body: (store: KeyvalStore<Mode>) => Promise<T>,
  ): Promise<Outcome<T>> {
    let db: IDBPDatabase<StorageSchema>;
    try {
      db = await this.open();
    } catch (error) {
      this.connection = null;
      const failure = unavailableFailure(error);
      this.status.set({ state: "failed", ...failure });
      return { ok: false, failure };
    }
    try {
      const tx = db.transaction(STORE, mode);
      // `done` is awaited below; this only stops an abort being reported as unhandled.
      tx.done.catch(() => undefined);
      try {
        const value = await body(tx.store);
        await tx.done;
        return { ok: true, value };
      } catch (error) {
        abortQuietly(tx);
        throw error;
      }
    } catch (error) {
      return { ok: false, failure: describeFailure(error) };
    }
  }

  /**
   * The open connection, opening the database (and upgrading it) on first use.
   *
   * @returns The connection; rejects or throws if IndexedDB is missing or refuses to open.
   */
  private open(): Promise<IDBPDatabase<StorageSchema>> {
    this.connection ??= openDB<StorageSchema>(DB_NAME, DB_VERSION, {
      upgrade: (db, oldVersion) => upgradeDatabase(db, oldVersion),
      // A newer version of the app in another tab wants to upgrade: let it.
      blocking: () => this.close(),
      terminated: () => {
        this.connection = null;
      },
    });
    return this.connection;
  }

  /** Ask the browser once to keep the data (UISpec.md section 6, rule 6); the answer is unused. */
  private requestPersistence(): void {
    if (this.persistRequested) return;
    this.persistRequested = true;
    try {
      void navigator.storage?.persist?.()?.catch(() => undefined);
    } catch {
      // Best effort only: a browser without the API, or one that refuses, changes nothing.
    }
  }
}

/**
 * Whether a stored value is a plausible document for this id.
 *
 * @param value - The value stored under `event:<id>`.
 * @param id - The id in the key.
 * @returns True for a plausible document whose own `id` matches.
 */
function isStoredDocument(value: unknown, id: string): value is EventDocument {
  return looksLikeEventDocument(value) && value.id === id;
}

/**
 * The revision of a stored value, for overwriting on import.
 *
 * @param value - The stored value (possibly corrupt).
 * @returns Its revision, or -1 if it has none.
 */
function storedRevision(value: unknown): number {
  return isRecord(value) && Number.isInteger(value.revision) ? Number(value.revision) : -1;
}

/**
 * Whether a value is a well-formed index entry.
 *
 * @param value - One element of the stored index.
 * @returns True if every field has the right type.
 */
function isIndexEntry(value: unknown): value is IndexEntry {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.name === "string" &&
    STATUSES.includes(value.status) &&
    typeof value.updated_at === "string" &&
    typeof value.n_archers === "number"
  );
}

/**
 * The index entry for a document.
 *
 * @param doc - A plausible event document.
 * @returns Its Home list row.
 */
function indexEntry(doc: EventDocument): IndexEntry {
  return {
    id: doc.id,
    name: doc.name,
    status: doc.status,
    updated_at: doc.updated_at,
    n_archers: doc.setup.n_archers,
  };
}

/**
 * The key range holding every `event:<id>` key (and not `events:index`).
 *
 * @returns The range.
 */
function eventRange(): IDBKeyRange {
  return IDBKeyRange.bound(EVENT_PREFIX, `${EVENT_PREFIX}￿`);
}

/**
 * Read the index inside a transaction, rebuilding it from the event records if it is missing
 * or unreadable (the rebuilt index is stored by the next write).
 *
 * @param store - The store, in any transaction mode.
 * @returns The entries, in no particular order.
 */
async function readIndex<Mode extends IDBTransactionMode>(
  store: KeyvalStore<Mode>,
): Promise<IndexEntry[]> {
  const stored = await store.get(INDEX_KEY);
  if (Array.isArray(stored) && stored.every(isIndexEntry)) return stored;
  const keys = await store.getAllKeys(eventRange());
  const values = await store.getAll(eventRange());
  const entries: IndexEntry[] = [];
  keys.forEach((key, i) => {
    const value = values[i];
    if (isStoredDocument(value, key.slice(EVENT_PREFIX.length))) entries.push(indexEntry(value));
  });
  return entries;
}

/**
 * Write a document and its index entry inside a readwrite transaction.
 *
 * @param store - The store, in a readwrite transaction.
 * @param document - The document to store under `event:<id>`.
 */
async function putDocument(
  store: KeyvalStore<"readwrite">,
  document: EventDocument,
): Promise<void> {
  await store.put(document, eventKey(document.id));
  const index = (await readIndex(store)).filter((entry) => entry.id !== document.id);
  index.push(indexEntry(document));
  await store.put(index, INDEX_KEY);
}

/**
 * Order index entries by `updated_at`, newest first (unparseable times last).
 *
 * @param a - One entry.
 * @param b - Another entry.
 * @returns A sort comparison value.
 */
function newestFirst(a: IndexEntry, b: IndexEntry): number {
  return timeOf(b.updated_at) - timeOf(a.updated_at);
}

/**
 * An ISO time in milliseconds.
 *
 * @param iso - An ISO-8601 time.
 * @returns Milliseconds since 1970, or 0 if it cannot be parsed.
 */
function timeOf(iso: string): number {
  const time = Date.parse(iso);
  return Number.isNaN(time) ? 0 : time;
}

/**
 * Abort a transaction, ignoring the error if it has already finished or aborted.
 *
 * @param tx - The transaction.
 */
function abortQuietly(tx: { abort(): void }): void {
  try {
    tx.abort();
  } catch {
    // Already aborted (a failed request aborts it) or already committed.
  }
}
