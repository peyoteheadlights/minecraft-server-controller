import { signOut } from "./auth.js";
import { state } from "./state.js";
import { t } from "./strings.js";

// Areas that belong to one Minecraft server. Their paths are sent under
// /api/servers/<selected server>/, so every page acts on the server whose
// tab is open. Everything else (sign-in, agent settings, security, the
// server list, jobs) is about the agent itself.
const PER_SERVER = new Set([
  "status", "info", "server", "logs", "events", "crashes", "players", "performance",
  "worlds", "tps", "mods", "backups", "schedules", "recommendations",
  "game-settings", "join", "duplicate", "modpack",
]);

export function serverPath(path, serverId = state.serverId) {
  const head = path.split(/[/?]/)[1];
  const perServer = PER_SERVER.has(head) || path.startsWith("/health/server");
  if (!serverId || !perServer) return path;
  return `/servers/${encodeURIComponent(serverId)}${path}`;
}

export async function api(path, options = {}) {
  const headers = Object.assign({}, options.headers || {});
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(options.body);
  }
  let response;
  try {
    response = await fetch(`/api${serverPath(path)}`, Object.assign({}, options, { headers }));
  } catch (err) {
    throw new Error(t("error.unreachable"));
  }
  const isJson = (response.headers.get("content-type") || "").includes("application/json");
  const payload = isJson ? await response.json() : await response.text();
  // A 401 from sign-in means the password was wrong, not that a session
  // expired, so it is reported as the server worded it.
  if (response.status === 401 && path !== "/auth/login") {
    signOut(true);
    throw new Error(t("error.session_ended"));
  }
  if (!response.ok) {
    const error = new Error((payload && typeof payload.detail === "string" && payload.detail)
      || t("error.request_failed", { status: response.status }));
    // A form's per-field reasons, when the agent gave them.
    error.problems = (payload && typeof payload.problems === "object" && payload.problems) || null;
    throw error;
  }
  return payload;
}
