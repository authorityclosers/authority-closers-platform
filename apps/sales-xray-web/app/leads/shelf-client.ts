/**
 * Archived and the Bin (owner's M3-A, 17 Nov 2026): the two lists the shelf
 * API keeps (`GET /leads?shelf=archived|bin`), and their Restore through bulk
 * jobs, so one tap or "Restore 12" is one job with its Undo.
 */

import {
  commandId,
  deskRequest,
  type BulkJob,
  type LeadPage,
} from "./leads-client";
import { runWithUndo } from "./manage-bar";

export type Shelf = "archived" | "bin";

/** Days a lead stays in the Bin before it is deleted for good (shelf.py). */
export const BIN_DAYS = 30;

export function readShelf(
  shelf: Shelf,
  offset = 0,
  signal?: AbortSignal,
): Promise<LeadPage> {
  const params = new URLSearchParams({ scope: "team", shelf });
  if (offset) params.set("offset", String(offset));
  return deskRequest<LeadPage>(`/leads?${params}`, { signal });
}

/** Bring these leads back to Leads, as one bulk job (its Undo puts them back). */
export function restoreShelved(
  shelf: Shelf,
  leadIds: string[],
  command = commandId(),
): Promise<BulkJob> {
  return runWithUndo(
    {
      lead_ids: leadIds,
      action: shelf === "bin" ? "restore_bin" : "restore_archive",
    },
    command,
  );
}

/** The day a lead in the Bin is deleted for good. */
export function purgeDay(binnedAt: string): Date {
  return new Date(Date.parse(binnedAt) + BIN_DAYS * 86_400_000);
}

export function dayText(at: Date): string {
  return at.toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

/** The words under a row: when it was archived, or when the Bin deletes it. */
export function shelfNote(
  shelf: Shelf,
  lead: { archived_at?: string | null; binned_at?: string | null },
): string {
  if (shelf === "bin")
    return lead.binned_at
      ? `Deleted for good on ${dayText(purgeDay(lead.binned_at))}`
      : "In the Bin";
  return lead.archived_at
    ? `Archived on ${dayText(new Date(lead.archived_at))}`
    : "Archived";
}
