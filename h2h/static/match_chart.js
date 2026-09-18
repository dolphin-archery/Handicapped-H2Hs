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
      interaction: { mode: "index", intersect: false },
      plugins: {
        tooltip: {
          filter: (item) => !item.dataset.isMarker,
        },
      },
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
