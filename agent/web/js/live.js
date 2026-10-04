import { api } from "./api.js";
import { signOut } from "./auth.js";
import { navigate, render } from "./nav.js";
import { appendConsoleLine, renderConsoleLines } from "./pages/console.js";
import { loadLatestCrash, overviewConsoleAppend, overviewUpdate } from "./pages/overview.js";
import { STATES, state } from "./state.js";
import { $, announce, el, known, toast } from "./ui.js";

export function connectSocket() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(`${protocol}//${location.host}/ws`);
  state.socket = socket;

  socket.onopen = () => socket.send(JSON.stringify({ type: "auth", token: state.token }));
  socket.onmessage = (event) => {
    let message;
    try { message = JSON.parse(event.data); } catch (e) { return; }
    if (message.type === "ready") {
      setLink(true);
      state.reconnectDelay = 1000;
      state.status = message.status;
      state.console = message.console || [];
      updateStatusViews();
      if (state.page === "console") renderConsoleLines();
      else if (state.page === "dashboard") render();
    } else if (message.type === "event" && message.event) {
      handleEvent(message.event);
    } else if (message.type === "console_tail") {
      state.console = message.lines;
      renderConsoleLines();
    } else if (message.type === "error") {
      signOut(true);
    }
  };
  socket.onclose = () => {
    if (state.socket !== socket) return;
    setLink(false);
    setTimeout(() => { if (state.token) connectSocket(); }, state.reconnectDelay);
    state.reconnectDelay = Math.min(state.reconnectDelay * 1.7, 20000);
  };
  socket.onerror = () => socket.close();
}

export function setLink(connected) {
  if (state.connected !== connected) {
    announce(connected ? "Connected to the server agent." : "Connection to the agent lost. Reconnecting.");
  }
  state.connected = connected;
  const node = $("#connection");
  if (!node) return;
  node.replaceChildren(
    el("span", { class: `status-dot tone-${connected ? "success" : "warning"}` }),
    el("span", { class: "label" }, connected ? "Connected" : "Reconnecting…"));
  node.title = connected ? "Live updates are connected" : "Reconnecting to the agent";
}

export const NOTABLE = {
  server_started: "success", server_stopped: "info", server_crashed: "error",
  server_recovered: "success", crash_loop: "error", restart_cancelled: "info", tps_detection_failed: "warn",
  backup_completed: "success", backup_failed: "error", backup_restored: "warn",
  mod_installed: "success", mod_removed: "warn", mod_updated: "success",
  mod_rolled_back: "warn", high_ram: "warn", high_cpu: "warn", low_disk: "warn",
  low_tps: "warn", high_mspt: "warn", notification_failed: "warn",
  maintenance_mode: "info", schedule_finished: "info", certificate_expiring: "warn",
  certificate_problem: "error",
};

export function friendly(event) {
  const data = event.data || {};
  switch (event.type) {
    case "server_started": return "The server is online.";
    case "server_stopped": return "The server stopped.";
    case "server_crashed": {
      const code = known(data.exit_code) ? ` Exit code ${data.exit_code}.` : "";
      return `The server stopped unexpectedly.${code}`;
    }
    case "server_recovered": return "The server restarted after a crash and is online again.";
    case "crash_loop": return "Automatic restart is paused: the server crashed repeatedly.";
    default: return event.message || event.type;
  }
}

export function handleEvent(event) {
  const data = event.data || {};
  if (event.type === "console") {
    if (state.paused) return;
    state.console.push(data);
    if (state.console.length > state.consoleLimit) state.console.splice(0, 200);
    if (state.page === "console") appendConsoleLine(data);
    if (state.page === "dashboard") overviewConsoleAppend(data);
    if (state.status && state.status.state === "STARTING") updateStatusViews();
    return;
  }
  if (event.type === "state") {
    if (state.status) {
      state.status.state = data.state;
      // Take the exit details from the event itself. Keeping the previous
      // values until the next refresh showed a stale exit code as current.
      if ("exit_code" in data) state.status.last_exit_code = data.exit_code;
      if ("reason" in data) state.status.last_exit_reason = data.reason;
      state.status.restart_at = data.state === "RESTART_PENDING" ? (data.restart_at || null) : null;
      if (data.state === "CRASHED") state.latestCrash = null;
      if (data.state === "ONLINE") state.latestCrash = null;
    }
    if (data.state === "STARTING") state.startingSince = event.ts;
    announce(`Server ${(STATES[data.state] || STATES.UNKNOWN).label.replace("…", "")}.`);
    updateStatusViews();
    scheduleRefresh();
    return;
  }
  if (event.type === "metrics") {
    if (state.status) {
      state.status.metrics = data;
      // each sample carries the latest measured tick figures
      if ("tps" in data) state.status.tps = data.tps;
      if ("mspt" in data) state.status.mspt = data.mspt;
    }
    if (state.page === "dashboard") overviewUpdate();
    return;
  }
  if (event.type.startsWith("tps_")) {
    scheduleRefresh();   // detection started, found a command, or found none
    if (event.type !== "tps_detection_failed") return;
  }
  if (event.type === "player_joined" || event.type === "player_left") {
    scheduleRefresh();
    if (state.page === "players") render();
    return;
  }
  if (event.type === "server_crashed") loadLatestCrash();  // the record now exists
  const level = NOTABLE[event.type];
  if (level) {
    const action = event.type === "server_crashed" || event.type === "crash_loop"
      ? { label: "View details", onClick: () => navigate("crashes") } : null;
    toast(friendly(event), level, level === "error" ? 9000 : 5200, action);
    scheduleRefresh();
    if (["events", "crashes", "mods", "backups"].includes(state.page)) render();
  }
}

export function scheduleRefresh() {
  clearTimeout(state.refreshTimer);
  state.refreshTimer = setTimeout(refreshStatus, 350);
}

export async function refreshStatus() {
  try {
    state.status = await api("/status");
    if (state.status.state === "STARTING" && !state.startingSince) state.startingSince = state.status.started_at;
    updateStatusViews();
  } catch (e) { /* the connection indicator reports the outage */ }
}

export function renderStatus() { updateStatusViews(); }

export function updateStatusViews() {
  const status = state.status || {};
  const info = STATES[status.state] || STATES.UNKNOWN;
  const line = $("#sidebar-state");
  if (line) {
    line.replaceChildren(
      el("span", { class: `status-dot tone-${info.tone}${info.busy ? " pulse" : ""}` }),
      info.label);
  }
  const nameNode = $("#sidebar-name");
  if (nameNode && status.name) nameNode.textContent = status.name;
  if (state.page === "dashboard") overviewUpdate();
}
