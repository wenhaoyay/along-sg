import type { NextConfig } from "next";

/* One id per build, stamped into the client so the service worker can name
 * its caches after the build that made them (ServiceWorker.tsx, public/sw.js)
 * and drop the previous build's on activation. */
const buildId = process.env.NEXT_PUBLIC_BUILD_ID || Date.now().toString(36);

const nextConfig: NextConfig = {
  reactStrictMode: true,
  env: { NEXT_PUBLIC_BUILD_ID: buildId },
  generateBuildId: async () => buildId,
  devIndicators: false,
  output: "export",
  trailingSlash: true,
};

export default nextConfig;
