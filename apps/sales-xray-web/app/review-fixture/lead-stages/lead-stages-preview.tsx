"use client";

/**
 * Leads → Lead stages with a fictional business (Fictional Homes, real estate)
 * and a fictional Meta dataset, for screenshots on GitHub (wb-ci --visual).
 * The page's own API calls are answered here; nothing leaves the browser.
 * `?first=1` shows the first visit (pick a kind of business).
 */

import { useEffect, useState } from "react";

import { JourneyTab } from "../../leads/journey/journey-view";
import styles from "../../leads/leads.module.css";

const at = (minutes: number) =>
  new Date(Date.now() - minutes * 60_000).toISOString();

const MEANINGS: Record<string, string> = {
  lead: "A new enquiry",
  unreachable: "You couldn't reach them",
  contacted: "You spoke to them",
  qualified: "A good fit and keen",
  appointment_booked: "A meeting or visit is booked",
  appointment_done: "The meeting or visit happened",
  proposal: "They have your quote or proposal",
  application: "They sent forms or documents",
  negotiation: "Agreeing the final terms",
  won: "They bought",
  lost: "They won't buy",
  other: "Something else",
};
const KINDS: Record<string, string> = {
  new: "New lead",
  not_connected: "Couldn't reach",
  follow_up: "In talks",
  interested: "Hot",
  won: "Won",
  lost: "Lost",
};

const stage = (
  key: string,
  label: string,
  kind: string,
  milestone: string,
  leads: number,
  archived = false,
) => ({
  key,
  label,
  kind,
  kindWords: KINDS[kind],
  milestone,
  meaning: MEANINGS[milestone],
  archived,
  origin: "template",
  leads,
});

const JOURNEY = {
  version: 3,
  industry: "real_estate",
  savedAt: at(90),
  savedBy: null,
  canEdit: true,
  kinds: KINDS,
  meanings: MEANINGS,
  stages: [
    stage("new", "New enquiry", "new", "lead", 18),
    stage("not_connected", "Couldn't reach", "not_connected", "unreachable", 6),
    stage("contacted", "Contacted", "follow_up", "contacted", 11),
    stage(
      "site_visit_booked",
      "Site visit booked",
      "interested",
      "appointment_booked",
      5,
    ),
    stage(
      "site_visit_done",
      "Site visit done",
      "interested",
      "appointment_done",
      3,
    ),
    stage("negotiation", "Negotiation", "interested", "negotiation", 2),
    stage("booked", "Booked", "won", "won", 4),
    stage("lost", "Lost", "lost", "lost", 9),
    stage("interested", "Interested", "interested", "qualified", 1, true),
  ],
};

const TEMPLATES = [
  ["simple", "Any business", "Six stages that suit most teams.", "spark"],
  [
    "real_estate",
    "Real estate",
    "From enquiry to site visit to booking.",
    "building",
  ],
  [
    "education",
    "Coaching & education",
    "Counselling, demo class, enrolment.",
    "cap",
  ],
  ["insurance", "Insurance", "Needs, quote, documents, policy.", "shield"],
  [
    "clinic",
    "Clinics & healthcare",
    "Enquiry, appointment, visit, treatment.",
    "heart",
  ],
  [
    "b2b_services",
    "B2B services & agencies",
    "Discovery, meeting, proposal, deal.",
    "briefcase",
  ],
  ["automotive", "Cars & bikes", "Test drive, quote, booking.", "car"],
  ["loans", "Loans & finance", "Eligibility, documents, disbursal.", "bank"],
  ["home_services", "Home services & solar", "Survey, quote, order.", "home"],
  ["software", "Software & SaaS", "Demo, trial, proposal, signed.", "screen"],
  ["travel", "Travel & holidays", "Plan, itinerary, booking.", "plane"],
  ["retail", "Shops & showrooms", "Enquiry, store visit, purchase.", "bag"],
].map(([id, name, blurb, icon]) => ({
  id,
  name,
  blurb,
  icon,
  stages: JOURNEY.stages
    .filter((item) => !item.archived)
    .map(({ label, kind, milestone }) => ({ label, kind, milestone })),
}));

const match = (
  key: string,
  label: string,
  kind: string,
  milestone: string,
  name: string | null,
  state: "on" | "off" | "new",
) => ({
  stageKey: key,
  stageLabel: label,
  kind,
  milestone,
  suggested: name,
  saved: state === "new" ? null : name,
  state,
  words: name ? `“${name}”` : null,
});

const GOOGLE_OPTIONS = [
  { id: "qualified_lead", words: "a qualified lead" },
  { id: "booked_appointment", words: "a booked meeting" },
  { id: "requested_quote", words: "a quote sent" },
  { id: "converted_lead", words: "a customer" },
];

