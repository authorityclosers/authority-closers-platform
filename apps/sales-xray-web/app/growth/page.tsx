import { Suspense } from "react";

import {
  PerformanceRoute,
  PerformanceSkeleton,
} from "../performance/performance-page";

/** Growth (Dipak's tab bar, 31 Oct 2026): Analytics now, Coaching later. One
 *  word, as its tab: "My Growth" took two lines at 360 px, so the top bar grew
 *  on arrival (robot 2ac64000, 3 Nov 2026). No "Analytics" heading over the
 *  period switch: a one-word heading that does nothing (robot 7c4f00ca, 8 Nov). */
export default function Page() {
  return (
    <Suspense fallback={<PerformanceSkeleton title="Growth" />}>
      <PerformanceRoute title="Growth" />
    </Suspense>
  );
}
