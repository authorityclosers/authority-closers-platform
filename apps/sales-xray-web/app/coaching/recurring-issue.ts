/**
 * For the Report (Strike B): does this call's main issue come up across the
 * rep's calls? One quiet line there ("This issue may be part of a recurring
 * pattern → View Coaching"), never counts or history (spec "What should not
 * live in Report"). Reads My coaching once per account session and minute;
 * null whenever it can't be said, so the Report shows nothing.
 */
import { fetchCoaching, type Coaching } from "./coaching-client";

export type RecurringIssue = { recurring: boolean; href: string };
export type CoachingIdentity = {
  personId: string;
  tenantId: string;
  sessionId?: string | null;
};

const TTL_MS = 60_000;
const reads = new Map<string, { at: number; read: Promise<Coaching | null> }>();

function myCoaching(identity: CoachingIdentity): Promise<Coaching | null> {
  const key = `${identity.personId}:${identity.tenantId}:${identity.sessionId ?? ""}`;
  const cached = reads.get(key);
  if (cached && Date.now() - cached.at < TTL_MS) return cached.read;
  // One shared read: a caller leaving early never cancels it for the others.
  const read = fetchCoaching(AbortSignal.timeout(15_000))
    .then((coaching) =>
      coaching.person_id === identity.personId &&
      coaching.tenant_id === identity.tenantId
        ? coaching
        : null,
    )
    .catch(() => {
      // A failed read is not kept: the next Report asks again.
      if (reads.get(key)?.read === read) reads.delete(key);
      return null;
    });
  reads.clear(); // Only the current account's read is ever kept.
  reads.set(key, { at: Date.now(), read });
  return read;
}

export async function recurringIssue(
  callId: string,
  identity: CoachingIdentity,
  signal?: AbortSignal,
): Promise<RecurringIssue | null> {
  if (signal?.aborted) return null;
  let leave = () => {};
  const abandoned = new Promise<null>((resolve) => {
    leave = () => resolve(null);
    signal?.addEventListener("abort", leave, { once: true });
  });
  const coaching = await Promise.race([myCoaching(identity), abandoned]);
  signal?.removeEventListener("abort", leave);
  if (!coaching || signal?.aborted) return null;
  const call = coaching.calls?.find((row) => row.submission_id === callId);
  if (call?.recurring == null) return null;
  return { recurring: call.recurring, href: "/coaching" };
}

/** Tests only: forget the shared read. */
export function resetRecurringIssue() {
  reads.clear();
}
