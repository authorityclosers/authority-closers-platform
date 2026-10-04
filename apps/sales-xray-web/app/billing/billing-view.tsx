"use client";

import {
  Check,
  Clock3,
  CreditCard,
  FileText,
  Gem,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { AcquisitionShell } from "../acquisition-shell";
import type {
  Allowance,
  MePlan,
  Money,
  Subscriptions,
  Usage,
} from "./contract";
import { count, day, formatMoney, minutes } from "./money";
import { useWorkspaceAccess } from "../workspace-access";
import styles from "./billing.module.css";

export type BillingDocument = {
  id: string;
  createdAt: string;
  description: string;
  amount: Money;
  status: string;
  invoiceHref: string | null;
  receiptHref: string | null;
};

export type BillingViewProps = {
  mePlan?: MePlan | null;
  usage?: Usage | null;
  subs?: Subscriptions | null;
  documents?: BillingDocument[];
  invoicesStatus?: "loading" | "ready" | "error";
  status?: "loading" | "ready" | "error";
  busy?: boolean;
  error?: string | null;
  onRefresh?: () => void;
  onCancel?: (subscriptionId: string) => void;
};

/** Account data and actions arrive as props; this screen never invents payments. */
export function BillingView({
  mePlan = null,
  usage = null,
  subs = null,
  documents,
  status = "error",
  invoicesStatus = status,
  busy = false,
  error,
  onRefresh,
  onCancel,
}: BillingViewProps = {}) {
  const access = useWorkspaceAccess();
  const authenticated = access?.authenticated === true;
  const [cancelAsk, setCancelAsk] = useState(false);
  const loading = status === "loading";
  const current = subs?.current;
  const isPaidActive = current?.status === "active";
  const isCancelled = current?.cancelAtPeriodEnd === true;
  const allowance = usage?.allowance ?? mePlan?.allowance;
  const planName = mePlan?.plan.name ?? "Unavailable";

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

        {status !== "ready" ? (
          <p className={styles.hint} role={loading ? "status" : "alert"}>
            {loading
              ? "Loading billing details…"
              : (error ?? "Billing details are currently unavailable.")}
          </p>
        ) : error ? (
          <p role="alert">{error}</p>
        ) : null}
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
                    : current?.status === "pending_authorisation"
                      ? "Awaiting payment"
                      : current?.status === "past_due"
                        ? "Payment due"
                        : current?.status === "halted"
                          ? "Paused"
                          : current?.status === "ended" ||
                              current?.status === "cancelled"
                            ? "Ended"
                            : (mePlan?.plan.name ?? "Unavailable")}
              </span>
            </div>

            <p className={styles.planPrice}>
              {current ? formatMoney(current.amount) : "—"}
              <small>{current ? ` / ${current.interval}` : ""}</small>
            </p>

            <ul className={styles.facts}>
              <li>
                <Check size={14} className={styles.iconGood} />
                <b>{planName}</b>
                {current?.account === "organisation" && current.seats
                  ? ` · ${current.seats} team seats`
                  : ""}
              </li>
              {mePlan ? (
                <li>
                  <Clock3 size={14} aria-hidden="true" />
                  Calls up to {count(minutes(mePlan.longestCallSeconds))}{" "}
                  minutes
                </li>
              ) : null}
              <li>
                <ShieldCheck size={14} />
                Full refund within 7 days if none of this payment&apos;s minutes
                were used.
              </li>
            </ul>

            {current?.renewalNeedsCustomerApproval ? (
              <p className={styles.hint}>
                Your bank will ask you to approve each renewal above ₹15,000.
              </p>
            ) : null}

            <div className={styles.actions}>
              <Link className={styles.primary} href="/plans">
                {current ? "Change plan" : "Upgrade plan"}
              </Link>
              {current &&
              !isCancelled &&
              ["active", "past_due", "halted"].includes(current.status) ? (
                cancelAsk ? (
                  <div className={styles.confirmBox}>
                    <p>
                      Renewal stops; access continues to the end of the period.
                    </p>
                    <div className={styles.actions}>
                      <button
                        type="button"
                        className={styles.danger}
                        disabled={busy || !onCancel}
                        onClick={() => onCancel?.(current.subscriptionId)}
                      >
                        {busy ? "Stopping…" : "Yes, cancel renewal"}
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
              {current?.renewsAt && !isCancelled ? (
                <span className={styles.hint}>
                  Renews {day(current.renewsAt)}
                </span>
              ) : null}
            </div>

            <div className={styles.ringRow}>
              <UsageRing allowance={allowance ?? null} />
              <div className={styles.ringDetails}>
                <b>
                  {allowance?.unlimited
                    ? "Unlimited minutes"
                    : allowance
                      ? `${count(minutes(allowance.availableSeconds))} min left`
                      : "Minutes unavailable"}
                </b>
                <span>
                  {allowance?.unlimited
                    ? "No minute cap on your account"
                    : allowance
                      ? `of ${count(minutes(allowance.allowanceSeconds))} monthly allowance`
                      : ""}
                </span>
              </div>
            </div>

            <div className={styles.actions}>
              <Link className={styles.ghost} href="/new-analysis">
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
                  : status === "ready"
                    ? "No renewal scheduled"
                    : "Unavailable"}
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
                onClick={onRefresh}
                disabled={loading || busy || !onRefresh}
              >
                <RefreshCw size={14} /> Refresh status
              </button>
            </div>
          </section>

          {/* Card 4: Invoices & Receipts */}
          {documents ? (
            <section className={styles.card}>
              <div className={styles.cardHead}>
                <h2>Invoices &amp; Receipts</h2>
              </div>

              {invoicesStatus !== "ready" ? (
                <p
                  className={styles.hint}
                  role={invoicesStatus === "loading" ? "status" : "alert"}
                >
                  {invoicesStatus === "loading"
                    ? "Loading invoices…"
                    : "Invoices and receipts are currently unavailable."}
                </p>
              ) : documents.length > 0 ? (
                <div className={styles.tableWrap}>
                  <table className={styles.table}>
                    <caption className={styles.hint}>
                      Invoices and receipts
                    </caption>
                    <thead>
                      <tr>
                        <th scope="col">Date</th>
                        <th scope="col">Description</th>
                        <th scope="col">Amount</th>
                        <th scope="col">Status</th>
                        <th scope="col">Documents</th>
                      </tr>
                    </thead>
                    <tbody>
                      {documents.map((document) => (
                        <tr key={document.id}>
                          <td>{day(document.createdAt)}</td>
                          <td>{document.description}</td>
                          <td>{formatMoney(document.amount)}</td>
                          <td>{document.status}</td>
                          <td>
                            {document.invoiceHref ? (
                              <a
                                href={document.invoiceHref}
                                download
                                aria-label={`Invoice for ${document.description}`}
                              >
                                Invoice
                              </a>
                            ) : null}
                            {document.invoiceHref && document.receiptHref
                              ? " · "
                              : ""}
                            {document.receiptHref ? (
                              <a
                                href={document.receiptHref}
                                aria-label={`Receipt for ${document.description}`}
                              >
                                Receipt
                              </a>
                            ) : null}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className={styles.empty}>
                  <FileText size={24} aria-hidden="true" />
                  <p>
                    {invoicesStatus === "ready"
                      ? "No invoices or receipts yet."
                      : "Invoices and receipts are currently unavailable."}
                  </p>
                  <Link className={styles.primary} href="/plans">
                    Choose a plan
                  </Link>
                </div>
              )}
            </section>
          ) : null}
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
