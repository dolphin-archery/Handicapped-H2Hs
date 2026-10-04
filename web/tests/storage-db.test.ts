// @vitest-environment node
/**
 * UI-8: the IndexedDB storage layer (src/storage/db.ts) on fake-indexeddb, a fresh database per
 * test: revisioned writes and conflicts, the events index, rename, delete, corrupt values and
 * the failure state (quota, other write errors, IndexedDB unavailable).
 */
import "fake-indexeddb/auto";
import { IDBFactory } from "fake-indexeddb";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EventDocument } from "../src/engine/types";
import { draftKey, EventStore, eventKey, INDEX_KEY, sessionKey } from "../src/storage/db";

const T0 = "2026-10-04T15:30:12";
const T1 = "2026-10-04T15:31:00";
const T2 = "2026-10-04T15:32:00";

/** A plausible event document (the storage layer does not run the engine's validation). */
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

/** Save a new event and return the stored document. */
async function saveNew(store: EventStore, doc: EventDocument, nowIso = T0): Promise<EventDocument> {
  const result = await store.saveEvent(doc, null, nowIso);
  if (result.status !== "saved") throw new Error(`save failed: ${JSON.stringify(result)}`);
  return result.document;
}

/** The stored document, failing the test if it is not found. */
async function stored(store: EventStore, id: string): Promise<EventDocument> {
  const result = await store.loadEvent(id);
  if (result.status !== "found") throw new Error(`not found: ${JSON.stringify(result)}`);
  return result.document;
}

/** Make IDBObjectStore.put throw `error` for one key (and work normally for the others). */
function failPutFor(key: string, error: unknown) {
  const original = IDBObjectStore.prototype.put;
  return vi.spyOn(IDBObjectStore.prototype, "put").mockImplementation(function (
    this: IDBObjectStore,
    value: unknown,
    storeKey?: IDBValidKey,
  ) {
    if (storeKey === key) throw error;
    return original.call(this, value, storeKey);
  });
}

let store: EventStore;

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory();
  store = new EventStore();
});

