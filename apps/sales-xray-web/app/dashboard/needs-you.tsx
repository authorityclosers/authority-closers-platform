"use client";

/**
 * "Needs you" on an owner's Home (approved map, slice 8, 22 Oct 2026): what is
 * waiting on someone right now, from facts the server counts, never an AI score.
 * Leads waiting past the first-response target, new leads with no owner, and late
 * follow-ups across the team; each row opens the work. Nothing waiting: it says so.
 */

import { CalendarClock, MessageCircleWarning, UserX } from "lucide-react";
import { useEffect, useState } from "react";

import { displayName } from "../display-name";
import { leadLink, type Desk } from "../leads/leads-client";
import { waCall, type SlaReport } from "../leads/whatsapp-client";
import { ActionList, ActionRow } from "../ui/kit";
import styles from "./sales-home.module.css";

/** How many named leads the waiting row lists before "See all". */
const SHOWN = 3;

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
  const loading = !desk || late === undefined;
  const nothing = !loading && !waiting.length && !unassigned && !late;

  return (
    <section className={styles.block} aria-labelledby="needs-title">
      <div className={styles.head}>
        <h2 id="needs-title">Needs you</h2>
      </div>
      {loading ? (
        <div className={styles.listSkeleton} aria-busy="true">
          {[0, 1].map((index) => (
            <i key={index} />
          ))}
        </div>
      ) : nothing ? (
        <p className={styles.quiet} role="status">
          Nothing needs you right now.
        </p>
      ) : (
        <ActionList label="Needs you">
          {waiting.length ? (
            <ActionRow
              icon={<MessageCircleWarning size={20} />}
              tone="bad"
              title={`${waiting.length} ${waiting.length === 1 ? "lead is" : "leads are"} waiting for a first response`}
              note={`Longer than ${waited(sla?.settings.minutes ?? 0)}, your target`}
              href="/settings/lead-rules"
            />
          ) : null}
          {waiting.slice(0, SHOWN).map((lead) => (
            <ActionRow
              key={lead.leadId}
              title={displayName(lead.leadName)}
              note={`Waiting ${waited(lead.minutesLate)} · ${displayName(lead.seller)}`}
              href={leadLink(lead.leadId)}
            />
          ))}
          {unassigned ? (
            <ActionRow
              icon={<UserX size={20} />}
              tone="warn"
              title={`${unassigned} new ${unassigned === 1 ? "lead has" : "leads have"} no owner`}
              note="Give them to a seller, or let the lead rules decide"
              href="/leads?tab=all&stage=open&who=unassigned"
            />
          ) : null}
          {late ? (
            <ActionRow
              icon={<CalendarClock size={20} />}
              tone="warn"
              title={`${late} ${late === 1 ? "follow-up is" : "follow-ups are"} late`}
              note="Across the team; Sellers below shows whose"
              href="/leads?tab=all&stage=open"
            />
          ) : null}
        </ActionList>
      )}
    </section>
  );
}
