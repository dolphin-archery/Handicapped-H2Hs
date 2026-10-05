// @vitest-environment node
/**
 * Pyodide parity (UISpec.md 8, task UI-7): the real engine host runs under Node with the pinned
 * `pyodide` npm package and the hashed Python bundle, and every UI-5 fixture step sent through
 * the client gives the committed native-Python result. Needs network access on the first run
 * (Pyodide's packages from jsDelivr, archeryutils and fpdf2 from PyPI).
 */
import { readFile, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { loadPyodide, version } from "pyodide";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import requirementsText from "../pyodide-requirements.txt?raw";
import { buildPyBundle } from "../scripts/build-py-bundle.mjs";
import { EngineClient, type EngineStatus, type WorkerLike } from "../src/engine/client";
import {
  createEngineHost,
  parseRequirements,
  PYODIDE_VERSION,
  type FromEngine,
  type ToEngine,
} from "../src/engine/host";
import type { CommandName, PayloadOf } from "../src/engine/types";
import { compareJson, loadFixtures, normaliseResult, type Comparison } from "./bridgeFixtures";

/**
 * A worker stand-in that runs the engine host in this process (Node has no Web Workers).
 *
 * @returns The worker.
 */
function inProcessWorker(): WorkerLike {
  const worker: WorkerLike = {
    onmessage: null,
    onerror: null,
    postMessage(message: ToEngine) {
      setTimeout(() => void handle(message).catch((error: unknown) => worker.onerror?.(error)));
    },
    terminate() {},
  };
  const handle = createEngineHost({
    loadPyodide: (options) => loadPyodide(options),
    requirements: parseRequirements(requirementsText),
    fetchBundle: async (file) => {
      const bytes = await readFile(file);
      return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    },
    post: (message: FromEngine) => worker.onmessage?.({ data: message }),
  });
  return worker;
}

let client: EngineClient;
let outDir: string;
const statuses: EngineStatus[] = [];

beforeAll(async () => {
  outDir = await mkdtemp(path.join(tmpdir(), "h2h-bundle-"));
  const bundle = await buildPyBundle({ outDir });
  client = new EngineClient(inProcessWorker, bundle.filePath, {
    startTimeoutMs: 600_000,
    callTimeoutMs: 120_000,
  });
  client.subscribe((status) => statuses.push(status));
  client.start();
  await new Promise<void>((resolve, reject) => {
    const stop = client.subscribe((status) => {
      if (status.state === "ready") resolve();
      if (status.state === "failed") reject(new Error(status.message));
    });
    if (client.getStatus().state === "ready") {
      stop();
      resolve();
    }
  });
}, 600_000);

afterAll(async () => {
  client?.dispose();
  if (outDir) await rm(outDir, { recursive: true, force: true });
});

describe("the engine under Node Pyodide", () => {
  it("is the pinned Pyodide release", () => {
    expect(version).toBe(PYODIDE_VERSION);
  });

  it("reported every load stage, then ready with its timings", () => {
    expect(statuses.map((s) => (s.state === "loading" ? s.stage : s.state))).toEqual([
      "runtime",
      "packages",
      "app",
      "ready",
    ]);
    const ready = statuses.at(-1);
    if (ready?.state !== "ready") throw new Error("not ready");
    console.log("Engine start under Node (ms):", JSON.stringify(ready.timings));
    expect(ready.timings.total_ms).toBeGreaterThan(0);
  });

  const totals: Comparison = { mismatches: [], floatsCompared: 0, maxRelativeDifference: 0 };

  for (const fixture of loadFixtures()) {
    it(`reproduces the "${fixture.scenario}" fixture step by step`, async () => {
      const before = totals.mismatches.length;
      for (const [i, step] of fixture.steps.entries()) {
        const result = await client.call(
          step.command as CommandName,
          step.payload as PayloadOf<CommandName>,
        );
        compareJson(
          step.result,
          normaliseResult(step, result),
          `${fixture.scenario}[${i}] ${step.command}`,
          totals,
        );
      }
      expect(totals.mismatches.slice(before)).toEqual([]);
    }, 300_000);
  }

  it("matched every float within the tolerance (and logs the largest difference)", () => {
    console.log(
      `Parity: ${totals.floatsCompared} non-integer numbers compared; largest relative difference ${totals.maxRelativeDifference}.`,
    );
    expect(totals.floatsCompared).toBeGreaterThan(0);
    expect(totals.mismatches).toEqual([]);
  });
});
