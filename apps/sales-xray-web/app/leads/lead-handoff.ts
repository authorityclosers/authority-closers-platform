/**
 * A lead to open on the Leads page, handed over from another page: one added
 * from the + sheet, or Home's "Call <name>". The page hands its id over here,
 * then moves to Leads. Leads already open takes it from the event; Leads that
 * opens next takes it once on arrival. Ids only, in memory: nothing reaches
 * the address bar or storage.
 */

export const LEAD_ADDED_EVENT = "sx:lead-added";

export type HandedLead = { leadId: string; call: boolean };

let waiting: HandedLead | null = null;

/** `call`: open it ready to call, as Start calling does. */
export function handOverLead(leadId: string, call = false) {
  waiting = { leadId, call };
  if (typeof window !== "undefined")
    window.dispatchEvent(
      new CustomEvent<HandedLead>(LEAD_ADDED_EVENT, { detail: waiting }),
    );
}

/** The lead waiting to open, once; null after it has been taken. */
export function takeHandedLead(): HandedLead | null {
  const handed = waiting;
  waiting = null;
  return handed;
}
