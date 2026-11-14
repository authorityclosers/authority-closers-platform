import { Suspense } from "react";

import {
  ReportLibrary,
  ReportsSkeleton,
} from "../../report-library/report-library";

/**
 * Reports, the phone's Reports tab: Dipak's Reports V4 (13 Nov 2026), in
 * report-library.tsx. The phone's own calls are its "Your phone calls" view.
 */
export default function AnalysisCallsPage() {
  return (
    <Suspense fallback={<ReportsSkeleton />}>
      <ReportLibrary />
    </Suspense>
  );
}
