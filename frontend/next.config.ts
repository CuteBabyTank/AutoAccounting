import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: false,
  poweredByHeader: false,
  // The dev-only "N" badge defaults to bottom-left, on top of the sidebar's Sign out.
  devIndicators: { position: "bottom-left" }, // bottom-right is the assistant launcher
  productionBrowserSourceMaps: false,
  compiler: {
    removeConsole: process.env.NODE_ENV === "production" ? { exclude: ["error", "warn"] } : false,
  },
  experimental: {
    optimizePackageImports: ["@phosphor-icons/react"],
  },
  // The marketing landing page is plain static HTML in public/ (index.html,
  // styles.css, app.js, assets/), served at the root so search engines index
  // it there. The old /homepage address redirects permanently.
  async redirects() {
    return [{ source: "/homepage", destination: "/", permanent: true }];
  },
  async rewrites() {
    return { beforeFiles: [{ source: "/", destination: "/index.html" }], afterFiles: [], fallback: [] };
  },
  async headers() {
    // NOTE: Content-Security-Policy is intentionally NOT set here. It is
    // emitted per-request with a fresh nonce by src/middleware.ts so inline
    // scripts can be allow-listed by nonce instead of 'unsafe-inline'. The
    // remaining headers are static and live here.
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-XSS-Protection", value: "1; mode=block" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          {
            key: "Permissions-Policy",
            value: "camera=(self), microphone=(), geolocation=()",  // camera: taking a profile picture
          },
          {
            key: "Strict-Transport-Security",
            value: "max-age=63072000; includeSubDomains; preload",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
