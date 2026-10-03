"use client";

import { Check, Minus, Plus, ShieldCheck, Sparkles } from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";
import { AcquisitionShell } from "../acquisition-shell";
import {
  onSale,
  type Allowance,
  type Interval,
  type MePlan,
  type Order,
  type Plan,
} from "../billing/contract";
import { count, day, minutes, money, planPrice } from "../billing/money";
import { useWorkspaceAccess } from "../workspace-access";
import styles from "./plans.module.css";

export type PlanSelection = {
  planKey: string;
  interval: Interval;
  seats: number;
};
export type PurchaseQuote = {
  selection: PlanSelection;
  subtotalPaise: number;
  gstPaise: number;
  totalPaise: number;
  renewsAt: string;
};
export type PlansScreenProps = {
  plans: Plan[];
  gstRate: number;
  mePlan?: MePlan | null;
  quote?: PurchaseQuote | null;
  onSelectionChange?: (selection: PlanSelection) => void;
  onBuy?: (selection: PlanSelection) => void;
  busy?: boolean;
  error?: string | null;
  paidOrder?: Order | null;
  allowance?: Allowance | null;
};

/** Screens only. Catalogue, account state, verified payment and actions arrive as props. */
export function PlansScreen({
  plans,
  gstRate,
  mePlan,
  quote,
  onSelectionChange,
  onBuy,
  busy = false,
  error,
  paidOrder,
  allowance,
}: PlansScreenProps) {
  const access = useWorkspaceAccess();
  const [interval, setInterval] = useState<Interval>("month");
  const [seatCounts, setSeatCounts] = useState<Record<string, number>>({});
  const [selected, setSelected] = useState<string | null>(null);
  const summaryRef = useRef<HTMLElement>(null);
  const plan = plans.find((item) => item.key === selected);
  const seats = plan ? (seatCounts[plan.key] ?? plan.seatMin ?? 1) : 1;
  const selection = plan ? { planKey: plan.key, interval, seats } : null;
  const quoted =
    quote &&
    selection &&
    quote.selection.planKey === selection.planKey &&
    quote.selection.interval === interval &&
    quote.selection.seats === seats
      ? quote
      : null;
  const unit = plan ? planPrice(plan, interval) : null;
  const subtotal =
    quoted?.subtotalPaise ?? (unit === null ? null : unit * seats);
  const gst =
    quoted?.gstPaise ??
    (subtotal !== null && plan?.key !== "personal"
      ? Math.round(subtotal * gstRate)
      : 0);
  const total =
    quoted?.totalPaise ?? (subtotal === null ? null : subtotal + gst);
  const period = interval === "month" ? "month" : "year";
  const paid = paidOrder?.status === "paid" ? paidOrder : null;

  const choose = (key: string) => {
    setSelected(key);
    const item = plans.find((item) => item.key === key);
    if (item)
      onSelectionChange?.({
        planKey: key,
        interval,
        seats: seatCounts[key] ?? item.seatMin ?? 1,
      });
    requestAnimationFrame(() => {
      summaryRef.current?.focus();
      summaryRef.current?.scrollIntoView({
        block: "nearest",
        behavior: "instant",
      });
    });
  };

  const changeInterval = (next: Interval) => {
    setInterval(next);
    if (selection) onSelectionChange?.({ ...selection, interval: next });
  };
  const changeSeats = (key: string, next: number) => {
    setSeatCounts({ ...seatCounts, [key]: next });
    if (selected === key)
      onSelectionChange?.({ planKey: key, interval, seats: next });
  };

  return (
    <AcquisitionShell
      authenticated={access?.authenticated === true}
      showPolicyLinks
      homeHref="/"
      active="account"
      mobileFit={false}
    >
      <div className={styles.page} data-plans-screen>
        <header className={styles.top}>
          <div className={styles.brand}>
            <Sparkles size={18} aria-hidden="true" />
            <h1>Plans</h1>
          </div>
          <Link className={styles.ghost} href="/billing">
            Billing &amp; receipts
          </Link>
        </header>
        {paid ? (
          <section className={`${styles.panel} ${styles.result}`} role="status">
            <Check size={24} aria-hidden="true" />
            <h2>Payment successful</h2>
            <p>
              {paid.planName} · {money(paid.amount.minor, paid.amount.currency)}{" "}
              paid
            </p>
            <p>
              {allowance
                ? allowance.unlimited
                  ? "Unlimited analysis minutes available"
                  : `${count(minutes(allowance.availableSeconds))} analysis minutes available`
                : "Your analysis minutes are being updated."}
            </p>
            <div className={styles.actions}>
              <Link className={styles.primary} href="/">
                Go to dashboard
              </Link>
              <Link className={styles.ghost} href="/billing">
                View billing &amp; receipt
              </Link>
            </div>
          </section>
        ) : null}
        <section className={styles.panel}>
          <h2>Choose your plan</h2>
          <p className={styles.hint}>
            Choose a plan and review its details before paying.
          </p>
          {mePlan ? (
            <p className={styles.trial}>
              <span>
                <b>{mePlan.plan.name}</b> ·{" "}
                {mePlan.allowance.unlimited
                  ? "Unlimited analysis time"
                  : `${count(minutes(mePlan.allowance.availableSeconds))} minutes left`}
              </span>
            </p>
          ) : null}
          <div
            className={styles.seg}
            role="group"
            aria-label="How often you pay"
          >
            <button
              type="button"
              aria-pressed={interval === "month"}
              disabled={busy}
              onClick={() => changeInterval("month")}
            >
              Monthly
            </button>
            <button
              type="button"
              aria-pressed={interval === "year"}
              disabled={busy}
              onClick={() => changeInterval("year")}
            >
              Yearly <small>10% off</small>
            </button>
          </div>
          <div className={styles.plansGrid}>
            {plans.map((item) => {
              const team = item.key !== "personal";
              const number = seatCounts[item.key] ?? item.seatMin ?? 1;
              const price = planPrice(item, interval);
              const itemSubtotal = price === null ? null : price * number;
              const itemGst =
                itemSubtotal === null
                  ? null
                  : team
                    ? Math.round(itemSubtotal * gstRate)
                    : 0;
              const current = mePlan?.plan.key === item.key;
              const available = onSale(item) && price !== null;
              return (
                <article
                  key={item.key}
                  className={styles.planCard}
                  data-plan={item.key}
                  data-selected={selected === item.key}
                  data-current={current || undefined}
                >
                  {current || item.key === "enterprise" ? (
                    <span
                      className={`${styles.planBadge} ${styles.currentBadge}`}
                    >
                      {current ? "Current plan" : `${item.seatMin}+ seats`}
                    </span>
                  ) : null}
                  <div className={styles.planHead}>
                    <div>
                      <h3>{item.name}</h3>
                      <p className={styles.hint}>{item.audience}</p>
                    </div>
                    <p className={styles.price}>
                      {price === null ? "Price unavailable" : money(price)}
                      <small>
                        {team ? " per seat" : ""} / {period} ·{" "}
                        {team ? "+ GST" : "GST included"}
                      </small>
                    </p>
                  </div>
                  {team ? (
                    <>
                      <div className={styles.seats}>
                        <b id={`seats-${item.key}`}>Seats</b>
                        <span
                          className={styles.stepper}
                          role="group"
                          aria-labelledby={`seats-${item.key}`}
                        >
                          <button
                            type="button"
                            aria-label={`Remove a ${item.name} seat`}
                            disabled={
                              busy ||
                              item.seatMin === null ||
                              number <= item.seatMin
                            }
                            onClick={() => changeSeats(item.key, number - 1)}
                          >
                            <Minus size={16} aria-hidden="true" />
                          </button>
                          <output aria-live="polite">{number}</output>
                          <button
                            type="button"
                            aria-label={`Add a ${item.name} seat`}
                            disabled={
                              busy ||
                              item.seatMin === null ||
                              (item.seatMax !== null && number >= item.seatMax)
                            }
                            onClick={() => changeSeats(item.key, number + 1)}
                          >
                            <Plus size={16} aria-hidden="true" />
                          </button>
                        </span>
                        <span className={styles.hint}>
                          {item.seatMax === null
                            ? `${item.seatMin}+ seats`
                            : `${item.seatMin} to ${item.seatMax} seats`}
                        </span>
                      </div>
                      {itemSubtotal !== null && itemGst !== null ? (
                        <dl className={styles.gstLine}>
                          <div className={styles.gstRow}>
                            <dt>Subtotal ({number} seats)</dt>
                            <dd>{money(itemSubtotal)}</dd>
                          </div>
                          <div className={styles.gstRow}>
                            <dt>GST ({gstRate * 100}%)</dt>
                            <dd>{money(itemGst)}</dd>
                          </div>
                          <div
                            className={`${styles.gstRow} ${styles.gstTotal}`}
                          >
                            <dt>Total</dt>
                            <dd>
                              {money(itemSubtotal + itemGst)} / {period}
                            </dd>
                          </div>
                        </dl>
                      ) : null}
                    </>
                  ) : null}
                  <ul className={styles.facts}>
                    {item.key === "enterprise" ? (
                      <li>Everything in Organisation</li>
                    ) : null}
                    {item.includedMinutes !== null ? (
                      <li>
                        {count(item.includedMinutes * number)}{" "}
                        {team ? "pooled " : ""}analysis minutes every month
                      </li>
                    ) : null}
                    {item.longestCallMinutes !== null ? (
                      <li>
                        Calls up to {item.longestCallMinutes} minutes long
                      </li>
                    ) : null}
                    {team ? (
                      <li>Team dashboard &amp; shared call library</li>
                    ) : (
                      <li>1 user seat</li>
                    )}
                    {item.featureKeys.includes("priority_support") ? (
                      <li>Priority support</li>
                    ) : null}
                    {item.featureKeys.includes("team_onboarding") ? (
                      <li>Onboarding session for the team</li>
                    ) : null}
                  </ul>
                  <button
                    type="button"
                    className={styles.planActionBtn}
                    data-primary={!current || undefined}
                    disabled={busy || current || !available}
                    onClick={() => choose(item.key)}
                  >
                    {current
                      ? "Current plan"
                      : !available
                        ? "Unavailable"
                        : mePlan && mePlan.plan.key === "personal" && team
                          ? `Upgrade to ${item.name}`
                          : `Buy ${item.name}`}
                  </button>
                </article>
              );
            })}
          </div>
        </section>
        {selection && plan ? (
          <section
            ref={summaryRef}
            tabIndex={-1}
            className={styles.panel}
            aria-labelledby="purchase-summary"
          >
            <h2 id="purchase-summary">Purchase summary</h2>
            <dl className={styles.rows}>
              <div>
                <dt>Plan</dt>
                <dd>
                  {plan.name} · {interval === "month" ? "Monthly" : "Yearly"}
                </dd>
              </div>
              {plan.key !== "personal" ? (
                <>
                  <div>
                    <dt>Seats</dt>
                    <dd>{seats}</dd>
                  </div>
                  <div>
                    <dt>Subtotal</dt>
                    <dd>{subtotal === null ? "—" : money(subtotal)}</dd>
                  </div>
                  <div>
                    <dt>GST ({gstRate * 100}%)</dt>
                    <dd>{money(gst)}</dd>
                  </div>
                </>
              ) : (
                <div>
                  <dt>GST</dt>
                  <dd>Included</dd>
                </div>
              )}
              <div>
                <dt>Renewal date</dt>
                <dd>
                  {quoted
                    ? day(quoted.renewsAt) || "Unavailable"
                    : "Confirmed before payment"}
                </dd>
              </div>
              <div className={styles.total}>
                <dt>Pay today</dt>
                <dd>{total === null ? "—" : money(total)}</dd>
              </div>
            </dl>
            <p className={styles.hint}>
              <ShieldCheck size={14} aria-hidden="true" /> Full refund within 7
              days if none of this payment&apos;s minutes were used.
            </p>
            {error ? (
              <p role="alert" className={styles.note}>
                {error}
              </p>
            ) : null}
            <div className={styles.actions}>
              <button
                type="button"
                className={styles.pay}
                disabled={busy || !onBuy || !quoted}
                onClick={() => onBuy?.(selection)}
              >
                {busy ? "Opening checkout…" : "Pay with Razorpay"}
              </button>
              <button
                type="button"
                className={styles.ghost}
                disabled={busy}
                onClick={() => setSelected(null)}
              >
                Back to plans
              </button>
            </div>
            {!onBuy ? (
              <p className={styles.hint}>
                Checkout is currently unavailable. You can review plans and
                totals here.
              </p>
            ) : null}
          </section>
        ) : null}
      </div>
    </AcquisitionShell>
  );
}
