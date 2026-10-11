import { AdminShell } from "@/app/components/admin-shell";
import { BenchmarkCenterPanel } from "@/app/sales-xray/benchmark-center";
import { ControlCenterPanel } from "@/app/sales-xray/control-center";
import { ProviderControlsPanel } from "@/app/sales-xray/provider-controls";
import { QueryTabs } from "@/app/ui/kit";

export const dynamic = "force-dynamic";

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "providers", label: "Providers and routes" },
  { key: "benchmark", label: "Benchmark" },
];

export default async function ProvidersPage({
  searchParams,
}: {
  searchParams: Promise<{ tab?: string }>;
}) {
  const { tab } = await searchParams;
  const current = TABS.some((item) => item.key === tab) ? tab! : "overview";
  return (
    <AdminShell
      active="sales-xray"
      title="Providers & costs"
      description="Which models analyse calls, what each step may cost, and how they compare."
    >
      <QueryTabs base="/sales-xray/providers" items={TABS} current={current} />
      {current === "providers" ? (
        <ProviderControlsPanel />
      ) : current === "benchmark" ? (
        <BenchmarkCenterPanel />
      ) : (
        <ControlCenterPanel />
      )}
    </AdminShell>
  );
}
