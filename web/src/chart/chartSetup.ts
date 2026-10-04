/**
 * The pair chart's Chart.js pieces, ported from h2h/static/match_chart.js (UISpec.md 7.3, Chart
 * component): the datasets, the `nearestCurveX` interaction mode and the marker-label plugin.
 * Everything plotted comes from the bridge's `pair_chart` payload (h2h/chart_data.py); nothing is
 * computed here except where on the canvas to draw it.
 *
 * Both archers' smoothed score-distribution curves share one chart; vertical dashed lines mark
 * the scores the archers have shot, each labelled with its pass number ("P3"). By default only the
 * pass being scored is marked; "Show previous passes' scores too" adds every earlier pass of both
 * archers, whoever they were shooting against. The legend names each archer with the handicap the
 * plotted curve is built from.
 */
import {
  Chart,
  Filler,
  Interaction,
  Legend,
  LinearScale,
  LineController,
  LineElement,
  PointElement,
  Tooltip,
  type ChartDataset,
  type InteractionItem,
  type InteractionModeFunction,
  type Plugin,
} from "chart.js";
import { getRelativePosition } from "chart.js/helpers";
import type { PairChart } from "../engine/types";

declare module "chart.js" {
  interface InteractionModeMap {
    nearestCurveX: InteractionModeFunction;
  }
}

/** The two series' colours: the Flask chart's blue and red, lighter on a dark background. */
export const SERIES_COLORS = {
  light: { a: "#4c72b0", b: "#c44e52" },
  dark: { a: "#7a9fdc", b: "#e2777a" },
} as const;

export type SeriesColors = { a: string; b: string };

/** A line dataset with the marker fields the plugin and legend filter read. */
export type PairDataset = ChartDataset<"line", { x: number; y: number }[]> & {
  isMarker?: boolean;
  /** Marker only: "P3". */
  passLabel?: string;
  /** Which archer the dataset belongs to (the first archer's labels prefer the left). */
  archer?: "a" | "b";
};

/**
 * One archer's distribution curve.
 *
 * @param points - The curve's points from the payload.
 * @param color - The series colour (hex).
 * @param label - The legend text (name and handicap, from the payload).
 * @param archer - "a" or "b".
 * @returns The dataset.
 */
function curveDataset(
  points: { x: number; y: number }[],
  color: string,
  label: string,
  archer: "a" | "b",
): PairDataset {
  return {
    label,
    data: points,
    borderColor: color,
    backgroundColor: `${color}33`,
    fill: true,
    tension: 0.35,
    pointRadius: 0,
    order: 2,
    archer,
  };
}

/**
 * A vertical dashed marker at a score shot.
 *
 * @param x - The score.
 * @param yMax - The top of the y axis (from the payload).
 * @param color - The series colour.
 * @param label - The dataset's name, e.g. "Ann pass 3: 104".
 * @param passLabel - The text drawn beside the line, e.g. "P3".
 * @param archer - "a" or "b".
 * @returns The dataset.
 */
function markerDataset(
  x: number,
  yMax: number,
  color: string,
  label: string,
  passLabel: string,
  archer: "a" | "b",
): PairDataset {
  return {
    label,
    passLabel,
    data: [
      { x, y: 0 },
      { x, y: yMax },
    ],
    borderColor: color,
    borderWidth: 2,
    borderDash: [6, 4],
    pointRadius: 0,
    fill: false,
    tension: 0,
    order: 1,
    isMarker: true,
    archer,
  };
}

/**
 * The chart's datasets: both curves, then one marker per score shot, for the current pass only or,
 * with `all`, for every pass of either archer (against any opponent).
 *
 * @param data - The bridge's `pair_chart` payload.
 * @param all - Include every pass's markers.
 * @param colors - The series colours.
 * @returns The datasets.
 */
export function pairDatasets(data: PairChart, all: boolean, colors: SeriesColors): PairDataset[] {
  const datasets = [
    curveDataset(data.distribution_a, colors.a, data.archer_a.legend, "a"),
    curveDataset(data.distribution_b, colors.b, data.archer_b.legend, "b"),
  ];
  for (const [archer, key] of [
    [data.archer_a, "a"],
    [data.archer_b, "b"],
  ] as const) {
    for (const p of archer.passes) {
      if (all || p.index === data.current_pass) {
        datasets.push(
          markerDataset(
            p.score,
            data.y_max,
            colors[key],
            `${archer.name} pass ${p.index + 1}: ${p.score}`,
            `P${p.index + 1}`,
            key,
          ),
        );
      }
    }
  }
  return datasets;
}

/**
 * Interaction mode for hover and the tooltip: for each archer's curve, the point nearest the
 * pointer by x alone, ignoring the markers.
 *
 * Chart.js's built-in "index" mode is not usable here. It finds the single nearest point across
 * every visible dataset, markers included, then returns the points at that same data index in
 * every dataset. A marker is a 2-point dataset sitting at exactly the x of a curve point, so near
 * a marker line it ties with the nearest curve point and, having a lower `order`, wins: the
 * tooltip then showed the curves' leftmost point instead of the score under the pointer. Choosing
 * from the curve datasets only fixes that and keeps markers out of the tooltip by construction.
 *
 * @param chart - The chart.
 * @param event - The pointer event.
 * @param _options - Interaction options (unused).
 * @param useFinalPosition - Use animation end positions.
 * @returns One item per curve dataset.
 */
