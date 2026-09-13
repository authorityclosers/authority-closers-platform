import path from "node:path";

import type { NextConfig } from "next";
import nextPackage from "next/package.json";
import { resolveDevAuthBridgeConfig } from "./app/lib/dev-api-proxy";
import { assertDevelopmentMediaNativePrivacy } from "./app/lib/dev-media-native-privacy";

const developmentBridge = resolveDevAuthBridgeConfig(
  process.env,
  process.env.NODE_ENV,
);
const localSandbox =
  process.env.NODE_ENV === "development" &&
  process.env.AC_DEV_LOCAL_SANDBOX_ENABLED === "true";
const privateMediaDevelopment = Boolean(developmentBridge || localSandbox);

if (privateMediaDevelopment) assertDevelopmentMediaNativePrivacy();

if (
  privateMediaDevelopment &&
  (nextPackage.version !== "16.3.3" ||
    process.env.NEXT_TRACE_SPAN_THRESHOLD_MS !== "9007199254740991")
) {
  // logging:false does not cover .next/dev/trace. This pinned, internal Next
  // control must be inherited before bootstrap, not assigned from this config.
  // An upgrade needs renewed installed-runtime privacy evidence before use.
  throw new Error(
    "Local staging media requires the reviewed trace-private launcher and validated Next version. Start with scripts/Start-LocalStagingBridge.ps1; revalidate trace privacy before upgrading Next.",
  );
}

const nextConfig: NextConfig = {
  output: "standalone",
  outputFileTracingRoot: path.join(__dirname, "../.."),
  reactStrictMode: true,
  // Keep framework chrome off the viewport while reviewing the actual app UI.
  devIndicators: false,
  transpilePackages: ["@ac/ui", "@ac/sales-xray-review-ui"],
  poweredByHeader: false,
  // Next logs fetch warnings separately from incoming-request ignore rules.
  // Disable framework URL logging only for this validated opt-in dev bridge.
  logging: privateMediaDevelopment ? false : undefined,
  experimental: { serverComponentsHmrCache: !privateMediaDevelopment },
};

export default nextConfig;
