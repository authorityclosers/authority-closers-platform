"use client";

import { useState } from "react";
import { Lock, Save } from "lucide-react";
import { z } from "zod";
import { newIdempotencyKey } from "@ac/operations-web/api";
import { Badge, Button, Field, Panel, kitStyles } from "../ui/kit";
import styles from "./execution-controls.module.css";

/**
 * The AI budget's ceiling and period in Admin (owner decision, 19 Oct 2026: "add those
 * as nice UI/UX settings in admin … all settings doable from admin"). Only the owner
 * changes them, after a confirm step that shows old and new; every change is audited.
 */

const amount = z.number().int().nonnegative();
const period = z.enum(["lifetime", "monthly", "daily"]);
export type Period = z.infer<typeof period>;
export const budgetSettings = z
  .object({
    revision: amount,
    ceiling_paise: amount,
    sealed_ceiling_paise: amount,
    from_release: z.boolean(),
    period,
    cap_paise: amount,
    lifetime_committed_paise: amount.nullable(),
    period_starts_at: z.string().nullable(),
    period_ends_at: z.string().nullable(),
    can_change_ceiling: z.boolean(),
    periods: z
      .array(z.object({ value: period, help: z.string() }).strict())
      .max(3),
    history: z
      .array(
        z
          .object({
            revision: amount,
            ceiling_paise: amount,
            period,
            cap_paise: amount.nullable(),
            reason: z.string(),
            changed_at: z.string(),
          })
          .strict(),
      )
      .max(10),
  })
  .strict();
export type BudgetSettings = z.infer<typeof budgetSettings>;

export const PERIOD_LABEL: Record<Period, string> = {
  lifetime: "Lifetime",
  monthly: "Monthly",
  daily: "Daily",
};
/** "this month", "today" or nothing: what the cap and the spend refer to. */
export const PERIOD_NOW: Record<Period, string> = {
  lifetime: "",
  monthly: " this month",
  daily: " today",
};
const PER: Record<Period, string> = {
  lifetime: "in total",
  monthly: "a month",
  daily: "a day",
};
const CAP_LABEL: Record<Period, string> = {
  lifetime: "Budget cap (INR)",
  monthly: "Cap per month (INR)",
  daily: "Cap per day (INR)",
};

export const rupees = (paise: number) =>
  new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(paise / 100);

const day = (iso: string) =>
  new Date(iso).toLocaleDateString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "numeric",
    month: "short",
  });

/** Whole rupees only (no paise) for the owner's settings. */
function parseRupees(value: string) {
  const trimmed = value.trim().replaceAll(",", "");
  if (!/^\d{1,8}$/.test(trimmed)) return null;
  return Number(trimmed) * 100;
}

function capText(settings: { period: Period; cap_paise: number | null }) {
  return settings.cap_paise == null
    ? "the budget cap"
    : `${rupees(settings.cap_paise)} ${PER[settings.period]}`;
}

export function resetsText(settings: BudgetSettings) {
  return settings.period !== "lifetime" && settings.period_ends_at
    ? `starts fresh ${settings.period === "daily" ? "at midnight" : `on ${day(settings.period_ends_at)}`}`
    : "";
}

