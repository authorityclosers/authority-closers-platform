import { notFound } from "next/navigation";

import { LOOP_HREFS, LoopTabs } from "../../telemetry/loop-view";
import { normalizeSpeed } from "../../telemetry/speed-data";
import { SpeedView } from "../../telemetry/speed-view";
import { Page, PageHeader } from "../../ui/kit";
import { speedFixture } from "./speed-fixture";

/**
 * Local review of Admin → Product telemetry → Speed and journeys with fictional numbers (no
 * API, no account). Never in a production build.
 */
export default async function TelemetrySpeedFixturePage({
  searchParams,
}: {
  searchParams: Promise<{ state?: string }>;
}) {
  if (process.env.NODE_ENV !== "development") notFound();
  const { state } = await searchParams;
  const speed = normalizeSpeed(
    speedFixture(new Date(), state === "empty" ? "empty" : "live"),
  );
  return (
    <Page wide>
      <PageHeader
        title="Speed and journeys"
        context={["Fixture: fictional numbers"]}
      />
      <LoopTabs current="speed" hrefs={LOOP_HREFS} />
      <SpeedView speed={speed} />
    </Page>
  );
}
