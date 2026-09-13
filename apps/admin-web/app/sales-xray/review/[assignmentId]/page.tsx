import { academyAppOrigin } from "../review-api";
import { ReviewWorkspace } from "../review-workspace";

export const dynamic = "force-dynamic";

function configuredAcademyOrigin(): string | null {
  return academyAppOrigin(process.env.AC_PUBLIC_APP_URL);
}

export default async function AssignedReviewPage({
  params,
}: {
  params: Promise<{ assignmentId: string }>;
}) {
  const { assignmentId } = await params;
  return (
    <ReviewWorkspace
      assignmentId={assignmentId}
      academyOrigin={configuredAcademyOrigin()}
    />
  );
}
