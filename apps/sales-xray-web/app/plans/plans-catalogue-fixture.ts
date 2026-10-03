import type { Plan } from "../billing/contract";

export type DisplayTopUpPack = {
  key: string;
  planKey: string;
  title: string;
  audience: string;
  minutes: number;
  pricePaise: number;
  gstInclusive: boolean;
};

/** Owner-approved top-up display prices; purchase wiring belongs to AUT-880. */
export const TOP_UP_PACKS: DisplayTopUpPack[] = [
  {
    key: "personal_100",
    planKey: "personal",
    title: "Personal Top-up",
    audience: "For individual closers",
    minutes: 100,
    pricePaise: 29900,
    gstInclusive: true,
  },
  {
    key: "organisation_500",
    planKey: "organisation",
    title: "Organisation Top-up",
    audience: "Shared pool for your sales team",
    minutes: 500,
    pricePaise: 129900,
    gstInclusive: false,
  },
];

/** Owner-approved display catalogue for AUT-894. Replaced by catalogue props in AUT-880. */
export const PLANS_CATALOGUE_FIXTURE: Plan[] = [
  {
    key: "personal",
    name: "Personal",
    audience: "For one salesperson",
    status: "active",
    prices: {
      monthlyPaise: 249900,
      yearlyPaise: 2699000,
      monthlyCents: null,
      yearlyCents: null,
    },
    includedMinutes: 800,
    seatMin: 1,
    seatMax: 1,
    perSeat: false,
    longestCallMinutes: 90,
    retentionDays: null,
    rolloverMonths: null,
    featureKeys: [],
    topUpPacks: [],
    sortOrder: 10,
    revision: 1,
  },
  {
    key: "organisation",
    name: "Organisation",
    audience: "For sales teams",
    status: "active",
    prices: {
      monthlyPaise: 1000000,
      yearlyPaise: 10800000,
      monthlyCents: null,
      yearlyCents: null,
    },
    includedMinutes: 1000,
    seatMin: 2,
    seatMax: 49,
    perSeat: true,
    longestCallMinutes: 90,
    retentionDays: null,
    rolloverMonths: null,
    featureKeys: ["team_dashboard", "team_library"],
    topUpPacks: [],
    sortOrder: 20,
    revision: 1,
  },
  {
    key: "enterprise",
    name: "Enterprise",
    audience: "For large sales companies",
    status: "active",
    prices: {
      monthlyPaise: 1000000,
      yearlyPaise: 10800000,
      monthlyCents: null,
      yearlyCents: null,
    },
    includedMinutes: 1000,
    seatMin: 50,
    seatMax: null,
    perSeat: true,
    longestCallMinutes: 120,
    retentionDays: null,
    rolloverMonths: null,
    featureKeys: [
      "team_dashboard",
      "team_library",
      "priority_support",
      "team_onboarding",
    ],
    topUpPacks: [],
    sortOrder: 30,
    revision: 1,
  },
];

/** Display tax only; the checkout quote supplied by AUT-880 remains authoritative. */
export const PLANS_GST_RATE = 0.18;
