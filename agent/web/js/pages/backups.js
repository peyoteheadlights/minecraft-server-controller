import { api, serverPath } from "../api.js";
import { render } from "../nav.js";
import { renderers, state } from "../state.js";
import { card, confirmDialog, el, fmt, loadInto, table, toast } from "../ui.js";

renderers.backups = (page) => loadInto(page, async () => {
  const [data, worlds, jobs] = await Promise.all([
    api("/backups"), api("/worlds"),
    api(`/jobs?server_id=${encodeURIComponent(state.serverId)}&limit=20`).catch(() => ({ jobs: [] })),
  ]);
  const holder = el("div");

  const last = lastUndoable(jobs.jobs || []);
  if (last) {
    holder.append(card("Last change", el("div", {},
      el("p", {}, `${last.title}, ${fmt.ago(last.finished_at)}. `
        + `Undo puts back the safety copy ${last.result.undo.backup} taken just before it.`),
      el("div", { class: "btn-row mt-10" },
        el("button", { class: "btn", onclick: () => undoChange(last) }, "Undo this change")))));
  }

  holder.append(el("div", { class: "btn-row mb-14" },
    el("button", {
      class: "btn primary",
      onclick: async () => {
        toast("Backup started. Large worlds take a while.");
        try {
          const result = await api("/backups", { method: "POST", body: {} });
          toast(`Backup verified: ${result.name} `
            + `(${result.verification ? result.verification.entries + " entries" : ""})`,
            "info", 8000);
          render();
        } catch (err) { toast(err.message, "error"); }
      },
    }, "Back up now"),
    el("button", {
      class: "btn",
      onclick: async () => {
        try { await api("/worlds/save", { method: "POST" }); toast("save-all flush sent"); }
        catch (err) { toast(err.message, "error"); }
      },
    }, "Save world now")));

  holder.append(card("Worlds", table(["World", "Size", "Last modified", "Last backup"],
    worlds.worlds.map((w) => [
      w.label,
      w.exists ? fmt.bytes(w.size_bytes) : "not present",
      w.exists ? fmt.time(w.modified) : "—",
      w.last_backup ? `${w.last_backup.name} (${fmt.ago(w.last_backup.created_at)})` : "never",
    ]))));

  holder.append(el("div", { class: "gap-section" },
    card(`Backups (keeping ${data.retention.daily} daily, ${data.retention.weekly} weekly, ${data.retention.monthly} monthly)`,
      data.backups.length
        ? table(["Name", "Type", "Created", "Size", ""], data.backups.map((b) => [
            el("span", { class: "mono" }, b.name),
            el("span", { class: `tag ${b.kind === "manual" ? "ok" : b.kind === "safety" ? "warn" : ""}` }, b.kind),
            fmt.time(b.created_at),
            fmt.bytes(b.size_bytes),
            el("div", { class: "btn-row" },
              el("button", {
                class: "btn small",
                onclick: async () => {
                  const result = await api(`/backups/${b.id}/verify`);
                  toast(result.ok ? "Backup verified: archive and checksum are intact"
                                  : `Verify failed: ${result.reason}`, result.ok ? "info" : "error");
                },
              }, "Verify"),
              el("a", { class: "btn small", href: `/api${serverPath(`/backups/${b.id}/download`)}`,
                        onclick: downloadWithToken }, "Download"),
              el("button", { class: "btn small", onclick: () => restoreBackup(b) }, "Restore"),
              el("button", {
                class: "btn small danger",
                onclick: async () => {
                  const ok = await confirmDialog({
                    title: `Delete ${b.name}?`,
                    body: "The archive file is deleted from disk. This cannot be undone.",
                    confirmLabel: "Delete backup", danger: true,
                  });
                  if (!ok) return;
                  await api(`/backups/${b.id}`, { method: "DELETE" });
                  toast("Backup deleted"); render();
                },
              }, "Delete")),
          ]))
        : el("div", { class: "empty" }, "No backups yet"))));
  return holder;
});

export async function downloadWithToken(event) {
  // Fetch with the bearer header, then hand the blob to the browser, so the
  // token never travels in a URL.
  event.preventDefault();
  const href = event.currentTarget.getAttribute("href");
  toast("Preparing download…");
  const response = await fetch(href, { headers: { Authorization: `Bearer ${state.token}` } });
  if (!response.ok) { toast("Download failed", "error"); return; }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = el("a", { href: url, download: href.split("/").pop() });
  document.body.append(link); link.click(); link.remove();
  URL.revokeObjectURL(url);
}

export async function restoreBackup(backup) {
  const preview = await api(`/backups/${backup.id}/restore`, { method: "POST", body: { confirm: false } });
  const startAfter = el("input", { type: "checkbox" });
  const body = el("div", {},
    el("p", {}, `Restore ${backup.name} from ${fmt.time(backup.created_at)}?`),
    el("ul", {}, preview.will_happen.map((item) => el("li", {}, item))),
    el("label", { class: "check-row mt-10" },
      startAfter, "Start the server when the restore finishes"));
  const ok = await confirmDialog({
    title: "Restore this backup?", body, confirmLabel: "Verify and restore", danger: true,
  });
  if (!ok) return;
  toast("Restoring. The server will stop first.");
  try {
    const result = await api(`/backups/${backup.id}/restore`, {
      method: "POST",
      body: { confirm: true, start_after: startAfter.checked, safety_backup: true },
    });
    const job = { id: result.job_id, title: `Restoring ${result.restored}`,
      result: { undo: result.undo } };
    toast(`Restored ${result.restored}. Safety copy: ${result.safety_backup.name}`, "info", 15000,
      result.job_id && result.undo ? { label: "Undo", onClick: () => undoChange(job) } : null);
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
    title: "Undo this change?",
    body: `${job.title} will be undone by restoring ${job.result.undo.backup}. `
      + "The server stops first, and a new safety copy is taken, so this can be undone too.",
    confirmLabel: "Undo", danger: true,
  });
  if (!ok) return;
  toast("Undoing. The server will stop first.");
  try {
    const result = await api(`/jobs/${encodeURIComponent(job.id)}/undo`, { method: "POST" });
    toast(`Undone: ${result.restored} is back.`);
    render();
  } catch (err) { toast(err.message, "error"); }
}
