import { notFound } from "next/navigation";

import { Page, PageHeader } from "../../ui/kit";
import { BillingFixtureView } from "./billing-fixture-view";

/**
 * Local review of Admin -> Platform -> Billing (no API, no account): Revenue with dev's test-mode
 * totals from fictional buyers, and the Billing lists with fictional rows. Never in a production
 * build.
 */
export default function BillingFixturePage() {
  if (process.env.NODE_ENV !== "development") notFound();
  return (
    <Page>
      <PageHeader
        title="Billing"
        context={["Fixture: fictional buyers, test payments"]}
      />
      <BillingFixtureView />
    </Page>
  );
}
