"use client";

/**
 * "Last call, in short" on a lead (UX study item 10, 18 Oct): the newest
 * analysed call's Report in three lines, readable in five seconds, with Use
 * as follow-up when the Report names a date. The full Report is one tap away.
 * Nothing shows when the call has no Report the viewer may read.
 */

import { CalendarClock, FileText } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { acquisition, callHref, submissionPath } from "../acquisition-client";
import { Button, Skeleton } from "../ui/kit";
import { callBrief, type CallBrief } from "./call-brief";
import { LeadsError, setFollowUp, when, type LeadDetail } from "./leads-client";
import styles from "./leads.module.css";

export function LastCallBrief({
  detail,
  onChanged,
}: {
  detail: LeadDetail;
  onChanged: (next: LeadDetail) => void;
}) {
  const id =
    detail.events.find((event) => event.kind === "call" && event.submission_id)
      ?.submission_id ?? null;
  const [read, setRead] = useState<{
    id: string;
    brief: CallBrief | null;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    const controller = new AbortController();
    acquisition(`${submissionPath(id)}/report`, { signal: controller.signal })
      .then((payload) => setRead({ id, brief: callBrief(payload) }))
      .catch(() => {
        // Not ready, not yours or gone: the History link still opens it.
        if (!controller.signal.aborted) setRead({ id, brief: null });
      });
    return () => controller.abort();
  }, [id]);

  if (!id) return null;
  const loading = read?.id !== id;
  const brief = loading ? null : (read?.brief ?? null);
  if (!loading && !brief) return null;

  const open = detail.lead.stage !== "won" && detail.lead.stage !== "lost";
  const at = brief?.next?.at ?? null;
  const lost = Boolean(brief?.outcome && /lost/i.test(brief.outcome));
  const bookIt = async () => {
    if (!at) return;
    setBusy(true);
    setNote(null);
    try {
      onChanged(await setFollowUp(detail.lead, at));
      setNote(`Next call booked for ${when(at.toISOString())}.`);
    } catch (reason) {
      setNote(
        reason instanceof LeadsError
          ? reason.message
          : "Not booked. Try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      className={styles.panel}
      aria-label="Last call, in short"
      aria-busy={loading || undefined}
    >
      <div className={styles.panelHead}>
        <h3>Last call, in short</h3>
        <Link className={styles.linkButton} href={callHref(id)}>
          <FileText size={14} aria-hidden="true" />
          Full Report
        </Link>
      </div>
      {loading ? (
        <div className={styles.briefSkeleton}>
          <Skeleton height={12} />
          <Skeleton height={12} width="80%" />
          <Skeleton height={12} width="60%" />
        </div>
      ) : (
        <dl className={styles.detailRows}>
          {brief?.summary ? (
            <div>
              <dt>What happened</dt>
              <dd>{brief.summary}</dd>
            </div>
          ) : null}
          {brief?.objection ? (
            <div>
              <dt>{lost ? "Why it was lost" : "Main objection"}</dt>
              <dd>{brief.objection}</dd>
            </div>
          ) : null}
          {brief?.next ? (
            <div>
              <dt>Next step</dt>
              <dd>
                {brief.next.text}
                {at ? ` · ${when(at.toISOString())}` : ""}
              </dd>
            </div>
          ) : null}
        </dl>
      )}
      {at && open && detail.can_edit ? (
        <Button disabled={busy} onClick={() => void bookIt()}>
          <CalendarClock size={14} aria-hidden="true" />
          Use as follow-up
        </Button>
      ) : null}
      {note ? (
        <p className={styles.doneLine} role="status">
          {note}
        </p>
      ) : null}
    </section>
  );
}
