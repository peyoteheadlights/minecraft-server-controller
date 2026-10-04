import { api } from "../api.js";
import { refreshStatus } from "../live.js";
import { navigate } from "../nav.js";
import { showCrash } from "./crashes.js";
import { CAUSES, STATES, renderers, state } from "../state.js";
import { busy, confirmDialog, el, emptyState, fmt, known, metric, toast } from "../ui.js";

export const overview = { nodes: null };

export function startingStage() {
  const since = state.startingSince || 0;
  const recent = state.console.filter((l) => !l.ts || l.ts >= since - 1).slice(-60);
  const text = recent.map((l) => l.raw).join("\n");
  if (/Preparing (spawn area|level|start region)/i.test(text)) return "Loading the world";
  if (/Starting Minecraft server on|Starting minecraft server version/i.test(text)) return "Starting the server";
  if (/Loading \d+ mods|with Fabric Loader/i.test(text)) return "Loading mods";
  return "Launching Java";
}

export function heroDetail(s) {
  const versions = s.minecraft_version
    ? `Minecraft ${s.minecraft_version}${s.fabric_loader ? ` with Fabric Loader ${s.fabric_loader}` : ""}.`
    : "";
  switch (s.state) {
    case "ONLINE":
      return [el("strong", {}, `Up for ${fmt.duration(s.uptime)}.`), " ", versions];
    case "STARTING": {
      const elapsed = state.startingSince ? ` ${Math.max(0, Math.round(Date.now() / 1000 - state.startingSince))}s` : "";
      return [el("strong", {}, `${startingStage()}…`), elapsed ? ` ${elapsed.trim()} so far.` : ""];
    }
    case "STOPPING": return ["Saving the world and shutting down."];
    case "RESTARTING": return ["Stopping the server, then starting it again."];
    case "RESTART_PENDING":
    case "CRASHED": {
      const parts = ["The server stopped unexpectedly."];
      if (known(s.last_exit_code)) parts.push(` Exit code ${s.last_exit_code}.`);
      const crash = state.latestCrash;
      if (crash && crash.category && crash.category !== "Unknown" && CAUSES[crash.category]) {
        const lead = { confirmed: "Cause", likely: "Likely cause", possible: "Possible cause" }[crash.confidence] || "Possible cause";
        parts.push(" ", el("strong", {}, `${lead}: ${CAUSES[crash.category]}.`));
      } else if (crash) {
        parts.push(" The cause could not be determined from the log.");
      } else {
        parts.push(" Reading the crash report…");
      }
      if (s.auto_restart_blocked) parts.push(" Automatic restart is paused.");
      else if (s.auto_restart_cancelled) parts.push(" Automatic restart cancelled.");
      if (s.state === "RESTART_PENDING") {
        const left = restartSecondsLeft(s);
        parts.push(el("div", { class: "countdown", role: "timer", "aria-live": "off" },
          left > 0 ? `Restarting in ${left}s` : "Starting server…"));
      }
      return parts;
    }
    case "OFFLINE":
      return [s.last_exit_reason === "force_killed" ? "The server was force stopped."
        : s.last_exit_reason ? "The server is stopped." : "The server is not running.",
        versions ? ` Last run: ${versions}` : ""];
    default:
      return ["The agent has not confirmed whether the server is running yet."];
  }
}

export function heroActions(s) {
  const busyState = (STATES[s.state] || {}).busy || state.pendingAction;
  const buttons = [];
  if (s.state === "ONLINE") {
    buttons.push(el("button", { class: "btn", type: "button", disabled: busyState,
      onclick: (e) => serverAction("restart", e.currentTarget) }, "Restart"));
    buttons.push(el("button", { class: "btn danger", type: "button", disabled: busyState,
      onclick: (e) => serverAction("stop", e.currentTarget) }, "Stop Server"));
  } else if (s.state === "STARTING" || s.state === "STOPPING" || s.state === "RESTARTING") {
    const label = STATES[s.state].label;
    buttons.push(el("button", { class: "btn is-busy", type: "button", disabled: true, "aria-busy": "true" },
      el("span", { class: "spinner", "aria-hidden": "true" }), label));
  } else if (s.state === "RESTART_PENDING") {
    // The normal Start button is not offered here: the server enforces this
    // too, so a second start cannot race the automatic one.
    buttons.push(el("button", { class: "btn plain", type: "button",
      onclick: () => (state.latestCrash ? showCrash(state.latestCrash.id) : navigate("crashes")) },
      "View Crash Details"));
    buttons.push(el("button", { class: "btn", type: "button", disabled: state.pendingAction,
      onclick: (e) => pendingRestartAction("cancel", e.currentTarget) }, "Cancel"));
    buttons.push(el("button", { class: "btn primary", type: "button", disabled: state.pendingAction,
      onclick: (e) => pendingRestartAction("now", e.currentTarget) }, "Restart Now"));
  } else if (s.state === "CRASHED") {
    buttons.push(el("button", { class: "btn plain", type: "button",
      onclick: () => (state.latestCrash ? showCrash(state.latestCrash.id) : navigate("crashes")) },
      "View Crash Details"));
    buttons.push(el("button", { class: "btn primary", type: "button", disabled: busyState,
      onclick: (e) => serverAction("start", e.currentTarget) }, "Start Server"));
  } else {
    buttons.push(el("button", { class: "btn primary", type: "button",
      disabled: busyState || s.state === "UNKNOWN",
      onclick: (e) => serverAction("start", e.currentTarget) }, "Start Server"));
  }
  return buttons;
}

