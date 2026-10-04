/**
 * Backup export and import (UISpec.md section 6, rule 7; decision D18).
 *
 * A backup is JSON text: `{"format": "handicapped-h2hs-backup", "version": 1, "exported_at":
 * ..., "events": [...]}`. Import accepts such a backup or a single event document, rejects files
 * over 10 MB before reading them, passes every event through the engine's `validate_document`
 * (which also migrates old schema versions) and stores only valid documents, never replacing an
 * existing event unless the user confirmed that id. All events are checked before any is stored,
 * so a file the engine cannot check stores nothing.
 */
import type { Envelope, EventDocument } from "../engine/types";
import { isRecord, type EventStore } from "./db";
import type { StorageFailure } from "./status";

export const BACKUP_FORMAT = "handicapped-h2hs-backup";
export const BACKUP_VERSION = 1;
/** The import size limit (decision D18). */
export const MAX_BACKUP_BYTES = 10 * 1024 * 1024;

export interface BackupFile {
  format: typeof BACKUP_FORMAT;
  version: typeof BACKUP_VERSION;
  exported_at: string;
  /** Stored event documents, as they were stored (a corrupt value is kept as it was read). */
  events: unknown[];
}

/** Checks one untrusted document; in the app `(raw) => engine.call("validate_document", { raw })`. */
export type Validator = (raw: unknown) => Promise<Envelope<EventDocument>>;

export type ExportResult =
  | { status: "ok"; text: string; filename: string; count: number }
  | { status: "failed"; failure: StorageFailure };

/** An event that was not imported, with the id and name from the file when it has them. */
export interface Rejection {
  id: string | null;
  name: string | null;
  /** The validator's message, or the storage failure's. */
  message: string;
}

export type ReadBackupResult =
  | { status: "ok"; documents: EventDocument[]; rejected: Rejection[] }
  /** The whole file was refused; nothing was validated or stored. */
  | { status: "rejected"; message: string };

export interface ImportReport {
  /** Ids stored. */
  imported: string[];
  /** Valid documents whose id already exists; store them with `storeImported` once confirmed. */
  needsConfirmation: EventDocument[];
  rejected: Rejection[];
}

export type ImportResult =
  | ({ status: "ok" } & ImportReport)
  /** The whole file was refused; nothing was stored. */
  | { status: "rejected"; message: string };

const NOT_A_BACKUP = "The file is not a backup or an event from this app.";

/**
 * The text of a backup file.
 *
 * @param events - Event documents (or raw stored values, for a corrupt event).
 * @param exportedAt - The export time, ISO-8601.
 * @returns Indented JSON text.
 */
export function backupText(events: readonly unknown[], exportedAt: string): string {
  const backup: BackupFile = {
    format: BACKUP_FORMAT,
    version: BACKUP_VERSION,
    exported_at: exportedAt,
    events: [...events],
  };
  return JSON.stringify(backup, null, 2);
}

/**
 * The backup's file name, stamped like the engine's exports ("leaderboard_20261004-153012.csv").
 *
 * @param exportedAt - The export time, ISO-8601; its own date and time digits are used, as
 *   `exports.filename_stamp` does.
 * @returns E.g. "backup_20261004-153012.json", or "backup.json" if the time cannot be read.
 */
export function backupFileName(exportedAt: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/.exec(exportedAt);
  if (match === null) return "backup.json";
  const [, year, month, day, hour, minute, second] = match;
  return `backup_${year}${month}${day}-${hour}${minute}${second}.json`;
}

/**
 * Export one or all stored events as a backup ("Download backup").
 *
 * @param store - The storage layer.
 * @param exportedAt - The export time, ISO-8601.
 * @param eventId - One event, or undefined for every stored event (corrupt values included, as
 *   stored, so nothing readable is lost).
 * @returns The file's text, name and event count (0 if the one event is missing), or a failure.
 *   With storage failing, build the backup from the document in memory with `backupText`.
 */
export async function exportEvents(
  store: EventStore,
  exportedAt: string,
  eventId?: string,
): Promise<ExportResult> {
  const read = await store.readEventValues(eventId);
  if (read.status === "failed") return read;
  return {
    status: "ok",
    text: backupText(read.values, exportedAt),
    filename: backupFileName(exportedAt),
    count: read.values.length,
  };
}

/**
 * Read and validate a backup file without storing anything.
 *
 * @param input - The chosen file, or its text.
 * @param validate - The engine's `validate_document`.
 * @returns The valid (and migrated) documents and the rejected events with the validator's
 *   message; or "rejected" for a file over 10 MB (checked before reading it), unreadable or not
 *   JSON, not a backup or event, from a newer app version, or that the validator could not check
 *   (it threw, e.g. an `EngineError`).
 */
