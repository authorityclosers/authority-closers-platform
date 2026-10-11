import { AdminShell } from "@/app/components/admin-shell";
import { AnalysisSettingsPanel } from "@/app/sales-xray/analysis-settings";

export const dynamic = "force-dynamic";

export default function AnalysisSettingsPage() {
  return (
    <AdminShell
      active="sales-xray"
      title="Analysis settings"
      description="Prompt versions, request limits and the default report language for new analyses."
    >
      <AnalysisSettingsPanel />
    </AdminShell>
  );
}
