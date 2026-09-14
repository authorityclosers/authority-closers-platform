import type { NextConfig } from "next";
import path from "node:path";

// Deployment supplies an exact internal AC API origin. Never accept a browser
// destination, cookies, credentials or arbitrary URL from a query parameter.
const configured = process.env.AC_CONVERSATION_API_ORIGIN;
const staticPreview = process.env.AC_SALES_XRAY_STATIC_PREVIEW === "1";
let apiOrigin: string | undefined;
if (configured) {
  const url = new URL(configured);
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.pathname !== "/" ||
    url.search ||
    url.hash
  )
    throw new Error(
      "AC_CONVERSATION_API_ORIGIN must be an exact credential-free origin.",
    );
  apiOrigin = url.origin;
}
const config: NextConfig = {
  output: staticPreview ? "export" : "standalone",
  ...(staticPreview ? { trailingSlash: true } : {}),
  outputFileTracingRoot: path.join(__dirname, "../.."),
  reactStrictMode: true,
  devIndicators: false,
  poweredByHeader: false,
  transpilePackages: ["@ac/ui", "@ac/sales-xray-client"],
  logging: false,
  ...(!staticPreview
    ? {
        async rewrites() {
          return apiOrigin
            ? [
                {
                  source: "/v1/conversation/:path*",
                  destination: `${apiOrigin}/v1/conversation/:path*`,
                },
                // The standalone document uses the same canonical identity
                // endpoints as the hosted reverse proxy. Keep this list exact;
                // the browser cannot choose an upstream or forward arbitrary APIs.
                ...[
                  "/v1/me/workspaces",
                  "/v1/context",
                  "/v1/auth/password/login",
                  "/v1/auth/logout",
                  "/v1/auth/google/start",
                  "/v1/auth/google/callback",
                ].map((source) => ({
                  source,
                  destination: `${apiOrigin}${source}`,
                })),
              ]
            : [];
        },
        async headers() {
          return [
            {
              source: "/:path*",
              headers: [
                { key: "Referrer-Policy", value: "no-referrer" },
                { key: "X-Content-Type-Options", value: "nosniff" },
                { key: "X-Frame-Options", value: "DENY" },
                {
                  key: "Permissions-Policy",
                  value: "camera=(), microphone=(), geolocation=()",
                },
                { key: "Cache-Control", value: "no-store" },
              ],
            },
          ];
        },
      }
    : {}),
};
export default config;
