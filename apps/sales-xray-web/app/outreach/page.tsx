import { Suspense } from "react";

import { OutreachRoute, OutreachSkeleton } from "./outreach-page";

/** Outreach (v1.95): every message sent to leads, by whom. */
export default function Page() {
  return (
    <Suspense fallback={<OutreachSkeleton />}>
      <OutreachRoute />
    </Suspense>
  );
}
