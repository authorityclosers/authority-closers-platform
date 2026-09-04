import { AdminShell } from "../../../components/admin-shell";
import { StudioProgram } from "../../../components/studio/studio-runtime";

export default async function StudioProgramPage({
  params,
}: {
  params: Promise<{ programId: string }>;
}) {
  const { programId } = await params;
  return (
    <AdminShell
      active="catalog"
      surface="studio"
      eyebrow="Academy Studio / program"
      title="Program readiness"
      description="Review version provenance, topology, publication blockers, and the exact guarded publish transition."
    >
      <StudioProgram programId={programId} />
    </AdminShell>
  );
}
