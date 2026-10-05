/* Line graphs with real axes, drawn as plain SVG (no library, no build).

   Time runs along the bottom with clock ticks, the value up the side with
   its unit, on a fixed range where one exists (0-100% for CPU, 0-20 for
   server speed). Where there is no sample (the server was off, nothing
   answered) the line stops: a gap, never a line drawn through it or a
   zero. Hovering, tapping or using the arrow keys shows the exact value
   and time of a point. */

import { t } from "./strings.js";
import { el } from "./ui.js";

const NS = "http://www.w3.org/2000/svg";
const MARGIN = { top: 10, right: 14, bottom: 26, left: 48 };

function svgEl(tag, attrs = {}, text = null) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text !== null) node.textContent = text;
  return node;
}

/* Round numbers for a value axis: 0 to at least max, in 4 or 5 steps. */
export function niceTicks(max) {
  if (!(max > 0)) return [0, 1];
  const rough = max / 4;
  const power = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= rough);
  const ticks = [];
  for (let v = 0; v < max + step * 0.999; v += step) ticks.push(Math.round(v * 1e6) / 1e6);
  return ticks;
}

/* Clock ticks on whole hours (or days) that suit the range shown. */
export function timeTicks(from, to) {
  const span = to - from;
  const step = span <= 2 * 3600 ? 900 : span <= 8 * 3600 ? 3600 : span <= 30 * 3600 ? 4 * 3600 : 86400;
  const ticks = [];
  const offset = new Date().getTimezoneOffset() * 60;
  let tick = Math.ceil((from - offset) / step) * step + offset;
  if (step === 86400) {  // local midnight
    const d = new Date(from * 1000);
    d.setHours(24, 0, 0, 0);
    tick = d.getTime() / 1000;
  }
  for (; tick <= to; tick += step) ticks.push(tick);
  return { ticks, days: step >= 86400 };
}

