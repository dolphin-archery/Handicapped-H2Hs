import { describe, expect, it } from "vitest";
import { localIso } from "../src/components/exports";

describe("localIso", () => {
  it("writes the local clock time with no offset, as export's now_iso expects", () => {
    expect(localIso(new Date(2026, 9, 4, 15, 30, 12, 345))).toBe("2026-10-04T15:30:12");
    expect(localIso(new Date(2026, 0, 2, 3, 4, 5))).toBe("2026-01-02T03:04:05");
  });
});
