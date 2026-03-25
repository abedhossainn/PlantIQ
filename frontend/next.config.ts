import type { NextConfig } from "next";

const isStaticExport = process.env.NEXT_STATIC_EXPORT === "true";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["10.1.10.181", "127.0.0.1", "localhost"],
  ...(isStaticExport ? { output: "export" as const } : {}),
  basePath: "/PlantIQ",
  trailingSlash: true,
  reactCompiler: true,
  images: {
    unoptimized: true,
  },
};

export default nextConfig;
