import Link from "next/link";

import { kitStyles } from "../ui/kit";
import type { CallSummary } from "./coaching-client";
import { CALLS } from "./coaching-copy";
import { callDate } from "./coaching-format";
import styles from "./coaching.module.css";

/** Existing rep calls only; sharing never opens a real rep's per-call coaching. */
export function RepCallLinks({
  calls,
  sandbox = false,
}: {
  calls?: CallSummary[];
  sandbox?: boolean;
}) {
  if (!calls?.length) return null;
  const latest = calls.reduce<CallSummary | null>(
    (newest, call) =>
      call.state === "ready" &&
      (!newest || Date.parse(call.created_at) > Date.parse(newest.created_at))
        ? call
        : newest,
    null,
  );
  return (
    <nav className={styles.repCallLinks} aria-label="This rep’s calls">
      {latest ? (
        <div>
          <span className={styles.cardLabel}>{CALLS.latestReady}</span>
          <p className={styles.repCallTitle}>{latest.call_label}</p>
          <p className={styles.note}>{callDate(latest.created_at)}</p>
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
            {sandbox ? (
              <Link
                className={kitStyles.button}
                href={`/coaching?call=${latest.submission_id}`}
              >
                {CALLS.openCoaching}
              </Link>
            ) : null}
          </>
        ) : null}
        <a className={kitStyles.button} href="#coaching-calls">
          {CALLS.seeCalls}
        </a>
      </div>
    </nav>
  );
}
