/**
 * The Python engine's message handler, independent of where it runs (UISpec.md 4, 5.1).
 *
 * The browser runs it inside a module Web Worker (worker.ts); the Vitest parity tests run it
 * in-process under Node with the `pyodide` npm package. It loads Pyodide, numpy and micropip,
 * installs archeryutils, unpacks the hashed Python bundle and then answers calls with
 * `h2h.bridge.call`, passing JSON text both ways. Python keeps no state between calls. fpdf2
 * (with pillow and fonttools, about 2.5 MB) is installed only before the first PDF export
 * (decision D16), so engine start does not wait for it.
 */
import type { PyodideAPI } from "pyodide";

/** The Pyodide release, pinned (deploymentConstrains 4, rule 2); the npm package matches it. */
export const PYODIDE_VERSION = "314.0.7";
/** Where the browser loads Pyodide and its own packages from (decision D15). */
export const PYODIDE_CDN = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;

/** Where the bundle is unpacked inside Pyodide's file system (added to sys.path). */
const APP_DIR = "/home/pyodide/app";

/** The stages of engine start, in order, reported as progress. */
export type LoadStage = "runtime" | "packages" | "app";

/** How long each part of engine start took, in milliseconds (logged for UI-7, decision D16). */
export interface EngineTimings {
  runtime_ms: number;
  packages_ms: number;
  app_ms: number;
  total_ms: number;
}

/** Messages from the client to the engine. */
export type ToEngine =
  | { type: "init"; bundleUrl: string }
  | { type: "call"; id: number; command: string; payload: string };

/** Messages from the engine to the client. */
export type FromEngine =
  | { type: "progress"; stage: LoadStage }
  | { type: "ready"; timings: EngineTimings }
  | { type: "result"; id: number; envelope: string }
  | { type: "fatal"; message: string };

/** What the host needs from its surroundings. */
export interface HostOptions {
  /** Pyodide's loader (from the CDN in the browser, from the npm package under Node). */
  loadPyodide: (options: { indexURL?: string }) => Promise<PyodideAPI>;
  /** Where Pyodide's own files come from; undefined lets the loader decide (Node). */
  indexURL?: string;
  /** micropip requirements, e.g. ["archeryutils>=3.0.0", "fpdf2>=2.8.9"]. */
  requirements: string[];
  /** Fetches the Python bundle (a zip) from its URL. */
  fetchBundle: (url: string) => Promise<ArrayBuffer>;
  /** Sends a message to the client. */
  post: (message: FromEngine) => void;
  /** A millisecond clock (performance.now by default). */
  now?: () => number;
}

/**
 * Build the engine's message handler.
 *
 * @param options - The loader, requirements, bundle fetcher and message sender.
 * @returns A function to call with each message from the client. Calls that arrive while the
 *   engine is starting wait for it; an unexpected Python exception is answered with an
 *   `internal` error envelope (bridge.call already turns its own failures into envelopes).
 */
export function createEngineHost(options: HostOptions): (message: ToEngine) => Promise<void> {
  const now = options.now ?? (() => performance.now());
  let starting: Promise<((command: string, payload: string) => string) | null> | null = null;
  let micropip: { install: (requirements: string[]) => Promise<void> } | null = null;
  let pdfReady: Promise<void> | null = null;
  const pdfRequirements = options.requirements.filter((r) => r.startsWith("fpdf2"));

  async function start(bundleUrl: string): Promise<(command: string, payload: string) => string> {
    const t0 = now();
    options.post({ type: "progress", stage: "runtime" });
    // An explicit `indexURL: undefined` would replace the loader's own default, so leave it out.
    const pyodide = await options.loadPyodide(
      options.indexURL === undefined ? {} : { indexURL: options.indexURL },
    );
    const t1 = now();

    options.post({ type: "progress", stage: "packages" });
    await pyodide.loadPackage(["numpy", "micropip"], { messageCallback: () => {} });
    micropip = pyodide.pyimport("micropip") as typeof micropip;
    await micropip!.install(options.requirements.filter((r) => !r.startsWith("fpdf2")));
    const t2 = now();

    options.post({ type: "progress", stage: "app" });
    const bundle = await options.fetchBundle(bundleUrl);
    pyodide.unpackArchive(bundle, "zip", { extractDir: APP_DIR });
    pyodide.runPython(
      `import sys\nif ${JSON.stringify(APP_DIR)} not in sys.path: sys.path.insert(0, ${JSON.stringify(APP_DIR)})`,
    );
    const bridge = pyodide.pyimport("h2h.bridge");
    const t3 = now();

    options.post({
      type: "ready",
      timings: {
        runtime_ms: t1 - t0,
        packages_ms: t2 - t1,
        app_ms: t3 - t2,
        total_ms: t3 - t0,
      },
    });
    return (command, payload) => bridge.call(command, payload) as string;
  }

  return async (message) => {
    if (message.type === "init") {
      starting ??= start(message.bundleUrl).catch((error: unknown) => {
        options.post({ type: "fatal", message: describe(error) });
        return null;
      });
      await starting;
      return;
    }
    const call = starting === null ? null : await starting;
    if (call === null) {
      options.post({ type: "fatal", message: "The engine has not started." });
      return;
    }
    let envelope: string;
    try {
      if (needsPdf(message)) {
        pdfReady ??= micropip!.install(pdfRequirements).catch((error: unknown) => {
          pdfReady = null; // let a later export try again, e.g. after the network returns
          throw error;
        });
        await pdfReady;
      }
      envelope = call(message.command, message.payload);
    } catch (error) {
      envelope = JSON.stringify({
        ok: false,
        error: { code: "internal", message: describe(error) },
      });
    }
    options.post({ type: "result", id: message.id, envelope });
  };
}

/**
 * Whether a call is a PDF export, which needs fpdf2 installed first.
 *
 * @param message - A call from the client.
 * @returns True for the `export` command with kind `results_pdf`.
 */
function needsPdf(message: { command: string; payload: string }): boolean {
  if (message.command !== "export") return false;
  try {
    return (JSON.parse(message.payload) as { kind?: unknown }).kind === "results_pdf";
  } catch {
    return false; // the bridge answers malformed JSON with a validation error
  }
}

/**
 * Read `pyodide-requirements.txt`: one requirement per line; blank lines and # comments ignored.
 *
 * @param text - The file's text.
 * @returns The requirements, e.g. ["archeryutils>=3.0.0", "fpdf2>=2.8.9"].
 */
export function parseRequirements(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map((line) => line.replace(/#.*/, "").trim())
    .filter((line) => line.length > 0);
}

/**
 * A readable description of a thrown value.
 *
 * @param error - Anything thrown.
 * @returns Its message, or its text form.
 */
function describe(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
