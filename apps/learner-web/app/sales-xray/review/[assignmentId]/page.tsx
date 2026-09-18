import { notFound } from "next/navigation";

export default async function AcademyAssignedReviewPage({
  params,
}: {
  params: Promise<{ assignmentId: string }>;
}) {
  await params;
  notFound();
}
