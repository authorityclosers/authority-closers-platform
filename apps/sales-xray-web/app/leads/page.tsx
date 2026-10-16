import { Suspense } from "react";

import { LeadsRoute, LeadsSkeleton } from "./leads-page";

export default function Page() {
  return (
    <Suspense fallback={<LeadsSkeleton />}>
      <LeadsRoute />
    </Suspense>
  );
}
