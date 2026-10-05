import { api } from "../api.js";
import { refreshStatus } from "../live.js";
import { navigate } from "../nav.js";
import { showCrash } from "./crashes.js";
import { CAUSES, renderers, stateInfo, state } from "../state.js";
import { t, technical, tn } from "../strings.js";
import { busy, confirmDialog, detailRows, el, emptyState, fmt, icon, known, metric, section, toast } from "../ui.js";

export const overview = { nodes: null, hour: null };

export function startingStage() {
  const since = state.startingSince || 0;
  const recent = state.console.filter((l) => !l.ts || l.ts >= since - 1).slice(-60);
  const text = recent.map((l) => l.raw).join("\n");
  if (/Preparing (spawn area|level|start region)/i.test(text)) return t("starting.world");
  if (/Starting Minecraft server on|Starting minecraft server version/i.test(text)) return t("starting.server");
  if (/Loading \d+ mods|with Fabric Loader/i.test(text)) return t("starting.mods");
  return t("starting.java");
}

function versionLine(s) {
  if (!s.minecraft_version) return "";
  return s.fabric_loader && technical()
    ? t("hero.version_loader", { mc: s.minecraft_version, loader: s.fabric_loader })
    : t("hero.version", { mc: s.minecraft_version });
}

export function heroDetail(s) {
  const versions = versionLine(s);
  switch (s.state) {
    case "ONLINE":
      return [el("strong", {}, t("hero.up_for", { duration: fmt.duration(s.uptime) })), versions ? ` · ${versions}` : ""];
    case "STARTING": {
      const elapsed = state.startingSince ? Math.max(0, Math.round(Date.now() / 1000 - state.startingSince)) : null;
      return [el("strong", {}, `${startingStage()}…`), known(elapsed) ? ` ${t("hero.so_far", { s: elapsed })}` : ""];
    }
    case "STOPPING": return [t("hero.stopping")];
    case "RESTARTING": return [t("hero.restarting")];
    case "RESTART_PENDING":
    case "CRASHED": {
      const parts = [t("hero.crashed")];
      if (known(s.last_exit_code) && technical()) parts.push(` ${t("hero.exit_code", { code: s.last_exit_code })}`);
      const crash = state.latestCrash;
      if (crash && crash.category && crash.category !== "Unknown") {
        const lead = { confirmed: "hero.cause", likely: "hero.likely_cause" }[crash.confidence] || "hero.possible_cause";
        parts.push(" ", el("strong", {}, t(lead, { cause: CAUSES.includes(crash.category) ? t(`cause.${crash.category}`) : crash.category })));
      } else if (crash) {
        parts.push(` ${t("hero.cause_unknown")}`);
      } else {
        parts.push(` ${t("hero.reading_crash")}`);
      }
      if (s.auto_restart_blocked) parts.push(` ${t("hero.restart_paused")}`);
      else if (s.auto_restart_cancelled) parts.push(` ${t("hero.restart_cancelled")}`);
      if (s.state === "RESTART_PENDING") {
        const left = restartSecondsLeft(s);
        parts.push(el("div", { class: "countdown", role: "timer", "aria-live": "off" },
          left > 0 ? t("hero.restarting_in", { s: left }) : t("hero.starting_now")));
      }
      return parts;
    }
    case "OFFLINE":
      return [s.last_exit_reason === "force_killed" ? t("hero.force_stopped")
        : s.last_exit_reason ? t("hero.stopped") : t("hero.not_running"),
        versions ? ` ${t("hero.last_run", { versions })}` : ""];
    default:
      return [t("hero.unknown")];
  }
}

