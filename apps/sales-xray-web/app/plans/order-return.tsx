"use client";

import { CircleCheck, CircleX, Clock3, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { AcquisitionShell } from "../acquisition-shell";
import {
  BillingError,
  idempotencyKey,
  liveBilling,
  type BillingClient,
} from "../billing/billing-api";
import type { Order } from "../billing/contract";
import { count, day, formatMoney } from "../billing/money";
import { useWorkspaceAccess } from "../workspace-access";
import styles from "./plans.module.css";

const POLL_MS = 3_000;
const POLL_FOR_MS = 60_000;

type State =
  | { status: "loading" }
  | { status: "order"; order: Order; waited: boolean }
  | { status: "missing" }
  | { status: "error"; detail: string | null };

const settled = (order: Order) =>
  order.status !== "awaiting_payment" && order.status !== "confirming";

/**
 * Where the payment page sends the buyer back (C1 §2). It only reads: the
 * order becomes paid when the provider confirms it to our server, never
 * because the browser came back. Polls every 3 s for a minute, then offers
 * one verified check.
 */
export function OrderReturn({
  orderId,
  client = liveBilling,
  plansHref = "/plans",
}: {
  orderId: string | null;
  client?: BillingClient;
  plansHref?: string;
}) {
  const access = useWorkspaceAccess();
  const authenticated = access?.authenticated === true;
  const [state, setState] = useState<State>({ status: "loading" });
  const [checking, setChecking] = useState(false);
  const verifyKey = useRef<string | null>(null);

  useEffect(() => {
    if (!orderId || !authenticated) return;
    const controller = new AbortController();
    const started = Date.now();
    let timer: ReturnType<typeof setTimeout> | null = null;
    const read = async () => {
      try {
        const order = await client.readOrder(orderId, controller.signal);
        if (controller.signal.aborted) return;
        const waited = Date.now() - started >= POLL_FOR_MS;
        setState({ status: "order", order, waited });
        if (!settled(order) && !waited) timer = setTimeout(read, POLL_MS);
      } catch (error) {
        if (controller.signal.aborted) return;
        if (
          error instanceof BillingError &&
          (error.status === 404 || error.status === 405 || error.status === 501)
        )
          setState({ status: "missing" });
        else
          setState({
            status: "error",
            detail: error instanceof BillingError ? error.detail : null,
          });
      }
    };
    void read();
    return () => {
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [authenticated, client, orderId]);

  const check = async () => {
    if (!orderId || checking) return;
    setChecking(true);
    try {
      verifyKey.current ??= idempotencyKey();
      const order = await client.verifyOrder(orderId, verifyKey.current);
      setState({ status: "order", order, waited: true });
      verifyKey.current = null;
    } catch (error) {
      if (error instanceof BillingError && error.status === 429) return; // once per 10 s; the button says so
      setState({
        status: "error",
        detail: error instanceof BillingError ? error.detail : null,
      });
    } finally {
      setChecking(false);
    }
  };

  let body;
  if (!orderId || state.status === "missing") {
    body = (
      <>
        <CircleX className={styles.iconMuted} size={40} aria-hidden="true" />
        <h2>We can&apos;t find this order</h2>
        <p className={styles.hint}>
          If you just paid, your bank&apos;s confirmation may still be on its
          way. Your plan page shows the result as soon as it arrives.
        </p>
        <Link className={styles.primary} href={plansHref}>
          Go to plans
        </Link>
      </>
    );
  } else if (state.status === "loading") {
    body = (
      <>
        <h2>Confirming your payment</h2>
        <p className={styles.hint}>
          You are back from the payment page. We are waiting for the bank to
          confirm.
        </p>
        <div className={styles.skeleton} aria-hidden="true">
          <i />
          <i />
          <i />
        </div>
      </>
    );
  } else if (state.status === "error") {
    body = (
      <>
        <CircleX className={styles.iconMuted} size={40} aria-hidden="true" />
        <h2>We could not check the order</h2>
        <p className={styles.hint}>
          {state.detail ??
            "Please try again in a moment. No money moves because of this page."}
        </p>
        <button
          type="button"
          className={styles.ghost}
          onClick={() => void check()}
          disabled={checking}
        >
          <RefreshCw size={14} aria-hidden="true" /> Check again
        </button>
      </>
    );
  } else {
    const { order } = state;
    const what =
      order.kind === "top_up"
        ? `${count(order.minutes)} top-up minutes`
        : `${order.planName}${order.interval ? `, ${order.interval === "month" ? "monthly" : "yearly"}` : ""}`;
    if (order.status === "paid") {
      body = (
        <>
          <CircleCheck
            className={styles.iconGood}
            size={40}
            aria-hidden="true"
          />
          <h2>
            {order.kind === "top_up"
              ? "Top-up added"
              : "Your minutes are ready"}
          </h2>
          <dl className={styles.rows}>
            <div>
              <dt>{order.kind === "top_up" ? "Top-up" : "Plan"}</dt>
              <dd>{what}</dd>
            </div>
            {order.account === "organisation" ? (
              <div>
                <dt>Seats</dt>
                <dd>{order.seats}</dd>
              </div>
            ) : null}
            <div>
              <dt>Minutes</dt>
              <dd>{count(order.minutes)}</dd>
            </div>
            <div>
              <dt>Paid</dt>
              <dd>
                {formatMoney(order.amount)} ·{" "}
                {day(order.paidAt ?? order.createdAt)}
                {order.mode === "test" ? " · TEST" : ""}
              </dd>
            </div>
          </dl>
          <div className={styles.actions}>
            <Link className={styles.primary} href="/new-analysis">
              Analyse a call
            </Link>
            <Link className={styles.ghost} href={plansHref}>
              See your plan
            </Link>
          </div>
          {order.refund?.state === "available" &&
          order.refund.refundableUntil ? (
            <p className={styles.hint}>
              Changed your mind? Ask for a refund until{" "}
              {day(order.refund.refundableUntil)} if you have not used any
              minutes.
            </p>
          ) : null}
        </>
      );
    } else if (order.status === "failed" || order.status === "expired") {
      body = (
        <>
          <CircleX className={styles.iconBad} size={40} aria-hidden="true" />
          <h2>
            {order.status === "failed"
              ? "Payment did not go through"
              : "The payment page timed out"}
          </h2>
          <p className={styles.hint}>
            No money was taken. Check the details and try again whenever you
            like.
          </p>
          <Link className={styles.primary} href={plansHref}>
            Back to plans
          </Link>
        </>
      );
    } else if (order.status === "needs_review") {
      body = (
        <>
          <Clock3 className={styles.iconMuted} size={40} aria-hidden="true" />
          <h2>We are checking this payment</h2>
          <p className={styles.hint}>
            Something about the payment did not match the order, so a person
            will look at it. Nothing is lost: we will add your minutes or return
            the money, and email you either way.
          </p>
          <Link className={styles.ghost} href={plansHref}>
            Back to plans
          </Link>
        </>
      );
    } else {
      body = (
        <>
          <h2>Confirming your payment</h2>
          <p className={styles.hint}>
            {order.status === "confirming"
              ? "The payment page reported success. We are waiting for the bank's confirmation to reach our server."
              : "You are back from the payment page. We are waiting for the bank to confirm."}{" "}
            This usually takes a few seconds, and you can keep using the app.
          </p>
          <dl className={styles.rows}>
            <div>
              <dt>{order.kind === "top_up" ? "Top-up" : "Plan"}</dt>
              <dd>{what}</dd>
            </div>
            <div>
              <dt>Amount</dt>
              <dd>
                {formatMoney(order.amount)}
                {order.mode === "test" ? " · TEST" : ""}
              </dd>
            </div>
          </dl>
          {state.waited ? (
            <button
              type="button"
              className={styles.ghost}
              onClick={() => void check()}
              disabled={checking}
            >
              <RefreshCw size={14} aria-hidden="true" />{" "}
              {checking ? "Checking…" : "Check again"}
            </button>
          ) : (
            <div className={styles.skeleton} aria-hidden="true">
              <i />
              <i />
              <i />
            </div>
          )}
        </>
      );
    }
  }

  return (
    <AcquisitionShell
      authenticated={authenticated}
      homeHref="/"
      active="account"
      mobileFit={false}
    >
      <div className={styles.page} data-order-return>
        <div className={`${styles.panel} ${styles.result}`} aria-live="polite">
          {authenticated ? (
            body
          ) : (
            <>
              <h2>Sign in to see this order</h2>
              <Link className={styles.primary} href="/login">
                Sign in
              </Link>
            </>
          )}
        </div>
      </div>
    </AcquisitionShell>
  );
}
