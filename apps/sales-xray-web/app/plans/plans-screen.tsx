"use client";

import {
  Building2,
  Check,
  CircleUserRound,
  ExternalLink,
  Minus,
  Plus,
  ShieldCheck,
  Sparkles,
  Users,
  Zap,
} from "lucide-react";
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

export type TopUpPack = {
  key: string;
  planKey: string;
  title: string;
  audience: string;
  minutes: number;
  pricePaise: number;
  gstInclusive: boolean;
  priceFormatted: string;
  totalFormatted: string;
  gstNote: string;
};

export const TOP_UP_PACKS: TopUpPack[] = [
  {
    key: "personal_100",
    planKey: "personal",
    title: "Personal Top-up",
    audience: "For individual closers",
    minutes: 100,
    pricePaise: 29900,
    gstInclusive: true,
    priceFormatted: "₹299",
    totalFormatted: "₹299",
    gstNote: "GST included",
  },
  {
    key: "organisation_500",
    planKey: "organisation",
    title: "Organisation Top-up",
    audience: "Shared pool for your sales team",
    minutes: 500,
    pricePaise: 129900,
    gstInclusive: false,
    priceFormatted: "₹1,299",
    totalFormatted: "₹1,533",
    gstNote: "+ 18% GST (₹234)",
  },
];

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
  allowance?: Allowance | null;
};

