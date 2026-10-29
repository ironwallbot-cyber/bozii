import type { NextConfig } from "next";

const BACKEND = process.env.BOZII_API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // The FastAPI backend is proxied through the Next.js server so the browser
  // only talks to one origin (cookies, SSE and CORS stay simple). An explicit
  // route handler at /api/stream takes precedence over this rewrite so
  // server-sent events stream instead of being buffered.
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND}/api/:path*` }];
  },
};

export default nextConfig;