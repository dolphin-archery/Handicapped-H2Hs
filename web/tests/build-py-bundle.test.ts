// @vitest-environment node
import { mkdir, mkdtemp, readdir, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { unzipSync } from "fflate";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  BUNDLE_MODULES,
  DEFAULT_OUT_DIR,
  DEFAULT_SOURCE_DIR,
  buildPyBundle,
} from "../scripts/build-py-bundle.mjs";

// Spelled out here (not taken from BUNDLE_MODULES) so the test checks the whitelist itself.
const EXPECTED_ENTRIES = [
  "h2h/__init__.py",
  "h2h/bridge.py",
  "h2h/chart_data.py",
  "h2h/draw.py",
  "h2h/exports.py",
  "h2h/models.py",
  "h2h/outputs.py",
  "h2h/rotation.py",
  "h2h/stats.py",
];

let tmp: string;

beforeEach(async () => {
  tmp = await mkdtemp(path.join(os.tmpdir(), "h2h-bundle-test-"));
});

afterEach(async () => {
  await rm(tmp, { recursive: true, force: true });
});

/**
 * Copy the bundled modules of the real h2h/ package into a temporary directory.
 * @param name Name of the new directory under the test's temporary directory.
 * @param eol Line ending to write the copies with.
 * @returns Absolute path of the copy.
 */
async function copyModules(name: string, eol: "\n" | "\r\n"): Promise<string> {
  const dir = path.join(tmp, name);
  await mkdir(dir, { recursive: true });
  for (const module of BUNDLE_MODULES) {
    const text = await readFile(path.join(DEFAULT_SOURCE_DIR, module), "utf8");
    await writeFile(path.join(dir, module), text.replace(/\r\n/g, "\n").replace(/\n/g, eol));
  }
  return dir;
}

/**
 * List the entry names of a zip file, sorted.
 * @param filePath Path of the zip file.
 * @returns The sorted entry names.
 */
async function zipEntries(filePath: string): Promise<string[]> {
  return Object.keys(unzipSync(await readFile(filePath))).sort();
}

describe("build-py-bundle", () => {
  it("the bundle named by __PY_BUNDLE__ is in public/py and holds exactly the whitelisted modules", async () => {
    expect(__PY_BUNDLE__).toMatch(/^py\/h2h-[0-9a-f]{12}\.zip$/);
    const filePath = path.join(DEFAULT_OUT_DIR, path.basename(__PY_BUNDLE__));
    expect(await zipEntries(filePath)).toEqual(EXPECTED_ENTRIES);
  });

  it("leaves out app.py, state.py, templates/ and static/", async () => {
    const source = await copyModules("src", "\n");
    await writeFile(path.join(source, "app.py"), "import flask\n");
    await writeFile(path.join(source, "state.py"), "STATE = None\n");
    await mkdir(path.join(source, "templates"));
    await writeFile(path.join(source, "templates", "base.html"), "<html></html>\n");
    await mkdir(path.join(source, "static"));
    await writeFile(path.join(source, "static", "match_chart.js"), "// chart\n");

    const bundle = await buildPyBundle({ sourceDir: source, outDir: path.join(tmp, "out") });
    const entries = await zipEntries(bundle.filePath);
    expect(entries).toEqual(EXPECTED_ENTRIES);
    for (const excluded of ["app.py", "state.py", "templates/", "static/"]) {
      expect(entries.some((entry) => entry.includes(excluded))).toBe(false);
    }
  });

  it("gives the same hash and byte-identical zip for identical content", async () => {
    const source = await copyModules("src", "\n");
    const first = await buildPyBundle({ sourceDir: source, outDir: path.join(tmp, "out1") });
    const second = await buildPyBundle({ sourceDir: source, outDir: path.join(tmp, "out2") });
    expect(second.fileName).toBe(first.fileName);
    expect(await readFile(second.filePath)).toEqual(await readFile(first.filePath));
  });

  it("gives the same hash and zip for CRLF and LF copies of the same modules", async () => {
    const lf = await buildPyBundle({
      sourceDir: await copyModules("lf", "\n"),
      outDir: path.join(tmp, "out-lf"),
    });
    const crlf = await buildPyBundle({
      sourceDir: await copyModules("crlf", "\r\n"),
      outDir: path.join(tmp, "out-crlf"),
    });
    expect(crlf.hash).toBe(lf.hash);
    expect(await readFile(crlf.filePath)).toEqual(await readFile(lf.filePath));
  });

  it("changes the hash when a bundled module changes", async () => {
    const source = await copyModules("src", "\n");
    const before = await buildPyBundle({ sourceDir: source, outDir: path.join(tmp, "out") });
    await writeFile(path.join(source, "stats.py"), "# changed\n", { flag: "a" });
    const after = await buildPyBundle({ sourceDir: source, outDir: path.join(tmp, "out") });
    expect(after.hash).not.toBe(before.hash);
    expect(after.fileName).toMatch(/^h2h-[0-9a-f]{12}\.zip$/);
  });

  it("removes older bundles from the output directory", async () => {
    const outDir = path.join(tmp, "out");
    await mkdir(outDir);
    await writeFile(path.join(outDir, "h2h-000000000000.zip"), "old");
    const bundle = await buildPyBundle({ sourceDir: await copyModules("src", "\n"), outDir });
    expect(await readdir(outDir)).toEqual([bundle.fileName]);
  });
});
