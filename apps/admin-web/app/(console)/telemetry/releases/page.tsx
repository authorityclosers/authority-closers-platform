import { adminRead } from "@/app/lib/server-api";
import { compareQuery, normalizeComparison } from "@/app/telemetry/loop-data";
import { LOOP_HREFS, LoopTabs, ReleasesView } from "@/app/telemetry/loop-view";
import { Page, PageHeader, QueryTabs, Unavailable } from "@/app/ui/kit";

export const dynamic = "force-dynamic";

/**
 * Admin → Product telemetry → Releases (owner, 24 Oct 2026: "each new update we improve
 * the app using that data"): a release against the one before it on key actions, problem
 * rates, page speed and funnels, and what the release gate says.
 */
export default async function TelemetryReleasesPage({
  searchParams,
}: {
  searchParams: Promise<{ head?: string; base?: string }>;
}) {
  const query = compareQuery(await searchParams);
  const result = await adminRead(query.path, normalizeComparison);
  const releases = result.ok ? result.data.releases.slice(0, 8) : [];
  return (
    <Page wide>
      <PageHeader
        title="Releases"
        context={[
          "Each release against the one before it, from the last 30 days of this environment's telemetry.",
        ]}
      />
      <LoopTabs current="releases" hrefs={LOOP_HREFS} />
      {result.ok ? (
        <ReleasesView
          comparison={result.data}
          releaseTabs={
            releases.length > 1 ? (
              <QueryTabs
                base="/telemetry/releases"
                param="head"
                items={[
                  { key: "latest", label: "Latest" },
                  ...releases.map((row) => ({
                    key: row.release,
                    label: row.release,
                  })),
                ]}
                current={query.head ?? "latest"}
              />
            ) : null
          }
        />
      ) : (
        <Unavailable title="Releases" reason={result.error} />
      )}
    </Page>
  );
}
