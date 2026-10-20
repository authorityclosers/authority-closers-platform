"use client";

/**
 * Today's spend per pipeline, and when a cap is reached, one button: "Raise to
 * ₹X and resume" (owner, 19 Oct: "one click for admin ... getting it unstuck").
 * The queue in plain words (owner, 20 Oct: nothing runs or charges without an
 * explicit action): new calls wait a short while; older ones are held and are
 * read only by a backfill someone approves. Reports always go on.
 */

import { Play } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Badge, Button } from "../ui/kit";
import type { CallDataSettings } from "./call-data-model";
import styles from "./call-data-settings.module.css";

const LABEL = { fast: "Fast pipeline", deep: "Deep pipeline" } as const;

const DAY = new Intl.DateTimeFormat("en-IN", {
  day: "numeric",
  month: "short",
  timeZone: "Asia/Kolkata",
});

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
      setMessage(
        `Raised to ₹${to}. Calls from the last ${settings.status[pipeline].freshHours} hours resume within seconds; held calls stay held.`,
      );
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
                <span>
                  {status.waiting} new {status.waiting === 1 ? "call" : "calls"}{" "}
                  {status.atCap ? "waiting" : "being read"}
                </span>
              ) : null}
            </div>
            {status.held ? (
              <p className={styles.sub} data-held="">
                <strong>
                  {status.held} {status.held === 1 ? "call" : "calls"} held
                </strong>
                {status.oldestHeldAt
                  ? ` since ${DAY.format(new Date(status.oldestHeldAt))}`
                  : ""}
                : not read because the pipeline was off, at its cap or stopped
                by the AI spend guard. Held calls never run or charge by
                themselves. To read them, raise the backfill cap in AI spend
                (that is the approval) and run a backfill.
              </p>
            ) : null}
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
                  New calls wait {status.freshHours} hours: raising the cap now
                  reads them. After that they are held and never charged unless
                  you act. Reports are not affected.
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
