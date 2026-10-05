"use client";

import {
  Building2,
  Check,
  CircleUserRound,
  Minus,
  Plus,
  Users,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  onSale,
  type Allowance,
  type Interval,
  type Hosted,
  type MePlan,
  type Order,
  type Plan,
} from "../billing/contract";
import { count, minutes, money, planPrice } from "../billing/money";
import { dismissNotice, notify } from "../notice-center";
import type { DisplayTopUpPack } from "./plans-catalogue-fixture";
import { PurchaseShell } from "./purchase-shell";
import { CheckoutDrawer } from "./checkout-drawer";
import type { Buyer } from "../billing/billing-api";
import { AnimatedCountUp } from "./animated-count-up";
import styles from "./plans.module.css";

export type PlanSelection = {
  planKey: string;
  interval: Interval;
  seats: number;
  buyer?: Buyer;
};

export type PurchaseQuote = {
  selection: PlanSelection;
  subtotalPaise: number;
  gstPaise: number;
  totalPaise: number;
  renewsAt: string;
};

export type TopUpPack = DisplayTopUpPack;

export type PlansScreenProps = {
  plans: Plan[];
  gstRate: number;
  mePlan?: MePlan | null;
  quote?: PurchaseQuote | null;
  onSelectionChange?: (selection: PlanSelection) => void;
  onBuy?: (selection: PlanSelection) => void;
  onBuyTopUp?: (pack: TopUpPack) => void;
  busy?: boolean;
  error?: string | null;
  paidOrder?: Order | null;
  checkoutOrder?: Order | null;
  checkoutProvider?: Hosted["provider"];
  allowance?: Allowance | null;
  topUpPacks?: TopUpPack[];
};

/**
 * Screen presentation for the subscription purchase ladder.
 * Built strictly to the owner order:
 * - Dedicated purchase shell: no app sidebar, no header, no account menu, just close/back.
 * - The ladder (Personal, Organisation, Enterprise) with distinctive icons.
 * - Monthly / Yearly (10% off) toggle.
 * - Seat stepper: Organisation 2–49, Enterprise 50+.
 * - Everything fits in one viewport at 1440 and 390 px.
 * - Checkout opens as a side panel (drawer), never at the page bottom.
 * - Top-ups removed from /plans (live in Settings → Plan & billing).
 * - Success: animated minute count-up, receipt link, and "Start an analysis".
 */
