"use client";

import {
  BIG_PICTURE,
  COMMON,
  OUTCOME_CHOICES,
  OUTCOME_RECORD,
} from "./report-copy";
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
          ? OUTCOME_RECORD.needReason
          : kind === "follow_up" && !date
            ? OUTCOME_RECORD.needDate
            : OUTCOME_RECORD.checkValues,
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
      setError(OUTCOME_RECORD.saveNotConfirmed);
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
      setError(OUTCOME_RECORD.stillUnavailable);
    } finally {
      pending.current = false;
      setReloading(false);
    }
  }
  const disabled = saving || needsReload;
  return (
    <section
      className={styles.outcome}
      aria-label={BIG_PICTURE.outcome.label}
      aria-busy={saving || reloading}
    >
      <div className={styles.current}>
        <strong>{OUTCOME_RECORD.title}</strong>
        <span>
          {needsReload
            ? OUTCOME_RECORD.notConfirmed
            : value === undefined
              ? OUTCOME_RECORD.unavailable
              : value === null
                ? OUTCOME_RECORD.notSet
                : OUTCOME_CHOICES[value.outcome]}
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
            aria-label={OUTCOME_RECORD.title}
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
                  {OUTCOME_CHOICES[kind]}
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
              {OUTCOME_RECORD.dealValue}
            </button>
          </div>
          {choice === "lost" && (
            <label htmlFor={`${id}-reason`}>
              {OUTCOME_RECORD.lostReason}
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
              {OUTCOME_RECORD.followUpDate}
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
                {OUTCOME_RECORD.amount}
                <input
                  id={`${id}-amount`}
                  inputMode="decimal"
                  value={amount}
                  disabled={disabled}
                  onChange={(event) => setAmount(event.target.value)}
                />
              </label>
              <label htmlFor={`${id}-currency`}>
                {OUTCOME_RECORD.currency}
                <input
                  id={`${id}-currency`}
                  maxLength={3}
                  placeholder={OUTCOME_RECORD.currencyExample}
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
              {OUTCOME_RECORD.save}
            </button>
          )}
          {saving && (
            <span className={styles.state}>{OUTCOME_RECORD.saving}</span>
          )}
          {reloading && (
            <span className={styles.state}>{OUTCOME_RECORD.checking}</span>
          )}
          {error && (
            <div className={styles.error} role="alert">
              <span>{error}</span>
              {needsReload ? (
                <button
                  type="button"
                  disabled={reloading}
                  onClick={() => void reload()}
                >
                  {OUTCOME_RECORD.reload}
                </button>
              ) : choice ? (
                <button
                  type="button"
                  disabled={saving}
                  onClick={() => void save(choice)}
                >
                  {COMMON.tryAgain}
                </button>
              ) : null}
            </div>
          )}
        </>
      )}
    </section>
  );
}
