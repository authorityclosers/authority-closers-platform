"use client";

import {
  Building2,
  Check,
  Copy,
  ExternalLink,
  Minus,
  Plus,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { QRCodeSVG } from "qrcode.react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { AcquisitionShell } from "../acquisition-shell";
import {
  BillingError,
  idempotencyKey,
  liveBilling,
  notOnSale,
  returnPath,
  signedOut,
  type BillingClient,
} from "../billing/billing-api";
import {
  onSale,
  type Account,
  type Allowance,
  type Hosted,
  type Interval,
  type MePlan,
  type OfflinePayment,
  type Plan,
  type Subscription,
  type Subscriptions,
} from "../billing/contract";
import {
  count,
  day,
  formatMoney,
  minutes,
  money,
  planPrice,
  yearlySaving,
} from "../billing/money";
import { notify } from "../notice-center";
import { useWorkspaceAccess } from "../workspace-access";
import { openHostedCheckout } from "./hosted-checkout";
import styles from "./plans.module.css";

/** Above this one renewal, the bank asks the customer to approve each renewal (RBI e-mandate). */
const APPROVAL_LIMIT_PAISE = 15_000 * 100;
const PLAN_KEY: Record<Account, string> = {
  personal: "personal",
  organisation: "organisation",
};
const ENTERPRISE_KEY = "enterprise";
const CONTACT = "admin@authorityclosers.com";

type Loaded<T> =
  | { status: "loading" }
  | { status: "ready"; value: T }
  | { status: "missing" }
  | { status: "error" };

function useLoaded<T>(
  read: (signal: AbortSignal) => Promise<T>,
  enabled: boolean,
  deps: unknown[],
) {
  const [state, setState] = useState<Loaded<T> & { key?: string }>({
    status: "loading",
  });
  const [tick, setTick] = useState(0);
  const key = JSON.stringify([enabled, tick, ...deps]);
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    read(controller.signal)
      .then((value) => setState({ status: "ready", value, key }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({
          status: notOnSale(error) || signedOut(error) ? "missing" : "error",
          key,
        });
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, key]);
  // A result from an older read shows as loading until the current one lands.
  const current: Loaded<T> =
    state.key === key || state.status === "loading"
      ? state
      : { status: "loading" };
  return [current, () => setTick((n) => n + 1)] as const;
}

const liveSubscription = (subs: Subscriptions | null): Subscription | null => {
  const current = subs?.current ?? null;
  if (!current) return null;
  return ["pending_authorisation", "active", "past_due", "halted"].includes(
    current.status,
  )
    ? current
    : null;
};

function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: Array<{ value: T; label: ReactNode }>;
  onChange: (value: T) => void;
}) {
  return (
    <div className={styles.seg} role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={value === option.value}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function Steps({ current }: { current: "choose" | "pay" | "subscription" }) {
  const order = ["choose", "pay", "subscription"] as const;
  const labels = {
    choose: "Choose a plan",
    pay: "Pay",
    subscription: "Subscription status",
  };
  return (
    <ol className={styles.steps} aria-label="Purchase steps">
      {order.map((step, index) => (
        <li
          key={step}
          data-on={order.indexOf(current) >= index ? "true" : undefined}
        >
          <i aria-hidden="true">{index + 1}</i>
          {labels[step]}
        </li>
      ))}
    </ol>
  );
}

function TrialStrip({ me }: { me: MePlan | null }) {
  if (!me)
    return (
      <div className={styles.trial}>
        <span>Current plan and minutes unavailable</span>
      </div>
    );
  const a = me.allowance;
  if (a.unlimited)
    return (
      <div className={styles.trial}>
        <span>
          <b>{me.plan.name}</b> · unlimited analysis time
        </span>
      </div>
    );
  const left = minutes(a.availableSeconds);
  const total = minutes(a.allowanceSeconds);
  const share =
    a.allowanceSeconds > 0
      ? Math.min(1, a.availableSeconds / a.allowanceSeconds)
      : 0;
  return (
    <div className={styles.trial}>
      <span>
        <b>{me.plan.name}</b> · {count(left)} of {count(total)} minutes left
      </span>
      <span className={styles.bar} aria-hidden="true">
        <i style={{ width: `${share * 100}%` }} />
      </span>
    </div>
  );
}

function CopyButton({ value, label }: { value: string; label: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      className={styles.copy}
      aria-label={`Copy ${label}`}
      onClick={() => {
        navigator.clipboard?.writeText(value).then(
          () => {
            setDone(true);
            setTimeout(() => setDone(false), 1600);
          },
          () => {},
        );
      }}
    >
      {done ? (
        <Check size={14} aria-hidden="true" />
      ) : (
        <Copy size={14} aria-hidden="true" />
      )}
      {done ? "Copied" : "Copy"}
    </button>
  );
}

/** The interim path: pay by UPI or bank transfer, and staff add the minutes. */
function OfflinePay({
  offline,
  amount,
}: {
  offline: OfflinePayment;
  amount: number | null;
}) {
  const upiLink = offline.upiId
    ? `upi://pay?pa=${encodeURIComponent(offline.upiId)}&pn=${encodeURIComponent(offline.payeeName ?? "")}&cu=INR${amount ? `&am=${(amount / 100).toFixed(2)}` : ""}`
    : null;
  return (
    <div className={styles.offline} data-offline-payment>
      <h3>Pay by UPI or bank transfer</h3>
      <p className={styles.hint}>
        After you pay, we add your minutes. Send us the payment reference from{" "}
        {CONTACT.split("@")[0]} if it takes more than one working day.
      </p>
      {upiLink ? (
        <QRCodeSVG
          value={upiLink}
          size={160}
          marginSize={4}
          role="img"
          title="Scan to pay by UPI"
          aria-label="Scan to pay by UPI"
        />
      ) : null}
      {offline.upiId ? (
        <div className={styles.payRow}>
          <span>
            <small>UPI ID</small>
            <b>{offline.upiId}</b>
            {offline.payeeName ? <small>{offline.payeeName}</small> : null}
          </span>
          <span className={styles.payActions}>
            <CopyButton value={offline.upiId} label="UPI ID" />
            {upiLink ? (
              <a className={styles.copy} href={upiLink}>
                <ExternalLink size={14} aria-hidden="true" />
                Open UPI app
              </a>
            ) : null}
          </span>
        </div>
      ) : null}
      {offline.bank ? (
        <div className={styles.payRow}>
          <span>
            <small>Bank transfer · {offline.bank.bankName}</small>
            <b>{offline.bank.accountNumber}</b>
            <small>
              {offline.bank.accountName} · IFSC {offline.bank.ifsc}
            </small>
          </span>
          <span className={styles.payActions}>
            <CopyButton
              value={offline.bank.accountNumber}
              label="account number"
            />
          </span>
        </div>
      ) : null}
      {offline.instructions ? (
        <p className={styles.hint}>{offline.instructions}</p>
      ) : null}
    </div>
  );
}

function EnterpriseSheet({ onClose }: { onClose: () => void }) {
  const [form, setForm] = useState({
    name: "",
    company: "",
    size: "",
    calls: "",
    phone: "",
  });
  const body = [
    `Name: ${form.name}`,
    `Company: ${form.company}`,
    `Team size: ${form.size}`,
    `Calls a month: ${form.calls}`,
    `Phone: ${form.phone}`,
  ].join("\n");
  const href = `mailto:${CONTACT}?subject=${encodeURIComponent("Sales Xray Enterprise")}&body=${encodeURIComponent(body)}`;
  const field = (key: keyof typeof form, label: string, type = "text") => (
    <label className={styles.field}>
      <span>{label}</span>
      <input
        type={type}
        value={form[key]}
        autoComplete={
          key === "name"
            ? "name"
            : key === "phone"
              ? "tel"
              : key === "company"
                ? "organization"
                : "off"
        }
        onChange={(event) => setForm({ ...form, [key]: event.target.value })}
      />
    </label>
  );
  return (
    <div className={styles.sheetBack} role="presentation" onClick={onClose}>
      <div
        className={styles.sheet}
        role="dialog"
        aria-label="Talk to us about Enterprise"
        onClick={(event) => event.stopPropagation()}
      >
        <div className={styles.sheetHead}>
          <h2>Talk to us</h2>
          <button
            type="button"
            className={styles.close}
            aria-label="Close"
            onClick={onClose}
          >
            <X size={16} aria-hidden="true" />
          </button>
        </div>
        <p className={styles.hint}>
          Enterprise is for 50 or more people, single sign-on, invoices on your
          terms and a named contact. Tell us a little and we reply within one
          working day.
        </p>
        <div className={styles.fields}>
          {field("name", "Your name")}
          {field("company", "Company")}
          {field("size", "People on the sales team", "number")}
          {field("calls", "Calls a month", "number")}
          {field("phone", "Phone", "tel")}
        </div>
        <a className={styles.primary} href={href} data-enterprise-send>
          Send by email
        </a>
        <p className={styles.hint}>
          This opens your email app with the details filled in, addressed to{" "}
          {CONTACT}.
        </p>
      </div>
    </div>
  );
}

/**
 * Choose a plan, pay, and manage the plan you are on. Built to the approved
 * prototype (AUT-597) and contract C1: prices come only from GET /v1/plans,
 * minutes only from GET /v1/me/plan, and a plan not on sale says so.
 */
export function PlansView({
  client = liveBilling,
}: {
  client?: BillingClient;
}) {
  const router = useRouter();
  const access = useWorkspaceAccess();
  const authenticated = access?.authenticated === true;

  const [scope, setScope] = useState<Account>("personal");
  const [interval, setInterval_] = useState<Interval>("month");
  const [seats, setSeats] = useState<number | null>(null);
  const [enterprise, setEnterprise] = useState(false);
  const [busy, setBusy] = useState<"checkout" | "top_up" | "cancel" | null>(
    null,
  );
  const [cancelAsk, setCancelAsk] = useState(false);
  const keys = useRef<Record<string, string>>({});
  const keyFor = (action: string) =>
    (keys.current[action] ??= idempotencyKey());

  const [catalogue] = useLoaded((signal) => client.readPlans(signal), true, []);
  const [me] = useLoaded(
    (signal) => client.readMePlan(signal),
    authenticated,
    [],
  );
  const [subs, reloadSubs] = useLoaded(
    (signal) => client.readSubscriptions(scope, signal),
    authenticated,
    [scope],
  );
  const [offline] = useLoaded(
    (signal) => client.readOfflinePayment(signal),
    authenticated,
    [],
  );

  const plans = catalogue.status === "ready" ? catalogue.value : [];
  const plan: Plan | null =
    plans.find((item) => item.key === PLAN_KEY[scope]) ?? null;
  const enterprisePlan =
    plans.find((item) => item.key === ENTERPRISE_KEY) ?? null;
  const buyable =
    plan !== null && onSale(plan) && planPrice(plan, interval) !== null;
  const seatMin = plan?.seatMin ?? null;
  const seatMax = plan?.seatMax ?? null;
  const seatCount = scope === "organisation" ? (seats ?? seatMin ?? 0) : 1;
  const unit = plan ? planPrice(plan, interval) : null;
  const total = unit !== null ? unit * Math.max(1, seatCount) : null;
  const saving = plan ? yearlySaving(plan) : 0;
  const includedMinutes =
    plan?.includedMinutes !== null && plan?.includedMinutes !== undefined
      ? plan.includedMinutes * Math.max(1, seatCount)
      : null;
  const current = liveSubscription(subs.status === "ready" ? subs.value : null);
  const mePlan = me.status === "ready" ? me.value : null;
  const offlinePay =
    offline.status === "ready" && offline.value.enabled ? offline.value : null;
  const stage: "choose" | "pay" | "subscription" = current
    ? "subscription"
    : busy === "checkout"
      ? "pay"
      : "choose";

  const fail = useCallback(
    (error: unknown, fallbackText: string) => {
      const detail =
        error instanceof BillingError && error.detail
          ? error.detail
          : fallbackText;
      if (
        error instanceof BillingError &&
        error.code === "billing_forbidden" &&
        scope === "organisation"
      ) {
        notify({
          id: "billing",
          tone: "info",
          title: "Switch to your organisation first",
          message:
            "Only the organisation owner can buy for the team. Open the organisation workspace, then choose the plan again.",
        });
        return;
      }
      notify({
        id: "billing",
        tone: notOnSale(error) ? "info" : "error",
        title: notOnSale(error) ? "Not on sale yet" : "That did not go through",
        message: notOnSale(error)
          ? "You will see prices here first. Your trial keeps working."
          : detail,
      });
    },
    [scope],
  );

  const goHosted = useCallback(
    async (hosted: Hosted, orderId: string) => {
      const result = await openHostedCheckout(hosted, orderId);
      if (result === "left") return;
      // Both SDK outcomes need the canonical server-read order result.
      router.push(returnPath(orderId));
    },
    [router],
  );

  const pay = async () => {
    if (!plan || !buyable || busy) return;
    if (!authenticated) {
      router.push("/login");
      return;
    }
    setBusy("checkout");
    try {
      const checkout = await client.checkout(
        {
          kind: "subscription",
          account: scope,
          planKey: plan.key,
          interval,
          seats: seatCount,
        },
        keyFor(`checkout:${scope}:${plan.key}:${interval}:${seatCount}`),
      );
      await goHosted(checkout.hosted, checkout.order.orderId);
    } catch (error) {
      fail(error, "Please try again in a moment.");
    } finally {
      setBusy(null);
    }
  };

  const topUp = async (packKey: string) => {
    if (!plan || busy) return;
    setBusy("top_up");
    try {
      const checkout = await client.checkout(
        { kind: "top_up", account: scope, planKey: plan.key, packKey },
        keyFor(`top_up:${scope}:${plan.key}:${packKey}`),
      );
      await goHosted(checkout.hosted, checkout.order.orderId);
    } catch (error) {
      fail(error, "The top-up could not be started.");
    } finally {
      setBusy(null);
    }
  };

  const cancel = async () => {
    if (!current || busy) return;
    setBusy("cancel");
    try {
      await client.cancelSubscription(
        current.subscriptionId,
        null,
        keyFor(`cancel:${current.subscriptionId}`),
      );
      setCancelAsk(false);
      reloadSubs();
      notify({
        id: "billing",
        tone: "success",
        title: "Renewal is off",
        message: `The recorded subscription period ends ${day(current.currentPeriod?.end ?? current.renewsAt)}. Check your current plan and available minutes before analysing a call.`,
        timeout: 6000,
      });
    } catch (error) {
      fail(error, "The renewal could not be stopped. Nothing has changed.");
    } finally {
      setBusy(null);
    }
  };

  const periodWord = interval === "month" ? "month" : "year";
  const perSeat = scope === "organisation" ? " per seat" : "";
  const packs =
    plan?.topUpPacks.filter((pack) => pack.pricePaise !== null) ?? [];

  const chooser = (
    <>
      <div>
        <h2>Choose your plan</h2>
        <p className={styles.hint}>
          Choose a plan and review its details before paying.
        </p>
      </div>
      {authenticated ? <TrialStrip me={mePlan} /> : null}
      <div className={styles.controls}>
        <Segmented
          label="Who is this for"
          value={scope}
          options={[
            { value: "personal", label: "Just me" },
            { value: "organisation", label: "My team" },
          ]}
          onChange={setScope}
        />
        <Segmented
          label="How often you pay"
          value={interval}
          options={[
            { value: "month", label: "Monthly" },
            {
              value: "year",
              label: (
                <>
                  Yearly
                  {saving > 0 ? <small>save {money(saving)}</small> : null}
                </>
              ),
            },
          ]}
          onChange={setInterval_}
        />
      </div>
      {catalogue.status === "loading" ? (
        <div className={styles.skeleton} aria-label="Loading plans">
          <i />
          <i />
          <i />
        </div>
      ) : catalogue.status === "error" ? (
        <p className={styles.note} role="alert">
          The plans could not be loaded. Refresh to try again.
        </p>
      ) : plan ? (
        <div
          className={styles.plan}
          data-plan={plan.key}
          data-on-sale={buyable ? "true" : "false"}
        >
          <div className={styles.planHead}>
            <div>
              <h3>{plan.name}</h3>
              <p className={styles.hint}>{plan.audience}</p>
            </div>
            {buyable && unit !== null ? (
              <p className={styles.price}>
                {money(unit)}
                <small>
                  {perSeat} / {periodWord}
                </small>
              </p>
            ) : (
              <span className={styles.soon}>Not on sale yet</span>
            )}
          </div>
          <ul className={styles.facts}>
            {plan.includedMinutes !== null ? (
              <li>
                {count(plan.includedMinutes)} analysis minutes{perSeat} every
                month
              </li>
            ) : null}
            {plan.longestCallMinutes !== null ? (
              <li>Calls up to {plan.longestCallMinutes} minutes long</li>
            ) : null}
            {plan.rolloverMonths !== null ? (
              <li>
                {plan.rolloverMonths === 0
                  ? "Unused minutes do not carry over"
                  : `Unused minutes carry over for ${plan.rolloverMonths} month${plan.rolloverMonths === 1 ? "" : "s"}`}
              </li>
            ) : null}
            {packs.map((pack) => (
              <li key={pack.key}>
                Top up any time: {count(pack.minutes)} minutes for{" "}
                {money(pack.pricePaise ?? 0)}
              </li>
            ))}
            {plan.retentionDays !== null ? (
              <li>
                Recordings and reports kept for{" "}
                {Math.round(plan.retentionDays / 30)} months
              </li>
            ) : null}
            {scope === "organisation" ? (
              <>
                <li>One shared pool of minutes for the whole team</li>
                <li>Only the organisation owner can buy or cancel</li>
              </>
            ) : null}
            {!buyable && plan.includedMinutes === null ? (
              <li>
                Limits and prices are being set. You will see them here first.
              </li>
            ) : null}
          </ul>
          {scope === "organisation" ? (
            <div className={styles.seats}>
              <b id="seat-label">Seats</b>
              <span
                className={styles.stepper}
                role="group"
                aria-labelledby="seat-label"
              >
                <button
                  type="button"
                  aria-label="Remove a seat"
                  disabled={seatMin === null || seatCount <= seatMin}
                  onClick={() =>
                    setSeats(Math.max(seatMin ?? 1, seatCount - 1))
                  }
                >
                  <Minus size={16} aria-hidden="true" />
                </button>
                <output aria-live="polite">
                  {seatMin === null ? "–" : seatCount}
                </output>
                <button
                  type="button"
                  aria-label="Add a seat"
                  disabled={seatMax === null || seatCount >= seatMax}
                  onClick={() =>
                    setSeats(Math.min(seatMax ?? seatCount, seatCount + 1))
                  }
                >
                  <Plus size={16} aria-hidden="true" />
                </button>
              </span>
              <span className={styles.hint}>
                {seatMin !== null && seatMax !== null
                  ? `${includedMinutes !== null ? `${count(includedMinutes)} pooled minutes a month · ` : ""}${seatMin} to ${seatMax} seats`
                  : "Seat limits are set when the plan goes on sale"}
              </span>
            </div>
          ) : null}
        </div>
      ) : (
        <p className={styles.note}>This plan is not listed yet.</p>
      )}
      <div className={styles.enterprise}>
        <span>
          <Building2 size={16} aria-hidden="true" />
          <span>
            <b>{enterprisePlan?.name ?? "Enterprise"}</b> ·{" "}
            {enterprisePlan?.audience ?? "For large sales companies"}: single
            sign-on, invoices on your terms, a named contact
          </span>
        </span>
        <button
          type="button"
          className={styles.ghost}
          onClick={() => setEnterprise(true)}
        >
          Talk to us
        </button>
      </div>
    </>
  );

  const summary = (
    <>
      <h2>Summary</h2>
      {plan && buyable && unit !== null && total !== null ? (
        <>
          <dl className={styles.rows}>
            <div>
              <dt>Plan</dt>
              <dd>
                {plan.name}, {interval === "month" ? "monthly" : "yearly"}
              </dd>
            </div>
            {scope === "organisation" ? (
              <div>
                <dt>Seats</dt>
                <dd>
                  {seatCount} × {money(unit)}
                </dd>
              </div>
            ) : null}
            {includedMinutes !== null ? (
              <div>
                <dt>Minutes</dt>
                <dd>{count(includedMinutes)} a month</dd>
              </div>
            ) : null}
            <div>
              <dt>GST</dt>
              <dd>Included</dd>
            </div>
            <div className={styles.total}>
              <dt>Pay today</dt>
              <dd>{money(total)}</dd>
            </div>
          </dl>
          {total > APPROVAL_LIMIT_PAISE ? (
            <p className={`${styles.note} ${styles.warn}`}>
              Renews every {periodWord}. This amount is above{" "}
              {money(APPROVAL_LIMIT_PAISE)}, so your bank will ask you to
              approve each renewal.
            </p>
          ) : (
            <p className={styles.note}>
              Renews every {periodWord} on the same date. We remind you before
              each renewal.
            </p>
          )}
          <button
            type="button"
            className={styles.pay}
            disabled={busy !== null}
            onClick={() => void pay()}
            data-pay
          >
            {busy === "checkout"
              ? "Opening the payment page…"
              : authenticated
                ? `Pay ${money(total)}`
                : "Sign in to pay"}
          </button>
          <p className={styles.hint}>
            <ShieldCheck size={13} aria-hidden="true" /> You pay by UPI, card or
            net banking on the payment partner&apos;s secure page. We never see
            your card. Refund within 7 days if you have not used any minutes.
          </p>
        </>
      ) : (
        <>
          <span className={styles.soon}>Not on sale yet</span>
          <p className={styles.hint}>
            {authenticated
              ? "You will see prices here first. Your trial keeps working meanwhile."
              : "Sign in to keep your trial and be first to see prices."}
          </p>
          {offlinePay ? (
            <OfflinePay offline={offlinePay} amount={null} />
          ) : null}
          {!authenticated ? (
            <Link className={styles.primary} href="/login">
              Sign in
            </Link>
          ) : null}
        </>
      )}
    </>
  );

  const active = current ? (
    <>
      <div className={styles.planHead}>
        <div>
          <h2>{current.planName} subscription</h2>
          <p className={styles.hint}>
            {current.account === "organisation"
              ? `${current.seats} subscription seats`
              : "Subscription details"}
            {current.mode === "test" ? " · TEST" : ""}
          </p>
        </div>
        <span className={styles.ok} data-status={current.status}>
          {current.status === "active" && current.cancelAtPeriodEnd
            ? `Ends ${day(current.currentPeriod?.end ?? current.renewsAt)}`
            : current.status === "active"
              ? "Active"
              : current.status === "past_due"
                ? "Payment due"
                : current.status === "pending_authorisation"
                  ? "Waiting for your bank"
                  : "Paused"}
        </span>
      </div>
      <div className={styles.activeGrid}>
        <Ring allowance={mePlan?.allowance ?? null} />
        <dl className={styles.rows}>
          <div>
            <dt>Current plan</dt>
            <dd>{mePlan?.plan.name ?? "—"}</dd>
          </div>
          <div>
            <dt>Current allowance</dt>
            <dd>
              {mePlan && !mePlan.allowance.unlimited
                ? `${count(minutes(mePlan.allowance.allowanceSeconds))} minutes`
                : "—"}
            </dd>
          </div>
          {mePlan ? (
            <div>
              <dt>Longest call</dt>
              <dd>{count(minutes(mePlan.longestCallSeconds))} minutes</dd>
            </div>
          ) : null}
          <div>
            <dt>
              {current.cancelAtPeriodEnd
                ? "Plan ends"
                : current.renewalNeedsCustomerApproval
                  ? "Next renewal (needs your approval)"
                  : "Next renewal"}
            </dt>
            <dd>
              {day(
                current.cancelAtPeriodEnd
                  ? (current.currentPeriod?.end ?? current.renewsAt)
                  : current.renewsAt,
              ) || "—"}
              {current.cancelAtPeriodEnd
                ? ""
                : ` · ${formatMoney(current.amount)}`}
            </dd>
          </div>
        </dl>
      </div>
      <div className={styles.actions}>
        <Link className={styles.primary} href="/new-analysis">
          Analyse a call
        </Link>
        {plan
          ? packs.map((pack) => (
              <button
                key={pack.key}
                type="button"
                className={styles.ghost}
                disabled={busy !== null}
                onClick={() => void topUp(pack.key)}
              >
                Top up {count(pack.minutes)} minutes ·{" "}
                {money(pack.pricePaise ?? 0)}
              </button>
            ))
          : null}
      </div>
    </>
  ) : null;

  const manage = current ? (
    <>
      <h2>Manage</h2>
      {current.cancelAtPeriodEnd ? (
        <p className={styles.note}>
          Renewal is off for this subscription. The recorded period ends{" "}
          {day(current.currentPeriod?.end ?? current.renewsAt)}. Check your
          current plan and available minutes above before analysing a call.
        </p>
      ) : cancelAsk ? (
        <div
          className={styles.confirm}
          role="group"
          aria-label="Confirm cancel"
        >
          <p>
            Stop the next renewal for this subscription? The recorded period
            ends {day(current.currentPeriod?.end ?? current.renewsAt)}.
          </p>
          <div className={styles.actions}>
            <button
              type="button"
              className={styles.danger}
              disabled={busy !== null}
              onClick={() => void cancel()}
            >
              {busy === "cancel" ? "Stopping…" : "Yes, stop renewal"}
            </button>
            <button
              type="button"
              className={styles.ghost}
              onClick={() => setCancelAsk(false)}
            >
              Keep it
            </button>
          </div>
        </div>
      ) : (
        <>
          <p className={styles.hint}>
            Cancel stops the next renewal for this subscription. The recorded
            period ends {day(current.currentPeriod?.end ?? current.renewsAt)}.
          </p>
          <button
            type="button"
            className={styles.ghost}
            onClick={() => setCancelAsk(true)}
          >
            Cancel renewal
          </button>
        </>
      )}
      <p className={styles.hint}>
        Paid recently and not used any minutes? You can ask for a refund for 7
        days from the order page.
      </p>
    </>
  ) : null;

  return (
    <AcquisitionShell
      authenticated={authenticated}
      showPolicyLinks
      homeHref="/"
      active="account"
      mobileFit={false}
    >
      <div className={styles.page} data-plans-view data-stage={stage}>
        <header className={styles.top}>
          <div className={styles.brand}>
            <Sparkles size={18} aria-hidden="true" />
            <h1>{current ? "Your subscription" : "Plans"}</h1>
          </div>
          <Steps current={stage} />
        </header>
        <div className={styles.frame}>
          <section className={styles.panel} aria-live="polite">
            {current ? active : chooser}
          </section>
          <aside className={styles.panel} aria-live="polite">
            {current ? manage : summary}
          </aside>
        </div>
        <section className={styles.rules} aria-label="How buying works">
          <ul>
            <li>
              Nothing is granted when the browser returns from the payment page.
              Minutes appear only after the payment is confirmed to our server.
            </li>
            <li>
              Cancel stops the next renewal. The plan stays active until the
              paid period ends.
            </li>
            <li>
              Organisation: only the owner can buy or cancel. Minutes are
              pooled. When the pool runs out, uploads stop until the next
              payment or a top-up.
            </li>
          </ul>
        </section>
      </div>
      {enterprise ? (
        <EnterpriseSheet onClose={() => setEnterprise(false)} />
      ) : null}
    </AcquisitionShell>
  );
}

function Ring({ allowance }: { allowance: Allowance | null }) {
  const circumference = 2 * Math.PI * 52;
  const share =
    allowance && !allowance.unlimited && allowance.allowanceSeconds > 0
      ? Math.min(1, allowance.availableSeconds / allowance.allowanceSeconds)
      : allowance?.unlimited
        ? 1
        : 0;
  return (
    <div
      className={styles.ring}
      role="img"
      aria-label={
        allowance
          ? allowance.unlimited
            ? "Unlimited minutes"
            : `${count(minutes(allowance.availableSeconds))} minutes left`
          : "Minutes"
      }
    >
      <svg viewBox="0 0 120 120" aria-hidden="true">
        <circle className={styles.ringTrack} cx="60" cy="60" r="52" />
        <circle
          className={styles.ringValue}
          cx="60"
          cy="60"
          r="52"
          strokeDasharray={circumference.toFixed(1)}
          strokeDashoffset={(circumference * (1 - share)).toFixed(1)}
        />
      </svg>
      <div>
        <b>
          {allowance
            ? allowance.unlimited
              ? "∞"
              : count(minutes(allowance.availableSeconds))
            : "—"}
        </b>
        <span>minutes left</span>
      </div>
    </div>
  );
}
