"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { CreditCard, RefreshCw } from "lucide-react";
import {
  BillingReadError,
  loadStaffBilling,
  requestRefund,
  type BillingPayment,
  type StaffBilling,
} from "./billing-api";
import styles from "./billing-panel.module.css";

type Customer = StaffBilling["orders"][number]["customer"];

const dateTime = new Intl.DateTimeFormat("en-IN", {
  dateStyle: "medium",
  timeStyle: "short",
});
const date = new Intl.DateTimeFormat("en-IN", { dateStyle: "medium" });

function money(minor: number | null, currency: string | null) {
  if (minor === null || currency === null) return "—";
  return new Intl.NumberFormat("en-IN", { style: "currency", currency }).format(
    minor / 100,
  );
}

function gst(inclusive: boolean | null) {
  return inclusive === null ? "" : inclusive ? "incl. GST" : "excl. GST";
}

function label(value: string) {
  const text = value.replaceAll("_", " ").replace(".", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function CustomerCell({ customer }: { customer: Customer | null }) {
  if (!customer) return <>Unknown account</>;
  return (
    <>
      <strong>{customer.name ?? customer.email ?? "Unnamed account"}</strong>
      <small>
        {customer.kind === "organisation" ? "Organisation" : "Personal"}
        {customer.name && customer.email ? " · " + customer.email : ""}
      </small>
    </>
  );
}

function Table({
  id,
  title,
  empty,
  headings,
  children,
  count,
}: {
  id: string;
  title: string;
  empty: string;
  headings: string[];
  children: ReactNode;
  count: number;
}) {
  return (
    <section className={styles.block} aria-labelledby={id}>
      <h3 id={id}>{title}</h3>
      {count === 0 ? (
        <p className={styles.empty}>{empty}</p>
      ) : (
        <div className={styles.scroll}>
          <table className={styles.table}>
            <thead>
              <tr>
                {headings.map((heading) => (
                  <th key={heading} scope="col">
                    {heading}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>{children}</tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function RefundCell({
  payment,
  onDone,
}: {
  payment: BillingPayment;
  onDone: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [refused, setRefused] = useState("");
  const key = useRef("");
  const until = payment.refundable_until
    ? " until " + date.format(new Date(payment.refundable_until))
    : "";

  if (payment.refund_state === null) return <>—</>;
  if (message) return <span role="status">{message}</span>;
  if (payment.refund_state !== "available")
    return (
      <span className={styles.badge}>
        {payment.refund_state === "unavailable"
          ? "Window closed"
          : label(payment.refund_state)}
      </span>
    );
  if (!open)
    return (
      <button
        type="button"
        onClick={() => {
          key.current = crypto.randomUUID();
          setOpen(true);
        }}
      >
        Refund
      </button>
    );

  async function submit() {
    if (busy || !reason.trim()) return;
    setBusy(true);
    setRefused("");
    const outcome = await requestRefund(
      payment.payment_id,
      reason.trim(),
      key.current,
      AbortSignal.timeout(25000),
    );
    setBusy(false);
    if (!outcome.ok) {
      setRefused(outcome.reason);
      return;
    }
    setMessage(
      outcome.state === "refunded"
        ? "Refunded."
        : outcome.state === "pending"
          ? "Refund sent to the provider."
          : "Refund " + label(outcome.state).toLowerCase() + ".",
    );
    onDone();
  }

  return (
    <form
      className={styles.refund}
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <label>
        Refund reason
        <textarea
          value={reason}
          maxLength={500}
          required
          onChange={(event) => setReason(event.target.value)}
        />
      </label>
      <small>
        Full refund{until}, only if none of this payment’s minutes were used.
        The server decides.
      </small>
      {refused && (
        <p className={styles.refused} role="alert">
          {refused}
        </p>
      )}
      <div>
        <button type="submit" disabled={busy || !reason.trim()}>
          {busy ? "Requesting…" : "Request refund"}
        </button>
        <button type="button" disabled={busy} onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
    </form>
  );
}

export function BillingPanel() {
  const [data, setData] = useState<StaffBilling | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(true);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    loadStaffBilling(controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        setData(result);
        setError("");
      })
      .catch((failure: unknown) => {
        if (controller.signal.aborted) return;
        setData(null);
        setError(
          failure instanceof BillingReadError && failure.kind === "denied"
            ? "Your billing assignment could not be confirmed. Reload to check your account."
            : "Billing could not be loaded. Check your connection and try again.",
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) setPending(false);
      });
    return () => controller.abort();
  }, [retry]);

  const reload = () => {
    setPending(true);
    setError("");
    setRetry((value) => value + 1);
  };

  return (
    <section className={styles.panel} aria-labelledby="billing-heading">
      <div className={styles.heading}>
        <CreditCard size={22} aria-hidden="true" />
        <h2 id="billing-heading">Billing</h2>
        <button
          type="button"
          onClick={reload}
          disabled={pending}
          aria-label="Reload billing"
        >
          <RefreshCw size={17} aria-hidden="true" />
          Refresh
        </button>
      </div>
      {pending && <p role="status">Loading billing…</p>}
      {error && (
        <div className={styles.error} role="alert">
          {error}
        </div>
      )}
      {data && (
        <>
          <p className={styles.note}>
            Newest {data.page_limit} of each, as of{" "}
            {dateTime.format(new Date(data.generated_at))}.
          </p>
          <Table
            id="billing-orders"
            title="Orders"
            empty="No orders yet."
            count={data.orders.length}
            headings={[
              "Customer",
              "Plan",
              "Seats",
              "Amount",
              "Status",
              "Provider reference",
              "Date",
            ]}
          >
            {data.orders.map((order) => (
              <tr key={order.order_id}>
                <td>
                  <CustomerCell customer={order.customer} />
                </td>
                <td>
                  {order.plan_name}
                  <small>
                    {order.kind === "top_up"
                      ? "Minute pack"
                      : order.interval === "year"
                        ? "Yearly"
                        : "Monthly"}
                    {order.mode === "test" ? " · Test" : ""}
                  </small>
                </td>
                <td>{order.seats}</td>
                <td>
                  {money(order.amount_minor, order.currency)}
                  <small>{gst(order.gst_inclusive)}</small>
                </td>
                <td>
                  <span className={styles.badge}>{label(order.status)}</span>
                </td>
                <td>
                  {order.provider_order_ref ?? order.order_ref}
                  <small>{order.provider}</small>
                </td>
                <td>{dateTime.format(new Date(order.created_at))}</td>
              </tr>
            ))}
          </Table>
          <Table
            id="billing-payments"
            title="Payments"
            empty="No payments yet."
            count={data.payments.length}
            headings={[
              "Customer",
              "Plan",
              "Seats",
              "Amount",
              "Status",
              "Provider reference",
              "Date",
              "Refund",
            ]}
          >
            {data.payments.map((payment) => (
              <tr key={payment.payment_id}>
                <td>
                  <CustomerCell customer={payment.customer} />
                </td>
                <td>{payment.plan_name ?? "—"}</td>
                <td>{payment.seats ?? "—"}</td>
                <td>
                  {money(payment.amount_minor, payment.currency)}
                  <small>{gst(payment.gst_inclusive)}</small>
                </td>
                <td>
                  <span className={styles.badge}>
                    {payment.event === "payment.failed"
                      ? "Failed"
                      : payment.event === "subscription.charged"
                        ? "Renewal charged"
                        : "Captured"}
                  </span>
                </td>
                <td>
                  {payment.payment_id}
                  <small>{payment.provider}</small>
                </td>
                <td>{dateTime.format(new Date(payment.verified_at))}</td>
                <td>
                  <RefundCell payment={payment} onDone={reload} />
                </td>
              </tr>
            ))}
          </Table>
          <Table
            id="billing-refunds"
            title="Refunds"
            empty="No refunds requested."
            count={data.refunds.length}
            headings={[
              "Customer",
              "Payment",
              "Amount",
              "State",
              "Reason",
              "Requested",
              "Updated",
            ]}
          >
            {data.refunds.map((refund) => (
              <tr key={refund.order_id + refund.payment_id}>
                <td>
                  <CustomerCell customer={refund.customer} />
                </td>
                <td>
                  {refund.payment_id}
                  {refund.provider_refund_ref && (
                    <small>{refund.provider_refund_ref}</small>
                  )}
                </td>
                <td>{money(refund.amount_minor, refund.currency)}</td>
                <td>
                  <span className={styles.badge}>
                    {refund.state === "pending"
                      ? "Requested"
                      : refund.state === "refunded"
                        ? "Succeeded"
                        : "Failed"}
                  </span>
                </td>
                <td>{refund.reason}</td>
                <td>{dateTime.format(new Date(refund.requested_at))}</td>
                <td>{dateTime.format(new Date(refund.updated_at))}</td>
              </tr>
            ))}
          </Table>
          <Table
            id="billing-subscriptions"
            title="Subscriptions"
            empty="No subscriptions yet."
            count={data.subscriptions.length}
            headings={[
              "Customer",
              "Plan",
              "Seats",
              "Amount",
              "State",
              "Next renewal",
              "Provider reference",
            ]}
          >
            {data.subscriptions.map((subscription) => (
              <tr key={subscription.subscription_id}>
                <td>
                  <CustomerCell customer={subscription.customer} />
                </td>
                <td>
                  {subscription.plan_name}
                  <small>
                    {subscription.interval === "year" ? "Yearly" : "Monthly"}
                    {subscription.mode === "test" ? " · Test" : ""}
                  </small>
                </td>
                <td>{subscription.seats}</td>
                <td>
                  {money(subscription.amount_minor, subscription.currency)}
                  <small>{gst(subscription.gst_inclusive)}</small>
                </td>
                <td>
                  <span className={styles.badge}>
                    {label(subscription.status)}
                  </span>
                </td>
                <td>
                  {subscription.renews_at
                    ? date.format(new Date(subscription.renews_at))
                    : subscription.cancel_at_period_end &&
                        subscription.current_period_end
                      ? "Cancelled at period end, " +
                        date.format(new Date(subscription.current_period_end))
                      : "—"}
                </td>
                <td>
                  {subscription.provider_subscription_ref ?? "—"}
                  <small>{subscription.provider}</small>
                </td>
              </tr>
            ))}
          </Table>
        </>
      )}
      <section className={styles.block} aria-labelledby="billing-invoices">
        <h3 id="billing-invoices">Invoices</h3>
        <p className={styles.empty}>
          The platform does not issue invoices yet, so there are none to show.
          Amounts above state whether GST is included.
        </p>
      </section>
      <section className={styles.block} aria-labelledby="billing-grants">
        <h3 id="billing-grants">Minute grants</h3>
        <p className={styles.empty}>
          Grant minutes with the audited minute-account tool. It records who
          granted what and why.{" "}
          <a href="/sales-xray/settings">Open minute accounts</a>
        </p>
      </section>
    </section>
  );
}
