import { ReviewerAssignmentAdapter } from "../reviewer-assignment-adapter";

export const dynamic = "force-dynamic";

export default async function ReviewerAssignmentPage({ params }: { params: Promise<{ assignmentId: string }> }) {
  const { assignmentId } = await params;
  return <ReviewerAssignmentAdapter assignmentId={assignmentId} />;
}