export function heroActions(s) {
  const busyState = stateInfo(s.state).busy || state.pendingAction;
  const buttons = [];
  if (s.state === "ONLINE") {
    buttons.push(el("button", { class: "btn", type: "button", disabled: busyState,
      onclick: (e) => serverAction("restart", e.currentTarget) }, t("action.restart")));
    buttons.push(el("button", { class: "btn danger", type: "button", disabled: busyState,
      onclick: (e) => serverAction("stop", e.currentTarget) }, t("action.stop")));
  } else if (s.state === "STARTING" || s.state === "STOPPING" || s.state === "RESTARTING") {
    buttons.push(el("button", { class: "btn is-busy", type: "button", disabled: true, "aria-busy": "true" },
      el("span", { class: "spinner", "aria-hidden": "true" }), t(stateInfo(s.state).label)));
  } else if (s.state === "RESTART_PENDING") {
    // The normal Start button is not offered here: the server enforces this
    // too, so a second start cannot race the automatic one.
    buttons.push(el("button", { class: "btn plain", type: "button",
      onclick: () => (state.latestCrash ? showCrash(state.latestCrash.id) : navigate("crashes")) },
      t("action.what_happened")));
    buttons.push(el("button", { class: "btn", type: "button", disabled: state.pendingAction,
      onclick: (e) => pendingRestartAction("cancel", e.currentTarget) }, t("action.cancel")));
    buttons.push(el("button", { class: "btn primary", type: "button", disabled: state.pendingAction,
      onclick: (e) => pendingRestartAction("now", e.currentTarget) }, t("action.restart_now")));
  } else if (s.state === "CRASHED") {
    buttons.push(el("button", { class: "btn plain", type: "button",
      onclick: () => (state.latestCrash ? showCrash(state.latestCrash.id) : navigate("crashes")) },
      t("action.what_happened")));
    buttons.push(el("button", { class: "btn primary", type: "button", disabled: busyState,
      onclick: (e) => serverAction("start", e.currentTarget) }, t("action.start")));
  } else {
    buttons.push(el("button", { class: "btn primary", type: "button",
      disabled: busyState || s.state === "UNKNOWN",
      onclick: (e) => serverAction("start", e.currentTarget) }, t("action.start")));
  }
  return buttons;
}

/* Why server speed is not known, in a few words. */
export function speedNote(s) {
  const status = s.tps_status || {};
  if (known(s.tps)) {
    if (!technical()) return null;
    const parts = [];
    if (known(s.mspt)) parts.push(t("overview.mspt_now", { ms: s.mspt.toFixed(1) }));
    if (status.command) parts.push(t("overview.via", { command: status.command }));
    return parts.join(" · ") || null;
  }
  if (status.state === "detecting") return t("overview.speed_detecting");
  if (status.state === "unavailable") return t("overview.speed_unavailable");
  if (status.state === "disabled") return t("overview.speed_off");
  return s.state === "ONLINE" ? t("overview.speed_waiting") : t("overview.when_running");
}

/* ------------------------------------------------------------ hover summaries */

function hourPoints() {
  return (overview.hour && overview.hour.series && overview.hour.series.points) || [];
}

function summaryLines(lines) {
  return lines.filter(Boolean).map((line) => el("div", {}, line));
}

function playersSummary(s) {
  if (!known(s.players_online)) return summaryLines([t("summary.players_unknown")]);
  const players = s.players || [];
  if (!players.length) return summaryLines([t("summary.nobody")]);
  return players.map((p) => el("div", { class: "summary-row" },
    el("span", {}, p.username), el("span", {}, fmt.duration(p.session_seconds))));
}

function speedSummary() {
  const tps = hourPoints().filter((p) => known(p.tps));
  if (!tps.length) return summaryLines([t("summary.not_yet")]);
  const avg = tps.reduce((sum, p) => sum + p.tps, 0) / tps.length;
  const low = Math.min(...tps.map((p) => (known(p.tps_min) ? p.tps_min : p.tps)));
  return summaryLines([
    t("summary.last_hour"),
    t("summary.speed", { avg: avg.toFixed(1), low: low.toFixed(1) }),
    technical() ? t("summary.samples", { n: tps.length }) : null,
  ]);
}

function memorySummary(s) {
  const mem = hourPoints().filter((p) => known(p.proc_ram_mb));
  const limit = overview.hour && overview.hour.memory_limit_mb;
  if (!mem.length) {
    return summaryLines([t("summary.not_yet"), limit ? t("summary.limit", { limit: fmt.memory(limit) }) : null]);
  }
  const peak = Math.max(...mem.map((p) => (known(p.proc_ram_max) ? p.proc_ram_max : p.proc_ram_mb)));
  return summaryLines([
    t("summary.last_hour"),
    t("summary.memory_trend", { from: fmt.memory(mem[0].proc_ram_mb), to: fmt.memory(mem[mem.length - 1].proc_ram_mb) }),
    t("summary.memory_peak", { peak: fmt.memory(peak) }),
    limit ? t("summary.limit", { limit: fmt.memory(limit) }) : t("summary.no_limit"),
  ]);
}