afterEach(() => {
  store.close();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("revisioned writes", () => {
  it("a write whose expected revision does not match is a conflict and writes nothing", async () => {
    const first = await saveNew(store, makeDoc());
    expect(first.revision).toBe(1);
    const second = await store.saveEvent({ ...first, name: "Tab A" }, 1, T1);
    expect(second.status).toBe("saved");

    // A second tab still holding revision 1 tries to save.
    const stale = await store.saveEvent({ ...first, name: "Tab B" }, 1, T2);
    expect(stale.status).toBe("conflict");
    if (stale.status !== "conflict") return;
    expect(stale.current?.name).toBe("Tab A");
    expect(stale.current?.revision).toBe(2);
    expect(await stored(store, "e1")).toEqual(stale.current);
    const list = await store.listEvents();
    expect(list.status === "ok" && list.events[0].name).toBe("Tab A");
  });

  it("refuses a new event whose id was created elsewhere, and an event deleted elsewhere", async () => {
    const saved = await saveNew(store, makeDoc("e1", { name: "Other tab" }));
    const created = await store.saveEvent(makeDoc("e1", { name: "This tab" }), null, T1);
    expect(created).toEqual({ status: "conflict", current: saved });

    await store.deleteEvent("e1");
    const deleted = await store.saveEvent(saved, saved.revision, T2);
    expect(deleted).toEqual({ status: "conflict", current: null });
    expect((await store.loadEvent("e1")).status).toBe("missing");
  });

  it("a write replaces the whole document, increments revision and updates the index", async () => {
    const running = makeDoc("e1", {
      status: "running",
      archers: [{ name: "Ann", bowstyle: "Recurve", handicap: 35, target: null }],
      assignment: [0],
      scores: { "0": { "0": { scores: { "0": 280 }, closest: null } } },
      // A key the next document does not have: it must not survive the replace.
      ...({ leftover: true } as object),
    });
    const first = await saveNew(store, running);
    expect(first).toEqual({ ...running, revision: 1, updated_at: T0 });

    const next = makeDoc("e1", {
      name: "Renamed by a command",
      status: "complete",
      setup: { ...running.setup, n_archers: 6 },
      revision: 1,
    });
    const result = await store.saveEvent(next, 1, T1);
    expect(result).toEqual({ status: "saved", document: { ...next, revision: 2, updated_at: T1 } });
    expect(await stored(store, "e1")).toEqual({ ...next, revision: 2, updated_at: T1 });
    expect(await store.getValue(INDEX_KEY)).toEqual([
      { id: "e1", name: "Renamed by a command", status: "complete", updated_at: T1, n_archers: 6 },
    ]);
    // The caller's document is not changed.
    expect(next.revision).toBe(1);
  });

  it("sets the save status and asks for persistent storage once", async () => {
    const persist = vi.fn().mockResolvedValue(false);
    vi.stubGlobal("navigator", { storage: { persist } });
    const seen: string[] = [];
    store.status.subscribe(() => seen.push(store.status.getSnapshot().state));
    expect(store.status.getSnapshot()).toEqual({ state: "idle" });

    const doc = await saveNew(store, makeDoc());
    await store.saveEvent(doc, doc.revision, T1);
    expect(seen).toEqual(["saving", "saved", "saving", "saved"]);
    expect(store.status.getSnapshot()).toEqual({ state: "saved", savedAt: T1 });
    expect(persist).toHaveBeenCalledTimes(1);
  });

  it("a conflict restores the previous save status", async () => {
    const doc = await saveNew(store, makeDoc());
    await store.saveEvent(doc, 99, T1);
    expect(store.status.getSnapshot()).toEqual({ state: "saved", savedAt: T0 });
  });
});

describe("events index", () => {
  it("lists events newest first and rebuilds a missing or unreadable index", async () => {
    await saveNew(store, makeDoc("old", { name: "Old" }), T0);
    await saveNew(store, makeDoc("new", { name: "New", status: "running" }), T2);
    await saveNew(store, makeDoc("mid", { name: "Mid", status: "complete" }), T1);
    const expected = [
      { id: "new", name: "New", status: "running", updated_at: T2, n_archers: 4 },
      { id: "mid", name: "Mid", status: "complete", updated_at: T1, n_archers: 4 },
      { id: "old", name: "Old", status: "setup", updated_at: T0, n_archers: 4 },
    ];
    expect(await store.listEvents()).toEqual({ status: "ok", events: expected });

    for (const broken of ["not a list", [{ id: "new" }], undefined]) {
      if (broken === undefined) await store.deleteValue(INDEX_KEY);
      else await store.putValue(INDEX_KEY, broken);
      expect(await store.listEvents()).toEqual({ status: "ok", events: expected });
    }

    // The next write stores a rebuilt index again.
    await store.renameEvent("old", "Older", 1, T0);
    const index = await store.getValue(INDEX_KEY);
    expect(index).toHaveLength(3);
  });

  it("leaves corrupt event values out of a rebuilt index", async () => {
    await saveNew(store, makeDoc("good"));
    await store.putValue(eventKey("bad"), { id: "bad" });
    await store.deleteValue(INDEX_KEY);
    const list = await store.listEvents();
    expect(list.status === "ok" && list.events.map((entry) => entry.id)).toEqual(["good"]);
  });
});

describe("rename and delete", () => {
  it("renaming changes only name, increments revision and updates the index", async () => {
    const doc = await saveNew(store, makeDoc("e1", { status: "running" }));
    const result = await store.renameEvent("e1", "Club night 3 Oct", doc.revision, T1);
    const renamed = { ...doc, name: "Club night 3 Oct", revision: 2, updated_at: T1 };
    expect(result).toEqual({ status: "saved", document: renamed });
    expect(await stored(store, "e1")).toEqual(renamed);
    expect(await store.listEvents()).toEqual({
      status: "ok",
      events: [
        { id: "e1", name: "Club night 3 Oct", status: "running", updated_at: T1, n_archers: 4 },
      ],
    });
  });

  it("renaming with a stale revision or a missing event is a conflict", async () => {
    const doc = await saveNew(store, makeDoc());
    await store.renameEvent("e1", "First", doc.revision, T1);
    expect(await store.renameEvent("e1", "Second", doc.revision, T2)).toMatchObject({
      status: "conflict",
      current: { name: "First", revision: 2 },
    });
    expect(await store.renameEvent("nope", "Name", 1, T2)).toEqual({
      status: "conflict",
      current: null,
    });
  });

  it("deleting removes the event, its draft, its session and its index entry", async () => {
    await saveNew(store, makeDoc("e1"));
    const other = await saveNew(store, makeDoc("e2"));
    for (const id of ["e1", "e2"]) {
      await store.putValue(draftKey(id), { form: id });
      await store.putValue(sessionKey(id), `/event/${id}/pass`);
    }

    expect(await store.deleteEvent("e1")).toEqual({ status: "deleted" });
    expect(await store.getValue(eventKey("e1"))).toBeUndefined();
    expect(await store.getValue(draftKey("e1"))).toBeUndefined();
    expect(await store.getValue(sessionKey("e1"))).toBeUndefined();
    const list = await store.listEvents();
    expect(list.status === "ok" && list.events.map((entry) => entry.id)).toEqual(["e2"]);
    // The other event is untouched.
    expect(await stored(store, "e2")).toEqual(other);
    expect(await store.getValue(draftKey("e2"))).toEqual({ form: "e2" });
    expect(await store.getValue(sessionKey("e2"))).toBe("/event/e2/pass");
  });
});

describe("reading", () => {
  it("tells found, missing and corrupt values apart without throwing", async () => {
    const doc = await saveNew(store, makeDoc("ok"));
    expect(await store.loadEvent("ok")).toEqual({ status: "found", document: doc });
    expect(await store.loadEvent("none")).toEqual({ status: "missing" });

    const corrupt: [string, unknown][] = [
      ["text", "{not json"],
      ["null", null],
      ["array", [doc]],
      ["no-schema", { ...doc, id: "no-schema", schema_version: undefined }],
      ["bad-revision", { ...doc, id: "bad-revision", revision: "2" }],
      ["bad-status", { ...doc, id: "bad-status", status: "paused" }],
      ["no-setup", { ...doc, id: "no-setup", setup: null }],
      ["empty-id", { ...doc, id: "" }],
      ["other-id", { ...doc, id: "someone-else" }],
    ];
    for (const [id, raw] of corrupt) {
      await store.putValue(eventKey(id), raw);
      expect(await store.loadEvent(id)).toEqual({ status: "corrupt", raw });
    }
  });

  it("a save over a corrupt value is a conflict, so what can be read is kept", async () => {
    await store.putValue(eventKey("e1"), { id: "e1", garbage: true });
    expect(await store.saveEvent(makeDoc("e1"), null, T1)).toEqual({
      status: "conflict",
      current: null,
    });
    expect(await store.loadEvent("e1")).toEqual({
      status: "corrupt",
      raw: { id: "e1", garbage: true },
    });
  });
});

describe("failures", () => {
  it.each([
    ["the event record", eventKey("e1")],
    ["the index, after the event record was written", INDEX_KEY],
  ])(
    "a quota failure writing %s keeps the previous document and sets the failure state",
    async (_, key) => {
      const good = await saveNew(store, makeDoc("e1", { name: "Good" }));
      const indexBefore = await store.getValue(INDEX_KEY);
      failPutFor(key, new DOMException("The quota has been exceeded.", "QuotaExceededError"));

      const result = await store.saveEvent({ ...good, name: "Lost" }, good.revision, T1);
      expect(result).toMatchObject({ status: "failed", failure: { reason: "quota" } });
      expect(store.status.getSnapshot()).toMatchObject({ state: "failed", reason: "quota" });

      vi.restoreAllMocks();
      expect(await stored(store, "e1")).toEqual(good);
      expect(await store.getValue(INDEX_KEY)).toEqual(indexBefore);

      // Once space is freed, the next save succeeds and clears the failure.
      const retry = await store.saveEvent({ ...good, name: "Saved" }, good.revision, T2);
      expect(retry.status).toBe("saved");
      expect(store.status.getSnapshot()).toEqual({ state: "saved", savedAt: T2 });
    },
  );

  it("a failed save keeps the document it was writing on the status, for the backup", async () => {
    const good = await saveNew(store, makeDoc());
    failPutFor(
      eventKey("e1"),
      new DOMException("The quota has been exceeded.", "QuotaExceededError"),
    );
    const changed = { ...good, name: "Not stored" };
    await store.saveEvent(changed, good.revision, T1);
    expect(store.status.getSnapshot()).toMatchObject({ state: "failed", unsaved: changed });
    vi.restoreAllMocks();
    vi.stubGlobal("indexedDB", undefined);
    // With no IndexedDB at all, a new event's first save is kept the same way.
    const fresh = makeDoc("e2");
    const offline = new EventStore();
    await offline.saveEvent(fresh, null, T0);
    expect(offline.status.getSnapshot()).toMatchObject({
      state: "failed",
      reason: "unavailable",
      unsaved: fresh,
    });
  });

  it("any other write error sets an error failure and keeps the previous document", async () => {
    const good = await saveNew(store, makeDoc());
    failPutFor(eventKey("e1"), new Error("disk on fire"));
    const result = await store.renameEvent("e1", "Lost", good.revision, T1);
    expect(result).toMatchObject({ status: "failed", failure: { reason: "error" } });
    const status = store.status.getSnapshot();
    expect(status.state === "failed" && status.message).toContain("disk on fire");
    vi.restoreAllMocks();
    expect(await stored(store, "e1")).toEqual(good);
  });

  it("reports IndexedDB that is missing as unavailable, without throwing", async () => {
    vi.stubGlobal("indexedDB", undefined);
    expect(await store.listEvents()).toMatchObject({
      status: "failed",
      failure: { reason: "unavailable" },
    });
    expect(store.status.getSnapshot()).toMatchObject({ state: "failed", reason: "unavailable" });
    expect(await store.saveEvent(makeDoc(), null, T0)).toMatchObject({
      status: "failed",
      failure: { reason: "unavailable" },
    });
    expect(await store.loadEvent("e1")).toMatchObject({ status: "failed" });
    expect(await store.deleteEvent("e1")).toMatchObject({ status: "failed" });
    expect(await store.getValue("settings")).toBeUndefined();
    expect(await store.putValue("settings", {})).toBe(false);
  });

  it("reports IndexedDB that refuses to open as unavailable, and retries later", async () => {
    const open = vi.spyOn(indexedDB, "open").mockImplementation(() => {
      throw new DOMException("A mutation operation was attempted.", "InvalidStateError");
    });
    expect(await store.saveEvent(makeDoc(), null, T0)).toMatchObject({
      status: "failed",
      failure: { reason: "unavailable" },
    });
    open.mockRestore();
    expect((await store.saveEvent(makeDoc(), null, T0)).status).toBe("saved");
  });
});
