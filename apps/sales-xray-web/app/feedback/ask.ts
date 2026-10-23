/**
 * Ask for feedback after a key moment: one line where the moment happens,
 *
 *   askFeedback("call_outcome");
 *   askFeedback("plan_purchase", { subject: orderId });
 *
 * The prompt mounted in the app frame decides whether to ask at all (rules.ts),
 * waits until no sheet, dialog or call is in the way, and never interrupts.
 * Outside the frame nothing listens, and nothing happens.
 */

import type { Moment } from "./feedback-client";

export const ASK_FEEDBACK_EVENT = "sales-xray:ask-feedback";

export type AskDetail = Readonly<{
  moment: Moment;
  /** One thing it is about (an update key, an order), asked about once. */
  subject?: string;
}>;

export function askFeedback(
  moment: Moment,
  options: { subject?: string } = {},
): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent<AskDetail>(ASK_FEEDBACK_EVENT, {
      detail: { moment, subject: options.subject },
    }),
  );
}
