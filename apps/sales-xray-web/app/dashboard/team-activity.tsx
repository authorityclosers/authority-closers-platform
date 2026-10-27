"use client";

/**
 * Team activity (owner, 27 Oct 2026, of the Team view: "ugly"; orchestrator:
 * a team Recent activity feed, who called whom, reports ready, leads assigned
 * or moved, with what needs you first and the charts after). Today's work
 * across the team, newest first: each line names the lead or call, says who
 * did what in the lead's own history words, and opens the lead or the Report.
 * Reports come from the saved calls Home already reads; the rest from the
 * team's lead history (GET /v1/lead-desk/activity?team=1, owners and admins).
 */

import {
  ArrowRightLeft,
  ChevronRight,
  Clock,
  FileCheck2,
  MessageCircle,
  NotebookPen,
  Phone,
  PhoneMissed,
  Sparkles,
  UserPlus,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { callHref, type LibrarySubmission } from "../acquisition-client";
import { callTitle } from "../call-label";
import { shortWhen } from "../calls/call-rows";
import { CallRowsSkeleton } from "../calls/phone-calls";
import { displayName } from "../display-name";
import { eventText } from "../leads/lead-sheet";
import { handOverLead } from "../leads/lead-handoff";
import {
  deskRequest,
  type ActivityItem,
  type ActivityPage,
} from "../leads/leads-client";
import { Avatar } from "../ui/kit";
import styles from "./home-v2.module.css";
import homeStyles from "./sales-home.module.css";

export const TEAM_ROWS = 6;

/** Today's work by everyone in the workspace (owners and admins). */
export function readTeamActivity(signal?: AbortSignal) {
  return deskRequest<ActivityPage>("/activity?day=today&team=1", { signal });
}

export type TeamRow = {
  key: string;
  at: string;
  /** Who did it, for the avatar; null for the lead rules or the system. */
  actor: string | null;
  /** The lead's name, or the call's. */
  title: string;
  line: string;
  kind: string;
  report: string | null;
  leadId: string | null;
};

export function rowFromWork(item: ActivityItem): TeamRow {
  const missed =
    item.event.direction === "missed" || item.event.direction === "rejected";
  return {
    key: item.event_id,
    at: item.event.at,
    actor: item.event.actor_name,
    title: displayName(item.lead_name),
    line: eventText(item.event).title,
    kind: missed ? "missed" : item.event.kind,
    report:
      item.event.kind === "call" ? (item.event.submission_id ?? null) : null,
    leadId: item.lead_id,
  };
}

/** A saved call whose Report is ready, as a team line. */
export function rowFromReport(call: LibrarySubmission): TeamRow {
  const owner = call.owner?.name ?? null;
  return {
    key: `report-${call.id}`,
    at: call.createdAt,
    actor: owner,
    title: call.lead
      ? displayName(call.lead.name)
      : callTitle(call.label, "Saved call"),
    line: owner
      ? `Report ready · ${displayName(owner)}'s call`
      : "Report ready",
    kind: "report",
    report: call.id,
    leadId: call.lead?.leadId ?? null,
  };
}

/** Today's lines, newest first; a call already listed with its Report shows once. */
export function teamRows(
  work: readonly ActivityItem[],
  saved: readonly LibrarySubmission[],
  now: Date = new Date(),
): TeamRow[] {
  const today = now.toDateString();
  const lines = work.map(rowFromWork);
  const listed = new Set(lines.map((row) => row.report).filter(Boolean));
  const reports = saved
    .filter(
      (call) =>
        call.hasReport &&
        !listed.has(call.id) &&
        new Date(call.createdAt).toDateString() === today,
    )
    .map(rowFromReport);
  return [...lines, ...reports].sort(
    (a, b) => Date.parse(b.at) - Date.parse(a.at),
  );
}

const ICONS: Record<string, LucideIcon> = {
  call: Phone,
  missed: PhoneMissed,
  result: Phone,
  note: NotebookPen,
  stage: ArrowRightLeft,
  message: MessageCircle,
  assigned: UserPlus,
  reassigned: UserPlus,
  captured: Sparkles,
  report: FileCheck2,
};

type Work =
  | { status: "loading" }
  | { status: "ready"; items: ActivityItem[] }
  | { status: "off" };

export function TeamActivity({
  saved,
}: {
  /** The latest saved calls Home already reads (the team's, for owners). */
  saved: readonly LibrarySubmission[] | null;
}) {
  const router = useRouter();
  const [work, setWork] = useState<Work>({ status: "loading" });
  const [now] = useState(() => new Date());
  useEffect(() => {
    const controller = new AbortController();
    readTeamActivity(controller.signal).then(
      (page) =>
        setWork({
          status: "ready",
          items: Array.isArray(page?.items) ? page.items : [],
        }),
      (reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError")
          return;
        // Not for this role, or not loaded: Team stays as it is.
        setWork({ status: "off" });
      },
    );
    return () => controller.abort();
  }, []);
  if (work.status === "off") return null;
  const rows =
    work.status === "ready"
      ? teamRows(work.items, saved ?? [], now).slice(0, TEAM_ROWS)
      : [];
  return (
    <section className={homeStyles.block} aria-labelledby="team-activity-title">
      <div className={homeStyles.head}>
        <h2 id="team-activity-title">Team today</h2>
        <Link className={styles.more} href="/organisation?tab=team">
          Team
          <ChevronRight size={16} aria-hidden="true" />
        </Link>
      </div>
      {work.status === "loading" ? (
        <CallRowsSkeleton label="Team today" rows={4} />
      ) : rows.length === 0 ? (
        <p className={homeStyles.quiet}>
          Nothing yet today. Calls, reports and lead moves show here as they
          happen.
        </p>
      ) : (
        <ol className={styles.activity} aria-label="Team today, newest first">
          {rows.map((row) => {
            const Icon = ICONS[row.kind] ?? Clock;
            const leadId = row.leadId;
            return (
              <li key={row.key}>
                <Link
                  className={styles.activityRow}
                  href={row.report ? callHref(row.report) : "/leads"}
                  data-sx-action={row.report ? "report_open" : "lead_open"}
                  onClick={(click) => {
                    if (row.report || !leadId) return;
                    click.preventDefault();
                    handOverLead(leadId, false, row.at);
                    router.push("/leads");
                  }}
                >
                  <span className={styles.who} aria-hidden="true">
                    <Avatar name={row.actor ?? "Lead rules"} size={32} />
                    <span className={styles.badge} data-kind={row.kind}>
                      <Icon size={11} />
                    </span>
                  </span>
                  <span className={styles.words}>
                    <strong>{row.title}</strong>
                    <span>{row.line}</span>
                  </span>
                  <time dateTime={row.at}>{shortWhen(row.at, now)}</time>
                </Link>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
