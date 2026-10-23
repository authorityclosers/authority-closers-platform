"use client";

import { CircleCheck, Clock3 } from "lucide-react";
import { useRef, useState, useSyncExternalStore } from "react";
import { createPortal } from "react-dom";

import { Button } from "../ui/kit";
import { Sheet } from "../ui/sheet";
import { BillingError, idempotencyKey } from "./billing-api";
import type { Refund } from "./contract";
import { day } from "./money";
import styles from "./refund-request.module.css";

export type RequestRefund = (
  paymentId: string,
  reason: string,
  idempotencyKey: string,
) => Promise<Refund>;

const DEFAULT_REASON = "Asked for a refund in the app";

const noSubscription = () => () => {};
/** True once in the browser; the server render has no body to portal into. */
const useInBrowser = () =>
  useSyncExternalStore(
    noSubscription,
    () => true,
    () => false,
  );

/**
 * C1 §4: a full refund within 7 days when none of that payment's minutes were used.
 * Shown only while the server says the payment qualifies ("available"); the server
 * decides again when asked, and its answer is shown as it is.
 */
export function RefundRequest({
  refund,
  amount,
  onRequest,
  className,
  label = "Request refund",
}: {
  refund: Refund | null | undefined;
  /** The amount as the buyer saw it, e.g. "₹2,499". */
  amount: string;
  onRequest: RequestRefund;
  className?: string;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Refund | null>(null);
  const key = useRef<string | null>(null);
  const inBrowser = useInBrowser();

  if (result?.state === "refunded" || result?.state === "pending")
    return <RefundState state={result.state} live />;
  if (refund?.state === "pending" || refund?.state === "refunded")
    return <RefundState state={refund.state} />;
  if (refund?.state !== "available") return null;

  const submit = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    key.current ??= idempotencyKey();
    try {
      const outcome = await onRequest(
        refund.paymentId,
        reason.trim() || DEFAULT_REASON,
        key.current,
      );
      setResult(outcome);
      if (outcome.state === "pending" || outcome.state === "refunded") {
        setOpen(false);
      } else {
        setError(
          outcome.reasonCode === "used"
            ? "Minutes from this payment were already used, so it can't be refunded."
            : "This payment can no longer be refunded.",
        );
      }
    } catch (failure) {
      setError(
        failure instanceof BillingError && failure.detail
          ? failure.detail
          : "The refund couldn't be requested. Please try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  // Drawn on the page body, so a table cell's right alignment and type never
  // reach it (QA, 23 Oct 2026).
  const sheet = (
    <Sheet
      open={open}
      onClose={() => (busy ? undefined : setOpen(false))}
      title="Request a refund"
      description={
        refund.refundableUntil
          ? `Available until ${day(refund.refundableUntil)}.`
          : undefined
      }
      footer={
        <div className={styles.footer}>
          <Button
            variant="ghost"
            disabled={busy}
            onClick={() => setOpen(false)}
          >
            Keep it
          </Button>
          <Button
            variant="primary"
            disabled={busy}
            onClick={() => void submit()}
          >
            {busy ? "Requesting…" : `Refund ${amount}`}
          </Button>
        </div>
      }
    >
      <div className={styles.body}>
        <p>
          You get back the full {amount} because none of this payment&apos;s
          minutes were used. Its minutes leave your balance, and the money goes
          back to the way you paid.
        </p>
        <label className={styles.reason}>
          <span>Reason (optional)</span>
          <textarea
            value={reason}
            maxLength={500}
            rows={3}
            onChange={(event) => setReason(event.target.value)}
          />
        </label>
        {error ? (
          <p className={styles.error} role="alert">
            {error}
          </p>
        ) : null}
      </div>
    </Sheet>
  );

  return (
    <>
      <button
        type="button"
        className={className}
        onClick={() => {
          setError(null);
          setOpen(true);
        }}
      >
        {label}
      </button>
      {inBrowser ? createPortal(sheet, document.body) : null}
    </>
  );
}

/** Where a refund stands, as a small chip with its icon. */
function RefundState({
  state,
  live = false,
}: {
  state: "pending" | "refunded";
  live?: boolean;
}) {
  const Icon = state === "refunded" ? CircleCheck : Clock3;
  return (
    <span
      className={styles.state}
      data-state={state}
      role={live ? "status" : undefined}
    >
      <Icon size={14} aria-hidden="true" />
      {state === "refunded" ? "Refunded" : "Refund requested"}
    </span>
  );
}
