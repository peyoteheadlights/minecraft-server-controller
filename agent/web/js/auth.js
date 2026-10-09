import { api } from "./api.js";
import { tellApp } from "./phoneapp.js";
import { clearTimers } from "./nav.js";
import { applyServerColor } from "./colors.js";
import { state } from "./state.js";
import { t } from "./strings.js";
import { $ } from "./ui.js";

export function signOut(expired) {
  if (state.socket) {
    state.socket.onclose = null;
    try { state.socket.close(); } catch (e) { /* already closed */ }
  }
  if (!expired && state.token) api("/auth/logout", { method: "POST" }).catch(() => {});
  state.token = "";
  // The app forgets its copy too, so the widget and the next launch are
  // signed out as well (a 401 means the PC signed this device out).
  tellApp("signed-out", { expired: Boolean(expired) });
  sessionStorage.removeItem("mcsc_token");
  try { localStorage.removeItem("mcsc_token"); } catch (e) { /* nothing kept */ }
  clearTimers();
  applyServerColor(null);
  $("#app").classList.remove("visible");
  $("#login").hidden = false;
  if (expired) {
    $("#login-error").textContent = t("error.session_ended");
    $("#login-error").hidden = false;
  }
}
