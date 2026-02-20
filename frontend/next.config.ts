import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  reactCompiler: true,
  // Static export for GitHub Pages
  output: "export",
  basePath: "/PlantIQ",
  trailingSlash: true,
  images: {
    unoptimized: true,
  },
};

export default nextConfig;
