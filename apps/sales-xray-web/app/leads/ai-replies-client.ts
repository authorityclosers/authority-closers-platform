/**
 * AI replies for the Sales Xray CRM (/v1/lead-desk/ai-replies): per organisation off,
 * suggest (a seller reviews each draft and taps send) or auto; answers only from the
 * organisation's own profile, and hands to a person on complaints, price talk,
 * uncertainty or a request for a person.
 */

import { waCall } from "./whatsapp-client";

export type AiMode = "off" | "suggest" | "auto";
export type AiChannel = "whatsapp" | "messenger" | "instagram";
export type Faq = { question: string; answer: string };
export type AiSettings = {
  mode: AiMode;
  channels: AiChannel[];
  quotePrices: boolean;
  businessName: string;
  about: string;
  offerings: string;
  faqs: Faq[];
  notes: string;
  ready: boolean;
  /** Sales Xray's AI is switched on for messages (in Admin, per environment). */
  available: boolean;
  /** Paused for now: no drafts until Sales Xray resumes them. */
  paused?: boolean;
};
export type AiDraftStatus =
  | "queued"
  | "drafted"
  | "handoff"
  | "paused"
  | "failed";
export type AiDraft = {
  replyId?: string | null;
  /** Older answers had no status: a draft or a hand-off at once. */
  status?: AiDraftStatus;
  draft?: string | null;
  handoff: boolean;
  reason?: string | null;
  words: string;
};
export type AiHandoff = { channel: AiChannel; reason: string; at: string };
export type AiLeadState = {
  channels: AiChannel[];
  mode: AiMode;
  ready: boolean;
  /** Sales Xray's AI is switched on for messages (in Admin, per environment). */
  available: boolean;
  /** Paused for now: no drafts until Sales Xray resumes them. */
  paused?: boolean;
  handoffs: AiHandoff[];
};

/** Why a person should answer, in the seller's words. */
export const HANDOFF_WORDS: Record<string, string> = {
  human: "They asked for a person.",
  complaint: "It sounds like a complaint.",
  price: "They're asking about price.",
  discount: "They want a better price.",
  unsure: "The answer isn't in your business profile.",
  off_topic: "It isn't about your business.",
  opt_out: "They asked to stop messages. Nothing automatic goes to them now.",
  not_text: "They sent something other than words.",
  window: "It's more than 24 hours since their last message.",
  no_profile:
    "Add your business profile in Settings → Integrations → AI replies.",
  blocked_reply:
    "The draft said something your profile doesn't, so it wasn't used.",
  budget: "AI replies are paused for now.",
  off: "AI replies are switched off for now.",
  failed: "The AI couldn't answer just now.",
};

export function draftReply(
  leadId: string,
  body: { channel: AiChannel; accountId?: string | null },
): Promise<AiDraft> {
  return waCall<AiDraft>(`/leads/${leadId}/ai-draft`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/** "Try it": the reply the AI would draft for a sample message (nothing is sent). */
export function tryReply(body: {
  message: string;
  channel?: AiChannel;
}): Promise<AiDraft> {
  return waCall<AiDraft>("/ai-replies/try", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function tryStatus(replyId: string): Promise<AiDraft> {
  return waCall<AiDraft>(`/ai-replies/try/${replyId}`);
}

/** Whether a queued draft is ready yet. */
export function draftStatus(leadId: string, replyId: string): Promise<AiDraft> {
  return waCall<AiDraft>(`/leads/${leadId}/ai-draft/${replyId}`);
}

export function leadAi(leadId: string): Promise<AiLeadState> {
  return waCall<AiLeadState>(`/leads/${leadId}/ai`);
}
