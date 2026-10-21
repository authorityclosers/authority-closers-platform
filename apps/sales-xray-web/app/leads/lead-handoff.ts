/**
 * A lead added from the + sheet (any page) opens on the Leads page: the shell
 * hands its id over here, then moves to Leads. Leads already open takes it
 * from the event; Leads that opens next takes it once on arrival.
 * Ids only, in memory: nothing reaches the address bar or storage.
 */

export const LEAD_ADDED_EVENT = "sx:lead-added";

let waiting: string | null = null;

export function handOverLead(leadId: string) {
  waiting = leadId;
  if (typeof window !== "undefined")
    window.dispatchEvent(
      new CustomEvent<{ leadId: string }>(LEAD_ADDED_EVENT, {
        detail: { leadId },
      }),
    );
}

/** The lead waiting to open, once; null after it has been taken. */
export function takeHandedLead(): string | null {
  const leadId = waiting;
  waiting = null;
  return leadId;
}
