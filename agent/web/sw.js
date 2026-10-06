/* The dashboard's service worker. Served from the site root (/sw.js) so it
   covers the whole dashboard.

   It exists for two reasons: a phone can open the dashboard full screen
   from its home screen even for a moment before the agent answers, and
   phone alerts are delivered through it.

   What it caches: only the app's own shell (the page, its stylesheet, its
   scripts and its icons), and only ever as a fallback. Anything under /api
   or /ws is passed straight to the network and never stored, so no world
   data, no player name and no sign-in token is written to the phone. */

const SHELL = "mcsc-shell";
const SHELL_FILES = [
  "/",
  "/assets/styles.css",
  "/assets/theme.js",
  "/assets/icon.svg",
  "/assets/js/main.js",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL)
      .then((cache) => cache.addAll(SHELL_FILES))
      .catch(() => null)
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((names) => Promise.all(names.filter((n) => n !== SHELL).map((n) => caches.delete(n))))
      .then(() => self.clients.claim()),
  );
});

/* Never cache data: only this origin's static files, and the network first
   so the dashboard is never a stale copy of itself. */
function isShellRequest(url) {
  if (url.origin !== self.location.origin) return false;
  if (url.pathname.startsWith("/api") || url.pathname.startsWith("/ws")) return false;
  return url.pathname === "/" || url.pathname.startsWith("/assets/") || url.pathname === "/sw.js"
    || url.pathname === "/manifest.webmanifest";
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (!isShellRequest(url)) return;  // straight to the network, nothing stored
  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response && response.ok && response.type === "basic") {
          const copy = response.clone();
          caches.open(SHELL).then((cache) => cache.put(request, copy)).catch(() => null);
        }
        return response;
      })
      .catch(() => caches.match(request).then((hit) => hit || Response.error())),
  );
});

/* A phone alert. The agent sends a small JSON object; nothing is fetched
   here, so an alert shows the same words whether the phone is on the
   network or not. */
self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (err) {
    data = {};
  }
  const title = data.title || "Minecraft Server Control";
  event.waitUntil(self.registration.showNotification(title, {
    body: data.body || "",
    icon: "/assets/icons/icon-192.png",
    badge: "/assets/icons/icon-192.png",
    tag: data.event || "mcsc",
    timestamp: data.ts ? data.ts * 1000 : Date.now(),
    data: { server_id: data.server_id || null },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true })
    .then((windows) => {
      for (const client of windows) {
        if (client.url.startsWith(self.location.origin)) return client.focus();
      }
      return self.clients.openWindow("/");
    }));
});
