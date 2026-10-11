import { KeyRound } from "lucide-react";

import { AdminShell } from "@/app/components/admin-shell";
import { Empty, Panel, Why } from "@/app/ui/kit";

/** Manual course access (POST /v1/admin/enrollment-grants) waits for the same audited lookup. */
export default function GrantsPage() {
  return (
    <AdminShell
      active="people"
      activeSupport="grant"
      title="Course access"
      description="Give a learner access to a course version by hand, with a reason."
    >
      <Panel
        title="Not connected yet"
        tools={
          <Why detail="Enrollment and permission to see content are separate; a grant records who gave access, to what, and why." />
        }
      >
        <Empty
          icon={KeyRound}
          title="Course access needs an audited lookup first"
          text="Granting access needs the exact learner and course version from an audited lookup, which isn't connected to this screen yet. Until then, course access can’t be granted from Admin."
          action={{ href: "/people", label: "Go to People" }}
        />
      </Panel>
    </AdminShell>
  );
}
