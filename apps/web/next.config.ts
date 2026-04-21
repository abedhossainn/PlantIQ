import type { NextConfig } from "next";

const isStaticExport = process.env.NEXT_STATIC_EXPORT === "true";

const POSTGREST_INTERNAL_URL = process.env.POSTGREST_INTERNAL_URL || "http://plantiq-postgrest:3000";
// Server-side URL for the FastAPI backend (never exposed to browser).
// In Docker this is the container-network hostname; outside Docker override via env.
const BACKEND_INTERNAL_URL = process.env.BACKEND_INTERNAL_URL || "http://backend:8000";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["10.1.10.181", "127.0.0.1", "localhost", "plantiq.sahossain.com", "api.plantiq.sahossain.com"],
  ...(isStaticExport ? { output: "export" as const } : {}),
  basePath: "/PlantIQ",
  trailingSlash: true,
  reactCompiler: true,
  images: {
    unoptimized: true,
  },
  async rewrites() {
    if (isStaticExport) return [];
    return [
      {
        source: "/api/postgrest/:path*",
        destination: `${POSTGREST_INTERNAL_URL}/:path*`,
      },
      // Proxy all FastAPI calls server-side so the browser only needs the
      // relative path "/PlantIQ/api/backend" — works identically on
      // localhost:3000 and via any Cloudflare tunnel origin.
      {
        source: "/api/backend/:path*",
        destination: `${BACKEND_INTERNAL_URL}/:path*`,
      },
    ];
  },
};

export default nextConfig;
