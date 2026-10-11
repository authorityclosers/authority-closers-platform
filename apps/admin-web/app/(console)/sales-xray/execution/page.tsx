import { AdminShell } from "@/app/components/admin-shell";
import { ExecutionControlsPanel } from "@/app/sales-xray/execution-controls";

export const dynamic = "force-dynamic";

export default function ExecutionPage() {
  return (
    <AdminShell
      active="sales-xray"
      title="Execution & budget"
      description="Pause or resume new analyses, and set the shared spend limit."
    >
      <ExecutionControlsPanel />
    </AdminShell>
  );
}
