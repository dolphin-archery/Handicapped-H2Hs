import { describe, expect, it } from "vitest";
import { byesApply, controlTotal, divisors, snapToDivisor } from "../src/setup/divisors";

/** The arrows-per-pass rules, as the old script in h2h/templates/stage1.html. */
describe("arrows per pass", () => {
  it("offers only the divisors of the total, ascending", () => {
    expect(divisors(60)).toEqual([1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60]);
    expect(divisors(7)).toEqual([1, 7]);
  });

  it("reads the total as parseInt(value) || 1", () => {
    expect(controlTotal("")).toBe(1);
    expect(controlTotal("36")).toBe(36);
    expect(controlTotal(0)).toBe(1);
    expect(controlTotal("-5")).toBe(1);
  });

  it("keeps the preferred value when it divides the total", () => {
    const { options, index } = snapToDivisor(60, 12);
    expect(options[index]).toBe(12);
  });

  it("shows the nearest divisor otherwise, the smaller one on a tie", () => {
    expect(pick(50, 12)).toBe(10);
    expect(pick(7, 4)).toBe(1); // 1 and 7 are 3 away each: the first wins
    expect(pick(36, 10)).toBe(9);
  });

  it("returns to the preference when the total allows it again (the preference is not changed)", () => {
    const preferred = 12;
    const typed = ["6", "60"].map((total) => pick(total, preferred));
    expect(typed).toEqual([6, 12]);
  });

  it("shows the byes control only for an odd number of archers of 3 or more", () => {
    expect([1, 2, 3, 4, 5, 9].map(byesApply)).toEqual([false, false, true, false, true, true]);
    expect(byesApply("")).toBe(false);
  });
});

/**
 * The value the control shows.
 *
 * @param total - The total arrows.
 * @param preferred - The preferred arrows per pass.
 * @returns The divisor shown.
 */
function pick(total: string | number, preferred: number): number {
  const { options, index } = snapToDivisor(total, preferred);
  return options[index];
}
