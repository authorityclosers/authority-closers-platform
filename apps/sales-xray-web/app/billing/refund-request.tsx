"use client";

import { useRef, useState } from "react";

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

  if (result?.state === "refunded" || result?.state === "pending")
    return (
      <span role="status">
        {result.state === "refunded" ? "Refunded" : "Refund requested"}
      </span>
    );
  if (refund?.state === "pending") return <span>Refund requested</span>;
  if (refund?.state === "refunded") return <span>Refunded</span>;
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
            <button
              type="button"
              className={className}
              data-primary="true"
              disabled={busy}
              onClick={() => void submit()}
            >
              {busy ? "Requesting…" : `Refund ${amount}`}
            </button>
            <button
              type="button"
              className={className}
              disabled={busy}
              onClick={() => setOpen(false)}
            >
              Keep it
            </button>
          </div>
        }
      >
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
      </Sheet>
    </>
  );
}
