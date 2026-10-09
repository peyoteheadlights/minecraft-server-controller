/* Inside the phone app (mobile/), the dashboard is these same pages in the
   app's web view. The app says so by defining window.mcscApp before the
   page loads, only for the PC it paired with:

     { platform: "android" | "ios", version: "1.0.0",
       token: "<sign-in token from the phone's secure storage, or empty>",
       pending: { server, action } | null,   // a quick action to confirm
       post(message) }                       // tells the app something

   In the app the sign-in token lives only in memory here and in the
   phone's secure storage (Keystore or Keychain), never in the web view's
   own storage. Everything else works exactly as in a browser: every
   action is still checked by the agent. */

const bridge = (typeof window !== "undefined" && window.mcscApp
  && typeof window.mcscApp.post === "function") ? window.mcscApp : null;

export const inApp = Boolean(bridge);

/* The token the app kept from the last sign-in, or "". */
export function appToken() {
  return bridge && typeof bridge.token === "string" ? bridge.token : "";
}

/* Tells the app something. Never throws: a page outside the app, or an app
   that has gone away, simply hears nothing. */
export function tellApp(type, details = {}) {
  if (!bridge) return;
  try { bridge.post(Object.assign({ type }, details)); } catch (e) { /* not heard */ }
}

/* The quick actions the app offers (app icon shortcuts and the widget). */
export const QUICK_ACTIONS = ["start", "stop", "restart"];

/* Runs a quick action the app handed over: opens that server's Overview
   and asks first, like the buttons there do (start asks too, since it was
   tapped outside the dashboard). Returns false for anything it won't do. */
export async function runQuickAction(request) {
  if (!request || !QUICK_ACTIONS.includes(request.action)) return false;
  const { state } = await import("./state.js");
  if (!state.servers.some((s) => s.id === request.server)) return false;
  const { selectServer } = await import("./servers.js");
  const { serverAction } = await import("./pages/overview.js");
  await selectServer(request.server, "dashboard");
  await serverAction(request.action, null, { askFirst: true });
  return true;
}

/* Called once the dashboard is signed in and showing: runs the quick action
   the app was opened with, and takes any later ones. */
export function acceptQuickActions() {
  if (!bridge) return;
  bridge.run = (request) => runQuickAction(request);
  const waiting = bridge.pending;
  bridge.pending = null;
  if (waiting) runQuickAction(waiting);
}
