"use client";

/**
 * The real Leads page with a fictional organisation, for screenshots on GitHub
 * (wb-ci --visual). Lead Desk reads are answered here; nothing leaves the
 * browser. Names arrive in lower case on purpose: the page shows them with
 * capitals. `?tab=all&stage=…|team|sources|stages` opens that view, as on
 * /leads; `&tap=menu` then opens the ⋯ menu by itself.
 */

import { Suspense, useEffect, useState } from "react";

import { LeadsRoute } from "../../leads/leads-page";
import { WorkspaceAccessContext } from "../../workspace-access";

const OWNER = "00000000-0000-4000-8000-000000000001";
const SELLER = "00000000-0000-4000-8000-000000000002";
const SECOND = "00000000-0000-4000-8000-000000000003";
const TENANT = "00000000-0000-4000-8000-000000000004";
const SESSION = "00000000-0000-4000-8000-000000000005";
const MINUTE = 60_000;

type Stage =
  | "new"
  | "not_connected"
  | "follow_up"
  | "interested"
  | "won"
  | "lost";

const LEADS: [string, string | null, string | null, Stage, string, string][] = [
  ["asha fictional", "Pune", "2 BHK", "new", "New", "due"],
  ["RAVI SAMPLE", "Mumbai", "Site visit", "follow_up", "Follow up", "due"],
  [
    "meera fictional",
    "Nashik",
    "Plot",
    "not_connected",
    "Not contacted",
    "retry",
  ],
  [
    "karan example",
    "Pune",
    "Office space",
    "interested",
    "Interested",
    "later",
  ],
  ["neha fictional", "Thane", "Villa", "new", "New", "new"],
  ["sample buyer", null, null, "follow_up", "Follow up", "later"],
  ["priya example", "Pune", "3 BHK", "won", "Won", "closed"],
  ["amit fictional", "Nagpur", "Shop", "lost", "Lost", "closed"],
];

function rows(now: number) {
  return LEADS.map(([name, city, interest, stage, label, why], index) => ({
    lead_id: `00000000-0000-4000-8000-0000000003${String(index).padStart(2, "0")}`,
    revision: 1,
    name,
    company: null,
    city,
    language: null,
    interest,
    phone_last4: "3210",
    stage,
    stage_label: label,
    source: index % 2 ? "meta" : "manual",
    source_label: index % 2 ? "Facebook ad" : "Added by hand",
    owner_person_id: index % 3 ? SELLER : SECOND,
    owner_name: index % 3 ? "swamini fictional" : "rahul example",
    why: why === "due" ? "Call back now" : why === "new" ? "New" : "Later",
    why_kind: why,
    next_action_at: new Date(now + (index - 2) * 30 * MINUTE).toISOString(),
    created_at: new Date(now - index * 90 * MINUTE).toISOString(),
    attempts: index % 3,
    calls: index % 4,
    last_result: null,
    last_result_label: null,
    test_data: false,
    overdue: index === 1,
  }));
}

function answers(now: number, path: string): unknown {
  const all = rows(now);
  if (path === "/v1/lead-desk")
    return {
      me: {
        person_id: OWNER,
        name: "priya owner",
        role: "owner",
        can_manage: true,
        taking_leads: true,
        paused_until: null,
      },
      numbers: {
        calls: 14,
        connected: 6,
        talk_seconds: 2_460,
        follow_ups_done: 3,
        new_assigned: 4,
      },
      counts: {
        open: 6,
        new: 2,
        follow_up_due: 2,
        not_connected: 1,
        later_today: 2,
        unassigned: 1,
        overdue: 1,
        call_back: 0,
      },
      queue: all.filter((row) => row.why_kind !== "closed"),
      call_mode: "phone",
      sandbox: false,
      generated_at: new Date(now).toISOString(),
      upcoming: [],
      templates: [],
      call_back: [],
    };
  if (path.startsWith("/v1/lead-desk/leads?")) {
    const params = new URLSearchParams(path.split("?")[1]);
    const stage = params.get("stage");
    const leads = all.filter((row) =>
      !stage || stage === "open"
        ? row.stage !== "won" && row.stage !== "lost"
        : row.stage === stage,
    );
    const stage_counts: Record<string, number> = {};
    for (const row of all)
      stage_counts[row.stage] = (stage_counts[row.stage] ?? 0) + 1;
    return { leads, total: leads.length, next_offset: null, stage_counts };
  }
  if (path === "/v1/lead-desk/journey")
    return {
      version: 2,
      industry: "real_estate",
      savedAt: null,
      savedBy: null,
      canEdit: true,
      kinds: {},
      meanings: {},
      stages: (
        [
          ["Enquiry", "new"],
          ["Not reachable", "not_connected"],
          ["Call back", "follow_up"],
          ["Site visit booked", "interested"],
          ["Booked", "won"],
          ["Not interested", "lost"],
        ] as const
      ).map(([label, kind], index) => ({
        key: `step_${index}`,
        label,
        kind,
        kindWords: "",
        milestone: "",
        meaning: "",
        archived: false,
        origin: "",
        leads: 1,
      })),
    };
  if (path === "/v1/lead-desk/team")
    return {
      reps: [
        ["swamini fictional", SELLER, 38, 6, 22, 9],
        ["rahul example", SECOND, 21, 2, 11, 4],
      ].map(([name, id, open, due, calls, connected]) => ({
        person_id: id,
        name,
        role: "member",
        revision: 1,
        available: true,
        max_open: 50,
        languages: ["Marathi", "Hindi"],
        areas: ["Pune"],
        interests: [],
        open_leads: open,
        due_now: due,
        calls_today: calls,
        connected_today: connected,
        first_call_minutes: 6,
        phone: null,
      })),
      settings: {
        revision: 3,
        auto_reassign: false,
        reassign_minutes: 10,
        default_country: "91",
        work_hours: null,
      },
      by_stage: { new: 2, follow_up: 2, interested: 1 },
      by_source: { meta: 4, manual: 4 },
      unassigned: 1,
      waiting_first_call: 1,
      first_call_minutes: 6,
    };
  if (path === "/v1/lead-desk/journey/templates") return [];
  if (path === "/v1/lead-desk/journey/suggestions") return [];
  if (path === "/v1/lead-desk/journey/ads")
    return {
      version: 1,
      providers: [],
      recent: [],
      settling: 0,
      sendsAt: null,
    };
  if (path === "/v1/lead-desk/sources")
    return { sources: [], meta: "not_configured" };
  return null;
}

function install() {
  if (typeof window === "undefined") return true;
  const real = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    const body = path.startsWith("/v1/") ? answers(Date.now(), path) : null;
    if (body !== null)
      return new Response(JSON.stringify(body), {
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

/** `&tap=menu`: the ⋯ menu opens by itself once the page has drawn. */
function useTap() {
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("tap") !== "menu")
      return;
    const timer = window.setTimeout(
      () =>
        document
          .querySelector<HTMLButtonElement>(
            'button[aria-label="Leads settings"]',
          )
          ?.click(),
      600,
    );
    return () => window.clearTimeout(timer);
  }, []);
}

export function LeadsPreview() {
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
      <Suspense fallback={null}>
        <LeadsRoute />
      </Suspense>
    </WorkspaceAccessContext.Provider>
  );
}
