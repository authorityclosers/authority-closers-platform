/**
 * A lead to open on the Leads page, handed over from another page: one added
 * from the + sheet, Home's "Call <name>", or a call on Calls. The page hands
 * its id over here, then moves to Leads. Leads already open takes it from the
 * event; Leads that opens next takes it once on arrival. Ids only, in memory:
 * nothing reaches the address bar or storage.
 */

export const LEAD_ADDED_EVENT = "sx:lead-added";

/** `at`: the line of its history to show, such as the call tapped on Calls;
 *  `round`: start a calling round at this lead (its card first). */
export type HandedLead = {
  leadId: string;
  call: boolean;
  at?: string | null;
  round?: boolean;
};

let waiting: HandedLead | null = null;

/** `call`: open it ready to call, as Start calling does. */
export function handOverLead(
  leadId: string,
  call = false,
  at: string | null = null,
) {
  waiting = at ? { leadId, call, at } : { leadId, call };
  if (typeof window !== "undefined")
    window.dispatchEvent(
      new CustomEvent<HandedLead>(LEAD_ADDED_EVENT, { detail: waiting }),
    );
}

/**
 * Start a calling round on Leads at this lead, as Leads' own Start Cold
 * Calling does: its card first, with Call and Skip, and nothing dials until
 * Call (phone personas ph2-33, 1 Nov 2026: Home's Start cold calling opened
 * the dialer at once, and backing out left a phantom call).
 */
export function handOverRound(leadId: string) {
  waiting = { leadId, call: false, round: true };
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
