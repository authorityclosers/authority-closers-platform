import { AdminShell } from "@/app/components/admin-shell";
import { read } from "@/app/lib/read";
import { adminRead } from "@/app/lib/server-api";
import { BenchmarkCenterPanel } from "@/app/sales-xray/benchmark-center";
import { normalizeCallData } from "@/app/sales-xray/call-data-model";
import { ControlCenterPanel } from "@/app/sales-xray/control-center";
import { ProviderControlsPanel } from "@/app/sales-xray/provider-controls";
import { ProviderHub } from "@/app/sales-xray/provider-hub";
import {
  modelPrices,
  normalizeHealth,
  normalizeHub,
} from "@/app/sales-xray/provider-hub-data";
import { StageAssignments } from "@/app/sales-xray/stage-assignments";
import { normalizeRegistry } from "@/app/settings/registry-data";
import { QueryTabs, Unavailable } from "@/app/ui/kit";
import { normalizeMetrics } from "@/app/usage/cost-data";

export const dynamic = "force-dynamic";

const TABS = [
  { key: "hub", label: "Providers" },
  { key: "overview", label: "Overview" },
  { key: "providers", label: "Routes (advanced)" },
  { key: "benchmark", label: "Benchmark" },
];

const PROVIDER_ID = /^[a-z_]{1,32}$/;

/** The hub, its health here, and who does each job: read together so the page arrives whole. */
async function readHub(chosen: string | null) {
  const [hub, health, registry, callData, leadAi, metrics] = await Promise.all([
    adminRead(
      `/v1/admin/providers/hub${chosen ? `?provider=${chosen}` : ""}`,
      normalizeHub,
    ),
    adminRead("/v1/admin/providers/health", normalizeHealth),
    adminRead("/v1/admin/settings", normalizeRegistry),
    adminRead("/v1/admin/call-data", read.object),
    adminRead("/v1/admin/lead-desk-ai", read.object),
    adminRead(
      "/v1/admin/conversation/metrics?days=30&env=all&tests=0",
      normalizeMetrics,
    ),
  ]);
  // Each area's answer by its route: the setting controls change from these.
  const answers: Record<string, unknown> = {};
  if (callData.ok) answers["/v1/admin/call-data"] = callData.data;
  if (leadAi.ok) answers["/v1/admin/lead-desk-ai"] = leadAi.data;
  return {
    hub,
    // An older server without the health read still shows the hub.
    health: health.ok ? health.data : null,
    settings: registry.ok ? registry.data.settings : [],
    answers,
    prices: callData.ok
      ? modelPrices(normalizeCallData(callData.data).models)
      : [],
    metrics: metrics.ok ? metrics.data : null,
  };
}

export default async function ProvidersPage({
  searchParams,
}: {
  searchParams: Promise<{ tab?: string; provider?: string }>;
}) {
  const { tab, provider } = await searchParams;
  const current = TABS.some((item) => item.key === tab) ? tab! : "hub";
  const chosen = provider && PROVIDER_ID.test(provider) ? provider : null;
  const data = current === "hub" ? await readHub(chosen) : null;
  return (
    <AdminShell
      active="sales-xray"
      title="Providers & costs"
      description="Find a provider, see every model it offers and what each costs, and which models do each job."
    >
      <QueryTabs base="/sales-xray/providers" items={TABS} current={current} />
      {data ? (
        <>
          <StageAssignments
            metrics={data.metrics}
            settings={data.settings}
            answers={data.answers}
            prices={data.prices}
          />
          {data.hub.ok ? (
            <ProviderHub hub={data.hub.data} health={data.health} />
          ) : (
            <Unavailable title="The Providers hub" reason={data.hub.error} />
          )}
        </>
      ) : current === "providers" ? (
        <ProviderControlsPanel />
      ) : current === "benchmark" ? (
        <BenchmarkCenterPanel />
      ) : (
        <ControlCenterPanel />
      )}
    </AdminShell>
  );
}
