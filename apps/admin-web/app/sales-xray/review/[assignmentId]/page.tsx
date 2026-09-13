import { ReviewWorkspace } from "../review-workspace";

export default async function AssignedReviewPage({
  params,
}: {
  params: Promise<{ assignmentId: string }>;
}) {
  const { assignmentId } = await params;
  return <ReviewWorkspace assignmentId={assignmentId} />;
}
