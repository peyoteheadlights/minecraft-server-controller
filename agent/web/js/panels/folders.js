/* The folder picker: browse the PC's folders instead of typing a path.
   It lists folders only (never files), and marks the ones that hold a
   Minecraft world. Whatever is chosen is still checked by the agent. */

import { api } from "../api.js";
import { t } from "../strings.js";
import { confirmDialog, el, icon } from "../ui.js";

const SHORTCUT_WORDS = {
  home: "folders.home", desktop: "folders.desktop", onedrive: "folders.onedrive",
  google_drive: "folders.google_drive", dropbox: "folders.dropbox", saves: "folders.saves",
};

/* Opens the picker. Resolves to the chosen folder's path, or null. */
export async function pickFolder({ title, start = "", worlds = false } = {}) {
  let current = null;
  const where = el("div", { class: "folder-where mono", role: "status" });
  const list = el("ul", { class: "folder-list" });
  const body = el("div", { class: "folder-picker" }, where, list);

  const open = async (path) => {
    list.replaceChildren(el("li", { class: "hint" }, t("status.loading")));
    let data;
    try {
      data = await api(`/folders?path=${encodeURIComponent(path || "")}`);
    } catch (err) {
      list.replaceChildren(el("li", { class: "banner error" }, err.message));
      return;
    }
    current = data.path;
    where.textContent = data.path || t("folders.this_pc");
    const rows = [];
    if (data.path) {
      rows.push(entry(t("folders.up"), () => open(data.parent || "")));
    } else {
      for (const s of data.shortcuts) rows.push(entry(t(SHORTCUT_WORDS[s.key] || "folders.home"), () => open(s.path), s.path));
      for (const d of data.drives) rows.push(entry(t("folders.drive", { name: d.name }), () => open(d.path)));
    }
    for (const f of data.folders) {
      rows.push(entry(f.name, () => open(f.path), null, worlds && f.world ? t("folders.world") : null));
    }
    if (data.path && !data.folders.length) rows.push(el("li", { class: "hint" }, t("folders.empty")));
    if (data.truncated) rows.push(el("li", { class: "hint" }, t("folders.truncated")));
    list.replaceChildren(...rows);
  };

  function entry(label, onOpen, detail = null, tag = null) {
    return el("li", {}, el("button", { class: "folder-row", type: "button", onclick: onOpen },
      icon("chevron"), el("span", { class: "grow" }, label),
      detail ? el("span", { class: "hint mono" }, detail) : null,
      tag ? el("span", { class: "tag ok" }, tag) : null));
  }

  open(start);
  const ok = await confirmDialog({
    title: title || t("folders.title"), body, confirmLabel: t("folders.choose"), wide: true,
  });
  return ok && current ? current : null;
}
