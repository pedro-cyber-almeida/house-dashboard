// Service worker: offline shell for the dashboard.
//
// Online behaviour is always fresh (network-first, cache as fallback), so a
// deploy never serves stale JS/CSS. The cache only matters when the browser
// (or the phone) is offline; health states stay server-driven either way.

const CACHE_NAME = "house-dashboard-shell-v1";

const PRECACHE = [
  "/",
  "/css/style.css",
  "/js/app.js",
  "/js/admin.js",
  "/js/api.js",
  "/favicon.svg",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return; // API and probes are always live

  event.respondWith(
    (async () => {
      try {
        const response = await fetch(request);
        if (response.ok) {
          const cache = await caches.open(CACHE_NAME);
          cache.put(request, response.clone());
        }
        return response;
      } catch (err) {
        const cached = (await caches.match(request)) || (request.mode === "navigate" ? await caches.match("/") : undefined);
        if (cached) return cached;
        throw err;
      }
    })(),
  );
});
