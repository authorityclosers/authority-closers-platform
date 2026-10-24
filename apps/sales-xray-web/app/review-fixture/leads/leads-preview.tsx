"use client";

/**
 * The real Leads page with a fictional organisation, for screenshots on GitHub
 * (wb-ci --visual). Lead Desk reads are answered here; nothing leaves the
 * browser. Names arrive in lower case on purpose: the page shows them with
 * capitals. `?tab=all&stage=…|team|sources|stages` opens that view, as on
 * /leads; `&tap=menu` then opens the ⋯ menu by itself, and with
 * `?tab=stages&tap=change` the kinds of business. `&pipelines=2` gives the
 * organisation two pipelines (enquiries and partner outreach; `&pipeline=`
 * picks one), and `?tab=stages&pipelines=2&tap=new` opens New pipeline.
 * `?tab=board` shows the pipeline board and `?tab=numbers` Pipeline numbers (Lead OS).
 * `?after-call=1` opens the first lead just after a call to it that the phone
 * logged with 1 min 22 s of talk, so "How did it go?" shows (Redmi #47: Save
 * says what it still needs); `&tap=next` then saves "Didn't get through" and
 * shows who is next. `?after-call=back` opens it back from a browser's dialler
 * instead: whether it connected is unknown, so only the "Log this" chip shows
 * (owner, 23 Oct 2026: the question only after a real call).
 * `?tab=all&stage=open&tap=bulk` ticks two leads and opens Select → Actions;
 * `tap=bulkwa` goes on to a WhatsApp template and who gets it.
 * `?loop=1&tap=loop` opens Start calling just back from a call and taps No answer:
 * Call mode's "Save and call <name>", "Save and stop here" and who is next.
 * `?tab=all&stage=open&tap=filter` opens Filter (name or number, whose leads,
 * pipeline); add `&who=mine&q=pune` to see the filters that are on as chips.
 * `?hub=1&after-call=1` opens the first lead as the lead hub: a call with its
 * Report, a stage change, a note and a WhatsApp chat in one timeline.
 * `&views=1` keeps three saved views on this browser, one of them the view in use
 * (Open, Everyone); `&tap=views` then opens Views. `&q=` searches by name or city;
 * `?tab=all&stage=open&q=nagpurx` shows an empty list's "Clear filters".
 */

import { Suspense, useEffect, useState, type ReactNode } from "react";

import { rememberCall } from "../../leads/leads-client";
import {
  fixtureBoard,
  fixtureReport,
} from "../lead-pipeline/lead-pipeline-data";
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

/** `&pipelines=2`: two pipelines, half the leads in each. */
/** `&hub=1`: the first lead has a day of history and a WhatsApp chat (lead hub). */
const hub = () =>
  typeof window !== "undefined" &&
  new URLSearchParams(window.location.search).get("hub") === "1";

const afterCall = () =>
  typeof window === "undefined"
    ? null
    : new URLSearchParams(window.location.search).get("after-call");

/** A call the phone logged from its own dialler 95 s ago, 1 min 22 s of talk. */
function diallerCall(now: number) {
  return {
    kind: "call",
    at: new Date(now - 95_000).toISOString(),
    actor_name: "rahul example",
    stage: null,
    stage_label: null,
    reason: null,
    reason_label: null,
    connected: true,
    note: null,
    next_action_at: null,
    owner_name: null,
    previous_owner_name: null,
    allocation_reason: null,
    source_label: null,
    submission_id: null,
    simulated: null,
    duration_seconds: 82,
    via: "phone",
    direction: "outgoing",
  };
}