export function tpsNote(s) {
  const t = s.tps_status || {};
  if (known(s.tps)) return t.command ? `via ${t.command}` : null;
  if (t.state === "detecting") return "Detecting…";
  if (t.state === "unavailable") return "No TPS command found";
  if (t.state === "disabled") return "Turned off";
  return s.state === "ONLINE" ? "Waiting for a reading" : "Server not running";
}

export function overviewStats(s) {
  const m = s.metrics || {};
  const limit = fmt.xmx(s.memory);
  const proc = fmt.memory(m.proc_ram_mb);
  const players = known(s.players_online) ? `${s.players_online}` : null;
  return [
    metric("Players", players, players === null ? "Not reported yet" : null,
      { unit: players !== null && s.max_players ? `/ ${s.max_players}` : "" }),
    metric("TPS", known(s.tps) ? s.tps.toFixed(1) : null, tpsNote(s)),
    metric("MSPT", known(s.mspt) ? s.mspt.toFixed(1) : null,
      known(s.mspt) ? null : "No tick-time source", { unit: "ms" }),
    metric("Server memory", proc,
      proc ? (limit ? `of ${limit} limit` : "measured") : (s.state === "ONLINE" ? "Not measured" : "Not running")),
    metric("CPU", known(m.cpu_percent) ? `${Math.round(m.cpu_percent)}%` : null, "Whole machine",
      { bar: m.cpu_percent, barLevel: m.cpu_percent > 90 ? "danger" : m.cpu_percent > 75 ? "warn" : "" }),
  ];
}

