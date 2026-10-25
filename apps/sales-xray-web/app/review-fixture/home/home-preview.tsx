"use client";

/**
 * Home in an organisation with fictional sellers and leads, for screenshots
 * on GitHub (wb-ci --visual). Lead Desk reads are answered here; nothing
 * leaves the browser. `?role=owner` (default): how sales are going, sellers,
 * open leads by stage, then call analysis. `?role=seller`: today's calls.
 * `&quiet=1`: a seller with nobody to call now and nothing done today (My day's
 * fallback: what is next, this week beside last week). `&none=1`: a seller with
 * no leads yet, while the team has open ones. `&targets=0`: no targets, so
 * today's numbers sit beside yesterday's. Owners see Needs you (two leads past
 * the first-response target, two with no owner) and Team | My day
 * (`?view=mine`). `&pipelines=2`: two pipelines, each with its own stages, and
 * a switch above the open leads by stage. Owners also see Targets (two sellers
 * with targets, one without) and can share out leads from My day (`&none=1`).
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

type Mode = { quiet: boolean; none: boolean; targets: boolean };

const BECAUSE: Record<string, string[]> = {
  due: ["promised a call back", "1 h overdue"],
  new: ["new lead, 12 min waiting"],
  retry: ["due in 30 min", "far along"],
  later: ["due in 1 h 30 min"],
};

/** My day (Lead OS's team engine): ranked work with why, targets, fallback. */
function myDay(now: number, mode: Mode) {
  const empty = mode.quiet || mode.none;
  return {
    schema: "lead-desk/1",
    person_id: SELLER,
    do_now: empty
      ? []
      : queue(now).map((row, index) => ({
          lead_id: row.lead_id,
          lead_name: row.name,
          task_id: null,
          due_at: row.next_action_at,
          score: 1 - index / 10,
          because: BECAUSE[String(row.why_kind)] ?? [],
        })),
    today: empty ? {} : { calls: 18, connects: 7, follow_ups: 5 },
    progress:
      empty || !mode.targets
        ? []
        : (
            [
              ["calls", "day", 40, 18, 26, true, 8],
              ["connects", "day", 15, 7, 9.75, false, 0],
              ["follow_ups", "day", 5, 5, 3.25, false, 0],
              ["meetings", "week", 6, 2, 3, true, 1],
            ] as const
          ).map(([metric, period, target, done, expected, behind, short]) => ({
            metric,
            period,
            target,
            done,
            pace: 0.65,
            expected,
            behind,
            short,
          })),
    fallback: mode.quiet
      ? {
          next_up: queue(now)
            .slice(2, 5)
            .map((row, index) => ({
              lead_id: row.lead_id,
              lead_name: row.name,
              at: new Date(now + (14 + index * 2) * 60 * MINUTE).toISOString(),
              what: index === 1 ? "Meeting" : "Call",
            })),
          week: { calls: 64, connects: 29, follow_ups: 12, meetings: 3 },
          last_week: { calls: 58, connects: 22, follow_ups: 15, meetings: 3 },
          recent: [],
        }
      : null,
  };
}

const REPS = [
  [SELLER, "kavya fictional", 21, 40, true],
  [SECOND, "RAHUL EXAMPLE", 26, 40, true],
  [THIRD, "priya sample", 12, 30, false],
].map(([person_id, name, open_leads, max_open, available]) => ({
  person_id,
  name,
  role: "member",
  revision: 1,
  available,
  max_open,
  languages: [],
  areas: [],
  interests: [],
  open_leads,
  due_now: 2,
  calls_today: 9,
  connected_today: 4,
}));

const progress = (
  metric: string,
  target: number,
  done: number,
  behind: boolean,
) => ({
  metric,
  period: "day",
  target,
  done,
  pace: 0.65,
  expected: target * 0.65,
  behind,
  short: behind ? Math.ceil(target * 0.65 - done) : 0,
});

/** The team engine: the team, targets, and a share-out plan (no lead names). */
function teamAnswers(path: string): unknown {
  if (path === "/v1/lead-desk/team")
    return {
      reps: REPS,
      settings: {
        revision: 3,
        auto_reassign: false,
        reassign_minutes: 10,
        default_country: "IN",
        nudges: true,
        nudges_off_for: [THIRD],
      },
      by_stage: {},
      by_source: {},
      unassigned: 40,
      waiting_first_call: 2,
    };
  if (path === "/v1/lead-desk/targets/team")
    return {
      schema: "lead-desk/1",
      sellers: [
        {
          person_id: SELLER,
          targets: [],
          progress: [
            progress("calls", 40, 18, true),
            progress("connects", 15, 7, false),
            progress("meetings", 2, 2, false),
          ],
        },
        {
          person_id: SECOND,
          targets: [],
          progress: [progress("calls", 40, 31, false)],
        },
      ],
    };
  if (path === "/v1/lead-desk/leads/distribute")
    return {
      rule: "even",
      preview: true,
      leads: 40,
      moved: 38,
      given: REPS.filter((rep) => rep.available).map((rep) => ({
        person_id: rep.person_id,
        name: rep.name,
        leads: 19,
        open_after: Number(rep.open_leads) + 19,
        max_open: rep.max_open,
      })),
      left: { closed: 2 },
      sources: { "Facebook ad": 28, Website: 9, "Walk-in": 3 },
      cities: { Pune: 22, Mumbai: 18 },
      more: false,
      words: "38 leads given out evenly: 19 each to 2 sellers.",
    };
  return null;
}

function answers(now: number, path: string, mode: Mode): unknown {
  const { quiet, none } = mode;
  const empty = quiet || none;
  const team = teamAnswers(path);
  if (team !== null) return team;
  if (path === "/v1/lead-desk/my-day") return myDay(now, mode);
  if (path === "/v1/lead-desk")
    return {
      me: {
        person_id: SELLER,
        name: "swamini fictional",
        role: "member",
        // An owner's own desk manages the team (Share out leads on My day).
        can_manage:
          typeof window !== "undefined" &&
          new URLSearchParams(window.location.search).get("role") !== "seller",
        taking_leads: true,
      },
      numbers: empty
        ? {
            calls: 0,
            connected: 0,
            talk_seconds: 0,
            follow_ups_done: 0,
            new_assigned: 0,
          }
        : {
            calls: 18,
            connected: 7,
            talk_seconds: 3_120,
            follow_ups_done: 5,
            new_assigned: 3,
          },
      numbers_yesterday: {
        calls: 22,
        connected: 9,
        talk_seconds: 3_900,
        follow_ups_done: 4,
        new_assigned: 2,
      },
      numbers_week: {
        calls: 64,
        connected: 29,
        talk_seconds: 11_400,
        follow_ups_done: 12,
        new_assigned: 9,
      },
      team_pool: { open: 382, unassigned: 40, may_take: true },
      counts: {
        open: none ? 0 : 21,
        new: 1,
        follow_up_due: 2,
        not_connected: 1,
        later_today: 2,
        // Owners: two new leads nobody has yet (Needs you).
        unassigned: 2,
        overdue: 1,
      },
      queue: empty ? [] : queue(now),
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

function install(mode: Mode) {
  if (typeof window === "undefined") return true;
  const real = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    const path = url.replace(/^https?:\/\/[^/]+/, "");
    const body = path.startsWith("/v1/")
      ? answers(Date.now(), path, mode)
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
  const analysis = params.get("analysis") === "1";
  useState(() =>
    install({
      quiet: params.get("quiet") === "1",
      none: params.get("none") === "1",
      targets: params.get("targets") !== "0",
    }),
  );
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
