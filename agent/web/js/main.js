/* Dashboard entry point, loaded by index.html as the only module script.
   Native ES modules, no build step: the browser loads each file directly.
   Each pages/*.js module registers its renderer when imported. */

import "./pages/add-server.js";
import "./pages/app-settings.js";
import "./pages/backups.js";
import "./pages/chat.js";
import "./pages/console.js";
import "./pages/crashes.js";
import "./pages/events.js";
import "./pages/game-settings.js";
import "./pages/getting-started.js";
import "./pages/helpers.js";
import "./pages/mods.js";
import "./pages/overview.js";
import "./pages/performance.js";
import "./pages/players.js";
import "./pages/schedules.js";
import "./pages/security.js";
import "./pages/settings.js";
import "./pages/world.js";
import "./servers.js";
import { api } from "./api.js";
import { signOut } from "./auth.js";
import { connectSocket, renderStatus } from "./live.js";
import { showOffline } from "./offline.js";
import { pageHash, parseHash, render, renderRail } from "./nav.js";
import { acceptQuickActions, inApp, tellApp } from "./phoneapp.js";
import { adopt } from "./prefs.js";
import { registerServiceWorker } from "./pwa.js";
import { loadServers } from "./servers.js";
import { pageEntry, state } from "./state.js";
import { t } from "./strings.js";
import { $, busy } from "./ui.js";

// The sign-in form's words, from the strings table like everything else.
$("#login-title").textContent = t("app.name");
$("#username-label").textContent = t("login.username");
$("#password-label").textContent = t("login.password");
$("#login-button").textContent = t("login.sign_in");
$("#remember-label").textContent = t("login.remember");
// The phone app always keeps the sign-in, in the phone's secure storage,
// behind its own fingerprint or face unlock.
if (inApp) $("#remember").closest("label").hidden = true;

/* What the Security page calls this device: "Chrome on Windows". Read
   from the browser's own description of itself. */
function deviceName() {
  const ua = navigator.userAgent;
  const system = [["iPhone", /iPhone/], ["iPad", /iPad/], ["Android", /Android/],
    ["Windows", /Windows/], ["Mac", /Macintosh/], ["Linux", /Linux/]].find(([, re]) => re.test(ua));
  const browser = [["Edge", /Edg\//], ["Firefox", /Firefox\//], ["Chrome", /Chrome\//],
    ["Safari", /Safari\//]].find(([, re]) => re.test(ua));
  if (!system && !browser) return ua.slice(0, 60);
  return t("login.device_name", {
    browser: browser ? browser[0] : t("login.browser"), system: system ? system[0] : "",
  }).trim();
}

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
          device: deviceName(),
          remember: inApp || $("#remember").checked,
        },
      });
      state.token = result.token;
      state.user = result.user;
      if (inApp) {
        // Kept by the app in the phone's secure storage, not here.
        tellApp("signed-in", { token: result.token, user: result.user });
      } else {
        // A kept sign-in survives closing the browser (or the phone's home
        // screen app); otherwise it ends with this tab.
        try {
          if (result.remember) localStorage.setItem("mcsc_token", state.token);
          else localStorage.removeItem("mcsc_token");
        } catch (e) { /* kept for this tab only */ }
        sessionStorage.setItem("mcsc_token", state.token);
      }
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
  if (me) {
    adopt(me.preferences);
    state.me = me;
    state.user = me.user || state.user;
  }
  $("#login").hidden = true;
  $("#app").classList.add("visible");
  const wanted = parseHash();
  if (pageEntry(wanted.page)) state.page = wanted.page;
  try {
    // A link that names a server (#survival/console) opens that server.
    if (wanted.server) state.serverId = wanted.server;
    await loadServers();
    state.status = await api("/status");
  } catch (e) { return; }
  try {
    const running = await api("/jobs?running=true");
    for (const job of running.jobs || []) state.jobs[job.id] = job;
  } catch (e) { /* the jobs indicator stays empty; nothing is assumed */ }
  // A new version shows as a dot on the gear, so it is seen without
  // opening App settings. Checked by the agent once a day.
  api("/updates").then((u) => {
    state.newVersion = u.available && u.latest ? u.latest.version : "";
    renderRail();
  }).catch(() => { /* no dot; App settings says why */ });
  history.replaceState(null, "", pageHash());
  renderRail();
  renderStatus();
  render();
  connectSocket();
  if (inApp) {
    // The app is already installed and gets its alerts from the agent.
    acceptQuickActions();
    return;
  }
  // Lets the dashboard be added to a phone's home screen, and is what
  // phone alerts are delivered through.
  registerServiceWorker();
}

if (state.token) {
  // Unreachable is not signed out: the offline screen waits for the PC and
  // then loads the page again, still signed in.
  api("/auth/me").then(startApp).catch((err) => (err.offline ? showOffline({ reload: true }) : signOut(true)));
}
