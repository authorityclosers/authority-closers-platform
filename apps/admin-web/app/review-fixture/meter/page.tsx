import { notFound } from "next/navigation";

import { Page, PageHeader } from "../../ui/kit";
import { CostMeter } from "../../usage/cost-meter";
import { normalizeMeter } from "../../usage/meter-data";
import { meterFixture } from "./meter-fixture";

/**
 * Local review of the cost meter with fictional numbers (no API, no account): Home's three
 * numbers, Health's full meter, and an old export. Never in a production build.
 */
export default async function MeterFixturePage({
  searchParams,
}: {
  searchParams: Promise<{ state?: string }>;
}) {
  if (process.env.NODE_ENV !== "development") notFound();
  const { state } = await searchParams;
  const now = new Date();
  const chosen = state === "stale" || state === "empty" ? state : "live";
  const meter = normalizeMeter(meterFixture(now, chosen));
  return (
    <Page>
      <PageHeader title="Cost meter" context={["Fixture: fictional numbers"]} />
      <CostMeter meter={meter} />
      <div id="cost-meter">
        <CostMeter meter={meter} detail />
      </div>
    </Page>
  );
}
