import { api } from "../api.js";
import { lineChart, niceTicks } from "../charts.js";
import { render } from "../nav.js";
import { tpsPanel } from "../panels/tps.js";
import { renderers, state } from "../state.js";
import { t, technical } from "../strings.js";
import { advanced, card, el, fmt, known, loadInto, metric, table } from "../ui.js";
import { serverRow } from "../servers.js";

const RANGES = [1, 6, 24, 168];

function rangePicker() {
  return el("div", { class: "segmented", role: "group", "aria-label": t("perf.range") },
    RANGES.map((hours) => el("button", {
      type: "button", "aria-pressed": state.range === hours ? "true" : "false",
      onclick: () => {
        state.range = hours;
        try { localStorage.setItem("mcsc_range", String(hours)); } catch (e) { /* this visit only */ }
        render();
      },
    }, t(`perf.range_${hours}`))));
}

renderers.performance = (page, toolbar) => {
  if (!RANGES.includes(state.range)) state.range = 6;
  toolbar.append(rangePicker());
  return renderPerformance(page);
};

/* Which cores the server runs on, as read from its process. */
function coresNote() {
  const cores = state.status && state.status.cpu_cores;
  if (!cores || !cores.applied) return t("perf.server_cpu_note");
  const all = cores.logical_cores && cores.applied.length === cores.logical_cores;
  return all ? t("perf.server_cpu_all") : t("perf.server_cpu_some", { n: cores.applied.length, total: cores.logical_cores });
}

function gb(mb) { return mb / 1024; }

function memoryFormat(useGb) {
  return (v, axis) => (useGb ? `${gb(v).toFixed(axis ? (gb(v) % 1 ? 1 : 0) : 1)} GB` : `${Math.round(v)} MB`);
}

function charts(data) {
  const series = data.series;
  const points = series.points;
  const to = Date.now() / 1000;
  const from = to - series.hours * 3600;
  // a missing bucket or two is jitter; more than that is a gap
  const gap = Math.max(series.bucket_seconds * 2.5, data.sample_interval * 3);
  const base = { points, from, to, gap };
  const limit = data.memory_limit_mb;
  const peak = Math.max(0, ...points.map((p) => p.proc_ram_mb || 0), limit || 0);
  const useGb = peak >= 1536;
  const memFormat = memoryFormat(useGb);
  const list = [
    lineChart({
      ...base, key: "cpu_percent", title: t("perf.chart_cpu"), unit: "%",
      format: (v) => `${Math.round(v)}%`, min: 0, max: 100, ticks: [0, 25, 50, 75, 100],
    }),
    lineChart({
      ...base, key: "proc_ram_mb", title: t("perf.chart_memory"), unit: useGb ? "GB" : "MB",
      format: memFormat, min: 0, max: null,
      // round gigabytes on the axis, not round megabytes shown as GB
      ticks: (top) => (useGb ? niceTicks(top / 1024).map((v) => v * 1024) : niceTicks(top)),
      guide: limit ? { value: limit, label: t("perf.limit", { limit: memFormat(limit) }) } : null,
      empty: t("perf.memory_empty"),
    }),
    lineChart({
      ...base, key: "tps", title: t("perf.chart_speed"), unit: t("perf.speed_unit"),
      format: (v, axis) => (axis ? String(v) : `${v.toFixed(1)} / 20`), min: 0, max: 20, ticks: [0, 5, 10, 15, 20],
      // Bedrock servers report no speed: said instead of an empty chart.
      empty: ((serverRow() || {}).capabilities || {}).speed === false
        ? t("perf.speed_not_bedrock") : t("perf.speed_empty"),
    }),
    lineChart({
      ...base, key: "players", title: t("perf.chart_players"), unit: t("perf.players_unit"),
      format: (v, axis) => (axis ? String(v) : (Math.round(v * 10) / 10).toString()), min: 0,
      max: Math.max(4, ...points.map((p) => p.players_max || 0)),
      empty: t("perf.players_empty"),
    }),
  ];
  if (technical()) {
    list.push(lineChart({
      ...base, key: "mspt", title: t("perf.chart_mspt"), unit: "ms",
      format: (v, axis) => `${axis ? Math.round(v) : v.toFixed(1)} ms`, min: 0, max: null, guide: { value: 50, label: t("perf.mspt_budget") },
      empty: t("perf.speed_empty"),
    }));
    list.push(lineChart({
      ...base, key: "ram_used_mb", title: t("perf.chart_pc_memory"), unit: "GB",
      format: (v, axis) => `${gb(v).toFixed(axis ? 0 : 1)} GB`, min: 0,
      ticks: (top) => niceTicks(Math.max(top, ...points.map((p) => p.ram_total_mb || 0)) / 1024).map((v) => v * 1024),
    }));
  }
  return el("div", { class: "chart-grid" }, list);
}

