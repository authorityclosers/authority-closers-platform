import { adminRead } from "@/app/lib/server-api";
import { LOOP_HREFS, LoopTabs } from "@/app/telemetry/loop-view";
import {
  SPEED_APPS,
  SPEED_WINDOWS,
  normalizeSpeed,
  speedQuery,
} from "@/app/telemetry/speed-data";
import { SpeedView } from "@/app/telemetry/speed-view";
import { Page, PageHeader, QueryTabs, Unavailable } from "@/app/ui/kit";

export const dynamic = "force-dynamic";

const WINDOW_WORDS: Record<string, string> = {
  "7d": "7 days",
  "24h": "24 hours",
  "30d": "30 days",
};
const APP_WORDS: Record<string, string> = {
  all: "All",
  android: "Android app",
  web: "Web",
};

/**
 * Admin → Product telemetry → Speed and journeys (owner, 27 Oct 2026: how Sales X-Ray runs on
 * the slowest phones): frames, slow API calls, load and the CPU test, taps by device tier and
 * the journey from Leads, each with its sample count.
 */
export default async function TelemetrySpeedPage({
  searchParams,
}: {
  searchParams: Promise<{ window?: string; app?: string }>;
}) {
  const query = speedQuery(await searchParams);
  const result = await adminRead(query.path, normalizeSpeed);
  return (
    <Page wide>
      <PageHeader
        title="Speed and journeys"
        context={[
          "How fast Sales X-Ray is on people's own phones and computers, and how far they get from Leads. Counts and timings only, never a name.",
        ]}
      />
      <LoopTabs current="speed" hrefs={LOOP_HREFS} />
      <QueryTabs
        base="/telemetry/speed"
        param="window"
        items={SPEED_WINDOWS.map((key) => ({
          key,
          label: WINDOW_WORDS[key] ?? key,
        }))}
        current={query.window}
        keep={query.app !== "all" ? `app=${query.app}` : ""}
      />
      <QueryTabs
        base="/telemetry/speed"
        param="app"
        items={SPEED_APPS.map((key) => ({
          key,
          label: APP_WORDS[key] ?? key,
        }))}
        current={query.app}
        keep={query.window !== "7d" ? `window=${query.window}` : ""}
      />
      {result.ok ? (
        <SpeedView speed={result.data} />
      ) : (
        <Unavailable title="Speed and journeys" reason={result.error} />
      )}
    </Page>
  );
}