function cpuSummary() {
  const cpu = hourPoints().filter((p) => known(p.cpu_percent));
  if (!cpu.length) return summaryLines([t("summary.not_yet")]);
  const avg = cpu.reduce((sum, p) => sum + p.cpu_percent, 0) / cpu.length;
  const high = Math.max(...cpu.map((p) => p.cpu_percent));
  return summaryLines([t("summary.last_hour"), t("summary.cpu", { avg: Math.round(avg), high: Math.round(high) })]);
}

export function overviewStats(s) {
  const m = s.metrics || {};
  const limit = fmt.xmx(s.memory);
  const proc = fmt.memory(m.proc_ram_mb);
  const players = known(s.players_online) ? `${s.players_online}` : null;
  const notRunning = s.state === "ONLINE" ? null : t("overview.when_running");
  return [
    metric(t("overview.players"), players, players === null ? (notRunning || t("overview.players_waiting")) : null,
      { unit: players !== null && s.max_players ? t("overview.of_max", { max: s.max_players }) : "",
        summary: () => playersSummary(s) }),
    metric(t("overview.speed"), known(s.tps) ? s.tps.toFixed(1) : null, speedNote(s),
      { unit: known(s.tps) ? t("overview.speed_unit") : "", summary: speedSummary }),
    metric(t("overview.memory"), proc,
      proc ? (limit ? t("overview.of_limit", { limit }) : null) : (notRunning || t("overview.not_measured")),
      { summary: () => memorySummary(s) }),
    metric(t("overview.cpu"), known(m.cpu_percent) ? `${Math.round(m.cpu_percent)}%` : null, t("overview.cpu_note"),
      { bar: m.cpu_percent, barLevel: m.cpu_percent > 90 ? "danger" : m.cpu_percent > 75 ? "warn" : "",
        summary: cpuSummary }),
  ];
}

export function logLine(line) {
  const raw = line.raw || "";
  const m = /^\[(\d{2}:\d{2}:\d{2})\]\s?(.*)$/s.exec(raw);
  const time = m ? m[1] : (line.ts ? fmt.clock(line.ts) : "");
  const text = m ? m[2] : raw;
  return el("div", { class: `log-line ${line.level || "INFO"} ${line.source || ""}` },
    el("span", { class: "time" }, time),
    el("span", { class: "msg" }, text));
}

function detailsRows(s) {
  const m = s.metrics || {};
  const later = s.state === "ONLINE" ? null : t("overview.detected_on_start");
  return detailRows([
    [t("overview.minecraft"), s.minecraft_version || later],
    technical() ? [t("overview.loader"), s.fabric_loader || later] : null,
    technical() ? [t("overview.java"), fmt.java(s.java_version)] : null,
    [t("overview.port"), known(s.port) ? String(s.port) : null],
    [t("overview.mods"), known(s.mod_count) ? String(s.mod_count) : later],
    [t("overview.disk_free"), known(m.disk_free_gb) ? fmt.gb(m.disk_free_gb)
      : (m.disk_unknown_reason ? t("perf.unknown_because", { reason: m.disk_unknown_reason }) : null)],
  ]);
}

export function overviewUpdate() {
  const n = overview.nodes;
  if (!n || state.page !== "dashboard") return;
  const s = state.status || {};
  const info = stateInfo(s.state);
  n.dot.className = `status-dot lg tone-${info.tone}${info.busy ? " pulse" : ""}`;
  n.title.textContent = t(info.label);
  n.title.classList.toggle("is-danger", ["CRASHED", "RESTART_PENDING"].includes(s.state));
  n.detail.replaceChildren(...heroDetail(s));
  const key = `${s.state}|${state.pendingAction}|${s.auto_restart_blocked}`;
  if (n.actionsState !== key) {
    n.actionsState = key;
    n.actions.replaceChildren(...heroActions(s));
  }
  // Keep a summary that is open (focused or hovered) where it is.
  if (!n.stats.querySelector(".stat:focus, .stat:hover, .stat.show-summary")) {
    n.stats.replaceChildren(...overviewStats(s));
  }
  n.notices.replaceChildren(...overviewNotices(s));

  const players = s.players || [];
  n.players.replaceChildren(!known(s.players_online)
    ? emptyState(t("overview.players_unknown"), t("overview.players_unknown_hint"))
    : players.length
      ? detailRows(players.map((p) => [p.username, t("overview.online_for", { duration: fmt.duration(p.session_seconds) })]))
      : emptyState(t("overview.nobody_online")));
  n.details.replaceChildren(detailsRows(s));
}

