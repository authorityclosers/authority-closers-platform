import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  transpilePackages: ["@ac/ui"],
  poweredByHeader: false,
};

export default nextConfig;
