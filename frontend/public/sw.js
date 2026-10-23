/* Along the Way service worker.
 *
 * Scope is deliberately narrow: keep the app shell openable without a network,
 * because this app is used underground and at station gantries where the
 * connection drops. It must never make a journey look answered when it was not,
 * so nothing under /api/ is cached or replayed - a recommendation is a live
 * computation against live routing, and a stale one is worse than an error.
 */

/* The build this worker belongs to, from the URL the page registered it with
 * (ServiceWorker.tsx appends ?v=<build id>, stamped by next.config.ts). A new
 * deploy registers a new URL, so a new worker installs with caches of its own
 * and the activate step below deletes the last build's - hashed assets from
 * old builds no longer pile up for ever. */
const BUILD = new URL(self.location.href).searchParams.get("v") || "dev";
const SHELL = `shell-${BUILD}`;
const ASSETS = `assets-${BUILD}`;
const OWN_CACHE = /^(?:shell|assets)-/;

// Enough to render each page and its offline state, nothing more.
const SHELL_URLS = ["/", "/privacy/", "/manifest.webmanifest", "/icon-192.png"];

/* One cache entry per page. The export is built with trailing slashes, so
 * "/privacy" and "/privacy/" are the same page; the query never selects a
 * different document. */
function pageKey(url) {
  const path =
    url.pathname.endsWith("/") || /\.[a-z0-9]+$/i.test(url.pathname)
      ? url.pathname
      : `${url.pathname}/`;
  return new URL(path, url.origin).href;
}

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
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => OWN_CACHE.test(key) && key !== SHELL && key !== ASSETS)
            .map((key) => caches.delete(key)),
        ),
      )
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
    caches.open(ASSETS).then((cache) =>
      Promise.allSettled(
        urls
          .filter((url) => {
            try {
              return new URL(url).origin === self.location.origin;
            } catch {
              return false;
            }
          })
          .map((url) => cache.add(url)),
      ),
    ),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return; // map tiles, geocoder: browser default
  if (url.pathname.startsWith("/api/")) return; // never cached, never replayed

  /* Navigations: network first so a fresh page wins, the cache only as the
   * offline fallback - and each page under its own URL. Every navigation used
   * to be stored as "/", so offline the privacy page opened the planner, or
   * the planner opened whichever page was visited last. A page never seen
   * online has no copy, and gets the browser's own offline error rather than
   * a different page. */
  if (request.mode === "navigate") {
    const key = pageKey(url);
    event.respondWith(
      fetch(request)
        .then((response) => {
          // Redirects arrive opaque here; only a real page is worth keeping.
          if (response.ok && response.type === "basic") {
            const copy = response.clone();
            caches
              .open(SHELL)
              .then((cache) => cache.put(key, copy))
              .catch(() => {});
          }
          return response;
        })
        .catch(() =>
          caches
            .open(SHELL)
            .then((cache) => cache.match(key))
            .then((cached) => cached ?? Response.error()),
        ),
    );
    return;
  }

  // Build output is content-hashed, so a hit is always correct: serve from
  // cache and fill on first miss.
  if (
    url.pathname.startsWith("/_next/") ||
    /\.(?:png|svg|ico|webmanifest|css|js|woff2?)$/.test(url.pathname)
  ) {
    event.respondWith(
      caches.match(request).then(
        (cached) =>
          cached ??
          fetch(request).then((response) => {
            if (response.ok) {
              const copy = response.clone();
              caches
                .open(ASSETS)
                .then((cache) => cache.put(request, copy))
                .catch(() => {});
            }
            return response;
          }),
      ),
    );
  }
});
