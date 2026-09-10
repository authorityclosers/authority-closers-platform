import { AdminShell } from "../../../components/admin-shell";
import { StudioProgram } from "../../../components/studio/studio-runtime";
import { notFound } from "next/navigation";

export default async function StudioProgramPage({
  params,
}: {
  params: Promise<{ programId: string }>;
}) {
  const { programId } = await params;
  const canonicalProgramId = programId.toLowerCase();
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(
      canonicalProgramId,
    )
  )
    notFound();
  return (
    <AdminShell
      active="catalog"
      surface="studio"
      eyebrow="Academy Studio"
      title="Course studio"
      description="Shape your course, preview the learning experience, and prepare each version for publication."
    >
      <StudioProgram programId={canonicalProgramId} />
    </AdminShell>
  );
}
