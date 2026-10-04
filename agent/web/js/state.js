export const state = {
  token: sessionStorage.getItem("mcsc_token") || "",
  user: "",
  status: null,
  console: [],
  consoleLimit: 1000,
  autoscroll: true,
  paused: false,
  filter: "",
  page: "dashboard",
  socket: null,
  connected: false,
  reconnectDelay: 1000,
  pageTimer: null,
  clock: null,
  pendingAction: null,
  startingSince: null,
  latestCrash: null,
  refreshTimer: null,
};

// [key, label, group, icon]. Keys are the URL hashes and must not change.
export const PAGES = [
  ["dashboard", "Overview", "Server", "overview"],
  ["console", "Console", "Server", "console"],
  ["players", "Players", "Server", "players"],
  ["performance", "Performance", "Server", "performance"],
  ["backups", "Backups", "Manage", "backups"],
  ["mods", "Mods", "Manage", "mods"],
  ["schedules", "Schedules", "Manage", "schedules"],
  ["events", "Events", "Activity", "events"],
  ["crashes", "Crash history", "Activity", "crashes"],
  ["settings", "Settings", "System", "settings"],
  ["security", "Security", "System", "security"],
];

export const STATES = {
  ONLINE: { label: "Online", tone: "success" },
  OFFLINE: { label: "Offline", tone: "danger" },
  STARTING: { label: "Starting…", tone: "warning", busy: true },
  STOPPING: { label: "Stopping…", tone: "warning", busy: true },
  RESTARTING: { label: "Restarting…", tone: "warning", busy: true },
  // crashed, with an automatic restart counting down
  RESTART_PENDING: { label: "Crashed", tone: "danger" },
  CRASHED: { label: "Crashed", tone: "danger" },
  UNKNOWN: { label: "Status unknown", tone: "neutral" },
};

export const CAUSES = {
  OutOfMemoryError: "the server ran out of memory",
  JavaHeapError: "Java could not reserve the configured memory",
  JavaVersionIncompatible: "the installed Java version does not match this Minecraft version",
  ModDependencyError: "a mod is missing a dependency, or has the wrong version of one",
  MissingMod: "a required mod is not installed",
  IncompatibleMod: "two installed mods are incompatible",
  MixinError: "a mod failed to apply its changes to the game",
  FabricLoaderError: "Fabric Loader refused to start",
  ClassNotFoundException: "a mod was built for a different game version",
  NoSuchMethodError: "installed mods do not match each other's versions",
  WorldChunkError: "world data could not be loaded or saved",
  DiskStorageError: "the disk is full or not writable",
  PortInUse: "the server port is already in use",
  EulaNotAccepted: "the Minecraft EULA has not been accepted",
  NetworkError: "a network error",
  ServerThreadCrash: "an error in the main server thread",
};

export const renderers = {};
