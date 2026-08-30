import path from "node:path";

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  outputFileTracingRoot: path.join(__dirname, "../.."),
  reactStrictMode: true,
  transpilePackages: ["@ac/ui"],
  poweredByHeader: false,
  async rewrites() {
    if (process.env.NODE_ENV !== "development") return [];
    const apiOrigin = process.env.AC_API_URL ?? "http://127.0.0.1:8000";
    return [
      {
        source: "/v1/:path*",
        destination: `${apiOrigin.replace(/\/$/, "")}/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
