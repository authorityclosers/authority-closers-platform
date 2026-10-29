"use client";

/**
 * Plan prices in Admin (owner, 29 Oct 2026: "Admin price editor"). Each environment keeps
 * its own prices: this panel shows and sets this Admin's environment. Only the owner
 * changes a price, after a confirm step that shows old and new
 * (PUT /v1/admin/plan-prices/{key}); each change is a new plan revision, kept in an
 * append-only history and audited. Checkout uses the new price at once; orders already
 * placed keep theirs. Admin only.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Lock, Save } from "lucide-react";

import { send } from "../lib/client-api";
import { Badge, Button, Field, Panel, Table, kitStyles } from "../ui/kit";
import type { PlanPrices, PlanRow } from "./plan-prices-data";
import styles from "./plan-prices.module.css";

const ENVIRONMENT: Record<string, string> = {
  production: "Production",
  staging: "Staging",
  development: "Dev",
};
const STATUS: Record<PlanRow["status"], string> = {
  active: "On sale",
  coming_soon: "Coming soon",
  draft: "Draft",
  retired: "Retired",
};

export const rupees = (value: number | null) =>
  value == null
    ? "Not set"
    : new Intl.NumberFormat("en-IN", {
        style: "currency",
        currency: "INR",
        maximumFractionDigits: 0,
      }).format(value / 100);

/** Whole rupees only (no paise), as the budget settings take them. */
function parseRupees(value: string) {
  const trimmed = value.trim().replaceAll(",", "");
  if (!/^\d{1,7}$/.test(trimmed) || Number(trimmed) === 0) return null;
  return Number(trimmed) * 100;
}

const unit = (row: { per_seat: boolean; prices_include_gst: boolean }) =>
  `${row.per_seat ? " per seat" : ""}${row.prices_include_gst ? ", GST included" : " + GST"}`;

function PriceEditor({ row, onDone }: { row: PlanRow; onDone: () => void }) {
  const router = useRouter();
  const [monthly, setMonthly] = useState(
    row.monthly_price_paise == null
      ? ""
      : String(row.monthly_price_paise / 100),
  );
  const [yearly, setYearly] = useState(
    row.yearly_price_paise == null ? "" : String(row.yearly_price_paise / 100),
  );
  const [reason, setReason] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const monthlyPaise = parseRupees(monthly);
  const yearlyPaise = parseRupees(yearly);
  const unchanged =
    monthlyPaise === row.monthly_price_paise &&
    yearlyPaise === row.yearly_price_paise;
  const problem =
    monthlyPaise == null
      ? "Enter the price a month in whole rupees."
      : yearlyPaise == null
        ? "Enter the price a year in whole rupees."
        : !reason.trim()
          ? "Add a short reason; it goes in the audit trail."
          : null;

  function edit(setter: (value: string) => void) {
    return (value: string) => {
      setter(value);
      setConfirming(false);
      setError(null);
    };
  }

  async function save() {
    if (problem || unchanged || busy) return;
    setBusy(true);
    setError(null);
    const result = await send(
      "PUT",
      `/v1/admin/plan-prices/${encodeURIComponent(row.key)}`,
      {
        expected_revision: row.revision,
        monthly_price_paise: monthlyPaise,
        yearly_price_paise: yearlyPaise,
        reason: reason.trim(),
      },
      null,
    );
    setBusy(false);
    if (!result.ok) {
      setError(
        result.status === 403
          ? "Only the owner can change plan prices."
          : result.status === 409
            ? "This plan changed. Refresh before trying again."
            : result.message,
      );
      return;
    }
    onDone();
    router.refresh();
  }

  return (
    <div className={styles.editor}>
      <Field label={`₹ a month${row.per_seat ? " per seat" : ""}`}>
        <input
          aria-label={`${row.name} price a month in INR`}
          type="text"
          inputMode="numeric"
          value={monthly}
          onChange={(event) => edit(setMonthly)(event.target.value)}
          disabled={busy}
        />
      </Field>
      <Field label={`₹ a year${row.per_seat ? " per seat" : ""}`}>
        <input
          aria-label={`${row.name} price a year in INR`}
          type="text"
          inputMode="numeric"
          value={yearly}
          onChange={(event) => edit(setYearly)(event.target.value)}
          disabled={busy}
        />
      </Field>
      <Field label="Reason (audited)" wide>
        <input
          aria-label={`Reason for the ${row.name} price change`}
          type="text"
          maxLength={300}
          value={reason}
          onChange={(event) => edit(setReason)(event.target.value)}
          disabled={busy}
        />
      </Field>
      {confirming && !problem && !unchanged ? (
        <div
          className={styles.confirm}
          role="group"
          aria-label={`Confirm the ${row.name} price change`}
        >
          <p>
            <strong>{row.name}, from now on:</strong>
          </p>
          <ul>
            <li>
              A month {rupees(row.monthly_price_paise)} →{" "}
              <strong>{rupees(monthlyPaise)}</strong>
              {unit(row)}
            </li>
            <li>
              A year {rupees(row.yearly_price_paise)} →{" "}
              <strong>{rupees(yearlyPaise)}</strong>
              {unit(row)}
            </li>
          </ul>
          <p className={kitStyles.muted}>
            Checkout uses the new price at once. Orders already placed keep
            theirs.
          </p>
          <span className={styles.actions}>
            <Button
              variant="primary"
              onClick={() => void save()}
              disabled={busy}
            >
              <Save size={15} aria-hidden />
              {busy ? "Saving…" : "Confirm change"}
            </Button>
            <Button
              variant="ghost"
              onClick={() => setConfirming(false)}
              disabled={busy}
            >
              Cancel
            </Button>
          </span>
        </div>
      ) : (
        <span className={styles.actions}>
          <Button
            variant="primary"
            onClick={() => setConfirming(true)}
            disabled={busy || !!problem || unchanged}
            title={problem ?? (unchanged ? "Nothing changed yet" : "")}
          >
            Review change
          </Button>
          <Button variant="ghost" onClick={onDone} disabled={busy}>
            Close
          </Button>
        </span>
      )}
      {problem && !unchanged ? (
        <small className={kitStyles.muted}>{problem}</small>
      ) : null}
      {error ? (
        <small role="alert" className={kitStyles.fieldError}>
          {error}
        </small>
      ) : null}
    </div>
  );
}

