/* The activity feed: events as plain sentences, grouped by day.

   Every sentence is built from an event the agent recorded, with the
   numbers that event carried. FEED maps an event type to its wording in the
   strings table; anything not listed falls back to the message the agent
   wrote, so a new event type is readable before it gets a sentence of its
   own. Technical mode adds the raw type and data under each line. */

import { t, technical } from "./strings.js";
import { el, fmt, known } from "./ui.js";

/* event type -> strings key. Keys hold the Simple and Technical wording. */
export const FEED = {
  server_started: "feed.server_started",
  server_stopped: "feed.server_stopped",
  server_crashed: "feed.server_crashed",
  server_restarted: "feed.server_restarted",
  server_recovered: "feed.server_recovered",
  crash_loop: "feed.crash_loop",
  player_joined: "feed.player_joined",
  player_left: "feed.player_left",
  backup_completed: "feed.backup_completed",
  backup_failed: "feed.backup_failed",
  low_tps: "feed.low_tps",
  high_mspt: "feed.high_mspt",
  high_ram: "feed.high_ram",
  high_cpu: "feed.high_cpu",
  low_disk: "feed.low_disk",
  auth_failure: "feed.auth_failure",
  agent_started: "feed.agent_started",
  agent_stopping: "feed.agent_stopping",
};

/* An event's data, whether it came live (an object) or from the stored
   history (where it is the JSON text the database holds). */
export function eventData(event) {
  const data = event.data;
  if (!data) return {};
  if (typeof data !== "string") return data;
  try {
    return JSON.parse(data) || {};
  } catch (err) {
    return {};
  }
}

/* Steps the app takes on the way to something that matters. They are the
   detail behind a line that is already in the feed ("Starting Minecraft"
   before "The server came online"), so Simple mode leaves them out and
   Technical mode keeps everything. */
export const INTERNAL = [
  "state", "console", "metrics", "job", "chat", "plain", "text",
  "server_start_requested", "server_stop_requested",
  "backup_started", "restore_stopping", "backup_retention",
  "tps_detection_started", "tps_command_detected", "tps_detection_failed",
  "server_changed", "data_folder_moved", "data_folder_not_moved",
];

export function worthShowing(event) {
  return technical() || !INTERNAL.includes(event.type);
}

/* The values a sentence may fill in, from the event's own data. */
function values(event) {
  const data = eventData(event);
  return {
    name: data.username || data.server_name || data.name || data.mod_name || "",
    duration: known(data.session_seconds) ? fmt.duration(data.session_seconds) : "",
    startup: known(data.startup_seconds) ? `${Number(data.startup_seconds).toFixed(1)}s` : "",
    code: known(data.exit_code) ? data.exit_code : "",
    backup: data.backup || data.name || "",
    minutes: known(data.empty_minutes) ? data.empty_minutes : "",
    version: data.version || data.minecraft_version || "",
    task: data.task ? t(`task.${data.task}`) : "",
    count: known(data.count) ? data.count : "",
  };
}

/* One plain sentence for an event, or the agent's own message. */
export function sentence(event) {
  const key = FEED[event.type];
  if (!key) return event.message || event.type;
  const filled = values(event);
  // A player who left without a measured session length gets the shorter
  // line, rather than a sentence with a gap in it.
  if (event.type === "player_left" && !filled.duration) {
    return t("feed.player_left_only", filled);
  }
  return t(key, filled);
}

export function dayLabel(ts) {
  const when = new Date(ts * 1000);
  const today = new Date();
  const start = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const days = Math.round((start(today) - start(when)) / 86400000);
  if (days <= 0) return t("feed.today");
  if (days === 1) return t("feed.yesterday");
  if (days < 7) return when.toLocaleDateString(undefined, { weekday: "long" });
  return when.toLocaleDateString(undefined, { month: "short", day: "numeric", year: days > 300 ? "numeric" : undefined });
}

const TONES = { error: "danger", warn: "warning", success: "success" };

export function feedLine(event) {
  const tone = TONES[event.level];
  return el("li", { class: "feed-item" },
    el("span", { class: `feed-dot tone-${tone || "neutral"}`, "aria-hidden": "true" }),
    el("div", { class: "feed-main" },
      el("span", { class: "feed-text" }, sentence(event)),
      technical() ? el("div", { class: "feed-raw mono" },
        [event.type, Object.entries(eventData(event))
          .filter(([, v]) => typeof v !== "object")
          .map(([k, v]) => `${k}=${v}`).join(" ")].filter(Boolean).join(" · ")) : null),
    el("span", { class: "feed-time" }, fmt.clock(event.ts)));
}

/* Events as day groups, newest day first, newest event first inside a day. */
export function feedDays(events, limit = 0) {
  const shown = events.filter(worthShowing);
  const rows = limit ? shown.slice(0, limit) : shown;
  const groups = [];
  for (const event of rows) {
    const label = dayLabel(event.ts);
    const last = groups[groups.length - 1];
    if (last && last.label === label) last.events.push(event);
    else groups.push({ label, events: [event] });
  }
  return groups;
}

export function feedList(events, limit = 0) {
  return el("div", { class: "feed" }, feedDays(events, limit).map((group) =>
    el("div", { class: "feed-day" },
      el("h3", { class: "feed-day-label" }, group.label),
      el("ul", { class: "feed-items" }, group.events.map(feedLine)))));
}
