/* A Bedrock server's add-ons: behavior and resource packs.

   Packs arrive as .mcpack, .mcaddon or .mctemplate files. The agent checks
   each one (its manifest.json, and that nothing in it would land outside
   its folder) before anything is written, installs it, and turns it on in
   this server's world. The server reads its packs when it starts, so a
   change made while it runs takes effect after a restart. Bedrock add-ons
   aren't on Modrinth, so there is no search here. */

import { api } from "../api.js";
import { render } from "../nav.js";
import { t, technical, tn } from "../strings.js";
import { busy, confirmDialog, el, emptyState, loadInto, section, table, toast } from "../ui.js";

function afterChange(result, doneKey, name) {
  toast(t(doneKey, { name }), "success");
  if (result.restart_needed) toast(t("addons.restart"), "warn", 9000);
  render();
}

function packRows(data) {
  return table(
    [t("addons.col_pack"), t("addons.col_kind"), t("addons.col_version"), t("addons.col_world"), ""],
    data.addons.map((pack) => [
      el("div", {}, el("strong", {}, pack.name),
        pack.description ? el("div", { class: "hint" }, pack.description) : null,
        technical() ? el("div", { class: "hint mono" }, `${pack.uuid} · ${pack.folder}`) : null),
      t(pack.kind === "resource" ? "addons.kind_resource" : "addons.kind_behavior"),
      el("span", { class: "mono" }, pack.version),
      el("span", { class: `tag ${pack.enabled ? "ok" : "off"}` },
        t(pack.enabled ? "addons.on" : "addons.off")),
      el("div", { class: "btn-row" },
        el("button", {
          class: "btn small", type: "button", disabled: data.world ? false : "disabled",
          onclick: (e) => busy(e.currentTarget, t("action.saving"), async () => {
            try {
              const result = await api(`/addons/${pack.uuid}`, { method: "PUT", body: { enabled: !pack.enabled } });
              afterChange(result, pack.enabled ? "addons.turned_off" : "addons.turned_on", pack.name);
            } catch (err) { toast(err.message, "error", 9000); }
          }),
        }, t(pack.enabled ? "addons.turn_off" : "addons.turn_on")),
        el("button", {
          class: "btn small danger", type: "button",
          onclick: async (e) => {
            const button = e.currentTarget;
            const ok = await confirmDialog({
              title: t("addons.remove_title", { name: pack.name }),
              body: el("p", {}, t("addons.remove_body")),
              confirmLabel: t("addons.remove"), danger: true,
            });
            if (!ok) return;
            await busy(button, t("action.saving"), async () => {
              try {
                const result = await api(`/addons/${pack.uuid}`, { method: "DELETE" });
                afterChange(result, "addons.removed", pack.name);
              } catch (err) { toast(err.message, "error", 9000); }
            });
          },
        }, t("addons.remove"))),
    ]));
}

function uploadCard() {
  const input = el("input", { type: "file", accept: ".mcpack,.mcaddon,.mctemplate", class: "sr-only", id: "addon-file" });
  const button = el("button", { class: "btn primary", type: "button", onclick: () => input.click() },
    t("addons.choose"));
  const upload = (file) => {
    if (!file) return;
    busy(button, t("addons.installing"), async () => {
      const form = new FormData();
      form.append("file", file);
      try {
        const result = await api("/addons/upload", { method: "POST", body: form });
        const names = result.installed.map((p) => p.name).join(", ");
        afterChange(result, "addons.installed_done", names);
      } catch (err) { toast(err.message, "error", 12000); }
    });
  };
  input.addEventListener("change", () => upload(input.files[0]));
  const drop = el("div", { class: "drop-zone" }, t("addons.drop"));
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => {
    e.preventDefault();
    drop.classList.remove("over");
    upload(e.dataTransfer.files[0]);
  });
  return section(t("addons.add_title"), null,
    el("p", { class: "hint mt-0" }, t("addons.add_lead")),
    drop, input, el("div", { class: "btn-row mt-10" }, button));
}

export const addonsPage = (page) => loadInto(page, async () => {
  const data = await api("/addons");
  return el("div", { class: "stack" },
    data.running ? el("div", { class: "banner" }, el("div", { class: "grow" }, t("addons.running"))) : null,
    data.world ? null : el("div", { class: "banner warn" }, el("div", { class: "grow" }, t("addons.no_world"))),
    section(tn("addons.installed", data.addons.length), null,
      data.addons.length ? packRows(data) : emptyState(t("addons.none"), t("addons.none_hint"))),
    uploadCard());
});
