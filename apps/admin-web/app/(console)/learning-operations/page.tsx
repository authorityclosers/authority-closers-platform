import { Workflow } from "lucide-react";

import { AdminShell } from "@/app/components/admin-shell";
import { Empty, List, Panel, Row, Why } from "@/app/ui/kit";

/**
 * Academy learning jobs: held side effects and restore reconciliation. The
 * commands exist (job retry, recovery reconcile) but there's no read of held
 * academy jobs to choose from, so this screen points to what works today.
 */
export default function LearningOperationsPage() {
  return (
    <AdminShell
      active="operations"
      title="Learning operations"
      description="Held academy jobs and restore reconciliation."
    >
      <Panel title="Sales Xray analyses">
        <List label="Where to go">
          <Row
            href="/health"
            title="Analysis health"
            meta={[
              "Failed and stuck analyses, with Retry for jobs that never reached a provider",
            ]}
          />
        </List>
      </Panel>
      <Panel
        title="Academy jobs"
        tools={
          <Why detail="A held job stays held until a named operator releases an explicit set, with a reason. Nothing is released in bulk." />
        }
      >
        <Empty
          icon={Workflow}
          title="No list of held academy jobs yet"
          text="Retrying a held job or reconciling a restore needs the exact job set from an operations read that isn't built. Until then, held academy jobs can’t be released from Admin."
        />
      </Panel>
    </AdminShell>
  );
}
