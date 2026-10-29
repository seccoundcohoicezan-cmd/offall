import type { NextConfig } from "next";

const apiOrigin = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  // gzip buffers responses and would break Server-Sent Events through the proxy
  compress: false,
  poweredByHeader: false,
  experimental: {
    // The /api proxy defaults to 30 s, which cut off slow provider calls (key tests,
    // model sync) and surfaced as a bare "Internal Server Error".
    proxyTimeout: 300_000,
  },
  async rewrites() {
    // Same-origin proxy keeps the httpOnly auth cookies first-party.
    return [
      { source: "/api/:path*", destination: `${apiOrigin}/api/:path*` },
      { source: "/health", destination: `${apiOrigin}/health` },
    ];
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Frame-Options", value: "DENY" },
        ],
      },
      { source: "/sw.js", headers: [{ key: "Cache-Control", value: "no-cache" }] },
    ];
  },
};

export default nextConfig;
