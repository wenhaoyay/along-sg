"use client";

import { useEffect } from "react";

/** Registers the offline shell, production only.
 *
 * Kept out of development so the Playwright suite and `next dev` always see
 * the code on disk rather than a cached shell from an earlier run. */
export function ServiceWorker() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production") return;
    if (!("serviceWorker" in navigator)) return;
    const timer = window.setTimeout(() => {
      void navigator.serviceWorker
        .register("/sw.js")
        .then(async () => {
          // Hand the worker the assets this page really loaded. It activated
          // too late to intercept them, so without this the offline shell has
          // markup but no script to hydrate it.
          const registration = await navigator.serviceWorker.ready;
          const urls = performance
            .getEntriesByType("resource")
            .map((entry) => entry.name)
            .filter((name) => name.startsWith(location.origin)
              && (name.includes("/_next/") || /\.(?:css|js|woff2?|png|svg)(?:\?|$)/.test(name)));
          registration.active?.postMessage({ type: "warm", urls });
        })
        .catch(() => {
          // Offline support is an enhancement; the app works without it.
        });
    }, 1200); // let the first paint and the catalog fetch finish first
    return () => window.clearTimeout(timer);
  }, []);
  return null;
}
