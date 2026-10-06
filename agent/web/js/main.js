/* Dashboard entry point, loaded by index.html as the only module script.
   Native ES modules, no build step: the browser loads each file directly.
   Each pages/*.js module registers its renderer when imported. */

import "./pages/add-server.js";
import "./pages/app-settings.js";
import "./pages/backups.js";
import "./pages/console.js";
import "./pages/crashes.js";
import "./pages/events.js";
import "./pages/game-settings.js";
import "./pages/mods.js";
import "./pages/overview.js";
import "./pages/performance.js";
import "./pages/players.js";
import "./pages/schedules.js";
import "./pages/security.js";
import "./pages/settings.js";
import "./servers.js";
import { api } from "./api.js";
import { signOut } from "./auth.js";
import { connectSocket, renderStatus } from "./live.js";
import { render, renderRail } from "./nav.js";
import { adopt } from "./prefs.js";
import { loadServers } from "./servers.js";
import { pageEntry, state } from "./state.js";
import { t } from "./strings.js";
import { $, busy } from "./ui.js";

// The sign-in form's words, from the strings table like everything else.
$("#login-title").textContent = t("app.name");
$("#username-label").textContent = t("login.username");
$("#password-label").textContent = t("login.password");
$("#login-button").textContent = t("login.sign_in");

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const error = $("#login-error");
  const button = event.target.querySelector("button[type=submit]");
  error.hidden = true;
  await busy(button, t("login.signing_in"), async () => {
    try {
      const result = await api("/auth/login", {
        method: "POST",
        body: {
          username: $("#username").value,
          password: $("#password").value,
          label: navigator.userAgent.slice(0, 60),
        },
      });
      state.token = result.token;
      state.user = result.user;
      sessionStorage.setItem("mcsc_token", state.token);
      $("#password").value = "";
      const me = await api("/auth/me").catch(() => null);
      startApp(me);
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
    }
  });
});

async function startApp(me) {
  if (me) adopt(me.preferences);
  $("#login").hidden = true;
  $("#app").classList.add("visible");
  const hash = location.hash.replace("#", "");
  if (pageEntry(hash)) state.page = hash;
  try {
    await loadServers();
    state.status = await api("/status");
  } catch (e) { return; }
  try {
    const running = await api("/jobs?running=true");
    for (const job of running.jobs || []) state.jobs[job.id] = job;
  } catch (e) { /* the jobs indicator stays empty; nothing is assumed */ }
  renderRail();
  renderStatus();
  render();
  connectSocket();
}

if (state.token) {
  api("/auth/me").then(startApp).catch(() => signOut(true));
}
