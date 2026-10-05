// @vitest-environment node
import { describe, expect, it } from "vitest";
import {
  drawMarkerLabels,
  pairDatasets,
  SERIES_COLORS,
  type LabelBox,
  type LabelChart,
  type PairDataset,
} from "../src/chart/chartSetup";
import type { PairChart } from "../src/engine/types";
import { loadFixtures } from "./bridgeFixtures";

/**
 * UI-16: the pair chart's marker labels, checked on `chart.markerLabelBoxes` after the plugin runs
 * on a stand-in chart (jsdom has no canvas), and the datasets built only from `pair_chart`.
 */

const AREA = { left: 50, right: 650, top: 10, bottom: 310 };
const X_MIN = 0;
const X_MAX = 200; // 3 px per score

/**
 * A marker dataset as `pairDatasets` makes it.
 *
 * @param archer - "a" or "b".
 * @param score - The score.
 * @param pass - The pass number shown ("P<pass>").
 * @returns The dataset.
 */
function marker(archer: "a" | "b", score: number, pass: number): PairDataset {
  return {
    data: [
      { x: score, y: 0 },
      { x: score, y: 1 },
    ],
    isMarker: true,
    passLabel: `P${pass}`,
    archer,
    borderColor: SERIES_COLORS.light[archer],
  };
}

/**
 * Run the label plugin on a stand-in chart and return what it kept on `chart.markerLabelBoxes`.
 *
 * @param datasets - The datasets (markers, and optionally curves).
 * @param hidden - Indices of hidden datasets.
 * @returns The boxes and the markers' pixel positions.
 */
function placeLabels(datasets: PairDataset[], hidden: number[] = []) {
  const noop = () => {};
  const ctx = {
    save: noop,
    restore: noop,
    translate: noop,
    rotate: noop,
    fillText: noop,
    measureText: (text: string) => ({ width: 7 * text.length }),
  } as unknown as CanvasRenderingContext2D;
  const toPixel = (value: number) =>
    AREA.left + ((value - X_MIN) / (X_MAX - X_MIN)) * (AREA.right - AREA.left);
  const chart: LabelChart = {
    ctx,
    chartArea: AREA,
    data: { datasets },
    scales: { x: { getPixelForValue: toPixel } },
    isDatasetVisible: (index) => !hidden.includes(index),
  };
  drawMarkerLabels(chart);
  return { boxes: chart.markerLabelBoxes!, toPixel };
}

const overlaps = (p: LabelBox, q: LabelBox) =>
  p.x0 < q.x1 && q.x0 < p.x1 && p.y0 < q.y1 && q.y0 < p.y1;

/**
 * Check the three rules for every label: no two overlap, each sits beside its own marker line
 * (3 px to its left or right), and each is inside the plot area.
 *
 * @param boxes - The placed boxes, in marker order.
 * @param lines - Each marker's x in pixels, in the same order.
 */
function expectWellPlaced(boxes: LabelBox[], lines: number[]) {
  expect(boxes).toHaveLength(lines.length);
  boxes.forEach((box, i) => {
    for (const other of boxes.slice(i + 1)) expect(overlaps(box, other)).toBe(false);
    expect(box.x1 === lines[i] - 3 || box.x0 === lines[i] + 3).toBe(true);
    expect(box.x0).toBeGreaterThanOrEqual(AREA.left);
    expect(box.x1).toBeLessThanOrEqual(AREA.right);
    expect(box.y0).toBeGreaterThanOrEqual(AREA.top);
    expect(box.y1).toBeLessThanOrEqual(AREA.bottom);
  });
}

