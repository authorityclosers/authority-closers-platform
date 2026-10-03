"use client";

import { useState } from "react";
import { BillingView } from "../../../billing/billing-view";
import type { MePlan, Order, Subscription } from "../../../billing/contract";
import { planPrice } from "../../../billing/money";
import {
  PLANS_CATALOGUE_FIXTURE,
  PLANS_GST_RATE,
} from "../../../plans/plans-catalogue-fixture";
import {
  PlansScreen,
  type PlanSelection,
  type PurchaseQuote,
} from "../../../plans/plans-screen";
import styles from "../../../plans/plans.module.css";

/** Development-only prop fixtures. No API, account, provider or payment exists. */
export function PurchaseScreensFixture() {
  const [billing, setBilling] = useState(false);
  const [quote, setQuote] = useState<PurchaseQuote | null>(null);
  const [order, setOrder] = useState<Order | null>(null);
  const [cancelled, setCancelled] = useState(false);
  const select = (selection: PlanSelection) => {
    const plan = PLANS_CATALOGUE_FIXTURE.find(
      (item) => item.key === selection.planKey,
    )!;
    const subtotalPaise =
      planPrice(plan, selection.interval)! * selection.seats;
    const gstPaise =
      plan.key === "personal" ? 0 : Math.round(subtotalPaise * PLANS_GST_RATE);
    setQuote({
      selection,
      subtotalPaise,
      gstPaise,
      totalPaise: subtotalPaise + gstPaise,
      renewsAt:
        selection.interval === "month"
          ? "2026-11-03T00:00:00Z"
          : "2027-10-03T00:00:00Z",
    });
  };
  const buy = (selection: PlanSelection) => {
    const plan = PLANS_CATALOGUE_FIXTURE.find(
      (item) => item.key === selection.planKey,
    )!;
    if (!quote) return;
    setOrder({
      orderId: "fictional-order",
      kind: "subscription",
      account: plan.key === "personal" ? "personal" : "organisation",
      status: "paid",
      mode: "test",
      amount: { minor: quote.totalPaise, currency: "INR", gstInclusive: true },
      planKey: plan.key,
      planName: plan.name,
      interval: selection.interval,
      seats: selection.seats,
      packKey: null,
      minutes: plan.includedMinutes! * selection.seats,
      subscriptionId: "fictional-subscription",
      createdAt: "2026-10-03T00:00:00Z",
      paidAt: "2026-10-03T00:00:00Z",
      refund: null,
    });
  };
  const mePlan: MePlan = {
    plan: { key: order?.planKey ?? "trial", name: order?.planName ?? "Trial" },
    allowance: {
      allowanceSeconds: (order?.minutes ?? 100) * 60,
      committedSeconds: 0,
      availableSeconds: (order?.minutes ?? 100) * 60,
      unlimited: false,
    },
    longestCallSeconds: (order?.planKey === "enterprise" ? 120 : 90) * 60,
  };
  const subscription: Subscription | null =
    order && quote
      ? {
          subscriptionId: "fictional-subscription",
          account: order.account,
          planKey: order.planKey,
          planName: order.planName,
          interval: order.interval!,
          seats: order.seats,
          amount: order.amount,
          mode: "test",
          status: "active",
          currentPeriod: { start: order.createdAt, end: quote.renewsAt },
          renewsAt: quote.renewsAt,
          cancelAtPeriodEnd: cancelled,
          cancelState: cancelled ? "confirmed" : "none",
          renewalNeedsCustomerApproval: false,
          createdAt: order.createdAt,
        }
      : null;
  return (
    <>
      <p role="note">
        Development fixture · fictional account, payment and documents · no
        money is taken.{" "}
        <button
          type="button"
          className={styles.copy}
          onClick={() => setBilling(!billing)}
        >
          {billing ? "Show Plans" : "Show Billing"}
        </button>
      </p>
      {billing ? (
        <BillingView
          mePlan={mePlan}
          subs={{ current: subscription, past: [] }}
          status="ready"
          onCancel={() => setCancelled(true)}
          onRefresh={() => {}}
          documents={
            order
              ? [
                  {
                    id: order.orderId,
                    createdAt: order.createdAt,
                    description: `Fictional ${order.planName} purchase`,
                    amount: order.amount,
                    status: "Paid (fictional)",
                    invoiceHref: "#fixture-document",
                    receiptHref: "#fixture-document",
                  },
                ]
              : []
          }
        />
      ) : (
        <PlansScreen
          plans={PLANS_CATALOGUE_FIXTURE}
          gstRate={PLANS_GST_RATE}
          mePlan={mePlan}
          quote={quote}
          onSelectionChange={select}
          onBuy={buy}
          paidOrder={order}
          allowance={order ? mePlan.allowance : null}
        />
      )}
      {billing && order ? (
        <section id="fixture-document">
          <h2>Fictional invoice and receipt</h2>
          <p>Visual review only. This is not a tax invoice or a receipt.</p>
        </section>
      ) : null}
    </>
  );
}
