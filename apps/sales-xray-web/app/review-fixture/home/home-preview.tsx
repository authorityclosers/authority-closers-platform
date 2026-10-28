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
 * `&controls=1`: Team controls open (targets, nudges and who gets them).
 */

import type { CallActivity, CallSummary } from "../../dashboard/dashboard-data";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import type { LibrarySubmission } from "../../acquisition-client";
import { LightboxShell } from "../../shell/lightbox-shell";
import { DashboardBody } from "../../dashboard/dashboard-body";
import { rememberOpened } from "../../dashboard/home-v2";
import { SalesHome } from "../../dashboard/sales-home";
import { WorkspaceAccessContext } from "../../workspace-access";

const OWNER = "00000000-0000-4000-8000-000000000001";

/** `&switcher=1`: more places to switch to, with long fictional names. */
const SWITCHER_WORKSPACES = [
  {
    tenant_id: "00000000-0000-4000-8000-0000000000a1",
    kind: "personal" as const,
    name: "Personal",
    role: null,
    sales_xray_enabled: true,
  },
  {
    tenant_id: "00000000-0000-4000-8000-0000000000a2",
    kind: "organisation" as const,
    name: "Sample Sales Org",
    role: "admin" as const,
    sales_xray_enabled: true,
  },
  {
    tenant_id: "00000000-0000-4000-8000-0000000000a3",
    kind: "organisation" as const,
    name: "Fictional Learning Academy Pune",
    role: "member" as const,
    sales_xray_enabled: true,
  },
];
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
    owner_name: "asha fictional",
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

type Mode = {
  quiet: boolean;
  none: boolean;
  targets: boolean;
  /** `&fresh=1`: a brand-new workspace (Home v2's start). */
  fresh?: boolean;
};

const BECAUSE: Record<string, string[]> = {
  due: ["promised a call back", "1 h overdue"],
  new: ["new lead, 12 min waiting"],
  retry: ["due in 30 min", "far along"],
  later: ["due in 1 h 30 min"],
};

