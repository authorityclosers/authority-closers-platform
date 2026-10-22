"use client";

/**
 * "Call next": who is next on the desk, and one tap to call them (the ease-of-use wave,
 * 22 Oct 2026). One component, so the IA refresh can place it anywhere: after a save in
 * a lead today; Home and Chats next.
 */

import { Phone } from "lucide-react";

import { Button } from "../ui/kit";
import { whyLine } from "./desk-view";
import type { LeadDetail } from "./leads-client";
import styles from "./leads.module.css";

export function CallNext({
  lead,
  saved = false,
  onCall,
}: {
  /** The next lead on the desk; none: nobody is due now. */
  lead: LeadDetail | null;
  /** Just after a save in a lead: the line starts "Saved." */
  saved?: boolean;
  onCall: (leadId: string) => void;
}) {
  const first = saved ? "Saved. " : "";
  if (!lead)
    return (
      <div className={styles.nextUp} role="status">
        <span>{first}Nobody else is due now.</span>
      </div>
    );
  const name = lead.lead.name;
  return (
    <div className={styles.nextUp} role="status">
      <span>
        {first}Next up: <strong>{name}</strong>
        <small>{whyLine(lead.lead)}</small>
      </span>
      <Button variant="primary" onClick={() => onCall(lead.lead.lead_id)}>
        <Phone size={16} aria-hidden="true" />
        Call {name.split(" ")[0]}
      </Button>
    </div>
  );
}
