import { EconomicsView } from "@/app/economics/economics-view";
import {
  ENVIRONMENTS,
  WINDOWS,
  economicsQuery,
  normalizeEconomics,
} from "@/app/economics/economics-data";
import { PlanPricesPanel } from "@/app/economics/plan-prices";
import { normalizePlanPrices } from "@/app/economics/plan-prices-data";
import { adminRead } from "@/app/lib/server-api";
import { Page, PageHeader, QueryTabs, Unavailable } from "@/app/ui/kit";

export const dynamic = "force-dynamic";

/**
 * Admin → Economics (owner, 23 Oct 2026): what each plan earns after GST and fees, what its
 * minutes cost on each analysis route, margins, break-even against the fixed costs, top-ups
 * and the free trial. Read only; Admin only. Plan prices (owner, 29 Oct 2026): this
 * environment's prices, which only the owner changes.
 */
export default async function EconomicsPage({
  searchParams,
}: {
  searchParams: Promise<{ env?: string; days?: string }>;
}) {
  const { env, days } = await searchParams;
  const query = economicsQuery(env, days);
  const [result, prices] = await Promise.all([
    adminRead(query.path, normalizeEconomics),
    adminRead("/v1/admin/plan-prices", normalizePlanPrices),
  ]);
  return (
    <Page wide>
      <PageHeader
        title="Economics"
        context={[
          "What each plan earns after GST and the payment fee, what its minutes cost, and how many plans cover the fixed costs. List-price estimates for Admin only.",
        ]}
      />
      {prices.ok ? (
        <PlanPricesPanel prices={prices.data} />
      ) : (
        <Unavailable title="Plan prices" reason={prices.error} />
      )}
      <QueryTabs
        base="/economics"
        param="env"
        items={[...ENVIRONMENTS]}
        current={query.environment}
        keep={query.days === "30" ? undefined : `days=${query.days}`}
      />
      <QueryTabs
        base="/economics"
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
        <EconomicsView economics={result.data} />
      ) : (
        <Unavailable title="Economics" reason={result.error} />
      )}
    </Page>
  );
}
