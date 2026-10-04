// @vitest-environment node
import { describe, expect, it } from "vitest";
import { eventHomePath, guardEventView, NOT_STARTED_MESSAGE } from "../src/app/guards";
import type { EventDocument } from "../src/engine/types";

/** A document stub at a given stage and status. */
function doc(stage: 0 | 1 | 2 | 3, status: EventDocument["status"] = "setup") {
  return { id: "e1", status, setup: { stage } as EventDocument["setup"] };
}

describe("eventHomePath", () => {
  it.each([
    [doc(0), "/e/e1/setup/1"],
    [doc(1), "/e/e1/setup/2"],
    [doc(2), "/e/e1/setup/3"],
    [doc(3, "running"), "/e/e1/pass"],
    [doc(3, "complete"), "/e/e1/pass"],
  ])("opens %o at %s", (d, path) => {
    expect(eventHomePath(d)).toBe(path);
  });
});

describe("guardEventView", () => {
  it("lets every stage up to the next one through, and sends a later stage back", () => {
    expect(guardEventView(doc(0), { kind: "setup", stage: 1 })).toEqual({ allowed: true });
    expect(guardEventView(doc(0), { kind: "setup", stage: 2 })).toEqual({
      allowed: false,
      redirect: "/e/e1/setup/1",
      message: "Complete Stage 1 first.",
    });
    expect(guardEventView(doc(1), { kind: "setup", stage: 3 })).toEqual({
      allowed: false,
      redirect: "/e/e1/setup/2",
      message: "Complete Stage 2 first.",
    });
    expect(guardEventView(doc(2), { kind: "setup", stage: 3 })).toEqual({ allowed: true });
  });

  it("keeps the setup stages reachable after the start (read-only summaries)", () => {
    for (const stage of [1, 2, 3] as const) {
      expect(guardEventView(doc(3, "running"), { kind: "setup", stage })).toEqual({
        allowed: true,
      });
    }
  });

  it.each([
    { kind: "pass" },
    { kind: "match", index: "0" },
    { kind: "results", tab: "leaderboard" },
  ] as const)("sends %o back to setup before the start", (view) => {
    expect(guardEventView(doc(2), view)).toEqual({
      allowed: false,
      redirect: "/e/e1/setup/3",
      message: NOT_STARTED_MESSAGE,
    });
  });

  it("allows the scoring views once running or complete (D11)", () => {
    for (const status of ["running", "complete"] as const) {
      expect(guardEventView(doc(3, status), { kind: "pass" })).toEqual({ allowed: true });
      expect(guardEventView(doc(3, status), { kind: "match", index: "2" })).toEqual({
        allowed: true,
      });
      expect(guardEventView(doc(3, status), { kind: "results", tab: "archers" })).toEqual({
        allowed: true,
      });
    }
  });

  it("sends an unknown results tab to the leaderboard and a malformed match index to the pass", () => {
    expect(guardEventView(doc(3, "running"), { kind: "results", tab: "charts" })).toMatchObject({
      redirect: "/e/e1/results/leaderboard",
    });
    expect(guardEventView(doc(3, "running"), { kind: "match", index: "x1" })).toMatchObject({
      redirect: "/e/e1/pass",
    });
  });
});
