"use client";

import { LockKeyhole } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  useEffect,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { BillingView } from "../../billing/billing-view";
import type { Order } from "../../billing/contract";
import { count, formatMoney } from "../../billing/money";
import { useBillingAccount } from "../../billing/use-billing-account";

import { OrderReturn } from "../../plans/order-return";
import { PlansPurchase } from "../../plans/plans-purchase";
import plansStyles from "../../plans/plans.module.css";
import { WorkspaceAccessProvider } from "../../workspace-access";
import {
  FIXTURE_RETURN_PATH,
  fixtureBilling,
  fixtureAccount,
  fixtureProviderReports,
  fixtureRecording,
  resetFixtureBilling,
} from "./fixture-billing";
import styles from "../shell/full-shell-preview.module.css";

/** Fictional identity: never a real person, session or workspace. */
export const FIXTURE_ACCESS = {
  status: "ready" as const,
  authenticated: true,
  context: {
    personId: "fixture-person",
    sessionId: "fixture-session",
    tenantId: "fixture-workspace",
  },
  retry: () => {},
};

const noSubscription = () => () => {};

function Banner() {
  const router = useRouter();
  // Hidden while a tutorial is recorded (set on the billing journey page).
  const recording = useSyncExternalStore(
    noSubscription,
    fixtureRecording,
    () => false,
  );
  if (recording) return null;
  return (
    <p className={styles.banner} role="note">
      Development fixture · fictional plans, orders and payment · nothing here
      can take money ·{" "}
      <button
        type="button"
        className={plansStyles.copy}
        onClick={() => {
          resetFixtureBilling();
          router.push("/review-fixture/plans");
          router.refresh();
        }}
      >
        Start again
      </button>
      {" · "}
      <button
        type="button"
        className={plansStyles.copy}
        onClick={() => router.push("/review-fixture/plans?view=billing")}
      >
        Manage billing
      </button>
    </p>
  );
}

/** The fictional workspace, as the plans and billing screens see it. */
export function FixtureWorkspace({ children }: { children: ReactNode }) {
  return (
    <WorkspaceAccessProvider
      value={{
        ...FIXTURE_ACCESS,
        workspaces: [
          {
            tenant_id: "fixture-workspace",
            kind: fixtureAccount(),
            name: "Fictional workspace",
            role: "owner",
            sales_xray_enabled: true,
          },
        ],
      }}
    >
      {children}
    </WorkspaceAccessProvider>
  );
}

/** The plans screens on the fictional billing server. */
export function PlansFixture() {
  const params = useSearchParams();
  return (
    <FixtureWorkspace>
      <Banner />
      {params.get("view") === "billing" ? (
        <FixtureBilling />
      ) : (
        <PlansPurchase client={fixtureBilling} />
      )}
    </FixtureWorkspace>
  );
}

export function FixtureBilling() {
  const billing = useBillingAccount(true, fixtureBilling);
  return <BillingView {...billing} />;
}

/** A stand-in for the payment partner's page: it only reports an outcome. */
export function PayFixture() {
  const params = useSearchParams();
  return <PayPage orderId={params.get("order") ?? ""} />;
}

export function PayPage({ orderId }: { orderId: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [order, setOrder] = useState<Order | null>(null);
  useEffect(() => {
    if (!orderId) return;
    let live = true;
    fixtureBilling
      .readOrder(orderId)
      .then((value) => {
        if (live) setOrder(value);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [orderId]);
  const report = (outcome: "paid" | "failed") => {
    setBusy(true);
    fixtureProviderReports(orderId, outcome);
    router.push(`${FIXTURE_RETURN_PATH}?order=${encodeURIComponent(orderId)}`);
  };
  const amount = order ? formatMoney(order.amount) : null;
  return (
    <div className={`${plansStyles.page} ${plansStyles.testPayPage}`}>
      <Banner />
      <div className={`${plansStyles.panel} ${plansStyles.result}`}>
        <span className={plansStyles.testPayTag}>
          <LockKeyhole size={14} aria-hidden="true" />
          Test payment page
        </span>
        <h2>{amount ? `Pay ${amount}` : "Test payment"}</h2>
        <p className={plansStyles.hint}>
          In the app this step is the payment partner&apos;s secure page. Here
          no money moves: choose what the partner reports back.
        </p>
        {order ? (
          <dl className={`${plansStyles.rows} ${plansStyles.receipt}`}>
            <div>
              <dt>{order.kind === "top_up" ? "Top-up" : "Plan"}</dt>
              <dd>
                {order.kind === "top_up"
                  ? `${count(order.minutes)} minutes`
                  : `${order.planName}${order.interval ? `, ${order.interval === "month" ? "monthly" : "yearly"}` : ""}`}
              </dd>
            </div>
            {order.account === "organisation" ? (
              <div>
                <dt>Seats</dt>
                <dd>{order.seats}</dd>
              </div>
            ) : null}
            <div className={plansStyles.total}>
              <dt>Total</dt>
              <dd>{amount}</dd>
            </div>
          </dl>
        ) : null}
        <div className={plansStyles.resultActions}>
          <button
            type="button"
            className={plansStyles.pay}
            disabled={busy || !orderId}
            onClick={() => report("paid")}
          >
            {amount ? `Pay ${amount} (test)` : "Pay (test)"}
          </button>
          <button
            type="button"
            className={plansStyles.ghost}
            disabled={busy || !orderId}
            onClick={() => report("failed")}
          >
            Simulate a failed payment
          </button>
        </div>
      </div>
    </div>
  );
}

/** The return page on the fictional server. */
export function ReturnFixture() {
  const params = useSearchParams();
  return <ReturnPage orderId={params.get("order")} />;
}

export function ReturnPage({ orderId }: { orderId: string | null }) {
  return (
    <WorkspaceAccessProvider value={FIXTURE_ACCESS}>
      <Banner />
      <OrderReturn
        orderId={orderId}
        client={fixtureBilling}
        plansHref="/review-fixture/plans"
        billingHref="/review-fixture/plans?view=billing"
      />
    </WorkspaceAccessProvider>
  );
}
