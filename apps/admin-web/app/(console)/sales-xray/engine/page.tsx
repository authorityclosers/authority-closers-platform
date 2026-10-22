import { EngineView } from "@/app/analysis-engine/engine-view";
import {
  ENVIRONMENTS,
  WINDOWS,
  engineQuery,
  normalizeEngine,
} from "@/app/analysis-engine/engine-data";
import { adminRead } from "@/app/lib/server-api";
import { Page, PageHeader, QueryTabs, Unavailable } from "@/app/ui/kit";

export const dynamic = "force-dynamic";

/**
 * Admin → Analysis engine (adaptive analysis, phase 1; owner, 22 Oct 2026): the registry
 * of analysis modules with measured cost fits, expected against actual per module for one
 * environment and window, and each plan's cost per audio minute. Read only.
 */
export default async function AnalysisEnginePage({
  searchParams,
}: {
  searchParams: Promise<{ env?: string; days?: string }>;
}) {
  const { env, days } = await searchParams;
  const query = engineQuery(env, days);
  const result = await adminRead(query.path, normalizeEngine);
  return (
    <Page wide>
      <PageHeader
        title="Analysis engine"
        context={[
          "What each analysis read costs, measured, against what it cost on real calls; the plans the engine can choose between. List-price estimates for Admin only; nothing here routes a call.",
        ]}
      />
      <QueryTabs
        base="/sales-xray/engine"
        param="env"
        items={[...ENVIRONMENTS]}
        current={query.environment}
        keep={query.days === "7" ? undefined : `days=${query.days}`}
      />
      <QueryTabs
        base="/sales-xray/engine"
        param="days"
        items={[...WINDOWS]}
        current={query.days}
        keep={
          query.environment === "production"
            ? undefined
            : `env=${query.environment}`
        }
      />
      {result.ok ? (
        <EngineView engine={result.data} />
      ) : (
        <Unavailable title="Analysis engine" reason={result.error} />
      )}
    </Page>
  );
}
