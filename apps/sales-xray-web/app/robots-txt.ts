/**
 * /robots.txt (orchestrator, 27 Oct 2026). On the production host, crawlers may read the
 * public policy pages (policy-metadata.ts) and the /.well-known discovery documents; the
 * signed-in app stays disallowed. Every other host (staging, dev) disallows everything.
 */

import { PRODUCTION_HOST } from "./openai-apps-challenge";
import { PUBLIC_PAGES } from "./policy-metadata";

/** The robots.txt for the host a request reached (null: not a Sales X-Ray host). */
export function robotsTxt(host: string | null): string {
  if (host !== PRODUCTION_HOST) return "User-agent: *\nDisallow: /\n";
  return [
    "User-agent: *",
    ...PUBLIC_PAGES.map((page) => `Allow: ${page}`),
    "Allow: /.well-known/",
    "Disallow: /",
    "",
  ].join("\n");
}
