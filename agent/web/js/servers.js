/* Several Minecraft servers: the list, the tabs across the top (one per
   server, like the tabbed dividers of a portfolio), the "All servers" page
   and the running-jobs indicator. Every other page acts on state.serverId
   through api() (see serverPath in api.js). */

import { api } from "./api.js";
import { derive } from "./colors.js";
import { renderers, stateInfo, state } from "./state.js";
import { t, tn } from "./strings.js";
import { $, el, emptyState, fmt, icon, known, loadInto } from "./ui.js";

// Set by nav.js, which imports this module, to avoid a cycle.
export const hooks = { navigate: null, afterSwitch: null };

export async function loadServers() {
  const data = await api("/servers");
  state.servers = data.servers || [];
  state.palette = data.palette || [];
  state.nextColor = data.next_color || null;
  if (!state.servers.some((s) => s.id === state.serverId)) {
    state.serverId = data.default || (state.servers[0] && state.servers[0].id) || "";
  }
  return state.servers;
}

export function serverRow(id = state.serverId) {
  return state.servers.find((s) => s.id === id) || null;
}

export function serverName(id) {
  const found = serverRow(id);
  return found ? found.name : id;
}

export async function selectServer(id, page = null) {
  const switching = id && id !== state.serverId;
  if (switching) {
    const from = state.servers.findIndex((s) => s.id === state.serverId);
    const to = state.servers.findIndex((s) => s.id === id);
    state.flip = to < from ? "back" : "forward";
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
  }
  if (page && hooks.navigate) hooks.navigate(page);
  else if (switching && hooks.afterSwitch) hooks.afterSwitch();
}

/* ------------------------------------------------------------ the tabs */

function serverTab(s, selected) {
  const info = stateInfo(s.id === state.serverId && state.status ? state.status.state : s.state);
  const crashed = state.crashedElsewhere.has(s.id);
  const tab = el("button", {
    class: `tab server-tab${selected ? " selected" : ""}`,
    type: "button", role: "tab", id: `tab-${s.id}`,
    "aria-selected": selected ? "true" : "false", "aria-controls": "main",
    tabindex: selected ? "0" : "-1",
    "data-server": s.id,
    title: `${s.name}: ${t(info.label)}`,
    onclick: () => selectServer(s.id, state.scope === "server" ? null : "dashboard"),
  },
    el("span", { class: `status-dot tone-${crashed ? "danger" : info.tone}${info.busy ? " pulse" : ""}`,
      "aria-hidden": "true" }),
    el("span", { class: "tab-name" }, s.name),
    el("span", { class: "sr-only" }, `, ${crashed ? t("tabs.crashed") : t(info.label)}`),
    crashed ? el("span", { class: "tab-badge", "aria-hidden": "true" }, "!") : null);
  const tokens = s.color ? derive(s.color) : null;
  if (tokens) {
    tab.style.setProperty("--tab-fill", tokens["--tab-fill"]);
    tab.style.setProperty("--tab-text", tokens["--tab-text"]);
    tab.style.setProperty("--tab-edge", tokens["--accent-edge"]);
  }
  return tab;
}

function plainTab(id, label, selected, iconName, onclick, extraClass = "") {
  return el("button", {
    class: `tab plain-tab ${extraClass}${selected ? " selected" : ""}`, type: "button", role: "tab", id,
    "aria-selected": selected ? "true" : "false", "aria-controls": "main",
    tabindex: selected ? "0" : "-1", title: label, onclick,
  }, iconName ? icon(iconName) : null, el("span", { class: iconName === "plus" ? "sr-only" : "tab-name" }, label));
}

