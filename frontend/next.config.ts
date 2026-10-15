import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: false,
  poweredByHeader: false,
  productionBrowserSourceMaps: false,
  compiler: {
    removeConsole: process.env.NODE_ENV === "production" ? { exclude: ["error", "warn"] } : false,
  },
  experimental: {
    optimizePackageImports: ["@phosphor-icons/react"],
  },
  // The marketing landing page is plain static HTML in public/ (index.html,
  // styles.css, app.js, assets/), served at /homepage. The bare root sends
  // visitors there; it's a temporary redirect so browsers don't cache it.
  async redirects() {
    return [{ source: "/", destination: "/homepage", permanent: false }];
  },
  async rewrites() {
    return { beforeFiles: [{ source: "/homepage", destination: "/index.html" }], afterFiles: [], fallback: [] };
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
            value: "camera=(), microphone=(), geolocation=()",
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
