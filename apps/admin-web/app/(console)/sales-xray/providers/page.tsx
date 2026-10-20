import { AdminShell } from "@/app/components/admin-shell";
import { adminRead } from "@/app/lib/server-api";
import { BenchmarkCenterPanel } from "@/app/sales-xray/benchmark-center";
import { ControlCenterPanel } from "@/app/sales-xray/control-center";
import { ProviderControlsPanel } from "@/app/sales-xray/provider-controls";
import { ProviderHub } from "@/app/sales-xray/provider-hub";
import { normalizeHub } from "@/app/sales-xray/provider-hub-data";
import { QueryTabs, Unavailable } from "@/app/ui/kit";

export const dynamic = "force-dynamic";

const TABS = [
  { key: "hub", label: "Providers" },
  { key: "overview", label: "Overview" },
  { key: "providers", label: "Routes (advanced)" },
  { key: "benchmark", label: "Benchmark" },
];

const PROVIDER_ID = /^[a-z_]{1,32}$/;

export default async function ProvidersPage({
  searchParams,
}: {
  searchParams: Promise<{ tab?: string; provider?: string }>;
}) {
  const { tab, provider } = await searchParams;
  const current = TABS.some((item) => item.key === tab) ? tab! : "hub";
  const chosen = provider && PROVIDER_ID.test(provider) ? provider : null;
  const hub =
    current === "hub"
      ? await adminRead(
          `/v1/admin/providers/hub${chosen ? `?provider=${chosen}` : ""}`,
          normalizeHub,
        )
      : null;
  return (
    <AdminShell
      active="sales-xray"
      title="Providers & costs"
      description="Find a provider, see every model it offers and what each costs, and which models analyse calls."
    >
      <QueryTabs base="/sales-xray/providers" items={TABS} current={current} />
      {current === "hub" ? (
        hub?.ok ? (
          <ProviderHub hub={hub.data} />
        ) : (
          <Unavailable
            title="The Providers hub"
            reason={hub?.error ?? "Not read"}
          />
        )
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
