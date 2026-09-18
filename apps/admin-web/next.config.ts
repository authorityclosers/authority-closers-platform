import path from "node:path";

import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  outputFileTracingRoot: path.join(__dirname, "../.."),
  reactStrictMode: true,
  devIndicators: false,
  transpilePackages: [
    "@ac/ui",
    "@ac/operations-web",
    "@ac/sales-xray-review-ui",
  ],
  poweredByHeader: false,
};

export default nextConfig;