export function detailRows(pairs) {
  return el("div", { class: "rows" }, pairs.map(([label, value, mono]) => el("div", { class: "row" },
    el("span", { class: "row-label" }, label),
    el("span", { class: `row-value${mono ? " mono" : ""}`, title: value || "" }, value || "Unknown"))));
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

export function overviewUpdate() {
  const n = overview.nodes;
  if (!n || state.page !== "dashboard") return;
  const s = state.status || {};
  const info = STATES[s.state] || STATES.UNKNOWN;
  n.dot.className = `status-dot lg tone-${info.tone}${info.busy ? " pulse" : ""}`;
  n.title.textContent = info.label;
  n.title.style.color = ["CRASHED", "RESTART_PENDING"].includes(s.state) ? "var(--danger)" : "";
  n.detail.replaceChildren(...heroDetail(s));
  if (n.actionsState !== `${s.state}|${state.pendingAction}|${s.auto_restart_blocked}`) {
    n.actionsState = `${s.state}|${state.pendingAction}|${s.auto_restart_blocked}`;
    n.actions.replaceChildren(...heroActions(s));
  }
  n.stats.replaceChildren(...overviewStats(s));
  n.notices.replaceChildren(...overviewNotices(s));

  const players = s.players || [];
  n.players.replaceChildren(!known(s.players_online)
    ? emptyState("Player list not reported yet", "It appears when a player joins or the server answers /list.")
    : players.length
      ? detailRows(players.map((p) => [p.username, `Online for ${fmt.duration(p.session_seconds)}`]))
      : emptyState("No players online"));

  const m = s.metrics || {};
  n.details.replaceChildren(detailRows([
    ["Minecraft", s.minecraft_version || (s.state === "ONLINE" ? null : "Detected when the server starts")],
    ["Fabric Loader", s.fabric_loader || (s.state === "ONLINE" ? null : "Detected when the server starts")],
    ["Java", fmt.java(s.java_version)],
    ["Port", known(s.port) ? String(s.port) : null],
    ["Mods loaded", known(s.mod_count) ? String(s.mod_count) : (s.state === "ONLINE" ? null : "Reported at startup")],
    ["Disk free", known(m.disk_free_gb) ? fmt.gb(m.disk_free_gb) : null],
  ]));
}

export function overviewNotices(s) {
  const notices = [];
  if (s.maintenance) {
    notices.push(el("div", { class: "banner info", role: "status" },
      el("div", { class: "grow" }, el("strong", {}, "Maintenance mode is on. "),
        "Automatic restarts and scheduled tasks are paused."),
      el("button", { class: "btn small", type: "button",
        onclick: (e) => busy(e.currentTarget, "Turning off…", async () => {
          await api("/maintenance", { method: "POST", body: { enabled: false } });
          toast("Maintenance mode is off.", "success");
          refreshStatus();
        }) }, "Turn Off")));
  }
  if (s.auto_restart_blocked) {
    notices.push(el("div", { class: "banner error", role: "alert" },
      el("div", { class: "grow" }, el("strong", {}, "Automatic restart is paused. "),
        `The server crashed repeatedly (${s.auto_restart_block_reason}). Fix the cause, then allow restarts again.`),
      el("button", { class: "btn small", type: "button",
        onclick: (e) => busy(e.currentTarget, "Allowing…", async () => {
          await api("/server/clear-crash-block", { method: "POST" });
          toast("Automatic restarts are allowed again.", "success");
          refreshStatus();
        }) }, "Allow Restarts")));
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

renderers.dashboard = (page) => {
  const s = state.status || {};
  const nodes = {
    dot: el("span", { class: "status-dot lg", "aria-hidden": "true" }),
    title: el("h2", { id: "server-state-title" }),
    detail: el("p", { class: "hero-detail", id: "server-state-detail" }),
    actions: el("div", { class: "hero-actions" }),
    notices: el("div"),
    stats: el("div", { class: "stats", role: "group", "aria-label": "Server statistics" }),
    players: el("div"),
    details: el("div"),
    console: el("div", { class: "console-body", role: "log", "aria-label": "Recent console output" }),
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
    el("div", { class: "columns gap-section" },
      el("section", { class: "section" },
        el("div", { class: "section-head" }, el("h2", {}, "Players online")),
        el("div", { class: "group-box" }, nodes.players)),
      el("section", { class: "section" },
        el("div", { class: "section-head" }, el("h2", {}, "Server")),
        el("div", { class: "group-box" }, nodes.details))),
    el("section", { class: "section gap-section" },
      el("div", { class: "section-head" }, el("h2", {}, "Recent console"), el("div", { class: "grow" }),
        el("button", { class: "btn plain small", type: "button", onclick: () => navigate("console") },
          "Open Console")),
      el("div", { class: "console console-preview" }, nodes.console)));

  const lines = state.console.slice(-12);
  if (lines.length) lines.forEach((l) => nodes.console.append(logLine(l)));
  else nodes.console.append(emptyState("No console output yet", "Start the server to see its log here."));

  overviewUpdate();
  requestAnimationFrame(() => { nodes.console.scrollTop = nodes.console.scrollHeight; });
  if (s.state === "CRASHED" || s.state === "RESTART_PENDING") loadLatestCrash();

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
  state.pageTimer = setInterval(refreshStatus, 15000);
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
    await busy(button, kind === "now" ? "Starting…" : "Cancelling…", async () => {
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
      title: "Stop the Minecraft server?",
      body: "Players will be disconnected. The world is saved before the server shuts down.",
      confirmLabel: "Stop Server",
      danger: true,
    });
    if (!ok) return;
  } else if (action === "restart") {
    const ok = await confirmDialog({
      title: "Restart the Minecraft server?",
      body: "Players will be disconnected while the server stops and starts again.",
      confirmLabel: "Restart",
    });
    if (!ok) return;
  }
  const labels = { start: "Starting…", stop: "Stopping…", restart: "Restarting…" };
  state.pendingAction = action;
  if (action === "start") state.startingSince = Date.now() / 1000;
  overviewUpdate();
  const target = (overview.nodes && overview.nodes.actions.querySelector("button:not(.plain)")) || button;
  try {
    await busy(target, labels[action], async () => {
      try {
        const result = await api(`/server/${action}`, { method: "POST", body: {} });
        // success is announced by the server_stopped event, once, on every dashboard
        if (action === "restart" && result.result !== "VERIFIED") {
          toast("Restart requested. The server is starting.", "info");
        }
      } catch (err) {
        toast(err.message, "error", 9000);
      }
    });
  } finally {
    state.pendingAction = null;
    await refreshStatus();
  }
}