function timeLabel(ts, days) {
  const d = new Date(ts * 1000);
  return days ? d.toLocaleDateString(undefined, { weekday: "short", day: "numeric" })
    : d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

function pointTime(ts, span) {
  const d = new Date(ts * 1000);
  return span > 30 * 3600
    ? d.toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" })
    : d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

/* Runs of consecutive points with values and no gap between them. */
export function segments(points, key, gap) {
  const runs = [];
  let run = [];
  let last = null;
  for (const p of points) {
    const v = p[key];
    if (v === null || v === undefined || Number.isNaN(v)) {
      if (run.length) runs.push(run);
      run = [];
      last = null;
      continue;
    }
    if (last !== null && p.ts - last > gap) {
      runs.push(run);
      run = [];
    }
    run.push(p);
    last = p.ts;
  }
  if (run.length) runs.push(run);
  return runs;
}

/**
 * A graph of one value over time.
 *   points  [{ts, [key]: number|null}], oldest first
 *   key     which value to draw
 *   title   shown above the graph
 *   unit    the y axis' unit label ("%", "GB", "TPS")
 *   format  value -> text for ticks and the tooltip
 *   from,to the time range shown (seconds)
 *   gap     seconds between samples beyond which the line breaks
 *   min,max fixed value range; max null scales to the data (and the guide)
 *   ticks   value-axis ticks, or a function of the top value that returns them
 *   guide   optional {value, label}: a dashed reference line (a limit)
 *   empty   what to say when there is nothing to draw
 */
export function lineChart(opts) {
  const { points, key, title, unit, format, from, to, gap, guide = null } = opts;
  const values = points.map((p) => p[key]).filter((v) => v !== null && v !== undefined);
  const figure = el("figure", { class: "chart-box" },
    el("figcaption", { class: "chart-title" }, el("span", {}, title),
      el("span", { class: "chart-unit" }, unit)));
  if (!values.length) {
    figure.append(el("div", { class: "chart-empty" }, opts.empty || t("chart.no_samples")));
    return figure;
  }
  const yMax = opts.max ?? Math.max(...values, guide ? guide.value : 0) * 1.1;
  const yTicks = typeof opts.ticks === "function" ? opts.ticks(yMax) : (opts.ticks || niceTicks(yMax));
  const top = yTicks[yTicks.length - 1];
  const holder = el("div", { class: "chart-plot" });
  const tip = el("div", { class: "chart-tip", role: "status", "aria-live": "polite", hidden: true });
  holder.append(tip);
  figure.append(holder);
  figure.tabIndex = 0;
  figure.setAttribute("aria-label", t("chart.aria", {
    title, latest: format(values[values.length - 1]),
    low: format(Math.min(...values)), high: format(Math.max(...values)),
  }));

  let cursor = -1;
  let geometry = null;
  const drawn = points.filter((p) => p[key] !== null && p[key] !== undefined);

  function draw() {
    const width = Math.max(240, Math.round(holder.clientWidth || 560));
    const height = opts.height || 170;
    const w = width - MARGIN.left - MARGIN.right;
    const h = height - MARGIN.top - MARGIN.bottom;
    const x = (ts) => MARGIN.left + ((ts - from) / (to - from)) * w;
    const y = (v) => MARGIN.top + h - (Math.min(Math.max(v, 0), top) / top) * h;
    geometry = { x, y };
    const svg = svgEl("svg", { viewBox: `0 0 ${width} ${height}`, width, height, class: "chart", "aria-hidden": "true" });
    for (const v of yTicks) {
      svg.append(svgEl("line", { x1: MARGIN.left, x2: width - MARGIN.right, y1: y(v), y2: y(v), class: "grid" }));
      svg.append(svgEl("text", { x: MARGIN.left - 8, y: y(v) + 4, class: "tick y" }, format(v, true)));
    }
    const { ticks, days } = timeTicks(from, to);
    const every = Math.max(1, Math.ceil(ticks.length / Math.max(2, Math.floor(w / 80))));
    ticks.forEach((ts, i) => {
      if (i % every) return;
      svg.append(svgEl("line", { x1: x(ts), x2: x(ts), y1: MARGIN.top, y2: MARGIN.top + h, class: "grid v" }));
      svg.append(svgEl("text", { x: x(ts), y: height - 8, class: "tick x" }, timeLabel(ts, days)));
    });
    if (guide && guide.value <= top) {
      svg.append(svgEl("line", { x1: MARGIN.left, x2: width - MARGIN.right, y1: y(guide.value), y2: y(guide.value), class: "guide" }));
      svg.append(svgEl("text", { x: width - MARGIN.right - 4, y: y(guide.value) - 5, class: "guide-label" }, guide.label));
    }
    for (const run of segments(points, key, gap)) {
      if (run.length === 1) {
        svg.append(svgEl("circle", { cx: x(run[0].ts), cy: y(run[0][key]), r: 2.2, class: "dot" }));
        continue;
      }
      const d = run.map((p, i) => `${i ? "L" : "M"}${x(p.ts).toFixed(1)},${y(p[key]).toFixed(1)}`).join(" ");
      svg.append(svgEl("path", { d: `${d} L${x(run[run.length - 1].ts).toFixed(1)},${MARGIN.top + h} L${x(run[0].ts).toFixed(1)},${MARGIN.top + h} Z`, class: "area" }));
      svg.append(svgEl("path", { d, class: "line" }));
    }
    svg.append(svgEl("line", { class: "cursor", y1: MARGIN.top, y2: MARGIN.top + h, x1: 0, x2: 0, visibility: "hidden" }));
    svg.append(svgEl("circle", { class: "cursor-dot", r: 4, cx: 0, cy: 0, visibility: "hidden" }));
    const old = holder.querySelector("svg");
    if (old) old.replaceWith(svg); else holder.prepend(svg);
    if (cursor >= 0) show(cursor);
  }

  function show(index) {
    if (!drawn.length || !geometry) return;
    cursor = Math.max(0, Math.min(drawn.length - 1, index));
    const p = drawn[cursor];
    const svg = holder.querySelector("svg");
    const cx = geometry.x(p.ts), cy = geometry.y(p[key]);
    const line = svg.querySelector(".cursor");
    line.setAttribute("x1", cx); line.setAttribute("x2", cx);
    line.setAttribute("visibility", "visible");
    const dot = svg.querySelector(".cursor-dot");
    dot.setAttribute("cx", cx); dot.setAttribute("cy", cy);
    dot.setAttribute("visibility", "visible");
    tip.hidden = false;
    tip.replaceChildren(el("strong", {}, format(p[key])), el("span", {}, pointTime(p.ts, to - from)));
    const left = Math.min(Math.max(cx, 60), holder.clientWidth - 60);
    tip.style.left = `${left}px`;
    tip.style.top = `${Math.max(0, cy - 44)}px`;
  }

  function hide() {
    cursor = -1;
    tip.hidden = true;
    const svg = holder.querySelector("svg");
    if (!svg) return;
    svg.querySelector(".cursor").setAttribute("visibility", "hidden");
    svg.querySelector(".cursor-dot").setAttribute("visibility", "hidden");
  }

  function nearest(clientX) {
    const rect = holder.getBoundingClientRect();
    const ts = from + ((clientX - rect.left - MARGIN.left) / (rect.width - MARGIN.left - MARGIN.right)) * (to - from);
    let best = 0;
    drawn.forEach((p, i) => { if (Math.abs(p.ts - ts) < Math.abs(drawn[best].ts - ts)) best = i; });
    return best;
  }

  holder.addEventListener("pointermove", (e) => show(nearest(e.clientX)));
  holder.addEventListener("pointerdown", (e) => show(nearest(e.clientX)));
  holder.addEventListener("pointerleave", (e) => { if (e.pointerType === "mouse") hide(); });
  figure.addEventListener("focus", () => show(cursor >= 0 ? cursor : drawn.length - 1));
  figure.addEventListener("blur", hide);
  figure.addEventListener("keydown", (e) => {
    const step = { ArrowLeft: -1, ArrowRight: 1, Home: -Infinity, End: Infinity }[e.key];
    if (step === undefined) return;
    e.preventDefault();
    show(Number.isFinite(step) ? cursor + step : (step < 0 ? 0 : drawn.length - 1));
  });

  new ResizeObserver(() => draw()).observe(holder);
  requestAnimationFrame(draw);
  return figure;
}
