// @vitest-environment node
import { zlibSync } from "fflate";
import { describe, expect, it } from "vitest";
import { compareJson, loadFixtures, normaliseResult, pdfSummary } from "./bridgeFixtures";

describe("compareJson (the fixture comparison rules)", () => {
  const base = { a: 1, b: 0.1234567890123, c: ["x", true, null], d: { e: 2.5 } };

  it("accepts an identical value and a float within 1e-9 relative", () => {
    expect(compareJson(base, structuredClone(base)).mismatches).toEqual([]);
    expect(compareJson(base, { ...base, b: base.b * (1 + 1e-10) }).mismatches).toEqual([]);
  });

  it.each([
    ["a float beyond 1e-9", { ...base, b: base.b * (1 + 1e-8) }],
    ["a changed integer", { ...base, a: 2 }],
    ["a changed string", { ...base, c: ["y", true, null] }],
    ["a changed boolean", { ...base, c: ["x", false, null] }],
    ["null replaced", { ...base, c: ["x", true, 0] }],
    ["a shorter list", { ...base, c: ["x", true] }],
    ["a missing key", { a: 1, b: base.b, c: base.c }],
    ["an extra key", { ...base, f: 1 }],
  ])("reports %s", (_, changed) => {
    expect(compareJson(base, changed).mismatches).not.toEqual([]);
  });
});

describe("pdfSummary", () => {
  it("reads drawn text from a deflated stream and unescapes it", () => {
    const stream = zlibSync(new TextEncoder().encode("BT 1 2 Td (a \\(b\\) c\\\\d) Tj ET"));
    const pdf = `%PDF-1.3\nstream\n${String.fromCharCode(...stream)}\nendstream /Type /Page /Type /Pages`;
    expect(pdfSummary(btoa(pdf))).toEqual({ header: "%PDF-1.3", pages: 1, text: ["a (b) c\\d"] });
  });

  it("is the normalisation the committed fixtures used (their PDF summaries are already normalised)", () => {
    const steps = loadFixtures().flatMap((f) => f.steps);
    const pdfStep = steps.find((s) => s.command === "export" && s.payload.kind === "results_pdf");
    expect(pdfStep).toBeDefined();
    const other = steps.find((s) => s.command === "overview")!;
    expect(normaliseResult(other, other.result)).toBe(other.result); // untouched
  });
});
