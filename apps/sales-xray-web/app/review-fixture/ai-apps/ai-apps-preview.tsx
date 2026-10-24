"use client";

/**
 * Settings → AI apps with fictional connections, for screenshots on GitHub
 * (wb-ci --visual). Its reads are answered here and nothing leaves the browser.
 * Default: Pulse (checked, in a fictional organisation) and ChatGPT (used today,
 * Personal). `?state=none`: nothing connected yet. `&tap=disconnect` opens the
 * confirm for ChatGPT by itself.
 */

import { Suspense, useEffect, useState } from "react";

import { AcquisitionShell } from "../../acquisition-shell";
import { AiAppsSection } from "../../settings/ai-apps";
import { SettingsShell } from "../../settings/settings-shell";
import { FixtureWorkspace } from "../leads/leads-preview";

const PERSONAL = "00000000-0000-4000-8000-0000000000b1";
const HOMES = "00000000-0000-4000-8000-000000000004";
const MINUTE = 60_000;
const at = (minutes: number) =>
  new Date(Date.now() + minutes * MINUTE).toISOString();

function connections() {
  const none =
    typeof window !== "undefined" &&
    new URLSearchParams(window.location.search).get("state") === "none";
  if (none) return [];
  return [
    {
      id: "00000000-0000-4000-8000-0000000000c1",
      app: "ChatGPT",
      client_id: "sxc_fictional_chatgpt",
      scopes: ["calls:read", "reports:read", "leads:read", "leads:write"],
      granted_by_person_id: PERSONAL,
      created_at: at(-3 * 24 * 60),
      last_used_at: at(-25),
      revoked_at: null,
      tenant_id: PERSONAL,
      verified: false,
      maker: null,
    },
    {
      id: "00000000-0000-4000-8000-0000000000c2",
      app: "Pulse",
      client_id: "sxc_fictional_pulse",
      scopes: ["calls:read", "reports:read", "leads:read"],
      granted_by_person_id: PERSONAL,
      created_at: at(-9 * 24 * 60),
      last_used_at: at(-26 * 60),
      revoked_at: null,
      tenant_id: HOMES,
      verified: true,
      maker: "Estate Autopilots",
    },
  ];
}

const WORKSPACES = {
  selected_tenant_id: HOMES,
  workspaces: [
    {
      tenant_id: PERSONAL,
      kind: "personal",
      name: "Personal",
      role: null,
      sales_xray_enabled: true,
    },
    {
      tenant_id: HOMES,
      kind: "organisation",
      name: "Fictional Homes",
      role: "owner",
      sales_xray_enabled: true,
    },
  ],
};

function install() {
  if (typeof window === "undefined") return true;
  const earlier = window.fetch.bind(window);
  let apps = connections();
  const json = (body: unknown) =>
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  window.fetch = async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
    if (path === "/v1/me/connected-apps") return json({ apps });
    if (path === "/v1/me/sales-xray-workspaces") return json(WORKSPACES);
    const revoke = path.match(/^\/v1\/me\/connected-apps\/([^/]+)\/revoke$/);
    if (revoke && init?.method === "POST") {
      apps = apps.filter((app) => app.id !== revoke[1]);
      return json({ apps });
    }
    return earlier(input, init);
  };
  return true;
}

/** `&tap=disconnect`: the confirm opens by itself, for its screenshot. */
function useTap() {
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("tap") !== "disconnect")
      return;
    const timer = window.setTimeout(() => {
      Array.from(document.querySelectorAll<HTMLButtonElement>("li button"))
        .find((item) => item.textContent?.trim() === "Disconnect")
        ?.click();
    }, 600);
    return () => window.clearTimeout(timer);
  }, []);
}

function Preview() {
  useState(install);
  useTap();
  return (
    <AcquisitionShell
      authenticated
      homeHref="/"
      active="account"
      pageName="Settings"
      mobileFit={false}
    >
      <SettingsShell>
        <AiAppsSection />
      </SettingsShell>
    </AcquisitionShell>
  );
}

export function AiAppsPreview() {
  return (
    <FixtureWorkspace>
      <Suspense fallback={null}>
        <Preview />
      </Suspense>
    </FixtureWorkspace>
  );
}
