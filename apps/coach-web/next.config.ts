import path from "node:path";
import type { NextConfig } from "next";
const config: NextConfig = {
  output: "standalone",
  outputFileTracingRoot: path.join(__dirname, "../.."),
  reactStrictMode: true,
  devIndicators: false,
  transpilePackages: ["@ac/ui", "@ac/operations-web"],
  poweredByHeader: false,
};
export default config;
