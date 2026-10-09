/* "Restore world": going back to the world as it was at a point in time.

   Every point is a backup that already exists and that the app checked.
   Going back always takes a fresh backup of the world as it is now first,
   so this can itself be undone from the Backups page. The server has to be
   off, because a running Minecraft would write over whatever is put back.

   The same page brings a world in (a .zip, or a folder such as one in
   single-player's saves) and takes this server's world out as a .zip to
   play offline. A world brought in is read and shown first (its name,
   version and size); it replaces this world only after a confirm, through
   the same safe-change routine, so it can be undone. */

import { api, serverPath } from "../api.js";
import { navigate } from "../nav.js";
import { pickFolder } from "../panels/folders.js";
import { serverRow } from "../servers.js";
import { can, renderers, state } from "../state.js";
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

/* ------------------------------------------------------------ bringing a world in */

function worldFacts(world) {
  return el("dl", { class: "facts" },
    el("dt", {}, t("import.name")), el("dd", {}, world.name || world.folder_name),
    el("dt", {}, t("import.version")), el("dd", {}, world.version || t("value.unknown")),
    el("dt", {}, t("import.size")), el("dd", {}, t("import.size_value",
      { size: fmt.bytes(world.size_bytes), files: world.files })),
    el("dt", {}, t("import.last_played")),
    el("dd", {}, world.last_played ? fmt.time(world.last_played) : t("value.unknown")));
}

const isBedrock = () => (serverRow() || {}).edition === "bedrock";

/* Shows what was read and asks before replacing anything. A Bedrock world
   saved by a newer game version than the server runs is flagged: an older
   server can't load it. */
async function confirmImport(token, world, reload, fit = {}) {
  const warnings = [];
  if (fit.edition_matches === false) {
    warnings.push(t(world.edition === "bedrock" ? "import.is_bedrock" : "import.is_java"));
  }
  if (fit.newer_than_server === true) {
    warnings.push(t("import.newer", { world: world.version, server: fit.server_version }));
  }
  const ok = await confirmDialog({
    title: t("import.confirm_title", { name: world.name || world.folder_name }),
    body: el("div", {},
      worldFacts(world),
      world.read_problem ? el("p", { class: "banner warn" }, t("import.read_problem", { problem: world.read_problem })) : null,
      ...warnings.map((text) => el("p", { class: "banner warn" }, text)),
      fit.level_name ? el("p", {}, t("import.bedrock_level", { name: fit.level_name })) : null,
      el("p", {}, t("import.confirm_body"))),
    confirmLabel: t("import.confirm_action"), danger: true,
  });
  if (!ok) {
    api(`/world/import/${token}`, { method: "DELETE" }).catch(() => {});
    return;
  }
  toast(t("import.working"));
  try {
    const result = await api("/world/import", { method: "POST", body: { token, confirm: true } });
    toast(result.undo ? t("import.done_with_undo") : t("import.done"), "success", 10000);
    reload();
  } catch (err) { toast(err.message, "error", 12000); }
}

async function uploadZip(file, button, reload) {
  if (!file) return;
  await busy(button, t("import.reading"), async () => {
    const form = new FormData();
    form.append("file", file);
    try {
      const result = await api("/world/import/upload", { method: "POST", body: form });
      await confirmImport(result.token, result.world, reload, result);
    } catch (err) { toast(err.message, "error", 12000); }
  });
}

async function useFolder(path, button, reload) {
  await busy(button, t("import.reading"), async () => {
    try {
      const result = await api("/world/import/folder", { method: "POST", body: { path } });
      await confirmImport(result.token, result.world, reload, result);
    } catch (err) { toast(err.message, "error", 12000); }
  });
}