export function PlansScreen({
  plans,
  gstRate,
  mePlan,
  quote,
  onSelectionChange,
  onBuy,
  onBuyTopUp,
  busy = false,
  error,
  paidOrder,
  checkoutOrder,
  checkoutProvider,
  allowance,
}: PlansScreenProps) {
  const [interval, setInterval] = useState<Interval>("month");
  const [seatCounts, setSeatCounts] = useState<Record<string, number>>({});
  const [selectedPlanKey, setSelectedPlanKey] = useState<string | null>(null);
  const [selectedTopUp, setSelectedTopUp] = useState<TopUpPack | null>(null);
  const [mobileTab, setMobileTab] = useState<string>("organisation");
  const summaryRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!error) return;
    const id = "plans-purchase-error";
    notify({
      id,
      tone: "error",
      title: "Purchase unavailable",
      message: error,
    });
    return () => dismissNotice(id);
  }, [error]);

  const plan = plans.find((item) => item.key === selectedPlanKey);
  const seats = plan
    ? (seatCounts[plan.key] ??
      (plan.key === "enterprise" ? 50 : (plan.seatMin ?? 1)))
    : 1;
  const selection: PlanSelection | null = plan
    ? { planKey: plan.key, interval, seats }
    : null;

  const quoted =
    quote &&
    selection &&
    quote.selection.planKey === selection.planKey &&
    quote.selection.interval === interval &&
    quote.selection.seats === seats
      ? quote
      : null;

  const confirmedOrder =
    checkoutOrder &&
    (selectedTopUp
      ? checkoutOrder.kind === "top_up" &&
        checkoutOrder.packKey === selectedTopUp.key &&
        checkoutOrder.planKey === selectedTopUp.planKey
      : selection &&
        checkoutOrder.kind === "subscription" &&
        checkoutOrder.planKey === selection.planKey &&
        checkoutOrder.interval === interval &&
        checkoutOrder.seats === seats)
      ? checkoutOrder
      : null;

  const paid = paidOrder?.status === "paid" ? paidOrder : null;

  const choosePlan = (key: string) => {
    setSelectedTopUp(null);
    setSelectedPlanKey(key);
    setMobileTab(key);
    const item = plans.find((i) => i.key === key);
    const itemSeats =
      seatCounts[key] ?? (key === "enterprise" ? 50 : (item?.seatMin ?? 1));
    if (item) {
      onSelectionChange?.({
        planKey: key,
        interval,
        seats: itemSeats,
      });
    }
  };

  const changeInterval = (next: Interval) => {
    setInterval(next);
    if (selection) onSelectionChange?.({ ...selection, interval: next });
  };

  const changeSeats = (key: string, next: number) => {
    setSeatCounts((prev) => ({ ...prev, [key]: next }));
    if (selectedPlanKey === key) {
      onSelectionChange?.({ planKey: key, interval, seats: next });
    }
  };

  const handlePay = (buyer?: Buyer) => {
    if (selectedTopUp) {
      onBuyTopUp?.(selectedTopUp);
    } else if (selection) {
      onBuy?.({ ...selection, ...(buyer ? { buyer } : {}) });
    }
  };

  const closeCheckout = () => {
    setSelectedPlanKey(null);
    setSelectedTopUp(null);
  };

  return (
    <PurchaseShell backHref="/">
      <div className={styles.page} data-plans-screen>
        {paid ? (
          <section className={`${styles.panel} ${styles.result}`} role="status">
            <div className={styles.successIconWrap}>
              <Check size={28} className={styles.iconGood} aria-hidden="true" />
            </div>
            <h2>Payment successful</h2>
            <p className={styles.successSummary}>
              <b>{paid.planName}</b> ·{" "}
              {money(paid.amount.minor, paid.amount.currency)} paid
            </p>
            {paid.minutes !== null ? (
              <AnimatedCountUp targetMinutes={paid.minutes} />
            ) : null}
            <p className={styles.successAllowance}>
              {allowance?.unlimited
                ? `Unlimited · ${count(minutes(allowance.committedSeconds))} min used or reserved by analyses.`
                : allowance
                  ? `${count(minutes(allowance.availableSeconds))} analysis minutes available on your account.`
                  : "Your updated analysis minutes are being confirmed."}
            </p>
            <div className={styles.actions}>
              <Link className={styles.primary} href="/analysis/new">
                Start an analysis
              </Link>
              <Link className={styles.ghost} href="/account#billing">
                View receipt &amp; billing
              </Link>
              <Link className={styles.ghost} href="/">
                Go to dashboard
              </Link>
            </div>
          </section>
        ) : (
          <div className={styles.viewportLadderContainer}>
            {/* Header row with Title and Cycle Switcher */}
            <div className={styles.ladderTopRow}>
              <div className={styles.ladderHeading}>
                <h2>Choose your subscription</h2>
                <p className={styles.hint}>
                  Select the plan that fits your sales rhythm. Upgrade,
                  downgrade, or cancel anytime.
                </p>
              </div>

              {mePlan ? (
                <div className={styles.trial}>
                  <span>
                    <b>Current: {mePlan.plan.name}</b> ·{" "}
                    {mePlan.allowance.unlimited
                      ? `Unlimited · ${count(minutes(mePlan.allowance.committedSeconds))} min used or reserved by analyses.`
                      : `${count(minutes(mePlan.allowance.availableSeconds))} minutes left`}
                  </span>
                </div>
              ) : null}

              {/* Monthly / Yearly (10% off) toggle */}
              <div className={styles.billingCycleToggle}>
                <div
                  className={styles.seg}
                  role="group"
                  aria-label="Billing frequency"
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
                    Yearly <small>save 10%</small>
                  </button>
                </div>
              </div>
            </div>

            {/* Mobile Plan Tab Switcher (Visible only at <=768px for 1-viewport fit on 390px) */}
            <div
              className={styles.mobilePlanTabs}
              role="tablist"
              aria-label="Select plan"
            >
              {plans.map((item) => (
                <button
                  key={item.key}
                  type="button"
                  role="tab"
                  aria-selected={mobileTab === item.key}
                  className={styles.mobilePlanTabBtn}
                  data-active={mobileTab === item.key}
                  onClick={() => setMobileTab(item.key)}
                >
                  {item.name}
                  {item.key === "organisation" ? " ★" : ""}
                </button>
              ))}
            </div>

            {/* The 3-card Plan Ladder */}
            <div className={styles.plansGrid}>
              {plans.map((item) => {
                const isPersonal = item.key === "personal";
                const isOrganisation = item.key === "organisation";
                const isEnterprise = item.key === "enterprise";
                const team = !isPersonal;
                const defaultMin = isEnterprise ? 50 : (item.seatMin ?? 1);
                const number = seatCounts[item.key] ?? defaultMin;
                const price = planPrice(item, interval);
                const itemSubtotal = price === null ? null : price * number;
                const itemGst =
                  itemSubtotal === null
                    ? null
                    : team
                      ? Math.round(itemSubtotal * gstRate)
                      : 0;
                const itemTotal =
                  itemSubtotal === null ? null : itemSubtotal + (itemGst ?? 0);
                const current = mePlan?.plan.key === item.key;
                const available = onSale(item) && price !== null;
                const isSelected = selectedPlanKey === item.key;
                const isMobileActive = mobileTab === item.key;

                return (
                  <article
                    key={item.key}
                    className={styles.planCard}
                    data-plan={item.key}
                    data-selected={isSelected}
                    data-current={current || undefined}
                    data-mobile-active={isMobileActive}
                  >
                    {isOrganisation ? (
                      <span
                        className={`${styles.planBadge} ${styles.popularBadge}`}
                      >
                        Most popular
                      </span>
                    ) : current ? (
                      <span
                        className={`${styles.planBadge} ${styles.currentBadge}`}
                      >
                        Current plan
                      </span>
                    ) : null}

                    <div className={styles.cardHeader}>
                      <div className={styles.cardIconWrap}>
                        {isPersonal && (
                          <CircleUserRound
                            size={22}
                            className={styles.cardIcon}
                            aria-hidden="true"
                          />
                        )}
                        {isOrganisation && (
                          <Users
                            size={22}
                            className={styles.cardIcon}
                            aria-hidden="true"
                          />
                        )}
                        {isEnterprise && (
                          <Building2
                            size={22}
                            className={styles.cardIcon}
                            aria-hidden="true"
                          />
                        )}
                      </div>
                      <div>
                        <h3 className={styles.cardTitle}>{item.name}</h3>
                        <p className={styles.tagline}>
                          {isPersonal &&
                            "For individual sales closers and consultants"}
                          {isOrganisation && "For high-performing sales teams"}
                          {isEnterprise && "For enterprise sales organizations"}
                        </p>
                      </div>
                    </div>

                    <div className={styles.priceBlock}>
                      <p className={styles.price}>
                        {price === null ? "Price unavailable" : money(price)}
                      </p>
                      <span className={styles.priceSub}>
                        {team ? "per seat / " : "/ "}
                        {interval === "month" ? "month" : "year"} ·{" "}
                        {team ? "+ 18% GST" : "GST included"}
                      </span>
                    </div>

                    {/* Seat Stepper for Organisation & Enterprise */}
                    {team ? (
                      <div className={styles.seatsArea}>
                        <div className={styles.seatsHeader}>
                          <span className={styles.seatsLabel}>
                            Seats ({isOrganisation ? "2–49" : "50+"})
                          </span>
                          <div
                            className={styles.stepper}
                            role="group"
                            aria-label={`Seats for ${item.name}`}
                          >
                            <button
                              type="button"
                              aria-label={`Decrease seats for ${item.name}`}
                              disabled={busy || number <= defaultMin}
                              onClick={() => changeSeats(item.key, number - 1)}
                            >
                              <Minus size={14} aria-hidden="true" />
                            </button>
                            <output aria-live="polite">{number}</output>
                            <button
                              type="button"
                              aria-label={`Increase seats for ${item.name}`}
                              disabled={
                                busy ||
                                (item.seatMax !== null &&
                                  number >= item.seatMax)
                              }
                              onClick={() => changeSeats(item.key, number + 1)}
                            >
                              <Plus size={14} aria-hidden="true" />
                            </button>
                          </div>
                        </div>

                        {itemTotal !== null ? (
                          <div className={styles.liveTotalLine}>
                            <span>
                              {number} seats · <b>{money(itemTotal)}</b> a{" "}
                              {interval === "month" ? "month" : "year"} incl.
                              GST
                            </span>
                          </div>
                        ) : null}
                      </div>
                    ) : null}

                    {/* Feature list */}
                    <ul className={styles.featureList}>
                      {isEnterprise ? (
                        <li>
                          <Check
                            size={14}
                            className={styles.iconGood}
                            aria-hidden="true"
                          />
                          <span>Everything in Organisation</span>
                        </li>
                      ) : null}

                      {item.includedMinutes !== null ? (
                        <li>
                          <Check
                            size={14}
                            className={styles.iconGood}
                            aria-hidden="true"
                          />
                          <span>
                            {count(item.includedMinutes * (team ? number : 1))}{" "}
                            {team ? "pooled " : ""}analysis minutes / mo
                          </span>
                        </li>
                      ) : null}

                      {item.longestCallMinutes !== null ? (
                        <li>
                          <Check
                            size={14}
                            className={styles.iconGood}
                            aria-hidden="true"
                          />
                          <span>
                            Calls up to {item.longestCallMinutes} minutes long
                          </span>
                        </li>
                      ) : null}

                      {isPersonal && (
                        <li>
                          <Check
                            size={14}
                            className={styles.iconGood}
                            aria-hidden="true"
                          />
                          <span>1 user seat</span>
                        </li>
                      )}

                      {isOrganisation && (
                        <li>
                          <Check
                            size={14}
                            className={styles.iconGood}
                            aria-hidden="true"
                          />
                          <span>Team dashboard &amp; shared call library</span>
                        </li>
                      )}

                      {isEnterprise && (
                        <>
                          <li>
                            <Check
                              size={14}
                              className={styles.iconGood}
                              aria-hidden="true"
                            />
                            <span>Priority support</span>
                          </li>
                          <li>
                            <Check
                              size={14}
                              className={styles.iconGood}
                              aria-hidden="true"
                            />
                            <span>Onboarding session for the team</span>
                          </li>
                        </>
                      )}
                    </ul>

                    <button
                      type="button"
                      className={styles.planActionBtn}
                      data-primary={!current || undefined}
                      disabled={busy || current || !available}
                      onClick={() => choosePlan(item.key)}
                    >
                      {current
                        ? "Current plan"
                        : !available
                          ? "Unavailable"
                          : `Get ${item.name}`}
                    </button>
                  </article>
                );
              })}
            </div>

            {/* Bottom Satisfaction Guarantee */}
            <footer className={styles.ladderFooter}>
              <span className={styles.ladderGuarantee}>
                <b>Satisfaction guarantee:</b> Full refund within 7 days if none
                of this payment&apos;s minutes were used.
              </span>
            </footer>
          </div>
        )}

        {/* Checkout Drawer (Side panel, never at page bottom) */}
        <CheckoutDrawer
          key={selectedPlanKey ?? selectedTopUp?.key ?? "none"}
          open={Boolean(selectedPlanKey || selectedTopUp)}
          onClose={closeCheckout}
          item={
            selectedPlanKey && plan
              ? {
                  type: "plan",
                  plan,
                  interval,
                  seats,
                }
              : selectedTopUp
                ? {
                    type: "top_up",
                    pack: selectedTopUp,
                  }
                : null
          }
          gstRate={gstRate}
          busy={busy}
          confirmedOrder={confirmedOrder}
          checkoutProvider={confirmedOrder ? checkoutProvider : undefined}
          quoted={quoted}
          onPay={handlePay}
          onBuyerChange={() => selection && onSelectionChange?.(selection)}
          summaryRef={summaryRef}
        />
      </div>
    </PurchaseShell>
  );
}
