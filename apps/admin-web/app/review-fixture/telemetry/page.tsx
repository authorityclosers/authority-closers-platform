import { notFound } from "next/navigation";

import { normalizeTelemetry } from "../../telemetry/telemetry-data";
import { TelemetryView } from "../../telemetry/telemetry-view";
import { Page, PageHeader } from "../../ui/kit";
import { telemetryFixture } from "./telemetry-fixture";

/**
 * Local review of Admin → Product telemetry with fictional numbers (no API, no account).
 * Never in a production build.
 */
export default async function TelemetryFixturePage({
  searchParams,
}: {
  searchParams: Promise<{ state?: string }>;
}) {
  if (process.env.NODE_ENV !== "development") notFound();
  const { state } = await searchParams;
  const telemetry = normalizeTelemetry(
    telemetryFixture(new Date(), state === "empty" ? "empty" : "live"),
  );
  return (
    <Page wide>
      <PageHeader
        title="Product telemetry"
        context={["Fixture: fictional numbers"]}
      />
      <TelemetryView telemetry={telemetry} />
    </Page>
  );
}