export function overviewNotices(s) {
  const notices = [];
  if (s.maintenance) {
    notices.push(el("div", { class: "banner info", role: "status" },
      el("div", { class: "grow" }, el("strong", {}, t("notice.maintenance")), " ", t("notice.maintenance_detail")),
      el("button", { class: "btn small", type: "button",
        onclick: (e) => busy(e.currentTarget, t("notice.turning_off"), async () => {
          await api("/maintenance", { method: "POST", body: { enabled: false } });
          toast(t("appset.maintenance_off"), "success");
          refreshStatus();
        }) }, t("notice.turn_off"))));
  }
  if (s.auto_restart_blocked) {
    notices.push(el("div", { class: "banner error", role: "alert" },
      el("div", { class: "grow" }, el("strong", {}, t("notice.restart_paused")), " ",
        t("notice.restart_paused_detail", { reason: s.auto_restart_block_reason })),
      el("button", { class: "btn small", type: "button",
        onclick: (e) => busy(e.currentTarget, t("notice.allowing"), async () => {
          await api("/server/clear-crash-block", { method: "POST" });
          toast(t("notice.restarts_allowed"), "success");
          refreshStatus();
        }) }, t("notice.allow_restarts"))));
  }
  return notices;
}

export function overviewConsoleAppend(line) {
  const body = overview.nodes && overview.nodes.console;
  if (!body) return;
  const empty = body.querySelector(".empty");
  if (empty) empty.remove();
  body.append(logLine(line));
  while (body.children.length > 40) body.firstChild.remove();
  body.scrollTop = body.scrollHeight;
}

export async function loadLatestCrash() {
  try {
    const data = await api("/crashes?limit=1");
    state.latestCrash = (data.crashes || [])[0] || null;
    overviewUpdate();
  } catch (e) { state.latestCrash = null; }
}

/* ------------------------------------------------------------ cards */

async function backupNow(button) {
  await busy(button, t("backup.working"), async () => {
    try {
      const result = await api("/backups", { method: "POST", body: {} });
      toast(t("backup.done", { name: result.name }), "success", 8000);
      if (overview.nodes) fillCards();
    } catch (err) { toast(err.message, "error", 9000); }
  });
}

function lastBackupCard(backups) {
  const newest = backups[0];
  if (!newest) {
    return el("div", { class: "info-card" },
      el("p", { class: "lead" }, t("backup.never")),
      el("p", { class: "hint" }, t("backup.never_hint")),
      el("button", { class: "btn primary", type: "button", onclick: (e) => backupNow(e.currentTarget) },
        t("action.back_up_now")));
  }
  const verdict = { ok: ["ok", "backup.checked"], unverified: ["warn", "backup.unchecked"], failed: ["error", "backup.failed"] }[newest.status]
    || ["off", "backup.unchecked"];
  return el("div", { class: "info-card" },
    el("p", { class: "lead" }, fmt.ago(newest.created_at)),
    el("p", { class: "hint" }, fmt.time(newest.created_at), " · ", fmt.bytes(newest.size_bytes), " ",
      el("span", { class: `tag ${verdict[0]}` }, t(verdict[1]))),
    technical() ? el("p", { class: "hint mono" }, newest.name) : null,
    el("button", { class: "btn", type: "button", onclick: (e) => backupNow(e.currentTarget) },
      t("action.back_up_now")));
}

function nextTaskCard(schedules) {
  const upcoming = schedules.filter((s) => s.enabled && s.next_run).sort((a, b) => a.next_run - b.next_run)[0];
  if (!upcoming) {
    return el("div", { class: "info-card" },
      el("p", { class: "lead" }, t("schedule.nothing")),
      el("button", { class: "btn plain", type: "button", onclick: () => navigate("schedules") }, t("schedule.add")));
  }
  return el("div", { class: "info-card" },
    el("p", { class: "lead" }, t("schedule.next", { task: t(`task.${upcoming.task}`), when: fmt.until(upcoming.next_run) })),
    el("p", { class: "hint" }, fmt.time(upcoming.next_run), upcoming.name ? ` · ${upcoming.name}` : ""),
    el("button", { class: "btn plain", type: "button", onclick: () => navigate("schedules") }, t("schedule.open")));
}

