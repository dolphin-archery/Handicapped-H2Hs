// @vitest-environment node
/**
 * UI-8: backup export and import (src/storage/backup.ts) on fake-indexeddb, a fresh database
 * per test, with a fake `validate_document` (the real one runs in the Python engine).
 */
import "fake-indexeddb/auto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { IDBFactory } from "fake-indexeddb";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EngineError } from "../src/engine/client";
import type { Envelope, EventDocument } from "../src/engine/types";
import {
  BACKUP_FORMAT,
  backupFileName,
  exportEvents,
  importBackup,
  MAX_BACKUP_BYTES,
  readBackup,
  storeImported,
  type Validator,
} from "../src/storage/backup";
import { EventStore, eventKey, INDEX_KEY } from "../src/storage/db";

const T0 = "2026-10-04T15:30:12";
const T1 = "2026-10-04T16:00:00";

/** A plausible event document. */
function makeDoc(id = "e1", overrides: Partial<EventDocument> = {}): EventDocument {
  return {
    schema_version: 1,
    id,
    name: "Club night",
    created_at: T0,
    updated_at: T0,
    revision: 0,
    status: "setup",
    setup: {
      stage: 0,
      n_archers: 4,
      total_arrows: 60,
      n_pass: 12,
      setup_mode: "simple",
      shoot_byes: true,
      target: { distance_key: "20yd", face_cm: 60 },
      update_handicaps: false,
      n_lookback: null,
      start_weight: null,
    },
    archers: [],
    assignment: null,
    scores: {},
    current_pass: 0,
    ...overrides,
  };
}

/** A validator that accepts every value as it is. */
const acceptAll: Validator = (raw) =>
  Promise.resolve({ ok: true, data: raw as EventDocument } as Envelope<EventDocument>);

/** A validator that refuses non-objects and documents named "Bad", as `validate_document` would. */
const refuseBad = vi.fn<Validator>(async (raw) => {
  if (typeof raw !== "object" || raw === null)
    return {
      ok: false,
      error: { code: "validation", message: "Invalid event document: not an object." },
    };
  if ((raw as EventDocument).name === "Bad")
    return {
      ok: false,
      error: { code: "validation", message: "Invalid event document: bad name." },
    };
  return { ok: true, data: raw as EventDocument };
});

/** Save a new event and return the stored document. */
async function saveNew(store: EventStore, doc: EventDocument, nowIso = T0): Promise<EventDocument> {
  const result = await store.saveEvent(doc, null, nowIso);
  if (result.status !== "saved") throw new Error(`save failed: ${JSON.stringify(result)}`);
  return result.document;
}

/** Export all events of `store` as backup text. */
async function exportText(store: EventStore, eventId?: string): Promise<string> {
  const result = await exportEvents(store, T1, eventId);
  if (result.status !== "ok") throw new Error("export failed");
  return result.text;
}

/** The ids in the events index. */
async function listedIds(store: EventStore): Promise<string[]> {
  const list = await store.listEvents();
  return list.status === "ok" ? list.events.map((entry) => entry.id).sort() : [];
}

let store: EventStore;

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory();
  store = new EventStore();
  refuseBad.mockClear();
});

afterEach(() => {
  store.close();
  vi.restoreAllMocks();
});

describe("export", () => {
  it("exports one or all events as a backup envelope with a stamped file name", async () => {
    const one = await saveNew(store, makeDoc("e1"));
    const two = await saveNew(store, makeDoc("e2", { name: "Second" }));
    await store.putValue(eventKey("broken"), { id: "broken" });

    const single = await exportEvents(store, T1, "e1");
    expect(single).toMatchObject({
      status: "ok",
      filename: "backup_20261004-160000.json",
      count: 1,
    });
    if (single.status !== "ok") return;
    expect(JSON.parse(single.text)).toEqual({
      format: BACKUP_FORMAT,
      version: 1,
      exported_at: T1,
      events: [one],
    });

    // Every stored value is exported, a corrupt one as it was read.
    const all = JSON.parse(await exportText(store));
    expect(all.events).toEqual([{ id: "broken" }, one, two]);
    expect(await exportEvents(store, T1, "none")).toMatchObject({ status: "ok", count: 0 });
  });

  it("names the file from the export time's own digits", () => {
    expect(backupFileName("2026-10-04T09:05:07.123Z")).toBe("backup_20261004-090507.json");
    expect(backupFileName("yesterday")).toBe("backup.json");
  });
});

