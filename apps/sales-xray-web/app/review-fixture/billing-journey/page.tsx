import { notFound } from "next/navigation";
import { Suspense } from "react";

import { BillingJourney } from "./billing-journey";

/** Local review and tutorial recordings only. Never available in a production build. */
export default function Page() {
  if (process.env.NODE_ENV !== "development") notFound();
  return (
    <Suspense fallback={null}>
      <BillingJourney />
    </Suspense>
  );
}
