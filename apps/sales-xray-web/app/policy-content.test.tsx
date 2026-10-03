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
    perSeat: false,
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
    perSeat: true,
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
    perSeat: true,
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
    perSeat: false,
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
  const terms = renderToStaticMarkup(
    <PolicyPage slug="terms" pricingPlans={samplePlans} />,
  );
  expect(markup).not.toContain("Must not be shown");
  expect(terms).not.toContain("GST");
});

it("shows each plan's GST treatment next to its catalogue prices", () => {
  const markup = renderToStaticMarkup(
    <PolicyPage slug="pricing" pricingPlans={samplePlans} />,
  );
  expect(markup).toContain("₹1,234 / month (GST included)");
  expect(markup).toContain("₹90 (GST included)");
  expect(markup).toContain("₹2,345 per seat / month + GST");
  // Enterprise is not on sale in the sample, so it shows no price or GST note.
  expect(markup.split("+ GST")).toHaveLength(2);
});

it("lists the Enterprise inclusions and an open seat range", () => {
  const markup = renderToStaticMarkup(
    <PolicyPage slug="pricing" pricingPlans={samplePlans} />,
  );
  expect(markup).toContain(
    "Everything in Organisation, plus priority support and an onboarding session for your team.",
  );
  expect(markup).toContain("Seats: 6 or more");
  expect(markup).toContain("Seats: 2–5");
  expect(markup).toContain("Seats: 1<");
});

it("makes none of the promises the owner removed on 3 October", () => {
  const pages = policyRoutes
    .map((slug) =>
      renderToStaticMarkup(
        <PolicyPage slug={slug} pricingPlans={samplePlans} />,
      ),
    )
    .join("\n");
  for (const removed of [
    "working day",
    "within 30",
    "5–7",
    "remind you",
    "under contract",
    "10:00–19:00",
    "UPI",
  ]) {
    expect(pages).not.toContain(removed);
  }
  expect(pages).toContain("Vikriya Solutions LLP");
  expect(pages).toContain(
    "Failed, duplicate or wrongly charged payments are refunded in full.",
  );
});

it("hides unavailable plan prices and top-up amounts", () => {
  const comingSoon: Plan = {
    ...samplePlans[2],
    prices: {
      monthlyPaise: 765_432_100,
      yearlyPaise: 1_234_567_800,
      monthlyCents: null,
      yearlyCents: null,
    },
    topUpPacks: [
      {
        key: "fictional-coming-soon-pack",
        minutes: 300,
        validityRule: "billing_year_end",
        pricePaise: 9_876_543,
        priceCents: null,
      },
    ],
  };
  const pricingWithComingSoon = renderToStaticMarkup(
    <PolicyPage
      slug="pricing"
      pricingPlans={[...samplePlans.slice(0, 2), comingSoon, samplePlans[3]]}
    />,
  );
  const pricingWithMissingPrice = renderToStaticMarkup(
    <PolicyPage slug="pricing" pricingPlans={samplePlans} />,
  );

  expect(pricingWithComingSoon).toContain("Not currently on sale");
  expect(pricingWithComingSoon).not.toContain("₹7,654,321");
  expect(pricingWithComingSoon).not.toContain("₹12,345,678");
  expect(pricingWithComingSoon).not.toContain("₹98,765.43");
  expect(pricingWithComingSoon).toContain("₹1,234 / month");
  expect(pricingWithComingSoon).toContain("₹90");
  expect(pricingWithMissingPrice).toContain(
    "Price is not listed in the catalogue.",
  );
});
