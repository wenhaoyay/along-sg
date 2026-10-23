import type { MetadataRoute } from "next";

import { THEME_COLOR } from "./theme";

/* Generated rather than kept as a file in public/, so its colours come from
 * the same constant as the page's <meta name="theme-color"> and the theme
 * switch. They used to be three different greens and greys. */
export const dynamic = "force-static";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Along",
    short_name: "Along",
    description:
      "Fit one or two errands into a Singapore public-transport journey with less detour.",
    start_url: "/",
    scope: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: THEME_COLOR.light,
    theme_color: THEME_COLOR.light,
    lang: "en-SG",
    categories: ["travel", "navigation", "utilities"],
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
      { src: "/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" },
    ],
  };
}