const google = (
  key: string,
  label: string,
  kind: string,
  milestone: string,
  name: string | null,
  state: "on" | "off" | "new",
) => ({
  ...match(key, label, kind, milestone, name, state),
  words: GOOGLE_OPTIONS.find((option) => option.id === name)?.words ?? null,
});

const ADS = {
  version: 3,
  settling: 1,
  sendsAt: new Date(Date.now() + 4 * 60_000).toISOString(),
  providers: [
    {
      id: "meta",
      name: "Meta",
      brand: "meta",
      naming: "stage",
      learns:
        "Meta's ads learn which leads become customers and find more people like them.",
      reaches: "Leads from your Facebook and Instagram lead forms.",
      destinationWords: "dataset",
      available: true,
      configured: true,
      connected: true,
      destination: {
        id: "100000000000001",
        name: "Fictional Homes lead stages",
      },
      on: true,
      testCode: null,
      since: at(60 * 24 * 3),
      matches: [
        match("new", "New enquiry", "new", "lead", "Lead", "on"),
        match(
          "contacted",
          "Contacted",
          "follow_up",
          "contacted",
          "Contacted",
          "on",
        ),
        match(
          "site_visit_booked",
          "Site visit booked",
          "interested",
          "appointment_booked",
          "Site visit booked",
          "on",
        ),
        match(
          "site_visit_done",
          "Site visit done",
          "interested",
          "appointment_done",
          "Site visit done",
          "new",
        ),
        match(
          "negotiation",
          "Negotiation",
          "interested",
          "negotiation",
          "Negotiation",
          "on",
        ),
        match("booked", "Booked", "won", "won", "Booked", "on"),
        match(
          "not_connected",
          "Couldn't reach",
          "not_connected",
          "unreachable",
          null,
          "off",
        ),
        match("lost", "Lost", "lost", "lost", "Lost", "on"),
      ],
      needsCheck: 1,
      confirmedAt: at(60 * 24),
      counts: { delivered: 37, pending: 2 },
      lastDeliveredAt: at(12),
      waitingOn: null,
    },
    {
      id: "google_ads",
      name: "Google Ads",
      brand: "googleads",
      naming: "action",
      learns:
        "Google's bidding learns which clicks turn into good leads and customers, and finds more of them.",
      reaches:
        "Leads from your Google lead forms and website forms that keep Google's click id, and any lead with an email or phone.",
      destinationWords: "account",
      available: true,
      configured: true,
      connected: true,
      destination: { id: "1234567890", name: "Fictional Homes (test account)" },
      on: true,
      testCode: null,
      since: at(60 * 24),
      options: GOOGLE_OPTIONS,
      matches: [
        google("new", "New enquiry", "new", "lead", null, "off"),
        google("contacted", "Contacted", "follow_up", "contacted", null, "off"),
        google(
          "site_visit_booked",
          "Site visit booked",
          "interested",
          "appointment_booked",
          "booked_appointment",
          "on",
        ),
        google(
          "site_visit_done",
          "Site visit done",
          "interested",
          "appointment_done",
          null,
          "off",
        ),
        google(
          "negotiation",
          "Negotiation",
          "interested",
          "negotiation",
          null,
          "off",
        ),
        google("booked", "Booked", "won", "won", "converted_lead", "on"),
        google(
          "not_connected",
          "Couldn't reach",
          "not_connected",
          "unreachable",
          null,
          "off",
        ),
        google("lost", "Lost", "lost", "lost", null, "off"),
      ],
      needsCheck: 0,
      confirmedAt: at(60 * 24),
      counts: { delivered: 9 },
      lastDeliveredAt: at(48),
      waitingOn: null,
    },
    ...[
      ["linkedin", "LinkedIn", "linkedin"],
      ["tiktok", "TikTok", "tiktok"],
      ["microsoft_ads", "Microsoft Ads", "microsoft"],
    ].map(([id, name, brand]) => ({
      id,
      name,
      brand,
      naming: "action",
      learns: "",
      reaches: "",
      destinationWords: "",
      available: false,
      configured: false,
      connected: false,
      destination: null,
      on: false,
      testCode: null,
      since: null,
      matches: [],
      needsCheck: 0,
      confirmedAt: null,
      counts: {},
      lastDeliveredAt: null,
      waitingOn: null,
    })),
  ],
  recent: [
    ["Asha Verma", "Booked", "delivered", 12],
    ["Rahul Mehta", "Site visit booked", "delivered", 40],
    ["Neha Iyer", "Contacted", "pending", 3],
    ["Karan Shah", "Lost", "delivered", 95],
  ].map(([leadName, stageLabel, status, minutes], index) => ({
    id: `00000000-0000-4000-8000-00000000000${index}`,
    provider: "meta",
    leadId: `00000000-0000-4000-8000-00000000010${index}`,
    leadName,
    stageLabel,
    eventName: stageLabel,
    status,
    attempts: status === "pending" ? 0 : 1,
    eventTime: at(Number(minutes)),
    deliveredAt: status === "delivered" ? at(Number(minutes) - 5) : null,
    error: null,
    test: false,
  })),
};

