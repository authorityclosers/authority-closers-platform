import type { Metadata } from "next";

/**
 * The public pages that app directories and crawlers read (orchestrator, 27 Oct 2026: the
 * ChatGPT directory reported the privacy policy as not accessible). They carry their own
 * title and index,follow; every other page keeps the layout's noindex, and robots.txt
 * allows only these on production (robots-txt.ts).
 */
const PUBLIC_TITLES = {
  privacy: "Privacy policy",
  terms: "Terms of service",
  contact: "Contact us",
} as const;

export type PublicPolicy = keyof typeof PUBLIC_TITLES;

/** Each public page's path, for robots.txt. */
export const PUBLIC_PAGES = (Object.keys(PUBLIC_TITLES) as PublicPolicy[]).map(
  (slug) => `/${slug}`,
);

/** A public page's heading, which its title repeats. */
export function publicTitle(slug: PublicPolicy): string {
  return PUBLIC_TITLES[slug];
}

export function publicPolicyMetadata(slug: PublicPolicy): Metadata {
  return {
    title: `${PUBLIC_TITLES[slug]} · Sales X-Ray`,
    robots: { index: true, follow: true },
  };
}
