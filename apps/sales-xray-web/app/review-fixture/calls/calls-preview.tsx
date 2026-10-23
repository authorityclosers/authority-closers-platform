"use client";

/**
 * The real Calls page with a fictional organisation's calls, for screenshots
 * (wb-ci --visual and the design-direction proposal, 22 Oct 2026). The calls
 * list is answered here; nothing leaves the browser. `?empty=1` shows a
 * workspace with no calls yet. Five calls belong to a lead (slice 7).
 */

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";

import { CallsLibrary } from "../../calls-library";
import { WorkspaceAccessContext } from "../../workspace-access";

const OWNER = "00000000-0000-4000-8000-000000000001";
const SELLER = "00000000-0000-4000-8000-000000000002";
const SECOND = "00000000-0000-4000-8000-000000000003";
const TENANT = "00000000-0000-4000-8000-000000000004";
const SESSION = "00000000-0000-4000-8000-000000000005";
const MINUTE = 60_000;

type Call = [
  name: string,
  owner: string,
  minutesAgo: number,
  seconds: number,
  state: string,
  report: boolean,
  outcome: string | null,
  assessment: string | null,
];

const CALLS: Call[] = [
  [
    "Site visit · Asha Fictional",
    SELLER,
    35,
    842,
    "completed",
    true,
    "Site visit booked for Saturday",
    "Clear need, budget confirmed, wants a weekend visit.",
  ],
  [
    "Follow-up · Ravi Sample",
    SECOND,
    90,
    515,
    "completed",
    true,
    "Asked for a price sheet on WhatsApp",
    "Interested but comparing two projects.",
  ],
  [
    "First call · Meera Fictional",
    SELLER,
    180,
    1268,
    "completed",
    true,
    "Callback tomorrow at 11 am",
    "Wants a plot near the highway; loan not yet approved.",
  ],
  [
    "Enquiry · Karan Example",
    SECOND,
    240,
    377,
    "processing",
    false,
    null,
    null,
  ],
  [
    "Negotiation · Neha Fictional",
    SELLER,
    1500,
    1910,
    "completed",
    true,
    "Token amount agreed",
    "Ready to book; asked about possession date.",
  ],
  [
    "Cold call · Sample Buyer",
    SECOND,
    2900,
    204,
    "completed",
    true,
    "Not interested right now",
    "Already bought elsewhere; open to referrals.",
  ],
  ["Walk-in · Priya Sample", SELLER, 4300, 655, "ready", false, null, null],
];

/** The lead each call belongs to (slice 7): by the call's place in CALLS. */
const LEADS: Record<number, [name: string, stage: string]> = {
  0: ["asha fictional", "interested"],
  1: ["ravi sample", "follow_up"],
  3: ["karan example", "new"],
  4: ["neha fictional", "won"],
  // A cold call whose name doesn't say whom: the row names the lead.
  5: ["anil example", "lost"],
};

const OWNERS: Record<string, string> = {
  [SELLER]: "Swamini Fictional",
  [SECOND]: "Rahul Example",
};

function page(now: number, empty: boolean) {
  return {
    submissions: empty
      ? []
      : CALLS.map(
          (
            [name, owner, ago, seconds, state, report, outcome, assessment],
            index,
          ) => ({
            submission_id: `00000000-0000-4000-8000-0000000005${String(index).padStart(2, "0")}`,
            created_at: new Date(now - ago * MINUTE).toISOString(),
            duration_seconds: seconds,
            state,
            has_report: report,
            display_name: name,
            display_name_revision: 1,
            owner_person_id: owner,
            owner_name: OWNERS[owner],
            ...(LEADS[index]
              ? {
                  lead: {
                    lead_id: `00000000-0000-4000-8000-0000000006${String(index).padStart(2, "0")}`,
                    name: LEADS[index][0],
                    stage: LEADS[index][1],
                    step: null,
                    pipeline: "main",
                  },
                }
              : {}),
            summary: report
              ? {
                  outcome,
                  assessment,
                  fix_first: null,
                  next_focus: null,
                  strengths: 3,
                  missed: 1,
                }
              : null,
          }),
        ),
    next_cursor: null,
  };
}

function install(empty: boolean) {
  if (typeof window === "undefined") return true;
  const real = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    if (path.startsWith("/v1/conversation/acquisition/submissions?"))
      return new Response(JSON.stringify(page(Date.now(), empty)), {
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

function Preview() {
  const params = useSearchParams();
  const empty = params.get("empty") === "1";
  useState(() => install(empty));
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
      <CallsLibrary insights />
    </WorkspaceAccessContext.Provider>
  );
}

export function CallsPreview() {
  return (
    <Suspense fallback={null}>
      <Preview />
    </Suspense>
  );
}
