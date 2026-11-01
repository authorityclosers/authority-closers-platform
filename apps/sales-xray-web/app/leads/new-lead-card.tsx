"use client";

/**
 * A new lead arrives (owner, 24 Oct 2026), the moment Leads hears of it (a
 * minute's read, or at once on the phone's alert). Only leads that came in
 * while the page was open: those already there when it opened, and those the
 * seller added themselves, never pop up. Later keeps the lead in To call,
 * where it already is.
 *
 * It is a one-line corner pill, "New enquiry · Asha · Meta" with Call now in
 * it and its X for Later, never a sheet over the list, the rows or the tab bar
 * (competitor teardown 12, 1 Nov 2026).
 */

import { useEffect, useRef, useState } from "react";

import { displayName } from "../display-name";
import { dismissNotice, notify } from "../notice-center";
import { sourceText } from "./desk-view";
import { LEAD_ADDED_EVENT, type HandedLead } from "./lead-handoff";
import type { LeadRow } from "./leads-client";

/** The corner card's id: one new-enquiry pill at a time. */
export const NEW_LEAD_NOTICE = "new-enquiry";

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
  // A Cold lead comes in a list: it never pops up (ph1-16, 1 Nov 2026).
  return rows.filter(
    (row) =>
      row.why_kind === "new" &&
      row.side !== "cold" &&
      row.owner_person_id === me &&
      !seen.has(row.lead_id) &&
      now - Date.parse(row.created_at) <= FRESH_MS,
  );
}

export type Arrival = {
  /** The first lead waiting, and how many. */
  lead: LeadRow | null;
  count: number;
  /** Every lead waiting, first come first. */
  leads: readonly LeadRow[];
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
    leads: waiting,
    putBy: () => setWaiting([]),
    know,
  };
}

/** "New enquiry · Asha Sample · Facebook ad", or "3 new enquiries · Asha Sample and 2 more". */
export function enquiryWords(lead: LeadRow, count: number): string {
  const name = displayName(lead.name);
  return count > 1
    ? `${count} new enquiries · ${name} and ${count - 1} more`
    : ["New enquiry", name, sourceText(lead)].filter(Boolean).join(" · ");
}

export function NewLeadCard({
  lead,
  count,
  open,
  onCall,
  onLater,
}: {
  lead: LeadRow | null;
  /** How many arrived; more than one says so. */
  count: number;
  open: boolean;
  onCall: (lead: LeadRow) => void;
  /** Kept for the page's call: WhatsApp stays on the lead's own row. */
  onMessage: (lead: LeadRow) => void;
  onLater: () => void;
}) {
  // The pill's buttons call the page's latest handlers, for the lead now shown.
  const latest = useRef({ lead, onCall, onLater });
  useEffect(() => {
    latest.current = { lead, onCall, onLater };
  });
  const title = open && lead ? enquiryWords(lead, count) : null;
  const callable = Boolean(lead?.phone_last4);
  useEffect(() => {
    if (!title) {
      dismissNotice(NEW_LEAD_NOTICE);
      return;
    }
    notify({
      id: NEW_LEAD_NOTICE,
      tone: "lead",
      title,
      action: callable
        ? {
            label: "Call now",
            icon: "none",
            run: () => {
              const now = latest.current;
              if (now.lead) now.onCall(now.lead);
            },
          }
        : undefined,
      dismissLabel: "Later",
      onDismiss: async () => latest.current.onLater(),
      pillAction: true,
      folded: true,
      timeout: 0,
    });
  }, [title, callable]);
  useEffect(() => () => dismissNotice(NEW_LEAD_NOTICE), []);
  return null;
}
