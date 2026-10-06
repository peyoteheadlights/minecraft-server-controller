/* Importing a Modrinth modpack (.mrpack), as a new server (the "+" tab)
   or into the server that is open (its Mods page).

   Choosing the file only reads it: the panel then shows the Minecraft
   version, the loader and its version, and every file in the pack, with
   what will be skipped (client-only) or refused and why. Nothing is
   downloaded or changed until the person presses the button. */

import { api } from "../api.js";
import { loadServers, selectServer } from "../servers.js";
import { state } from "../state.js";
import { t, technical } from "../strings.js";
import { busy, card, confirmDialog, detailRows, el, fmt, problem, table, toast } from "../ui.js";

const STATUS_WORDS = {
  download: ["pack.status_download", ""],
  client_only: ["pack.status_client", "off"],
  refused: ["pack.status_refused", "error"],
};

function packSummary(pack) {
  return detailRows([
    [t("pack.name"), pack.version ? `${pack.name} ${pack.version}` : pack.name],
    [t("pack.minecraft"), pack.minecraft_version],
    [t("pack.loader"), pack.loader_version ? `${pack.type_name} ${pack.loader_version}` : pack.type_name, true],
    [t("pack.files"), t("pack.files_value", { count: pack.download_count, size: fmt.bytes(pack.download_bytes) })],
    [t("pack.extras"), t("pack.extras_value", { count: pack.overrides, size: fmt.bytes(pack.overrides_bytes) })],
  ]);
}

function fileList(pack) {
  return table([t("pack.col_file"), t("pack.col_size"), t("pack.col_what")], pack.files.map((f) => {
    const [key, tone] = STATUS_WORDS[f.status] || STATUS_WORDS.refused;
    return [
      el("div", {}, el("span", { class: "mono" }, f.name),
        technical() ? el("div", { class: "hint mono" }, f.path) : null),
      f.size === null ? t("value.unknown") : fmt.bytes(f.size),
      el("div", {}, el("span", { class: `tag ${tone}` }, t(key)),
        f.reason ? el("div", { class: "hint" }, f.reason) : null),
    ];
  }));
}

function preview(pack) {
  return el("div", { class: "stack" },
    pack.summary ? el("p", { class: "hint mt-0" }, pack.summary) : null,
    packSummary(pack),
    pack.problems.length
      ? el("div", { class: "banner error", role: "alert" }, el("div", { class: "grow" },
          el("strong", {}, t("pack.cant_import")), el("ul", {}, pack.problems.map((p) => el("li", {}, p)))))
      : null,
    pack.client_only.length
      ? el("p", { class: "hint" }, t("pack.client_only", { names: pack.client_only.join(", ") }))
      : null,
    pack.skipped_overrides.length
      ? el("p", { class: "hint" }, t("pack.skipped_extras", { names: pack.skipped_overrides.join(", ") }))
      : null,
    el("details", { class: "advanced", open: pack.files.length <= 12 ? "open" : false },
      el("summary", {}, t("pack.all_files", { count: pack.files.length })),
      el("div", { class: "advanced-body" }, fileList(pack))));
}

/* The fields for a new server made from the pack. */
function newServerForm(result, onDone) {
  const pack = result.pack;
  const name = el("input", { id: "pack-name", maxlength: "60", value: pack.name.slice(0, 60), autocomplete: "off" });
  const folder = el("input", { id: "pack-folder", maxlength: "400", class: "mono",
    placeholder: "C:\\Minecraft\\Modpack", autocomplete: "off" });
  const eula = el("input", { id: "pack-eula", type: "checkbox" });
  const create = el("button", { class: "btn primary", type: "button",
    disabled: pack.can_import ? false : "disabled" }, t("pack.create"));
  create.addEventListener("click", () => {
    if (!name.value.trim() || !folder.value.trim()) { toast(t("add.need_name_and_folder"), "warn"); return; }
    if (!eula.checked) { toast(t("pack.need_eula"), "warn"); eula.focus(); return; }
    busy(create, t("pack.creating"), async () => {
      try {
        const made = await api(`/modpacks/${result.token}/new-server`, { method: "POST",
          body: { name: name.value.trim(), directory: folder.value.trim(), eula_accepted: true } });
        toast(t("pack.created", { name: made.name }), "success", 9000);
        await loadServers();
        onDone();
        await selectServer(made.server_id, "dashboard");
      } catch (err) { toast(err.message, "error", 14000); }
    });
  });
  return el("div", { class: "stack mt-12" },
    el("div", { class: "grid cols-2" },
      el("div", { class: "field" }, el("label", { for: "pack-name" }, t("add.name")), name),
      el("div", { class: "field" }, el("label", { for: "pack-folder" }, t("pack.folder")), folder,
        el("div", { class: "hint" }, t("pack.folder_hint")))),
    el("label", { class: "check-row" }, eula, el("span", {}, t("pack.eula"), " ",
      el("a", { href: "https://aka.ms/MinecraftEULA", target: "_blank", rel: "noopener noreferrer" },
        t("pack.eula_link")))),
    el("div", { class: "btn-row" }, create, el("span", { class: "hint" }, t("pack.create_hint"))));
}

