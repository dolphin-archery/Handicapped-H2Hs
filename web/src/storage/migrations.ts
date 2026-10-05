/**
 * IndexedDB version upgrades for the storage layer (UISpec.md section 6).
 *
 * Only the database's shape lives here: version 1 creates the one object store of keyed values.
 * Event document schema migrations belong to the Python engine (`validate_document`, UISpec.md
 * section 6, rule 9), never to TypeScript.
 */
import type { DBSchema, IDBPDatabase } from "idb";

export const DB_NAME = "handicapped-h2hs";
export const DB_VERSION = 1;
/** The one object store: string keys (`event:<id>`, `events:index`, ...) to JSON values. */
export const STORE = "keyval";

export interface StorageSchema extends DBSchema {
  keyval: { key: string; value: unknown };
}

/**
 * Bring the database up to `DB_VERSION`; idb calls this inside the version-change transaction.
 *
 * @param db - The database being upgraded.
 * @param oldVersion - Its version before the upgrade (0 for a new database).
 */
export function upgradeDatabase(db: IDBPDatabase<StorageSchema>, oldVersion: number): void {
  if (oldVersion < 1) db.createObjectStore(STORE);
}
