import { Suspense } from "react";

import { ReportsRoute, ReportsSkeleton } from "./reports-page";

export default function Page() {
  return (
    <Suspense fallback={<ReportsSkeleton />}>
      <ReportsRoute />
    </Suspense>
  );
}
