/**
 * A calling round's controls (competitor teardown 2, 1 Nov 2026; Close's
 * Power Dialer, HubSpot's task queue): the start button carries the count,
 * the card says where the round is ("12 of 900"), Skip sends a lead to the
 * end of the round, closing the round pauses it (Continue or Start from top
 * on the next start, Continue passing over leads tried in the last hour), and
 * the end says what the round did. The round never moves while the after-call
 * answer is open: only Save, Skip or "I didn't call" move it.
 */

/** The desk's numbers for today that a round's end compares. */
export type RoundNumbers = {
  calls: number;
  connected: number;
  talk_seconds: number;
};

/** A round closed before its end, kept to continue (this tab, this side). */
export type PausedRound = {
  side: string;
  served: string[];
  skipped: string[];
  at: number;
  start: RoundNumbers | null;
};

/** A running round's bookkeeping: whether one runs, the leads skipped to its
 *  end and those already offered again, the leads Continue passes over, the
 *  desk's numbers at its start, and new enquiries to call first. */
export type RoundBook = {
  on: boolean;
  skipped: string[];
  again: string[];
  passOver: string[];
  from: RoundNumbers | null;
  ahead: string[];
};

export const NO_ROUND: RoundBook = {
  on: false,
  skipped: [],
  again: [],
  passOver: [],
  from: null,
  ahead: [],
};

/** How long a lead counts as just tried: Continue passes over it. */
export const RECENT_MS = 60 * 60_000;
/** A paused round older than this starts again from the top. */
export const PAUSE_KEEP_MS = 12 * 60 * 60_000;

/**
 * The round's next lead: a new enquiry that came in during the round first,
 * then the list's order, past the leads already offered and those tried in
 * the last hour; once those run out, the skipped leads, first skipped first.
 * Null: the round is done.
 */
export function nextInRound({
  ahead = [],
  order,
  served,
  skipped,
  recent = new Set<string>(),
}: {
  ahead?: readonly string[];
  order: readonly string[];
  served: ReadonlySet<string>;
  skipped: readonly string[];
  recent?: ReadonlySet<string>;
}): { next: string | null; again: boolean } {
  const fresh = [...ahead, ...order].find(
    (id) => !served.has(id) && !recent.has(id),
  );
  if (fresh) return { next: fresh, again: false };
  return { next: skipped[0] ?? null, again: skipped.length > 0 };
}

/** What the round did, from the desk's numbers at its start and now. */
export function roundDone(
  start: RoundNumbers | null,
  now: RoundNumbers | null,
): { tried: number; talked: number; minutes: number } | null {
  if (!start || !now) return null;
  return {
    tried: Math.max(0, now.calls - start.calls),
    talked: Math.max(0, now.connected - start.connected),
    minutes: Math.round(
      Math.max(0, now.talk_seconds - start.talk_seconds) / 60,
    ),
  };
}

const pausedKey = (person: string) => `sx:call-round:${person}`;

/** Keep a paused round for this tab, stamped now (private browsing keeps
 *  nothing). */
export function keepPaused(
  person: string,
  round: Omit<PausedRound, "at"> | null,
  at: number = Date.now(),
): void {
  try {
    if (round)
      window.sessionStorage.setItem(
        pausedKey(person),
        JSON.stringify({ ...round, at }),
      );
    else window.sessionStorage.removeItem(pausedKey(person));
  } catch {
    // Nothing kept: the next start begins at the top.
  }
}

/** The paused round on this side, if one is recent enough to continue. */
export function readPaused(
  person: string,
  side: string,
  now: number = Date.now(),
): PausedRound | null {
  try {
    const raw = window.sessionStorage.getItem(pausedKey(person));
    if (!raw) return null;
    const round = JSON.parse(raw) as PausedRound;
    return round.side === side &&
      Array.isArray(round.served) &&
      round.served.length > 0 &&
      now - round.at <= PAUSE_KEEP_MS
      ? round
      : null;
  } catch {
    return null;
  }
}

/** The leads tried in the last hour, from the list's rows. */
export function triedLately(
  rows: readonly { lead_id: string; last_contact_at?: string | null }[],
  now: number = Date.now(),
): string[] {
  return rows
    .filter((row) => {
      const at = row.last_contact_at ? Date.parse(row.last_contact_at) : NaN;
      return !Number.isNaN(at) && now - at <= RECENT_MS;
    })
    .map((row) => row.lead_id);
}
