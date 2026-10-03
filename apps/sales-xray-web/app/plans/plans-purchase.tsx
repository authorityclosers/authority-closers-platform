"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  BillingError,
  idempotencyKey,
  liveBilling,
  notOnSale,
  returnPath,
  type BillingClient,
  type CheckoutRequest,
} from "../billing/billing-api";
import { onSale, type Checkout, type Plan } from "../billing/contract";
import { useBillingAccount } from "../billing/use-billing-account";
import { useWorkspaceAccess } from "../workspace-access";
import { openHostedCheckout } from "./hosted-checkout";
import {
  PLANS_CATALOGUE_FIXTURE,
  PLANS_GST_RATE,
  TOP_UP_PACKS,
} from "./plans-catalogue-fixture";
import {
  PlansScreen,
  type PlanSelection,
  type TopUpPack,
} from "./plans-screen";

/** Remount on account/workspace changes so an old order cannot cross identities. */
export function PlansPurchase({
  client = liveBilling,
}: {
  client?: BillingClient;
}) {
  const access = useWorkspaceAccess();
  return (
    <Purchase
      key={JSON.stringify([access?.authenticated, access?.context])}
      client={client}
    />
  );
}

function Purchase({ client }: { client: BillingClient }) {
  const router = useRouter();
  const access = useWorkspaceAccess();
  const billing = useBillingAccount(true, client);
  const [catalogue, setCatalogue] = useState<Plan[] | null>(null);
  const [prepared, setPrepared] = useState<Checkout | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const attempt = useRef<{
    fingerprint: string;
    key: string;
    checkout?: Checkout;
  } | null>(null);
  const inFlight = useRef(false);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    const controller = new AbortController();
    client
      .readPlans(controller.signal)
      .then((plans) => {
        if (!controller.signal.aborted && plans.some(onSale))
          setCatalogue(plans);
      })
      .catch(() => {}); // Keep the owner-approved display catalogue until plans are on sale.
    return () => {
      alive.current = false;
      controller.abort();
    };
  }, [client]);

  const select = () => {
    attempt.current = null;
    setPrepared(null);
    setError(null);
  };
  const buy = async (request: CheckoutRequest) => {
    if (inFlight.current) return;
    if (access?.authenticated !== true) {
      if (access?.requestAccountSignIn) access.requestAccountSignIn();
      else router.push("/login?returnTo=%2Fplans");
      return;
    }
    inFlight.current = true;
    setBusy(true);
    setError(null);
    const fingerprint = JSON.stringify(request);
    const expiresAt = attempt.current?.checkout?.hosted.expiresAt;
    if (expiresAt && Date.parse(expiresAt) <= Date.now()) {
      attempt.current = null;
      setPrepared(null);
    }
    if (attempt.current?.fingerprint !== fingerprint)
      attempt.current = { fingerprint, key: idempotencyKey() };
    const current = attempt.current;
    try {
      if (!current.checkout) {
        const checkout = await client.checkout(request, current.key);
        if (!alive.current || attempt.current !== current) return;
        current.checkout = checkout;
        setPrepared(checkout); // Review the server's amount and tax before leaving for payment.
        return;
      }
      const result = await openHostedCheckout(
        current.checkout.hosted,
        current.checkout.order.orderId,
      );
      if (alive.current && result !== "left")
        router.push(returnPath(current.checkout.order.orderId));
    } catch (error) {
      if (alive.current)
        setError(
          notOnSale(error)
            ? "Payments are currently unavailable. Please try again later."
            : error instanceof BillingError && error.detail
              ? error.detail
              : "Checkout could not be opened. Please try again.",
        );
    } finally {
      inFlight.current = false;
      if (alive.current) setBusy(false);
    }
  };

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
      onSelectionChange={select}
      onBuy={buyPlan}
      onBuyTopUp={buyTopUp}
      checkoutOrder={prepared?.order}
      topUpPacks={
        catalogue
          ? catalogue
              .filter(onSale)
              .flatMap((plan) =>
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
