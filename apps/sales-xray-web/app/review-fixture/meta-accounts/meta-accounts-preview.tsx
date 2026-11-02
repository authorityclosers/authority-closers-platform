"use client";

/**
 * Leads setup → Sources → Facebook & Instagram by account, for review
 * screenshots (owner, 2 Nov 2026): two Facebook accounts, one wrongly
 * connected with many Pages, the Pages bringing leads first, older leads
 * counted before anything is filed. Fictional accounts, Pages and forms; its
 * reads are answered here and nothing leaves the browser.
 */

import { Suspense, useState } from "react";

import { AcquisitionShell } from "../../acquisition-shell";
import type { MetaPage } from "../../leads/sources-view";
import { OrganisationSources } from "../../organisation/setup/sources";
import { WorkspaceAccessContext } from "../../workspace-access";

const OWNER = "00000000-0000-4000-8000-000000000001";
const TENANT = "00000000-0000-4000-8000-000000000004";
const SESSION = "00000000-0000-4000-8000-000000000005";
const HOUR = 3_600_000;
const at = (hours: number) => new Date(Date.now() + hours * HOUR).toISOString();

const right = {
  id: "880000000000001",
  name: "Asha Fictional",
  connectedAt: at(-24 * 21),
};
const wrong = {
  id: "880000000000002",
  name: "Old Agency Login",
  connectedAt: at(-24 * 3),
};
const forms = (prefix: string, live: number, archived: number) => [
  ...Array.from({ length: live }, (_, i) => ({
    id: `${prefix}-a${i}`,
    name: `${["Site visit", "Brochure", "Callback", "Offer"][i % 4]} form ${i + 1}`,
    status: "ACTIVE",
    leads: 40 - i * 7,
  })),
  ...Array.from({ length: archived }, (_, i) => ({
    id: `${prefix}-x${i}`,
    name: `Campaign form, June 2024 (${i + 1})`,
    status: "ARCHIVED",
    leads: 0,
  })),
];
const PAGES: MetaPage[] = [
  {
    pageId: "910000000000001",
    name: "Fictional Homes",
    active: true,
    account: right,
    received: 104,
    lastReceivedAt: at(-2),
    realLeads: true,
    forms: "all",
    formsCovered: forms("h", 3, 0),
    formsOnPage: forms("h", 3, 2),
  },
  {
    pageId: "910000000000002",
    name: "Fictional Clinics",
    active: true,
    account: right,
    received: 12,
    lastReceivedAt: at(-30),
    realLeads: true,
    forms: ["c-a0"],
    formsCovered: forms("c", 1, 0),
    formsOnPage: forms("c", 2, 4),
    backfill: { state: "done", created: 9, seen: 11, known: 2, days: 30 },
  },
  ...Array.from({ length: 12 }, (_, i) => ({
    pageId: `91000000000010${i}`,
    name: `Agency client Page ${i + 1}`,
    active: false,
    account: wrong,
    received: 0,
    forms: "all" as const,
    formsOnPage: forms(`w${i}`, 2, 3),
  })),
];

function answer(path: string): unknown {
  if (path === "/v1/lead-desk/meta/status")
    return { configured: true, pages: PAGES };
  const asked = /^\/v1\/lead-desk\/meta\/pages\/(\d+)\/forms$/.exec(path);
  if (asked)
    return PAGES.find((page) => page.pageId === asked[1])?.formsOnPage ?? [];
  if (/^\/v1\/lead-desk\/meta\/pages\/\d+\/older$/.test(path))
    return {
      until: at(-24 * 21),
      counts: [
        { days: 7, leads: 6 },
        { days: 30, leads: 31 },
        { days: 90, leads: 118 },
      ],
      capped: false,
    };
  if (path === "/v1/lead-desk/google/status")
    return { configured: false, accounts: [] };
  if (path === "/v1/lead-desk/sources") return { sources: [] };
  // The sellers, for each Page's "Who gets these leads?"; the owner doesn't sell.
  if (path === "/v1/lead-desk/team")
    return {
      reps: [
        { person_id: "s1", name: "Meera Fictional", available: true },
        { person_id: "s2", name: "Kabir Example", available: true },
        { person_id: "o1", name: "Asha Fictional", available: false },
      ],
    };
  if (path === "/v1/me/sales-xray-workspaces")
    return {
      selected_tenant_id: TENANT,
      workspaces: [
        {
          tenant_id: TENANT,
          kind: "organisation",
          name: "Fictional Homes",
          role: "owner",
          sales_xray_enabled: true,
        },
      ],
    };
  return undefined;
}

function install() {
  if (typeof window === "undefined") return true;
  const real = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
    const body = (init?.method ?? "GET") === "GET" ? answer(path) : undefined;
    if (body !== undefined)
      return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
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
  useState(install);
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
      <AcquisitionShell authenticated active="account" pageName="Leads setup">
        <OrganisationSources />
      </AcquisitionShell>
    </WorkspaceAccessContext.Provider>
  );
}

export function MetaAccountsPreview() {
  return (
    <Suspense fallback={null}>
      <Preview />
    </Suspense>
  );
}
