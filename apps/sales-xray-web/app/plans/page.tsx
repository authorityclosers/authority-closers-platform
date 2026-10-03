import {
  PLANS_CATALOGUE_FIXTURE,
  PLANS_GST_RATE,
} from "./plans-catalogue-fixture";
import { PlansScreen } from "./plans-screen";

/** Choose a plan, pay, and manage the plan you are on. */
export default function PlansPage() {
  return (
    <PlansScreen plans={PLANS_CATALOGUE_FIXTURE} gstRate={PLANS_GST_RATE} />
  );
}
