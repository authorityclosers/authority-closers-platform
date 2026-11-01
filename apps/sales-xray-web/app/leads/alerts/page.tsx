import { Suspense } from "react";

import { AlertsRoute, AlertsSkeleton } from "./alerts-page";

export default function Page() {
  return (
    <Suspense fallback={<AlertsSkeleton />}>
      <AlertsRoute />
    </Suspense>
  );
}
