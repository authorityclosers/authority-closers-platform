"use client";

/**
 * Leads setup → Sources with Facebook Pages from two accounts, for screenshots
 * on GitHub (wb-ci --visual): each account, its Pages and every form as rows,
 * with switches and chips (owner, 26 Oct 2026, bug reports #21 and #22).
 * Fictional accounts, Pages and forms; its reads are answered here and nothing
 * leaves the browser.
 */

import { Suspense, useState } from "react";

import { AcquisitionShell } from "../../acquisition-shell";
import { SourcesView, type MetaPage } from "../../leads/sources-view";
import { WorkspaceAccessContext } from "../../workspace-access";

const OWNER = "00000000-0000-4000-8000-000000000001";
const TENANT = "00000000-0000-4000-8000-000000000004";
const SESSION = "00000000-0000-4000-8000-000000000005";
const MINUTE = 60_000;

const at = (minutes: number) =>
  new Date(Date.now() + minutes * MINUTE).toISOString();

const PAGES: MetaPage[] = [
  {
    pageId: "910000000000001",
    name: "Fictional Homes",
    active: true,
    account: { name: "Asha Fictional", picture: null },
    received: 104,
    lastPulledAt: at(-4),
    forms: "all",
    formsCovered: [],
    formsOnPage: [
      { id: "f1", name: "Site visit enquiry", status: "ACTIVE", leads: 87 },
      { id: "f2", name: "Brochure download", status: "ACTIVE", leads: 14 },
      { id: "f3", name: "Festive offer 2025", status: "ARCHIVED", leads: 1 },
      { id: "f4", name: "Callback request", status: "ACTIVE", leads: 1 },
    ],
    backfill: {
      state: "done",
      created: 2,
      seen: 104,
      linked: 100,
      known: 2,
      forms: 4,
    },
    problem: null,
  },
  {
    pageId: "910000000000002",
    name: "Fictional Homes Offers",
    active: false,
    account: { name: "Asha Fictional", picture: null },
    received: 0,
    lastPulledAt: null,
    forms: "all",
    formsCovered: [],
    formsOnPage: [
      { id: "f5", name: "Plot offer", status: "ACTIVE", leads: 9 },
      { id: "f6", name: "Old launch form", status: "DRAFT", leads: 0 },
    ],
    backfill: null,
    problem: null,
  },
  {
    pageId: "910000000000003",
    name: "Fictional Clinics",
    active: true,
    account: { name: "Ravi Example", picture: null },
    received: 12,
    lastPulledAt: at(-9),
    forms: ["f7"],
    formsCovered: [],
    formsOnPage: [
      { id: "f7", name: "Book a consultation", status: "ACTIVE", leads: 12 },
      { id: "f8", name: "Health camp", status: "ARCHIVED", leads: 40 },
    ],
    backfill: { state: "running", created: 3, seen: 20, known: 17, forms: 1 },
    problem: null,
  },
];

function answer(path: string): unknown {
  if (path === "/v1/lead-desk/meta/status")
    return { configured: true, pages: PAGES };
  if (path === "/v1/lead-desk/google/status")
    return { configured: false, accounts: [] };
  if (path === "/v1/lead-desk/sources") return { sources: [] };
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
        <SourcesView sandbox={false} onChanged={() => {}} onImport={() => {}} />
      </AcquisitionShell>
    </WorkspaceAccessContext.Provider>
  );
}

export function MetaSourcesPreview() {
  return (
    <Suspense fallback={null}>
      <Preview />
    </Suspense>
  );
}
