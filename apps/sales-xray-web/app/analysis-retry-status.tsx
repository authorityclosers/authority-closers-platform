"use client";

import { useEffect, useRef, useState } from "react";
import {
  acquisition,
  AcquisitionError,
  submissionPath,
} from "./acquisition-client";
import { notify } from "./notice-center";
import {
  parseProcessingPlan,
  type ProcessingPlan,
} from "./processing-plan-contract";
import styles from "./analysis-retry-status.module.css";

function acceptedPlan(plan: ProcessingPlan): boolean {
  return (
    plan.accepted &&
    (["active", "completed"].includes(plan.state) ||
      (plan.state === "held" &&
        plan.failure_code === "account_profile_required"))
  );
}

function terminalPlan(plan: ProcessingPlan): boolean {
  return (
    plan.state === "cancelled" ||
    (plan.state === "held" && plan.failure_code !== "account_profile_required")
  );
}

function retryKey(submissionId: string): string {
  const storageKey = `ac.xray.retry.v1:${submissionId}`;
  let saved: string | null = null;
  try {
    saved = sessionStorage.getItem(storageKey);
  } catch {
    /* In-memory coalescing still applies. */
  }
  if (saved && /^retry:[a-f0-9-]{36}$/.test(saved)) return saved;
  const key = `retry:${crypto.randomUUID()}`;
  try {
    sessionStorage.setItem(storageKey, key);
  } catch {
    /* Storage is optional. */
  }
  return key;
}

export function AnalysisRetryAction({
  submissionId,
  recordingId,
}: {
  submissionId: string;
  recordingId: string;
}) {
  const [plan, setPlan] = useState<ProcessingPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const flight = useRef<AbortController | null>(null);
  const key = useRef<string | null>(null);
  useEffect(() => () => flight.current?.abort(), []);

  const retry = async () => {
    if (flight.current) return;
    const controller = new AbortController();
    flight.current = controller;
    setBusy(true);
    const timeout = setTimeout(() => controller.abort(), 20_000);
    let terminalConfirmed = false;
    const clearTerminalPlan = () => {
      terminalConfirmed = true;
      setPlan(null);
      key.current = null;
      try {
        sessionStorage.removeItem(`ac.xray.retry.v1:${submissionId}`);
      } catch {
        /* The confirmed terminal plan needs a fresh command. */
      }
    };
    try {
      key.current ??= retryKey(submissionId);
      const value = await acquisition(
        `${submissionPath(submissionId)}/${plan ? "plan" : "retry"}`,
        {
          method: "POST",
          signal: controller.signal,
          headers: {
            "Idempotency-Key": plan ? `${key.current}:accept` : key.current,
            ...(plan ? { "content-type": "application/json" } : {}),
          },
          ...(plan
            ? {
                body: JSON.stringify({
                  plan_id: plan.id,
                  plan_fingerprint: plan.plan_fingerprint,
                  privacy_revision: plan.privacy_revision,
                  accepted: true,
                }),
              }
            : {}),
        },
      );
      if (value && typeof value === "object" && "retry_kind" in value) {
        const local = value as Record<string, unknown>;
        if (
          plan !== null ||
          local.retry_kind !== "local" ||
          local.recording_id !== recordingId ||
          typeof local.run_id !== "string" ||
          !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(
            local.run_id,
          ) ||
          !["queued", "running", "completed", "failed"].includes(
            local.state as string,
          )
        )
          throw new Error("Local retry was not confirmed.");
        try {
          sessionStorage.removeItem(`ac.xray.retry.v1:${submissionId}`);
        } catch {
          /* Optional cache. */
        }
        window.location.reload();
        return;
      }
      const saved = parseProcessingPlan(value, recordingId);
      if (plan) {
        if (
          saved.id !== plan.id ||
          saved.plan_fingerprint !== plan.plan_fingerprint
        )
          throw new Error("Retry was not accepted.");
        if (terminalPlan(saved)) {
          clearTerminalPlan();
          throw new AcquisitionError(409);
        }
        if (!acceptedPlan(saved)) throw new Error("Retry was not accepted.");
        try {
          sessionStorage.removeItem(`ac.xray.retry.v1:${submissionId}`);
        } catch {
          /* The server receipt owns idempotency. */
        }
        window.location.reload();
      } else if (acceptedPlan(saved)) {
        try {
          sessionStorage.removeItem(`ac.xray.retry.v1:${submissionId}`);
        } catch {
          /* Optional cache. */
        }
        window.location.reload();
      } else if (terminalPlan(saved)) {
        clearTerminalPlan();
        throw new AcquisitionError(409);
      } else {
        setPlan(saved);
      }
    } catch (error) {
      if (
        plan &&
        !terminalConfirmed &&
        error instanceof AcquisitionError &&
        [403, 409].includes(error.status) &&
        !controller.signal.aborted
      ) {
        try {
          const latest = parseProcessingPlan(
            await acquisition(`${submissionPath(submissionId)}/plan`, {
              signal: controller.signal,
            }),
            recordingId,
          );
          if (
            latest.id === plan.id &&
            latest.plan_fingerprint === plan.plan_fingerprint
          ) {
            if (acceptedPlan(latest)) {
              try {
                sessionStorage.removeItem(`ac.xray.retry.v1:${submissionId}`);
              } catch {
                /* The matching server view confirms the acceptance. */
              }
              window.location.reload();
              return;
            }
            if (terminalPlan(latest)) clearTerminalPlan();
          }
        } catch {
          /* An ambiguous read must retain the exact acceptance command. */
        }
      }
      notify({
        id: `analysis-retry:${submissionId}`,
        tone: "error",
        title: "Retry needs checking",
        message:
          error instanceof AcquisitionError
            ? error.message
            : "The retry was not confirmed. Try again to check the same request.",
      });
    } finally {
      clearTimeout(timeout);
      flight.current = null;
      setBusy(false);
    }
  };

  return (
    <div>
      {plan && (
        <div>
          <p>Review this retry’s approval: {plan.cost_label}.</p>
          <p>
            Minutes are reserved now and used only when a report is delivered.
          </p>
          <details>
            <summary>Providers and privacy terms</summary>
            {plan.stages.map((stage) => (
              <p key={stage.stage}>
                {stage.provider} · {stage.model}: {stage.privacy_notice}
              </p>
            ))}
          </details>
        </div>
      )}
      <div className={styles.actions}>
        <button
          type="button"
          className={styles.button}
          disabled={busy}
          onClick={() => void retry()}
        >
          {busy
            ? "Checking retry…"
            : plan
              ? "Accept and retry analysis"
              : "Try again"}
        </button>
      </div>
    </div>
  );
}
