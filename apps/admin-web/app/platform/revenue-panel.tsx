"use client";

import { useEffect, useState } from "react";
import { IndianRupee, RefreshCw } from "lucide-react";
import {
  loadRevenue,
  RevenueReadError,
  type Revenue,
  type RevenueMode,
  type RevenueWindow,
} from "./revenue-api";
import styles from "./revenue-panel.module.css";

const WINDOW_LABELS: Record<RevenueWindow["key"], string> = {
  today: "Today",
  last_7_days: "7 days",
  this_month: "This month",
  all_time: "All time",
};

const inr = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});
const number = new Intl.NumberFormat("en-IN");
const dateTime = new Intl.DateTimeFormat("en-IN", {
  dateStyle: "medium",
  timeStyle: "short",
});

function rupees(minor: number) {
  return inr.format(minor / 100);
}

function Tile({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail?: string;
}) {
  return (
    <div className={styles.tile}>
      <span>{label}</span>
      <strong>{value}</strong>
      {detail ? <small>{detail}</small> : null}
    </div>
  );
}

/** What Sales Xray earned: collected, refunded, net, GST and recurring revenue. */
export function RevenuePanel() {
  const [mode, setMode] = useState<RevenueMode>("live");
  const [windowKey, setWindowKey] =
    useState<RevenueWindow["key"]>("this_month");
  const [data, setData] = useState<Revenue | null>(null);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(true);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    loadRevenue(mode, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        setData(result);
        setError("");
      })
      .catch((failure: unknown) => {
        if (controller.signal.aborted) return;
        setData(null);
        setError(
          failure instanceof RevenueReadError && failure.kind === "denied"
            ? "Your billing assignment could not be confirmed. Reload to check your account."
            : "Revenue could not be loaded. Check your connection and try again.",
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) setPending(false);
      });
    return () => controller.abort();
  }, [mode, retry]);

  const choose = (next: RevenueMode) => {
    if (next === mode) return;
    setPending(true);
    setMode(next);
  };
  const current = data?.windows.find((row) => row.key === windowKey) ?? null;

  return (
    <section className={styles.panel} aria-labelledby="revenue-heading">
      <div className={styles.heading}>
        <IndianRupee size={22} aria-hidden="true" />
        <h2 id="revenue-heading">Revenue</h2>
        <div className={styles.segment} role="group" aria-label="Payment mode">
          {(["live", "test"] as const).map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={mode === value}
              onClick={() => choose(value)}
            >
              {value === "live" ? "Live" : "Test"}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={() => {
            setPending(true);
            setRetry((value) => value + 1);
          }}
          disabled={pending}
          aria-label="Reload revenue"
        >
          <RefreshCw size={17} aria-hidden="true" />
        </button>
      </div>
      {mode === "test" ? (
        <p className={styles.note}>
          Test payments only (the test provider and test keys). Never real
          money.
        </p>
      ) : null}
      {pending && !data ? <p role="status">Loading revenue…</p> : null}
      {error ? (
        <div className={styles.error} role="alert">
          {error}
        </div>
      ) : null}
      {data && current ? (
        <>
          <div className={styles.segment} role="group" aria-label="Period">
            {data.windows.map((row) => (
              <button
                key={row.key}
                type="button"
                aria-pressed={row.key === windowKey}
                onClick={() => setWindowKey(row.key)}
              >
                {WINDOW_LABELS[row.key]}
              </button>
            ))}
          </div>
          <div className={styles.tiles}>
            <Tile
              label="Collected"
              value={rupees(current.collected_minor)}
              detail={`${number.format(current.payments)} payments · incl. GST`}
            />
            <Tile
              label="Net after refunds"
              value={rupees(current.net_minor)}
              detail={`${rupees(current.refunded_minor)} refunded · ${number.format(current.refunds)} refunds`}
            />
            <Tile
              label="GST collected"
              value={rupees(current.gst_minor)}
              detail={`${rupees(current.taxable_minor)} before GST`}
            />
            <Tile
              label="Monthly recurring"
              value={rupees(data.monthly_recurring_taxable_minor)}
              detail="Before GST · renewing plans, yearly ÷ 12"
            />
            <Tile
              label="Active subscriptions"
              value={number.format(data.active_subscriptions)}
              detail={`${number.format(data.cancelling_subscriptions)} cancelling at period end`}
            />
            <Tile
              label="Paying customers"
              value={number.format(data.paying_accounts)}
              detail={`${number.format(data.personal_accounts)} personal · ${number.format(data.organisation_accounts)} organisations`}
            />
          </div>
          <div className={styles.columns}>
            <section aria-labelledby="revenue-plans">
              <h3 id="revenue-plans">By plan, all time</h3>
              {data.by_plan.length === 0 ? (
                <p className={styles.note}>No payments yet.</p>
              ) : (
                <ul className={styles.rows}>
                  {data.by_plan.map((row) => (
                    <li key={row.plan_key + row.kind}>
                      <span>
                        {row.plan_name}
                        {row.kind === "top_up" ? " top-ups" : ""}
                        <small>{number.format(row.payments)} payments</small>
                      </span>
                      <strong>{rupees(row.collected_minor)}</strong>
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <section aria-labelledby="revenue-recurring">
              <h3 id="revenue-recurring">Renewing plans</h3>
              {data.recurring.length === 0 ? (
                <p className={styles.note}>No renewing subscriptions.</p>
              ) : (
                <ul className={styles.rows}>
                  {data.recurring.map((row) => (
                    <li key={row.plan_key + row.interval}>
                      <span>
                        {row.plan_name} ·{" "}
                        {row.interval === "year" ? "yearly" : "monthly"}
                        <small>
                          {number.format(row.subscriptions)} subscriptions ·{" "}
                          {number.format(row.seats)} seats
                        </small>
                      </span>
                      <strong>
                        {rupees(row.monthly_taxable_minor)}
                        <small> / month</small>
                      </strong>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
          <p className={styles.note}>
            From issued invoices and credit notes, as of{" "}
            {dateTime.format(new Date(data.generated_at))}. Days and months
            follow India time.
          </p>
        </>
      ) : null}
    </section>
  );
}
