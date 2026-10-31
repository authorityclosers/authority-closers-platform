import { Suspense } from "react";

import {
  PerformanceRoute,
  PerformanceSkeleton,
} from "../performance/performance-page";

/** My Growth (Dipak's tab bar, 31 Oct 2026): Analytics now, Coaching later. */
export default function Page() {
  return (
    <Suspense fallback={<PerformanceSkeleton title="My Growth" />}>
      <PerformanceRoute title="My Growth" section="Analytics" />
    </Suspense>
  );
}