export function PlanPricesPanel({ prices }: { prices: PlanPrices }) {
  const [editing, setEditing] = useState<string | null>(null);
  const owner = prices.can_change;
  const where = ENVIRONMENT[prices.environment] ?? prices.environment;
  const names = new Map(prices.plans.map((row) => [row.key, row.name]));
  return (
    <Panel
      title="Plan prices"
      sub={`What ${where} sells at now · each environment keeps its own prices`}
      tools={
        owner ? (
          <Badge tone="good">Owner</Badge>
        ) : (
          <Badge>
            <Lock size={12} aria-hidden /> Owner only
          </Badge>
        )
      }
    >
      {prices.plans.length ? (
        <Table label="Plan prices">
          <thead>
            <tr>
              <th scope="col">Plan</th>
              <th scope="col" data-num="">
                A month
              </th>
              <th scope="col" data-num="">
                A year
              </th>
              <th scope="col">Status</th>
              <th scope="col" data-num="">
                Revision
              </th>
              {owner ? <th scope="col" aria-label="Change" /> : null}
            </tr>
          </thead>
          <tbody>
            {prices.plans.map((row) => (
              <tr key={row.key}>
                <th scope="row">
                  <strong>{row.name}</strong>
                  <small className={kitStyles.muted}>{unit(row)}</small>
                </th>
                <td data-num="">{rupees(row.monthly_price_paise)}</td>
                <td data-num="">{rupees(row.yearly_price_paise)}</td>
                <td>{STATUS[row.status]}</td>
                <td data-num="">{row.revision}</td>
                {owner ? (
                  <td>
                    {row.editable && editing !== row.key ? (
                      <Button
                        variant="ghost"
                        onClick={() => setEditing(row.key)}
                      >
                        Change price
                      </Button>
                    ) : null}
                  </td>
                ) : null}
              </tr>
            ))}
          </tbody>
        </Table>
      ) : (
        <p className={kitStyles.muted}>No plans in this environment yet.</p>
      )}
      {owner && editing ? (
        <PriceEditor
          key={editing}
          row={prices.plans.find((row) => row.key === editing)!}
          onDone={() => setEditing(null)}
        />
      ) : null}
      {!owner ? (
        <p className={`${kitStyles.muted} ${styles.note}`}>
          <Lock size={13} aria-hidden /> Only the owner changes plan prices.
        </p>
      ) : null}
      {prices.history.length ? (
        <details className={styles.history}>
          <summary>Price history</summary>
          <ol>
            {prices.history.map((item) => (
              <li key={`${item.plan_key}-${item.plan_revision}`}>
                {new Date(item.changed_at).toLocaleString("en-IN", {
                  timeZone: "Asia/Kolkata",
                })}{" "}
                · {names.get(item.plan_key) ?? item.plan_key} revision{" "}
                {item.plan_revision}: a month{" "}
                {rupees(item.previous_monthly_price_paise)} →{" "}
                {rupees(item.monthly_price_paise)}, a year{" "}
                {rupees(item.previous_yearly_price_paise)} →{" "}
                {rupees(item.yearly_price_paise)} · {item.reason}
                {item.changed_by ? ` · ${item.changed_by}` : ""}
              </li>
            ))}
          </ol>
        </details>
      ) : null}
    </Panel>
  );
}
