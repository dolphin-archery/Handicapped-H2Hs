/**
 * Typed client for the Python engine running in a Web Worker (UISpec.md 4, 5.1, 7.6).
 *
 * `call(command, payload)` sends JSON text with a request id and resolves with the bridge's
 * envelope. The client starts the worker on demand, reports load progress, holds calls until
 * the engine is ready, times calls out, and replaces a worker that crashed, failed to start or
 * hung, so a later call starts a fresh engine. Stored data is never involved: the engine is
 * stateless (UISpec.md 4).
 */
import type { EngineTimings, FromEngine, LoadStage, ToEngine } from "./host";
import type { CommandName, Envelope, PayloadOf, ResultOf } from "./types";

/** The part of the Web Worker API the client uses (so tests can supply a stand-in). */
export interface WorkerLike {
  postMessage(message: ToEngine): void;
  terminate(): void;
  onmessage: ((event: { data: FromEngine }) => void) | null;
  onerror: ((event: unknown) => void) | null;
}

/** The engine's state, for the loading banner and the failure message. */
export type EngineStatus =
  | { state: "idle" }
  | { state: "loading"; stage: LoadStage }
  | { state: "ready"; timings: EngineTimings }
  | { state: "failed"; message: string };

/** Why a call did not get an answer from the engine. */
export class EngineError extends Error {
  readonly reason: "timeout" | "crashed" | "disposed";

  /**
   * @param reason - "timeout" (no answer in time), "crashed" (the engine failed or stopped
   *   before answering) or "disposed" (the client was shut down).
   * @param message - Text for the user.
   */
  constructor(reason: "timeout" | "crashed" | "disposed", message: string) {
    super(message);
    this.name = "EngineError";
    this.reason = reason;
  }
}

export interface EngineClientOptions {
  /** How long one call may take once sent, in ms (default 60 s). */
  callTimeoutMs?: number;
  /** How long engine start may take, in ms (default 180 s; first visits download about 11 MB). */
  startTimeoutMs?: number;
}

interface Pending {
  command: string;
  payload: string;
  resolve: (envelope: Envelope<unknown>) => void;
  reject: (error: EngineError) => void;
  timer?: ReturnType<typeof setTimeout>;
}

export class EngineClient {
  private worker: WorkerLike | null = null;
  private status: EngineStatus = { state: "idle" };
  private readonly listeners = new Set<(status: EngineStatus) => void>();
  private readonly pending = new Map<number, Pending>();
  private nextId = 1;
  private startTimer?: ReturnType<typeof setTimeout>;
  private disposed = false;
  private readonly createWorker: () => WorkerLike;
  private readonly bundleUrl: string;
  private readonly options: EngineClientOptions;

  /**
   * @param createWorker - Makes a new worker (a module Web Worker in the browser).
   * @param bundleUrl - Absolute URL of the hashed Python bundle.
   * @param options - Timeouts.
   */
  constructor(
    createWorker: () => WorkerLike,
    bundleUrl: string,
    options: EngineClientOptions = {},
  ) {
    this.createWorker = createWorker;
    this.bundleUrl = bundleUrl;
    this.options = options;
  }

  /** The current engine status. */
  getStatus(): EngineStatus {
    return this.status;
  }

  /**
   * Listen to status changes.
   *
   * @param listener - Called with every new status.
   * @returns A function that stops listening.
   */
  subscribe(listener: (status: EngineStatus) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /** Start the engine if it is not running or starting (a failed engine is started afresh). */
  start(): void {
    if (this.disposed || (this.worker !== null && this.status.state !== "failed")) return;
    this.stopWorker();
    const worker = this.createWorker();
    this.worker = worker;
    worker.onmessage = (event) => this.receive(worker, event.data);
    worker.onerror = (event) =>
      this.fail(worker, `The engine stopped unexpectedly (${describe(event)}).`);
    this.setStatus({ state: "loading", stage: "runtime" });
    this.startTimer = setTimeout(
      () => this.fail(worker, "The engine took too long to start."),
      this.options.startTimeoutMs ?? 180_000,
    );
    worker.postMessage({ type: "init", bundleUrl: this.bundleUrl });
  }

  /**
   * Run one bridge command.
   *
   * @param command - The command name.
   * @param payload - Its arguments (sent as JSON text).
   * @returns The bridge's envelope. Rejects with an `EngineError` if the engine times out,
   *   crashes or fails to start before answering (the engine is then replaced on the next call).
   */
  call<C extends CommandName>(command: C, payload: PayloadOf<C>): Promise<Envelope<ResultOf<C>>> {
    if (this.disposed)
      return Promise.reject(new EngineError("disposed", "The engine has been shut down."));
    this.start();
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, {
        command,
        payload: JSON.stringify(payload),
        resolve: resolve as (envelope: Envelope<unknown>) => void,
        reject,
      });
      if (this.status.state === "ready") this.send(id);
    });
  }

  /** Stop the engine and refuse further calls. */
  dispose(): void {
    this.disposed = true;
    this.rejectAll(new EngineError("disposed", "The engine has been shut down."));
    this.stopWorker();
  }

  private send(id: number): void {
    const request = this.pending.get(id);
    if (request === undefined || this.worker === null) return;
    const worker = this.worker;
    request.timer = setTimeout(() => {
      this.pending.delete(id);
      request.reject(
        new EngineError("timeout", `The engine did not answer "${request.command}" in time.`),
      );
      this.fail(worker, "The engine stopped answering.");
    }, this.options.callTimeoutMs ?? 60_000);
    worker.postMessage({ type: "call", id, command: request.command, payload: request.payload });
  }

  private receive(worker: WorkerLike, message: FromEngine): void {
    if (worker !== this.worker) return; // a message from a replaced worker
    switch (message.type) {
      case "progress":
        // start() already announced the first stage; report each stage once.
        if (this.status.state !== "loading" || this.status.stage !== message.stage) {
          this.setStatus({ state: "loading", stage: message.stage });
        }
        break;
      case "ready":
        clearTimeout(this.startTimer);
        this.setStatus({ state: "ready", timings: message.timings });
        for (const id of this.pending.keys()) this.send(id);
        break;
      case "result": {
        const request = this.pending.get(message.id);
        if (request === undefined) break;
        clearTimeout(request.timer);
        this.pending.delete(message.id);
        request.resolve(JSON.parse(message.envelope) as Envelope<unknown>);
        break;
      }
      case "fatal":
        this.fail(worker, message.message);
        break;
    }
  }

  private fail(worker: WorkerLike, message: string): void {
    if (worker !== this.worker) return;
    this.rejectAll(new EngineError("crashed", message));
    this.stopWorker();
    this.setStatus({ state: "failed", message });
  }

  private rejectAll(error: EngineError): void {
    for (const request of this.pending.values()) {
      clearTimeout(request.timer);
      request.reject(error);
    }
    this.pending.clear();
  }

  private stopWorker(): void {
    clearTimeout(this.startTimer);
    if (this.worker !== null) {
      this.worker.onmessage = null;
      this.worker.onerror = null;
      this.worker.terminate();
      this.worker = null;
    }
  }

  private setStatus(status: EngineStatus): void {
    this.status = status;
    for (const listener of this.listeners) listener(status);
  }
}

/**
 * A short description of a worker error event.
 *
 * @param event - The `error` event (an ErrorEvent in browsers) or anything else.
 * @returns Its message, or a generic text.
 */
function describe(event: unknown): string {
  if (event instanceof Error) return event.message;
  if (typeof event === "object" && event !== null && "message" in event)
    return String(event.message);
  return "no details";
}
