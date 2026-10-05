"use client";

import { useEffect, useState } from "react";
import { liveBilling, type BillingClient } from "../billing/billing-api";
import { onSale, type Plan } from "../billing/contract";
import { useBillingAccount } from "../billing/use-billing-account";
import { useWorkspaceAccess } from "../workspace-access";
import { usePurchaseCheckout } from "./use-purchase-checkout";
import {
  PLANS_CATALOGUE_FIXTURE,
  PLANS_GST_RATE,
  TOP_UP_PACKS,
} from "./plans-catalogue-fixture";
import {
  PlansScreen,
  type PlanSelection,
  type PurchaseQuote,
  type TopUpPack,
} from "./plans-screen";

/** Remount on account/workspace changes so an old order cannot cross identities. */
export function PlansPurchase({
  client = liveBilling,
  quote,
}: {
  client?: BillingClient;
  quote?: PurchaseQuote | null;
}) {
  const access = useWorkspaceAccess();
  return (
    <Purchase
      key={JSON.stringify([access?.authenticated, access?.context])}
      client={client}
      quote={quote}
    />
  );
}

function Purchase({
  client,
  quote,
}: {
  client: BillingClient;
  quote?: PurchaseQuote | null;
}) {
  const billing = useBillingAccount(true, client);
  const [catalogue, setCatalogue] = useState<Plan[] | null>(null);
  const { prepared, busy, error, select, buy } = usePurchaseCheckout(client);

  useEffect(() => {
    const controller = new AbortController();
    client
      .readPlans(controller.signal)
      .then((plans) => {
        if (!controller.signal.aborted && plans.some(onSale))
          setCatalogue(plans);
      })
      .catch(() => {}); // Keep the owner-approved display catalogue until plans are on sale.
    return () => {
      controller.abort();
    };
  }, [client]);

  const buyPlan = (selection: PlanSelection) =>
    void buy({
      kind: "subscription",
      account: selection.planKey === "personal" ? "personal" : "organisation",
      ...selection,
    });
  const buyTopUp = (pack: TopUpPack) =>
    void buy({
      kind: "top_up",
      account: pack.planKey === "personal" ? "personal" : "organisation",
      planKey: pack.planKey,
      packKey: pack.key,
    });
  return (
    <PlansScreen
      plans={catalogue ?? PLANS_CATALOGUE_FIXTURE}
      gstRate={PLANS_GST_RATE}
      mePlan={billing.mePlan}
      quote={quote}
      onSelectionChange={select}
      onBuy={buyPlan}
      onBuyTopUp={buyTopUp}
      checkoutOrder={prepared?.order}
      checkoutProvider={prepared?.hosted.provider}
      topUpPacks={
        catalogue
          ? catalogue.filter(onSale).flatMap((plan) =>
              plan.topUpPacks
                .filter((pack) => pack.pricePaise !== null)
                .map((pack) => ({
                  key: pack.key,
                  planKey: plan.key,
                  title: `${plan.name} Top-up`,
                  audience: plan.audience,
                  minutes: pack.minutes,
                  pricePaise: pack.pricePaise!,
                  gstInclusive: plan.key === "personal",
                })),
            )
          : TOP_UP_PACKS
      }
      busy={busy}
      error={error}
    />
  );
}
