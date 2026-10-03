/*
 * Renders the match page's interactive distribution chart from
 * window.MATCH_CHART_DATA (see h2h/chart_data.py for its shape).
 *
 * Both archers' smoothed score-distribution curves are drawn on one shared
 * chart; vertical dashed lines mark each archer's actual score for a pass.
 * By default only the most recent pass's markers are shown, per
 * Specification/feedback.md; a checkbox reveals every previous pass too.
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

  function markerDataset(x, color, label) {
    return {
      label: label,
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

  function markersFor(passList) {
    const datasets = [];
    for (const p of passList) {
      datasets.push(
        markerDataset(p.score_a, COLOR_A, `${data.archer_a.name} pass ${p.index + 1}: ${p.score_a}`)
      );
      datasets.push(
        markerDataset(p.score_b, COLOR_B, `${data.archer_b.name} pass ${p.index + 1}: ${p.score_b}`)
      );
    }
    return datasets;
  }

  const baseDatasets = [
    curveDataset(data.distribution_a, COLOR_A, data.archer_a.name),
    curveDataset(data.distribution_b, COLOR_B, data.archer_b.name),
  ];

  const passes = data.passes || [];
  const latestOnly = passes.length ? [passes[passes.length - 1]] : [];

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

  const chart = new Chart(canvas, {
    type: "line",
    data: { datasets: baseDatasets.concat(markersFor(latestOnly)) },
    options: {
      parsing: false,
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
      const shown = checkbox.checked ? passes : latestOnly;
      chart.data.datasets = baseDatasets.concat(markersFor(shown));
      chart.update();
    });
  }
})();