describe("marker labels (chart.markerLabelBoxes)", () => {
  it("two markers one score apart: no overlap, each beside its line, inside the plot", () => {
    for (const [a, b] of [
      [100, 101],
      [101, 100],
    ]) {
      const { boxes, toPixel } = placeLabels([marker("a", a, 1), marker("b", b, 1)]);
      expectWellPlaced(boxes, [toPixel(a), toPixel(b)]);
      // Neither label crosses the other marker's line.
      for (const box of boxes) {
        for (const x of [toPixel(a), toPixel(b)]) expect(x > box.x0 && x < box.x1).toBe(false);
      }
    }
  });

  it("equal scores: the first archer's label goes left, the second's right", () => {
    const { boxes, toPixel } = placeLabels([marker("a", 120, 2), marker("b", 120, 2)]);
    expectWellPlaced(boxes, [toPixel(120), toPixel(120)]);
    expect(boxes[0].x1).toBe(toPixel(120) - 3);
    expect(boxes[1].x0).toBe(toPixel(120) + 3);
  });

  it("markers at either edge put their label on the inside", () => {
    const { boxes, toPixel } = placeLabels([marker("a", X_MIN, 1), marker("b", X_MAX, 1)]);
    expectWellPlaced(boxes, [toPixel(X_MIN), toPixel(X_MAX)]);
    expect(boxes[0].x0).toBe(toPixel(X_MIN) + 3); // a prefers left, but left is outside
    expect(boxes[1].x1).toBe(toPixel(X_MAX) - 3); // b prefers right, but right is outside
  });

  it("many previous passes close together are stacked without overlapping", () => {
    const scores: ["a" | "b", number][] = [
      ["a", 100],
      ["a", 101],
      ["a", 101],
      ["b", 102],
      ["b", 103],
      ["b", 103],
      ["a", 104],
      ["b", 104],
    ];
    const { boxes, toPixel } = placeLabels(scores.map(([who, s], i) => marker(who, s, i + 1)));
    expectWellPlaced(
      boxes,
      scores.map(([, s]) => toPixel(s)),
    );
    expect(boxes.map((b) => b.text)).toEqual(["P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8"]);
  });

  it("ignores curves and hidden markers", () => {
    const curve: PairDataset = { data: [{ x: 0, y: 0 }], archer: "a" };
    const { boxes } = placeLabels([curve, marker("a", 50, 1), marker("b", 60, 2)], [2]);
    expect(boxes.map((b) => b.text)).toEqual(["P1"]);
  });
});

describe("pairDatasets", () => {
  const charts = loadFixtures().flatMap((fixture) =>
    fixture.steps
      .filter((step) => step.command === "pair_chart" && (step.result as { ok: boolean }).ok)
      .map((step) => ({
        scenario: fixture.scenario,
        data: (step.result as { data: PairChart }).data,
      })),
  );

  it("has pair_chart payloads to check", () => {
    expect(charts.length).toBeGreaterThan(0);
  });

  it("plots the payload as it is: curves, legends, and one marker per score shot", () => {
    for (const { data } of charts) {
      const all = pairDatasets(data, true, SERIES_COLORS.light);
      const [curveA, curveB, ...markers] = all;
      expect(curveA.data).toBe(data.distribution_a);
      expect(curveB.data).toBe(data.distribution_b);
      expect([curveA.label, curveB.label]).toEqual([data.archer_a.legend, data.archer_b.legend]);
      const shot = [...data.archer_a.passes, ...data.archer_b.passes];
      expect(markers.map((m) => m.data[0].x)).toEqual(shot.map((p) => p.score));
      expect(markers.map((m) => m.passLabel)).toEqual(shot.map((p) => `P${p.index + 1}`));
      expect(markers.every((m) => m.data[1].y === data.y_max)).toBe(true);
    }
  });

  it("marks only the current pass unless previous passes are asked for", () => {
    for (const { data } of charts) {
      const markers = pairDatasets(data, false, SERIES_COLORS.light).filter((d) => d.isMarker);
      const current = [...data.archer_a.passes, ...data.archer_b.passes].filter(
        (p) => p.index === data.current_pass,
      );
      expect(markers.map((m) => m.data[0].x)).toEqual(current.map((p) => p.score));
    }
  });

  it("keeps the two series distinct in both colour schemes", () => {
    for (const colors of [SERIES_COLORS.light, SERIES_COLORS.dark]) {
      expect(colors.a).not.toBe(colors.b);
    }
  });
});
