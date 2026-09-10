import { AdminShell } from "../../components/admin-shell";
import { StudioProgramList } from "../../components/studio/studio-runtime";

export default function StudioProgramsPage() {
  return (
    <AdminShell
      active="catalog"
      surface="studio"
      eyebrow="Academy Studio / content"
      title="Programs and versions"
      description="Review the programs and versions available within your current Studio access."
    >
      <StudioProgramList />
    </AdminShell>
  );
}
