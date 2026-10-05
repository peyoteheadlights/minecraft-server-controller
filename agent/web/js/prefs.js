/* The two display choices each account makes: the theme and Simple or
   Technical. Both apply at once, with no reload, are remembered in this
   browser (so theme.js can apply them before the first paint) and saved
   on the agent for the account, so they follow the person to every device. */

import { api } from "./api.js";
import { display } from "./strings.js";

export const THEMES = ["system", "light", "dark", "graphite", "contrast"];
export const MODES = ["simple", "technical"];

// Set by nav.js: redraws the page after a choice changes.
export const hooks = { changed: null };

export function currentTheme() {
  return document.documentElement.getAttribute("data-theme") || "system";
}

function remember(key, value, fallback) {
  try {
    if (value === fallback) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch (e) { /* still applies for this visit */ }
}

function applyTheme(theme) {
  if (theme === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", theme);
  remember("mcsc_theme", theme, "system");
}

function applyMode(mode) {
  display.mode = mode;
  document.documentElement.setAttribute("data-mode", mode);
  remember("mcsc_mode", mode, "simple");
}

/* Change one choice now, then save it for the account. */
export async function choose(key, value) {
  if (key === "theme") applyTheme(value);
  else applyMode(value);
  if (hooks.changed) hooks.changed(key);
  try {
    await api("/account/preferences", { method: "PUT", body: { [key]: value } });
  } catch (e) { /* kept in this browser; the account copy updates next time */ }
}

/* The account's saved choices, from sign-in: they win over this browser's. */
export function adopt(prefs) {
  if (!prefs) return false;
  let changed = false;
  if (THEMES.includes(prefs.theme) && prefs.theme !== currentTheme()) {
    applyTheme(prefs.theme);
    changed = true;
  }
  if (MODES.includes(prefs.mode) && prefs.mode !== display.mode) {
    applyMode(prefs.mode);
    changed = true;
  }
  return changed;
}

// "Match system" follows the operating system as it changes.
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (currentTheme() === "system" && hooks.changed) hooks.changed("theme");
});
