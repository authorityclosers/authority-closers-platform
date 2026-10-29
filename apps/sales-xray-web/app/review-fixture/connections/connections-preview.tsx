"use client";

/**
 * Organisation → Connections with every part answered, for screenshots and
 * the real-phone check (owner, 29 Oct 2026: "overflow and artifacts on
 * developers page, AI reply, Claude and other apps not having clean UI and
 * icons, the Pulse connection"): /review-fixture/connections?tab=connections
 * &part=apps|ai-replies|developers|pulse, as on /organisation. Pulse is linked
 * to a fictional Pulse org with fictional people; `&pulsestate=unlinked` shows the
 * connect card and `&pulsestate=hidden` the organisation Pulse isn't offered to.
 * Its reads are answered in the browser; nothing leaves it.
 */

import { Suspense, useState } from "react";

import { OrganisationHub } from "../../organisation/org-hub";
import { OrganisationFixture } from "../_fixtures/organisation-fixture";
import { DevelopersAnswers } from "../developers/developers-preview";
import { FixtureWorkspace } from "../leads/leads-preview";

const MINUTE = 60_000;
const at = (minutes: number) =>
  new Date(Date.now() + minutes * MINUTE).toISOString();

function pulseState(mode: string | null) {
  const members = [
    {
      id: "pm1",
      name: "Asha Fictional",
      email: "asha@fictional-homes.example",
      title: "Sales lead",
      team: "North",
      pulse_role: "admin",
      status: "active",
      person_id: "00000000-0000-4000-8000-000000000001",
      matched_by: "pulse_sign_in",
      can_invite: false,
    },
    {
      id: "pm2",
      name: "Ravi Example",
      email: "ravi@fictional-homes.example",
      title: "Seller",
      team: "North",
      pulse_role: "member",
      status: "active",
      person_id: "00000000-0000-4000-8000-000000000002",
      matched_by: "email",
      can_invite: false,
    },
    {
      id: "pm3",
      name: "Meera Sample",
      email: "meera@fictional-homes.example",
      title: "Seller",
      team: "South",
      pulse_role: "member",
      status: "active",
      person_id: null,
      matched_by: null,
      can_invite: true,
    },
  ];
  return {
    schema: "sx-pulse/1",
    configured: true,
    link:
      mode === "unlinked"
        ? null
        : {
            pulse_org_id: "pulse-fictional",
            pulse_org_name: "Fictional Homes office",
            linked_at: at(-6 * 24 * 60),
            linked_by: "Asha Fictional",
            scopes: [],
            sharing: { photos: "read", signals: "off" },
            webhooks: true,
            last_sync_at: at(-12),
            last_sync: { seen: 3, matched: 2, missing: 1 },
          },
    members: mode === "unlinked" ? [] : members,
    pulse_access: [
      {
        id: "pa1",
        scopes: ["calls:read", "leads:read"],
        created_at: at(-9 * 24 * 60),
        last_used_at: at(-80),
        revoked_at: null,
      },
    ],
  };
}

function install() {
  if (typeof window === "undefined") return true;
  const earlier = window.fetch.bind(window);
  const mode = new URLSearchParams(window.location.search).get("pulsestate");
  window.fetch = async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    const path = url.replace(/^https?:\/\/[^/]+/, "").split("?")[0];
    if ((init?.method ?? "GET") === "GET" && path === "/v1/sales-xray/pulse")
      return mode === "hidden"
        ? new Response(null, { status: 404 })
        : new Response(JSON.stringify(pulseState(mode)), {
            status: 200,
            headers: { "content-type": "application/json" },
          });
    return earlier(input, init);
  };
  return true;
}

function PulseAnswers() {
  useState(install);
  return null;
}

export function ConnectionsPreview() {
  return (
    <FixtureWorkspace>
      <Suspense fallback={null}>
        <OrganisationFixture>
          {/* Inside the others, so these answers come first. */}
          <DevelopersAnswers />
          <PulseAnswers />
          <OrganisationHub base="/review-fixture/connections" />
        </OrganisationFixture>
      </Suspense>
    </FixtureWorkspace>
  );
}
