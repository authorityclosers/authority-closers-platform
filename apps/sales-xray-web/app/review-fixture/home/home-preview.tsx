"use client";

/**
 * Home in an organisation with fictional sellers and leads, for screenshots
 * on GitHub (wb-ci --visual). Lead Desk reads are answered here; nothing
 * leaves the browser. `?role=owner` (default): how sales are going, sellers,
 * open leads by stage, then call analysis. `?role=seller`: today's calls.
 * `&quiet=1`: a seller with nobody to call now. Owners see Needs you (two leads
 * past the first-response target, two with no owner) and Team | My day (`?view=mine`). `&pipelines=2`: two pipelines,
 * each with its own stages, and a switch above the open leads by stage.
 */

import type { CallActivity, CallSummary } from "../../dashboard/dashboard-data";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";

import { LightboxShell } from "../../shell/lightbox-shell";
import { DashboardBody } from "../../dashboard/dashboard-body";
import { SalesHome } from "../../dashboard/sales-home";
import { WorkspaceAccessContext } from "../../workspace-access";

const OWNER = "00000000-0000-4000-8000-000000000001";
const SELLER = "00000000-0000-4000-8000-000000000002";
const SECOND = "00000000-0000-4000-8000-000000000003";
const THIRD = "00000000-0000-4000-8000-000000000007";
const TENANT = "00000000-0000-4000-8000-000000000004";
const SESSION = "00000000-0000-4000-8000-000000000005";
const MINUTE = 60_000;

function queue(now: number) {
  return [
    ["ravi sample", "Site visit · Mumbai", "due", true],
    ["asha fictional", "2 BHK · Pune", "new", false],
    ["meera fictional", "Plot · Nashik", "retry", false],
    ["karan example", "Office space · Pune", "later", false],
    ["neha fictional", "Villa · Thane", "later", false],
  ].map(([name, interest, why, overdue], index) => ({
    lead_id: `00000000-0000-4000-8000-0000000004${String(index).padStart(2, "0")}`,
    revision: 1,
    name,
    company: null,
    city: null,
    language: null,
    interest,
    phone_last4: "3210",
    stage: why === "new" ? "new" : "follow_up",
    stage_label: why === "new" ? "Enquiry" : "Call back",
    source: "meta",
    source_label: "Facebook ad",
    owner_person_id: SELLER,
    owner_name: "swamini fictional",
    why:
      why === "due"
        ? "Call back now"
        : why === "new"
          ? "New"
          : why === "retry"
            ? "Try again"
            : "Later",
    why_kind: why,
    next_action_at: new Date(now + (index - 1) * 45 * MINUTE).toISOString(),
    created_at: new Date(now - index * 90 * MINUTE).toISOString(),
    attempts: 1,
    calls: 1,
    last_result: null,
    last_result_label: null,
    test_data: false,
    overdue,
  }));
}

