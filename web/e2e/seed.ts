/**
 * Seed the app's IndexedDB directly (layout of src/storage: database "handicapped-h2hs" v1,
 * store "keyval", keys event:<id>, events:index, session:<id>), with real event documents from
 * the UI-5 fixtures, so shell tests do not need the Python engine.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import type { Page } from "@playwright/test";

const FIXTURES = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "tests",
  "fixtures",
  "bridge",
);

/**
 * A real event document from a fixture: the document returned by the first step of a command.
 *
 * @param command - e.g. "apply_stage1" (stage 1, setting up) or "start_event" (running).
 * @param changes - Fields to override (id, name, updated_at...).
 * @returns The document.
 */
export function fixtureDoc(
  command: string,
  changes: Record<string, unknown> = {},
): Record<string, unknown> {
  const fixture = JSON.parse(readFileSync(path.join(FIXTURES, "simple.json"), "utf8"));
  const step = fixture.steps.find((s: { command: string }) => s.command === command);
  return { ...step.result.data.document, ...changes };
}

/**
 * Write events (and optional raw values and session routes) into the app's database, then reload.
 *
 * @param page - A page already on the app (for its origin).
 * @param seed.events - Event documents (or raw values with an id, for corrupt ones).
 * @param seed.index - Index entries; derived from the documents when omitted.
 * @param seed.sessions - Last route per event id.
 */
export async function seed(
  page: Page,
  {
    events,
    index,
    sessions = {},
  }: { events: Record<string, unknown>[]; index?: unknown[]; sessions?: Record<string, string> },
  raws: Record<string, unknown> = {},
): Promise<void> {
  await page.evaluate(
    async ({ events, index, sessions, raws }) => {
      const db: IDBDatabase = await new Promise((resolve, reject) => {
        const request = indexedDB.open("handicapped-h2hs", 1);
        request.onupgradeneeded = () => request.result.createObjectStore("keyval");
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
      const tx = db.transaction("keyval", "readwrite");
      const store = tx.objectStore("keyval");
      for (const doc of events) store.put(doc, `event:${doc.id}`);
      for (const [id, raw] of Object.entries(raws)) store.put(raw, `event:${id}`);
      for (const [id, route] of Object.entries(sessions)) store.put(route, `session:${id}`);
      store.put(
        index ??
          events.map((d) => ({
            id: d.id,
            name: d.name,
            status: d.status,
            updated_at: d.updated_at,
            n_archers: (d.setup as { n_archers: number }).n_archers,
          })),
        "events:index",
      );
      await new Promise((resolve, reject) => {
        tx.oncomplete = resolve;
        tx.onerror = () => reject(tx.error);
      });
      db.close();
    },
    { events, index: index ?? null, sessions, raws },
  );
  await page.reload();
}
