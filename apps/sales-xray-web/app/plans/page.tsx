import { PurchaseGate } from "../purchase-policy";
import { PlansOnWeb } from "./plans-on-web";
import { PlansPurchase } from "./plans-purchase";

/** Choose a plan, pay, and manage the plan you are on (never inside the Google Play app). */
export default function PlansPage() {
  return (
    <PurchaseGate fallback={<PlansOnWeb />}>
      <PlansPurchase />
    </PurchaseGate>
  );
}
