"use client";

import {
  Check,
  Clock3,
  CreditCard,
  FileText,
  Gem,
  RefreshCw,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AcquisitionShell } from "../acquisition-shell";
import {
  BillingError,
  idempotencyKey,
  liveBilling,
  returnPath,
  type BillingClient,
} from "./billing-api";
import type { Allowance, Hosted, MePlan, Subscriptions } from "./contract";
import { count, day, formatMoney, minutes, money } from "./money";
import { notify } from "../notice-center";
import { openHostedCheckout } from "../plans/hosted-checkout";
import { useWorkspaceAccess } from "../workspace-access";
import styles from "./billing.module.css";

export function BillingView({
  client = liveBilling,
}: {
  client?: BillingClient;
}) {
  const router = useRouter();
  const access = useWorkspaceAccess();
  const authenticated = access?.authenticated === true;

  const [loading, setLoading] = useState(true);
  const [mePlan, setMePlan] = useState<MePlan | null>(null);
  const [subs, setSubs] = useState<Subscriptions | null>(null);
  const [busy, setBusy] = useState<"cancel" | "top_up" | null>(null);
  const [cancelAsk, setCancelAsk] = useState(false);

  const reload = useCallback(async () => {
    if (!authenticated) return;
    setLoading(true);
    try {
      const [meRes, subRes] = await Promise.allSettled([
        client.readMePlan(),
        client.readSubscriptions("personal"),
      ]);
      if (meRes.status === "fulfilled") setMePlan(meRes.value);
      if (subRes.status === "fulfilled") setSubs(subRes.value);
    } finally {
      setLoading(false);
    }
  }, [authenticated, client]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const goHosted = useCallback(
    async (hosted: Hosted, orderId: string) => {
      const result = await openHostedCheckout(hosted, orderId);
      if (result === "left") return;
      router.push(returnPath(orderId));
    },
    [router],
  );

  const cancel = async () => {
    const current = subs?.current;
    if (!current || busy) return;
    setBusy("cancel");
    try {
      await client.cancelSubscription(
        current.subscriptionId,
        null,
        idempotencyKey(),
      );
      setCancelAsk(false);
      await reload();
      notify({
        id: "billing",
        tone: "success",
        title: "Renewal is off",
        message: `The recorded subscription period ends ${day(current.currentPeriod?.end ?? current.renewsAt)}. Access runs until the period end.`,
        timeout: 6000,
      });
    } catch (error) {
      notify({
        id: "billing",
        tone: "error",
        title: "Could not stop renewal",
        message:
          error instanceof BillingError && error.detail
            ? error.detail
            : "Please try again in a moment.",
      });
    } finally {
      setBusy(null);
    }
  };

  const topUp = async (packKey: string) => {
    if (busy) return;
    setBusy("top_up");
    try {
      const checkout = await client.checkout(
        {
          kind: "top_up",
          account: "personal",
          planKey: mePlan?.plan.key ?? "personal",
          packKey,
        },
        idempotencyKey(),
      );
      await goHosted(checkout.hosted, checkout.order.orderId);
    } catch (error) {
      notify({
        id: "billing",
        tone: "error",
        title: "Top-up could not be started",
        message:
          error instanceof BillingError && error.detail
            ? error.detail
            : "Please try again in a moment.",
      });
    } finally {
      setBusy(null);
    }
  };

  const current = subs?.current;
  const isPaidActive = current?.status === "active";
  const isCancelled = current?.cancelAtPeriodEnd === true;
  const allowance = mePlan?.allowance;
  const planName = current?.planName ?? mePlan?.plan.name ?? "Free Trial";

  return (
    <AcquisitionShell
      authenticated={authenticated}
      showPolicyLinks
      homeHref="/"
      active="account"
      mobileFit={false}
    >
      <div className={styles.page}>
        <header className={styles.top}>
          <div className={styles.titleRow}>
            <div className={styles.brand}>
              <CreditCard size={20} aria-hidden="true" />
              <h1>Billing &amp; Subscription</h1>
            </div>
            <Link className={styles.primary} href="/plans">
              <Gem size={15} aria-hidden="true" />
              View all plans
            </Link>
          </div>
          <p className={styles.subtitle}>
            Manage your Sales Xray subscription, analysis minutes, and invoices.
          </p>
        </header>

        <div className={styles.grid}>
          {/* Card 1: Current Plan */}
          <section className={styles.card}>
            <div className={styles.cardHead}>
              <h2>Current plan</h2>
              <span
                className={styles.statusBadge}
                data-status={
                  isCancelled ? "cancelled" : isPaidActive ? "active" : "trial"
                }
              >
                {isCancelled
                  ? "Cancels at period end"
                  : isPaidActive
                    ? "Active"
                    : "Trial"}
              </span>
            </div>

            <p className={styles.planPrice}>
              {current
                ? formatMoney(current.amount)
                : planName === "Personal"
                  ? "₹2,499"
                  : "₹0"}
              <small>
                {current
                  ? ` / ${current.interval ?? "month"}`
                  : planName === "Personal"
                    ? " / month"
                    : " · Trial"}
              </small>
            </p>

            <ul className={styles.facts}>
              <li>
                <Check size={14} className={styles.iconGood} />
                <b>{planName}</b>
                {current?.account === "organisation" && current.seats
                  ? ` · ${current.seats} team seats`
                  : ""}
              </li>
              <li>
                <Clock3 size={14} />
                Calls up to{" "}
                {mePlan ? count(minutes(mePlan.longestCallSeconds)) : "90"}{" "}
                minutes
              </li>
              <li>
                <ShieldCheck size={14} />
                Full refund within 7 days if none of this payment&apos;s minutes
                were used.
              </li>
            </ul>

            <div className={styles.actions}>
              <Link className={styles.primary} href="/plans">
                {current ? "Change plan" : "Upgrade plan"}
              </Link>
              {current && !isCancelled ? (
                cancelAsk ? (
                  <div className={styles.confirmBox}>
                    <p>
                      Renewal stops; access continues to the end of the period.
                    </p>
                    <div className={styles.actions}>
                      <button
                        type="button"
                        className={styles.danger}
                        disabled={busy === "cancel"}
                        onClick={() => void cancel()}
                      >
                        {busy === "cancel"
                          ? "Stopping…"
                          : "Yes, cancel renewal"}
                      </button>
                      <button
                        type="button"
                        className={styles.ghost}
                        onClick={() => setCancelAsk(false)}
                      >
                        Keep renewal
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    type="button"
                    className={styles.ghost}
                    onClick={() => setCancelAsk(true)}
                  >
                    Cancel renewal
                  </button>
                )
              ) : null}
            </div>
          </section>

          {/* Card 2: Analysis Time Usage */}
          <section className={styles.card}>
            <div className={styles.cardHead}>
              <h2>Analysis time</h2>
              <span className={styles.hint}>Renews on schedule</span>
            </div>

            <div className={styles.ringRow}>
              <UsageRing allowance={allowance ?? null} />
              <div className={styles.ringDetails}>
                <b>
                  {allowance?.unlimited
                    ? "Unlimited minutes"
                    : `${count(minutes(allowance?.availableSeconds ?? 0))} min left`}
                </b>
                <span>
                  {allowance?.unlimited
                    ? "No minute cap on your account"
                    : `of ${count(minutes(allowance?.allowanceSeconds ?? 0))} monthly allowance`}
                </span>
              </div>
            </div>

            <div className={styles.actions}>
              <button
                type="button"
                className={styles.ghost}
                disabled={busy !== null}
                onClick={() => void topUp("personal_100")}
              >
                Top up 100 minutes · ₹299
              </button>
              <Link className={styles.ghost} href="/analysis/new">
                Analyse a call
              </Link>
            </div>
          </section>

          {/* Card 3: Renewal & Payment Details */}
          <section className={styles.card}>
            <div className={styles.cardHead}>
              <h2>Renewal &amp; Payment</h2>
            </div>

            <ul className={styles.facts}>
              <li>
                <b>Next renewal date:</b>{" "}
                {current
                  ? isCancelled
                    ? `Access runs until ${day(current.currentPeriod?.end ?? current.renewsAt)}`
                    : day(current.renewsAt)
                  : "No renewal scheduled"}
              </li>
              <li>
                <b>Payment method:</b> UPI, Card, Net Banking via Razorpay
              </li>
              <li>
                <b>Refund rule:</b> Full refund within 7 days if none of this
                payment&apos;s minutes were used.
              </li>
            </ul>

            <div className={styles.actions}>
              <button
                type="button"
                className={styles.ghost}
                onClick={() => void reload()}
                disabled={loading}
              >
                <RefreshCw size={14} /> Refresh status
              </button>
            </div>
          </section>

          {/* Card 4: Invoices & Receipts */}
          <section className={styles.card}>
            <div className={styles.cardHead}>
              <h2>Invoices &amp; Receipts</h2>
            </div>

            {current ? (
              <div className={styles.tableWrap}>
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Description</th>
                      <th>Amount</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td>{day(current.createdAt ?? current.renewsAt)}</td>
                      <td>
                        {current.planName} (
                        {current.interval === "year" ? "Yearly" : "Monthly"})
                      </td>
                      <td>{formatMoney(current.amount)}</td>
                      <td>
                        <span className={styles.statusBadge}>Paid</span>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            ) : (
              <div className={styles.empty}>
                <FileText size={24} />
                <p>
                  Invoices and receipts will appear here after your first
                  payment.
                </p>
                <Link className={styles.primary} href="/plans">
                  Choose a plan
                </Link>
              </div>
            )}
          </section>
        </div>
      </div>
    </AcquisitionShell>
  );
}

function UsageRing({ allowance }: { allowance: Allowance | null }) {
  const circumference = 2 * Math.PI * 36;
  const share =
    allowance && !allowance.unlimited && allowance.allowanceSeconds > 0
      ? Math.min(1, allowance.availableSeconds / allowance.allowanceSeconds)
      : allowance?.unlimited
        ? 1
        : 0;

  return (
    <div className={styles.ring}>
      <svg viewBox="0 0 90 90" aria-hidden="true">
        <circle className={styles.ringTrack} cx="45" cy="45" r="36" />
        <circle
          className={styles.ringValue}
          cx="45"
          cy="45"
          r="36"
          strokeDasharray={circumference.toFixed(1)}
          strokeDashoffset={(circumference * (1 - share)).toFixed(1)}
        />
      </svg>
      <div className={styles.ringText}>
        <b>
          {allowance
            ? allowance.unlimited
              ? "∞"
              : count(minutes(allowance.availableSeconds))
            : "—"}
        </b>
        <small>min left</small>
      </div>
    </div>
  );
}
