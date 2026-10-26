import { existsSync } from "node:fs";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { metadata as contact } from "./contact/page";
import { PRODUCTION_HOST } from "./openai-apps-challenge";
import { PolicyPage } from "./policy-content";
import {
  PUBLIC_PAGES,
  publicPolicyMetadata,
  publicTitle,
  type PublicPolicy,
} from "./policy-metadata";
import { metadata as privacy } from "./privacy/page";
import { GET } from "./robots.txt/route.discovery";
import { robotsTxt } from "./robots-txt";
import { metadata as terms } from "./terms/page";

// fetch's Request drops a Host header, so the proxy's forwarded host stands in.
function request(host: string) {
  return new Request(`https://${host}/robots.txt`, {
    headers: { "x-forwarded-host": host },
  });
}

describe("public policy pages for crawlers (27 Oct 2026)", () => {
  it("lets crawlers read production's policy pages and discovery documents only", () => {
    expect(robotsTxt(PRODUCTION_HOST)).toBe(
      [
        "User-agent: *",
        "Allow: /privacy",
        "Allow: /terms",
        "Allow: /contact",
        "Allow: /.well-known/",
        "Disallow: /",
        "",
      ].join("\n"),
    );
    for (const host of ["salesxray-staging.authorityclosers.com", null])
      expect(robotsTxt(host)).toBe("User-agent: *\nDisallow: /\n");
  });

  it("serves robots.txt as plain text for the host it reached", async () => {
    expect(
      existsSync(path.join(__dirname, "robots.txt", "route.discovery.ts")),
    ).toBe(true);
    const answer = GET(request(PRODUCTION_HOST));
    expect(answer.status).toBe(200);
    expect(answer.headers.get("content-type")).toBe(
      "text/plain; charset=utf-8",
    );
    expect(await answer.text()).toContain("Allow: /privacy\n");
    const staging = GET(request("salesxray-staging.authorityclosers.com"));
    expect(await staging.text()).toBe("User-agent: *\nDisallow: /\n");
  });

  it("gives each public page its own title and index,follow", () => {
    const pages: Record<PublicPolicy, unknown> = { privacy, terms, contact };
    expect(PUBLIC_PAGES).toEqual(["/privacy", "/terms", "/contact"]);
    for (const slug of Object.keys(pages) as PublicPolicy[]) {
      expect(pages[slug]).toEqual(publicPolicyMetadata(slug));
      expect(pages[slug]).toMatchObject({
        title: `${publicTitle(slug)} · Sales X-Ray`,
        robots: { index: true, follow: true },
      });
      // The title repeats the page's own heading.
      expect(renderToStaticMarkup(<PolicyPage slug={slug} />)).toContain(
        `<h1>${publicTitle(slug)}</h1>`,
      );
    }
  });
});
