import { currentTheme, setTheme } from "./appearance.js";
import { signOut } from "./auth.js";
import { setLink, updateStatusViews } from "./live.js";
import { overview } from "./pages/overview.js";
import { hooks, jobsLine, switcher } from "./servers.js";
import { PAGES, renderers, state } from "./state.js";
import { $, el, icon } from "./ui.js";

export function renderRail() {
  const rail = $("#sidebar");
  rail.replaceChildren();
  rail.append(el("div", { class: "sidebar-head" },
    switcher(),
    el("div", { class: "server-state", id: "sidebar-state" }),
    el("div", { id: "jobs" }, jobsLine())));

  let group = null, list = null;
  for (const [key, label, groupName, iconName] of PAGES) {
    if (groupName !== group) {
      group = groupName;
      list = el("div", { class: "nav-group", role: "group", "aria-label": groupName },
        el("div", { class: "nav-group-label", "aria-hidden": "true" }, groupName));
      rail.append(list);
    }
    list.append(el("a", {
      class: "nav-item",
      href: `#${key}`,
      title: label,
      "aria-current": state.page === key ? "page" : null,
      onclick: (event) => { event.preventDefault(); navigate(key); },
    }, icon(iconName), el("span", { class: "label" }, label)));
  }

  const theme = currentTheme();
  const themeButton = (mode, iconName, label) => el("button", {
    type: "button", title: label, "aria-label": label,
    "aria-pressed": theme === mode ? "true" : "false",
    onclick: () => setTheme(mode),
  }, icon(iconName));
  rail.append(el("div", { class: "sidebar-foot" },
    el("div", { class: "connection", id: "connection", role: "status" }),
    el("div", { class: "segmented", role: "group", "aria-label": "Appearance" },
      themeButton("system", "system", "Match system appearance"),
      themeButton("light", "sun", "Light appearance"),
      themeButton("dark", "moon", "Dark appearance")),
    el("button", { class: "signout", type: "button", title: "Sign out", onclick: () => signOut(false) },
      icon("signout"), el("span", { class: "label" }, "Sign out"))));
  setLink(state.connected);
  updateStatusViews();
}

export function setNavOpen(open) {
  $("#app").classList.toggle("nav-open", open);
  $("#menu-button").setAttribute("aria-expanded", open ? "true" : "false");
}

export function navigate(page) {
  state.page = page;
  if (location.hash !== `#${page}`) history.replaceState(null, "", `#${page}`);
  setNavOpen(false);
  renderRail();
  render();
  $("#main").focus({ preventScroll: true });
  window.scrollTo(0, 0);
}

hooks.navigate = navigate;
hooks.afterSwitch = () => { renderRail(); render(); };

window.addEventListener("hashchange", () => {
  const page = location.hash.replace("#", "");
  if (PAGES.some(([key]) => key === page) && page !== state.page) navigate(page);
});

$("#menu-button").append(icon("menu"));

$("#menu-button").addEventListener("click", () =>
  setNavOpen(!$("#app").classList.contains("nav-open")));

$("#app").addEventListener("click", (event) => {
  if ($("#app").classList.contains("nav-open") && !event.target.closest(".sidebar, #menu-button")) {
    setNavOpen(false);
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && $("#app").classList.contains("nav-open")) setNavOpen(false);
});

export function clearTimers() {
  if (state.pageTimer) { clearInterval(state.pageTimer); state.pageTimer = null; }
  if (state.clock) { clearInterval(state.clock); state.clock = null; }
}

export function render() {
  const page = $("#page");
  const entry = PAGES.find(([key]) => key === state.page) || PAGES[0];
  $("#page-title").textContent = entry[1];
  document.title = `${entry[1]} - Minecraft Server Control`;
  clearTimers();
  overview.nodes = null;
  $("#toolbar-actions").replaceChildren();
  page.replaceChildren();
  page.className = `page ${state.page}-page`;
  // restart the entrance transition
  void page.offsetWidth;
  const renderer = renderers[state.page];
  if (renderer) renderer(page, $("#toolbar-actions"));
}
