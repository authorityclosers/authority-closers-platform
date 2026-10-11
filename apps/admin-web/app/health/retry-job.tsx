"use client";

/**
 * Retry one failed analysis job through the existing admin retry command
 * (POST /v1/admin/jobs/{id}/retry). It needs a reason; the API refuses jobs
 * that already reached a provider, and its answer is shown as it is.
 */
import {
  retryJob,
  newIdempotencyKey,
  AdminApiProblem,
} from "@ac/operations-web/api";
import { RotateCcw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { kitStyles } from "../ui/kit";
import styles from "./health.module.css";

export function RetryJob({
  jobId,
  retryable,
}: {
  jobId: string;
  retryable: boolean;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "done" | "error">(
    "idle",
  );
  const [message, setMessage] = useState("");
  // One key per intent, so a retried click never retries the job twice.
  const key = useRef(newIdempotencyKey());

  if (!retryable)
    return (
      <span
        className={kitStyles.muted}
        title="This job reached a provider; retrying it could charge twice."
      >
        Not retryable
      </span>
    );
  if (state === "done") return <span role="status">Retry queued</span>;
  if (!open)
    return (
      <button
        type="button"
        className={kitStyles.button}
        onClick={() => setOpen(true)}
      >
        <RotateCcw size={14} aria-hidden="true" />
        Retry
      </button>
    );
  return (
    <form
      className={styles.retry}
      onSubmit={async (event) => {
        event.preventDefault();
        if (!reason.trim() || state === "sending") return;
        setState("sending");
        setMessage("");
        try {
          await retryJob({
            jobId,
            reason: reason.trim(),
            idempotencyKey: key.current,
          });
          setState("done");
          router.refresh();
        } catch (error) {
          setState("error");
          setMessage(
            error instanceof AdminApiProblem
              ? error.message
              : "The retry wasn't confirmed. Try again.",
          );
        }
      }}
    >
      <input
        aria-label="Why retry this job"
        placeholder="Reason (required)"
        value={reason}
        maxLength={500}
        onChange={(event) => setReason(event.target.value)}
      />
      <button
        type="submit"
        className={kitStyles.button}
        data-variant="primary"
        disabled={!reason.trim() || state === "sending"}
      >
        {state === "sending" ? "Retrying…" : "Retry"}
      </button>
      <button
        type="button"
        className={kitStyles.button}
        data-variant="ghost"
        onClick={() => setOpen(false)}
      >
        Cancel
      </button>
      {message ? (
        <small className={kitStyles.fieldError} role="alert">
          {message}
        </small>
      ) : null}
    </form>
  );
}
