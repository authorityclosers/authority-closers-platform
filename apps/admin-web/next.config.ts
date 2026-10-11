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
  // Old admin addresses keep working after the console rebuild (AUT-1798).
  async redirects() {
    return [
      {
        source: "/sales-xray",
        destination: "/sales-xray/providers",
        permanent: false,
      },
      {
        source: "/sales-xray/settings",
        destination: "/sales-xray/providers?tab=providers",
        permanent: false,
      },
      {
        source: "/sales-xray/benchmark",
        destination: "/sales-xray/providers?tab=benchmark",
        permanent: false,
      },
      {
        source: "/sales-xray/review",
        destination: "/reviewers",
        permanent: false,
      },
    ];
  },
};

export default nextConfig;
