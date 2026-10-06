/* "Can't reach your PC": the full-page screen shown when the agent doesn't
   answer at all (the PC is asleep or off, the app isn't running, or this
   phone isn't on Tailscale). It tries again by itself, sooner at first and
   then less often, and the moment the agent answers it goes away and the
   page carries on, still signed in.

   The screen itself loads from the service worker's copy of the app's
   static files, so it shows even when the PC is off; no data is cached. */

import { state } from "./state.js";
import { t } from "./strings.js";
import { $, el, icon } from "./ui.js";

const FIRST_WAIT = 3;
const LONGEST_WAIT = 30;

const screen = { shown: false, wait: FIRST_WAIT, timer: null, tick: null, due: 0, reload: false };

async function reachable() {
  try {
    const response = await fetch("/api/health", { cache: "no-store" });
    return response.ok;
  } catch (err) {
    return false;
  }
}

function countdown() {
  const left = Math.max(0, Math.ceil((screen.due - Date.now()) / 1000));
  const node = $("#offline-next");
  if (node) node.textContent = left ? t("offline.next_try", { seconds: left }) : t("offline.trying");
}

function schedule() {
  clearTimeout(screen.timer);
  screen.due = Date.now() + screen.wait * 1000;
  countdown();
  screen.timer = setTimeout(tryNow, screen.wait * 1000);
}

export async function tryNow() {
  clearTimeout(screen.timer);
  const node = $("#offline-next");
  if (node) node.textContent = t("offline.trying");
  if (await reachable()) {
    hideOffline();
    return;
  }
  screen.wait = Math.min(LONGEST_WAIT, Math.round(screen.wait * 1.6));
  schedule();
}

function draw() {
  $("#offline").replaceChildren(el("div", { class: "offline-panel" },
    el("div", { class: "app-mark", "aria-hidden": "true" }, icon("servers")),
    el("h1", {}, t("offline.title")),
    el("p", { class: "lead" }, t("offline.lead")),
    el("ul", { class: "offline-reasons" },
      el("li", {}, t("offline.reason_asleep")),
      el("li", {}, t("offline.reason_app")),
      el("li", {}, t("offline.reason_network"))),
    el("p", { class: "hint", id: "offline-next", role: "status" }),
    el("button", { class: "btn primary", type: "button", onclick: () => tryNow() }, t("offline.try_now"))));
}

/* Show the screen and start trying again. With reload, the whole page is
   loaded again once the agent answers (it never got as far as starting). */
export function showOffline(options = {}) {
  if (options.reload) screen.reload = true;
  if (screen.shown) return;
  screen.shown = true;
  screen.wait = FIRST_WAIT;
  draw();
  $("#offline").hidden = false;
  document.documentElement.classList.add("is-offline");
  clearInterval(screen.tick);
  screen.tick = setInterval(countdown, 1000);
  schedule();
}

export function hideOffline() {
  clearTimeout(screen.timer);
  clearInterval(screen.tick);
  if (!screen.shown) return;
  screen.shown = false;
  $("#offline").hidden = true;
  document.documentElement.classList.remove("is-offline");
  if (screen.reload || !state.token) {
    location.reload();
    return;
  }
  // Signed in and the page was already running: the live connection
  // reconnects by itself; the page is drawn again with fresh data.
  import("./live.js").then((live) => live.refreshStatus && live.refreshStatus()).catch(() => {});
}

export function offlineShown() {
  return screen.shown;
}
