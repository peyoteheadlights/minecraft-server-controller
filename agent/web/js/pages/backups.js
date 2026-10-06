import { api, serverPath } from "../api.js";
import { render } from "../nav.js";
import { pickFolder } from "../panels/folders.js";
import { can, renderers, state } from "../state.js";
import { t, technical } from "../strings.js";
import { busy, card, confirmDialog, el, emptyState, fmt, loadInto, table, toast, withHelp } from "../ui.js";

const KINDS = { manual: ["ok", "backups.kind_manual"], scheduled: ["", "backups.kind_scheduled"],
  safety: ["warn", "backups.kind_safety"] };

function kindTag(kind) {
  const [tone, key] = KINDS[kind] || ["", null];
  return el("span", { class: `tag ${tone}` }, key ? t(key) : kind);
}

function lastChangeCard(last) {
  return card(t("backups.last_change"),
    el("p", {}, t("backups.last_change_body", {
      title: last.title, when: fmt.ago(last.finished_at), backup: last.result.undo.backup })),
    el("div", { class: "btn-row mt-10" },
      el("button", { class: "btn", type: "button", onclick: () => undoChange(last) }, t("backups.undo_change"))));
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
  const choose = can("settings.edit") ? el("button", { class: "btn", type: "button",
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
  const off = offsite.directory && can("settings.edit") ? el("button", { class: "btn plain", type: "button",
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
    kindTag(b.kind),
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
  const [data, worlds, jobs, offsite] = await Promise.all([
    api("/backups"), api("/worlds"),
    api(`/jobs?server_id=${encodeURIComponent(state.serverId)}&limit=20`).catch(() => ({ jobs: [] })),
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

  const last = lastUndoable(jobs.jobs || []);
  if (last) holder.append(lastChangeCard(last));
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
    const job = { id: result.job_id, title: t("backups.restore_job", { name: result.restored }),
      result: { undo: result.undo } };
    toast(t("backups.restored", { name: result.restored, safety: result.safety_backup.name }), "success", 15000,
      result.job_id && result.undo ? { label: t("backups.undo"), onClick: () => undoChange(job) } : null);
    render();
  } catch (err) { toast(err.message, "error"); }
}

/* The newest finished change on this server that can be undone. */
function lastUndoable(jobs) {
  return jobs.find((job) => job.state === "succeeded" && job.result && job.result.undo) || null;
}

/* One-click undo of a safe change: restores the safety copy it took first.
   The undo is a change of its own, so it can be undone too. */
export async function undoChange(job) {
  const ok = await confirmDialog({
    title: t("backups.undo_title"),
    body: t("backups.undo_body", { title: job.title, backup: job.result.undo.backup }),
    confirmLabel: t("backups.undo"), danger: true,
  });
  if (!ok) return;
  toast(t("backups.undoing"));
  try {
    const result = await api(`/jobs/${encodeURIComponent(job.id)}/undo`, { method: "POST" });
    toast(t("backups.undone", { name: result.restored }), "success");
    render();
  } catch (err) { toast(err.message, "error"); }
}

