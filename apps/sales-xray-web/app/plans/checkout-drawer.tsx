"use client";

import {
  CreditCard,
  ExternalLink,
  Landmark,
  ShieldCheck,
  Smartphone,
  X,
} from "lucide-react";
import { useEffect, useEffectEvent, useRef, useState } from "react";
import type { Buyer } from "../billing/billing-api";
import type { Hosted, Interval, Order, Plan } from "../billing/contract";
import { count, day, money } from "../billing/money";
import type { DisplayTopUpPack } from "./plans-catalogue-fixture";
import type { PurchaseQuote } from "./plans-screen";
import styles from "./plans.module.css";

export type CheckoutDrawerItem =
  | {
      type: "plan";
      plan: Plan;
      interval: Interval;
      seats: number;
    }
  | {
      type: "top_up";
      pack: DisplayTopUpPack;
    };

export type CheckoutDrawerProps = {
  open: boolean;
  onClose: () => void;
  item: CheckoutDrawerItem | null;
  gstRate: number;
  busy?: boolean;
  confirmedOrder?: Order | null;
  checkoutProvider?: Hosted["provider"];
  quoted?: PurchaseQuote | null;
  onPay?: (buyer?: Buyer) => void;
  onBuyerChange?: () => void;
  summaryRef?: React.RefObject<HTMLElement | null>;
};

/**
 * Reusable side panel checkout for plans, credit packs, and minute top-ups.
 * Slides in from the right on desktop, or up as a full sheet on mobile.
 * Never rendered at the page bottom.
 */
