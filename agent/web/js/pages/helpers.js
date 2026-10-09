/* Helpers: friends' own logins, made by the owner. A helper can start,
   stop and restart, manage players, chat, back up and look at everything,
   and nothing else. A helper can be kept to some servers. The agent checks
   every action itself; this page only manages the accounts. */

import { api } from "../api.js";
import { render } from "../nav.js";
import { renderers } from "../state.js";
import { t } from "../strings.js";
import { busy, card, confirmDialog, el, emptyState, fmt, loadInto, table, toast } from "../ui.js";

const CAN = ["helpers.can_start", "helpers.can_players", "helpers.can_chat", "helpers.can_backup",
  "helpers.can_view"];
const CANNOT = ["helpers.cannot_settings", "helpers.cannot_backups", "helpers.cannot_mods",
  "helpers.cannot_console", "helpers.cannot_users"];

/* "Every server" or a box per server. Returns the node and a reader that
   gives null (every server) or the chosen ids. */
function serverPicker(servers, chosen, idPrefix) {
  const every = el("input", { type: "checkbox", id: `${idPrefix}-all`, checked: chosen === null ? "checked" : false });
  const boxes = servers.map((s) => el("input", {
    type: "checkbox", value: s.id, checked: chosen && chosen.includes(s.id) ? "checked" : false,
    disabled: chosen === null ? "disabled" : false,
  }));
  const list = el("div", { class: "grid cols-3" }, servers.map((s, i) =>
    el("label", { class: "check-row" }, boxes[i], s.name)));
  list.hidden = chosen === null;
  every.addEventListener("change", () => {
    list.hidden = every.checked;
    for (const box of boxes) box.disabled = every.checked;
  });
  return {
    node: el("div", { class: "field" },
      el("label", { class: "check-row" }, every, t("helpers.every_server")), list),
    read: () => (every.checked ? null : boxes.filter((b) => b.checked).map((b) => b.value)),
  };
}

function addCard(data) {
  const name = el("input", { id: "helper-name", maxlength: "32", autocomplete: "off" });
  const password = el("input", { id: "helper-password", type: "password", autocomplete: "new-password" });
  const picker = serverPicker(data.servers, null, "new-helper");
  return card(t("helpers.add"),
    el("div", { class: "grid cols-2" },
      el("div", { class: "field" }, el("label", { for: "helper-name" }, t("helpers.username")), name,
        el("div", { class: "hint" }, t("helpers.username_hint"))),
      el("div", { class: "field" }, el("label", { for: "helper-password" }, t("helpers.password")), password,
        el("div", { class: "hint" }, t("helpers.password_hint")))),
    data.servers.length > 1 ? picker.node : null,
    el("div", { class: "btn-row mt-12" }, el("button", {
      class: "btn primary", type: "button",
      onclick: (e) => busy(e.currentTarget, t("helpers.adding"), async () => {
        const servers = picker.read();
        if (servers && !servers.length) { toast(t("helpers.pick_a_server"), "error"); return; }
        try {
          await api("/accounts", { method: "POST",
            body: { username: name.value.trim(), password: password.value, servers } });
          password.value = "";
          toast(t("helpers.added", { name: name.value.trim() }), "success", 8000);
          render();
        } catch (err) { toast(err.message, "error", 9000); }
      }),
    }, t("helpers.add_button"))));
}

async function changeServers(helper, data) {
  const picker = serverPicker(data.servers, helper.servers, `edit-${helper.username}`);
  const ok = await confirmDialog({
    title: t("helpers.servers_title", { name: helper.username }), body: picker.node,
    confirmLabel: t("action.save"),
  });
  if (!ok) return;
  const servers = picker.read();
  if (servers && !servers.length) { toast(t("helpers.pick_a_server"), "error"); return; }
  try {
    await api(`/accounts/${encodeURIComponent(helper.username)}`, { method: "PUT",
      body: servers === null ? { all_servers: true } : { servers } });
    toast(t("settings.saved"), "success");
    render();
  } catch (err) { toast(err.message, "error"); }
}

async function newPassword(helper) {
  const input = el("input", { type: "password", id: "reset-helper-password", autocomplete: "new-password" });
  const ok = await confirmDialog({
    title: t("helpers.password_title", { name: helper.username }),
    body: el("div", {}, el("p", {}, t("helpers.password_body")),
      el("div", { class: "field" }, el("label", { for: "reset-helper-password" }, t("helpers.password")), input)),
    confirmLabel: t("helpers.set_password"),
  });
  if (!ok) return;
  try {
    await api(`/accounts/${encodeURIComponent(helper.username)}`, { method: "PUT", body: { password: input.value } });
    toast(t("helpers.password_set", { name: helper.username }), "success");
    render();
  } catch (err) { toast(err.message, "error", 9000); }
}

async function remove(helper) {
  const ok = await confirmDialog({
    title: t("helpers.remove_title", { name: helper.username }), body: t("helpers.remove_body"),
    confirmLabel: t("helpers.remove"), danger: true,
  });
  if (!ok) return;
  try {
    await api(`/accounts/${encodeURIComponent(helper.username)}`, { method: "DELETE" });
    toast(t("helpers.removed", { name: helper.username }));
    render();
  } catch (err) { toast(err.message, "error"); }
}

function listCard(data) {
  const names = Object.fromEntries(data.servers.map((s) => [s.id, s.name]));
  const rows = data.helpers.map((h) => [
    el("strong", {}, h.username),
    h.servers === null ? t("helpers.every_server") : h.servers.map((id) => names[id] || id).join(", "),
    h.last_sign_in ? fmt.ago(h.last_sign_in) : t("time.never"),
    el("div", { class: "btn-row" },
      data.servers.length > 1
        ? el("button", { class: "btn small", type: "button", onclick: () => changeServers(h, data) },
            t("helpers.change_servers"))
        : null,
      el("button", { class: "btn small", type: "button", onclick: () => newPassword(h) }, t("helpers.new_password")),
      el("button", { class: "btn small danger", type: "button", onclick: () => remove(h) }, t("helpers.remove"))),
  ]);
  return card(t("helpers.list"),
    data.helpers.length
      ? table([t("helpers.col_name"), t("helpers.col_servers"), t("helpers.col_last"), ""], rows)
      : emptyState(t("helpers.none"), t("helpers.none_hint")),
    el("p", { class: "hint mt-10" }, t("helpers.owner_note", { owner: data.owner })));
}

function rulesCard() {
  return card(t("helpers.what"),
    el("div", { class: "grid cols-2" },
      el("div", {}, el("h3", { class: "subheading" }, t("helpers.can")),
        el("ul", {}, CAN.map((key) => el("li", {}, t(key))))),
      el("div", {}, el("h3", { class: "subheading" }, t("helpers.cannot")),
        el("ul", {}, CANNOT.map((key) => el("li", {}, t(key)))))));
}

renderers.helpers = (page) => loadInto(page, async () => {
  const data = await api("/accounts");
  return el("div", { class: "stack" },
    el("p", { class: "lead mt-0" }, t("helpers.lead")),
    listCard(data),
    addCard(data),
    rulesCard());
});
