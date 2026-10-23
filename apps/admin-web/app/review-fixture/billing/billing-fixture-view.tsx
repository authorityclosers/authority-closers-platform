"use client";

import { billingFixture } from "../../platform/billing-fixture";
import { BillingPanel } from "../../platform/billing-panel";
import { RevenuePanel } from "../../platform/revenue-panel";
import { liveRevenueFixture, testRevenueFixture } from "./revenue-fixture";

/** Answers the two billing reads from fixtures; a refund is refused (nothing to refund here). */
const fixtureFetch: typeof fetch = async (input) => {
  const url = typeof input === "string" ? input : input.toString();
  if (url.startsWith("/v1/platform/billing/revenue"))
    return Response.json(
      url.endsWith("mode=test") ? testRevenueFixture : liveRevenueFixture,
    );
  if (url === "/v1/platform/billing") return Response.json(billingFixture);
  return Response.json(
    { detail: "Fixture: nothing to refund." },
    { status: 409 },
  );
};

export function BillingFixtureView() {
  return (
    <>
      <RevenuePanel fetcher={fixtureFetch} />
      <BillingPanel fetcher={fixtureFetch} />
    </>
  );
}