function recommendationItem(r) {
  const act = async (action) => {
    try {
      const view = await api(`/recommendations/${encodeURIComponent(r.id)}`, { method: "POST", body: { action } });
      renderRecommendations(view);
    } catch (err) { toast(err.message, "error"); }
  };
  const fix = r.action.url
    ? el("a", { class: "btn small", href: r.action.url, target: "_blank", rel: "noopener noreferrer" }, r.action.label)
    : el("button", { class: "btn small", type: "button", onclick: () => navigate(r.action.page) }, r.action.label);
  return el("li", { class: "rec" },
    el("div", { class: "rec-main" },
      el("strong", {}, r.title),
      el("div", { class: "rec-reason" }, r.reason),
      el("div", { class: "rec-evidence" }, icon("info"), r.evidence),
      technical() ? el("div", { class: "rec-details mono" },
        Object.entries(r.details).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : v}`).join(" · ")) : null),
    el("div", { class: "rec-actions" }, fix,
      el("button", { class: "btn plain small", type: "button", title: t("rec.snooze_title"), onclick: () => act("snooze") }, t("rec.snooze")),
      el("button", { class: "btn plain small", type: "button", title: t("rec.dismiss_title"), onclick: () => act("dismiss") }, t("rec.dismiss"))));
}

function renderRecommendations(view) {
  const n = overview.nodes;
  if (!n) return;
  const list = view.recommendations || [];
  const hidden = view.hidden || [];
  const restore = hidden.length ? el("details", { class: "rec-hidden" },
    el("summary", {}, tn("rec.hidden", hidden.length)),
    el("ul", {}, hidden.map((r) => el("li", {}, r.title, " ",
      el("button", { class: "btn plain small", type: "button", onclick: async () => {
        try {
          renderRecommendations(await api(`/recommendations/${encodeURIComponent(r.id)}`,
            { method: "POST", body: { action: "restore" } }));
        } catch (err) { toast(err.message, "error"); }
      } }, t("rec.show_again")))))) : null;
  n.recs.replaceChildren(list.length
    ? el("ul", { class: "rec-list" }, list.map(recommendationItem))
    : el("p", { class: "all-good" }, t("rec.none")), ...(restore ? [restore] : []));
}

async function fillCards() {
  const n = overview.nodes;
  const [backups, schedules, recs] = await Promise.all([
    api("/backups").catch(() => null), api("/schedules").catch(() => null),
    api("/recommendations").catch((err) => ({ error: err.message })),
  ]);
  if (n !== overview.nodes) return;
  n.backup.replaceChildren(backups ? lastBackupCard(backups.backups || []) : emptyState(t("value.unknown")));
  n.next.replaceChildren(schedules ? nextTaskCard(schedules.schedules || []) : emptyState(t("value.unknown")));
  if (recs.error) n.recs.replaceChildren(el("p", { class: "hint" }, recs.error));
  else renderRecommendations(recs);
}

async function loadHour() {
  try {
    overview.hour = await api("/performance?hours=1&storage=false");
  } catch (e) { overview.hour = null; }
}

renderers.dashboard = (page) => {
  const s = state.status || {};
  const nodes = {
    dot: el("span", { class: "status-dot lg", "aria-hidden": "true" }),
    title: el("h2", { id: "server-state-title" }),
    detail: el("p", { class: "hero-detail", id: "server-state-detail" }),
    actions: el("div", { class: "hero-actions" }),
    notices: el("div"),
    stats: el("div", { class: "stats", role: "group", "aria-label": t("overview.stats_label") }),
    backup: el("div", { class: "card-fill" }, el("div", { class: "empty" }, t("status.loading"))),
    next: el("div", { class: "card-fill" }, el("div", { class: "empty" }, t("status.loading"))),
    recs: el("div", {}, el("div", { class: "empty" }, t("status.loading"))),
    players: el("div"),
    details: el("div"),
    console: el("div", { class: "console-body", role: "log", "aria-label": t("overview.recent_console") }),
  };
  overview.nodes = nodes;

  page.append(
    nodes.notices,
    el("div", { class: "hero", role: "region", "aria-labelledby": "server-state-title" },
      el("div", { class: "hero-main" },
        el("div", { class: "hero-state" }, nodes.dot, nodes.title),
        nodes.detail),
      nodes.actions),
    nodes.stats,
    el("div", { class: "columns three gap-section" },
      section(t("overview.last_backup"), null, nodes.backup),
      section(t("overview.next_task"), null, nodes.next),
      section(t("overview.players_online"), null, nodes.players)),
    el("div", { class: "gap-section" }, section(t("overview.recommendations"), null, nodes.recs)),
    el("div", { class: "gap-section" }, section(t("overview.details"), null, nodes.details)),
    technical() ? el("section", { class: "section gap-section" },
      el("div", { class: "section-head" }, el("h2", {}, t("overview.recent_console")), el("div", { class: "grow" }),
        el("button", { class: "btn plain small", type: "button", onclick: () => navigate("console") },
          t("overview.open_console"))),
      el("div", { class: "console console-preview" }, nodes.console)) : "");

  const lines = state.console.slice(-12);
  if (lines.length) lines.forEach((l) => nodes.console.append(logLine(l)));
  else nodes.console.append(emptyState(t("console.empty"), t("console.empty_hint")));

  overviewUpdate();
  requestAnimationFrame(() => { nodes.console.scrollTop = nodes.console.scrollHeight; });
  if (s.state === "CRASHED" || s.state === "RESTART_PENDING") loadLatestCrash();
  fillCards();
  loadHour();

  state.clock = setInterval(() => {
    const st = state.status || {};
    if (st.state === "ONLINE" && known(st.uptime)) {
      st.uptime += 1;
      if (overview.nodes) overview.nodes.detail.replaceChildren(...heroDetail(st));
    } else if ((st.state === "STARTING" || st.state === "RESTART_PENDING") && overview.nodes) {
      overview.nodes.detail.replaceChildren(...heroDetail(st));
    }
  }, 1000);
  // live events keep this current; a slow poll covers anything missed
  let ticks = 0;
  state.pageTimer = setInterval(() => {
    refreshStatus();
    ticks += 1;
    if (ticks % 4 === 0) loadHour();
    if (ticks % 8 === 0) fillCards();
  }, 15000);
};

// The deadline comes from the agent (restart_at), so every open dashboard
// counts down to the same moment; the browser only formats it.
export function restartSecondsLeft(s) {
  if (known(s.restart_at)) return Math.max(0, Math.ceil(s.restart_at - Date.now() / 1000));
  if (known(s.restart_in)) return Math.max(0, Math.ceil(s.restart_in));
  return 0;
}

export async function pendingRestartAction(kind, button) {
  if (state.pendingAction) return;
  state.pendingAction = kind;
  try {
    await busy(button, kind === "now" ? t("action.starting") : t("action.cancelling"), async () => {
      try {
        await api(kind === "now" ? "/server/restart-now" : "/server/cancel-restart", { method: "POST" });
        // no local toast: the restart_cancelled event notifies every open dashboard
      } catch (err) {
        toast(err.message, "error", 8000);
      }
    });
  } finally {
    state.pendingAction = null;
    await refreshStatus();
  }
}

export async function serverAction(action, button) {
  if (state.pendingAction) return;
  if (action === "stop") {
    const ok = await confirmDialog({
      title: t("confirm.stop_title"), body: t("confirm.stop_body"),
      confirmLabel: t("action.stop"), danger: true,
    });
    if (!ok) return;
  } else if (action === "restart") {
    const ok = await confirmDialog({
      title: t("confirm.restart_title"), body: t("confirm.restart_body"), confirmLabel: t("action.restart"),
    });
    if (!ok) return;
  }
  const labels = { start: "action.starting", stop: "action.stopping", restart: "action.restarting" };
  state.pendingAction = action;
  if (action === "start") state.startingSince = Date.now() / 1000;
  overviewUpdate();
  const target = (overview.nodes && overview.nodes.actions.querySelector("button:not(.plain)")) || button;
  try {
    await busy(target, t(labels[action]), async () => {
      try {
        const result = await api(`/server/${action}`, { method: "POST", body: {} });
        // success is announced by the server_stopped event, once, on every dashboard
        if (action === "restart" && result.result !== "VERIFIED") toast(t("action.restart_requested"), "info");
      } catch (err) {
        toast(err.message, "error", 9000);
      }
    });
  } finally {
    state.pendingAction = null;
    await refreshStatus();
  }
}
