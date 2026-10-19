"use client";

/**
 * Today's spend per pipeline, and when a cap is reached, one button: "Raise to
 * ₹X and resume" (owner, 19 Oct: "one click for admin ... getting it unstuck").
 * Nothing waits on a cap but this engine: Reports always go on.
 */

import { Play } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Badge, Button } from "../ui/kit";
import type { CallDataSettings } from "./call-data-model";
import styles from "./call-data-settings.module.css";

const LABEL = { fast: "Fast pipeline", deep: "Deep pipeline" } as const;

export function CallDataBudget({ settings }: { settings: CallDataSettings }) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const raise = async (pipeline: "fast" | "deep", to: number) => {
    setBusy(pipeline);
    setMessage(null);
    try {
      const response = await fetch("/v1/admin/call-data/raise", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
        headers: {
          accept: "application/json",
          "content-type": "application/json",
        },
        body: JSON.stringify({
          expected_revision: settings.revision,
          pipeline,
          daily_cap_inr: to,
        }),
      });
      if (!response.ok) {
        setMessage(
          response.status === 409
            ? "Someone changed these settings. Refresh and try again."
            : "Not raised. Use your verified AC Admin account and try again.",
        );
        return;
      }
      setMessage(`Raised to ₹${to}. Waiting calls resume within seconds.`);
      router.refresh();
    } catch {
      setMessage("Not raised. Try again.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className={styles.form}>
      {(["fast", "deep"] as const).map((pipeline) => {
        const status = settings.status[pipeline];
        const on = settings.config[pipeline].enabled;
        const share = status.dailyCapInr
          ? Math.min(1, status.spentTodayInr / status.dailyCapInr)
          : 0;
        return (
          <div
            key={pipeline}
            className={status.atCap ? styles.paused : undefined}
          >
            <div className={styles.pausedLine}>
              <strong>{LABEL[pipeline]}</strong>
              <Badge tone={!on ? "neutral" : status.atCap ? "warn" : "good"}>
                {!on
                  ? "Off"
                  : status.atCap
                    ? "Paused: daily cap reached"
                    : "Running"}
              </Badge>
              <span>
                ₹{status.spentTodayInr.toFixed(2)} of ₹{status.dailyCapInr}{" "}
                today
              </span>
              {on && status.waiting ? (
                <span>{status.waiting} calls waiting</span>
              ) : null}
            </div>
            <span
              className={styles.meter}
              data-full={status.atCap ? "" : undefined}
            >
              <span style={{ width: `${Math.round(share * 100)}%` }} />
            </span>
            {status.atCap ? (
              <div className={styles.pausedLine}>
                <Button
                  variant="primary"
                  disabled={busy !== null}
                  onClick={() => void raise(pipeline, status.raiseToInr)}
                >
                  <Play size={14} aria-hidden="true" />
                  Raise to ₹{status.raiseToInr} and resume
                </Button>
                <span className={styles.sub}>
                  Nothing is lost: calls wait and are read once the cap is
                  raised. Reports are not affected.
                </span>
              </div>
            ) : null}
          </div>
        );
      })}
      {message ? (
        <span className={styles.message} role="status">
          {message}
        </span>
      ) : null}
    </div>
  );
}
