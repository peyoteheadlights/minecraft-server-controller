/* Installing the dashboard on a phone, and turning phone alerts on there.

   The service worker (/sw.js) does two things and nothing else: it lets the
   browser open the dashboard full screen from the home screen, and it
   receives phone alerts. It never stores anything from the API, so no world
   data and no sign-in token is ever written to the phone's cache. */

import { api } from "./api.js";
import { t } from "./strings.js";

export const SW_URL = "/sw.js";

export function supported() {
  return "serviceWorker" in navigator && window.isSecureContext;
}

export function pushSupported() {
  return supported() && "PushManager" in window && "Notification" in window;
}

/* Registers the service worker, quietly. A browser that refuses it (an old
   one, or a page served without HTTPS) simply keeps working as before. */
export async function registerServiceWorker() {
  if (!supported()) return null;
  try {
    return await navigator.serviceWorker.register(SW_URL);
  } catch (err) {
    return null;
  }
}

function keyBytes(base64) {
  const padded = base64.replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(padded + "=".repeat((4 - (padded.length % 4)) % 4));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

/* What this browser's own subscription is, if it has one. */
export async function currentSubscription() {
  if (!pushSupported()) return null;
  const registration = await navigator.serviceWorker.getRegistration(SW_URL);
  if (!registration) return null;
  return registration.pushManager.getSubscription();
}

/* Asks permission, subscribes this browser, and tells the agent. Throws an
   Error with a plain sentence when any step is refused. */
export async function enablePush(publicKey, label) {
  if (!pushSupported()) throw new Error(t("push.unsupported"));
  const registration = (await navigator.serviceWorker.getRegistration(SW_URL))
    || (await registerServiceWorker());
  if (!registration) throw new Error(t("push.unsupported"));
  const permission = await Notification.requestPermission();
  if (permission !== "granted") throw new Error(t("push.blocked"));
  const existing = await registration.pushManager.getSubscription();
  const subscription = existing || (await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: keyBytes(publicKey),
  }));
  const result = await api("/push/subscribe", {
    method: "POST",
    body: { subscription: subscription.toJSON(), label },
  });
  return result;
}

/* Stops alerts on this browser: the browser's own subscription goes, and so
   does the agent's record of it. */
export async function disablePush() {
  const subscription = await currentSubscription();
  if (!subscription) return null;
  const endpoint = subscription.endpoint;
  try {
    await subscription.unsubscribe();
  } catch (err) { /* the agent's record still goes, below */ }
  return api("/push/unsubscribe", { method: "POST", body: { endpoint } });
}

/* A name for this phone, so the list of phones is readable. The user agent
   is the only thing the browser offers, so it is trimmed, never guessed at. */
export function deviceLabel() {
  const ua = navigator.userAgent || "";
  const platform = /iPhone|iPad|Android|Windows|Macintosh|Linux/.exec(ua);
  const browser = /Firefox|Edg|Chrome|Safari/.exec(ua);
  return [platform && platform[0], browser && browser[0]].filter(Boolean).join(" ") || "This device";
}
