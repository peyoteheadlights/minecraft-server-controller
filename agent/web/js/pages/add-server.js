/* The "+" tab: add a Minecraft server that already exists in a folder on
   the PC. Nothing in the folder is changed and the server is not started.
   (Creating a brand-new server comes with the New server panel later.) */

import { api } from "../api.js";
import { loadServers, selectServer } from "../servers.js";
import { renderers, state } from "../state.js";
import { t } from "../strings.js";
import { advanced, busy, card, el, toast } from "../ui.js";

renderers["add-server"] = (page) => {
  const name = el("input", { id: "add-server-name", maxlength: "60", required: true, autocomplete: "off" });
  const folder = el("input", { id: "add-server-folder", maxlength: "400", required: true,
    class: "mono", placeholder: "C:\\Minecraft\\Creative", autocomplete: "off" });
  const jar = el("input", { id: "add-server-jar", maxlength: "180", autocomplete: "off",
    placeholder: "fabric-server-launch.jar" });
  let chosen = state.nextColor;
  const used = new Set(state.servers.map((s) => s.color));
  const swatches = el("div", { class: "swatches", role: "radiogroup", "aria-label": t("serverset.color") },
    state.palette.map((p) => {
      const label = el("label", { class: "swatch-choice", title: t(`color.${p.id}`) },
        el("input", {
          type: "radio", name: "new-color", value: p.hex,
          checked: p.hex === chosen ? "checked" : false,
          "aria-label": used.has(p.hex) ? t("add.color_used", { color: t(`color.${p.id}`) }) : t(`color.${p.id}`),
          onchange: () => { chosen = p.hex; },
        }),
        el("span", { class: `swatch${used.has(p.hex) ? " used" : ""}`, "aria-hidden": "true" }));
      label.style.setProperty("--swatch", p.hex);
      return label;
    }));

  const form = el("form", { class: "stack", novalidate: true });
  form.append(card(t("add.existing"),
    el("p", { class: "hint mt-0" }, t("add.existing_hint")),
    el("div", { class: "grid cols-2" },
      el("div", { class: "field" }, el("label", { for: "add-server-name" }, t("add.name")), name),
      el("div", { class: "field" }, el("label", { for: "add-server-folder" }, t("add.folder")), folder)),
    el("div", { class: "field" }, el("span", { class: "field-label" }, t("serverset.color")), swatches),
    advanced(t("add.more_options"),
      el("div", { class: "field" }, el("label", { for: "add-server-jar" }, t("add.jar")), jar,
        el("div", { class: "hint" }, t("add.jar_hint")))),
    el("div", { class: "btn-row mt-12" },
      el("button", { class: "btn primary", type: "submit", id: "add-server-submit" }, t("add.submit")))));

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!name.value.trim() || !folder.value.trim()) {
      toast(t("add.need_name_and_folder"), "warn");
      (name.value.trim() ? folder : name).focus();
      return;
    }
    busy(form.querySelector("#add-server-submit"), t("add.adding"), async () => {
      try {
        const result = await api("/servers", {
          method: "POST",
          body: { name: name.value.trim(), directory: folder.value.trim(), jar: jar.value.trim(), color: chosen },
        });
        toast(t("add.added", { name: result.server.name }), "success");
        for (const warning of result.warnings || []) toast(warning, "warn", 12000);
        await loadServers();
        await selectServer(result.server.id, "dashboard");
      } catch (err) { toast(err.message, "error", 9000); }
    });
  });
  page.append(form);
  name.focus({ preventScroll: true });
};
