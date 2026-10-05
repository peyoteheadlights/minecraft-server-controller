function remembered(key) {
  try { return localStorage.getItem(key) || ""; } catch (e) { return ""; }
}

export const state = {
  token: sessionStorage.getItem("mcsc_token") || "",
  // The server every page acts on, remembered per browser.
  serverId: remembered("mcsc_server"),
  servers: [],
  palette: [],
  nextColor: null,
  // Servers other than the selected one that crashed since they were last
  // looked at: shown on their tab.
  crashedElsewhere: new Set(),
  // Running jobs (backups, restores) by id, from "job" events.
  jobs: {},
  user: "",
  status: null,
  console: [],
  consoleLimit: 1000,
  autoscroll: true,
  paused: false,
  filter: "",
  page: "dashboard",
  // the current page's name, for the browser tab's title
  pageTitle: "",
  socket: null,
  connected: false,
  reconnectDelay: 1000,
  pageTimer: null,
  clock: null,
  pendingAction: null,
  startingSince: null,
  latestCrash: null,
  refreshTimer: null,
  // Performance graphs: hours of history shown.
  range: Number(remembered("mcsc_range")) || 6,
};

/* Every page: [key, strings key of its name, where it lives, icon].
   "server" pages sit in a server's sheet and act on state.serverId; "app"
   pages are about the agent itself and open from the gear; "all" is the
   All servers tab and "add" the "+" tab. Keys are URL hashes: never
   rename one. */
export const PAGES = [
  ["servers", "page.servers", "all", "servers"],
  ["add-server", "page.add_server", "add", "plus"],
  ["dashboard", "page.overview", "server", "overview"],
  ["players", "page.players", "server", "players"],
  ["backups", "page.backups", "server", "backups"],
  ["mods", "page.mods", "server", "mods"],
  ["schedules", "page.schedules", "server", "schedules"],
  ["performance", "page.performance", "server", "performance"],
  ["console", "page.console", "server", "console"],
  ["events", "page.events", "server", "events"],
  ["crashes", "page.crashes", "server", "crashes"],
  ["settings", "page.server_settings", "server", "settings"],
  ["app-settings", "page.app_settings", "app", "gear"],
  ["security", "page.security", "app", "security"],
];

export function pageEntry(key) {
  return PAGES.find(([k]) => k === key) || null;
}

/* The add-ons page calls itself what this server's type calls them:
   "Mods" on Fabric, Quilt, Forge and NeoForge, "Plugins" on Paper and
   Purpur. Vanilla takes neither, so the page is not offered at all. */
export function contentPage(row) {
  const kind = row && row.content;
  if (!kind) return null;
  return kind === "plugins" ? "page.plugins" : "page.mods";
}

/* label and tone are strings keys / status tones; busy states pulse. */
export const STATES = {
  ONLINE: { label: "state.online", tone: "success" },
  OFFLINE: { label: "state.offline", tone: "neutral" },
  STARTING: { label: "state.starting", tone: "warning", busy: true },
  STOPPING: { label: "state.stopping", tone: "warning", busy: true },
  RESTARTING: { label: "state.restarting", tone: "warning", busy: true },
  // crashed, with an automatic restart counting down
  RESTART_PENDING: { label: "state.crashed", tone: "danger" },
  CRASHED: { label: "state.crashed", tone: "danger" },
  UNKNOWN: { label: "state.unknown", tone: "neutral" },
};

export function stateInfo(name) {
  return STATES[name] || STATES.UNKNOWN;
}

// Crash categories from the analyzer; each has a strings key "cause.<name>".
export const CAUSES = [
  "OutOfMemoryError", "JavaHeapError", "JavaVersionIncompatible", "ModDependencyError",
  "MissingMod", "IncompatibleMod", "MixinError", "FabricLoaderError", "ClassNotFoundException",
  "NoSuchMethodError", "WorldChunkError", "DiskStorageError", "PortInUse", "EulaNotAccepted",
  "NetworkError", "ServerThreadCrash",
];

export const renderers = {};
