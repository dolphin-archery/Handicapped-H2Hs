// Build the browser Python bundle (UISpec.md section 4.3, task UI-6).
//
// Zips the whitelisted h2h modules into web/public/py/h2h-<hash>.zip. <hash> is the first 12 hex
// characters of a SHA-256 over the module names and contents with line endings normalised to LF,
// so a Windows (CRLF) checkout and Linux CI produce the same hash and the same zip. Entries are
// stored as h2h/<module> in a fixed order with a fixed timestamp, so the zip is reproducible
// byte for byte. Older h2h-*.zip bundles in the output directory are removed.
//
// Usage, from web/:
//   node scripts/build-py-bundle.mjs
// vite.config.ts also calls buildPyBundle() and compiles the bundle URL into the app as
// __PY_BUNDLE__, so `npm run dev`, `npm run build` and the tests always see the current bundle.

import { createHash } from "node:crypto";
import { mkdir, readdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { zipSync } from "fflate";

/** The h2h modules shipped to the browser; never app.py, state.py, templates/ or static/. */
export const BUNDLE_MODULES = Object.freeze([
  "__init__.py",
  "stats.py",
  "rotation.py",
  "models.py",
  "outputs.py",
  "exports.py",
  "chart_data.py",
  "draw.py",
  "bridge.py",
]);

const webDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

/** The repository's h2h/ package directory. */
export const DEFAULT_SOURCE_DIR = path.resolve(webDir, "..", "h2h");

/** web/public/py, which Vite copies into dist/py. */
export const DEFAULT_OUT_DIR = path.join(webDir, "public", "py");

// Zip entry timestamps are stored as local DOS time, which fflate reads with local-time getters.
// Building the date from local components stores the same fields in every time zone; midday
// avoids daylight-saving gaps.
const FIXED_MTIME = new Date(1980, 0, 1, 12, 0, 0);
const BUNDLE_FILE_PATTERN = /^h2h-[0-9a-f]{12}\.zip$/;

/**
 * Build the content-hashed Python bundle and remove older bundles from the output directory.
 * @param {object} [options] Optional directories, used by tests.
 * @param {string} [options.sourceDir] Directory holding the h2h modules (default: the repository's h2h/).
 * @param {string} [options.outDir] Directory the zip is written to (default: web/public/py).
 * @returns {Promise<{fileName: string, hash: string, filePath: string, url: string, size: number}>}
 *   The zip's file name (`h2h-<hash>.zip`), the 12-character hash, the absolute path written,
 *   the URL relative to the site root (`py/<fileName>`) and the zip size in bytes.
 */
export async function buildPyBundle({
  sourceDir = DEFAULT_SOURCE_DIR,
  outDir = DEFAULT_OUT_DIR,
} = {}) {
  const hasher = createHash("sha256");
  /** @type {Record<string, Uint8Array>} */
  const entries = {};
  for (const name of BUNDLE_MODULES) {
    const text = (await readFile(path.join(sourceDir, name), "utf8")).replace(/\r\n/g, "\n");
    const bytes = Buffer.from(text, "utf8");
    hasher.update(`${name}\0${bytes.length}\0`);
    hasher.update(bytes);
    entries[`h2h/${name}`] = bytes;
  }
  const hash = hasher.digest("hex").slice(0, 12);
  const fileName = `h2h-${hash}.zip`;
  const zip = zipSync(entries, { level: 9, mtime: FIXED_MTIME });

  await mkdir(outDir, { recursive: true });
  const filePath = path.join(outDir, fileName);
  await writeFile(filePath, zip);
  for (const existing of await readdir(outDir)) {
    if (existing !== fileName && BUNDLE_FILE_PATTERN.test(existing)) {
      await rm(path.join(outDir, existing));
    }
  }
  return { fileName, hash, filePath, url: `py/${fileName}`, size: zip.length };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const bundle = await buildPyBundle();
  console.log(`Python bundle: ${path.relative(webDir, bundle.filePath)} (${bundle.size} bytes)`);
}
