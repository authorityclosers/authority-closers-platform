"use client";

/**
 * A new lead arrives (owner, 24 Oct 2026): one card with Call, WhatsApp and
 * Later, the moment Leads hears of it (a minute's read, or at once on the
 * phone's alert). Only leads that came in while the page was open: those
 * already there when it opened, and those the seller added themselves, never
 * pop up. Later keeps the lead in To call, where it already is.
 */

import { PhoneCall } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { ChannelMark } from "../chats/channel-mark";
import { displayName } from "../display-name";
import { ActionSheet } from "./action-sheet";
import { sourceText } from "./desk-view";
import { LEAD_ADDED_EVENT, type HandedLead } from "./lead-handoff";
import type { LeadRow } from "./leads-client";
import styles from "./leads.module.css";

/** How new a lead must be to pop up: a page that opens on a desk kept from
 *  hours ago never pops up what came in meanwhile. */
export const FRESH_MS = 15 * 60_000;

/** The seller's own new leads in `rows` not seen before, made in the last quarter
 *  hour; null `seen` is the first read, which only learns what is there. */
export function arrivals(
  seen: ReadonlySet<string> | null,
  rows: readonly LeadRow[],
  me: string,
  now: number = Date.now(),
): LeadRow[] {
  if (seen === null) return [];
  return rows.filter(
    (row) =>
      row.why_kind === "new" &&
      row.owner_person_id === me &&
      !seen.has(row.lead_id) &&
      now - Date.parse(row.created_at) <= FRESH_MS,
  );
}

export type Arrival = {
  /** The first lead waiting, and how many. */
  lead: LeadRow | null;
  count: number;
  /** Later: put them all by (they stay in To call). */
  putBy: () => void;
  /** A lead the page opened itself is known: it never pops up. */
  know: (leadId: string) => void;
};

/** The leads that just arrived for this seller, from each read of the desk. */
export function useArrival(
  rows: readonly LeadRow[] | null,
  me: string | null,
): Arrival {
  const seen = useRef<Set<string> | null>(null);
  const [waiting, setWaiting] = useState<LeadRow[]>([]);

  useEffect(() => {
    if (rows === null || me === null) return;
    const fresh = arrivals(seen.current, rows, me);
    const known = seen.current ?? new Set<string>();
    for (const row of rows) known.add(row.lead_id);
    seen.current = known;
    if (fresh.length)
      setWaiting((current) => [
        ...current,
        ...fresh.filter(
          (row) => !current.some((item) => item.lead_id === row.lead_id),
        ),
      ]);
  }, [rows, me]);

  const know = (leadId: string) => {
    (seen.current ??= new Set()).add(leadId);
    setWaiting((current) => current.filter((row) => row.lead_id !== leadId));
  };

  // A lead the seller added, or opened from Home, is theirs already: no card.
  useEffect(() => {
    const own = (event: Event) => {
      const leadId = (event as CustomEvent<HandedLead>).detail?.leadId;
      if (!leadId) return;
      (seen.current ??= new Set()).add(leadId);
      setWaiting((current) => current.filter((row) => row.lead_id !== leadId));
    };
    window.addEventListener(LEAD_ADDED_EVENT, own);
    return () => window.removeEventListener(LEAD_ADDED_EVENT, own);
  }, []);

  return {
    lead: waiting[0] ?? null,
    count: waiting.length,
    putBy: () => setWaiting([]),
    know,
  };
}

export function NewLeadCard({
  lead,
  count,
  open,
  onCall,
  onMessage,
  onLater,
}: {
  lead: LeadRow | null;
  /** How many arrived; more than one says so. */
  count: number;
  open: boolean;
  onCall: (lead: LeadRow) => void;
  onMessage: (lead: LeadRow) => void;
  onLater: () => void;
}) {
  const name = lead ? displayName(lead.name) : "";
  const about = lead
    ? [sourceText(lead), lead.interest, lead.city].filter(Boolean).join(" · ")
    : undefined;
  return (
    <ActionSheet
      open={open && !!lead}
      title={lead ? `New lead: ${name}` : "New lead"}
      sub={
        count > 1
          ? `${about ? `${about}. ` : ""}${count - 1} more waiting in To call.`
          : about
      }
      onClose={onLater}
    >
      {lead ? (
        <div className={styles.confirmCall}>
          <button
            type="button"
            className={styles.callBarButton}
            disabled={!lead.phone_last4}
            onClick={() => onCall(lead)}
          >
            <PhoneCall size={18} aria-hidden="true" />
            {`Call ${name.split(" ")[0]}`}
          </button>
          <div className={styles.newLeadMore}>
            <button
              type="button"
              className={styles.actionButton}
              disabled={!lead.phone_last4}
              onClick={() => onMessage(lead)}
            >
              <ChannelMark channel="whatsapp" size={18} />
              WhatsApp
            </button>
            <button
              type="button"
              className={styles.actionButton}
              onClick={onLater}
            >
              Later
            </button>
          </div>
        </div>
      ) : null}
    </ActionSheet>
  );
}
