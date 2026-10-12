import { api, serverPath } from "../api.js";
import { render } from "../nav.js";
import { pickFolder } from "../panels/folders.js";
import { can, renderers, state } from "../state.js";
import { t, technical } from "../strings.js";
import { busy, card, confirmDialog, el, emptyState, fmt, loadInto, table, toast, withHelp } from "../ui.js";
import { lossLine } from "./world.js";

const KINDS = { manual: ["ok", "backups.kind_manual"], scheduled: ["", "backups.kind_scheduled"],
  safety: ["warn", "backups.kind_safety"] };

/* A backup made before a change is named by that change ("Before changing
   game settings"); the agent words that label. */
function kindTag(b) {
  const [tone, key] = KINDS[b.kind] || ["", null];
  return el("span", { class: `tag ${tone}` }, b.label || (key ? t(key) : b.kind));
}

/* Undo and Redo: the server's two stacks of changes. Undo reverses the
   newest change, and pressing it again reverses the one before. */
function changesCard(changes) {
  const nextUndo = changes.undo[0];
  const nextRedo = changes.redo[0];
  if (!nextUndo && !nextRedo) return null;
  const blocked = Boolean(changes.blocked_by);
  const later = changes.undo.slice(1, 4);
  return card(t("changes.title"),
    nextUndo ? el("p", {}, t("changes.next_undo", { title: nextUndo.title, when: fmt.ago(nextUndo.made_at),
      who: nextUndo.user || t("value.unknown") })) : el("p", {}, t("changes.nothing_to_undo")),
    nextRedo ? el("p", {}, t("changes.next_redo", { title: nextRedo.title, when: fmt.ago(nextRedo.undone_at) })) : null,
    later.length ? el("div", { class: "hint" }, t("changes.then"),
      el("ul", {}, later.map((c) => el("li", {}, t("changes.later_item", { title: c.title, when: fmt.ago(c.made_at) }))))) : null,
    blocked ? el("p", { class: "hint" }, t("world.busy", { job: changes.blocked_by })) : null,
    can("backups.restore") ? el("div", { class: "btn-row mt-10" },
      el("button", { class: "btn", type: "button", disabled: !nextUndo || blocked,
        onclick: () => moveChange("undo", nextUndo) }, t("changes.undo")),
      el("button", { class: "btn", type: "button", disabled: !nextRedo || blocked,
        onclick: () => moveChange("redo", nextRedo) }, t("changes.redo"))) : null);
}

function worldsCard(worlds) {
  return card(t("backups.worlds"), table(
    [t("backups.col_world"), t("backups.col_size"), t("backups.col_modified"), t("backups.col_last_backup")],
    worlds.map((w) => [
      w.label,
      w.exists ? fmt.bytes(w.size_bytes) : t("backups.world_missing"),
      w.exists ? fmt.time(w.modified) : "—",
      w.last_backup
        ? (technical() ? `${w.last_backup.name} (${fmt.ago(w.last_backup.created_at)})` : fmt.ago(w.last_backup.created_at))
        : t("time.never"),
    ])));
}

/* The second copy's state, as the agent found it just now. */
function copyCell(b, offsite) {
  const copy = b.copy || { state: "none" };
  const words = {
    ok: ["ok", t("offsite.copied")],
    failed: ["danger", t("offsite.failed", { reason: copy.reason })],
    unreachable: ["warn", t("offsite.unreachable", { reason: copy.reason })],
    missing: ["warn", t("offsite.missing")],
    none: ["", t("offsite.not_copied")],
  }[copy.state] || ["", t("value.unknown")];
  const again = offsite.directory && b.status === "ok" && copy.state !== "ok" && can("backups.create")
    ? el("button", { class: "btn plain small", type: "button",
        onclick: (e) => busy(e.currentTarget, t("offsite.copying"), async () => {
          try {
            const result = await api(`/backups/${b.id}/copy`, { method: "POST" });
            const state_ = (result.copy || {}).state;
            toast(state_ === "ok" ? t("offsite.copy_done") : t("offsite.copy_failed", {
              reason: (result.copy || {}).reason || t("value.unknown") }), state_ === "ok" ? "success" : "error", 9000);
            render();
          } catch (err) { toast(err.message, "error", 9000); }
        }) }, t("offsite.copy_now"))
    : null;
  return el("div", { class: "copy-cell" }, el("span", { class: `tag ${words[0]}`,
    title: copy.path || "" }, words[1]), again);
}