describe("import", () => {
  it("a backup exported then imported restores an identical document", async () => {
    const original = await saveNew(store, makeDoc("e1", { status: "running", name: "Kept" }));
    await store.renameEvent("e1", "Kept, renamed", original.revision, T1);
    const exported = (await store.loadEvent("e1")) as { document: EventDocument };
    const text = await exportText(store);

    globalThis.indexedDB = new IDBFactory();
    const restored = new EventStore();
    const result = await importBackup(restored, new Blob([text]), refuseBad, T1);
    expect(result).toEqual({ status: "ok", imported: ["e1"], needsConfirmation: [], rejected: [] });
    expect(refuseBad).toHaveBeenCalledWith(exported.document);
    expect(await restored.loadEvent("e1")).toEqual({
      status: "found",
      document: exported.document,
    });
    expect(await restored.listEvents()).toEqual(await store.listEvents());
    restored.close();
  });

  it("round-trips a real engine document from the committed bridge fixtures", async () => {
    const fixtureFile = path.resolve(
      path.dirname(fileURLToPath(import.meta.url)),
      "../../tests/fixtures/bridge/complete_event.json",
    );
    const fixture = JSON.parse(readFileSync(fixtureFile, "utf-8")) as {
      steps: { result: { ok: boolean; data?: { document?: EventDocument } } }[];
    };
    const documents = fixture.steps.flatMap((step) => step.result.data?.document ?? []);
    const finished = documents[documents.length - 1];
    expect(finished.status).toBe("complete");

    const saved = await saveNew(store, finished, T1);
    expect(saved).toEqual({ ...finished, revision: finished.revision + 1, updated_at: T1 });
    const text = await exportText(store);

    globalThis.indexedDB = new IDBFactory();
    const restored = new EventStore();
    expect(await importBackup(restored, text, acceptAll, T1)).toMatchObject({
      imported: [finished.id],
    });
    expect(await restored.loadEvent(finished.id)).toEqual({ status: "found", document: saved });
    restored.close();
  });

  it("accepts a single event document as well as a backup", async () => {
    const doc = makeDoc("solo", { revision: 7, updated_at: T1 });
    const result = await importBackup(store, JSON.stringify(doc), refuseBad, T1);
    expect(result).toMatchObject({ status: "ok", imported: ["solo"] });
    expect(await store.loadEvent("solo")).toEqual({ status: "found", document: doc });
  });

  it("stores only the documents the validator accepts and reports the others", async () => {
    const text = JSON.stringify({
      format: BACKUP_FORMAT,
      version: 1,
      exported_at: T0,
      events: [makeDoc("good"), makeDoc("bad", { name: "Bad" }), 42],
    });
    const result = await importBackup(store, text, refuseBad, T1);
    expect(result).toEqual({
      status: "ok",
      imported: ["good"],
      needsConfirmation: [],
      rejected: [
        { id: "bad", name: "Bad", message: "Invalid event document: bad name." },
        { id: null, name: null, message: "Invalid event document: not an object." },
      ],
    });
    expect(refuseBad).toHaveBeenCalledTimes(3);
    expect(await listedIds(store)).toEqual(["good"]);
    expect(await store.loadEvent("bad")).toEqual({ status: "missing" });
  });

  it("stores nothing when every event is invalid", async () => {
    const text = JSON.stringify(makeDoc("bad", { name: "Bad" }));
    expect(await importBackup(store, new Blob([text]), refuseBad, T1)).toMatchObject({
      status: "ok",
      imported: [],
      rejected: [{ id: "bad" }],
    });
    expect(await store.getValue(eventKey("bad"))).toBeUndefined();
    expect(await store.getValue(INDEX_KEY)).toBeUndefined();
  });

  it.each([
    ["not JSON", "{this is not json", "not readable JSON"],
    ["a JSON list", "[1, 2]", "not a backup"],
    ["a JSON number", "12", "not a backup"],
    ["another format", JSON.stringify({ format: "zip", events: [] }), "not a backup"],
    [
      "a backup without events",
      JSON.stringify({ format: BACKUP_FORMAT, version: 1 }),
      "not a backup",
    ],
    [
      "a newer backup version",
      JSON.stringify({ format: BACKUP_FORMAT, version: 2, events: [] }),
      "newer version",
    ],
  ])("rejects %s and stores nothing", async (_, text, message) => {
    const result = await importBackup(store, new Blob([text]), refuseBad, T1);
    expect(result.status).toBe("rejected");
    expect(result.status === "rejected" && result.message).toContain(message);
    expect(refuseBad).not.toHaveBeenCalled();
    expect(await listedIds(store)).toEqual([]);
  });

  it("rejects a file over 10 MB before reading it", async () => {
    const text = vi.fn(() => Promise.resolve(JSON.stringify(makeDoc())));
    const tooBig = { size: MAX_BACKUP_BYTES + 1, text } as unknown as Blob;
    const result = await importBackup(store, tooBig, refuseBad, T1);
    expect(result).toMatchObject({ status: "rejected", message: expect.stringContaining("10 MB") });
    expect(text).not.toHaveBeenCalled();
    expect(refuseBad).not.toHaveBeenCalled();

    // A real file one byte over the limit, and text over the limit, are refused too.
    const realFile = new Blob([new Uint8Array(MAX_BACKUP_BYTES + 1)]);
    expect((await importBackup(store, realFile, refuseBad, T1)).status).toBe("rejected");
    expect((await readBackup(" ".repeat(MAX_BACKUP_BYTES + 1), refuseBad)).status).toBe("rejected");
    expect(await listedIds(store)).toEqual([]);

    // Exactly 10 MB is allowed.
    const atLimit = { size: MAX_BACKUP_BYTES, text } as unknown as Blob;
    expect(await importBackup(store, atLimit, refuseBad, T1)).toMatchObject({ imported: ["e1"] });
  });

  it("reports a validator that throws (the engine failed) and stores nothing", async () => {
    const crashing = vi.fn<Validator>(async (raw) => {
      if ((raw as EventDocument).id === "second")
        throw new EngineError("crashed", "The engine stopped unexpectedly.");
      return { ok: true, data: raw as EventDocument };
    });
    const text = JSON.stringify({
      format: BACKUP_FORMAT,
      version: 1,
      exported_at: T0,
      events: [makeDoc("first"), makeDoc("second")],
    });
    const result = await importBackup(store, text, crashing, T1);
    expect(result).toEqual({
      status: "rejected",
      message:
        "The backup could not be checked, so nothing was imported: The engine stopped unexpectedly.",
    });
    expect(await listedIds(store)).toEqual([]);
  });

  it("does not overwrite an existing id without confirmation, and does with it", async () => {
    const mine = await saveNew(store, makeDoc("e1", { name: "Mine" }));
    await store.renameEvent("e1", "Mine, renamed", mine.revision, T0); // revision 2
    const backupDoc = makeDoc("e1", { name: "From backup", revision: 1 });
    const text = JSON.stringify(backupDoc);

    const first = await importBackup(store, text, refuseBad, T1);
    expect(first).toEqual({
      status: "ok",
      imported: [],
      needsConfirmation: [backupDoc],
      rejected: [],
    });
    expect(await store.loadEvent("e1")).toMatchObject({ document: { name: "Mine, renamed" } });

    // The user confirmed: store the pending documents with their ids allowed to overwrite.
    if (first.status !== "ok") return;
    const second = await storeImported(store, first.needsConfirmation, T1, ["e1"]);
    expect(second).toEqual({ imported: ["e1"], needsConfirmation: [], rejected: [] });
    // The revision is above both, so a tab holding the old document sees a conflict.
    const overwritten = { ...backupDoc, revision: 3, updated_at: T1 };
    expect(await store.loadEvent("e1")).toEqual({ status: "found", document: overwritten });
    expect(await store.getValue(INDEX_KEY)).toEqual([
      { id: "e1", name: "From backup", status: "setup", updated_at: T1, n_archers: 4 },
    ]);
    expect((await store.saveEvent(mine, 2, T1)).status).toBe("conflict");

    // importBackup takes the confirmation directly too.
    expect(await importBackup(store, text, refuseBad, T1, ["e1"])).toMatchObject({
      imported: ["e1"],
    });
  });

  it("reports an event that storage refuses, with the failure's message", async () => {
    const original = IDBObjectStore.prototype.put;
    vi.spyOn(IDBObjectStore.prototype, "put").mockImplementation(function (
      this: IDBObjectStore,
      value: unknown,
      key?: IDBValidKey,
    ) {
      if (key === eventKey("full")) throw new DOMException("Full.", "QuotaExceededError");
      return original.call(this, value, key);
    });
    const text = JSON.stringify({
      format: BACKUP_FORMAT,
      version: 1,
      exported_at: T0,
      events: [makeDoc("full", { name: "Too big" }), makeDoc("fits")],
    });
    expect(await importBackup(store, text, refuseBad, T1)).toEqual({
      status: "ok",
      imported: ["fits"],
      needsConfirmation: [],
      rejected: [
        { id: "full", name: "Too big", message: "The browser's storage for this site is full." },
      ],
    });
  });
});