export function CheckoutDrawer({
  open,
  onClose,
  item,
  gstRate,
  busy = false,
  confirmedOrder,
  checkoutProvider,
  quoted,
  onPay,
  onBuyerChange,
  summaryRef,
}: CheckoutDrawerProps) {
  const [buyerName, setBuyerName] = useState("");
  const [gstin, setGstin] = useState("");
  const localSummaryRef = useRef<HTMLElement>(null);
  const panelRef = summaryRef ?? localSummaryRef;
  const visible = open && item !== null;
  const dismiss = useEffectEvent(() => {
    if (!busy) onClose();
  });
  const providerHasFocus = useEffectEvent(
    (target: EventTarget | null) =>
      busy && target instanceof Node && !panelRef.current?.contains(target),
  );

  useEffect(() => {
    const panel = panelRef.current;
    if (!visible || !panel) return;
    const previousFocus = document.activeElement;
    // Keep the ancestor path usable, including when checkout is inside Settings.
    const background: Array<{ node: HTMLElement; inert: boolean }> = [];
    let branch: HTMLElement = panel;
    while (branch.parentElement) {
      for (const sibling of branch.parentElement.children) {
        if (
          sibling instanceof HTMLElement &&
          sibling !== branch &&
          sibling !== panel.previousElementSibling
        ) {
          background.push({
            node: sibling,
            inert: sibling.hasAttribute("inert"),
          });
          sibling.setAttribute("inert", "");
        }
      }
      branch = branch.parentElement;
      if (branch === document.body) break;
    }
    panel.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      // Hosted payment may mount its own controls outside this drawer.
      if (providerHasFocus(event.target)) return;
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        dismiss();
      }
      if (event.key !== "Tab") return;
      const controls = [
        ...panel.querySelectorAll<HTMLElement>(
          'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ),
      ].filter(
        (node) => node.tabIndex >= 0 && !node.closest("[hidden], [inert]"),
      );
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (!first || !last) {
        event.preventDefault();
        panel.focus();
      } else if (
        !panel.contains(document.activeElement) ||
        document.activeElement === panel ||
        (event.shiftKey && document.activeElement === first) ||
        (!event.shiftKey && document.activeElement === last)
      ) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      }
    };
    const onFocus = (event: FocusEvent) => {
      if (
        !panel.contains(event.target as Node) &&
        !providerHasFocus(event.target)
      )
        panel.focus();
    };
    document.addEventListener("keydown", onKeyDown, true);
    document.addEventListener("focusin", onFocus);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      document.removeEventListener("focusin", onFocus);
      for (const { node, inert } of background) {
        if (!inert) node.removeAttribute("inert");
      }
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected)
        previousFocus.focus();
    };
  }, [visible, panelRef]);

  if (!open || !item) return null;

  const testPayment = checkoutProvider === "fake";
  const isPlan = item.type === "plan";
  const plan = isPlan ? item.plan : null;
  const interval = isPlan ? item.interval : "month";
  const seats = isPlan ? item.seats : 1;
  const topUp = !isPlan ? item.pack : null;
  const period = interval === "month" ? "month" : "year";

  let subtotal: number | null = null;
  let gst: number = 0;
  let total: number | null = null;

  if (isPlan && plan) {
    const unitPrice =
      interval === "month"
        ? (plan.prices?.monthlyPaise ?? null)
        : (plan.prices?.yearlyPaise ?? null);
    const baseSubtotal = unitPrice === null ? null : unitPrice * seats;

    subtotal =
      confirmedOrder?.tax?.taxableMinor ??
      quoted?.subtotalPaise ??
      baseSubtotal;

    gst =
      confirmedOrder?.tax?.gstMinor ??
      quoted?.gstPaise ??
      (subtotal !== null && plan.key !== "personal"
        ? Math.round(subtotal * gstRate)
        : 0);

    total =
      confirmedOrder?.amount.minor ??
      quoted?.totalPaise ??
      (subtotal === null ? null : subtotal + gst);
  } else if (topUp) {
    const topUpGst = topUp.gstInclusive
      ? 0
      : Math.round(topUp.pricePaise * gstRate);

    subtotal = confirmedOrder?.tax?.taxableMinor ?? topUp.pricePaise;
    gst = confirmedOrder?.tax?.gstMinor ?? topUpGst;
    total = confirmedOrder?.amount.minor ?? topUp.pricePaise + gst;
  }

  const team = isPlan && plan?.key !== "personal";
  const unit =
    isPlan && plan
      ? interval === "month"
        ? (plan.prices?.monthlyPaise ?? null)
        : (plan.prices?.yearlyPaise ?? null)
      : null;

  return (
    <>
      <div
        className={styles.drawerBackdrop}
        onClick={busy ? undefined : onClose}
        aria-hidden="true"
      />
      <section
        ref={panelRef}
        tabIndex={-1}
        className={`${styles.panel} ${styles.checkoutSheet} ${styles.checkoutDrawer}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="purchase-summary"
      >
        <div className={styles.checkoutHead}>
          <div className={styles.checkoutHeadTitle}>
            <h2 id="purchase-summary">Checkout summary</h2>
            <span className={styles.secureTag}>
              <ShieldCheck size={14} aria-hidden="true" />
              Secure checkout
            </span>
          </div>
          <button
            type="button"
            className={styles.closeDrawerBtn}
            disabled={busy}
            onClick={onClose}
            aria-label="Close checkout"
          >
            <X size={18} aria-hidden="true" />
          </button>
        </div>

        {topUp ? (
          <dl className={styles.rows}>
            <div>
              <dt>Item</dt>
              <dd>{topUp.title}</dd>
            </div>
            <div>
              <dt>Minutes</dt>
              <dd>+{topUp.minutes} minutes</dd>
            </div>
            <div>
              <dt>{confirmedOrder?.tax ? "Taxable value" : "Subtotal"}</dt>
              <dd>{money(subtotal ?? topUp.pricePaise)}</dd>
            </div>
            <div>
              <dt>GST</dt>
              <dd>
                {confirmedOrder?.tax
                  ? money(confirmedOrder.tax.gstMinor)
                  : topUp.gstInclusive
                    ? "Included"
                    : `${gstRate * 100}% GST (${money(gst)})`}
              </dd>
            </div>
            <div>
              <dt>Renewal</dt>
              <dd>One-time payment (no renewal)</dd>
            </div>
            <div className={styles.total}>
              <dt>Total today</dt>
              <dd>{money(total ?? 0)}</dd>
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
            <div>
              <dt>Seats</dt>
              <dd>
                {seats} {seats === 1 ? "seat" : "seats"}
              </dd>
            </div>
            {team ? (
              <>
                <div>
                  <dt>Price per seat</dt>
                  <dd>{unit === null ? "—" : `${money(unit)} / ${period}`}</dd>
                </div>
                <div>
                  <dt>
                    {confirmedOrder?.tax
                      ? "Taxable value"
                      : `Subtotal (${seats} ${seats === 1 ? "seat" : "seats"})`}
                  </dt>
                  <dd>{subtotal === null ? "—" : money(subtotal)}</dd>
                </div>
                <div>
                  <dt>GST ({gstRate * 100}%)</dt>
                  <dd>{money(gst)}</dd>
                </div>
              </>
            ) : (
              <>
                <div>
                  <dt>
                    {confirmedOrder?.tax
                      ? "Taxable value"
                      : "Subtotal (1 seat)"}
                  </dt>
                  <dd>{subtotal === null ? "—" : money(subtotal)}</dd>
                </div>
                <div>
                  <dt>GST</dt>
                  <dd>
                    {confirmedOrder?.tax
                      ? `${money(confirmedOrder.tax.gstMinor)} included`
                      : "Included"}
                  </dd>
                </div>
              </>
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
                  : "Date and amount confirmed at checkout"}
              </dd>
            </div>
            <div className={styles.total}>
              <dt>Total today</dt>
              <dd>{total === null ? "—" : money(total)}</dd>
            </div>
          </dl>
        ) : null}

        {team ? (
          <form
            id="checkout-buyer"
            className={styles.fields}
            onSubmit={(event) => {
              event.preventDefault();
              onPay?.({ name: buyerName.trim(), gstin: gstin || null });
            }}
          >
            <label className={styles.field}>
              Organisation name
              <input
                required
                maxLength={200}
                pattern={".*\\S.*"}
                autoComplete="organization"
                value={buyerName}
                disabled={busy}
                onChange={(event) => {
                  setBuyerName(event.target.value);
                  onBuyerChange?.();
                }}
              />
            </label>
            <label className={styles.field}>
              GSTIN (optional)
              <input
                maxLength={15}
                pattern="[0-9]{2}[A-Z0-9]{13}"
                title="Enter a 15-character GSTIN starting with two digits."
                value={gstin}
                disabled={busy}
                onChange={(event) => {
                  setGstin(event.target.value.trim().toUpperCase());
                  onBuyerChange?.();
                }}
              />
            </label>
          </form>
        ) : null}

        {confirmedOrder ? (
          <p role="status" className={styles.hint}>
            {testPayment
              ? "Total confirmed. Continue to the simulated payment page."
              : "Total confirmed. Continue to the payment page to pay."}
          </p>
        ) : null}

        {total !== null && total > 1_500_000 && isPlan ? (
          <p className={styles.note}>
            Your bank will ask you to approve each renewal above ₹15,000.
          </p>
        ) : null}

        {/* Payment Methods */}
        {!testPayment ? (
          <div className={styles.paymentMethodsBlock}>
            <span className={styles.paymentMethodsLabel}>
              Accepted payment methods:
            </span>
            <div className={styles.paymentBadges}>
              <span className={styles.methodBadge}>
                <Smartphone size={14} aria-hidden="true" /> UPI
              </span>
              <span className={styles.methodBadge}>
                <CreditCard size={14} aria-hidden="true" /> Cards
              </span>
              <span className={styles.methodBadge}>
                <Landmark size={14} aria-hidden="true" /> Netbanking
              </span>
            </div>
            <p className={styles.razorpayTag}>
              Paid securely through Razorpay.
            </p>
          </div>
        ) : null}

        {/* Refund & Guarantee */}
        <div className={styles.guaranteeBox}>
          <ShieldCheck
            size={16}
            className={styles.iconGood}
            aria-hidden="true"
          />
          <div>
            <p className={styles.guaranteeText}>
              <b>Satisfaction guarantee:</b> Full refund within 7 days if none
              of this payment&apos;s minutes were used.
            </p>
            <p className={styles.legalLinks}>
              By proceeding, you agree to our{" "}
              <a href="/terms" target="_blank" rel="noreferrer">
                Terms of Service <ExternalLink size={11} aria-hidden="true" />
              </a>{" "}
              and{" "}
              <a href="/refunds" target="_blank" rel="noreferrer">
                Refund Policy <ExternalLink size={11} aria-hidden="true" />
              </a>
              .
            </p>
          </div>
        </div>

        {testPayment ? (
          <p role="status" className={`${styles.note} ${styles.warn}`}>
            <strong>Test payment · no money moves</strong>
          </p>
        ) : null}

        {/* Actions */}
        <div className={styles.actions}>
          <button
            type={team ? "submit" : "button"}
            form={team ? "checkout-buyer" : undefined}
            className={styles.pay}
            disabled={busy || !onPay}
            onClick={team ? undefined : () => onPay?.()}
          >
            {busy
              ? "Opening checkout…"
              : testPayment
                ? "Continue to test payment"
                : !confirmedOrder && !quoted
                  ? "Review total with Razorpay"
                  : `Pay ${total !== null ? money(total) : ""} with Razorpay`}
          </button>
          <button
            type="button"
            className={styles.ghost}
            disabled={busy}
            onClick={onClose}
          >
            Cancel
          </button>
        </div>
      </section>
    </>
  );
}
