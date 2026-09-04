import { AdminShell } from "../../components/admin-shell";
import { StudioProgramList } from "../../components/studio/studio-runtime";

export default function StudioProgramsPage() {
  return (
    <AdminShell
      active="catalog"
      surface="studio"
      eyebrow="Academy Studio / content"
      title="Programs and versions"
      description="Inspect selected-tenant working versions and the immutable global library without exposing another tenant’s drafts."
    >
      <StudioProgramList />
    </AdminShell>
  );
}
