/**
 * The arrows-per-pass control's rules, ported from the old Stage 1 script
 * (h2h/templates/stage1.html): it offers only divisors of the total arrows, remembers the value
 * the user last chose, and shows the divisor nearest to it when the total changes.
 */

/**
 * The divisors of a whole number, ascending.
 *
 * @param n - The total arrows.
 * @returns Every i from 1 to n with n % i === 0 (empty for n < 1).
 */
export function divisors(n: number): number[] {
  const out: number[] = [];
  for (let i = 1; i <= n; i++) if (n % i === 0) out.push(i);
  return out;
}

/**
 * The total the control works from, read as the old script did (`parseInt(value) || 1`).
 *
 * @param total - The total arrows field's value (a number, or text while typing).
 * @returns The typed whole number, or 1 when it is empty, below 1 or not a number.
 */
export function controlTotal(total: string | number): number {
  const n = Number.parseInt(String(total), 10);
  return n >= 1 ? n : 1; // the old script's `|| 1`, also for a negative total
}

/**
 * Which divisor to show for the user's preferred arrows per pass: that value if it divides the
 * total, otherwise the nearest divisor (the smaller one on a tie, as the old script's first-best
 * rule). The preference itself is kept unchanged by the caller.
 *
 * @param total - The total arrows field's value.
 * @param preferred - The arrows per pass the user last chose.
 * @returns The divisors and the index of the one to show.
 */
export function snapToDivisor(
  total: string | number,
  preferred: number,
): { options: number[]; index: number } {
  const options = divisors(controlTotal(total));
  let index = options.indexOf(preferred);
  if (index === -1) {
    index = 0;
    let bestDiff = Infinity;
    options.forEach((value, i) => {
      const diff = Math.abs(value - preferred);
      if (diff < bestDiff) {
        bestDiff = diff;
        index = i;
      }
    });
  }
  return { options, index };
}

/**
 * Whether the "Shoot byes?" control applies: an odd number of archers of at least 3.
 *
 * @param nArchers - The number of archers field's value.
 * @returns True when the control is shown.
 */
export function byesApply(nArchers: string | number): boolean {
  const n = Number.parseInt(String(nArchers), 10);
  return n >= 3 && n % 2 === 1;
}
