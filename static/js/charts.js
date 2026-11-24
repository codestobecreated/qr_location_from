/* Chart helpers. Data is embedded with Django's json_script; nothing is hardcoded. */
(function () {
  "use strict";
  if (typeof Chart === "undefined") return;

  var GREEN = "#1b8042", BLUE = "#0f5bf5", AMBER = "#f59e0b";
  var PALETTE = ["#1b8042", "#0f5bf5", "#06b6d4", "#f59e0b", "#8b5cf6", "#ef4444", "#64748b", "#14b8a6"];
  Chart.defaults.font.family = "Inter, ui-sans-serif, system-ui, sans-serif";
  Chart.defaults.color = "#64748b";
  Chart.defaults.plugins.legend.labels.usePointStyle = true;

  function data(id) {
    var el = document.getElementById(id);
    return el ? JSON.parse(el.textContent) : null;
  }

  function trend(canvasId, dataId) {
    var canvas = document.getElementById(canvasId), d = data(dataId);
    if (!canvas || !d) return;
    new Chart(canvas, {
      data: {
        labels: d.labels,
        datasets: [
          { type: "bar", label: "Leads", data: d.leads, backgroundColor: "rgba(27,128,66,.85)", borderRadius: 6, yAxisID: "y", order: 2 },
          { type: "bar", label: "Converted", data: d.converted, backgroundColor: "rgba(245,158,11,.85)", borderRadius: 6, yAxisID: "y", order: 3 },
          { type: "line", label: "QR scans", data: d.scans, borderColor: BLUE, backgroundColor: "rgba(15,91,245,.08)", fill: true, tension: .35, pointRadius: 2, yAxisID: "y1", order: 1 }
        ]
      },
      options: {
        maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
        scales: {
          x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 12 } },
          y: { beginAtZero: true, ticks: { precision: 0 }, title: { display: true, text: "Leads" } },
          y1: { beginAtZero: true, position: "right", grid: { drawOnChartArea: false }, ticks: { precision: 0 }, title: { display: true, text: "Scans" } }
        },
        plugins: { legend: { position: "bottom" } }
      }
    });
  }

  function doughnut(canvasId, dataId) {
    var canvas = document.getElementById(canvasId), d = data(dataId);
    if (!canvas || !d) return;
    if (!d.values.length) { canvas.parentElement.innerHTML = '<p class="py-16 text-center text-sm text-slate-500">No data for this period.</p>'; return; }
    new Chart(canvas, {
      type: "doughnut",
      data: { labels: d.labels, datasets: [{ data: d.values, backgroundColor: PALETTE, borderWidth: 2, borderColor: "#fff" }] },
      options: { maintainAspectRatio: false, cutout: "62%", plugins: { legend: { position: "bottom" } } }
    });
  }

  window.ReluxCharts = { trend: trend, doughnut: doughnut };
  document.querySelectorAll("[data-chart]").forEach(function (el) {
    var kind = el.dataset.chart;
    if (window.ReluxCharts[kind]) window.ReluxCharts[kind](el.id, el.dataset.source);
  });
})();
