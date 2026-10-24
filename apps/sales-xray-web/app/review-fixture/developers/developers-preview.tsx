"use client";

/**
 * Organisation → Connections → Developers with fictional keys, a webhook, an
 * app and connections, for screenshots on GitHub (wb-ci --visual). Its reads
 * are answered here and nothing leaves the browser. `?state=new`: nothing set
 * up yet.
 */

import { Suspense, useState } from "react";

import { AcquisitionShell } from "../../acquisition-shell";
import { DevelopersSection } from "../../settings/developers";
import { SettingsShell } from "../../settings/settings-shell";
import { OrganisationFixture } from "../_fixtures/organisation-fixture";
import { FixtureWorkspace } from "../leads/leads-preview";

const MINUTE = 60_000;
const DAY = 24 * 60;
const at = (minutes: number) =>
  new Date(Date.now() + minutes * MINUTE).toISOString();

function overview(origin: string, fresh: boolean) {
  const menu = {
    events: [
      { key: "analysis.completed", label: "A call's analysis is ready" },
      { key: "lead.created", label: "A lead is added" },
      { key: "lead.stage_changed", label: "A lead moves to another stage" },
    ],
    facts_profiles: [],
  };
  const base = {
    schema: "sx-integrations/1",
    api_base: `${origin}/v1/api`,
    key_mode: "test",
    scopes: [
      { key: "calls:read", label: "Read calls and their status" },
      { key: "reports:read", label: "Read call reports and their facts" },
      { key: "leads:read", label: "Read leads" },
      { key: "leads:write", label: "Create and update leads" },
      { key: "webhooks:manage", label: "Manage webhooks" },
    ],
    expiry_days: [30, 90, 365],
    webhooks_ready: true,
    webhook_menu: menu,
    handover: null,
    handover_menu: null,
  };
  if (fresh)
    return { ...base, keys: [], webhook: null, apps: [], connections: [] };
  return {
    ...base,
    keys: [
      {
        id: "k1",
        name: "Our CRM",
        prefix: "sxk_test_Ab12",
        scopes: ["calls:read", "leads:write"],
        state: "active",
        created_at: at(-12 * DAY),
        created_by_person_id: "p1",
        expires_at: at(78 * DAY),
        last_used_at: at(-40),
        revoked_at: null,
      },
      {
        id: "k2",
        name: "Sheet sync",
        prefix: "sxk_test_Zx90",
        scopes: ["leads:read"],
        state: "revoked",
        created_at: at(-40 * DAY),
        created_by_person_id: "p1",
        expires_at: null,
        last_used_at: at(-5 * DAY),
        revoked_at: at(-3 * DAY),
      },
    ],
    webhook: {
      id: "w1",
      url: "https://hooks.fictional-homes.example/sales-xray",
      host: "hooks.fictional-homes.example",
      events: ["analysis.completed", "lead.created"],
      facts_profile: null,
      managed_in_app: true,
      secret_hint: "whsec_…9f2a",
      rotating: false,
      next_secret_hint: null,
      created_at: at(-10 * DAY),
    },
    apps: [
      {
        id: "a1",
        client_id: "sxc_fictional_portal",
        name: "Fictional Homes portal",
        redirect_uris: ["https://portal.fictional-homes.example/callback"],
        confidential: true,
        created_at: at(-20 * DAY),
        revoked_at: null,
      },
    ],
    connections: [
      {
        id: "g1",
        app: "Pulse",
        client_id: "sxc_fictional_pulse",
        scopes: ["calls:read", "leads:read"],
        created_at: at(-9 * DAY),
        last_used_at: at(-60),
        revoked_at: null,
      },
      {
        id: "g2",
        app: "ChatGPT",
        client_id: "sxc_fictional_chatgpt",
        scopes: ["calls:read", "reports:read", "leads:read"],
        created_at: at(-2 * DAY),
        last_used_at: null,
        revoked_at: null,
      },
    ],
  };
}

const DELIVERIES = [
  {
    id: "d1",
    event_type: "lead.created",
    status: "delivered",
    attempts: 1,
    last_http_status: 204,
    last_error_code: null,
    created_at: at(-15),
    delivered_at: at(-15),
  },
  {
    id: "d2",
    event_type: "analysis.completed",
    status: "delivered",
    attempts: 2,
    last_http_status: 200,
    last_error_code: null,
    created_at: at(-3 * 60),
    delivered_at: at(-3 * 60 + 1),
  },
];

function install() {
  if (typeof window === "undefined") return true;
  const earlier = window.fetch.bind(window);
  const fresh =
    new URLSearchParams(window.location.search).get("state") === "new";
  const json = (body: unknown) =>
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  window.fetch = async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
    const get = (init?.method ?? "GET") === "GET";
    if (get && path === "/v1/sales-xray/integrations")
      return json(overview(window.location.origin, fresh));
    if (get && path === "/v1/sales-xray/integrations/webhook/deliveries")
      return json({ deliveries: fresh ? [] : DELIVERIES });
    return earlier(input, init);
  };
  return true;
}

function Preview() {
  useState(install);
  return (
    <AcquisitionShell
      authenticated
      homeHref="/"
      active="account"
      pageName="Settings"
      mobileFit={false}
    >
      <SettingsShell>
        <DevelopersSection />
      </SettingsShell>
    </AcquisitionShell>
  );
}

export function DevelopersPreview() {
  return (
    <FixtureWorkspace>
      <Suspense fallback={null}>
        <OrganisationFixture>
          <Preview />
        </OrganisationFixture>
      </Suspense>
    </FixtureWorkspace>
  );
}
