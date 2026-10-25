import { adminRead } from "@/app/lib/server-api";
import {
  frictionQuery,
  normalizeFriction,
  recentWeeks,
  weekWords,
} from "@/app/telemetry/friction-data";
import { FrictionView } from "@/app/telemetry/friction-view";
import { LOOP_HREFS, LoopTabs } from "@/app/telemetry/loop-view";
import { Page, PageHeader, QueryTabs, Unavailable } from "@/app/ui/kit";

export const dynamic = "force-dynamic";

/**
 * Admin → Product telemetry → Friction (owner, 25 Oct 2026: "automatically find where
 * users stop, which screen they get stuck on, where they try to tap, and why"): one India
 * week, ranked findings with evidence and the question to answer, where flows stop,
 * permission prompts, workspace switching and screens by friction. The weekly job writes
 * the same report as markdown for the owner and the builders.
 */
export default async function TelemetryFrictionPage({
  searchParams,
}: {
  searchParams: Promise<{ week?: string }>;
}) {
  const query = frictionQuery(await searchParams);
  const result = await adminRead(query.path, normalizeFriction);
  const weeks = recentWeeks(new Date());
  const current = result.ok ? result.data.week : (query.week ?? weeks[1]);
  return (
    <Page wide>
      <PageHeader
        title="Friction"
        context={[
          "Where people get stuck, week by week: flows they stop in, taps that do nothing, screens they bounce off, permissions refused and workspace switching. Counts only; nobody is named.",
        ]}
      />
      <LoopTabs current="friction" hrefs={LOOP_HREFS} />
      <QueryTabs
        base="/telemetry/friction"
        param="week"
        items={weeks.map((week, index) => ({
          key: week,
          label: index === 0 ? "This week" : `Week of ${weekWords(week)}`,
        }))}
        current={current}
      />
      {result.ok ? (
        <FrictionView friction={result.data} markdownHref={query.markdown} />
      ) : (
        <Unavailable title="Friction" reason={result.error} />
      )}
    </Page>
  );
}
