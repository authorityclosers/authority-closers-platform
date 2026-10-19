import { adminRead } from "@/app/lib/server-api";
import { Page, PageHeader, QueryTabs, Unavailable } from "@/app/ui/kit";
import {
  ENVIRONMENTS,
  chartView,
  normalizeMetrics,
} from "@/app/usage/cost-data";
import {
  COST_WINDOWS,
  CallsView,
  CostFilters,
  MoneyView,
  OverviewView,
  PipelinesView,
  ProvidersView,
  RevenueView,
  Sources,
  type CostFilter,
} from "@/app/usage/cost-views";
import { ProductEvents } from "@/app/usage/product-events";

export const dynamic = "force-dynamic";

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "calls", label: "Per call" },
  { key: "revenue", label: "Revenue vs cost" },
  { key: "providers", label: "Providers" },
  { key: "pipelines", label: "Pipelines" },
  { key: "money", label: "Money health" },
  { key: "events", label: "Product events" },
];

type Query = {
  tab?: string;
  days?: string;
  env?: string;
  tests?: string;
  a?: string;
  b?: string;
  charts?: string;
  ca?: string;
  cb?: string;
  sort?: string;
};

const pick = (
  value: string | undefined,
  allowed: readonly string[],
  fallback: string,
) => (value !== undefined && allowed.includes(value) ? value : fallback);

export default async function UsagePage({
  searchParams,
}: {
  searchParams: Promise<Query>;
}) {
  const query = await searchParams;
  const current: CostFilter = {
    tab: pick(
      query.tab,
      TABS.map((item) => item.key),
      "overview",
    ),
    days: pick(
      query.days,
      COST_WINDOWS.map((item) => item.key),
      "30",
    ),
    env: pick(query.env, ["all", ...ENVIRONMENTS], "all"),
    tests: query.tests === "1",
    // The Overview's chosen charts and compared pair (owner, 19 Oct 2026).
    ...chartView(query),
  };
  const keep = [
    current.days !== "30" ? `days=${current.days}` : "",
    current.env !== "all" ? `env=${current.env}` : "",
    current.tests ? "tests=1" : "",
  ]
    .filter(Boolean)
    .join("&");
  const events = current.tab === "events";
  const result = events
    ? null
    : await adminRead(
        `/v1/admin/conversation/metrics?days=${current.days}&env=${current.env}&tests=${current.tests ? 1 : 0}${
          current.tab === "calls"
            ? `&sort=${current.sort ?? "newest"}&steps=1`
            : ""
        }`,
        normalizeMetrics,
      );
  const metrics = result?.ok ? result.data : null;
  return (
    <Page wide>
      <PageHeader
        title="Usage & cost"
        context={[
          "What Sales X-Ray costs and earns in every environment",
          "list prices, not invoices",
        ]}
      />
      <QueryTabs base="/usage" items={TABS} current={current.tab} keep={keep} />
      <CostFilters current={current} whenOnly={events} />
      {events ? <ProductEvents days={current.days} /> : null}
      {result && !result.ok ? (
        <Unavailable title="Usage & cost" reason={result.error} />
      ) : null}
      {metrics ? (
        <>
          <Sources metrics={metrics} />
          {current.tab === "overview" ? (
            <OverviewView metrics={metrics} current={current} />
          ) : null}
          {current.tab === "calls" ? (
            <CallsView metrics={metrics} current={current} />
          ) : null}
          {current.tab === "revenue" ? <RevenueView metrics={metrics} /> : null}
          {current.tab === "providers" ? (
            <ProvidersView metrics={metrics} />
          ) : null}
          {current.tab === "pipelines" ? (
            <PipelinesView
              metrics={metrics}
              current={current}
              a={query.a}
              b={query.b}
            />
          ) : null}
          {current.tab === "money" ? <MoneyView metrics={metrics} /> : null}
        </>
      ) : null}
    </Page>
  );
}
