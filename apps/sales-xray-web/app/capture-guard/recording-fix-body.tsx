"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import {
  readAutoAnalysis,
  type AutoAnalysis,
} from "../settings/auto-analysis-client";
import { AutoCapturePanel } from "../settings/auto-capture-panel";
import { Skeleton } from "../ui/kit";
import styles from "./capture-guard.module.css";

/**
 * Settings, Privacy's own recording check, for one call's sheet. The panel
 * turns uploads off without the seller's consent, so it shows only once that
 * consent has been read: never while it loads, never after a failed read.
 */
export function RecordingFixBody() {
  const [view, setView] = useState<AutoAnalysis | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let alive = true;
    readAutoAnalysis().then(
      (next) => {
        if (alive) setView(next);
      },
      () => {
        if (alive) setFailed(true);
      },
    );
    return () => {
      alive = false;
    };
  }, []);
  if (failed)
    return (
      <p className={styles.note} role="status">
        The check couldn&apos;t load. Check your connection, or open{" "}
        <Link href="/settings/privacy#calls-setup">Settings, Privacy</Link>.
      </p>
    );
  if (!view) return <Skeleton height={160} />;
  return (
    <AutoCapturePanel
      consentOn={view.can_start}
      consentGiven={view.state === "on"}
    />
  );
}
