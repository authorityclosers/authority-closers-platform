import Link from "next/link";
import { useContext } from "react";

import { kitStyles } from "../ui/kit";
import type { CallSummary, ProgressPoint } from "./coaching-client";
import { CALLS, POINT_COPY } from "./coaching-copy";
import { callDate } from "./coaching-format";
import { CallsOpenReports, useTheirCoaching } from "./coaching-voice";
import styles from "./coaching.module.css";

/**
 * The newest call with coaching, straight from pillar 1: its Report, its own
 * coaching when this viewer may open it (the rep's own calls, or fictional
 * Sandbox calls; a real shared rep's per-call coaching stays theirs), and its
 * saved record on the current focus, marked like the progress history.
 */
export function RepCallLinks({
  calls,
  progress,
  onSeeCalls,
}: {
  calls?: CallSummary[];
  progress?: ProgressPoint[];
  onSeeCalls?: () => void;
}) {
  const they = useTheirCoaching();
  const reportsOnly = useContext(CallsOpenReports);
  if (!calls?.length) return null;
  const latest = calls.reduce<CallSummary | null>(
    (newest, call) =>
      call.state === "ready" &&
      (!newest || Date.parse(call.created_at) > Date.parse(newest.created_at))
        ? call
        : newest,
    null,
  );
  const state = latest
    ? progress?.find((point) => point.submission_id === latest.submission_id)
        ?.state
    : undefined;
  const record = state && state !== "not_covered" ? state : null;
  return (
    <nav
      className={styles.repCallLinks}
      aria-label={they ? CALLS.theirShortcuts : CALLS.yourShortcuts}
    >
      {latest ? (
        <div>
          <span className={styles.cardLabel}>{CALLS.latestReady}</span>
          <p className={styles.repCallTitle}>{latest.call_label}</p>
          <p className={`${styles.note} ${styles.repCallMeta}`}>
            <span>{callDate(latest.created_at)}</span>
            {record ? (
              <span className={styles.callPoint} data-state={record}>
                {POINT_COPY[record]}
              </span>
            ) : null}
          </p>
        </div>
      ) : null}
      <div className={styles.actions}>
        {latest ? (
          <>
            <Link
              className={kitStyles.button}
              href={`/analysis/calls/${latest.submission_id}`}
            >
              {CALLS.openReport}
            </Link>
            {reportsOnly ? null : (
              <Link
                className={kitStyles.button}
                href={`/coaching?call=${latest.submission_id}`}
              >
                {CALLS.openCoaching}
              </Link>
            )}
          </>
        ) : null}
        <a
          className={kitStyles.button}
          href="#coaching-calls"
          aria-controls="coaching-calls"
          onClick={onSeeCalls}
        >
          {CALLS.seeCalls}
        </a>
      </div>
    </nav>
  );
}