function hubEvents(now: number) {
  const at = (minutes: number) =>
    new Date(now - minutes * MINUTE).toISOString();
  const base = {
    actor_name: "rahul example",
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
  };
  return [
    {
      ...base,
      kind: "note",
      at: at(20),
      note: "Wants a Saturday visit with the family",
    },
    {
      ...base,
      kind: "stage",
      at: at(118),
      stage: "interested",
      stage_label: "Site visit booked",
    },
    {
      ...base,
      kind: "call",
      at: at(120),
      connected: true,
      direction: "outgoing",
      duration_seconds: 254,
      submission_id: "00000000-0000-4000-8000-000000000900",
    },
    {
      ...base,
      kind: "call",
      at: at(60 * 26),
      connected: false,
      direction: "outgoing",
      reason: "did_not_pick",
      reason_label: "No answer",
    },
    { ...base, kind: "captured", at: at(60 * 27), source_label: "Facebook ad" },
  ];
}

function hubChat(now: number) {
  const at = (minutes: number) =>
    new Date(now - minutes * MINUTE).toISOString();
  const message = (
    id: string,
    minutes: number,
    direction: string,
    text: string,
  ) => ({
    id,
    direction,
    kind: "text",
    text,
    status: "read",
    at: at(minutes),
  });
  return {
    configured: true,
    connected: true,
    numbers: [],
    messages: [
      message("m1", 70, "in", "Is the 2 BHK still free this weekend?"),
      message("m2", 66, "out", "Yes, Saturday 11 am works."),
      message("m3", 64, "in", "Great, see you then"),
    ],
    windowOpen: true,
    windowClosesAt: at(-60 * 22),
    optedIn: true,
    optInHow: "Lead form",
    templates: [],
  };
}

const twoPipelines = () =>
  typeof window !== "undefined" &&
  new URLSearchParams(window.location.search).get("pipelines") === "2";

const PARTNER_STAGES = [
  ["New", "new"],
  ["Couldn't reach", "not_connected"],
  ["Gatekeeper", "follow_up"],
  ["Spoke to owner", "follow_up"],
  ["Interested", "interested"],
  ["Meeting booked", "interested"],
  ["Partner signed", "won"],
  ["Not a fit", "lost"],
] as const;

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
    pipeline: index % 2 ? "main" : "partner_outreach",
  }));
}

/** My work (?tab=work): a seller's fictional day, newest first. */
function fixtureWork(now: number) {
  const at = (minutes: number) =>
    new Date(now - minutes * 60_000).toISOString();
  const item = (
    n: number,
    name: string,
    stage: string,
    minutes: number,
    event: Record<string, unknown>,
  ) => ({
    event_id: `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`,
    lead_id: `00000000-0000-4000-9000-${String(n).padStart(12, "0")}`,
    lead_name: name,
    stage_label: stage,
    event: { at: at(minutes), actor_name: "Kavya Fictional", ...event },
  });
  return {
    items: [
      item(1, "Asha Fictional", "Interested (In Follow-Up)", 12, {
        kind: "result",
        connected: true,
        stage_label: "Interested (In Follow-Up)",
        note: "Wants pricing for two people",
      }),
      item(1, "Asha Fictional", "Interested (In Follow-Up)", 14, {
        kind: "call",
        via: "phone",
        direction: "outgoing",
        duration_seconds: 186,
      }),
      item(2, "Rohan Sample", "Meeting / Demo Scheduled", 40, {
        kind: "stage",
        v: 2,
        action: "move",
        stage_label: "Meeting / Demo Scheduled",
        from_label: "Interested (In Follow-Up)",
      }),
      item(3, "neha fictional", "Discussion Incomplete", 75, {
        kind: "note",
        note: "Driving; call after 7 pm. Asked for the brochure on WhatsApp first.",
      }),
      item(4, "Vikram Sample", "Not Connected", 130, {
        kind: "result",
        connected: false,
        reason: "did_not_pick",
        reason_label: "Didn't pick up",
      }),
      item(5, "Pooja Fictional", "Closed / Lost", 190, {
        kind: "stage",
        v: 2,
        action: "close",
        stage_label: "Closed / Lost",
        from_label: "Discussion Incomplete",
        outcome_reason_label: "Price or budget",
      }),
    ],
    next_before: null,
    counts: { result: 2, call: 1, stage: 2, note: 1 },
  };
}

