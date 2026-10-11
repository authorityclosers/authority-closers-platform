import { academyAppOrigin } from "@/app/sales-xray/review/review-api";
import { ReviewWorkspace } from "@/app/sales-xray/review/review-workspace";

export const dynamic = "force-dynamic";

function configuredAcademyOrigin(): string | null {
  return academyAppOrigin(process.env.AC_PUBLIC_APP_URL);
}

export default function ReviewAssignmentsPage() {
  return <ReviewWorkspace academyOrigin={configuredAcademyOrigin()} />;
}
