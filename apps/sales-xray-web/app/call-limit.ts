/**
 * The longest call Sales X-Ray analyses, on every screen (owner, 23 Oct 2026: "Call
 * length limit: 120 minutes everywhere"). The analysis pipeline handles one hour today,
 * so this is 60 until that work lands, and then changes here, once, with the server's
 * twin (conversation_intelligence/limits.py CALL_LIMIT_SECONDS).
 */
export const CALL_LIMIT_MINUTES = 60;
export const CALL_LIMIT_SECONDS = CALL_LIMIT_MINUTES * 60;

/** A plan's stated longest call, as far as Sales X-Ray analyses one today. */
export const callLimitMinutes = (planMinutes: number | null | undefined) =>
  Math.min(planMinutes ?? CALL_LIMIT_MINUTES, CALL_LIMIT_MINUTES);