/* Importing into the open server. */
function intoForm(result, onDone) {
  const plan = result.into;
  const go = el("button", { class: "btn primary", type: "button",
    disabled: result.pack.can_import ? false : "disabled" }, t("pack.import"));
  go.addEventListener("click", async () => {
    const ok = await confirmDialog({
      title: t("pack.import_title", { name: result.pack.name }),
      body: el("ul", { class: "plain-list" },
        el("li", {}, t("pack.step_stop")),
        el("li", {}, t("pack.step_backup")),
        plan.version_change
          ? el("li", {}, t("pack.step_version", { type: result.pack.type_name, version: result.pack.minecraft_version }))
          : null,
        el("li", {}, t("pack.step_aside")),
        el("li", {}, t("pack.step_files", { count: result.pack.download_count }))),
      confirmLabel: t("pack.import"),
    });
    if (!ok) return;
    await busy(go, t("pack.importing"), async () => {
      try {
        await api("/modpack", { method: "POST", body: { token: result.token, confirm: true } });
        toast(t("pack.imported", { name: result.pack.name }), "success", 9000);
        onDone(true);
      } catch (err) { toast(err.message, "error", 14000); }
    });
  });
  return el("div", { class: "stack mt-12" },
    plan.version_change
      ? el("div", { class: "banner warn" }, el("div", { class: "grow" },
          t("pack.version_change", { type: result.pack.type_name, version: result.pack.minecraft_version })))
      : null,
    el("p", { class: "hint mt-0" }, t("pack.into_hint")),
    el("div", { class: "btn-row" }, go));
}

/* The whole panel. mode is "new" or "into"; afterImport runs once the
   pack is in (to redraw the page). */
export function modpackPanel(mode, afterImport = null) {
  const input = el("input", { id: `pack-file-${mode}`, type: "file", accept: ".mrpack" });
  const body = el("div", { class: "mt-12" });
  let token = null;
  const reset = () => {
    if (token) api(`/modpacks/${token}`, { method: "DELETE" }).catch(() => {});
    token = null;
    body.replaceChildren();
    input.value = "";
  };
  const finished = (redraw) => {
    token = null;
    body.replaceChildren();
    input.value = "";
    if (redraw && afterImport) afterImport();
  };
  input.addEventListener("change", async () => {
    const file = input.files && input.files[0];
    if (!file) return;
    if (token) api(`/modpacks/${token}`, { method: "DELETE" }).catch(() => {});
    body.replaceChildren(el("div", { class: "empty", "aria-busy": "true" }, t("pack.reading")));
    const form = new FormData();
    form.append("file", file);
    try {
      const where = mode === "into" ? `?server_id=${encodeURIComponent(state.serverId)}` : "";
      const result = await api(`/modpacks/inspect${where}`, { method: "POST", body: form });
      token = result.token;
      body.replaceChildren(preview(result.pack),
        mode === "into" ? intoForm(result, finished) : newServerForm(result, finished),
        el("div", { class: "btn-row mt-8" },
          el("button", { class: "btn plain small", type: "button", onclick: reset }, t("pack.cancel"))));
    } catch (err) {
      body.replaceChildren(problem(err.message));
    }
  });
  return card(mode === "into" ? t("pack.into_title") : t("pack.new_title"),
    el("p", { class: "hint mt-0" }, mode === "into" ? t("pack.into_intro") : t("pack.new_intro")),
    el("div", { class: "field" }, el("label", { for: `pack-file-${mode}` }, t("pack.choose")), input),
    body);
}
