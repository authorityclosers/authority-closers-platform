"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { BillingView } from "../../billing/billing-view";
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
  resetFixtureBilling,
} from "./fixture-billing";
import styles from "../shell/full-shell-preview.module.css";

/** Fictional identity: never a real person, session or workspace. */
const FIXTURE_ACCESS = {
  status: "ready" as const,
  authenticated: true,
  context: {
    personId: "fixture-person",
    sessionId: "fixture-session",
    tenantId: "fixture-workspace",
  },
  retry: () => {},
};

function Banner() {
  const router = useRouter();
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

/** The plans screens on the fictional billing server. */
export function PlansFixture() {
  const params = useSearchParams();
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
      <Banner />
      {params.get("view") === "billing" ? (
        <FixtureBilling />
      ) : (
        <PlansPurchase client={fixtureBilling} />
      )}
    </WorkspaceAccessProvider>
  );
}

function FixtureBilling() {
  const billing = useBillingAccount(true, fixtureBilling);
  return <BillingView {...billing} />;
}

/** A stand-in for the payment partner's page: it only reports an outcome. */
export function PayFixture() {
  const params = useSearchParams();
  const router = useRouter();
  const orderId = params.get("order") ?? "";
  const [busy, setBusy] = useState(false);
  const report = (outcome: "paid" | "failed") => {
    setBusy(true);
    fixtureProviderReports(orderId, outcome);
    router.push(`${FIXTURE_RETURN_PATH}?order=${encodeURIComponent(orderId)}`);
  };
  return (
    <div className={plansStyles.page} style={{ padding: 16 }}>
      <Banner />
      <div className={`${plansStyles.panel} ${plansStyles.result}`}>
        <h2>Fictional payment page</h2>
        <p className={plansStyles.hint}>
          In the app this is the payment partner&apos;s secure page. Pick what
          the partner reports back to our server for order {orderId || "?"}.
        </p>
        <div className={plansStyles.actions}>
          <button
            type="button"
            className={plansStyles.primary}
            disabled={busy || !orderId}
            onClick={() => report("paid")}
          >
            Payment confirmed
          </button>
          <button
            type="button"
            className={plansStyles.ghost}
            disabled={busy || !orderId}
            onClick={() => report("failed")}
          >
            Payment failed
          </button>
        </div>
      </div>
    </div>
  );
}

/** The return page on the fictional server. */
export function ReturnFixture() {
  const params = useSearchParams();
  return (
    <WorkspaceAccessProvider value={FIXTURE_ACCESS}>
      <Banner />
      <OrderReturn
        orderId={params.get("order")}
        client={fixtureBilling}
        plansHref="/review-fixture/plans"
      />
    </WorkspaceAccessProvider>
  );
}
