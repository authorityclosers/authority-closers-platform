import { AdminShell } from "../components/admin-shell";
import { StudioToday } from "../components/studio/studio-runtime";

export default function StudioPage() {
  return (
    <AdminShell
      active="catalog"
      surface="studio"
      eyebrow="Academy Studio / today"
      title="Today’s content work"
      description="A tenant-scoped view of the actual draft backlog and publication readiness. Operational rates and capacity stay explicitly unavailable until canonical work-item data exists."
    >
      <StudioToday />
    </AdminShell>
  );
}
