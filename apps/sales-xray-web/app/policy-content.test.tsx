import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";

import type { Plan } from "./billing/contract";
import { PolicyPage, type PolicySlug } from "./policy-content";

const samplePlans: Plan[] = [
  {
    key: "personal",
    name: "Sample Personal",
    audience: "Fictional individual plan",
    status: "active",
    prices: {
      monthlyPaise: 123400,
      yearlyPaise: null,
      monthlyCents: null,
      yearlyCents: null,
    },
    includedMinutes: 40,
    seatMin: 1,
    seatMax: 1,
    longestCallMinutes: 30,
    retentionDays: 7,
    rolloverMonths: null,
    featureKeys: [],
    topUpPacks: [
      {
        key: "sample-pack",
        minutes: 10,
        validityRule: "billing_year_end",
        pricePaise: 9000,
        priceCents: null,
      },
    ],
    sortOrder: 1,
    revision: 1,
  },
  {
    key: "organisation",
    name: "Sample Organisation",
    audience: "Fictional team plan",
    status: "active",
    prices: {
      monthlyPaise: 234500,
      yearlyPaise: null,
      monthlyCents: null,
      yearlyCents: null,
    },
    includedMinutes: 60,
    seatMin: 2,
    seatMax: 5,
    longestCallMinutes: 45,
    retentionDays: 14,
    rolloverMonths: null,
    featureKeys: [],
    topUpPacks: [],
    sortOrder: 2,
    revision: 1,
  },
  {
    key: "enterprise",
    name: "Sample Enterprise",
    audience: "Fictional large team plan",
    status: "coming_soon",
    prices: null,
    includedMinutes: null,
    seatMin: 6,
    seatMax: null,
    longestCallMinutes: null,
    retentionDays: null,
    rolloverMonths: null,
    featureKeys: [],
    topUpPacks: [],
    sortOrder: 3,
    revision: 1,
  },
  {
    key: "company",
    name: "Must not be shown",
    audience: "Not part of the catalogue pages",
    status: "active",
    prices: null,
    includedMinutes: null,
    seatMin: null,
    seatMax: null,
    longestCallMinutes: null,
    retentionDays: null,
    rolloverMonths: null,
    featureKeys: [],
    topUpPacks: [],
    sortOrder: 0,
    revision: 1,
  },
];

const policyRoutes: PolicySlug[] = [
  "pricing",
  "terms",
  "privacy",
  "refunds",
  "delivery",
  "contact",
];

for (const slug of policyRoutes) {
  it("snapshots the " + slug + " policy page", () => {
    const markup = renderToStaticMarkup(
      <PolicyPage slug={slug} pricingPlans={samplePlans} />,
    );
    expect(markup).toMatchSnapshot();
    expect(markup).toContain('href="/pricing"');
    expect(markup).toContain('href="/terms"');
    expect(markup).toContain('href="/privacy"');
    expect(markup).toContain('href="/refunds"');
    expect(markup).toContain('href="/delivery"');
    expect(markup).toContain('href="/contact"');
  });
}

it("does not show the superseded Company tier on pricing", () => {
  const markup = renderToStaticMarkup(
    <PolicyPage slug="pricing" pricingPlans={samplePlans} />,
  );
  expect(markup).not.toContain("Must not be shown");
  expect(markup).not.toContain("GST");
});