export const nearestCurveX: InteractionModeFunction = (
  chart,
  event,
  _options,
  useFinalPosition,
) => {
  const pointerX = getRelativePosition(event, chart as Chart).x;
  const items: InteractionItem[] = [];
  for (const meta of chart.getSortedVisibleDatasetMetas()) {
    if ((chart.data.datasets[meta.index] as PairDataset).isMarker) continue;
    let nearest: InteractionItem | null = null;
    let nearestDistance = Infinity;
    meta.data.forEach((element, index) => {
      const distance = Math.abs(element.getProps(["x"], useFinalPosition).x - pointerX);
      if (distance < nearestDistance) {
        nearest = { element, datasetIndex: meta.index, index };
        nearestDistance = distance;
      }
    });
    if (nearest) items.push(nearest);
  }
  return items;
};

/** A drawn marker label's box, in canvas pixels. */
export interface LabelBox {
  text: string;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

const LABEL_WIDTH = 13; // the rotated text's height, in pixels
const LABEL_GAP = 3; // between the marker line and its label

/** The part of a chart the label plugin reads and writes (so tests can supply a stand-in). */
export interface LabelChart {
  ctx: CanvasRenderingContext2D;
  chartArea: { left: number; right: number; top: number; bottom: number };
  data: { datasets: PairDataset[] };
  scales: { x: { getPixelForValue: (value: number) => number } };
  isDatasetVisible: (index: number) => boolean;
  canvas?: HTMLCanvasElement | null;
  markerLabelBoxes?: LabelBox[];
}

/**
 * Write each marker line's pass number ("P3") on the chart: rotated text just inside the top of
 * the plot, in the line's colour. The first archer's labels prefer the left of their line and the
 * second's the right, so two equal scores do not collide. A side is avoided if the label would
 * stick out of the plot area (a marker near either edge) or cross another marker line (two lines a
 * score apart); the label goes on the other side instead. A label that would still overlap one
 * already drawn is moved down below it. The drawn boxes are kept on `chart.markerLabelBoxes`
 * ({text, x0, y0, x1, y1} in canvas pixels) for tests, and mirrored to the canvas's
 * `data-marker-labels` attribute for the browser tests.
 *
 * @param chart - The chart, after its datasets are drawn.
 */
export function drawMarkerLabels(chart: LabelChart): void {
  const { ctx, chartArea: area } = chart;
  const markers: { dataset: PairDataset; x: number }[] = [];
  chart.data.datasets.forEach((dataset, index) => {
    if (dataset.isMarker && chart.isDatasetVisible(index)) {
      markers.push({ dataset, x: chart.scales.x.getPixelForValue(dataset.data[0].x) });
    }
  });
  const placed: LabelBox[] = [];
  ctx.save();
  ctx.font = "12px sans-serif";
  for (const { dataset, x } of markers) {
    const text = dataset.passLabel ?? "";
    const length = ctx.measureText(text).width;
    const prefersLeft = dataset.archer === "a";
    let best: { left: boolean; x0: number; y0: number; cost: number } | null = null;
    for (const left of prefersLeft ? [true, false] : [false, true]) {
      const x0 = left ? x - LABEL_GAP - LABEL_WIDTH : x + LABEL_GAP;
      const inside = x0 >= area.left && x0 + LABEL_WIDTH <= area.right;
      const crossings = markers.filter(
        (other) => other.x !== x && other.x > x0 - 1 && other.x < x0 + LABEL_WIDTH + 1,
      ).length;
      let y0 = area.top + 3;
      for (let moved = true; moved;) {
        moved = false;
        for (const box of placed) {
          if (x0 < box.x1 && x0 + LABEL_WIDTH > box.x0 && y0 < box.y1 && y0 + length > box.y0) {
            y0 = box.y1 + 3;
            moved = true;
          }
        }
      }
      const cost = (inside ? 0 : 100) + crossings;
      if (best === null || cost < best.cost) best = { left, x0, y0, cost };
    }
    if (best === null) continue;
    placed.push({
      text,
      x0: best.x0,
      y0: best.y0,
      x1: best.x0 + LABEL_WIDTH,
      y1: best.y0 + length,
    });
    ctx.save();
    ctx.fillStyle = dataset.borderColor as string;
    ctx.translate(best.left ? x - LABEL_GAP : x + LABEL_GAP, best.y0 + length);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = "left";
    ctx.textBaseline = best.left ? "bottom" : "top";
    ctx.fillText(text, 0, 0);
    ctx.restore();
  }
  ctx.restore();
  chart.markerLabelBoxes = placed;
  if (chart.canvas) chart.canvas.dataset.markerLabels = JSON.stringify(placed);
}

/** The marker-label plugin. */
export const markerLabels: Plugin<"line"> = {
  id: "markerLabels",
  afterDatasetsDraw: (chart) => drawMarkerLabels(chart as unknown as LabelChart),
};

let registered = false;

/** Register the Chart.js parts the pair chart uses (tree-shaken, decision D9) and its mode. */
export function registerPairChart(): void {
  if (registered) return;
  Chart.register(LineController, LineElement, PointElement, LinearScale, Filler, Legend, Tooltip);
  Interaction.modes.nearestCurveX = nearestCurveX;
  registered = true;
}
