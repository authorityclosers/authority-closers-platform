import { Suspense } from "react";

import { PerformanceRoute, PerformanceSkeleton } from "./performance-page";

export default function Page() {
  return (
    <Suspense fallback={<PerformanceSkeleton />}>
      <PerformanceRoute />
    </Suspense>
  );
}
