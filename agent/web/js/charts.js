import { el } from "./ui.js";

export function chart(history, key, label) {
  const width = 560, height = 140, pad = 4;
  const points = history.map((h) => h[key]).filter((v) => v !== null && v !== undefined);
  if (points.length < 2) return el("p", { class: "hint" }, `${label}: not enough samples yet`);
  const max = Math.max(...points) * 1.15 || 1;
  const step = (width - pad * 2) / (points.length - 1);
  const path = points.map((value, index) =>
    `${index === 0 ? "M" : "L"}${(pad + index * step).toFixed(1)},${(height - pad - (value / max) * (height - pad * 2)).toFixed(1)}`
  ).join(" ");
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("class", "chart");
  svg.setAttribute("preserveAspectRatio", "none");
  const line = document.createElementNS("http://www.w3.org/2000/svg", "path");
  line.setAttribute("d", path);
  line.setAttribute("fill", "none");
  line.setAttribute("stroke", "var(--accent)");
  line.setAttribute("stroke-width", "1.6");
  svg.append(line);
  return el("div", { style: "margin-bottom:14px" },
    el("div", { class: "chart-legend" },
      el("span", {}, label),
      el("span", {}, `peak ${Math.max(...points).toFixed(1)}`)),
    svg);
}
