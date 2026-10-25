"use client";

/**
 * A fictional organisation for review pages and tutorials (tutorial 09, "Your
 * team and organisation", 23 Oct 2026): Fictional Homes with an owner, an
 * admin, two sellers and one invitation waiting, a verified email domain, and
 * three workspaces to switch between. Its reads and saves are answered in the
 * browser; nothing leaves it. Other reads fall through to whatever answered
 * them before (the Leads fixture's, inside FixtureWorkspace).
 *
 *   ?invite=1          types a fictional address into "Invite people by email"
 *                      and presses Invite, so the question shows
 *   ?switcher=open     opens the workspace switcher
 */

import { useSearchParams } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { WorkspaceAccessContext } from "../../workspace-access";

const OWNER = "00000000-0000-4000-8000-000000000001";
const TENANT = "00000000-0000-4000-8000-000000000004";
const SESSION = "00000000-0000-4000-8000-000000000005";
const OTHER_ORG = "00000000-0000-4000-8000-000000000040";
const PERSONAL = "00000000-0000-4000-8000-000000000041";

const WORKSPACES = [
  {
    tenant_id: TENANT,
    kind: "organisation" as const,
    name: "Fictional Homes",
    role: "owner" as const,
    sales_xray_enabled: true,
  },
  {
    tenant_id: OTHER_ORG,
    kind: "organisation" as const,
    name: "Sample Realty",
    role: "member" as const,
    sales_xray_enabled: true,
  },
  {
    tenant_id: PERSONAL,
    kind: "personal" as const,
    name: "Vikram Example",
    role: null,
    sales_xray_enabled: true,
  },
];

const day = (daysAgo: number, hour = 11) => {
  const at = new Date();
  at.setDate(at.getDate() - daysAgo);
  at.setHours(hour, 0, 0, 0);
  return at.toISOString();
};

const member = (
  personId: string | null,
  name: string | null,
  email: string,
  role: "owner" | "admin" | "member",
  extra: { joined: number; active: number | null; calls: number },
  inviteId: string | null = null,
) => ({
  person_id: personId,
  invite_id: inviteId,
  name,
  email,
  role,
  status: personId ? "active" : "invited",
  joined_at: personId ? day(extra.joined) : null,
  last_active_at: extra.active === null ? null : day(extra.active, 17),
  minutes_used_30d: extra.calls * 6,
  calls_30d: extra.calls,
});

const MEMBERS = [
  member(OWNER, "vikram example", "vikram@fictionalhomes.in", "owner", {
    joined: 120,
    active: 0,
    calls: 14,
  }),
  member(
    "00000000-0000-4000-8000-000000000002",
    "swamini fictional",
    "swamini@fictionalhomes.in",
    "admin",
    { joined: 90, active: 0, calls: 31 },
  ),
  member(
    "00000000-0000-4000-8000-000000000003",
    "rahul example",
    "rahul@fictionalhomes.in",
    "member",
    { joined: 60, active: 1, calls: 22 },
  ),
  member(
    "00000000-0000-4000-8000-000000000006",
    "priya sample",
    "priya@fictionalhomes.in",
    "member",
    { joined: 21, active: 2, calls: 11 },
  ),
  member(
    null,
    null,
    "anil@fictionalhomes.in",
    "member",
    { joined: 0, active: null, calls: 0 },
    "00000000-0000-4000-8000-000000000042",
  ),
];

