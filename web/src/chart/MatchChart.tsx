import {
  Accordion,
  Alert,
  Box,
  Checkbox,
  Loader,
  Stack,
  Text,
  Title,
  useComputedColorScheme,
} from "@mantine/core";
import { Chart } from "chart.js";
import { useEffect, useRef, useState } from "react";
import type { EventDocument, PairChart } from "../engine/types";
import { useBridgeQuery } from "../engine/useBridgeQuery";
import {
  markerLabels,
  pairDatasets,
  registerPairChart,
  SERIES_COLORS,
  type PairDataset,
} from "./chartSetup";

/** Axis text and grid colours per colour scheme. */
const AXIS_COLORS = {
  light: { text: "#495057", grid: "rgba(0, 0, 0, 0.1)" },
  dark: { text: "#c9c9c9", grid: "rgba(255, 255, 255, 0.12)" },
} as const;

/**
 * The pair chart (port of h2h/static/match_chart.js): both distribution curves and the score
 * markers, drawn with Chart.js from the bridge's `pair_chart` payload only. Redraws when the
 * markers shown or the colour scheme change; resizes with its container.
 *
 * @param props.data - The `pair_chart` payload.
 * @param props.showPrevious - Also mark every earlier pass of both archers.
 * @returns The chart.
 */
export function MatchChart({ data, showPrevious }: { data: PairChart; showPrevious: boolean }) {
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const scheme = useComputedColorScheme("light");

  useEffect(() => {
    if (canvas.current === null) return;
    registerPairChart();
    const colors = SERIES_COLORS[scheme];
    const axis = AXIS_COLORS[scheme];
    const scale = (title: string) => ({
      title: { display: true, text: title, color: axis.text },
      ticks: { color: axis.text },
      grid: { color: axis.grid },
    });
    const chart = new Chart(canvas.current, {
      type: "line",
      data: { datasets: pairDatasets(data, showPrevious, colors) },
      plugins: [markerLabels],
      options: {
        parsing: false,
        responsive: true,
        maintainAspectRatio: true,
        aspectRatio: 1.6,
        animation: false,
        plugins: {
          legend: {
            // Only the two curves (named with their handicaps); markers are labelled on the chart.
            labels: {
              color: axis.text,
              filter: (item, chartData) =>
                !(chartData.datasets[item.datasetIndex ?? 0] as PairDataset).isMarker,
            },
          },
        },
        scales: {
          x: { type: "linear", min: data.x_min, max: data.x_max, ...scale("Pass score") },
          y: { min: 0, max: data.y_max, ...scale("Probability") },
        },
        interaction: { mode: "nearestCurveX", intersect: false },
      },
    });
    return () => chart.destroy();
  }, [data, showPrevious, scheme]);

  return (
    <Box pos="relative" w="100%">
      <canvas
        ref={canvas}
        data-testid="pair-chart"
        role="img"
        aria-label={`Score distributions: ${data.archer_a.legend} and ${data.archer_b.legend}`}
      />
    </Box>
  );
}

/**
 * The chart panel for two archers (the Flask `_pair_chart.html`): heading, the "Show previous
 * passes' scores too" checkbox, the chart, and "How the winner is decided" in a collapsible
 * section. Loads its data with the bridge's `pair_chart`.
 *
 * @param props.doc - The event document.
 * @param props.a - The first archer's schedule position.
 * @param props.b - The second archer's schedule position.
 * @returns The panel.
 */
export function PairChartPanel({ doc, a, b }: { doc: EventDocument; a: number; b: number }) {
  const chart = useBridgeQuery("pair_chart", { doc, a, b }, true);
  const [showPrevious, setShowPrevious] = useState(false);
  return (
    <Stack gap="sm" data-testid="chart-panel">
      <Title order={2} size="h3">
        Score distributions
      </Title>
      <Checkbox
        label="Show previous passes' scores too"
        checked={showPrevious}
        onChange={(event) => setShowPrevious(event.currentTarget.checked)}
      />
      {chart.state === "loading" && <Loader aria-label="Loading the chart" />}
      {chart.state === "error" && <Alert color="red">{chart.error.message}</Alert>}
      {chart.state === "ok" && <MatchChart data={chart.data} showPrevious={showPrevious} />}
      <Accordion variant="contained">
        <Accordion.Item value="maths">
          <Accordion.Control>How the winner is decided</Accordion.Control>
          <Accordion.Panel>
            <Text size="sm" mb="xs">
              An archer&apos;s handicap sets how well they are expected to shoot. The coloured
              curves show the scores each archer is expected to shoot, and the dashed vertical lines
              show the scores they actually shot.
            </Text>
            <Text size="sm">
              A <strong>percentile</strong> says how good a score is for that archer&apos;s
              handicap: it is the chance of scoring that much or less. Whoever has the higher
              percentile did better for their handicap and wins the pass.
            </Text>
          </Accordion.Panel>
        </Accordion.Item>
      </Accordion>
    </Stack>
  );
}
