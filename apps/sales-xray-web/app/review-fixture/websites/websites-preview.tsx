"use client";

/**
 * Leads → Sources → Websites and landing pages, for screenshots on GitHub (wb-ci --visual)
 * and the real-phone check (owner, 30 Oct 2026). Fictional sites; the reads are answered
 * here and nothing leaves the browser.
 *
 *   /review-fixture/websites                 three sites, one waiting, one paused
 *   /review-fixture/websites?state=empty     nothing connected yet
 *   /review-fixture/websites?state=waiting   Add website open, waiting for the first visit
 *   /review-fixture/websites?state=seen      Add website open, "We saw your site"
 *   /review-fixture/websites?state=site      one site's sheet with its pages
 */

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { AcquisitionShell } from "../../acquisition-shell";
import { WebsitesCard } from "../../leads/websites/websites-card";
import type { Website, Websites } from "../../leads/websites/websites-client";
import { WorkspaceAccessContext } from "../../workspace-access";

const OWNER = "00000000-0000-4000-8000-000000000001";
const TENANT = "00000000-0000-4000-8000-000000000004";
const SESSION = "00000000-0000-4000-8000-000000000005";
const KEY = "sxw_FictionalFixtureKey00000000000001";
const MINUTE = 60_000;

const LOADED = Date.now();
const OPENED = LOADED - MINUTE;
const at = (minutes: number) =>
  new Date(LOADED + minutes * MINUTE).toISOString();

const page = (
  path: string,
  title: string | null,
  views: number,
  forms: number,
  fills: number,
  leads: number,
): Website["pages"][number] => ({
  path,
  title,
  views,
  forms,
  fills,
  leads,
  blocked: 0,
  rate: views ? fills / views : null,
  last_day: at(0).slice(0, 10),
});

function site(extra: Partial<Website>): Website {
  const pages = extra.pages ?? [];
  const views = pages.reduce((sum, item) => sum + item.views, 0);
  const fills = pages.reduce((sum, item) => sum + item.fills, 0);
  return {
    site_id: "s1",
    host: "fictional-homes.example.com",
    label: "fictional-homes.example.com",
    status: "active",
    platform: "wordpress",
    added: "seen",
    first_seen_at: at(-9 * 24 * 60),
    last_seen_at: at(-2),
    last_page: null,
    last_lead_at: at(-35),
    test: false,
    views,
    forms: pages.reduce((sum, item) => sum + item.forms, 0),
    fills,
    leads: pages.reduce((sum, item) => sum + item.leads, 0),
    blocked: 0,
    rate: views ? fills / views : null,
    ...extra,
    pages,
  };
}

const SITES: Website[] = [
  site({
    site_id: "s1",
    blocked: 6,
    pages: [
      page("/site-visit", "Book a site visit", 812, 1, 31, 27),
      page("/", "Fictional Homes · 2 and 3 BHK homes", 1460, 1, 12, 10),
      page("/brochure", "Download the brochure", 233, 1, 9, 6),
      page("/contact", "Contact us", 140, 1, 3, 2),
      page("/blog/home-loan-tips", "Home loan tips", 390, 0, 0, 0),
    ],
  }),
  site({
    site_id: "s2",
    host: "offer.fictional-homes.example.com",
    label: "offer.fictional-homes.example.com",
    platform: "framer",
    last_seen_at: at(-14),
    pages: [page("/diwali", "Diwali offer · 5% off", 604, 1, 41, 38)],
  }),
  site({
    site_id: "s3",
    host: "fictionalclinic.example.com",
    label: "fictionalclinic.example.com",
    added: "person",
    platform: null,
    first_seen_at: null,
    last_seen_at: null,
    last_lead_at: null,
    pages: [],
  }),
  site({
    site_id: "s4",
    host: "old-campaign.example.com",
    label: "old-campaign.example.com",
    status: "paused",
    platform: "webflow",
    last_seen_at: at(-3 * 24 * 60),
    pages: [page("/", "Old campaign", 44, 1, 1, 1)],
  }),
];

function answer(state: string): Websites {
  const base: Websites = {
    on: true,
    key: KEY,
    script_url: "https://salesxray.example.com/sx.js",
    snippet: `<script src="https://salesxray.example.com/sx.js" data-key="${KEY}" async></script>`,
    period_days: 30,
    sites: [],
    views: 0,
    leads: 0,
    rate: null,
    now: at(0),
  };
  if (state === "empty") return { ...base, key: null, snippet: null };
  if (state === "waiting") return base;
  if (state === "seen")
    return {
      ...base,
      sites: [
        site({
          site_id: "s1",
          first_seen_at: at(-0.2),
          last_seen_at: at(-0.2),
          pages: [page("/", "Fictional Homes", 1, 2, 0, 0)],
        }),
      ],
    };
  const views = SITES.reduce((sum, item) => sum + item.views, 0);
  const fills = SITES.reduce((sum, item) => sum + item.fills, 0);
  return {
    ...base,
    sites: SITES,
    views,
    leads: SITES.reduce((sum, item) => sum + item.leads, 0),
    rate: fills / views,
  };
}

function install(state: string) {
  if (typeof window === "undefined") return true;
  const real = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
    if (path.startsWith("/v1/lead-desk/websites")) {
      const body = path.endsWith("/test")
        ? { lead_id: null }
        : answer(
            state === "empty" && init?.method === "POST" ? "waiting" : state,
          );
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
    if (path.startsWith("/v1/"))
      return new Response(JSON.stringify({ detail: "Sample data only." }), {
        status: 404,
        headers: { "content-type": "application/json" },
      });
    return real(input, init);
  };
  return true;
}

function Preview() {
  const state = useSearchParams().get("state") ?? "sites";
  useState(() => install(state));
  // Add website opened a minute ago; the "seen" site said hello since then.
  const opened = state === "waiting" || state === "seen" ? OPENED : null;
  return (
    <WorkspaceAccessContext.Provider
      value={{
        status: "ready",
        authenticated: true,
        context: { personId: OWNER, sessionId: SESSION, tenantId: TENANT },
        workspaces: [
          {
            tenant_id: TENANT,
            kind: "organisation",
            name: "Fictional Homes",
            role: "owner",
            sales_xray_enabled: true,
          },
        ],
        retry: () => {},
      }}
    >
      <AcquisitionShell authenticated active="account" pageName="Lead sources">
        <WebsitesCard
          openAdd={opened}
          openSite={state === "site" ? "s1" : null}
        />
      </AcquisitionShell>
    </WorkspaceAccessContext.Provider>
  );
}

export function WebsitesPreview() {
  return (
    <Suspense fallback={null}>
      <Preview />
    </Suspense>
  );
}
