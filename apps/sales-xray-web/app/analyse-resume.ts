/**
 * Owner 18 Oct: "Analyse my call" that first opens sign-in or the account
 * details step continues by itself afterwards, with the agree box still
 * ticked. The upload form unmounts while that step shows, so the click is
 * kept here, in memory only, for the selected file's intent and the exact
 * policy the person agreed to. A reload, another file or a newer policy
 * forgets it, and the person ticks and taps again.
 */

const KEEP_MS = 15 * 60_000;

type Pending = Readonly<{ intentId: string; policySha: string; at: number }>;

let pending: Pending | null = null;

/** Remember an Analyse click that had to stop for account access. */
export function rememberAnalyseClick(
  intentId: string,
  policySha: string,
  now = Date.now(),
) {
  pending = intentId && policySha ? { intentId, policySha, at: now } : null;
}

/** The agreed policy, when this intent's click is still waiting to continue. */
export function pendingAnalyseClick(
  intentId: string | null | undefined,
  now = Date.now(),
): string | null {
  if (!pending || !intentId || pending.intentId !== intentId) return null;
  if (now - pending.at > KEEP_MS) {
    pending = null;
    return null;
  }
  return pending.policySha;
}

/** The click continued (or was abandoned): never replay it twice. */
export function forgetAnalyseClick() {
  pending = null;
}
