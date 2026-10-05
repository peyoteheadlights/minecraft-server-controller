/* The page shell: server tabs across the top, the selected server's
   "sheet" tinted with its color, with the server's own pages in a list down
   its left side (a row on a phone), and the gear for app-wide settings. Pages about the agent itself (the gear,
   All servers, adding a server) get a neutral sheet. */

import { signOut } from "./auth.js";
import { applyServerColor } from "./colors.js";
import { setLink, updateStatusViews, updateTitle } from "./live.js";
import { overview } from "./pages/overview.js";
import { hooks as prefHooks } from "./prefs.js";
import { hooks, renderTabs, serverBadge, serverRow, jobsIndicator } from "./servers.js";
import { PAGES, pageEntry, renderers, stateInfo, state } from "./state.js";
import { t } from "./strings.js";
import { $, el, icon } from "./ui.js";

function renderTools() {
  $("#desk-tools").replaceChildren(
    el("div", { id: "jobs" }, jobsIndicator()),
    el("div", { class: "connection", id: "connection", role: "status" }),
    el("button", {
      class: `tool-button${state.scope === "app" ? " active" : ""}`, type: "button", id: "gear",
      title: t("page.app_settings"), "aria-label": t("page.app_settings"),
      "aria-current": state.scope === "app" ? "page" : null,
      onclick: () => navigate("app-settings"),
    }, icon("gear")),
    el("button", {
      class: "tool-button signout", type: "button", title: t("action.sign_out"),
      "aria-label": t("action.sign_out"), onclick: () => signOut(false),
    }, icon("signout")));
  setLink(state.connected);
}

/* The sheet's heading band: the server's name and state, or the name of
   the app-wide page. */
function renderHead() {
  const head = $("#sheet-head");
  if (state.scope !== "server") {
    head.replaceChildren(el("div", { class: "sheet-id" },
      el("span", { class: "sheet-name" }, state.scope === "app" ? t("head.app") : t(pageEntry(state.page)[1]))));
    return;
  }
  const row = serverRow();
  head.replaceChildren(el("div", { class: "sheet-id" },
    row ? serverBadge(row, { size: "lg" }) : null,
    el("div", { class: "sheet-titles" },
      el("span", { class: "sheet-name", id: "sheet-name" }, row ? row.name : ""),
      el("span", { class: "sheet-state", id: "sheet-state" }))));
}

/* The server's pages in three small groups, so the list reads at a glance:
   what is happening now, looking after the server, and what happened. */
const NAV_GROUPS = [
  ["nav.group_live", ["dashboard", "players", "console", "performance"]],
  ["nav.group_manage", ["backups", "mods", "schedules", "settings"]],
  ["nav.group_history", ["events", "crashes"]],
];

function navLink([key, label, , iconName]) {
  return el("a", {
    class: "nav-item", href: `#${key}`,
    "aria-current": state.page === key ? "page" : null,
    onclick: (event) => { event.preventDefault(); navigate(key); },
  }, icon(iconName), el("span", { class: "nav-label" }, t(label)));
}

function renderSubnav() {
  const nav = $("#subnav");
  const items = PAGES.filter(([, , scope]) => scope === state.scope && scope !== "all" && scope !== "add");
  nav.hidden = !items.length;
  nav.setAttribute("aria-label", state.scope === "server" ? t("nav.server_pages") : t("nav.app_pages"));
  if (state.scope !== "server") {
    nav.replaceChildren(...items.map(navLink));
  } else {
    const grouped = new Set(NAV_GROUPS.flatMap(([, keys]) => keys));
    const loose = items.filter(([key]) => !grouped.has(key));
    nav.replaceChildren(...NAV_GROUPS.map(([labelKey, keys]) => {
      const id = `nav-${labelKey.split("_").pop()}`;
      const links = keys.map(pageEntry).filter(Boolean).map(navLink);
      return el("div", { class: "nav-group", role: "group", "aria-labelledby": id },
        el("span", { class: "nav-group-label", id }, t(labelKey)), ...links);
    }), ...loose.map(navLink));
  }
  const current = nav.querySelector('[aria-current="page"]');
  if (current) current.scrollIntoView({ block: "nearest", inline: "nearest" });
}

/* The whole frame around the page: tabs, colors, heading, page row. */
export function renderRail() {
  const entry = pageEntry(state.page) || pageEntry("dashboard");
  state.scope = entry[2];
  if (state.scope === "server" && !serverRow()) state.scope = "all";
  applyServerColor(state.scope === "server" ? (serverRow() || {}).color : null);
  document.documentElement.dataset.scope = state.scope;
  renderTabs();
  renderTools();
  renderHead();
  renderSubnav();
  updateStatusViews();
}

export function navigate(page) {
  state.page = pageEntry(page) ? page : "dashboard";
  if (location.hash !== `#${state.page}`) history.replaceState(null, "", `#${state.page}`);
  renderRail();
  render();
  $("#main").focus({ preventScroll: true });
  window.scrollTo(0, 0);
}

hooks.navigate = navigate;
hooks.afterSwitch = () => { renderRail(); render(); };
// After the theme or Simple/Technical changes: the same page, redrawn.
prefHooks.changed = () => { renderRail(); render(); };

window.addEventListener("hashchange", () => {
  const page = location.hash.replace("#", "");
  if (pageEntry(page) && page !== state.page) navigate(page);
});

export function clearTimers() {
  if (state.pageTimer) { clearInterval(state.pageTimer); state.pageTimer = null; }
  if (state.clock) { clearInterval(state.clock); state.clock = null; }
}

export function render() {
  const page = $("#page");
  const entry = pageEntry(state.page) || pageEntry("dashboard");
  const title = t(entry[1]);
  $("#page-title").textContent = title;
  // the sheet's heading band names the page; the h1 is for screen readers
  $("#page-title").classList.add("sr-only");
  state.pageTitle = title;
  updateTitle();
  clearTimers();
  overview.nodes = null;
  $("#toolbar-actions").replaceChildren();
  page.replaceChildren();
  page.className = `page ${state.page}-page`;
  // Switching servers flips to the next sheet, like a portfolio's pages.
  const sheet = $("#main");
  sheet.classList.remove("flip-forward", "flip-back");
  if (state.flip) {
    void sheet.offsetWidth;
    sheet.classList.add(`flip-${state.flip}`);
    state.flip = null;
  }
  const renderer = renderers[state.page];
  if (renderer) renderer(page, $("#toolbar-actions"));
}

export function statusLine(status) {
  const info = stateInfo(status.state);
  return [el("span", { class: `status-dot tone-${info.tone}${info.busy ? " pulse" : ""}` }), t(info.label)];
}
