import { PlansOnWeb } from "../plans/plans-on-web";
import { PolicyPage } from "../policy-content";
import { PurchaseGate } from "../purchase-policy";

export default function PricingPage() {
  // Prices never show inside the Google Play app (purchase-policy.tsx).
  return (
    <PurchaseGate fallback={<PlansOnWeb />}>
      <PolicyPage slug="pricing" />
    </PurchaseGate>
  );
}
