"use client";

import { useId, useRef, useState } from "react";
import {
  CALL_OUTCOME_LABELS,
  parseHumanCallOutcome,
  type CallOutcomeKind,
  type HumanCallOutcome,
} from "./report-call-outcome-contract";
import styles from "./report-call-outcome.module.css";

type Props = {
  /** Parent binds person, tenant, session and call; scope changes discard unsaved drafts. */
  scopeKey: string;
  /** Undefined means unavailable; null means the server confirms it is unrecorded. */
  value?: HumanCallOutcome | null;
  canEdit?: boolean;
  onSave?: (value: HumanCallOutcome) => Promise<void>;
  /** Resolves only after a fresh scoped server read updates value/capability/revision. */
  onReload?: () => Promise<void>;
};

/** Controlled human command seam. Caller saves audited revisions and reads them back. */
export function CallOutcomeEditor(props: Props) {
  return <OutcomeControls key={props.scopeKey} {...props} />;
}

function OutcomeControls({ value, canEdit = false, onSave, onReload }: Props) {
  const id = useId();
  const [choice, setChoice] = useState<CallOutcomeKind | null>(null);
  const [reason, setReason] = useState("");
  const [date, setDate] = useState("");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("");
  const [showValue, setShowValue] = useState(false);
  const [saving, setSaving] = useState(false);
  const [needsReload, setNeedsReload] = useState(false);
  const [reloading, setReloading] = useState(false);
  const pending = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const enabled = value !== undefined && canEdit && !!onSave;
  async function save(kind: CallOutcomeKind) {
    if (!enabled || !onSave || pending.current || needsReload) return;
    let next: HumanCallOutcome;
    try {
      next = parseHumanCallOutcome({
        outcome: kind,
        lost_reason: kind === "lost" ? reason : null,
        follow_up_on: kind === "follow_up" ? date : null,
        deal_value: showValue
          ? amount || currency
            ? { amount, currency_code: currency }
            : null
          : (value?.deal_value ?? null),
      });
    } catch {
      setError(
        kind === "lost" && !reason.trim()
          ? "Add a reason for Lost."
          : kind === "follow_up" && !date
            ? "Choose a follow-up date."
            : "Check the date, amount and currency.",
      );
      return;
    }
    pending.current = true;
    setSaving(true);
    setError(null);
    try {
      await onSave(next);
      // No optimistic outcome/stage or success label: the parent must read back.
      setChoice(null);
    } catch {
      setNeedsReload(true);
      setError(
        "Your outcome couldn't be confirmed. Reload before saving again.",
      );
    } finally {
      pending.current = false;
      setSaving(false);
    }
  }
  function choose(kind: CallOutcomeKind) {
    if (!enabled || saving || needsReload) return;
    setError(null);
    setChoice(kind);
    if (kind === "won" || kind === "no_decision") void save(kind);
  }
  async function reload() {
    if (!enabled || !needsReload || pending.current) return;
    pending.current = true;
    setReloading(true);
    if (!onReload) {
      window.location.reload();
      return;
    }
    try {
      await onReload();
      setNeedsReload(false);
      setError(null);
      setChoice(null);
    } catch {
      setError(
        "Call outcome is still unavailable. Reload before saving again.",
      );
    } finally {
      pending.current = false;
      setReloading(false);
    }
  }
  const disabled = saving || needsReload;
  return (
    <section
      className={styles.outcome}
      aria-label="Recorded call outcome"
      aria-busy={saving || reloading}
    >
      <div className={styles.current}>
        <strong>Call outcome</strong>
        <span>
          {needsReload
            ? "Unconfirmed"
            : value === undefined
              ? "Unavailable"
              : value === null
                ? "Unrecorded"
                : CALL_OUTCOME_LABELS[value.outcome]}
        </span>
        {!needsReload && value?.lost_reason && <span>{value.lost_reason}</span>}
        {!needsReload && value?.follow_up_on && (
          <span>{value.follow_up_on}</span>
        )}
        {!needsReload && value?.deal_value && (
          <span>
            {value.deal_value.amount} {value.deal_value.currency_code}
          </span>
        )}
      </div>
      {enabled && (
        <>
          <div
            className={styles.choices}
            role="group"
            aria-label="Set call outcome"
          >
            {(Object.keys(CALL_OUTCOME_LABELS) as CallOutcomeKind[]).map(
              (kind) => (
                <button
                  key={kind}
                  type="button"
                  disabled={disabled}
                  aria-pressed={choice === kind}
                  onClick={() => choose(kind)}
                >
                  {CALL_OUTCOME_LABELS[kind]}
                </button>
              ),
            )}
            <button
              type="button"
              disabled={disabled}
              onClick={() => {
                setShowValue((shown) => !shown);
                setAmount(value?.deal_value?.amount ?? "");
                setCurrency(value?.deal_value?.currency_code ?? "");
              }}
            >
              Deal value
            </button>
          </div>
          {choice === "lost" && (
            <label htmlFor={`${id}-reason`}>
              Reason for Lost
              <input
                id={`${id}-reason`}
                maxLength={1000}
                value={reason}
                disabled={disabled}
                onChange={(event) => setReason(event.target.value)}
              />
            </label>
          )}
          {choice === "follow_up" && (
            <label htmlFor={`${id}-date`}>
              Follow-up date
              <input
                id={`${id}-date`}
                type="date"
                value={date}
                disabled={disabled}
                onChange={(event) => setDate(event.target.value)}
              />
            </label>
          )}
          {showValue && (
            <div className={styles.value}>
              <label htmlFor={`${id}-amount`}>
                Deal amount
                <input
                  id={`${id}-amount`}
                  inputMode="decimal"
                  value={amount}
                  disabled={disabled}
                  onChange={(event) => setAmount(event.target.value)}
                />
              </label>
              <label htmlFor={`${id}-currency`}>
                Currency code
                <input
                  id={`${id}-currency`}
                  maxLength={3}
                  placeholder="e.g. INR"
                  value={currency}
                  disabled={disabled}
                  onChange={(event) => setCurrency(event.target.value)}
                />
              </label>
            </div>
          )}
          {(choice === "lost" || choice === "follow_up") && (
            <button
              type="button"
              disabled={disabled}
              onClick={() => void save(choice)}
            >
              Save outcome
            </button>
          )}
          {saving && <span className={styles.state}>Saving outcome…</span>}
          {reloading && <span className={styles.state}>Reading outcome…</span>}
          {error && (
            <div className={styles.error} role="alert">
              <span>{error}</span>
              {needsReload ? (
                <button
                  type="button"
                  disabled={reloading}
                  onClick={() => void reload()}
                >
                  Reload
                </button>
              ) : choice ? (
                <button
                  type="button"
                  disabled={saving}
                  onClick={() => void save(choice)}
                >
                  Try again
                </button>
              ) : null}
            </div>
          )}
        </>
      )}
    </section>
  );
}
