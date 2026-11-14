"use client";

/**
 * Analysis time, in Settings for everyone (orchestrator, 13 Nov 2026: the owner
 * found "no good UI which makes it understandable" how much analysis time
 * someone has): what is left, read from the same numbers the server admits an
 * analysis by, and who can add more. Time only, never a price.
 */

import Link from "next/link";
import { useEffect, useState } from "react";

import type { Allowance } from "../acquisition-client";
import { analysisTimeLeft } from "../analysis-time";
import { readAllowance } from "../dashboard/dashboard-data";
import { useCanHere } from "../workspace-role";
import styles from "./analysis-time.module.css";

type Read =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; allowance: Allowance };

/** The big line: what is left, or why there is nothing to count. */
export function analysisTimeHeadline(allowance: Allowance): string {
  if (allowance.unlimited) return "Unlimited";
  if (allowance.allowance_seconds <= 0 && allowance.committed_seconds <= 0)
    return "Not on yet";
  return analysisTimeLeft(allowance, "member") ?? "None left";
}

export function AnalysisTimeSection() {
  const [read, setRead] = useState<Read>({ status: "loading" });
  const canHere = useCanHere();
  const pays = canHere("billing.view");
  useEffect(() => {
    const controller = new AbortController();
    readAllowance(controller.signal).then(
      (allowance) => setRead({ status: "ready", allowance }),
      () => {
        if (!controller.signal.aborted) setRead({ status: "error" });
      },
    );
    return () => controller.abort();
  }, []);
  return (
    <section
      className={styles.card}
      aria-label="Analysis time"
      aria-busy={read.status === "loading"}
    >
      <p className={styles.left} role="status">
        {read.status === "loading"
          ? "Checking…"
          : read.status === "error"
            ? "Couldn't check right now"
            : analysisTimeHeadline(read.allowance)}
      </p>
      <p className={styles.who}>
        {pays === null ? null : pays ? (
          <>
            Add more in{" "}
            <Link href="/settings/plan" className={styles.link}>
              Plan &amp; usage
            </Link>
            .
          </>
        ) : (
          "Your owner or admin can add more."
        )}
      </p>
    </section>
  );
}
