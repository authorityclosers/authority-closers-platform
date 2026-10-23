/**
 * The longest call Sales X-Ray analyses, on every screen (owner, 23 Oct 2026: "Call
 * length limit: 120 minutes everywhere"): the upload page, Help and every plan card.
 * The server's twin is conversation_intelligence/limits.py CALL_LIMIT_SECONDS, which also
 * caps every plan and the trial; the analysis pipeline handles two hours. A plan row's own
 * stored longest call (90 minutes for Personal and Organisation in the 2 Oct catalogue) is
 * superseded by this one limit, so plan cards show this.
 */
export const CALL_LIMIT_MINUTES = 120;
export const CALL_LIMIT_SECONDS = CALL_LIMIT_MINUTES * 60;
