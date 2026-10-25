"use client";

/**
 * A salesperson's profile with fictional people, for screenshots on GitHub (wb-ci --visual).
 * The real person page (organisation/people) draws; its reads are answered here and nothing
 * leaves the browser. `?tab=leads` and `?tab=settings` open those tabs.
 */

import { useState } from "react";

import { PersonView } from "../../organisation/people/person-view";
import { WorkspaceAccessContext } from "../../workspace-access";

const OWNER = "00000000-0000-4000-8000-000000000001";
const SELLER = "00000000-0000-4000-8000-000000000002";
const TENANT = "00000000-0000-4000-8000-000000000004";
const SESSION = "00000000-0000-4000-8000-000000000005";
const DAY = 86_400_000;

const member = (overrides: Record<string, unknown>) => ({
  person_id: OWNER,
  invite_id: null,
  name: "Priya Fictional",
  email: "owner@example.test",
  role: "owner",
  status: "active",
  joined_at: "2026-09-01T12:00:00Z",
  last_active_at: "2026-10-20T12:00:00Z",
  minutes_used_30d: 0,
  calls_30d: 0,
  ...overrides,
});

function routes(now: number): Record<string, unknown> {
  const ago = (days: number) => new Date(now - days * DAY).toISOString();
  // ?over=1: a seller past their limit and paused (owner, 25 Oct 2026: "168 / 50").
  const over = new URLSearchParams(window.location.search).get("over") === "1";
  const calls = [
    ["Discovery · Amit, Fictional Interiors", 1, 760],
    ["Follow-up · Neha, Sample Homes", 2, 410],
    [null, 3, 95],
    ["Site visit plan · Karan, Example Realty", 5, 1220],
    ["Pricing · Meera, Fictional Builders", 8, 540],
  ].map(([label, days, seconds], index) => ({
    id: `00000000-0000-4000-8000-0000000000a${index}`,
    owner_person_id: SELLER,
    owner_name: "Asha Fictional",
    label,
    created_at: ago(days as number),
    duration_seconds: seconds,
    state: index === 2 ? "data_only" : "completed",
    has_report: index !== 2,
  }));
  return {
    "/v1/organisation/members": {
      members: [
        member({}),
        member({
          person_id: SELLER,
          name: "Asha Fictional",
          email: "asha@example.test",
          role: "member",
        }),
      ],
    },
    "/v1/organisation/activity?days=84": {
      members: [],
      per_day: [],
      per_rep: [
        {
          person_id: SELLER,
          name: "Asha Fictional",
          calls: 41,
          recorded_minutes: 312.5,
          reports_ready: 33,
        },
      ],
      calls,
    },
    "/v1/lead-desk/team": {
      reps: [
        {
          person_id: SELLER,
          name: "Asha Fictional",
          role: "member",
          revision: 2,
          available: true,
          max_open: 50,
          languages: ["Marathi", "Hindi"],
          areas: ["Pune"],
          interests: ["2 BHK", "Villas"],
          open_leads: 38,
          due_now: 6,
          calls_today: 22,
          connected_today: 9,
          first_call_minutes: 5,
          phone: null,
          ...(over
            ? {
                available: false,
                open_leads: 168,
                over_capacity: 118,
                default_cap: true,
              }
            : {}),
        },
      ],
      settings: {
        revision: 7,
        auto_reassign: false,
        reassign_minutes: 10,
        default_country: "91",
      },
      by_stage: {},
      by_source: {},
      unassigned: 0,
      waiting_first_call: 0,
    },
    "/v1/sales-xray/call-ai": {
      revision: 4,
      default: "full",
      people: [
        { person_id: SELLER, name: "Asha Fictional", level: "data_only" },
      ],
      you: { level: "full", source: "organisation" },
      levels: [
        {
          id: "off",
          name: "Off",
          hint: "Calls are saved and logged on the lead. No AI reads them.",
        },
        {
          id: "data_only",
          name: "Data only",
          hint: "Transcript and lead facts for the CRM, WhatsApp and automations. No report or coaching.",
        },
        {
          id: "auto",
          name: "Auto",
          hint: "Sales X-Ray picks per call. Until call types arrive, every call gets the full report.",
        },
        {
          id: "full",
          name: "Full",
          hint: "The full report and coaching on every call.",
        },
      ],
      can_edit: true,
    },
    "/v1/lead-desk/leads": {
      leads: [
        ["Ravi Fictional", "Pune", "2 BHK", "follow_up", "Follow-up", true],
        ["Meera Fictional", "Pune", "Villa", "interested", "Interested", false],
        ["Sample Buyer", "Nashik", null, "new", "New", false],
        [
          "Karan Fictional",
          "Pune",
          "Office space",
          "not_connected",
          "Not connected",
          false,
        ],
      ].map(([name, city, interest, stage, label, overdue], index) => ({
        lead_id: `00000000-0000-4000-8000-0000000002${String(index).padStart(2, "0")}`,
        name,
        city,
        interest,
        stage,
        stage_label: label,
        source_label: "File upload",
        overdue,
      })),
      total: 38,
      next_offset: 50,
    },
  };
}

function install() {
  if (typeof window === "undefined") return true;
  const answers = routes(Date.now());
  const real = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    const key = Object.keys(answers).find(
      (route) => path === route || path.startsWith(`${route}?`),
    );
    if (key)
      return new Response(JSON.stringify(answers[key]), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    if (path.startsWith("/v1/"))
      return new Response(JSON.stringify({ detail: "Sample data only." }), {
        status: 404,
      });
    return real(input, init);
  };
  return true;
}

export function SellerProfilePreview() {
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
      <PersonView id={SELLER} />
    </WorkspaceAccessContext.Provider>
  );
}
