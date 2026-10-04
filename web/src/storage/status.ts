/**
 * The storage layer's save state, for the header's save indicator ("Saved HH:MM", "Saving...")
 * and the persistent "This event is NOT being saved" alert (UISpec.md section 6, rules 1 and 3,
 * and the failure modes paragraph).
 *
 * React reads it with `useSyncExternalStore(status.subscribe, status.getSnapshot)`.
 */
import type { EventDocument } from "../engine/types";

/** Why storage failed: no IndexedDB (e.g. a private window), a full quota, or anything else. */
export type StorageFailureReason = "unavailable" | "quota" | "error";

export interface StorageFailure {
  reason: StorageFailureReason;
  /** Text for the user. */
  message: string;
}

export type StorageStatus =
  | { state: "idle" }
  | { state: "saving" }
  /** `savedAt` is the ISO time passed to the save, as written to `updated_at`. */
  | { state: "saved"; savedAt: string }
  /**
   * `unsaved` is the document a failed save was writing, kept so "Download backup" can offer it
   * even when nothing could be stored (for example a new event in a private window).
   */
  | ({ state: "failed"; unsaved?: EventDocument } & StorageFailure);

export class StatusStore {
  private snapshot: StorageStatus = { state: "idle" };
  private readonly listeners = new Set<() => void>();

  /**
   * Listen to status changes (an arrow property, so it can be passed on unbound).
   *
   * @param listener - Called after every change.
   * @returns A function that stops listening.
   */
  readonly subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  /**
   * The current status (the same object until it changes, as `useSyncExternalStore` requires).
   *
   * @returns The status.
   */
  readonly getSnapshot = (): StorageStatus => this.snapshot;

  /**
   * Replace the status and notify the listeners.
   *
   * @param status - The new status.
   */
  set(status: StorageStatus): void {
    this.snapshot = status;
    for (const listener of this.listeners) listener();
  }
}

/**
 * The failure for IndexedDB that cannot be opened at all (missing, or refused in private mode).
 *
 * @param error - What opening threw or rejected with.
 * @returns An "unavailable" failure.
 */
export function unavailableFailure(error: unknown): StorageFailure {
  return {
    reason: "unavailable",
    message: `This browser is not letting the app store data, for example in a private window (${detail(error)}).`,
  };
}

/**
 * Classify an error from a transaction: a full quota, or any other failure.
 *
 * @param error - What the transaction threw or rejected with.
 * @returns A "quota" failure for `QuotaExceededError` (and Firefox's older name for it),
 *   otherwise an "error" failure.
 */
export function describeFailure(error: unknown): StorageFailure {
  const name = typeof error === "object" && error !== null && "name" in error ? error.name : "";
  if (name === "QuotaExceededError" || name === "NS_ERROR_DOM_QUOTA_REACHED")
    return { reason: "quota", message: "The browser's storage for this site is full." };
  return { reason: "error", message: `The browser could not store the data (${detail(error)}).` };
}

/**
 * A short description of an error.
 *
 * @param error - Anything thrown.
 * @returns Its name and message, or a generic text.
 */
function detail(error: unknown): string {
  if (typeof error === "object" && error !== null && "message" in error) {
    const name = "name" in error ? `${String(error.name)}: ` : "";
    return `${name}${String(error.message)}`;
  }
  return error === undefined ? "no details" : String(error);
}