function install() {
  if (typeof window === "undefined") return true;
  let domains = ["fictionalhomes.in"];
  let autoJoin = true;
  const organisation = () => ({
    tenant_id: TENANT,
    name: "Fictional Homes",
    role: "owner",
    verified_domains: domains,
    auto_join: autoJoin,
    member_count: MEMBERS.filter((item) => item.status === "active").length,
  });
  const failing =
    new URLSearchParams(window.location.search).get("billing") === "fail";
  const ANSWERS: Record<string, () => unknown> = {
    "/v1/me/sales-xray-profile": () => ({
      name: "vikram example",
      email: "vikram@fictionalhomes.in",
      phone_number_e164: null,
      phone_verified: false,
      profile_complete: true,
      revision: 1,
      photo_url: null,
      // Settings -> Profile's own part (25 Oct 2026): a title, the rest to add.
      handle: null,
      title: "Sales manager",
      team: null,
      details_revision: 0,
      avatar_url: null,
      own_photo: false,
      completion: {
        done: 2,
        total: 6,
        missing: ["photo", "handle", "team", "phone"],
      },
    }),
    ...(failing
      ? {}
      : {
          "/v1/conversation/acquisition/session": () => ({
            allowance: {
              allowance_seconds: 36000,
              committed_seconds: 7200,
              available_seconds: 28800,
            },
          }),
        }),
    "/v1/me/sales-xray-workspaces": () => ({
      selected_tenant_id: TENANT,
      workspaces: WORKSPACES,
    }),
    "/v1/organisation": organisation,
    "/v1/organisation/members": () => ({ members: MEMBERS }),
    "/v1/organisation/invites": () => ({ invites: [] }),
    "/v1/organisation/activity": () => ({
      per_day: [],
      per_rep: [],
      members: MEMBERS.filter((item) => item.person_id).map((item) => ({
        person_id: item.person_id,
        calls: item.calls_30d,
        minutes: item.minutes_used_30d,
        reports_ready: Math.round(item.calls_30d / 2),
        last_call_at: item.last_active_at,
      })),
      calls: [],
    }),
    "/v1/organisation/settings": () => ({
      tenant_id: TENANT,
      name: "Fictional Homes",
      legal_name: "Fictional Homes Private Limited",
      gstin: "",
      address: "Baner Road",
      industry: "Real estate",
      team_size: "11-50",
      website: "https://fictionalhomes.in",
      city: "Pune",
      logo_url: null,
    }),
  };
  const before = window.fetch.bind(window);
  const json = (body: unknown, status = 200) =>
    new Response(status === 204 ? null : JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    });
  window.fetch = async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
    const method = (init?.method ?? "GET").toUpperCase();
    if (method === "GET" && path in ANSWERS) return json(ANSWERS[path]());
    if (path === "/v1/organisation/domains" && method === "PUT") {
      const body = JSON.parse(String(init?.body ?? "{}")) as {
        verified_domains?: string[];
        auto_join?: boolean;
      };
      domains = body.verified_domains ?? domains;
      autoJoin = body.auto_join ?? autoJoin;
      return json(organisation());
    }
    // An invitation or a role change: accepted, nothing stored.
    if (path.startsWith("/v1/organisation/members") && method !== "GET")
      return json(null, 204);
    return before(input, init);
  };
  return true;
}

/** Sets a controlled input's value the way typing does. */
function type(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )?.set;
  setter?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

function Actions() {
  const query = useSearchParams();
  const invite = query.get("invite") === "1";
  const switcher = query.get("switcher") === "open";
  // Screenshots can't type or tap on every phone: these do it once.
  useEffect(() => {
    if (!invite && !switcher) return;
    const timer = window.setTimeout(() => {
      if (switcher) {
        const trigger = [
          ...document.querySelectorAll<HTMLButtonElement>("button[aria-label]"),
        ].find((button) => {
          const label = button.getAttribute("aria-label") ?? "";
          const shown = button.offsetParent !== null;
          return (
            shown &&
            (label.startsWith("Current workspace") ||
              label.startsWith("Workspace:"))
          );
        });
        trigger?.click();
      }
      if (invite) {
        const field = document.querySelector<HTMLInputElement>(
          'input[placeholder="Invite people by email"]',
        );
        if (!field) return;
        type(field, "neha@fictionalhomes.in");
        window.setTimeout(() => {
          const send = [
            ...(field.form?.querySelectorAll<HTMLButtonElement>("button") ??
              []),
          ].find((button) => button.textContent?.trim() === "Invite");
          send?.click();
        }, 150);
      }
    }, 900);
    return () => window.clearTimeout(timer);
  }, [invite, switcher]);
  return null;
}

/**
 * Wrap a review page in this to give it the fictional organisation: its
 * workspaces (with you as owner of Fictional Homes) and its answers.
 */
export function OrganisationFixture({ children }: { children: ReactNode }) {
  useState(install);
  return (
    <WorkspaceAccessContext.Provider
      value={{
        status: "ready",
        authenticated: true,
        context: { personId: OWNER, sessionId: SESSION, tenantId: TENANT },
        workspaces: WORKSPACES,
        retry: () => {},
      }}
    >
      {children}
      <Actions />
    </WorkspaceAccessContext.Provider>
  );
}
