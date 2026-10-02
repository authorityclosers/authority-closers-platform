import type { Plan } from "../billing/contract";

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
