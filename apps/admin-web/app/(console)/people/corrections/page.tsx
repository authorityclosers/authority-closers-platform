import { FileCheck2 } from "lucide-react";

import { AdminShell } from "@/app/components/admin-shell";
import { Empty, Panel, Why } from "@/app/ui/kit";

/**
 * Progress corrections append a superseding learning event; they never edit
 * evidence. The command exists in the API (POST /v1/admin/corrections) but
 * needs an audited way to find the exact submission first, so the screen says
 * what's missing instead of showing a form that can't be sent.
 */
export default function CorrectionsPage() {
  return (
    <AdminShell
      active="people"
      activeSupport="correction"
      title="Progress corrections"
      description="Correct a learner's recorded progress without erasing the original."
    >
      <Panel
        title="Not connected yet"
        tools={
          <Why detail="A correction is a new fact that supersedes the old one, with who, why and when. Original evidence stays." />
        }
      >
        <Empty
          icon={FileCheck2}
          title="Corrections need an audited lookup first"
          text="To correct progress, Admin must first find the exact submission through an audited learner lookup; that lookup isn't connected to this screen yet. Until it is, corrections can’t be made from Admin."
          action={{ href: "/people", label: "Go to People" }}
        />
      </Panel>
    </AdminShell>
  );
}
