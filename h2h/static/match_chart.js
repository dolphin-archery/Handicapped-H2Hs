/*
 * Renders the match page's interactive distribution chart from
 * window.MATCH_CHART_DATA (see h2h/chart_data.py for its shape).
 *
 * Both archers' smoothed score-distribution curves are drawn on one shared
 * chart; vertical dashed lines mark the scores the archers have shot, each
 * labelled on the chart with its pass number ("P3"). By default only the
 * pass currently being scored is marked; a checkbox adds every earlier pass
 * of both archers, whoever they were shooting against (Specification/
 * feedback.md "Feedback 5"). The legend names each archer with their handicap.
 */
(function () {
  const data = window.MATCH_CHART_DATA;
  const canvas = document.getElementById("match-chart");
  if (!data || !canvas || typeof Chart === "undefined") {
    return;
  }

  const COLOR_A = "#4c72b0";
  const COLOR_B = "#c44e52";

  function curveDataset(points, color, label) {
    return {
      label: label,
      data: points,
      borderColor: color,
      backgroundColor: color + "33",
      fill: true,
      tension: 0.35,
      pointRadius: 0,
      order: 2,
    };
  }

  function markerDataset(x, color, label, passLabel) {
    return {
      label: label,
      passLabel: passLabel,
      data: [
        { x: x, y: 0 },
        { x: x, y: data.y_max },
      ],
      borderColor: color,
      borderWidth: 2,
      borderDash: [6, 4],
      pointRadius: 0,
      fill: false,
      tension: 0,
      order: 1,
      isMarker: true,
    };
  }

  // One vertical marker per score shot: every pass of either archer (against any
  // opponent) when `all` is true, otherwise only the pass currently being scored.
  function markersFor(all) {
    const datasets = [];
    for (const [archer, color] of [[data.archer_a, COLOR_A], [data.archer_b, COLOR_B]]) {
      for (const p of archer.passes) {
        if (all || p.index === data.current_pass) {
          datasets.push(
            markerDataset(
              p.score,
              color,
              `${archer.name} pass ${p.index + 1}: ${p.score}`,
              `P${p.index + 1}`
            )
          );
        }
      }
    }
    return datasets;
  }

  const baseDatasets = [
    curveDataset(data.distribution_a, COLOR_A, data.archer_a.legend),
    curveDataset(data.distribution_b, COLOR_B, data.archer_b.legend),
  ];

  /*
   * Custom interaction mode used for hover and the tooltip: for each archer's
   * curve, the point nearest the pointer by x alone, ignoring the markers.
   *
   * Chart.js's built-in "index" mode is not usable here. It finds the single
   * nearest point across every visible dataset, markers included, then returns
   * the points at that same data *index* in every dataset. A marker is a
   * 2-point dataset (indices 0 and 1) sitting at exactly the x of a curve
   * point, so anywhere within half a score of a marker line the marker ties
   * with the nearest curve point, and as markers have a lower `order` than the
   * curves they win the tie. The tooltip then showed the curves' index-0 point
   * (the leftmost score) instead of the score under the pointer. Choosing the
   * point from the curve datasets only fixes that for every marker line shown,
   * and keeps markers out of the tooltip and hover highlight by construction.
   *
   * Arguments follow Chart.js's interaction-mode signature: chart (Chart),
   * event (a native or Chart.js event), options (interaction options, unused),
   * useFinalPosition (bool, use animation end positions). Returns an array of
   * { element, datasetIndex, index }, one per curve dataset.
   */
  Chart.Interaction.modes.nearestCurveX = function (chart, event, options, useFinalPosition) {
    const pointerX = Chart.helpers.getRelativePosition(event, chart).x;
    const items = [];
    for (const meta of chart.getSortedVisibleDatasetMetas()) {
      if (chart.data.datasets[meta.index].isMarker) {
        continue;
      }
      let nearest = null;
      let nearestDistance = Infinity;
      meta.data.forEach((element, index) => {
        const distance = Math.abs(element.getProps(["x"], useFinalPosition).x - pointerX);
        if (distance < nearestDistance) {
          nearest = { element: element, datasetIndex: meta.index, index: index };
          nearestDistance = distance;
        }
      });
      if (nearest) {
        items.push(nearest);
      }
    }
    return items;
  };

  /*
   * Inline plugin that writes each marker line's pass number ("P3") on the
   * chart: rotated text just inside the top of the plot, in the line's colour,
   * to the left of the line for the first archer and to the right for the
   * second so two equal scores do not collide. A label that would overlap one
   * already drawn is moved down below it. The boxes drawn are kept on
   * chart.markerLabelBoxes ({text, x0, y0, x1, y1} in canvas pixels) so tests
   * can check them.
   */
  const markerLabels = {
    id: "markerLabels",
    afterDatasetsDraw(chart) {
      const ctx = chart.ctx;
      const area = chart.chartArea;
      const placed = [];
      ctx.save();
      ctx.font = "12px sans-serif";
      chart.data.datasets.forEach((dataset, index) => {
        if (!dataset.isMarker || !chart.isDatasetVisible(index)) {
          return;
        }
        const x = chart.scales.x.getPixelForValue(dataset.data[0].x);
        const length = ctx.measureText(dataset.passLabel).width;
        const leftOfLine = dataset.borderColor === COLOR_A;
        const x0 = leftOfLine ? x - 3 - 13 : x + 3;
        let y0 = area.top + 3;
        for (let moved = true; moved; ) {
          moved = false;
          for (const box of placed) {
            const overlaps =
              x0 < box.x1 && x0 + 13 > box.x0 && y0 < box.y1 && y0 + length > box.y0;
            if (overlaps) {
              y0 = box.y1 + 3;
              moved = true;
            }
          }
        }
        placed.push({ text: dataset.passLabel, x0: x0, y0: y0, x1: x0 + 13, y1: y0 + length });
        ctx.save();
        ctx.fillStyle = dataset.borderColor;
        ctx.translate(leftOfLine ? x - 3 : x + 3, y0 + length);
        ctx.rotate(-Math.PI / 2);
        ctx.textAlign = "left";
        ctx.textBaseline = leftOfLine ? "bottom" : "top";
        ctx.fillText(dataset.passLabel, 0, 0);
        ctx.restore();
      });
      ctx.restore();
      chart.markerLabelBoxes = placed;
    },
  };

  const chart = new Chart(canvas, {
    type: "line",
    data: { datasets: baseDatasets.concat(markersFor(false)) },
    plugins: [markerLabels],
    options: {
      parsing: false,
      plugins: {
        legend: {
          // Only the two curves (named with their handicaps); markers are labelled on the chart.
          labels: { filter: (item, chartData) => !chartData.datasets[item.datasetIndex].isMarker },
        },
      },
      scales: {
        x: {
          type: "linear",
          min: data.x_min,
          max: data.x_max,
          title: { display: true, text: "Pass score" },
        },
        y: {
          min: 0,
          max: data.y_max,
          title: { display: true, text: "Probability" },
        },
      },
      interaction: { mode: "nearestCurveX", intersect: false },
    },
  });

  const checkbox = document.getElementById("show-previous-passes");
  if (checkbox) {
    checkbox.addEventListener("change", () => {
      chart.data.datasets = baseDatasets.concat(markersFor(checkbox.checked));
      chart.update();
    });
  }
})();
