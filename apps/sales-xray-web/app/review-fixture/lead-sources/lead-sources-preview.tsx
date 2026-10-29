"use client";

/**
 * Organisation → Leads setup → Sources with fictional Facebook Pages from two
 * accounts (owner bugs #75 and #76, 29 Oct 2026), for phone shots and the
 * real-phone check: /review-fixture/lead-sources?tab=leads&part=sources.
 *
 *   ?state=empty    Facebook is set up but no Page is connected yet
 *   ?state=edited   one form is tapped after load, so the save bar shows
 *
 * The Meta reads are answered in the browser; nothing leaves it.
 */

import { Suspense, useEffect, useState } from "react";

import type { MetaPage } from "../../leads/sources-view";
import { OrganisationHub } from "../../organisation/org-hub";
import { OrganisationFixture } from "../_fixtures/organisation-fixture";
import { FixtureWorkspace } from "../leads/leads-preview";

const MINUTE = 60_000;
const at = (minutes: number) =>
  new Date(Date.now() + minutes * MINUTE).toISOString();

const PAGES: MetaPage[] = [
  {
    pageId: "920000000000001",
    name: "Fictional Homes",
    active: true,
    account: { name: "Asha Fictional", picture: null },
    received: 104,
    lastPulledAt: at(-4),
    forms: "all",
    formsCovered: [],
    formsOnPage: [
      { id: "h1", name: "Site visit enquiry", status: "ACTIVE", leads: 87 },
      { id: "h2", name: "Brochure download", status: "ACTIVE", leads: 14 },
      { id: "h3", name: "Callback request", status: "ACTIVE", leads: 1 },
    ],
    backfill: { state: "done", created: 2, seen: 104, linked: 100, known: 2 },
    problem: null,
  },
  {
    pageId: "920000000000002",
    name: "Fictional Homes Offers",
    active: false,
    account: { name: "Asha Fictional", picture: null },
    received: 0,
    lastPulledAt: null,
    forms: "all",
    formsCovered: [],
    formsOnPage: [
      { id: "o1", name: "Plot offer", status: "ACTIVE", leads: 9 },
      { id: "o2", name: "Festive offer 2025", status: "ARCHIVED", leads: 0 },
    ],
    backfill: null,
    problem: null,
  },
  {
    pageId: "920000000000003",
    name: "Fictional Clinics",
    active: true,
    account: { name: "Ravi Example", picture: null },
    received: 12,
    lastPulledAt: at(-9),
    forms: ["c1"],
    formsCovered: [],
    formsOnPage: [
      { id: "c1", name: "Book a consultation", status: "ACTIVE", leads: 12 },
      { id: "c2", name: "Health camp", status: "ARCHIVED", leads: 40 },
    ],
    backfill: { state: "running", created: 3, seen: 20, known: 17 },
    problem: null,
  },
];

function install() {
  if (typeof window === "undefined") return true;
  const earlier = window.fetch.bind(window);
  const empty =
    new URLSearchParams(window.location.search).get("state") === "empty";
  const json = (body: unknown) =>
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  window.fetch = async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
    if (!path.startsWith("/v1/lead-desk/meta/")) return earlier(input, init);
    if (path === "/v1/lead-desk/meta/status")
      return json({ configured: true, pages: empty ? [] : PAGES });
    const page = PAGES.find((item) => path.includes(`/pages/${item.pageId}`));
    if (page && path.endsWith("/forms")) return json(page.formsOnPage ?? []);
    if (page && path.endsWith("/backfill"))
      return json({
        page: {
          ...page,
          backfill: { state: "running", created: 0, seen: 0, known: 0 },
        },
      });
    if (page) return json({ page });
    return json({});
  };
  return true;
}

/** ?state=edited: tap the first form once it is on screen. */
function EditOnce() {
  useEffect(() => {
    if (new URLSearchParams(location.search).get("state") !== "edited") return;
    const timer = setInterval(() => {
      const pick = document.querySelector<HTMLButtonElement>(
        'section[aria-label^="Forms on"] button[aria-pressed="true"]',
      );
      if (!pick) return;
      clearInterval(timer);
      pick.click();
    }, 250);
    return () => clearInterval(timer);
  }, []);
  return null;
}

function MetaAnswers() {
  useState(install);
  return null;
}

export function LeadSourcesPreview() {
  return (
    <FixtureWorkspace>
      <Suspense fallback={null}>
        <OrganisationFixture>
          {/* Inside the others, so its answers come first. */}
          <MetaAnswers />
          <EditOnce />
          <OrganisationHub base="/review-fixture/lead-sources" />
        </OrganisationFixture>
      </Suspense>
    </FixtureWorkspace>
  );
}