/**
 * Screen presentation for the subscription purchase ladder, top-ups and checkout.
 * Built strictly to the owner order:
 * - Top toggles: Just me | My team, Monthly | Yearly (save 10%)
 * - Three cards side by side with distinctive icons (Person, People, Building)
 * - Organisation marked "Most popular", stepper 2–49 seats, live total with GST
 * - Enterprise stepper 50+ seats, self-serve with CEO-approved extras
 * - Top-ups row: Personal 100 min for ₹299 (GST incl), Organisation 500 min for ₹1,299 + GST
 * - Detailed checkout sheet and complete post-purchase success screen
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
  allowance,
}: PlansScreenProps) {
  const access = useWorkspaceAccess();
  const [audienceScope, setAudienceScope] = useState<"personal" | "team">(
    "personal",
  );
  const [interval, setInterval] = useState<Interval>("month");
  const [seatCounts, setSeatCounts] = useState<Record<string, number>>({});
  const [selectedPlanKey, setSelectedPlanKey] = useState<string | null>(null);
  const [selectedTopUp, setSelectedTopUp] = useState<TopUpPack | null>(null);
  const summaryRef = useRef<HTMLElement>(null);

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

  const choosePlan = (key: string) => {
    setSelectedTopUp(null);
    setSelectedPlanKey(key);
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
    requestAnimationFrame(() => {
      summaryRef.current?.focus();
      summaryRef.current?.scrollIntoView({
        block: "nearest",
        behavior: "smooth",
      });
    });
  };

  const chooseTopUp = (pack: TopUpPack) => {
    setSelectedPlanKey(null);
    setSelectedTopUp(pack);
    requestAnimationFrame(() => {
      summaryRef.current?.focus();
      summaryRef.current?.scrollIntoView({
        block: "nearest",
        behavior: "smooth",
      });
    });
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

  const handleAudienceChange = (nextScope: "personal" | "team") => {
    setAudienceScope(nextScope);
    if (nextScope === "personal") {
      choosePlan("personal");
    } else {
      choosePlan("organisation");
    }
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
            <Sparkles size={20} aria-hidden="true" />
            <h1>Plans &amp; Pricing</h1>
          </div>
          <Link className={styles.ghost} href="/account#billing">
            Billing &amp; receipts
          </Link>
        </header>

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
            <p className={styles.successAllowance}>
              {allowance
                ? allowance.unlimited
                  ? "Unlimited analysis minutes available on your account."
                  : `${count(minutes(allowance.availableSeconds))} analysis minutes added to your account.`
                : "Your analysis minutes have been credited to your workspace."}
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
        ) : null}

        <section className={styles.panel}>
          <div className={styles.panelHeaderRow}>
            <div>
              <h2>Choose your subscription</h2>
              <p className={styles.hint}>
                Select the plan that fits your sales rhythm. Upgrade, downgrade,
                or cancel anytime.
              </p>
            </div>
            {mePlan ? (
              <div className={styles.trial}>
                <span>
                  <b>Current: {mePlan.plan.name}</b> ·{" "}
                  {mePlan.allowance.unlimited
                    ? "Unlimited analysis time"
                    : `${count(minutes(mePlan.allowance.availableSeconds))} minutes left`}
                </span>
              </div>
            ) : null}
          </div>

          {/* Top Toggles: Just me | My team & Monthly | Yearly · save 10% */}
          <div className={styles.controlsRow}>
            <div className={styles.segGroup}>
              <span className={styles.segLabel}>Audience</span>
              <div
                className={styles.seg}
                role="group"
                aria-label="Target audience"
              >
                <button
                  type="button"
                  aria-pressed={audienceScope === "personal"}
                  disabled={busy}
                  onClick={() => handleAudienceChange("personal")}
                >
                  Just me
                </button>
                <button
                  type="button"
                  aria-pressed={audienceScope === "team"}
                  disabled={busy}
                  onClick={() => handleAudienceChange("team")}
                >
                  My team
                </button>
              </div>
            </div>

            <div className={styles.segGroup}>
              <span className={styles.segLabel}>Billing cycle</span>
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

          {/* Three cards side by side */}
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

              return (
                <article
                  key={item.key}
                  className={styles.planCard}
                  data-plan={item.key}
                  data-selected={isSelected}
                  data-current={current || undefined}
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
                          size={24}
                          className={styles.cardIcon}
                          aria-hidden="true"
                        />
                      )}
                      {isOrganisation && (
                        <Users
                          size={24}
                          className={styles.cardIcon}
                          aria-hidden="true"
                        />
                      )}
                      {isEnterprise && (
                        <Building2
                          size={24}
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
                      {period} · {team ? "+ 18% GST" : "GST included"}
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
                            <Minus size={15} aria-hidden="true" />
                          </button>
                          <output aria-live="polite">{number}</output>
                          <button
                            type="button"
                            aria-label={`Increase seats for ${item.name}`}
                            disabled={
                              busy ||
                              (item.seatMax !== null && number >= item.seatMax)
                            }
                            onClick={() => changeSeats(item.key, number + 1)}
                          >
                            <Plus size={15} aria-hidden="true" />
                          </button>
                        </div>
                      </div>

                      {itemTotal !== null ? (
                        <div className={styles.liveTotalLine}>
                          <span>
                            {number} seats · <b>{money(itemTotal)}</b> a{" "}
                            {period} incl. GST
                          </span>
                        </div>
                      ) : null}
                    </div>
                  ) : null}

                  {/* Feature list with green checks */}
                  <ul className={styles.featureList}>
                    {isEnterprise ? (
                      <li>
                        <Check
                          size={15}
                          className={styles.iconGood}
                          aria-hidden="true"
                        />
                        <span>Everything in Organisation</span>
                      </li>
                    ) : null}

                    {item.includedMinutes !== null ? (
                      <li>
                        <Check
                          size={15}
                          className={styles.iconGood}
                          aria-hidden="true"
                        />
                        <span>
                          {count(item.includedMinutes * (team ? number : 1))}{" "}
                          {team ? "pooled " : ""}analysis minutes every month
                        </span>
                      </li>
                    ) : null}

                    {item.longestCallMinutes !== null ? (
                      <li>
                        <Check
                          size={15}
                          className={styles.iconGood}
                          aria-hidden="true"
                        />
                        <span>
                          Calls up to {item.longestCallMinutes} minutes long
                        </span>
                      </li>
                    ) : null}

                    {isPersonal && (
                      <>
                        <li>
                          <Check
                            size={15}
                            className={styles.iconGood}
                            aria-hidden="true"
                          />
                          <span>1 user seat</span>
                        </li>
                        <li>
                          <Check
                            size={15}
                            className={styles.iconGood}
                            aria-hidden="true"
                          />
                          <span>
                            Instant call scoring &amp; transcript insights
                          </span>
                        </li>
                        <li>
                          <Check
                            size={15}
                            className={styles.iconGood}
                            aria-hidden="true"
                          />
                          <span>Unused minutes roll over for 1 month</span>
                        </li>
                      </>
                    )}

                    {isOrganisation && (
                      <>
                        <li>
                          <Check
                            size={15}
                            className={styles.iconGood}
                            aria-hidden="true"
                          />
                          <span>Team dashboard &amp; shared call library</span>
                        </li>
                        <li>
                          <Check
                            size={15}
                            className={styles.iconGood}
                            aria-hidden="true"
                          />
                          <span>
                            Centralized team billing &amp; seat management
                          </span>
                        </li>
                        <li>
                          <Check
                            size={15}
                            className={styles.iconGood}
                            aria-hidden="true"
                          />
                          <span>Dedicated workspace for your team</span>
                        </li>
                      </>
                    )}

                    {isEnterprise && (
                      <>
                        <li>
                          <Check
                            size={15}
                            className={styles.iconGood}
                            aria-hidden="true"
                          />
                          <span>Priority support</span>
                        </li>
                        <li>
                          <Check
                            size={15}
                            className={styles.iconGood}
                            aria-hidden="true"
                          />
                          <span>Onboarding session for the team</span>
                        </li>
                        <li>
                          <Check
                            size={15}
                            className={styles.iconGood}
                            aria-hidden="true"
                          />
                          <span>
                            Single sign-on (SSO) &amp; custom governance
                          </span>
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

          {/* Top-ups Row: Need more minutes? */}
          <div className={styles.topUpsSection} id="topups">
            <div className={styles.topUpsHeader}>
              <div className={styles.topUpsTitle}>
                <Zap
                  size={18}
                  className={styles.topUpIcon}
                  aria-hidden="true"
                />
                <h3>Need more minutes?</h3>
              </div>
              <p className={styles.hint}>
                Top up anytime without changing your monthly subscription.
                Minutes appear immediately.
              </p>
            </div>

            <div className={styles.topUpsGrid}>
              {TOP_UP_PACKS.map((pack) => {
                const isSelected = selectedTopUp?.key === pack.key;
                return (
                  <div
                    key={pack.key}
                    className={styles.topUpCard}
                    data-selected={isSelected}
                  >
                    <div className={styles.topUpHead}>
                      <div>
                        <h4>{pack.title}</h4>
                        <p className={styles.topUpTagline}>{pack.audience}</p>
                      </div>
                      <span className={styles.topUpPriceBadge}>
                        {pack.priceFormatted}
                        <small>{pack.gstNote}</small>
                      </span>
                    </div>

                    <div className={styles.topUpBody}>
                      <span className={styles.topUpMinutes}>
                        +{pack.minutes} analysis minutes
                      </span>
                      <button
                        type="button"
                        className={styles.ghost}
                        disabled={busy}
                        onClick={() => chooseTopUp(pack)}
                      >
                        Top up {pack.totalFormatted}
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </section>

        {/* Detailed Checkout Sheet */}
        {(selection && plan) || selectedTopUp ? (
          <section
            ref={summaryRef}
            tabIndex={-1}
            className={`${styles.panel} ${styles.checkoutSheet}`}
            aria-labelledby="purchase-summary"
          >
            <div className={styles.checkoutHead}>
              <h2 id="purchase-summary">Checkout summary</h2>
              <span className={styles.secureTag}>
                <ShieldCheck size={15} aria-hidden="true" />
                256-bit SSL encrypted
              </span>
            </div>

            {selectedTopUp ? (
              <dl className={styles.rows}>
                <div>
                  <dt>Item</dt>
                  <dd>{selectedTopUp.title}</dd>
                </div>
                <div>
                  <dt>Minutes</dt>
                  <dd>+{selectedTopUp.minutes} minutes</dd>
                </div>
                <div>
                  <dt>Subtotal</dt>
                  <dd>{selectedTopUp.priceFormatted}</dd>
                </div>
                <div>
                  <dt>GST</dt>
                  <dd>
                    {selectedTopUp.gstInclusive ? "Included" : "18% GST (₹234)"}
                  </dd>
                </div>
                <div>
                  <dt>Renewal</dt>
                  <dd>One-time payment (no renewal)</dd>
                </div>
                <div className={styles.total}>
                  <dt>Total today</dt>
                  <dd>{selectedTopUp.totalFormatted}</dd>
                </div>
              </dl>
            ) : plan ? (
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
                      <dt>Price per seat</dt>
                      <dd>
                        {unit === null ? "—" : `${money(unit)} / ${period}`}
                      </dd>
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
                  <dt>Analysis minutes</dt>
                  <dd>
                    {plan.includedMinutes !== null
                      ? `${count(plan.includedMinutes * (plan.key === "personal" ? 1 : seats))} minutes / month`
                      : "Standard"}
                  </dd>
                </div>
                <div>
                  <dt>Next renewal</dt>
                  <dd>
                    {quoted
                      ? `${day(quoted.renewsAt)} · ${money(total ?? 0)}`
                      : `In 1 ${period} on the same date`}
                  </dd>
                </div>
                <div className={styles.total}>
                  <dt>Total today</dt>
                  <dd>{total === null ? "—" : money(total)}</dd>
                </div>
              </dl>
            ) : null}

            {/* Payment Method Badges & Assurance */}
            <div className={styles.paymentMethodsBlock}>
              <span className={styles.paymentMethodsLabel}>
                Accepted payment methods:
              </span>
              <div className={styles.paymentBadges}>
                <span className={styles.methodBadge}>UPI / QR</span>
                <span className={styles.methodBadge}>Visa</span>
                <span className={styles.methodBadge}>Mastercard</span>
                <span className={styles.methodBadge}>RuPay</span>
                <span className={styles.methodBadge}>Netbanking</span>
              </div>
              <p className={styles.razorpayTag}>
                Paid securely through Razorpay. We never store card or UPI
                credentials.
              </p>
            </div>

            {/* Refund & Terms Guarantee */}
            <div className={styles.guaranteeBox}>
              <ShieldCheck
                size={16}
                className={styles.iconGood}
                aria-hidden="true"
              />
              <div>
                <p className={styles.guaranteeText}>
                  <b>Satisfaction guarantee:</b> Full refund within 7 days if
                  none of this payment&apos;s minutes were used.
                </p>
                <p className={styles.legalLinks}>
                  By proceeding, you agree to our{" "}
                  <a href="/terms" target="_blank" rel="noreferrer">
                    Terms of Service{" "}
                    <ExternalLink size={11} aria-hidden="true" />
                  </a>{" "}
                  and{" "}
                  <a href="/refunds" target="_blank" rel="noreferrer">
                    Refund Policy <ExternalLink size={11} aria-hidden="true" />
                  </a>
                  .
                </p>
              </div>
            </div>

            {error ? (
              <p role="alert" className={styles.note}>
                {error}
              </p>
            ) : null}

            <div className={styles.actions}>
              <button
                type="button"
                className={styles.pay}
                disabled={busy}
                onClick={() => {
                  if (selectedTopUp) {
                    onBuyTopUp?.(selectedTopUp);
                  } else if (selection) {
                    onBuy?.(selection);
                  }
                }}
              >
                {busy
                  ? "Opening checkout…"
                  : selectedTopUp
                    ? `Pay ${selectedTopUp.totalFormatted} with Razorpay`
                    : `Pay ${total !== null ? money(total) : ""} with Razorpay`}
              </button>
              <button
                type="button"
                className={styles.ghost}
                disabled={busy}
                onClick={() => {
                  setSelectedPlanKey(null);
                  setSelectedTopUp(null);
                }}
              >
                Cancel
              </button>
            </div>
          </section>
        ) : null}
      </div>
    </AcquisitionShell>
  );
}
