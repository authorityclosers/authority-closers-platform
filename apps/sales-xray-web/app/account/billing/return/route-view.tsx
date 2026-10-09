import { Suspense } from "react";

import { OrderReturnPage } from "../../../plans/order-return-page";

/** Where the payment page sends the buyer back (contract C1: /account/billing/return?order=…). */
export default function BillingReturnPage() {
  return (
    <Suspense fallback={null}>
      <OrderReturnPage />
    </Suspense>
  );
}
