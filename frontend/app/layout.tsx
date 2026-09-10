import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import "leaflet/dist/leaflet.css";

import { ServiceWorker } from "./ServiceWorker";
import { THEME_BOOTSTRAP } from "./theme";

/* The stylesheet was written for Inter and Inter was never loaded - no
   next/font import, no @font-face, no link tag - so Windows rendered Segoe UI
   and Android Roboto. Worse, the CSS asks for weights 450, 650, 750 and 850,
   which only exist on a variable font; on a static family all four snap to the
   nearest real weight and the hierarchy collapses to bold-or-not. Loading the
   variable face is what makes the type scale below it real. */
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Along the Way — Singapore errand optimiser",
  description: "Fit one or two errands into a Singapore public-transport journey with less detour.",
  manifest: "/manifest.webmanifest",
  applicationName: "Along",
  appleWebApp: { capable: true, title: "Along", statusBarStyle: "default" },
  icons: {
    icon: [
      { url: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: "/apple-touch-icon.png",
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // The planner is a bottom sheet over a full-bleed map, so the browser chrome
  // should tint to the page ground rather than to the brand green.
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#dfe7e3" },
    { media: "(prefers-color-scheme: dark)", color: "#0c1211" },
  ],
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en-SG" className={inter.variable} suppressHydrationWarning>
      <head>
        {/* Stamps data-theme before the first paint. Without a blocking script
            here the page renders light and then flips, which is worse at night
            than having no dark mode at all. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
      </head>
      <body>
        {children}
        <ServiceWorker />
      </body>
    </html>
  );
}