function answers(now: number, path: string, quiet: boolean): unknown {
  if (path === "/v1/lead-desk")
    return {
      me: {
        person_id: SELLER,
        name: "swamini fictional",
        role: "member",
        can_manage: false,
        taking_leads: true,
      },
      numbers: {
        calls: 18,
        connected: 7,
        talk_seconds: 3_120,
        follow_ups_done: 5,
        new_assigned: 3,
      },
      counts: {
        open: 21,
        new: 1,
        follow_up_due: 2,
        not_connected: 1,
        later_today: 2,
        // Owners: two new leads nobody has yet (Needs you).
        unassigned: 2,
        overdue: 1,
      },
      queue: quiet ? [] : queue(now),
      upcoming: quiet
        ? [
            {
              ...queue(now)[3],
              next_action_at: new Date(now + 150 * MINUTE).toISOString(),
            },
          ]
        : [],
      call_mode: "phone",
      sandbox: false,
      generated_at: new Date(now).toISOString(),
      templates: [],
    };
  if (path.startsWith("/v1/lead-desk/reports/performance")) {
    const days = Number(new URLSearchParams(path.split("?")[1]).get("days"));
    const scale = days === 1 ? 1 : days === 30 ? 4 : 2;
    return {
      days,
      start: "2026-10-16",
      end: "2026-10-22",
      current: {
        calls: 64 * scale,
        connected: 29 * scale,
        leads_called: 41 * scale,
        interested: 9 * scale,
        won: 3 * scale,
        new_leads: 37 * scale,
        first_call_minutes: 6,
      },
      previous: {
        calls: 58 * scale,
        connected: 22 * scale,
        leads_called: 39 * scale,
        interested: 7 * scale,
        won: 2 * scale,
        new_leads: 40 * scale,
        first_call_minutes: 11,
      },
      sellers: [
        [SELLER, "swamini fictional", 31, 15, 5, 2, 38, 1],
        [SECOND, "RAHUL EXAMPLE", 22, 9, 3, 1, 26, 3],
        [THIRD, "priya sample", 11, 5, 1, 0, 12, 0],
      ].map(
        ([person_id, name, calls, connected, interested, won, open, late]) => ({
          person_id,
          name,
          calls,
          connected,
          interested,
          won,
          open_leads: open,
          late,
        }),
      ),
      pipeline: { new: 12, not_connected: 9, follow_up: 21, interested: 8 },
      pipelines: {
        main: { new: 5, not_connected: 3, follow_up: 9, interested: 6 },
        partner_outreach: {
          new: 7,
          not_connected: 6,
          follow_up: 12,
          interested: 2,
        },
      },
    };
  }
  const two =
    typeof window !== "undefined" &&
    new URLSearchParams(window.location.search).get("pipelines") === "2";
  // Needs you (slice 8): two leads waiting past a 10-minute first response.
  if (path === "/v1/lead-desk/reports/sla")
    return {
      settings: { on: true, minutes: 10, alertManagers: true, targets: [] },
      start: "2026-10-16",
      end: "2026-10-22",
      sellers: [],
      late: [
        {
          leadId: "00000000-0000-4000-8000-000000000301",
          leadName: "meera fictional",
          seller: "rahul example",
          minutesLate: 42,
        },
        {
          leadId: "00000000-0000-4000-8000-000000000302",
          leadName: "karan example",
          seller: "swamini fictional",
          minutesLate: 14,
        },
      ],
    };
  if (path === "/v1/lead-desk/pipelines" && two)
    return {
      pipelines: [
        ["main", "Enquiries", true],
        ["partner_outreach", "Partner outreach", false],
      ].map(([key, name, main], position) => ({
        key,
        name,
        position,
        main,
        sources: main ? [] : ["csv"],
        industry: null,
        leads: 20,
      })),
      sources: { csv: "File imports", manual: "Added by hand" },
      canEdit: true,
    };
  if (path.startsWith("/v1/lead-desk/journey")) {
    const partner = path.endsWith("pipeline=partner_outreach");
    const stages: [string, string][] = partner
      ? [
          ["New", "new"],
          ["Couldn't reach", "not_connected"],
          ["Spoke to owner", "follow_up"],
          ["Interested", "interested"],
          ["Partner signed", "won"],
          ["Not a fit", "lost"],
        ]
      : [
          ["New enquiry", "new"],
          ["Couldn't reach", "not_connected"],
          ["Counselled", "follow_up"],
          ["Session booked", "interested"],
          ["Enrolled", "won"],
          ["Lost", "lost"],
        ];
    return {
      version: 1,
      industry: null,
      savedAt: null,
      savedBy: null,
      canEdit: true,
      kinds: {},
      meanings: {},
      stages: stages.map(([label, kind], index) => ({
        key: `stage_${index}`,
        label,
        kind,
        kindWords: "",
        milestone: "",
        meaning: "",
        archived: false,
        origin: "",
        leads: 0,
      })),
    };
  }
  return null;
}

function install(quiet: boolean) {
  if (typeof window === "undefined") return true;
  const real = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    const body = path.startsWith("/v1/")
      ? answers(Date.now(), path, quiet)
      : null;
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

/** `?analysis=1`: fictional call analysis numbers (24 calls, 3 need a look). */
const FIXTURE_SUMMARY: CallSummary = {
  total: 24,
  processing: 2,
  completed: 19,
  needsAttention: 3,
};

function fixtureActivity(): CallActivity {
  const counts = [
    0, 1, 2, 0, 3, 1, 0, 2, 4, 1, 0, 0, 2, 3, 1, 2, 0, 1, 3, 2, 0, 4, 2, 1, 0,
    2, 3, 1, 2, 1,
  ];
  const today = Date.now();
  const days = counts.map((analysed, index) => ({
    date: new Date(today - (29 - index) * 86_400_000)
      .toISOString()
      .slice(0, 10),
    analysed,
    analysedSeconds: analysed * 540,
  }));
  return {
    timezone: "Asia/Kolkata",
    days,
    analysedLast30Days: counts.reduce((sum, value) => sum + value, 0),
    analysedPrevious30Days: 31,
  };
}

function Preview() {
  const params = useSearchParams();
  const seller = params.get("role") === "seller";
  const quiet = params.get("quiet") === "1";
  const analysis = params.get("analysis") === "1";
  useState(() => install(quiet));
  return (
    <WorkspaceAccessContext.Provider
      value={{
        status: "ready",
        authenticated: true,
        context: {
          personId: seller ? SELLER : OWNER,
          sessionId: SESSION,
          tenantId: TENANT,
        },
        workspaces: [
          {
            tenant_id: TENANT,
            kind: "organisation",
            name: "Fictional Homes",
            role: seller ? "member" : "owner",
            sales_xray_enabled: true,
          },
        ],
        retry: () => {},
      }}
    >
      <LightboxShell active="dashboard" authenticated homeHref="/dashboard">
        <DashboardBody
          team={!seller}
          summary={{
            status: "ready",
            value: analysis ? FIXTURE_SUMMARY : null,
          }}
          activity={{
            status: "ready",
            value: analysis ? fixtureActivity() : null,
          }}
          allowance={{
            status: "ready",
            value: {
              allowance_seconds: 3_600,
              committed_seconds: 1_080,
              available_seconds: 2_520,
            },
          }}
          recent={{ status: "ready", value: [] }}
          sales={<SalesHome manager={!seller} />}
          salesRole={seller ? "seller" : "manager"}
        />
      </LightboxShell>
    </WorkspaceAccessContext.Provider>
  );
}

export function HomePreview() {
  return (
    <Suspense fallback={null}>
      <Preview />
    </Suspense>
  );
}
