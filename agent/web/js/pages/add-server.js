/* The "+" tab, with two ways in:

   New server    - downloaded and set up from scratch (panels/newserver.js)
   Already have  - a Minecraft server that is already in a folder on this PC

   The second one changes nothing in the folder and does not start the
   server; it only puts it on the list. */

import { api } from "../api.js";
import { newServerPanel } from "../panels/newserver.js";
import { loadServers, selectServer } from "../servers.js";
import { renderers, state } from "../state.js";
import { t } from "../strings.js";
import { advanced, busy, card, el, toast } from "../ui.js";

function existingServerForm() {
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
  return { form, focus: () => name.focus({ preventScroll: true }) };
}

renderers["add-server"] = (page) => {
  const body = el("div", {});
  let which = "new";

  const tabs = el("div", { class: "segmented add-ways", role: "group", "aria-label": t("add.ways") });
  const show = (choice) => {
    which = choice;
    for (const button of tabs.children) {
      button.setAttribute("aria-pressed", button.dataset.way === which ? "true" : "false");
    }
    if (which === "new") {
      body.replaceChildren(newServerPanel());
    } else {
      const existing = existingServerForm();
      body.replaceChildren(existing.form);
      existing.focus();
    }
  };
  tabs.append(
    el("button", { type: "button", "data-way": "new", onclick: () => show("new") }, t("add.way_new")),
    el("button", { type: "button", "data-way": "have", onclick: () => show("have") }, t("add.way_have")));

  page.append(el("div", { class: "stack" }, tabs, body));
  show(which);
};
