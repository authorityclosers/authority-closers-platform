import { Suspense } from "react";

import { SummaryRoute, SummarySkeleton } from "./summary-page";

export default function Page() {
  return (
    <Suspense fallback={<SummarySkeleton />}>
      <SummaryRoute />
    </Suspense>
  );
}
