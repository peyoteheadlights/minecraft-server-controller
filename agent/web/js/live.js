import { api } from "./api.js";
import { signOut } from "./auth.js";
import { navigate, render, renderRail } from "./nav.js";
import { appendChatLine, updateChatControls } from "./pages/chat.js";
import { appendConsoleLine, renderConsoleLines } from "./pages/console.js";
import { loadLatestCrash, overviewConsoleAppend, overviewUpdate } from "./pages/overview.js";
import { setFavicon } from "./colors.js";
import { handleJobEvent, loadServers, selectServer, serverName, serverRow, updateJobs } from "./servers.js";
import { stateInfo, state } from "./state.js";
import { t } from "./strings.js";
import { $, announce, el, known, toast } from "./ui.js";

export function connectSocket() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(`${protocol}//${location.host}/ws`);
  state.socket = socket;

  socket.onopen = () => socket.send(JSON.stringify({
    type: "auth", token: state.token, server_id: state.serverId,
  }));
  socket.onmessage = (event) => {
    let message;
    try { message = JSON.parse(event.data); } catch (e) { return; }
    if (message.type === "ready") {
      setLink(true);
      state.reconnectDelay = 1000;
      if (message.servers) mergeServers(message.servers);
      if (message.server_id !== state.serverId) return;  // switched while connecting
      state.status = message.status;
      state.console = message.console || [];
      state.chat = [];
      updateStatusViews();
      if (state.page === "console") renderConsoleLines();
      else if (state.page === "dashboard") render();
    } else if (message.type === "event" && message.event) {
      handleEvent(message.event);
    } else if (message.type === "console_tail") {
      if (message.server_id && message.server_id !== state.serverId) return;
      state.console = message.lines;
      if (state.page === "console") renderConsoleLines();
      else if (state.page === "dashboard") render();
    } else if (message.type === "error") {
      signOut(true);
    }
  };
  socket.onclose = () => {
    if (state.socket !== socket) return;
    setLink(false);
    // After a couple of failed tries, check whether the agent answers at
    // all; if not, the offline screen takes over and keeps trying.
    if (state.reconnectDelay > 2500) {
      fetch("/api/health", { cache: "no-store" })
        .then((r) => { if (!r.ok) throw new Error("down"); })
        .catch(() => import("./offline.js").then((o) => o.showOffline()));
    }
    setTimeout(() => { if (state.token) connectSocket(); }, state.reconnectDelay);
    state.reconnectDelay = Math.min(state.reconnectDelay * 1.7, 20000);
  };
  socket.onerror = () => socket.close();
}

/* The socket's server list has states but not colors; keep what we have. */
function mergeServers(rows) {
  const known_ = Object.fromEntries(state.servers.map((s) => [s.id, s]));
  state.servers = rows.map((row) => Object.assign({}, known_[row.id] || {}, row));
}

export function setLink(connected) {
  if (state.connected !== connected) {
    announce(connected ? t("live.connected_announce") : t("live.lost_announce"));
  }
  state.connected = connected;
  const node = $("#connection");
  if (!node) return;
  node.replaceChildren(
    el("span", { class: `status-dot tone-${connected ? "success" : "warning"}` }),
    el("span", { class: "label" }, connected ? t("live.connected") : t("live.reconnecting")));
  node.title = connected ? t("live.connected_title") : t("live.reconnecting_title");
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
    case "server_started": return t("event.server_started");
    case "server_stopped": return t("event.server_stopped");
    case "server_crashed":
      return known(data.exit_code) ? t("event.server_crashed_code", { code: data.exit_code })
        : t("event.server_crashed");
    case "server_recovered": return t("event.server_recovered");
    case "crash_loop": return t("event.crash_loop");
    default: return event.message || event.type;
  }
}

/* Events from a server other than the one on screen: keep its tab
   current, and make a crash impossible to miss. */
