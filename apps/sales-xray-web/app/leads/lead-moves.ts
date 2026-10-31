/**
 * A lead the person has just moved (a call's outcome, a new stage) leaves the
 * list they are working in at once and shows under its new stage, before the
 * next read confirms it (owner, 30 Oct 2026: after a disposition the next lead
 * is on top; nobody scrolls for the next call). The lists are filters on the
 * lead's stage, so this holds whatever stages a business uses. A row the
 * server sends at the move's revision or later is the server's to show.
 */
import { useSyncExternalStore } from "react";

import { onWorkspaceChange } from "../workspace-change";
import type { Desk, LeadRow, ListMore } from "./leads-client";

export type Moves = ReadonlyMap<string, { row: LeadRow; at: number }>;
type Follower = (row: LeadRow, moves: Moves) => void;

const NONE: Moves = new Map();
const KEEP = 50;
let moves: Moves = NONE;
const listeners = new Set<() => void>();
const followers = new Set<Follower>();
const publish = (next: Moves) => {
  moves = next;
  for (const listener of listeners) listener();
};
onWorkspaceChange(() => publish(NONE));

/** Won, Lost and Junk close a lead; every other stage keeps it open. */
const CLOSED: ReadonlySet<string> = new Set(["won", "lost", "junk"]);

/** All leads ("open") holds every open lead; a stage's list, that stage. */
export function inStageList(
  row: Pick<LeadRow, "stage">,
  list: string,
): boolean {
  if (list === "all") return true;
  return list === "open" ? !CLOSED.has(row.stage) : row.stage === list;
}

/** Whether a lead still fits a work view, its follow-up split and its stage
 *  pick (Dipak's handoff, items 56-73): To Call is open and due before today
 *  ends, or new and never called; Follow-ups has a planned contact. */
export function inWorkView(
  row: Pick<LeadRow, "stage" | "step" | "next_action_at">,
  more: ListMore | null | undefined,
  now = Date.now(),
): boolean {
  if (!more) return true;
  if (more.step && row.step && row.step !== more.step) return false;
  const at = row.next_action_at ? Date.parse(row.next_action_at) : null;
  const start = new Date(now).setHours(0, 0, 0, 0);
  const end = start + 24 * 60 * 60 * 1000;
  if (more.view === "to_call") {
    if (CLOSED.has(row.stage)) return false;
    if (at === null ? row.stage !== "new" : at >= end) return false;
  }
  if (
    more.view === "follow_ups" &&
    (at === null || (row.stage !== "follow_up" && row.stage !== "interested"))
  )
    return false;
  if (!more.when) return true;
  if (at === null) return false;
  if (more.when === "overdue") return at < start;
  if (more.when === "upcoming") return at >= end;
  return at >= start && at < end;
}

/** What a list knows about itself to place the person's moves in it. */
export type ListFit = {
  /** Whether a lead belongs in this list; null: not a stage list. */
  belongs: ((row: LeadRow) => boolean) | null;
  /** A moved lead may join its top (no search or other filters on). */
  join: boolean;
  /** When its rows were asked for (0: kept on the device). */
  readAt: number;
};

/** A list's rows with the person's moves applied. */
export function withMoves(
  rows: LeadRow[],
  current: Moves,
  fit: ListFit,
): LeadRow[] {
  if (!current.size) return rows;
  const seen = new Set<string>();
  let changed = false;
  const kept: LeadRow[] = [];
  for (const row of rows) {
    seen.add(row.lead_id);
    const move = current.get(row.lead_id);
    if (!move || row.revision >= move.row.revision) kept.push(row);
    else {
      changed = true;
      if (!fit.belongs || fit.belongs(move.row)) kept.push(move.row);
    }
  }
  const { belongs } = fit;
  const joined =
    belongs && fit.join
      ? [...current.values()]
          .filter(
            (move) =>
              move.at > fit.readAt &&
              !seen.has(move.row.lead_id) &&
              belongs(move.row),
          )
          .sort((a, b) => b.at - a.at)
          .map((move) => move.row)
      : [];
  if (!changed && !joined.length) return rows;
  return [...joined, ...kept];
}

/** To call without the leads the person has just worked. */
export function deskWithMoves(desk: Desk, current: Moves): Desk {
  if (!current.size) return desk;
  const fresh = (row: LeadRow) => {
    const move = current.get(row.lead_id);
    return !move || row.revision >= move.row.revision;
  };
  const queue = desk.queue.filter(fresh);
  const upcoming = desk.upcoming?.filter(fresh);
  const callBack = desk.call_back?.filter(fresh);
  if (
    queue.length === desk.queue.length &&
    upcoming?.length === desk.upcoming?.length &&
    callBack?.length === desk.call_back?.length
  )
    return desk;
  return { ...desk, queue, upcoming, call_back: callBack };
}

/** The person moved a lead: every list and To call follow at once. */
export function noteLeadMoved(row: LeadRow) {
  const next = new Map(moves);
  next.delete(row.lead_id);
  next.set(row.lead_id, { row, at: Date.now() });
  while (next.size > KEEP) next.delete(next.keys().next().value!);
  publish(next);
  for (const follow of followers) follow(row, next);
}

/** What else keeps leads (list-cache.ts) follows each move too. */
export function onLeadMoved(follow: Follower): () => void {
  followers.add(follow);
  return () => {
    followers.delete(follow);
  };
}

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

/** The person's moves so far on this page. */
export function useLeadMoves(): Moves {
  return useSyncExternalStore(
    subscribe,
    () => moves,
    () => NONE,
  );
}