/** My day (Lead OS's team engine): ranked work with why, targets, fallback. */
function myDay(now: number, mode: Mode) {
  const empty = mode.quiet || mode.none || mode.fresh;
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
          targets: [
            { metric: "calls", period: "day", value: 40 },
            { metric: "connects", period: "day", value: 15 },
            { metric: "meetings", period: "day", value: 2 },
          ],
          progress: [
            progress("calls", 40, 18, true),
            progress("connects", 15, 7, false),
            progress("meetings", 2, 2, false),
          ],
        },
        {
          person_id: SECOND,
          targets: [{ metric: "calls", period: "day", value: 40 }],
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

/** Home v2 (27 Oct 2026): this week's own work, as My work reads it. */
type Work = [
  kind: string,
  lead: string,
  minutesAgo: number,
  extra: Record<string, unknown>,
];

const WORK: Work[] = [
  [
    "call",
    "asha fictional",
    14,
    { duration_seconds: 214, direction: "outgoing", via: "phone" },
  ],
  [
    "note",
    "asha fictional",
    12,
    { note: "Wants the site visit on Saturday morning" },
  ],
  [
    "call",
    "ravi sample",
    52,
    { duration_seconds: null, direction: "missed", via: "phone" },
  ],
  [
    "stage",
    "meera fictional",
    75,
    { stage_label: "Site visit booked", from_label: "Interested" },
  ],
  [
    "call",
    "meera fictional",
    95,
    {
      duration_seconds: 1268,
      direction: "outgoing",
      via: "phone",
      recording: true,
      submission_id: "00000000-0000-4000-8000-000000000501",
    },
  ],
  [
    "result",
    "karan example",
    160,
    {
      connected: true,
      reason_label: "Call back later",
      stage_label: "Follow-up",
    },
  ],
  [
    "call",
    "karan example",
    162,
    { duration_seconds: 65, direction: "incoming", via: "phone" },
  ],
  [
    "message",
    "neha fictional",
    1450,
    { channel: "WhatsApp", template_label: "Price sheet" },
  ],
];

function weekWork(now: number) {
  return {
    schema: "lead-desk/1",
    items: WORK.map(([kind, lead, ago, extra], index) => ({
      event_id: `00000000-0000-4000-8000-0000000009${String(index).padStart(2, "0")}`,
      lead_id: `00000000-0000-4000-8000-0000000010${String(index).padStart(2, "0")}`,
      lead_name: lead,
      stage_label: "Interested",
      event: {
        kind,
        at: new Date(now - ago * MINUTE).toISOString(),
        actor_name: "Asha Fictional",
        stage: null,
        stage_label: null,
        reason: null,
        reason_label: null,
        connected: null,
        note: null,
        next_action_at: null,
        owner_name: null,
        previous_owner_name: null,
        allocation_reason: null,
        source_label: null,
        submission_id: null,
        simulated: null,
        duration_seconds: null,
        ...extra,
      },
    })),
    next_before: null,
    counts: { call: 3, note: 1, stage: 1, result: 1, message: 1 },
  };
}

/** The Team view redesign (27 Oct 2026): today's work across the team. */
const TEAM_WORK: Work[] = [
  [
    "call",
    "asha fictional",
    9,
    {
      actor_name: "Asha Fictional",
      duration_seconds: 214,
      direction: "outgoing",
      via: "phone",
    },
  ],
  [
    "assigned",
    "neha fictional",
    21,
    {
      actor_name: null,
      owner_name: "Rahul Example",
      allocation_reason: "rules",
    },
  ],
  [
    "stage",
    "meera fictional",
    44,
    {
      actor_name: "Asha Fictional",
      stage_label: "Site visit booked",
      from_label: "Interested",
    },
  ],
  [
    "call",
    "ravi sample",
    70,
    {
      actor_name: "Rahul Example",
      duration_seconds: null,
      direction: "missed",
      via: "phone",
    },
  ],
  [
    "result",
    "karan example",
    118,
    {
      actor_name: "Rahul Example",
      connected: true,
      reason_label: "Call back later",
      stage_label: "Follow-up",
    },
  ],
  [
    "captured",
    "priya sample",
    150,
    { actor_name: null, source_label: "Website form" },
  ],
];

function teamWork(now: number) {
  const week = weekWork(now);
  return {
    ...week,
    items: TEAM_WORK.map(([kind, lead, ago, extra], index) => ({
      ...week.items[0],
      event_id: `00000000-0000-4000-8000-0000000011${String(index).padStart(2, "0")}`,
      lead_id: `00000000-0000-4000-8000-0000000012${String(index).padStart(2, "0")}`,
      lead_name: lead,
      event: {
        ...week.items[0].event,
        kind,
        at: new Date(now - ago * MINUTE).toISOString(),
        duration_seconds: null,
        direction: null,
        via: null,
        ...extra,
      },
    })),
  };
}

function answers(now: number, path: string, mode: Mode): unknown {
  const { quiet, none, fresh } = mode;
  const empty = quiet || none || fresh;
  const team = teamAnswers(path);
  if (team !== null) return team;
  if (path === "/v1/lead-desk/my-day") return myDay(now, mode);
  if (path.startsWith("/v1/lead-desk/activity?") && path.includes("team=1"))
    return teamWork(now);
  if (path.startsWith("/v1/lead-desk/activity?"))
    return empty
      ? { schema: "lead-desk/1", items: [], next_before: null, counts: {} }
      : weekWork(now);
  if (path === "/v1/lead-desk")
    return {
      me: {
        person_id: SELLER,
        name: "asha fictional",
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
      numbers_week: fresh
        ? {
            calls: 0,
            connected: 0,
            talk_seconds: 0,
            follow_ups_done: 0,
            new_assigned: 0,
          }
        : {
            calls: 64,
            connected: 29,
            talk_seconds: 11_400,
            follow_ups_done: 12,
            new_assigned: 9,
          },
      team_pool: fresh
        ? { open: 0, unassigned: 0, may_take: false }
        : { open: 382, unassigned: 40, may_take: true },
      counts: fresh
        ? {
            open: 0,
            new: 0,
            follow_up_due: 0,
            not_connected: 0,
            later_today: 0,
            unassigned: 0,
            overdue: 0,
          }
        : {
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
        [SELLER, "asha fictional", 31, 15, 5, 2, 38, 1],
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
      daily: fixtureDays(days, {
        calls: 64 * scale,
        connected: 29 * scale,
        interested: 9 * scale,
        won: 3 * scale,
        new_leads: 37 * scale,
      }),
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
          seller: "asha fictional",
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
          ["Not connected", "not_connected"],
          ["Spoke to owner", "follow_up"],
          ["Interested", "interested"],
          ["Partner signed", "won"],
          ["Not a fit", "lost"],
        ]
      : [
          ["New enquiry", "new"],
          ["Not connected", "not_connected"],
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

/** Home v2's Recent calls: two saved calls the dashboard already read. */
function savedCalls(now: number): LibrarySubmission[] {
  return [
    {
      id: "00000000-0000-4000-8000-000000000511",
      createdAt: new Date(now - 38 * MINUTE).toISOString(),
      durationSeconds: 842,
      state: "completed",
      hasReport: true,
      label: { displayName: "Site visit · Priya Sample", revision: 1 },
      owner: { personId: SELLER, name: "Asha Fictional" },
    },
    {
      id: "00000000-0000-4000-8000-000000000501",
      createdAt: new Date(now - 96 * MINUTE).toISOString(),
      durationSeconds: 1268,
      state: "completed",
      hasReport: true,
      label: null,
    },
  ];
}

function Preview() {
  const params = useSearchParams();
  const seller = params.get("role") === "seller";
  const analysis = params.get("analysis") === "1";
  // The Home redesign (27 Oct 2026) is Home; `&layout=1` shows the one before.
  // `&fresh=1`: a new workspace.
  const v2 = params.get("layout") !== "1";
  const fresh = params.get("fresh") === "1";
  // The Team view redesign (owners) is the Team view; `&team=1` shows the one before.
  const team = params.get("team") !== "1";
  const [saved] = useState(() => savedCalls(Date.now()));
  // `&focus=<heading id>`: the shot starts at that part of Home (Home is
  // taller than a phone screen; the shots show one screen).
  const focus = params.get("focus");
  useEffect(() => {
    if (!focus) return;
    const scroll = () =>
      document.getElementById(focus)?.scrollIntoView({ block: "start" });
    const timers = [300, 900, 1800].map((ms) => window.setTimeout(scroll, ms));
    return () => timers.forEach((timer) => window.clearTimeout(timer));
  }, [focus]);
  useState(() =>
    install({
      quiet: params.get("quiet") === "1",
      none: params.get("none") === "1",
      targets: params.get("targets") !== "0",
      fresh,
    }),
  );
  // `&switcher=1`: the workspace list open, with long fictional names: the
  // computer's popover, or the phone's sheet (owner, #66).
  const switcher = params.get("switcher") === "1";
  useEffect(() => {
    if (!switcher) return;
    const timer = window.setTimeout(() => {
      const phone = document.querySelector<HTMLButtonElement>(
        'button[aria-label^="Workspace: "]',
      );
      const computer = document.querySelector<HTMLButtonElement>(
        'button[aria-haspopup="menu"]',
      );
      (phone && phone.offsetParent !== null ? phone : computer)?.click();
    }, 600);
    return () => window.clearTimeout(timer);
  }, [switcher]);
  // `&controls=1`: Team controls open, for the sheet's own shots (owner Home v3).
  const controls = params.get("controls") === "1";
  useEffect(() => {
    if (!controls) return;
    const timer = window.setTimeout(() => {
      Array.from(document.querySelectorAll("button"))
        .find((button) => button.textContent === "Controls")
        ?.click();
    }, 600);
    return () => window.clearTimeout(timer);
  }, [controls]);
  // Where this person left off: a lead they opened 25 minutes ago.
  useState(() => {
    if (typeof window === "undefined" || !v2 || fresh) return null;
    rememberOpened(
      {
        kind: "lead",
        id: "00000000-0000-4000-8000-000000001000",
        name: "asha fictional",
        person: seller ? SELLER : OWNER,
        tenant: TENANT,
      },
      new Date(Date.now() - 25 * MINUTE),
    );
    return null;
  });
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
          ...(switcher ? SWITCHER_WORKSPACES : []),
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
          sales={
            <SalesHome
              manager={!seller}
              layout={v2 ? "v2" : "v1"}
              team={team ? "v2" : "v1"}
              recent={v2 && !fresh ? saved : null}
            />
          }
          salesRole={seller ? "seller" : "manager"}
        />
      </LightboxShell>
    </WorkspaceAccessContext.Provider>
  );
}

/**
 * Invented days for the outcome tiles: the period's counts spread over its
 * days in a fixed, uneven pattern, oldest first, ending on the fixture's end.
 */
function fixtureDays(
  days: number,
  totals: Record<
    "calls" | "connected" | "interested" | "won" | "new_leads",
    number
  >,
) {
  const pattern = [0.4, 1.1, 0.7, 1.5, 0.9, 1.3, 1.6];
  const weights = Array.from(
    { length: days },
    (_, index) => pattern[index % 7],
  );
  const sum = weights.reduce((total, weight) => total + weight, 0);
  const last = Date.parse("2026-10-22T12:00:00+05:30");
  return weights.map((weight, index) => {
    const share = (value: number) => Math.round((value * weight) / sum);
    return {
      day: new Date(last - (days - 1 - index) * 86_400_000)
        .toISOString()
        .slice(0, 10),
      calls: share(totals.calls),
      connected: share(totals.connected),
      interested: share(totals.interested),
      won: share(totals.won),
      new_leads: share(totals.new_leads),
    };
  });
}

export function HomePreview() {
  return (
    <Suspense fallback={null}>
      <Preview />
    </Suspense>
  );
}
