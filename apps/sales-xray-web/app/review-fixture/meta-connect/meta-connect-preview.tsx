"use client";

/**
 * Settings → Connected apps with the guided lead ads setup, for screenshots on
 * GitHub (wb-ci --visual). Fictional Pages and forms; its reads are answered
 * here and nothing leaves the browser.
 * `?state=new` (default): nothing connected yet. `?state=off`: a Page shared
 * but off. `?state=live`: one Page on and bringing leads in, one off.
 * `&tap=open` opens the lead ads sheet by itself; `&tap=forms` then opens the
 * first Page's forms and ticks one.
 */

import { Suspense, useEffect, useState } from "react";

import { AcquisitionShell } from "../../acquisition-shell";
import { ConnectedApps } from "../../settings/connected-apps";
import { PageHeader } from "../../ui/kit";
import { WorkspaceAccessContext } from "../../workspace-access";

const OWNER = "00000000-0000-4000-8000-000000000001";
const TENANT = "00000000-0000-4000-8000-000000000004";
const SESSION = "00000000-0000-4000-8000-000000000005";
const MINUTE = 60_000;

type State = "new" | "off" | "live";

const REVIEW = {
  state: "pending",
  since: "2026-10-19",
  worksNow:
    "Until Meta approves Sales Xray, only Pages run by people added to our Meta app as testers can connect. Ask us to add you as a tester.",
  after: "Once Meta approves it, any business can connect its own Pages here.",
};

const at = (minutes: number) =>
  new Date(Date.now() + minutes * MINUTE).toISOString();

function pages(state: State) {
  if (state === "new") return [];
  const offers = {
    pageId: "910000000000002",
    name: "Fictional Homes Offers",
    active: false,
    forms: "all",
    received: 0,
    formsCovered: [],
  };
  if (state === "off")
    return [{ ...offers, pageId: "910000000000001", name: "Fictional Homes" }];
  return [
    {
      pageId: "910000000000001",
      name: "Fictional Homes",
      active: true,
      forms: ["f-1"],
      received: 14,
      lastPulledAt: at(-4),
      formsCovered: [
        { id: "f-1", name: "Site visit request", status: "ACTIVE" },
      ],
    },
    offers,
  ];
}

function health(state: State) {
  const shared = pages(state);
  const live = state === "live";
  return {
    checkedAt: at(0),
    apps: [
      {
        app: "meta_leads",
        name: "Facebook & Instagram lead ads",
        state: live ? "ready" : "not_connected",
        words: live
          ? "1 Page connected."
          : "Bring in the leads from your Facebook and Instagram lead ads as they arrive.",
        configured: true,
        connect: { method: "GET", path: "/v1/lead-desk/meta/connect" },
        connections: shared.map((page) => ({
          id: page.pageId,
          label: page.name,
          detail: page.active ? `Forms: 1 · ${page.received} leads` : null,
          state: page.active ? "ready" : "off",
          words: page.active ? null : "Switched off.",
          disconnect: {
            method: "POST",
            path: `/v1/lead-desk/meta/pages/${page.pageId}/disconnect`,
          },
        })),
        lastEvent: live
          ? { at: at(-12), kind: "lead", words: "New lead from Meta" }
          : null,
        nextPullAt: live ? at(6) : null,
        tests: live
          ? [
              {
                kind: "test_lead",
                label: "Send a test lead",
                needs: ["pageId", "formId"],
              },
            ]
          : [],
        review: REVIEW,
      },
      {
        app: "google_ads",
        name: "Google Ads lead forms",
        state: "not_connected",
        words: "Not connected.",
        configured: true,
        connect: { method: "GET", path: "/v1/lead-desk/google/connect" },
        tests: [],
      },
      {
        app: "lead_stages",
        name: "Lead stages to your ad platforms",
        state: "not_connected",
        words: "Not connected yet.",
        configured: true,
        page: "/leads?tab=stages",
        tests: [],
      },
      {
        app: "whatsapp",
        name: "WhatsApp",
        state: "not_connected",
        words: "Not connected.",
        configured: true,
        connect: { method: "GET", path: "/v1/lead-desk/whatsapp/start" },
        tests: [],
      },
      {
        app: "phone_calls",
        name: "Phone call logging (Sales Xray app)",
        state: "ready",
        words: "2 phones log calls.",
        configured: true,
        tests: [{ kind: "report", label: "Check the phones", needs: [] }],
      },
    ],
  };
}

const FORMS = [
  { id: "f-1", name: "Site visit request", status: "ACTIVE" },
  { id: "f-2", name: "Price list download", status: "ACTIVE" },
  { id: "f-3", name: "Diwali offer", status: "ARCHIVED" },
];

function answer(path: string, state: State): unknown {
  if (path === "/v1/lead-desk/integrations/health") return health(state);
  if (path === "/v1/lead-desk/meta/status")
    return { configured: true, pages: pages(state) };
  if (/^\/v1\/lead-desk\/meta\/pages\/[^/]+\/forms$/.test(path)) return FORMS;
  if (path === "/v1/me/sign-in-methods") return { methods: [], available: [] };
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

function chosen(): State {
  const state =
    typeof window === "undefined"
      ? null
      : new URLSearchParams(window.location.search).get("state");
  return state === "off" || state === "live" ? state : "new";
}

function install() {
  if (typeof window === "undefined") return true;
  const real = window.fetch.bind(window);
  const state = chosen();
  window.fetch = async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
    const body =
      (init?.method ?? "GET") === "GET" ? answer(path, state) : undefined;
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

const pick = (selector: string, text?: string) =>
  Array.from(document.querySelectorAll<HTMLElement>(selector)).find(
    (item) => !text || item.textContent?.trim() === text,
  );

/** `&tap=open|forms`: the sheet (and the forms) open by themselves. */
function useTap() {
  useEffect(() => {
    const tap = new URLSearchParams(window.location.search).get("tap");
    if (tap !== "open" && tap !== "forms") return;
    const steps: (() => void)[] = [
      () =>
        pick('[data-app="meta_leads"] button', "Set up")?.click() ??
        pick('[data-app="meta_leads"] button', "Manage")?.click(),
    ];
    if (tap === "forms")
      steps.push(
        () =>
          (
            pick('dialog [aria-label="Facebook Pages"] button', "Turn on") ??
            pick('dialog [aria-label="Facebook Pages"] button', "Forms")
          )?.click(),
        () =>
          document
            .querySelectorAll<HTMLInputElement>('dialog input[type="radio"]')[1]
            ?.click(),
        () =>
          document
            .querySelector<HTMLInputElement>('dialog input[type="checkbox"]')
            ?.click(),
      );
    const timers = steps.map((step, index) =>
      window.setTimeout(step, 500 + index * 200),
    );
    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, []);
}

function Preview() {
  useState(install);
  useTap();
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
      <AcquisitionShell authenticated active="account" pageName="Settings">
        <div style={{ display: "grid", gap: 16, padding: 16 }}>
          <PageHeader title="Connected apps" />
          <ConnectedApps />
        </div>
      </AcquisitionShell>
    </WorkspaceAccessContext.Provider>
  );
}

export function MetaConnectPreview() {
  return (
    <Suspense fallback={null}>
      <Preview />
    </Suspense>
  );
}
