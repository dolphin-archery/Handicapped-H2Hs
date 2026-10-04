// Pyodide compatibility gate (UISpec.md section 8, task UI-1).
//
// Loads the pinned Pyodide under Node, loads numpy, installs archeryutils and fpdf2 with
// micropip (the exact versions recorded in golden.json, so only the runtime differs), writes
// the whitelisted h2h modules into the Pyodide file system, runs scenario.py and compares its
// output with golden.json (ints and strings exactly, floats within a relative 1e-9).
//
// Usage, from the repository root after `npm ci` in web/:
//   node web/scripts/pyodide-gate/run-gate.mjs
// Exit code 0 when the gate passes, 1 when it fails.

import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadPyodide, version } from "pyodide";

const PYODIDE_VERSION = "314.0.7";
const H2H_MODULES = [
  "__init__.py",
  "stats.py",
  "rotation.py",
  "models.py",
  "outputs.py",
  "exports.py",
  "chart_data.py",
];
const GATE_DIR = "/home/pyodide/gate";

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, "..", "..", "..");

/**
 * Seconds elapsed since a `performance.now()` reading, to one decimal place.
 * @param {number} start The earlier reading, in milliseconds.
 * @returns {string} The elapsed time, e.g. "3.2".
 */
function secondsSince(start) {
  return ((performance.now() - start) / 1000).toFixed(1);
}

/**
 * Run the gate and print its report.
 * @returns {Promise<boolean>} Whether the gate passed.
 */
async function runGate() {
  if (version !== PYODIDE_VERSION) {
    console.error(`Expected pyodide ${PYODIDE_VERSION} from npm, found ${version}.`);
    return false;
  }
  const goldenText = await readFile(path.join(here, "golden.json"), "utf8");
  const goldenEnv = JSON.parse(goldenText).environment;

  const start = performance.now();
  const pyodide = await loadPyodide();
  console.log(`Pyodide ${version} loaded in ${secondsSince(start)} s.`);

  let step = performance.now();
  await pyodide.loadPackage(["numpy", "micropip"], { messageCallback: () => {} });
  const micropip = pyodide.pyimport("micropip");
  await micropip.install([
    `archeryutils==${goldenEnv.archeryutils}`,
    `fpdf2==${goldenEnv.fpdf2}`,
  ]);
  console.log(`numpy, archeryutils and fpdf2 ready in ${secondsSince(step)} s.`);

  pyodide.FS.mkdirTree(`${GATE_DIR}/h2h`);
  for (const name of H2H_MODULES) {
    const source = await readFile(path.join(repoRoot, "h2h", name), "utf8");
    pyodide.FS.writeFile(`${GATE_DIR}/h2h/${name}`, source);
  }
  pyodide.FS.writeFile(`${GATE_DIR}/scenario.py`, await readFile(path.join(here, "scenario.py"), "utf8"));
  pyodide.runPython(`import sys; sys.path.insert(0, ${JSON.stringify(GATE_DIR)})`);

  step = performance.now();
  const scenario = pyodide.pyimport("scenario");
  console.log(`h2h modules imported in ${secondsSince(step)} s.`);

  step = performance.now();
  const actualText = scenario.result_json();
  console.log(`Scenario ran in Pyodide in ${secondsSince(step)} s.`);

  const report = JSON.parse(scenario.compare_json(goldenText, actualText));
  const actual = JSON.parse(actualText);
  const pdfHeaders = ["simple", "advanced"].map((name) => actual.outputs[name].pdf.header);
  const pdfOk = pdfHeaders.every((header) => header.startsWith("%PDF-"));

  console.log("Native (golden):", JSON.stringify(report.golden_environment));
  console.log("Pyodide:        ", JSON.stringify(report.actual_environment));
  console.log(`Floats compared: ${report.floats_compared}; largest relative difference: ${report.max_relative_difference}`);
  console.log(`PDF headers in Pyodide: ${pdfHeaders.join(", ")}`);
  for (const mismatch of report.mismatches) console.log(`MISMATCH ${mismatch}`);

  const passed = report.mismatches.length === 0 && pdfOk;
  console.log(passed ? "GATE PASSED" : `GATE FAILED (${report.mismatches.length} mismatches)`);
  console.log(`Total time ${secondsSince(start)} s.`);
  return passed;
}

runGate().then(
  (passed) => process.exit(passed ? 0 : 1),
  (error) => {
    console.error(error);
    console.log("GATE FAILED (error)");
    process.exit(1);
  },
);
