/**
 * The command bar's leads (phone QA, 1 Nov 2026, ph2-27): one row per lead, its
 * Call a small button at the row's end (a full-width "Call" row under each lead
 * was a fat-finger dial), six at most, then Show all over All Leads.
 */

import { Phone, Search, UserRound } from "lucide-react";

import type { Command } from "../ui/command-bar";
import type { LeadRow } from "./leads-client";

export const SEARCH_LEADS_SHOWN = 6;

export function leadSearchCommands(
  leads: readonly LeadRow[],
  text: string,
  act: {
    open: (leadId: string) => void;
    call: (row: LeadRow) => void;
    showAll: (words: string) => void;
  },
): Command[] {
  const words = text.trim();
  const rows: Command[] = leads.slice(0, SEARCH_LEADS_SHOWN).map((row) => ({
    id: `leads:open:${row.lead_id}`,
    group: "Leads",
    label: row.name,
    hint: [row.stage_label, row.city].filter(Boolean).join(" · "),
    icon: <UserRound size={16} aria-hidden="true" />,
    run: () => act.open(row.lead_id),
    ...(row.phone_last4
      ? {
          aside: {
            label: `Call ${row.name}, ends in ${row.phone_last4}`,
            icon: <Phone size={18} aria-hidden="true" />,
            run: () => act.call(row),
          },
        }
      : {}),
  }));
  if (leads.length <= SEARCH_LEADS_SHOWN) return rows;
  return [
    ...rows,
    {
      id: "leads:all",
      group: "Leads",
      label: "Show all leads",
      hint: `Every lead matching “${words}”`,
      icon: <Search size={16} aria-hidden="true" />,
      run: () => act.showAll(words),
    },
  ];
}
