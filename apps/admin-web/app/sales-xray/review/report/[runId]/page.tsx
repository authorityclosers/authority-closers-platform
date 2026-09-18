import { AdminReportPage } from "../../admin-report";

export const dynamic = "force-dynamic";

export default async function AdminReportRoute({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  const { runId } = await params;
  return <AdminReportPage runId={runId} />;
}
