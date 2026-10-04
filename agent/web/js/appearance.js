import { renderRail } from "./nav.js";

export function currentTheme() {
  return document.documentElement.getAttribute("data-theme") || "system";
}

export function setTheme(mode) {
  if (mode === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", mode);
  try {
    if (mode === "system") localStorage.removeItem("mcsc_theme");
    else localStorage.setItem("mcsc_theme", mode);
  } catch (e) { /* appearance still applies for this visit */ }
  renderRail();
}