function importCard(running, reload) {
  const bedrock = isBedrock();
  const input = el("input", {
    type: "file", class: "sr-only", id: "world-zip",
    accept: bedrock ? ".mcworld,.mctemplate,.zip" : ".zip,application/zip",
  });
  const zipButton = el("button", { class: "btn", type: "button", disabled: running ? "disabled" : false,
    onclick: () => input.click() }, t(bedrock ? "import.choose_mcworld" : "import.choose_zip"));
  input.addEventListener("change", () => uploadZip(input.files[0], zipButton, reload));
  const drop = el("div", { class: "drop-zone" }, t(bedrock ? "import.drop_mcworld" : "import.drop"));
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => {
    e.preventDefault();
    drop.classList.remove("over");
    if (running) { toast(t("import.stop_first"), "error"); return; }
    uploadZip(e.dataTransfer.files[0], zipButton, reload);
  });
  const saves = el("div", { class: "mt-10" });
  // Single-player's saves folder holds Java worlds; Bedrock keeps its own.
  if (!bedrock) api("/world/saves").then((found) => {
    if (!found.worlds.length) return;
    saves.replaceChildren(el("h3", { class: "subheading" }, t("import.from_saves")),
      el("ul", { class: "saves-list" }, found.worlds.slice(0, 8).map((w) => el("li", {},
        el("span", { class: "grow" }, w.folder),
        el("span", { class: "hint" }, fmt.ago(w.modified)),
        el("button", { class: "btn small", type: "button", disabled: running ? "disabled" : false,
          onclick: (e) => useFolder(w.path, e.currentTarget, reload) }, t("import.use"))))));
  }).catch(() => {});
  const folderButton = el("button", { class: "btn", type: "button", disabled: running ? "disabled" : false,
    onclick: async (e) => {
      const button = e.currentTarget;
      const path = await pickFolder({ title: t("import.pick_title"), worlds: true });
      if (path) useFolder(path, button, reload);
    } }, t("import.choose_folder"));
  return section(t("import.title"), null,
    el("p", { class: "hint mt-0" }, t(bedrock ? "import.lead_bedrock" : "import.lead")),
    running ? el("div", { class: "banner warn" }, t("import.stop_first")) : null,
    drop, input,
    el("div", { class: "btn-row mt-10" }, zipButton, folderButton),
    saves);
}

function downloadCard() {
  return section(t("download.title"), null,
    el("p", { class: "hint mt-0" }, t(isBedrock() ? "download.lead_bedrock" : "download.lead")),
    el("div", { class: "btn-row" }, el("button", { class: "btn", type: "button",
      onclick: (e) => busy(e.currentTarget, t("download.packing"), async () => {
        try {
          const result = await api("/world/download", { method: "POST" });
          const href = `/api${serverPath(`/world/download/${result.token}`)}?filename=${encodeURIComponent(result.filename)}`;
          const response = await fetch(href, { headers: { Authorization: `Bearer ${state.token}` } });
          if (!response.ok) throw new Error(t("backups.download_failed"));
          const url = URL.createObjectURL(await response.blob());
          const link = el("a", { href: url, download: result.filename });
          document.body.append(link); link.click(); link.remove();
          URL.revokeObjectURL(url);
        } catch (err) { toast(err.message, "error", 9000); }
      }) }, t("download.button"))));
}

renderers.world = (page) => loadInto(page, async () => {
  const reload = () => navigate("world");
  const data = await api("/world/timeline");
  const running = data.server_running;
  const help = withHelp(el("p", { class: "lead mt-0" }, t("world.lead")), "world_undo", "backups");
  const extra = [
    can("world.replace") ? importCard(running, reload) : null,
    can("backups.download") ? downloadCard() : null,
  ];

  if (!data.points.length) {
    return el("div", { class: "stack" }, section(t("world.title"), null, help,
      emptyState(t("world.none"), t("world.none_hint")),
      el("button", { class: "btn", type: "button", onclick: () => navigate("backups") }, t("world.open_backups"))),
      ...extra);
  }
  const notice = running
    ? problem(t("world.stop_first", { name: (state.status || {}).name || "" }), null,
        el("button", { class: "btn small", type: "button", onclick: () => navigate("dashboard") },
          t("world.open_overview")))
    : data.blocked_by
      ? problem(t("world.busy", { job: data.blocked_by }))
      : null;
  return el("div", { class: "stack" }, section(t("world.title"), null,
    help,
    notice,
    el("ul", { class: "timeline" }, data.points.map((p) => pointRow(p, data.can_restore, reload))),
    el("p", { class: "hint" }, t("world.footer"))),
    ...extra);
});