function offsiteCard(offsite) {
  const status = offsite.directory
    ? (offsite.unavailable
      ? el("div", { class: "banner warn" }, t("offsite.folder_unavailable", { folder: offsite.directory, reason: offsite.unavailable }))
      : el("p", { class: "mt-0" }, t("offsite.folder_ok", { folder: offsite.directory })))
    : el("p", { class: "hint mt-0" }, t("offsite.off"));
  const choose = can("pc.settings") ? el("button", { class: "btn", type: "button",
    onclick: async (e) => {
      const button = e.currentTarget;
      const path = await pickFolder({ title: t("offsite.pick_title"), start: offsite.directory || "" });
      if (!path) return;
      await busy(button, t("action.saving"), async () => {
        try {
          await api("/backups/offsite", { method: "PUT", body: { directory: path } });
          toast(t("offsite.saved"), "success", 8000);
          render();
        } catch (err) { toast(err.message, "error", 12000); }
      });
    } }, offsite.directory ? t("offsite.change") : t("offsite.choose")) : null;
  const off = offsite.directory && can("pc.settings") ? el("button", { class: "btn plain", type: "button",
    onclick: (e) => busy(e.currentTarget, t("action.saving"), async () => {
      try {
        await api("/backups/offsite", { method: "PUT", body: { directory: "" } });
        toast(t("offsite.turned_off"));
        render();
      } catch (err) { toast(err.message, "error"); }
    }) }, t("offsite.turn_off")) : null;
  return card(t("offsite.title"),
    withHelp(el("span", { class: "help-label" }, t("offsite.lead")), "offsite", "backups"),
    status,
    technical() && offsite.subfolder ? el("p", { class: "hint mono" }, offsite.subfolder) : null,
    el("div", { class: "btn-row mt-10" }, choose, off));
}

function backupRow(b, offsite) {
  return [
    technical() ? el("span", { class: "mono" }, b.name) : fmt.time(b.created_at),
    kindTag(b),
    ...(technical() ? [fmt.time(b.created_at)] : []),
    fmt.bytes(b.size_bytes),
    copyCell(b, offsite),
    el("div", { class: "btn-row" },
      el("button", {
        class: "btn small", type: "button",
        onclick: (e) => busy(e.currentTarget, t("backups.checking"), async () => {
          try {
            const result = await api(`/backups/${b.id}/verify`);
            toast(result.ok ? t("backups.verify_ok") : t("backups.verify_failed", { reason: result.reason }),
              result.ok ? "success" : "error");
          } catch (err) { toast(err.message, "error"); }
        }),
      }, t("backups.verify")),
      can("backups.download") ? el("a", { class: "btn small", href: `/api${serverPath(`/backups/${b.id}/download`)}`,
                onclick: downloadWithToken }, t("backups.download")) : null,
      can("backups.restore") ? el("button", { class: "btn small", type: "button", onclick: () => restoreBackup(b) }, t("backups.restore")) : null,
      !can("backups.delete") ? null : el("button", {
        class: "btn small danger", type: "button",
        onclick: async () => {
          const ok = await confirmDialog({
            title: t("backups.delete_title", { name: b.name }),
            body: t("backups.delete_body"),
            confirmLabel: t("backups.delete_confirm"), danger: true,
          });
          if (!ok) return;
          try {
            await api(`/backups/${b.id}`, { method: "DELETE" });
            toast(t("backups.deleted")); render();
          } catch (err) { toast(err.message, "error"); }
        },
      }, t("backups.delete"))),
  ];
}

function backupsCard(data, offsite) {
  const headers = technical()
    ? [t("backups.col_name"), t("backups.col_type"), t("backups.col_created"), t("backups.col_size"), t("offsite.col"), ""]
    : [t("backups.col_created"), t("backups.col_type"), t("backups.col_size"), t("offsite.col"), ""];
  const r = data.retention;
  return card(t("backups.list"),
    data.backups.length
      ? table(headers, data.backups.map((b) => backupRow(b, offsite)))
      : emptyState(t("backups.none"), t("backups.none_hint")),
    el("p", { class: "hint mt-10" },
      t("backups.keeping", { daily: r.daily, weekly: r.weekly, monthly: r.monthly })));
}

