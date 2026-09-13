import { LearnerShell } from "../../../components/site-shell";
import { ReviewAssignmentAdapter } from "../review-assignment-adapter";

export default async function AcademyAssignedReviewPage({
  params,
}: {
  params: Promise<{ assignmentId: string }>;
}) {
  const { assignmentId } = await params;
  return (
    <LearnerShell current="sales-xray">
      <ReviewAssignmentAdapter assignmentId={assignmentId} />
    </LearnerShell>
  );
}
