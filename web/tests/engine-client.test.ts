// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  EngineClient,
  EngineError,
  type EngineStatus,
  type WorkerLike,
} from "../src/engine/client";
import type { EngineTimings, FromEngine, ToEngine } from "../src/engine/host";

const TIMINGS: EngineTimings = {
  runtime_ms: 1,
  packages_ms: 2,
  app_ms: 4,
  total_ms: 10,
};
const BUNDLE = "http://localhost/py/h2h-test.zip";

/** A scripted stand-in for the engine worker. */
class FakeWorker implements WorkerLike {
  onmessage: ((event: { data: FromEngine }) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  readonly received: ToEngine[] = [];
  terminated = false;

  postMessage(message: ToEngine): void {
    this.received.push(message);
  }

  terminate(): void {
    this.terminated = true;
  }

  /** Send a message to the client, as the engine would. */
  emit(message: FromEngine): void {
    this.onmessage?.({ data: message });
  }

  /** The calls received so far. */
  calls(): Extract<ToEngine, { type: "call" }>[] {
    return this.received.filter((m): m is Extract<ToEngine, { type: "call" }> => m.type === "call");
  }

  /** Answer one call with an ok envelope holding `data`. */
  answer(id: number, data: unknown): void {
    this.emit({ type: "result", id, envelope: JSON.stringify({ ok: true, data }) });
  }
}

/** A client whose workers are FakeWorkers, plus the list of workers it has made. */
function makeClient(options = {}) {
  const workers: FakeWorker[] = [];
  const client = new EngineClient(
    () => {
      const worker = new FakeWorker();
      workers.push(worker);
      return worker;
    },
    BUNDLE,
    options,
  );
  return { client, workers };
}

afterEach(() => {
  vi.useRealTimers();
});

describe("EngineClient", () => {
  it("starts one worker with the bundle URL and reports load progress, then ready", () => {
    const { client, workers } = makeClient();
    const seen: EngineStatus[] = [];
    client.subscribe((status) => seen.push(status));
    client.start();
    client.start(); // already starting: no second worker
    expect(workers).toHaveLength(1);
    expect(workers[0].received).toEqual([{ type: "init", bundleUrl: BUNDLE }]);
    for (const stage of ["packages", "app"] as const)
      workers[0].emit({ type: "progress", stage });
    workers[0].emit({ type: "ready", timings: TIMINGS });
    expect(seen).toEqual([
      { state: "loading", stage: "runtime" },
      { state: "loading", stage: "packages" },
      { state: "loading", stage: "app" },
      { state: "ready", timings: TIMINGS },
    ]);
  });

  it("holds calls until the engine is ready, sending them as JSON text", async () => {
    const { client, workers } = makeClient();
    const answer = client.call("options", {});
    expect(workers[0].calls()).toEqual([]);
    workers[0].emit({ type: "ready", timings: TIMINGS });
    const [sent] = workers[0].calls();
    expect(sent).toEqual({ type: "call", id: sent.id, command: "options", payload: "{}" });
    workers[0].answer(sent.id, { bowstyles: ["Recurve"] });
    await expect(answer).resolves.toEqual({ ok: true, data: { bowstyles: ["Recurve"] } });
  });

  it("gives each of several calls in flight the answer with its own request id", async () => {
    const { client, workers } = makeClient();
    client.start();
    workers[0].emit({ type: "ready", timings: TIMINGS });
    const answers = [1, 2, 3].map((n) =>
      client.call("calculator", {
        kind: "indoor",
        round_codename: "portsmouth",
        compound: false,
        score: n,
      }),
    );
    const ids = workers[0].calls().map((call) => call.id);
    expect(new Set(ids).size).toBe(3);
    for (const [i, id] of [...ids.entries()].reverse()) workers[0].answer(id, `answer ${i}`); // out of order
    await expect(Promise.all(answers)).resolves.toEqual(
      [0, 1, 2].map((i) => ({ ok: true, data: `answer ${i}` })),
    );
  });

  it("passes error envelopes through unchanged", async () => {
    const { client, workers } = makeClient();
    client.start();
    workers[0].emit({ type: "ready", timings: TIMINGS });
    const answer = client.call("advance", { doc: {} as never });
    const error = { ok: false, error: { code: "state", message: "This is the final pass." } };
    workers[0].emit({
      type: "result",
      id: workers[0].calls()[0].id,
      envelope: JSON.stringify(error),
    });
    await expect(answer).resolves.toEqual(error);
  });

  it("rejects a call that is not answered in time and replaces the hung engine", async () => {
    vi.useFakeTimers();
    const { client, workers } = makeClient({ callTimeoutMs: 1_000 });
    client.start();
    workers[0].emit({ type: "ready", timings: TIMINGS });
    const answer = client.call("options", {});
    const outcome = expect(answer).rejects.toMatchObject({
      name: "EngineError",
      reason: "timeout",
    });
    vi.advanceTimersByTime(1_001);
    await outcome;
    expect(workers[0].terminated).toBe(true);
    expect(client.getStatus().state).toBe("failed");
    const next = client.call("options", {}); // a fresh engine
    expect(workers).toHaveLength(2);
    workers[1].emit({ type: "ready", timings: TIMINGS });
    workers[1].answer(workers[1].calls()[0].id, "fresh");
    await expect(next).resolves.toEqual({ ok: true, data: "fresh" });
  });

  it("rejects calls in flight when the worker crashes, and restarts it for the next call", async () => {
    const { client, workers } = makeClient();
    client.start();
    workers[0].emit({ type: "ready", timings: TIMINGS });
    const lost = client.call("options", {});
    workers[0].onerror?.({ message: "out of memory" });
    await expect(lost).rejects.toEqual(
      new EngineError("crashed", "The engine stopped unexpectedly (out of memory)."),
    );
    expect(client.getStatus()).toEqual({
      state: "failed",
      message: "The engine stopped unexpectedly (out of memory).",
    });
    expect(workers[0].terminated).toBe(true);
    const next = client.call("options", {});
    expect(workers).toHaveLength(2);
    workers[1].emit({ type: "ready", timings: TIMINGS });
    workers[1].answer(workers[1].calls()[0].id, "after restart");
    await expect(next).resolves.toEqual({ ok: true, data: "after restart" });
  });

  it("fails a call waiting for an engine that cannot start (for example offline), then retries on start()", async () => {
    const { client, workers } = makeClient();
    const waiting = client.call("options", {});
    workers[0].emit({ type: "fatal", message: "Failed to fetch" });
    await expect(waiting).rejects.toMatchObject({ reason: "crashed", message: "Failed to fetch" });
    expect(client.getStatus()).toEqual({ state: "failed", message: "Failed to fetch" });
    client.start(); // the Retry button
    expect(workers).toHaveLength(2);
    expect(client.getStatus()).toEqual({ state: "loading", stage: "runtime" });
  });

  it("fails an engine that takes too long to start", () => {
    vi.useFakeTimers();
    const { client } = makeClient({ startTimeoutMs: 5_000 });
    client.start();
    vi.advanceTimersByTime(5_001);
    expect(client.getStatus()).toEqual({
      state: "failed",
      message: "The engine took too long to start.",
    });
  });

  it("ignores messages from a worker it has replaced", async () => {
    const { client, workers } = makeClient();
    client.start();
    workers[0].onerror?.("boom");
    const next = client.call("options", {});
    workers[0].emit({ type: "ready", timings: TIMINGS }); // the old worker: ignored
    expect(client.getStatus().state).toBe("loading");
    workers[1].emit({ type: "ready", timings: TIMINGS });
    workers[1].answer(workers[1].calls()[0].id, "new");
    await expect(next).resolves.toEqual({ ok: true, data: "new" });
  });

  it("refuses calls after dispose", async () => {
    const { client } = makeClient();
    client.dispose();
    await expect(client.call("options", {})).rejects.toMatchObject({ reason: "disposed" });
  });
});
