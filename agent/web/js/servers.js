/* Several Minecraft servers: the list, the switcher in the sidebar, the
   "All servers" page, and the running-jobs line. Every other page acts on
   state.serverId through api() (see serverPath in api.js). */

import { api } from "./api.js";
import { renderers, STATES, state } from "./state.js";
import { $, card, el, emptyState, fmt, known, loadInto, table } from "./ui.js";

// Set by nav.js and live.js, which import this module, to avoid a cycle.
export const hooks = { navigate: null, afterSwitch: null };

export async function loadServers() {
  const data = await api("/servers");
  state.servers = data.servers || [];
  if (!state.servers.some((s) => s.id === state.serverId)) {
    state.serverId = data.default || (state.servers[0] && state.servers[0].id) || "";
  }
  return state.servers;
}

export function serverName(id) {
  const found = state.servers.find((s) => s.id === id);
  return found ? found.name : id;
}

export async function selectServer(id) {
  if (!id || id === state.serverId) return;
  state.serverId = id;
  state.crashedElsewhere.delete(id);
  try { localStorage.setItem("mcsc_server", id); } catch (e) { /* not remembered */ }
  state.console = [];
  state.latestCrash = null;
  state.startingSince = null;
  try { state.status = await api("/status"); } catch (e) { state.status = null; }
  if (state.socket && state.socket.readyState === WebSocket.OPEN) {
    state.socket.send(JSON.stringify({ type: "tail", server_id: id }));
  }
  if (hooks.afterSwitch) hooks.afterSwitch();
}

/* The sidebar head: the selected server's name, or a picker when there is
   more than one, with a badge when another server crashed. */
export function switcher() {
  const status = state.status || {};
  if (state.servers.length < 2) {
    return el("div", { class: "server-name", id: "sidebar-name" }, status.name || "Minecraft server");
  }
  const select = el("select", {
    class: "server-switcher", id: "server-switcher", "aria-label": "Server",
    onchange: (event) => selectServer(event.target.value),
  }, state.servers.map((s) => el("option", {
    value: s.id, selected: s.id === state.serverId ? "selected" : false,
  }, state.crashedElsewhere.has(s.id) ? `${s.name} (crashed)` : s.name)));
  const crashed = [...state.crashedElsewhere].filter((id) => id !== state.serverId);
  return el("div", { class: "switcher-row" }, select,
    crashed.length
      ? el("button", {
          class: "badge-dot", type: "button",
          title: `${crashed.map(serverName).join(", ")} crashed`,
          "aria-label": `${crashed.map(serverName).join(", ")} crashed. Show all servers.`,
          onclick: () => hooks.navigate && hooks.navigate("servers"),
        }, String(crashed.length))
      : null);
}

/* One line per running job, with its real progress or none at all. */
export function jobsLine() {
  const running = Object.values(state.jobs).filter((job) => job.state === "running");
  if (!running.length) return null;
  return el("div", { class: "jobs-line", role: "status" }, running.map((job) => {
    const percent = known(job.progress) ? ` ${Math.round(job.progress * 100)}%` : "";
    const where = job.server_id && job.server_id !== state.serverId ? ` (${serverName(job.server_id)})` : "";
    return el("div", { class: "job", title: job.step || job.title },
      el("span", { class: "status-dot tone-warning pulse" }),
      `${job.title}${where}: ${job.step || "working"}${percent}`);
  }));
}

export function updateJobsLine() {
  const holder = $("#jobs");
  if (holder) holder.replaceChildren(jobsLine() || "");
}

export function handleJobEvent(event) {
  const job = event.data || {};
  if (!job.id) return;
  if (job.state === "running") state.jobs[job.id] = job;
  else delete state.jobs[job.id];
  updateJobsLine();
}

renderers.servers = (page) => loadInto(page, async () => {
  await loadServers();
  if (!state.servers.length) return emptyState("No servers yet", "Add one in Settings.");
  const rows = state.servers.map((s) => {
    const info = STATES[s.state] || STATES.UNKNOWN;
    const players = known(s.players_online)
      ? `${s.players_online}${known(s.max_players) ? ` / ${s.max_players}` : ""}`
      : "Unknown";
    const running = s.state === "ONLINE" || s.state === "STARTING" || s.state === "STOPPING";
    return [
      el("span", {}, s.name, s.id === state.serverId ? el("span", { class: "tag off ml-6" }, "selected") : null),
      el("span", { class: "pill" },
        el("span", { class: `status-dot tone-${info.tone}${info.busy ? " pulse" : ""}` }), info.label),
      players,
      running ? fmt.duration(s.uptime) : "-",
      s.game_port && known(s.game_port.port) ? String(s.game_port.port) : "Unknown",
      el("button", {
        class: "btn small",
        onclick: async () => {
          await selectServer(s.id);
          if (hooks.navigate) hooks.navigate("dashboard");
        },
      }, "Open"),
    ];
  });
  return el("div", {},
    card(null, table(["Server", "State", "Players", "Uptime", "Port", ""], rows)),
    el("p", { class: "hint mt-10" },
      "Players and uptime are what each server reported; a server the agent has not "
      + "heard from shows Unknown. Add or remove servers in Settings."));
});
