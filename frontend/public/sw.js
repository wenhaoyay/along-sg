/* Along the Way service worker.
 *
 * Scope is deliberately narrow: keep the app shell openable without a network,
 * because this app is used underground and at station gantries where the
 * connection drops. It must never make a journey look answered when it was not,
 * so nothing under /api/ is cached or replayed - a recommendation is a live
 * computation against live routing, and a stale one is worse than an error.
 */

const VERSION = "along-v1";
const SHELL = `shell-${VERSION}`;
const ASSETS = `assets-${VERSION}`;

// Enough to render the shell and its offline state, nothing more.
const SHELL_URLS = ["/", "/manifest.webmanifest", "/icon-192.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL)
      // A missing entry must not fail the whole install.
      .then((cache) => Promise.allSettled(SHELL_URLS.map((url) => cache.add(url))))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(
        keys.filter((key) => key !== SHELL && key !== ASSETS).map((key) => caches.delete(key)),
      ))
      .then(() => self.clients.claim()),
  );
});

/* The worker activates after the first page has already fetched its scripts,
 * so those requests are never intercepted and the asset cache starts empty -
 * a cold offline start would then render the markup and fail to hydrate. The
 * page reports what it actually loaded and we cache exactly that. */
self.addEventListener("message", (event) => {
  const { type, urls } = event.data ?? {};
  if (type !== "warm" || !Array.isArray(urls)) return;
  event.waitUntil(
    caches.open(ASSETS).then((cache) => Promise.allSettled(
      urls
        .filter((url) => {
          try { return new URL(url).origin === self.location.origin; } catch { return false; }
        })
        .map((url) => cache.add(url)),
    )),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return; // map tiles, geocoder: browser default
  if (url.pathname.startsWith("/api/")) return; // never cached, never replayed

  // Navigations: network first so a fresh shell wins, cache only as the
  // offline fallback.
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          caches.open(SHELL).then((cache) => cache.put("/", response.clone())).catch(() => {});
          return response;
        })
        .catch(() => caches.match("/").then((cached) => cached ?? Response.error())),
    );
    return;
  }

  // Build output is content-hashed, so a hit is always correct: serve from
  // cache and fill on first miss.
  if (url.pathname.startsWith("/_next/") || /\.(?:png|svg|webmanifest|css|js|woff2?)$/.test(url.pathname)) {
    event.respondWith(
      caches.match(request).then((cached) => cached ?? fetch(request).then((response) => {
        if (response.ok) {
          caches.open(ASSETS).then((cache) => cache.put(request, response.clone())).catch(() => {});
        }
        return response;
      })),
    );
  }
});
