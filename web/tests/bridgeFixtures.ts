/**
 * The UI-5 bridge fixtures (tests/fixtures/bridge/*.json at the repository root) and the rules
 * for comparing a result with them, shared by the parity tests (UI-7) and later view tests.
 *
 * Comparison: integers, strings, booleans and null exactly; other numbers within a relative
 * 1e-9; a PDF export after the fixtures' normalisation (`pdfSummary`, mirroring
 * `tests/bridge_fixtures.py`).
 */
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { unzlibSync } from "fflate";

export const FIXTURE_DIR = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
  "..",
  "tests",
  "fixtures",
  "bridge",
);

/** Relative tolerance for non-integer numbers (UISpec.md 8, UI-1 and UI-7). */
export const REL_TOLERANCE = 1e-9;

export interface FixtureStep {
  command: string;
  payload: Record<string, unknown>;
  result: unknown;
}

export interface Fixture {
  scenario: string;
  description: string;
  now_iso: string;
  seed: number;
  steps: FixtureStep[];
}

/**
 * Every committed fixture, by scenario name.
 *
 * @returns The fixtures in file-name order.
 */
export function loadFixtures(): Fixture[] {
  return readdirSync(FIXTURE_DIR)
    .filter((name) => name.endsWith(".json"))
    .sort()
    .map((name) => JSON.parse(readFileSync(path.join(FIXTURE_DIR, name), "utf8")) as Fixture);
}

/** Decode Latin-1 bytes to text. */
function latin1(bytes: Uint8Array): string {
  let text = "";
  for (const byte of bytes) text += String.fromCharCode(byte);
  return text;
}

/**
 * Summarise a PDF as the fixtures do: header, page count and every string drawn with `Tj`.
 *
 * @param base64 - The PDF bytes in base64 (as the `export` command returns them).
 * @returns `{header, pages, text}`, equal to Python's `pdf_summary` for the same file.
 */
export function pdfSummary(base64: string): { header: string; pages: number; text: string[] } {
  const pdf = latin1(Uint8Array.from(atob(base64), (c) => c.charCodeAt(0)));
  const text: string[] = [];
  for (const match of pdf.matchAll(/stream\r?\n([\s\S]*?)\r?\nendstream/g)) {
    const raw = Uint8Array.from(match[1], (c) => c.charCodeAt(0));
    let content: string;
    try {
      content = latin1(unzlibSync(raw));
    } catch {
      content = match[1]; // an uncompressed stream
    }
    for (const shown of content.matchAll(/\(((?:\\[\s\S]|[^\\)])*)\)\s*Tj/g)) {
      text.push(shown[1].replace(/\\([()\\r])/g, (_, c: string) => (c === "r" ? "\r" : c)));
    }
  }
  return {
    header: pdf.slice(0, 8),
    pages: (pdf.match(/\/Type\s*\/Page\b/g) ?? []).length,
    text,
  };
}

/**
 * Apply the fixtures' normalisation to a command's result: a successful PDF export's content
 * becomes its `pdfSummary`.
 *
 * @param step - The fixture step (for the command and payload).
 * @param result - The envelope the engine returned.
 * @returns The result to compare with `step.result`.
 */
export function normaliseResult(step: FixtureStep, result: unknown): unknown {
  const envelope = result as { ok: boolean; data?: Record<string, unknown> };
  if (step.command === "export" && step.payload.kind === "results_pdf" && envelope.ok) {
    const data = envelope.data as { content: string };
    return { ...envelope, data: { ...data, content: pdfSummary(data.content) } };
  }
  return result;
}

export interface Comparison {
  mismatches: string[];
  floatsCompared: number;
  maxRelativeDifference: number;
}

/**
 * Compare two decoded JSON values under the fixtures' rules.
 *
 * @param expected - The fixture value.
 * @param actual - The value to check.
 * @param where - Path for messages.
 * @param into - Running totals, updated in place.
 * @returns `into`.
 */
export function compareJson(
  expected: unknown,
  actual: unknown,
  where = "result",
  into: Comparison = { mismatches: [], floatsCompared: 0, maxRelativeDifference: 0 },
): Comparison {
  if (typeof expected === "number" && typeof actual === "number") {
    if (!Number.isInteger(expected) || !Number.isInteger(actual)) {
      into.floatsCompared += 1;
      const relative =
        expected === actual
          ? 0
          : Math.abs(expected - actual) / Math.max(Math.abs(expected), Math.abs(actual));
      into.maxRelativeDifference = Math.max(into.maxRelativeDifference, relative);
      if (relative > REL_TOLERANCE)
        into.mismatches.push(`${where}: ${expected} != ${actual} (relative ${relative})`);
    } else if (expected !== actual) {
      into.mismatches.push(`${where}: ${expected} != ${actual}`);
    }
  } else if (Array.isArray(expected) && Array.isArray(actual)) {
    if (expected.length !== actual.length)
      into.mismatches.push(`${where}: length ${expected.length} != ${actual.length}`);
    expected.forEach((item, i) => compareJson(item, actual[i], `${where}[${i}]`, into));
  } else if (isObject(expected) && isObject(actual)) {
    const keys = new Set([...Object.keys(expected), ...Object.keys(actual)]);
    for (const key of keys) {
      if (!(key in expected) || !(key in actual))
        into.mismatches.push(`${where}.${key}: present on one side only`);
      else compareJson(expected[key], actual[key], `${where}.${key}`, into);
    }
  } else if (expected !== actual) {
    into.mismatches.push(`${where}: ${JSON.stringify(expected)} != ${JSON.stringify(actual)}`);
  }
  return into;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
