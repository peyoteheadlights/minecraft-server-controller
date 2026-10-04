import { api } from "./api.js";
import { clearTimers } from "./nav.js";
import { state } from "./state.js";
import { $ } from "./ui.js";

export function signOut(expired) {
  if (state.socket) {
    state.socket.onclose = null;
    try { state.socket.close(); } catch (e) { /* already closed */ }
  }
  if (!expired && state.token) api("/auth/logout", { method: "POST" }).catch(() => {});
  state.token = "";
  sessionStorage.removeItem("mcsc_token");
  clearTimers();
  $("#app").classList.remove("visible");
  $("#login").style.display = "grid";
  if (expired) {
    $("#login-error").textContent = "Your session ended. Sign in again.";
    $("#login-error").hidden = false;
  }
}