function otherServerEvent(event) {
  const row = state.servers.find((s) => s.id === event.server_id);
  if (event.type === "state" && row) {
    row.state = (event.data || {}).state;
    renderRail();
  }
  if (event.type === "server_crashed" || event.type === "crash_loop") {
    state.crashedElsewhere.add(event.server_id);
    const name = serverName(event.server_id);
    toast(t(event.type === "crash_loop" ? "event.other_crash_loop" : "event.other_crashed", { name }),
      "error", 9000, { label: t("event.show_server", { name }), onClick: () => selectServer(event.server_id, "dashboard") });
    renderRail();
  }
  if (state.page === "servers" && ["state", "server_started", "server_stopped",
    "server_crashed", "player_joined", "player_left"].includes(event.type)) {
    scheduleServersRender();
  }
}

let serversTimer = null;
function scheduleServersRender() {
  clearTimeout(serversTimer);
  serversTimer = setTimeout(() => { if (state.page === "servers") render(); }, 400);
}

export function handleEvent(event) {
  const data = event.data || {};
  if (event.type === "job") { handleJobEvent(event); return; }
  if (["server_added", "server_removed", "server_changed"].includes(event.type)) {
    loadServers().then(() => {
      renderRail();
      if (["servers", "settings", "add-server"].includes(state.page)) render();
    }).catch(() => {});
    if (event.type !== "server_changed") toast(event.message, "info");
    return;
  }
  if (event.server_id && event.server_id !== state.serverId) { otherServerEvent(event); return; }
  if (state.page === "servers") scheduleServersRender();
  if (event.type === "console") {
    if (state.paused) return;
    state.console.push(data);
    if (state.console.length > state.consoleLimit) state.console.splice(0, 200);
    if (state.page === "console") appendConsoleLine(data);
    if (state.page === "dashboard") overviewConsoleAppend(data);
    if (state.status && state.status.state === "STARTING") updateStatusViews();
    return;
  }
  if (event.type === "chat") {
    // Only this server's chat reaches this browser (the socket filters it).
    appendChatLine(data);
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
    const row = state.servers.find((s) => s.id === state.serverId);
    if (row) row.state = data.state;
    if (data.state === "STARTING") state.startingSince = event.ts;
    announce(t("live.state_announce", { state: t(stateInfo(data.state).label) }));
    updateStatusViews();
    // Pages whose buttons depend on the server being on or off.
    if (state.page === "chat") updateChatControls();
    if (state.page === "world") render();
    renderRail();
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
  // A whitelist, operator or ban change the console confirmed (from this
  // device or another): Minecraft's own lists have changed.
  if (event.type === "player_action") {
    if (state.page === "players") render();
    return;
  }
  if (event.type === "server_crashed") loadLatestCrash();  // the record now exists
  const level = NOTABLE[event.type];
  if (level) {
    const action = event.type === "server_crashed" || event.type === "crash_loop"
      ? { label: t("action.view_details"), onClick: () => navigate("crashes") } : null;
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

/* The sheet's status line: the state, and while it runs, who is on. */
export function updateStatusViews() {
  const status = state.status || {};
  const info = stateInfo(status.state);
  const line = $("#sheet-state");
  if (line) {
    const parts = [el("span", { class: `status-dot tone-${info.tone}${info.busy ? " pulse" : ""}` }),
      t(info.label)];
    if (status.state === "ONLINE" && known(status.players_online)) {
      parts.push(el("span", { class: "sep", "aria-hidden": "true" }, "·"),
        t(status.players_online === 1 ? "head.players.one" : "head.players.other",
          { count: status.players_online }));
    }
    line.replaceChildren(...parts);
  }
  updateJobs();
  updateTitle();
  if (state.page === "dashboard") overviewUpdate();
}

/* The browser tab says how the server is doing, so it can be checked from
   another tab: the state in the title, and a status dot on the icon. */
export function updateTitle() {
  const page = state.pageTitle || t("app.name");
  const row = state.scope === "server" ? serverRow() : null;
  if (!row) {
    document.title = `${page} · ${t("app.name")}`;
    setFavicon(null);
    return;
  }
  const name = state.status && state.status.state;
  const info = name ? stateInfo(name) : null;
  document.title = info && name !== "UNKNOWN" ? `${row.name} (${t(info.label)}) · ${page}` : `${row.name} · ${page}`;
  const dot = info && info.tone !== "neutral"
    ? getComputedStyle(document.documentElement).getPropertyValue(`--${info.tone}`).trim() : null;
  setFavicon(row.color, dot);
}
