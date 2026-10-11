import { academyAppOrigin } from "@/app/sales-xray/review/review-api";
import { ReviewWorkspace } from "@/app/sales-xray/review/review-workspace";

export const dynamic = "force-dynamic";

/** Outside reviewers: invitations and assignments for one saved analysis each. */
export default function ReviewersPage() {
  return (
    <ReviewWorkspace
      academyOrigin={academyAppOrigin(process.env.AC_PUBLIC_APP_URL)}
    />
  );
}
