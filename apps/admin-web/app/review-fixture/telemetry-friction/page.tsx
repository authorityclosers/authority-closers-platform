import { notFound } from "next/navigation";

import { normalizeFriction } from "../../telemetry/friction-data";
import { FrictionView } from "../../telemetry/friction-view";
import { LoopTabs } from "../../telemetry/loop-view";
import { Page, PageHeader } from "../../ui/kit";
import { frictionFixture } from "./friction-fixture";

const HREFS = {
  overview: "/review-fixture/telemetry",
  devices: "/review-fixture/telemetry-loop",
  releases: "/review-fixture/telemetry-loop?view=releases",
  fix: "/review-fixture/telemetry-loop?view=fix",
  friction: "/review-fixture/telemetry-friction",
};

/**
 * Local review of Friction with fictional numbers (no API, no account); ?state=empty for
 * a week with nothing recorded. Never in a production build.
 */
export default async function TelemetryFrictionFixturePage({
  searchParams,
}: {
  searchParams: Promise<{ state?: string }>;
}) {
  if (process.env.NODE_ENV !== "development") notFound();
  const params = await searchParams;
  const state = params.state === "empty" ? "empty" : "live";
  return (
    <Page wide>
      <PageHeader title="Friction" context={["Fixture: fictional numbers"]} />
      <LoopTabs current="friction" hrefs={HREFS} />
      <FrictionView
        friction={normalizeFriction(frictionFixture(new Date(), state))}
        markdownHref="#markdown"
      />
    </Page>
  );
}