renderers.backups = (page) => loadInto(page, async () => {
  const [data, worlds, changes, offsite] = await Promise.all([
    api("/backups"), api("/worlds"),
    api("/changes").catch(() => ({ undo: [], redo: [] })),
    api("/backups/offsite").catch(() => ({ directory: "", unavailable: null })),
  ]);
  const holder = el("div", { class: "stack" });

  holder.append(el("div", { class: "btn-row" },
    el("button", {
      class: "btn primary", type: "button",
      onclick: (e) => busy(e.currentTarget, t("backup.working"), async () => {
        toast(t("backups.started"));
        try {
          const result = await api("/backups", { method: "POST", body: {} });
          toast(result.verification
            ? t("backups.verified_toast", { name: result.name, entries: result.verification.entries })
            : t("backup.done", { name: result.name }), "success", 8000);
          render();
        } catch (err) { toast(err.message, "error"); }
      }),
    }, t("action.back_up_now")),
    el("button", {
      class: "btn", type: "button",
      onclick: async () => {
        try { await api("/worlds/save", { method: "POST" }); toast(t("backups.save_sent")); }
        catch (err) { toast(err.message, "error"); }
      },
    }, t("backups.save_world"))));

  const history = changesCard(changes);
  if (history) holder.append(history);
  holder.append(backupsCard(data, offsite));
  holder.append(offsiteCard(offsite));
  holder.append(worldsCard(worlds.worlds));
  return holder;
});

export async function downloadWithToken(event) {
  // Fetch with the bearer header, then hand the blob to the browser, so the
  // token never travels in a URL.
  event.preventDefault();
  const href = event.currentTarget.getAttribute("href");
  toast(t("backups.preparing"));
  const response = await fetch(href, { headers: { Authorization: `Bearer ${state.token}` } });
  if (!response.ok) { toast(t("backups.download_failed"), "error"); return; }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = el("a", { href: url, download: href.split("/").pop() });
  document.body.append(link); link.click(); link.remove();
  URL.revokeObjectURL(url);
}

export async function restoreBackup(backup) {
  let preview;
  try {
    preview = await api(`/backups/${backup.id}/restore`, { method: "POST", body: { confirm: false } });
  } catch (err) { toast(err.message, "error"); return; }
  const startAfter = el("input", { type: "checkbox" });
  const body = el("div", {},
    el("p", {}, t("backups.restore_question", { name: backup.name, when: fmt.time(backup.created_at) })),
    el("ul", {}, preview.will_happen.map((item) => el("li", {}, item))),
    el("label", { class: "check-row mt-10" }, startAfter, t("backups.start_after")));
  const ok = await confirmDialog({
    title: t("backups.restore_title"), body, confirmLabel: t("backups.restore_confirm"), danger: true,
  });
  if (!ok) return;
  toast(t("backups.restoring"));
  try {
    const result = await api(`/backups/${backup.id}/restore`, {
      method: "POST",
      body: { confirm: true, start_after: startAfter.checked, safety_backup: true },
    });
    toast(t("backups.restored", { name: result.restored }), "success", 15000,
      result.undo ? { label: t("changes.undo"), onClick: undoNewest } : null);
    render();
  } catch (err) { toast(err.message, "error"); }
}

const MOVE = {
  undo: { title: "changes.undo_title", body: "changes.undo_body", button: "changes.undo",
    working: "changes.undo_working", done: "changes.undo_done" },
  redo: { title: "changes.redo_title", body: "changes.redo_body", button: "changes.redo",
    working: "changes.redo_working", done: "changes.redo_done" },
};

/* Undo the newest change, or Redo the one undone last, after saying what
   goes back and what would be lost. */
export async function moveChange(direction, change) {
  const keys = MOVE[direction];
  const loss = lossLine({ age_seconds: Date.now() / 1000 - change.backup_at, played_seconds: change.played_seconds });
  const what = change.scope ? change.scope.join(", ") : t("changes.everything");
  const ok = await confirmDialog({
    title: t(keys.title, { title: change.title }),
    body: el("div", {},
      el("p", {}, t(keys.body, { what, when: fmt.time(change.backup_at) })),
      el("p", {}, loss),
      el("p", {}, t("changes.server_stops"))),
    confirmLabel: t(keys.button), danger: true,
  });
  if (!ok) return;
  toast(t(keys.working));
  try {
    await api(`/changes/${direction}`, { method: "POST", body: {} });
    toast(t(keys.done, { title: change.title }), "success");
    render();
  } catch (err) { toast(err.message, "error"); }
}

/* Undo straight after a change, from its toast: the change is the newest
   one, so this is the same as pressing Undo on the Backups page. */
export async function undoNewest() {
  try {
    const changes = await api("/changes");
    if (changes.undo[0]) await moveChange("undo", changes.undo[0]);
  } catch (err) { toast(err.message, "error"); }
}
