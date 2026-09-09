import { StudioProgram } from "@ac/operations-web/studio";
import { notFound } from "next/navigation";
export default async function Course({
  params,
}: {
  params: Promise<{ programId: string }>;
}) {
  const { programId } = await params;
  if (
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
      programId,
    )
  )
    notFound();
  return (
    <>
      <StudioProgram programId={programId} />
    </>
  );
}
