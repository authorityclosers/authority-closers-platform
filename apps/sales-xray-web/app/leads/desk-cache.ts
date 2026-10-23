/**
 * To call's last desk for each identity and pipeline, kept on the same
 * shelves as Home's and Calls' answers (calls-cache.ts: memory only, keyed by
 * person, session and workspace). A return to Leads paints it at once and
 * reads again quietly, so the tab never opens on a blank outline twice
 * (orchestrator, 23 Oct 2026: the owner wants the app to feel instant).
 */
import { cachedPanel, rememberPanel } from "../calls-cache";
import type { Desk } from "./leads-client";

const shelfOf = (pipeline: string | null) => `leads.desk:${pipeline ?? ""}`;

/** The desk this identity last read for this pipeline (null: all of them). */
export function cachedDesk(
  identity: string | null | undefined,
  pipeline: string | null,
): Desk | null {
  return cachedPanel<Desk>(identity, shelfOf(pipeline)) ?? null;
}

export function rememberDesk(
  identity: string | null | undefined,
  pipeline: string | null,
  desk: Desk,
) {
  rememberPanel(identity, shelfOf(pipeline), desk);
}
