import { adminRead } from "@/app/lib/server-api";
import {
  LOOP_WINDOWS,
  fixNextQuery,
  normalizeFixNext,
} from "@/app/telemetry/loop-data";
import { FixNextView, LOOP_HREFS, LoopTabs } from "@/app/telemetry/loop-view";
import { Page, PageHeader, QueryTabs, Unavailable } from "@/app/ui/kit";

export const dynamic = "force-dynamic";

const WINDOW_WORDS: Record<string, string> = {
  "7d": "This week",
  "24h": "24 hours",
  "30d": "30 days",
};

/**
 * Admin → Product telemetry → Fix next (owner, 24 Oct 2026: "use in our recursive
 * improvement pipeline"): what to fix next, ranked by people affected times severity, with
 * evidence, screen, a suggested owner and the task text, and what improved since.
 */
export default async function TelemetryFixNextPage({
  searchParams,
}: {
  searchParams: Promise<{ window?: string }>;
}) {
  const query = fixNextQuery(await searchParams);
  const result = await adminRead(query.path, normalizeFixNext);
  return (
    <Page wide>
      <PageHeader
        title="Fix next"
        context={[
          "What hurts the most people most in this environment, from telemetry: slow key actions, failing calls, crashes, errors and repeated taps.",
        ]}
      />
      <LoopTabs current="fix" hrefs={LOOP_HREFS} />
      <QueryTabs
        base="/telemetry/fix-next"
        param="window"
        items={LOOP_WINDOWS.map((key) => ({
          key,
          label: WINDOW_WORDS[key] ?? key,
        }))}
        current={query.window}
      />
      {result.ok ? (
        <FixNextView fixNext={result.data} />
      ) : (
        <Unavailable title="Fix next" reason={result.error} />
      )}
    </Page>
  );
}
