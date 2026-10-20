import { Suspense } from "react";

import { LeadsRoute } from "./leads-page";
import { LeadsSkeleton } from "./leads-skeleton";

export default function Page() {
  return (
    <Suspense fallback={<LeadsSkeleton />}>
      <LeadsRoute />
    </Suspense>
  );
}