export function renderTabs() {
  const holder = $("#server-tabs");
  holder.setAttribute("aria-label", t("tabs.label"));
  const tabs = [
    plainTab("tab-all", t("page.servers"), state.scope === "all", "servers",
      () => hooks.navigate("servers"), "all-tab"),
    ...state.servers.map((s) => serverTab(s, state.scope === "server" && s.id === state.serverId)),
    plainTab("tab-add", t("page.add_server"), state.scope === "add", "plus",
      () => hooks.navigate("add-server"), "add-tab"),
  ];
  holder.replaceChildren(...tabs);
  // With nothing selected (the gear's pages), the first tab takes focus.
  if (!tabs.some((tab) => tab.getAttribute("aria-selected") === "true")) tabs[0].tabIndex = 0;
  const selected = holder.querySelector('[aria-selected="true"]');
  $("#main").setAttribute("aria-labelledby", selected ? selected.id : "page-title");
  if (selected) selected.scrollIntoView({ block: "nearest", inline: "nearest" });
}

// Arrow keys move between tabs (and open them), Home and End jump to the ends.
$("#server-tabs").addEventListener("keydown", (event) => {
  const tabs = [...$("#server-tabs").querySelectorAll('[role="tab"]')];
  const index = tabs.indexOf(document.activeElement);
  if (index < 0) return;
  const next = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: tabs.length - 1 }[event.key];
  if (next === undefined) return;
  event.preventDefault();
  const target = tabs[(next + tabs.length) % tabs.length];
  target.click();
  // the row is redrawn by the click; focus the new copy of the tab
  requestAnimationFrame(() => { const again = document.getElementById(target.id); if (again) again.focus(); });
});

/* ------------------------------------------------------------ jobs */

/* What is running right now, with its real progress or none at all. */
export function jobsIndicator() {
  const running = Object.values(state.jobs).filter((job) => job.state === "running");
  if (!running.length) return null;
  const first = running[0];
  const percent = known(first.progress) ? ` ${Math.round(first.progress * 100)}%` : "";
  const where = first.server_id && first.server_id !== state.serverId ? ` (${serverName(first.server_id)})` : "";
  const text = `${first.title}${where}: ${first.step || t("jobs.working")}${percent}`;
  return el("div", { class: "jobs", role: "status", title: running.map((j) => j.title).join("\n") },
    el("span", { class: "spinner", "aria-hidden": "true" }),
    el("span", { class: "jobs-text" }, running.length > 1 ? tn("jobs.running", running.length) : text));
}

export function updateJobs() {
  const holder = $("#jobs");
  if (holder) holder.replaceChildren(jobsIndicator() || "");
}

export function handleJobEvent(event) {
  const job = event.data || {};
  if (!job.id) return;
  if (job.state === "running") state.jobs[job.id] = job;
  else delete state.jobs[job.id];
  updateJobs();
}

/* ------------------------------------------------------------ All servers */

renderers.servers = (page) => loadInto(page, async () => {
  await loadServers();
  if (!state.servers.length) {
    return emptyState(t("servers.none"), t("servers.none_hint"));
  }
  return el("div", { class: "server-cards" }, state.servers.map((s) => {
    const info = stateInfo(s.state);
    const running = ["ONLINE", "STARTING", "STOPPING"].includes(s.state);
    const card = el("button", {
      class: "server-card", type: "button",
      onclick: () => selectServer(s.id, "dashboard"),
    },
      el("div", { class: "server-card-head" },
        el("span", { class: "swatch", "aria-hidden": "true" }),
        el("strong", {}, s.name),
        el("span", { class: "pill" },
          el("span", { class: `status-dot tone-${info.tone}${info.busy ? " pulse" : ""}` }), t(info.label))),
      el("dl", { class: "facts" },
        el("dt", {}, t("servers.players")),
        el("dd", {}, known(s.players_online)
          ? (known(s.max_players) ? t("servers.players_of", { n: s.players_online, max: s.max_players })
            : String(s.players_online))
          : t("value.unknown")),
        el("dt", {}, t("servers.uptime")),
        el("dd", {}, running ? fmt.duration(s.uptime) : t("servers.not_running")),
        el("dt", {}, t("servers.port")),
        el("dd", {}, s.game_port && known(s.game_port.port) ? String(s.game_port.port) : t("value.unknown"))));
    if (s.color) card.style.setProperty("--card-color", s.color);
    return card;
  }));
});
