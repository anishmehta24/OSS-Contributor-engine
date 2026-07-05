import type { NextConfig } from "next";

// All FastAPI endpoints live under their own path prefixes (/auth, /users,
// /investigations, /admin, /health). We expose them under /api/* so the
// browser sees them as same-origin (cookies just work, no CORS gymnastics).
// Strip any trailing slash so `${FASTAPI_URL}/auth/...` never produces a
// double-slash path (e.g. `.../onrender.com//auth/login`), which FastAPI 404s on.
const FASTAPI_URL = (process.env.FASTAPI_URL ?? "http://localhost:8000").replace(
  /\/+$/,
  "",
);

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      { source: "/api/health", destination: `${FASTAPI_URL}/health` },
      { source: "/api/auth/:path*", destination: `${FASTAPI_URL}/auth/:path*` },
      { source: "/api/users/:path*", destination: `${FASTAPI_URL}/users/:path*` },
      // POST /investigations (no sub-path) and GET /investigations (list) need
      // a bare-path rewrite; the `:path*` rule below catches everything deeper.
      { source: "/api/investigations", destination: `${FASTAPI_URL}/investigations` },
      {
        source: "/api/investigations/:path*",
        destination: `${FASTAPI_URL}/investigations/:path*`,
      },
      { source: "/api/admin/:path*", destination: `${FASTAPI_URL}/admin/:path*` },
    ];
  },
};

export default nextConfig;