function answer(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

// ?choose=1: changing the kind of business with leads on the stages and two
// pipelines (the owner's phone screen, P1 of 24 Oct 2026).
const PIPES = {
  pipelines: [
    {
      key: "main",
      name: "Main pipeline",
      position: 0,
      main: true,
      sources: [],
      industry: "real_estate",
      leads: 47,
    },
    {
      key: "resale",
      name: "Resale",
      position: 1,
      main: false,
      sources: ["csv"],
      industry: "real_estate",
      leads: 6,
    },
  ],
  sources: {
    meta: "Facebook and Instagram lead ads",
    webhook: "Website forms and other apps",
    sheets: "Google Sheets",
    csv: "File imports",
    manual: "Added by hand",
    referral: "Referrals",
  },
  canEdit: true,
};

function install(first: boolean, choose = false) {
  if (typeof window === "undefined") return true;
  const real = window.fetch.bind(window);
  let journey = first ? { ...JOURNEY, version: 0, industry: null } : JOURNEY;
  window.fetch = async (input, init) => {
    const url = String(input instanceof Request ? input.url : input);
    if (!url.includes("/v1/lead-desk/")) return real(input, init);
    const method = init?.method ?? "GET";
    if (choose && method === "GET" && url.endsWith("/pipelines"))
      return answer(PIPES);
    if (url.endsWith("/journey/templates")) return answer(TEMPLATES);
    if (url.endsWith("/journey/suggestions"))
      return answer([
        {
          ref: "pulse:st_quote",
          label: "Quotation sent",
          source: "Pulse",
          workflow: "Sales",
          milestone: "proposal",
          meaning: MEANINGS.proposal,
          kind: "interested",
          kindWords: "Hot",
        },
        {
          ref: "pulse:st_token",
          label: "Token amount received",
          source: "Pulse",
          workflow: "Sales",
          milestone: "negotiation",
          meaning: MEANINGS.negotiation,
          kind: "interested",
          kindWords: "Hot",
        },
        {
          ref: "calls:proposal",
          label: "Quote sent",
          source: "your calls",
          workflow: "heard in 14 calls and notes",
          milestone: "proposal",
          meaning: MEANINGS.proposal,
          kind: "interested",
          kindWords: "Hot",
        },
      ]);
    if (url.endsWith("/journey/ads")) return answer(ADS);
    if (url.endsWith("/journey/ads/meta/quality"))
      return answer({
        score: 6.4,
        events: 24,
        keys: { email: 100, phone: 92, external_id: 100, country: 92, fbc: 18 },
      });
    if (url.endsWith("/journey/summary"))
      return answer({
        stages: 8,
        industry: "real_estate",
        providersOn: ["meta"],
        needsCheck: 1,
        lastDeliveredAt: at(12),
      });
    if (url.endsWith("/journey/guess"))
      return answer({
        milestone: "appointment_done",
        meaning: MEANINGS.appointment_done,
        kind: "interested",
        kindWords: "Hot",
      });
    if (url.endsWith("/journey/template") && method === "POST") {
      journey = JOURNEY;
      return answer(journey);
    }
    if (url.endsWith("/journey")) return answer(journey);
    return answer({});
  };
  return true;
}

const asked = (name: string) =>
  typeof window !== "undefined" &&
  new URLSearchParams(window.location.search).get(name) === "1";

export function LeadStagesPreview() {
  useState(() => install(asked("first"), asked("choose")));
  // ?choose=1 opens "Change your kind of business", as the Change button does.
  useEffect(() => {
    if (!asked("choose")) return;
    const timer = window.setInterval(() => {
      const change = [...document.querySelectorAll("button")].find(
        (button) => button.textContent?.trim() === "Change",
      );
      if (!change) return;
      change.click();
      window.clearInterval(timer);
    }, 100);
    return () => window.clearInterval(timer);
  }, []);
  return (
    <div className={styles.root}>
      <JourneyTab canManage />
    </div>
  );
}
