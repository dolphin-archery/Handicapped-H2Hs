/**
 * The app's one engine client, backed by the module Web Worker.
 */
import { EngineClient, type WorkerLike } from "./client";

let engine: EngineClient | null = null;

/**
 * The shared engine client, created (but not started) on first use.
 *
 * @returns The client; call `start()` to begin loading Python in the background.
 */
export function getEngine(): EngineClient {
  engine ??= new EngineClient(
    () =>
      new Worker(new URL("./worker.ts", import.meta.url), {
        type: "module",
      }) as unknown as WorkerLike,
    // Resolved here: a worker would resolve a relative URL against its own script in assets/.
    new URL(__PY_BUNDLE__, document.baseURI).href,
  );
  return engine;
}
