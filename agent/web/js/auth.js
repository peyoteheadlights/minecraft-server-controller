import { api } from "./api.js";
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