export async function readBackup(
  input: Blob | string,
  validate: Validator,
): Promise<ReadBackupResult> {
  const size = typeof input === "string" ? new Blob([input]).size : input.size;
  if (size > MAX_BACKUP_BYTES)
    return { status: "rejected", message: "The file is larger than 10 MB, so it is not a backup." };
  let parsed: unknown;
  try {
    parsed = JSON.parse(typeof input === "string" ? input : await input.text());
  } catch {
    return { status: "rejected", message: `${NOT_A_BACKUP} It is not readable JSON.` };
  }
  const events = eventsIn(parsed);
  if (!Array.isArray(events)) return { status: "rejected", message: events.message };

  const documents: EventDocument[] = [];
  const rejected: Rejection[] = [];
  for (const raw of events) {
    let envelope: Envelope<EventDocument>;
    try {
      envelope = await validate(raw);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return {
        status: "rejected",
        message: `The backup could not be checked, so nothing was imported: ${message}`,
      };
    }
    if (envelope.ok) documents.push(envelope.data);
    else rejected.push(rejection(raw, envelope.error.message));
  }
  return { status: "ok", documents, rejected };
}

/**
 * Store validated documents, never replacing an existing event that was not confirmed.
 *
 * @param store - The storage layer.
 * @param documents - Documents from `readBackup`.
 * @param nowIso - The time to store as `updated_at` when overwriting (new ids keep the backup's
 *   `revision` and `updated_at`; see `EventStore.importEvent`).
 * @param overwrite - Ids the user confirmed may replace the stored event.
 * @returns The ids imported, the documents that need confirmation, and those that storage
 *   refused (with the failure's message).
 */
export async function storeImported(
  store: EventStore,
  documents: readonly EventDocument[],
  nowIso: string,
  overwrite: readonly string[] = [],
): Promise<ImportReport> {
  const report: ImportReport = { imported: [], needsConfirmation: [], rejected: [] };
  for (const doc of documents) {
    const result = await store.importEvent(doc, overwrite.includes(doc.id), nowIso);
    if (result.status === "imported") report.imported.push(doc.id);
    else if (result.status === "exists") report.needsConfirmation.push(doc);
    else report.rejected.push(rejection(doc, result.failure.message));
  }
  return report;
}

/**
 * "Import backup": read, validate and store a file in one step.
 *
 * @param store - The storage layer.
 * @param input - The chosen file, or its text.
 * @param validate - The engine's `validate_document`.
 * @param nowIso - The time to store as `updated_at` when overwriting.
 * @param overwrite - Ids the user confirmed may replace the stored event.
 * @returns The import report (validation and storage rejections together), or "rejected" with
 *   the reason the whole file was refused.
 */
export async function importBackup(
  store: EventStore,
  input: Blob | string,
  validate: Validator,
  nowIso: string,
  overwrite: readonly string[] = [],
): Promise<ImportResult> {
  const read = await readBackup(input, validate);
  if (read.status === "rejected") return read;
  const report = await storeImported(store, read.documents, nowIso, overwrite);
  return { status: "ok", ...report, rejected: [...read.rejected, ...report.rejected] };
}

/**
 * The events in a parsed file: a backup's list, or a single event document.
 *
 * @param parsed - The decoded JSON.
 * @returns The raw events, or the reason the file is refused.
 */
function eventsIn(parsed: unknown): unknown[] | { message: string } {
  if (!isRecord(parsed)) return { message: NOT_A_BACKUP };
  if (!("format" in parsed)) return [parsed];
  if (parsed.format !== BACKUP_FORMAT || !Array.isArray(parsed.events))
    return { message: NOT_A_BACKUP };
  if (parsed.version === BACKUP_VERSION) return parsed.events;
  if (typeof parsed.version === "number" && parsed.version > BACKUP_VERSION)
    return { message: "The backup was made by a newer version of the app; reload the page first." };
  return { message: NOT_A_BACKUP };
}

/**
 * A rejection for an event, naming it by the id and name it has.
 *
 * @param raw - The event as read from the file.
 * @param message - Why it was not imported.
 * @returns The rejection.
 */
function rejection(raw: unknown, message: string): Rejection {
  const record = isRecord(raw) ? raw : {};
  return {
    id: typeof record.id === "string" ? record.id : null,
    name: typeof record.name === "string" ? record.name : null,
    message,
  };
}