export function BudgetSettingsPanel({
  settings,
  onSaved,
}: {
  settings: BudgetSettings;
  onSaved: () => Promise<void>;
}) {
  const [ceiling, setCeiling] = useState(String(settings.ceiling_paise / 100));
  const [chosen, setChosen] = useState<Period>(settings.period);
  const [cap, setCap] = useState(String(settings.cap_paise / 100));
  const [reason, setReason] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [key, setKey] = useState(() => newIdempotencyKey());

  const ceilingPaise = parseRupees(ceiling);
  const capPaise = parseRupees(cap);
  const spent = settings.lifetime_committed_paise ?? 0;
  const help = settings.periods.find((item) => item.value === chosen)?.help;
  const problem =
    ceilingPaise == null
      ? "Enter the ceiling in whole rupees."
      : capPaise == null
        ? "Enter the cap in whole rupees."
        : capPaise > ceilingPaise
          ? "The cap can't be above the ceiling."
          : chosen === "lifetime" && capPaise < spent
            ? `${rupees(spent)} is already spent or held in total. Set at least that, or choose monthly or daily.`
            : !reason.trim()
              ? "Add a short reason; it goes in the audit trail."
              : null;
  const unchanged =
    ceilingPaise === settings.ceiling_paise &&
    chosen === settings.period &&
    capPaise === settings.cap_paise;

  function edit<T>(setter: (value: T) => void) {
    return (value: T) => {
      setter(value);
      setConfirming(false);
      setMessage(null);
      setError(null);
    };
  }

  async function save() {
    if (
      problem ||
      unchanged ||
      busy ||
      ceilingPaise == null ||
      capPaise == null
    )
      return;
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/v1/admin/conversation/budget/settings", {
        method: "POST",
        cache: "no-store",
        credentials: "same-origin",
        redirect: "error",
        headers: {
          accept: "application/json",
          "content-type": "application/json",
          "Idempotency-Key": key,
        },
        body: JSON.stringify({
          expected_setting_revision: settings.revision,
          ceiling_paise: ceilingPaise,
          period: chosen,
          cap_paise: capPaise,
          reason: reason.trim(),
        }),
      });
      if (!response.ok) {
        const detail = await response
          .json()
          .then((body: { detail?: unknown }) =>
            typeof body?.detail === "string" ? body.detail : null,
          )
          .catch(() => null);
        throw new Error(
          response.status === 403
            ? "Only the owner can change the ceiling and the period."
            : response.status === 409
              ? (detail ??
                "The budget settings changed. Refresh before trying again.")
              : (detail ??
                "The change could not be confirmed. Refresh to check."),
        );
      }
      setConfirming(false);
      setReason("");
      setKey(newIdempotencyKey());
      setMessage(
        `Saved. Ceiling ${rupees(ceilingPaise)}, ${PERIOD_LABEL[chosen].toLowerCase()} cap ${capText({ period: chosen, cap_paise: capPaise })}. Waiting calls continue within a minute.`,
      );
      await onSaved();
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "The change could not be confirmed. Refresh to check.",
      );
    } finally {
      setBusy(false);
    }
  }

  const owner = settings.can_change_ceiling;
  return (
    <Panel
      title="Budget settings"
      sub={
        settings.from_release
          ? "from the release approval"
          : `revision ${settings.revision}`
      }
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
      <div className={styles.body}>
        <p>
          Ceiling <strong>{rupees(settings.ceiling_paise)}</strong> ·{" "}
          {PERIOD_LABEL[settings.period]}: cap{" "}
          <strong>{capText(settings)}</strong>
          {resetsText(settings) ? ` · ${resetsText(settings)}` : ""}
        </p>
        <p className={kitStyles.muted}>
          The ceiling is the most the cap can ever be. Admins raise the cap up
          to it in one click; only the owner moves the ceiling or the period.
          {settings.from_release
            ? ` Until the owner saves a setting, the release approval's ${rupees(settings.sealed_ceiling_paise)} is the ceiling.`
            : ""}
        </p>
        {owner ? (
          <div className={styles.budgetEditor}>
            <Field label="Ceiling (INR)" hint="The most the cap can be.">
              <input
                aria-label="Budget ceiling in INR"
                type="text"
                inputMode="numeric"
                value={ceiling}
                onChange={(event) => edit(setCeiling)(event.target.value)}
                disabled={busy}
              />
            </Field>
            <div className={styles.periodField}>
              <span className={styles.periodLabel}>Period</span>
              <span
                className={styles.segments}
                role="radiogroup"
                aria-label="Budget period"
              >
                {settings.periods.map((item) => (
                  <button
                    key={item.value}
                    type="button"
                    role="radio"
                    aria-checked={chosen === item.value}
                    className={styles.segment}
                    onClick={() => edit(setChosen)(item.value)}
                    disabled={busy}
                  >
                    {PERIOD_LABEL[item.value]}
                  </button>
                ))}
              </span>
              {help ? <small className={styles.hint}>{help}</small> : null}
            </div>
            <Field
              label={CAP_LABEL[chosen]}
              hint={
                chosen === "lifetime"
                  ? `At least ${rupees(spent)}, already spent or held.`
                  : "Money still held for a running call counts until it settles."
              }
            >
              <input
                aria-label={CAP_LABEL[chosen]}
                type="text"
                inputMode="numeric"
                value={cap}
                onChange={(event) => edit(setCap)(event.target.value)}
                disabled={busy}
              />
            </Field>
            <Field label="Reason (audited)">
              <input
                aria-label="Reason for the budget settings change"
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
                aria-label="Confirm the budget settings change"
              >
                <p>
                  <strong>Change from now:</strong>
                </p>
                <ul>
                  <li>
                    Ceiling {rupees(settings.ceiling_paise)} →{" "}
                    <strong>{rupees(ceilingPaise ?? 0)}</strong>
                  </li>
                  <li>
                    Period {PERIOD_LABEL[settings.period]} →{" "}
                    <strong>{PERIOD_LABEL[chosen]}</strong>
                  </li>
                  <li>
                    Cap {capText(settings)} →{" "}
                    <strong>
                      {capText({ period: chosen, cap_paise: capPaise })}
                    </strong>
                  </li>
                </ul>
                <span className={styles.budgetActions}>
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
              <span className={styles.budgetActions}>
                <Button
                  variant="primary"
                  onClick={() => setConfirming(true)}
                  disabled={busy || !!problem || unchanged}
                  title={problem ?? (unchanged ? "Nothing changed yet" : "")}
                >
                  Review change
                </Button>
              </span>
            )}
            {problem && !unchanged ? (
              <small className={styles.hint}>{problem}</small>
            ) : null}
          </div>
        ) : (
          <p className={kitStyles.muted}>
            <Lock size={13} aria-hidden /> Only the owner changes the ceiling
            and the period.
          </p>
        )}
        {error ? (
          <small role="alert" className={kitStyles.fieldError}>
            {error}
          </small>
        ) : null}
        {message ? <p role="status">{message}</p> : null}
        {settings.history.length ? (
          <details className={styles.history}>
            <summary>Settings history</summary>
            <ol>
              {settings.history.map((item) => (
                <li key={item.revision}>
                  {new Date(item.changed_at).toLocaleString("en-IN", {
                    timeZone: "Asia/Kolkata",
                  })}{" "}
                  · ceiling {rupees(item.ceiling_paise)} ·{" "}
                  {PERIOD_LABEL[item.period].toLowerCase()} cap {capText(item)}{" "}
                  · {item.reason}
                </li>
              ))}
            </ol>
          </details>
        ) : null}
      </div>
    </Panel>
  );
}
