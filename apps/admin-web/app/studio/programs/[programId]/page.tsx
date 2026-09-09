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
      eyebrow="Academy Studio"
      title="Course studio"
      description="Shape your course, preview the learning experience, and prepare each version for publication."
    >
      <StudioProgram programId={programId} />
    </AdminShell>
  );
}