function storageCard(storage) {
  return card(t("perf.storage"), table([t("perf.storage_what"), t("perf.storage_size")], [
    [t("perf.storage_worlds"), fmt.gb(storage.worlds_gb)],
    [t("perf.storage_backups"), fmt.gb(storage.backups_gb)],
    [t("perf.storage_mods"), fmt.gb(storage.mods_gb)],
    [t("perf.storage_logs"), fmt.gb(storage.logs_gb)],
    [t("perf.storage_other"), fmt.gb(storage.other_gb)],
    [t("perf.storage_free"), storage.free_gb === null && storage.free_unknown_reason
      ? t("perf.unknown_because", { reason: storage.free_unknown_reason }) : fmt.gb(storage.free_gb)],
  ], { class: "numbers" }));
}

function healthCard(health) {
  const overall = {
    "ALL CHECKS VERIFIED": ["ok", t("health.all_ok")],
    "PARTIALLY VERIFIED": ["", t("health.partial")],
    "ATTENTION NEEDED": ["error", t("health.attention")],
  }[health.overall] || ["", health.overall];
  return el("div", {},
    el("div", { class: `banner ${overall[0]} mb-10` }, el("div", { class: "grow" },
      el("strong", {}, overall[1]),
      health.note ? el("div", { class: "hint" }, health.note) : null)),
    health.checks.map((check) => el("div", { class: "check" },
      el("span", { class: "name" }, check.name),
      el("span", { class: `val tag ${check.status === "ok" ? "ok" : check.status === "unknown" ? "off" : "warn"}` },
        known(check.value) ? String(check.value) : t("value.unknown")),
      el("span", { class: "detail" },
        check.detail
        + (known(check.threshold) ? ` (${t("health.limit", { limit: check.threshold })})` : "")
        + (check.source ? ` [${check.source}]` : "")))));
}

export const renderPerformance = (page) => loadInto(page, async () => {
  const [data, health] = await Promise.all([
    api(`/performance?hours=${state.range}`), api("/health/server"),
  ]);
  const c = data.current;
  const procMem = fmt.memory(c.proc_ram_mb);
  const limit = data.memory_limit_mb;
  const level = (v, warn, bad) => (v > bad ? "danger" : v > warn ? "warn" : "");
  const tpsNode = el("div");
  tpsPanel(tpsNode);
  return el("div", { class: "stack" },
    el("div", { class: "stats" },
      metric(t("perf.pc_cpu"), known(c.cpu_percent) ? fmt.pct(c.cpu_percent) : null,
        t("perf.pc_cpu_note"), { bar: c.cpu_percent, barLevel: level(c.cpu_percent, 75, 90) }),
      metric(t("perf.server_cpu"), known(c.process_cpu_percent) ? fmt.pct(c.process_cpu_percent) : null,
        coresNote(), { bar: c.process_cpu_percent }),
      metric(t("perf.server_memory"), procMem,
        procMem ? (limit ? t("perf.of_limit", { limit: fmt.memory(limit) }) : null) : t("perf.not_running_note"),
        { bar: procMem && limit ? (c.proc_ram_mb / limit) * 100 : null }),
      metric(t("perf.pc_memory"), known(c.ram_percent) ? fmt.pct(c.ram_percent) : null, t("perf.pc_memory_note"),
        { bar: c.ram_percent, barLevel: level(c.ram_percent, 80, 92) }),
      metric(t("perf.disk_free"), known(c.disk_free_gb) ? fmt.gb(c.disk_free_gb) : null,
        known(c.disk_free_gb) || !c.disk_unknown_reason ? t("perf.on_server_drive") : c.disk_unknown_reason)),
    charts(data),
    el("div", { class: "columns" },
      storageCard(data.storage),
      technical() ? card(t("perf.network"), el("div", { class: "rows" },
        el("div", { class: "row" }, el("span", { class: "row-label" }, t("perf.net_in")),
          el("span", { class: "row-value" }, known(c.net_recv_mb_s) ? `${c.net_recv_mb_s.toFixed(2)} MB/s` : t("value.unknown"))),
        el("div", { class: "row" }, el("span", { class: "row-label" }, t("perf.net_out")),
          el("span", { class: "row-value" }, known(c.net_sent_mb_s) ? `${c.net_sent_mb_s.toFixed(2)} MB/s` : t("value.unknown"))))) : null),
    advanced(t("perf.speed_readings"), tpsNode),
    advanced(t("perf.health"), healthCard(health)));
});