function answers(now: number, path: string): unknown {
  // To call's ?pipeline=: that pipeline's leads only, as the server answers.
  const [bare, query = ""] = path.split("?");
  // Lead OS: the board and Pipeline numbers (?tab=board, ?tab=numbers).
  if (bare.startsWith("/v1/lead-desk/board")) return fixtureBoard();
  if (bare === "/v1/lead-desk/reports/pipeline") return fixtureReport();
  if (bare === "/v1/lead-desk/activity") return fixtureWork(now);
  const asked =
    bare === "/v1/lead-desk" || bare === "/v1/lead-desk/next"
      ? new URLSearchParams(query).get("pipeline")
      : null;
  const all = rows(now).filter((row) => !asked || row.pipeline === asked);
  if (bare === "/v1/lead-desk")
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
    const pipeline = params.get("pipeline");
    // A search narrows by name or city, as the desk does (`&q=` on the page).
    const words = (params.get("search") ?? "").toLowerCase();
    const inPipeline = all.filter(
      (row) =>
        (!pipeline || row.pipeline === pipeline) &&
        (!words ||
          `${row.name} ${row.city ?? ""}`.toLowerCase().includes(words)),
    );
    const leads = inPipeline.filter((row) =>
      !stage || stage === "open"
        ? row.stage !== "won" && row.stage !== "lost"
        : row.stage === stage,
    );
    const stage_counts: Record<string, number> = {};
    for (const row of inPipeline)
      stage_counts[row.stage] = (stage_counts[row.stage] ?? 0) + 1;
    return { leads, total: leads.length, next_offset: null, stage_counts };
  }
  if (path === "/v1/lead-desk/whatsapp/status")
    return {
      numbers: [{ id: "00000000-0000-4000-8000-000000000700" }],
      templates: [
        {
          name: "welcome_lead",
          language: "en",
          status: "APPROVED",
          text: "Hi {{1}}, thanks for your enquiry. When can we call?",
          parts: 1,
        },
      ],
    };
  if (path === "/v1/lead-desk/leads/bulk-whatsapp/preview")
    return {
      ready: 1,
      skipped: [
        { reason: "no_yes", words: "haven't said yes to WhatsApp", count: 1 },
      ],
      sent: 0,
      failed: 0,
      text: "Hi {name}, thanks for your enquiry. When can we call?",
      limit: 100,
    };
  if (path.startsWith("/v1/lead-desk/next")) {
    // The lead after the one skipped (Call mode reads it ahead).
    const skip = new URLSearchParams(path.split("?")[1] ?? "").get("skip");
    const after = skip === all[1].lead_id ? all[2] : all[1];
    return {
      lead: after,
      phone: "+91 98765 43211",
      email: null,
      owner_reason: null,
      next_action_note: null,
      fields: [],
      source_fields: [],
      events: [],
      can_edit: true,
      can_assign: true,
      reps: [],
      call_mode: "phone",
    };
  }
  // A lead's chats (the lead hub reads them once): a WhatsApp chat with `&hub=1`.
  const chat =
    /^\/v1\/lead-desk\/leads\/([0-9a-f-]{36})\/(whatsapp|social)$/.exec(path);
  if (chat)
    return chat[2] === "whatsapp" && hub()
      ? hubChat(Date.now())
      : { configured: false, connected: false, threads: [], messages: [] };
  const one = /^\/v1\/lead-desk\/leads\/([0-9a-f-]{36})(\/dispose)?$/.exec(
    path,
  );
  const row = one ? all.find((item) => item.lead_id === one[1]) : undefined;
  if (row)
    return {
      // `&hub=1`: the first lead's record agrees with its day of history.
      lead:
        hub() && row.lead_id === all[0].lead_id
          ? {
              ...row,
              source: "meta",
              source_label: "Facebook ad",
              stage: "interested",
              stage_label: "Site visit booked",
              calls: 2,
              attempts: 2,
              created_at: new Date(Date.now() - 27 * 60 * MINUTE).toISOString(),
            }
          : row,
      phone: "+91 98765 43210",
      email: null,
      owner_reason: null,
      next_action_note: null,
      fields: [],
      source_fields: [],
      events: [
        ...(afterCall() === "1" && row.lead_id === all[0].lead_id
          ? [diallerCall(Date.now())]
          : []),
        ...(hub() && row.lead_id === all[0].lead_id
          ? hubEvents(Date.now())
          : []),
      ],
      can_edit: true,
      can_assign: true,
      reps: [],
      call_mode: "phone",
      first_call_minutes: null,
      stage_suggestion: null,
      stage_choices: (
        [
          ["step_2", "Call back", "follow_up", "You spoke to them"],
          ["step_3", "Site visit booked", "interested", "A visit is booked"],
          ["step_4", "Booked", "won", "They bought"],
          ["step_5", "Not interested", "lost", "They won't buy"],
        ] as const
      ).map(([key, label, kind, meaning]) => ({ key, label, kind, meaning })),
    };
  if (path === "/v1/lead-desk/pipelines" && twoPipelines())
    return {
      pipelines: [
        {
          key: "main",
          name: "Enquiries",
          position: 0,
          main: true,
          sources: [],
          industry: "real_estate",
          leads: 4,
        },
        {
          key: "partner_outreach",
          name: "Partner outreach",
          position: 1,
          main: false,
          sources: ["csv"],
          industry: null,
          leads: 4,
        },
      ],
      sources: {
        meta: "Facebook and Instagram lead ads",
        webhook: "Website forms and other apps",
        sheet: "Google Sheets",
        csv: "File imports",
        manual: "Added by hand",
        referral: "Referrals",
      },
      canEdit: true,
    };
  if (path === "/v1/lead-desk/journey?pipeline=partner_outreach")
    return {
      version: 3,
      industry: null,
      savedAt: null,
      savedBy: null,
      canEdit: true,
      kinds: {},
      meanings: {},
      pipeline: "partner_outreach",
      stages: PARTNER_STAGES.map(([label, kind], index) => ({
        key: `partner_${index}`,
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
  if (path === "/v1/lead-desk/journey/templates")
    return (
      [
        [
          "real_estate",
          "Real estate",
          "Flats, plots, villas",
          "building",
          [
            ["New enquiry", "new"],
            ["Couldn't reach", "not_connected"],
            ["Contacted", "follow_up"],
            ["Site visit booked", "interested"],
            ["Site visit done", "interested"],
            ["Negotiation", "interested"],
            ["Booked", "won"],
            ["Lost", "lost"],
          ],
        ],
        [
          "education",
          "Education",
          "Courses, coaching, admissions",
          "cap",
          [
            ["New enquiry", "new"],
            ["Couldn't reach", "not_connected"],
            ["Counselled", "follow_up"],
            ["Demo class booked", "interested"],
            ["Demo attended", "interested"],
            ["Application started", "interested"],
            ["Enrolled", "won"],
            ["Lost", "lost"],
          ],
        ],
        [
          "b2b_services",
          "B2B services",
          "Agencies, consultants, IT services",
          "briefcase",
          [
            ["New lead", "new"],
            ["Couldn't reach", "not_connected"],
            ["Discovery call", "follow_up"],
            ["Qualified", "interested"],
            ["Meeting booked", "interested"],
            ["Proposal sent", "interested"],
            ["Won", "won"],
            ["Lost", "lost"],
          ],
        ],
      ] as const
    ).map(([id, name, blurb, icon, stages]) => ({
      id,
      name,
      blurb,
      icon,
      stages: stages.map(([label, kind]) => ({
        label,
        kind,
        milestone: "other",
      })),
    }));
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

/** `&views=1`: three saved views (Leads → Views), kept as the page keeps them. */
function keepViews() {
  if (new URLSearchParams(window.location.search).get("views") !== "1") return;
  const view = (
    id: string,
    name: string,
    stage: string,
    who: string,
    q: string,
  ) => ({ id, name, stage, pipeline: null, who, q });
  try {
    window.localStorage.setItem(
      `sx.leads.views.v1:${OWNER}:${TENANT}`,
      JSON.stringify([
        view("v-open", "All open leads", "open", "team", ""),
        view("v-pune", "Mine in Pune", "open", "mine", "pune"),
        view("v-hot", "Interested, no owner", "interested", "unassigned", ""),
      ]),
    );
  } catch {
    // A browser that keeps nothing shows Views empty.
  }
}

function install() {
  if (typeof window === "undefined") return true;
  keepViews();
  // `?after-call=1|back`: a call to the first lead ended 95 s ago; it opens.
  if (afterCall() === "1" || afterCall() === "back") {
    const first = rows(Date.now())[0].lead_id;
    rememberCall(first, Date.now() - 95_000);
    window.history.replaceState(
      window.history.state,
      "",
      `${window.location.pathname}${window.location.search}#lead=${first}`,
    );
  }
  // `?loop=1`: Start calling opens on the second lead, just back from its call
  // (Call mode: "Save and call <name>" then names the lead after it).
  if (new URLSearchParams(window.location.search).get("loop") === "1")
    rememberCall(rows(Date.now())[1].lead_id, Date.now() - 95_000);
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
    const tap = new URLSearchParams(window.location.search).get("tap");
    const press = (text: string) =>
      Array.from(document.querySelectorAll<HTMLButtonElement>("button"))
        .find((button) => button.textContent?.trim().startsWith(text))
        ?.click();
    // `?tab=all&stage=open&tap=filter`: the Filter sheet (Leads header).
    if (tap === "filter") {
      const timer = window.setTimeout(() => press("Filter"), 900);
      return () => window.clearTimeout(timer);
    }
    // `&tap=loop` (with `?loop=1`): Start calling, then No answer.
    if (tap === "loop") {
      const timers = [
        window.setTimeout(() => press("Start calling"), 900),
        window.setTimeout(() => press("No answer"), 2200),
      ];
      return () => timers.forEach((timer) => window.clearTimeout(timer));
    }
    if (tap === "next" || tap === "bulk" || tap === "bulkwa") {
      const steps =
        tap === "next"
          ? ["Didn't get through", "No answer", "Save"]
          : tap === "bulk"
            ? ["Select", "", "", "Actions"]
            : [
                "Select",
                "",
                "",
                "Actions",
                "Send a WhatsApp template",
                "welcome lead",
                "Check who gets it",
              ];
      const timers = steps.map((text, index) =>
        window.setTimeout(
          () => {
            if (text) press(text);
            else
              document
                .querySelectorAll<HTMLButtonElement>(
                  'li button[aria-checked="false"]',
                )[0]
                ?.click();
          },
          900 + index * 300,
        ),
      );
      return () => timers.forEach((timer) => window.clearTimeout(timer));
    }
    if (tap !== "menu" && tap !== "change" && tap !== "new" && tap !== "views")
      return;
    const timer = window.setTimeout(
      () =>
        (tap === "menu"
          ? document.querySelector<HTMLButtonElement>(
              'button[aria-label="Leads settings"]',
            )
          : tap === "views"
            ? document.querySelector<HTMLButtonElement>(
                'button[aria-label^="Saved view"]',
              )
            : tap === "new"
              ? Array.from(
                  document.querySelectorAll<HTMLButtonElement>("button"),
                ).find(
                  (button) => button.textContent?.trim() === "New pipeline",
                )
              : Array.from(
                  document.querySelectorAll<HTMLButtonElement>(
                    'section[aria-label="Your kind of business"] button',
                  ),
                ).find((button) => button.textContent === "Change")
        )?.click(),
      900,
    );
    return () => window.clearTimeout(timer);
  }, []);
}

/** The fictional organisation, signed in, with its answers installed: for any
 * screen's fixture that reads the Lead Desk (Leads, and Settings since slice 5). */
export function FixtureWorkspace({ children }: { children: ReactNode }) {
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
      {children}
    </WorkspaceAccessContext.Provider>
  );
}

export function LeadsPreview() {
  useTap();
  return (
    <FixtureWorkspace>
      <Suspense fallback={null}>
        <LeadsRoute />
      </Suspense>
    </FixtureWorkspace>
  );
}
