"use client";

/**
 * "Needs you" on an owner's Home (approved map, slice 8, 22 Oct 2026): what is
 * waiting on someone right now, from facts the server counts, never an AI score.
 * Leads waiting past the first-response target, new leads with no owner, and late
 * follow-ups across the team; each row opens the work. Nothing waiting: it says so.
 */

import {
  ArrowRight,
  CalendarClock,
  MessageCircleWarning,
  UserX,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { displayName } from "../display-name";
import { leadLink, type Desk } from "../leads/leads-client";
import { waCall, type SlaReport } from "../leads/whatsapp-client";
import { ActionList, ActionRow, Avatar, Badge } from "../ui/kit";
import { NeedsSkeleton } from "./sales-home-skeleton";
import styles from "./sales-home.module.css";

/** How many named leads the waiting row lists before "See all". */
const SHOWN = 3;

/** The team's late follow-ups on Leads. */
const LATE_HREF = "/leads?tab=all&due=late";

const waited = (minutes: number) =>
  minutes < 60
    ? `${Math.max(1, Math.round(minutes))} min`
    : `${Math.floor(minutes / 60)} h ${Math.round(minutes % 60)} min`;

export function NeedsYou({
  desk,
  late,
}: {
  /** The team's desk (its counts); null while it loads. */
  desk: Desk | null;
  /** Late follow-ups across the team this period; undefined while it loads. */
  late: number | undefined;
}) {
  const [sla, setSla] = useState<SlaReport | null>(null);
  useEffect(() => {
    let live = true;
    waCall<SlaReport>("/reports/sla").then(
      (report) => live && setSla(report),
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, []);

  const waiting = sla?.settings.on ? (sla.late ?? []) : [];
  const unassigned = desk?.counts.unassigned ?? 0;
  // A Viewer reads what is waiting and changes nothing (Roles B, 27 Oct 2026): no
  // way into the lead rules, and words that ask nothing of them.
  const manages = desk?.me.can_manage === true;
  const loading = !desk || late === undefined;
  const nothing = !loading && !waiting.length && !unassigned && !late;

  return (
    <section className={styles.block} aria-labelledby="needs-title">
      <div className={styles.head}>
        <h2 id="needs-title">{manages ? "Needs you" : "Needs attention"}</h2>
      </div>
      {loading ? (
        <NeedsSkeleton />
      ) : nothing ? (
        <p className={styles.quiet} role="status">
          {manages
            ? "Nothing needs you right now."
            : "Nothing is waiting right now."}
        </p>
      ) : (
        <ActionList label="Needs you">
          {waiting.length ? (
            <ActionRow
              icon={<MessageCircleWarning size={20} />}
              tone="bad"
              title="Waiting for a first response"
              note={`Right now, longer than ${waited(sla?.settings.minutes ?? 0)} (your target)`}
              end={<Badge tone="bad">{waiting.length}</Badge>}
              href={
                manages ? "/settings/lead-rules" : "/leads?tab=all&stage=open"
              }
            />
          ) : null}
          {waiting.slice(0, SHOWN).map((lead) => (
            <ActionRow
              key={lead.leadId}
              // A monogram, so the named leads read as part of the row above
              // (Liquid Glass review, 22 Oct 2026).
              tone="neutral"
              icon={
                <Avatar
                  name={displayName(lead.leadName)}
                  size={34}
                  shape="square"
                />
              }
              title={displayName(lead.leadName)}
              note={`Waiting ${waited(lead.minutesLate)} · ${displayName(lead.seller)}`}
              href={leadLink(lead.leadId)}
            />
          ))}
          {unassigned ? (
            <ActionRow
              icon={<UserX size={20} />}
              tone="warn"
              title="New leads with no owner"
              note={
                manages
                  ? "Give them to a seller, or let the lead rules decide"
                  : "Waiting for a seller or the lead rules"
              }
              end={<Badge tone="warn">{unassigned}</Badge>}
              href="/leads?tab=all&stage=open&who=unassigned"
            />
          ) : null}
          {late ? (
            <ActionRow
              icon={<CalendarClock size={20} />}
              tone="warn"
              title="Late follow-ups"
              note="Across the team. Sellers below shows whose."
              end={<Badge tone="warn">{late}</Badge>}
              href={LATE_HREF}
            />
          ) : null}
        </ActionList>
      )}
      {/* The screen's one primary action (owner Home v3, B: "Review
          follow-ups"): for those who work leads, while any are late. */}
      {!loading && late && manages ? (
        <Link className={styles.primary} href={LATE_HREF}>
          {`Review ${late} late ${late === 1 ? "follow-up" : "follow-ups"}`}
          <ArrowRight size={18} aria-hidden="true" />
        </Link>
      ) : null}
    </section>
  );
}
