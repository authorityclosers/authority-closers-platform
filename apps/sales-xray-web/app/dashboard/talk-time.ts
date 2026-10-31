/**
 * Talk time as the phone's own call log measured it (owner via the orchestrator,
 * 31 Oct 2026: a call from the Call button posted the seller's time away from the
 * app, and Home said "Talk time 1 min" with no phone duration behind it). Time away
 * is never talk time: with only that, talk time says "—", never a plain number.
 */
export function talkOrDash<T>(
  seconds: number,
  estimated: number | undefined,
  format: (seconds: number) => T,
): T | "—" {
  return seconds <= 0 && (estimated ?? 0) > 0 ? "—" : format(seconds);
}
