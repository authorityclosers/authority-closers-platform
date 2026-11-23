/**
 * The call this phone placed that still needs its answer (owner, 19 Nov 2026,
 * Wise Life: "After the call the pop-up doesn't ask; it should lock until
 * answered"). The phone app reports each call it placed when it ends; until
 * the seller saves how it went (outcome and next step) the app brings them
 * back to that lead's question, wherever they go (AfterCallGuard).
 *
 * Kept on this phone only, per account, ids and times only. A call older than
 * the after-call question's own freshness (FRESH_MS) no longer holds anyone,
 * and a call answered once is never asked again, even when the phone reports
 * it a second time (it does, once its recording is final).
 */

import { useEffect, useState } from "react";

import { FRESH_MS } from "./after-call";
import type { NativeCall } from "./native-phone";

const KEY = "sx-after-call-pending";
/** The lead the app last dialled, until the phone reports that call ended. */
const DIAL_KEY = "sx-after-call-dialled";
/** Answered calls remembered, so a second report of one never asks again. */
const KEEP_ANSWERED = 30;
export const PENDING_ANSWER_EVENT = "sx:after-call-pending";

export type PendingAnswer = {
  leadId: string;
  startedMs: number;
};

type Store = {
  account: string;
  pending: PendingAnswer | null;
  answered: string[];
};

/** This phone's signed-in seller in this workspace: whose answer is held. */
export function answerAccount(
  context:
    | { personId?: string | null; tenantId?: string | null }
    | null
    | undefined,
): string | null {
  return context?.personId && context.tenantId
    ? `${context.tenantId}:${context.personId}`
    : null;
}

const stamp = (call: PendingAnswer) => `${call.leadId}:${call.startedMs}`;

function read(account: string): Store {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) ?? "null") as Store | null;
    if (raw && raw.account === account) {
      const pending =
        raw.pending &&
        typeof raw.pending.leadId === "string" &&
        typeof raw.pending.startedMs === "number"
          ? raw.pending
          : null;
      return {
        account,
        pending,
        answered: Array.isArray(raw.answered)
          ? raw.answered.filter((item) => typeof item === "string")
          : [],
      };
    }
  } catch {
    // Storage blocked or unreadable: nothing is held.
  }
  return { account, pending: null, answered: [] };
}

function write(store: Store) {
  try {
    localStorage.setItem(KEY, JSON.stringify(store));
  } catch {
    // Storage blocked: the lead's own question still asks while it is open.
  }
  if (typeof window !== "undefined")
    window.dispatchEvent(new CustomEvent(PENDING_ANSWER_EVENT));
}

/**
 * Holds the seller to this call's answer: any call the phone placed that
 * ended, unless the phone knows it never connected (that one is logged as
 * missed by itself). Without call-history access the phone often can't tell
 * (no talk time), and those are asked too: the question has "Didn't get
 * through".
 */
export function rememberCallToAnswer(
  account: string | null,
  call: NativeCall,
  now = Date.now(),
): boolean {
  if (!account || !call.leadId || !call.endedMs || call.connected === false)
    return false;
  if (now - call.endedMs > FRESH_MS) return false;
  const store = read(account);
  const next = { leadId: call.leadId, startedMs: call.startedMs };
  if (store.answered.includes(stamp(next))) return false;
  if (
    store.pending?.leadId === next.leadId &&
    store.pending.startedMs === next.startedMs
  )
    return true;
  write({ ...store, pending: next });
  return true;
}

/** The call waiting for its answer on this phone, if it still counts. */
export function callToAnswer(
  account: string | null,
  now = Date.now(),
): PendingAnswer | null {
  if (!account) return null;
  const { pending } = read(account);
  if (!pending) return null;
  return now - pending.startedMs > FRESH_MS ? null : pending;
}

/** The lead's answer is saved: nothing holds the seller for it any more. */
export function answeredCallFor(account: string | null, leadId: string) {
  if (!account) return;
  const store = read(account);
  if (store.pending?.leadId !== leadId) return;
  write({
    account,
    pending: null,
    answered: [stamp(store.pending), ...store.answered].slice(0, KEEP_ANSWERED),
  });
}

/**
 * The held call's lead isn't on this seller's desk any more (a manager gave it
 * to someone else, or it was deleted): its question can never be answered
 * here, so nothing holds the seller for it (Wise Life, 23 Nov 2026: a lead moved
 * away minutes after its call locked the seller out of every screen). Kept as
 * answered, so the phone's second report of that call doesn't hold them again.
 */
export function releaseCallToAnswer(account: string | null, leadId: string) {
  answeredCallFor(account, leadId);
  forgetDial(leadId);
}

/** The held call, kept current as calls end and answers are saved. */
export function useCallToAnswer(account: string | null): PendingAnswer | null {
  const [held, setHeld] = useState<PendingAnswer | null>(null);
  useEffect(() => {
    const read = () => {
      const next = callToAnswer(account);
      setHeld((current) =>
        current?.leadId === next?.leadId &&
        current?.startedMs === next?.startedMs
          ? current
          : next,
      );
    };
    read();
    window.addEventListener(PENDING_ANSWER_EVENT, read);
    return () => window.removeEventListener(PENDING_ANSWER_EVENT, read);
  }, [account]);
  return held;
}

/**
 * The lead the app is dialling now. Android may close the app's page during a
 * long call, and then the phone's "call ended" never reaches it: on return the
 * guard asks the phone for this lead's last call instead.
 */
export function rememberDial(leadId: string, now = Date.now()) {
  try {
    localStorage.setItem(DIAL_KEY, JSON.stringify({ leadId, at: now }));
  } catch {
    // Storage blocked: the call-ended report still holds the seller.
  }
}

/** The lead dialled lately whose end isn't known yet, or null. */
export function dialledLead(now = Date.now()): string | null {
  try {
    const raw = JSON.parse(localStorage.getItem(DIAL_KEY) ?? "null") as {
      leadId?: unknown;
      at?: unknown;
    } | null;
    return raw &&
      typeof raw.leadId === "string" &&
      typeof raw.at === "number" &&
      now - raw.at <= FRESH_MS
      ? raw.leadId
      : null;
  } catch {
    return null;
  }
}

/** That call's end is known: nothing more to ask the phone about. */
export function forgetDial(leadId: string) {
  try {
    // Any age: an old dial of this lead is done with too.
    if (dialledLead(Number.NEGATIVE_INFINITY) === leadId)
      localStorage.removeItem(DIAL_KEY);
  } catch {
    // Storage blocked: nothing kept.
  }
}
