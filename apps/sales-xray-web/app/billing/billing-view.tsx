"use client";

import { documentStatus } from "./document-status";
import { RefundRequest, type RequestRefund } from "./refund-request";
import { revealAboveTabBar } from "./reveal";
import type { Refund } from "./contract";
import { usePurchasesAllowed } from "../purchase-policy";
import {
  CalendarClock,
  Check,
  Clock3,
  CreditCard,
  FileText,
  Gem,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { AcquisitionShell } from "../acquisition-shell";
import type {
  Allowance,
  MePlan,
  Money,
  Subscriptions,
  Usage,
} from "./contract";
import { count, day, formatMoney, minutes } from "./money";
import { dismissNotice, notify } from "../notice-center";
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
  /** The refund state of the payment behind this document, when it has one. */
  refund?: Refund | null;
};

export type BillingViewProps = {
  mePlan?: MePlan | null;
  usage?: Usage | null;
  subs?: Subscriptions | null;
  documents?: BillingDocument[];
  /** Asks for a refund of one payment (C1 §4); absent where refunds can't be asked. */
  onRefund?: RequestRefund;
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
  onRefund,
}: BillingViewProps = {}) {
  const access = useWorkspaceAccess();
  const refundable = documents?.find(
    (document) => document.refund?.state === "available",
  );
  const authenticated = access?.authenticated === true;
  const [cancelAsk, setCancelAsk] = useState(false);
  // The confirm opens below the fold on phones: bring it up, clear of the tab
  // bar (QA, 23 Oct 2026).
  const revealConfirm = useCallback((box: HTMLDivElement | null) => {
    if (box) requestAnimationFrame(() => revealAboveTabBar(box));
  }, []);
  const purchasesAllowed = usePurchasesAllowed();
  const loading = status === "loading";
  const current = subs?.current;
  // The refund promise is about a payment that can still be refunded; a trial
  // (or one just refunded) has none.
  const paid = Boolean(current) || Boolean(refundable);
  const isPaidActive = current?.status === "active";
  const isCancelled = current?.cancelAtPeriodEnd === true;
  const cancellable =
    current != null &&
    !isCancelled &&
    ["active", "past_due", "halted"].includes(current.status);
  const allowance = usage?.allowance ?? mePlan?.allowance;
  const planName = mePlan?.plan.name ?? "Not loaded";
  const unread = !loading && status !== "ready";
  const readFailed =
    unread || (documents !== undefined && invoicesStatus === "error");
  // Errors are corner cards (owner rule): a read that failed, or an update
  // that did not go through, never red text in the page (23 Oct 2026).
  const retry = useRef(onRefresh);
  useEffect(() => {
    retry.current = onRefresh;
  });
  useEffect(() => {
    if (!readFailed) return;
    const id = "billing-read-error";
    notify({
      id,
      tone: "error",
      title: "Billing details didn't load",
      message: "Your plan, minutes and invoices couldn't be loaded.",
      action: { label: "Try again", run: () => retry.current?.() },
    });
    return () => dismissNotice(id);
  }, [readFailed]);
  useEffect(() => {
    if (status !== "ready" || !error) return;
    const id = "billing-update-error";
    notify({
      id,
      tone: "error",
      title: "Billing update failed",
      message: error,
    });
    return () => dismissNotice(id);
  }, [error, status]);
  const ringAvailSecs = allowance ? allowance.availableSeconds : 0;
  const ringAvailMins = minutes(ringAvailSecs);
  const ringHours = Math.floor(ringAvailMins / 60);
  const ringRemMins = ringAvailMins % 60;
  const ringHoursText =
    ringAvailMins >= 60
      ? ringRemMins > 0
        ? `${ringHours} h ${ringRemMins} min`
        : `${ringHours} h`
      : null;

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
            {purchasesAllowed ? (
              <Link className={styles.ghost} href="/plans">
                <Gem size={15} aria-hidden="true" />
                View all plans
              </Link>
            ) : null}
          </div>
          <p className={styles.subtitle}>
            Manage your Sales X-Ray subscription, analysis minutes, and
            invoices.
          </p>
        </header>

        {loading ? (
          <BillingSkeleton />
        ) : (
          <div className={styles.grid}>
            {/* Card 1: Current Plan */}
            <section className={styles.card}>
              <div className={styles.cardHead}>
                <h2>Current plan</h2>
                <span
                  className={styles.statusBadge}
                  data-status={
                    isCancelled
                      ? "cancelled"
                      : isPaidActive
                        ? "active"
                        : "trial"
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
                              : unread
                                ? "Not loaded"
                                : (mePlan?.plan.name ?? "Trial")}
                </span>
              </div>

              {current ? (
                <p className={styles.planPrice}>
                  {formatMoney(current.amount)}
                  <small>{` / ${current.interval}`}</small>
                </p>
              ) : status === "ready" ? (
                <p className={styles.lead}>
                  {purchasesAllowed
                    ? "You're on the free trial. Choose a plan when you're ready."
                    : "You're on the free trial."}
                </p>
              ) : null}

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
                {paid ? (
                  <li>
                    <ShieldCheck size={14} />
                    Full refund within 7 days if none of this payment&apos;s
                    minutes were used.
                  </li>
                ) : null}
              </ul>

              {current?.renewalNeedsCustomerApproval ? (
                <p className={styles.hint}>
                  Your bank will ask you to approve each renewal above ₹15,000.
                </p>
              ) : null}

              <div className={`${styles.actions} ${styles.planActions}`}>
                {purchasesAllowed ? (
                  <Link className={styles.primary} href="/plans">
                    {current ? "Change plan" : "Choose a plan"}
                  </Link>
                ) : null}
                {cancellable && !cancelAsk ? (
                  <button
                    type="button"
                    className={styles.ghost}
                    onClick={() => setCancelAsk(true)}
                  >
                    Cancel renewal
                  </button>
                ) : null}
                {onRefund && refundable ? (
                  <RefundRequest
                    refund={refundable.refund}
                    amount={formatMoney(refundable.amount)}
                    onRequest={onRefund}
                    className={styles.ghost}
                  />
                ) : null}
              </div>
              {current && cancellable && cancelAsk ? (
                <div
                  className={styles.confirmBox}
                  ref={revealConfirm}
                  role="group"
                  aria-labelledby="cancel-renewal-title"
                >
                  <p className={styles.confirmTitle} id="cancel-renewal-title">
                    <CalendarClock size={18} aria-hidden="true" />
                    Stop renewing?
                  </p>
                  <p>
                    You keep {planName} until{" "}
                    {day(current.currentPeriod?.end ?? current.renewsAt)}. It
                    won&apos;t renew after that.
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
              ) : null}
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
                {!allowance?.unlimited ? (
                  <UsageRing allowance={allowance ?? null} />
                ) : null}
                <div className={styles.ringDetails}>
                  <b>
                    {allowance?.unlimited
                      ? "Unlimited"
                      : allowance
                        ? ringHoursText
                          ? `${count(ringAvailMins)} min (${ringHoursText}) left`
                          : `${count(ringAvailMins)} min left`
                        : "Not loaded"}
                  </b>
                  <span>
                    {allowance?.unlimited
                      ? `${count(minutes(allowance.committedSeconds))} min used or reserved by analyses.`
                      : allowance
                        ? allowance.allowanceSeconds > 0
                          ? `of ${count(minutes(allowance.allowanceSeconds))} min in total (plan, trial and top-ups)`
                          : "available analysis time"
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

              <dl className={styles.rows}>
                <div>
                  <dt>{isCancelled ? "Access until" : "Next renewal"}</dt>
                  <dd>
                    {current
                      ? isCancelled
                        ? day(current.currentPeriod?.end ?? current.renewsAt)
                        : day(current.renewsAt)
                      : status === "ready"
                        ? "No renewal scheduled"
                        : "Not loaded"}
                  </dd>
                </div>
                {paid ? (
                  <div>
                    <dt>Refunds</dt>
                    <dd>
                      Full refund within 7 days if none of this payment&apos;s
                      minutes were used.
                    </dd>
                  </div>
                ) : null}
              </dl>

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
              <section className={`${styles.card} ${styles.wide}`}>
                <div className={styles.cardHead}>
                  <h2>Invoices &amp; Receipts</h2>
                </div>

                {invoicesStatus !== "ready" ? (
                  <p
                    className={styles.hint}
                    role={invoicesStatus === "loading" ? "status" : undefined}
                  >
                    {invoicesStatus === "loading"
                      ? "Loading invoices…"
                      : "Invoices and receipts: not loaded."}
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
                            <td data-label="Date">{day(document.createdAt)}</td>
                            <td data-label="Description">
                              {document.description}
                            </td>
                            <td data-label="Amount">
                              {formatMoney(document.amount)}
                            </td>
                            <td data-label="Status">
                              <span
                                className={styles.statusChip}
                                data-tone={
                                  document.refund?.state === "refunded" ||
                                  document.refund?.state === "pending"
                                    ? "refund"
                                    : "paid"
                                }
                              >
                                {documentStatus(document)}
                              </span>
                            </td>
                            <td data-label="Documents">
                              {document.invoiceHref ? (
                                <a
                                  className={styles.docLink}
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
                                  className={styles.docLink}
                                  href={document.receiptHref}
                                  aria-label={`Receipt for ${document.description}`}
                                >
                                  Receipt
                                </a>
                              ) : null}
                              {/* The offer only; once asked, Status says where it stands. */}
                              {onRefund &&
                              document.refund?.state === "available" ? (
                                <>
                                  {" · "}
                                  <RefundRequest
                                    refund={document.refund}
                                    amount={formatMoney(document.amount)}
                                    onRequest={onRefund}
                                    className={styles.ghost}
                                  />
                                </>
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
                      No invoices or receipts yet. Each payment adds one here.
                    </p>
                    {purchasesAllowed ? (
                      <Link className={styles.primary} href="/plans">
                        Choose a plan
                      </Link>
                    ) : null}
                  </div>
                )}
              </section>
            ) : null}
          </div>
        )}
      </div>
    </AcquisitionShell>
  );
}

/** The cards' outline at their final sizes while billing loads (nothing jumps). */
function BillingSkeleton() {
  return (
    <div
      className={styles.grid}
      role="status"
      aria-busy="true"
      aria-label="Loading billing details"
    >
      {[0, 1, 2].map((card) => (
        <section key={card} className={`${styles.card} ${styles.skeletonCard}`}>
          <i data-size="title" />
          <i data-size="big" />
          <i />
          <i />
          <i data-size="button" />
        </section>
      ))}
    </div>
  );
}

function UsageRing({ allowance }: { allowance: Allowance | null }) {
  const circumference = 2 * Math.PI * 36;
  const availSecs = allowance ? allowance.availableSeconds : 0;
  const share =
    allowance && allowance.allowanceSeconds > 0
      ? Math.min(1, availSecs / allowance.allowanceSeconds)
      : allowance
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
        <b>{allowance ? count(minutes(availSecs)) : "—"}</b>
        <small>min left</small>
      </div>
    </div>
  );
}
