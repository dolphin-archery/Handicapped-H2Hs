// @vitest-environment node
/**
 * UI-8: device records (src/storage/autosave.ts) on fake-indexeddb, a fresh database per test:
 * drafts and the debounced draft saver, the last route per event, and device settings.
 */
import "fake-indexeddb/auto";
import { IDBFactory } from "fake-indexeddb";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  DEFAULT_SETTINGS,
  deleteDraft,
  DRAFT_DELAY_MS,
  DraftSaver,
  getDraft,
  getSessionRoute,
  getSettings,
  setDraft,
  setSessionRoute,
  updateSettings,
} from "../src/storage/autosave";
import { draftKey, EventStore, SETTINGS_KEY } from "../src/storage/db";

let store: EventStore;

beforeEach(() => {
  globalThis.indexedDB = new IDBFactory();
  store = new EventStore();
});

afterEach(() => {
  store.close();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("round trips", () => {
  it("drafts are stored per event and deleted", async () => {
    const draft = { stage: 2, archers: [{ name: "Ann", handicap: "35" }] };
    expect(await setDraft(store, "e1", draft)).toBe(true);
    expect(await setDraft(store, "e2", { match: 0, scores: { "0": "280" } })).toBe(true);

    // A second connection reads what the first stored.
    const reopened = new EventStore();
    expect(await getDraft(reopened, "e1")).toEqual(draft);
    expect(await getDraft(reopened, "e3")).toBeUndefined();

    expect(await deleteDraft(store, "e1")).toBe(true);
    expect(await getDraft(reopened, "e1")).toBeUndefined();
    expect(await getDraft(reopened, "e2")).toEqual({ match: 0, scores: { "0": "280" } });
    reopened.close();
  });

  it("the session route is stored per event", async () => {
    expect(await getSessionRoute(store, "e1")).toBeNull();
    expect(await setSessionRoute(store, "e1", "/event/e1/match/2")).toBe(true);
    await setSessionRoute(store, "e2", "/event/e2/stage/1");
    const reopened = new EventStore();
    expect(await getSessionRoute(reopened, "e1")).toBe("/event/e1/match/2");
    expect(await getSessionRoute(reopened, "e2")).toBe("/event/e2/stage/1");
    reopened.close();
  });

  it("settings start at the defaults and keep every update", async () => {
    expect(await getSettings(store)).toEqual({
      color_scheme: "auto",
      graph_view: false,
      last_event_id: null,
    });
    expect(await updateSettings(store, { graph_view: true })).toEqual({
      ...DEFAULT_SETTINGS,
      graph_view: true,
    });
    await updateSettings(store, { color_scheme: "dark", last_event_id: "e1" });

    const reopened = new EventStore();
    expect(await getSettings(reopened)).toEqual({
      color_scheme: "dark",
      graph_view: true,
      last_event_id: "e1",
    });
    reopened.close();
  });

  it("ill-typed stored settings fall back to the defaults field by field", async () => {
    await store.putValue(SETTINGS_KEY, {
      color_scheme: "purple",
      graph_view: "yes",
      last_event_id: 5,
    });
    expect(await getSettings(store)).toEqual(DEFAULT_SETTINGS);
    await store.putValue(SETTINGS_KEY, { color_scheme: "light", graph_view: 1 });
    expect(await getSettings(store)).toEqual({ ...DEFAULT_SETTINGS, color_scheme: "light" });
    await store.putValue(SETTINGS_KEY, "not an object");
    expect(await getSettings(store)).toEqual(DEFAULT_SETTINGS);
  });

  it("without IndexedDB, reads give the defaults and writes report false", async () => {
    vi.stubGlobal("indexedDB", undefined);
    expect(await getDraft(store, "e1")).toBeUndefined();
    expect(await setDraft(store, "e1", {})).toBe(false);
    expect(await getSessionRoute(store, "e1")).toBeNull();
    expect(await updateSettings(store, { graph_view: true })).toEqual({
      ...DEFAULT_SETTINGS,
      graph_view: true,
    });
  });
});

describe("DraftSaver", () => {
  // Only the debounce timer is faked; fake-indexeddb schedules its work with setImmediate.
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  });

  it("writes only the latest draft, once the form has been still for the delay", async () => {
    const put = vi.spyOn(store, "putValue");
    const saver = new DraftSaver(store, "e1");
    saver.schedule({ n_archers: "4" });
    await vi.advanceTimersByTimeAsync(DRAFT_DELAY_MS - 100);
    saver.schedule({ n_archers: "45" });
    await vi.advanceTimersByTimeAsync(DRAFT_DELAY_MS - 1);
    expect(put).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(1);
    expect(put).toHaveBeenCalledTimes(1);
    expect(put).toHaveBeenCalledWith(draftKey("e1"), { n_archers: "45" });
    expect(await put.mock.results[0].value).toBe(true);
    expect(await getDraft(store, "e1")).toEqual({ n_archers: "45" });
  });

  it("flush writes the waiting draft at once; with nothing waiting it writes nothing", async () => {
    const put = vi.spyOn(store, "putValue");
    const saver = new DraftSaver(store, "e1", 1000);
    expect(await saver.flush()).toBe(true);
    expect(put).not.toHaveBeenCalled();

    saver.schedule({ scores: { "0": "280" } });
    expect(await saver.flush()).toBe(true);
    expect(await getDraft(store, "e1")).toEqual({ scores: { "0": "280" } });
    await vi.advanceTimersByTimeAsync(2000);
    expect(put).toHaveBeenCalledTimes(1);
  });

  it("cancel drops the waiting draft, so a discarded draft is not written back", async () => {
    await setDraft(store, "e1", { old: true });
    const put = vi.spyOn(store, "putValue");
    const saver = new DraftSaver(store, "e1");
    saver.schedule({ newer: true });

    // The command succeeded: cancel the pending write and discard the draft (rule 8).
    saver.cancel();
    await deleteDraft(store, "e1");
    await vi.advanceTimersByTimeAsync(DRAFT_DELAY_MS * 2);
    expect(put).not.toHaveBeenCalled();
    expect(await getDraft(store, "e1")).toBeUndefined();
  });
});
