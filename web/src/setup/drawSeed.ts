/**
 * A fresh seed for the Stage 3 draw, from the browser's cryptographic random source (UISpec.md
 * 5.4); the bridge draws with `random.Random(seed)`.
 *
 * @returns A whole number from 0 to 2^32 - 1.
 */
export function drawSeed(): number {
  return crypto.getRandomValues(new Uint32Array(1))[0];
}
