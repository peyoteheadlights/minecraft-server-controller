/* "Restore world": going back to the world as it was at a point in time.

   Every point is a backup that already exists and that the app checked.
   Going back always takes a fresh backup of the world as it is now first,
   so this can itself be undone from the Backups page. The server has to be
   off, because a running Minecraft would write over whatever is put back. */

import { api } from "../api.js";
import { navigate } from "../nav.js";
import { renderers, state } from "../state.js";
import { t, technical } from "../strings.js";
import { busy, confirmDialog, el, emptyState, fmt, known, loadInto, problem, section, toast, withHelp } from "../ui.js";

/* "Yesterday, 9:00 PM" — the words a person would use for a moment. */
export function whenLabel(ts) {
  const when = new Date(ts * 1000);
  const today = new Date();
  const midnight = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const days = Math.floor((midnight - new Date(when.getFullYear(), when.getMonth(), when.getDate())) / 86400000);
  const clock = when.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  if (days <= 0) return t("world.today_at", { time: clock });
  if (days === 1) return t("world.yesterday_at", { time: clock });
  if (days < 7) return t("world.day_at", { day: when.toLocaleDateString(undefined, { weekday: "long" }), time: clock });
  return t("world.date_at", { date: when.toLocaleDateString(undefined, { month: "short", day: "numeric" }), time: clock });
}

/* What going back to this point would lose, in plain words. */
export function lossLine(point) {
  const since = t("world.since", { duration: fmt.duration(point.age_seconds) });
  if (!known(point.played_seconds)) return `${since} · ${t("world.play_unknown")}`;
  if (point.played_seconds < 60) return `${since} · ${t("world.no_play")}`;
  return `${since} · ${t("world.play_lost", { duration: fmt.duration(point.played_seconds) })}`;
}

async function goBack(point, button, reload) {
  const ok = await confirmDialog({
    title: t("world.confirm_title", { when: whenLabel(point.created_at) }),
    body: el("div", {},
      el("p", {}, t("world.confirm_body", { loss: lossLine(point) })),
      el("p", {}, t("world.confirm_safety"))),
    confirmLabel: t("world.confirm_action"),
    danger: true,
  });
  if (!ok) return;
  await busy(button, t("world.working"), async () => {
    try {
      const result = await api("/world/undo", { method: "POST", body: { backup_id: point.backup_id, confirm: true } });
      const safety = result.safety_backup;
      toast(safety ? t("world.done_with_undo", { name: safety.name }) : t("world.done"), "success", 10000);
      reload();
    } catch (err) {
      toast(err.message, "error", 10000);
    }
  });
}

function pointRow(point, canRestore, reload) {
  const tags = [];
  if (point.kind === "safety") tags.push(el("span", { class: "tag" }, t("world.tag_safety")));
  if (!point.checked) tags.push(el("span", { class: "tag warn" }, t("backup.unchecked")));
  const action = point.checked
    ? el("button", { class: "btn small", type: "button", disabled: canRestore ? false : true,
        onclick: (e) => goBack(point, e.currentTarget, reload) }, t("world.go_back"))
    : el("span", { class: "hint" }, t("world.not_offered"));
  return el("li", { class: "timeline-point" },
    el("span", { class: "timeline-dot", "aria-hidden": "true" }),
    el("div", { class: "timeline-main" },
      el("strong", {}, whenLabel(point.created_at)),
      el("div", { class: "hint" }, lossLine(point)),
      technical() ? el("div", { class: "hint mono" },
        `${point.name} · ${fmt.bytes(point.size_bytes)} · ${point.includes || ""}`) : null),
    el("div", { class: "timeline-actions" }, ...tags, action));
}

renderers.world = (page) => loadInto(page, async () => {
  const reload = () => navigate("world");
  const data = await api("/world/timeline");
  const running = data.server_running;
  const help = withHelp(el("p", { class: "lead mt-0" }, t("world.lead")), "world_undo", "backups");

  if (!data.points.length) {
    return el("div", {}, section(t("world.title"), null, help,
      emptyState(t("world.none"), t("world.none_hint")),
      el("button", { class: "btn", type: "button", onclick: () => navigate("backups") }, t("world.open_backups"))));
  }
  const notice = running
    ? problem(t("world.stop_first", { name: (state.status || {}).name || "" }), null,
        el("button", { class: "btn small", type: "button", onclick: () => navigate("dashboard") },
          t("world.open_overview")))
    : data.blocked_by
      ? problem(t("world.busy", { job: data.blocked_by }))
      : null;
  return el("div", {}, section(t("world.title"), null,
    help,
    notice,
    el("ul", { class: "timeline" }, data.points.map((p) => pointRow(p, data.can_restore, reload))),
    el("p", { class: "hint" }, t("world.footer"))));
});
