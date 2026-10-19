/**
 * Messenger and Instagram calls for the Sales Xray CRM (/v1/lead-desk). The
 * organisation connects its Facebook Pages and their Instagram accounts; replies
 * follow Meta's rules (24 hours after the person's last message; a person, never
 * an automation, may answer up to 7 days later with the Human Agent tag).
 */

import { waCall } from "./whatsapp-client";

export type SocialChannel = "messenger" | "instagram";

export type CommentRule = {
  on: boolean;
  keywords: string[];
  reply: string;
  publicReply?: string | null;
};
export type PageSettings = {
  messenger: boolean;
  instagram: boolean;
  humanAgent: boolean;
  firstReply: { on: boolean; text?: string | null };
  outOfHours: { on: boolean; text?: string | null };
  comments: CommentRule[];
};
export type SocialPage = {
  id: string;
  pageId: string;
  pageName: string;
  igUsername?: string | null;
  hasInstagram: boolean;
  settings: PageSettings;
};
export type MessagingStatus = {
  configured: boolean;
  accounts: SocialPage[];
  taken?: string[];
};
export type SocialMessage = {
  id: string;
  direction: "in" | "out";
  kind: string;
  text?: string | null;
  status: string;
  error?: string | null;
  auto?: string | null;
  humanAgent?: boolean;
  at: string;
  by?: string | null;
};
export type SocialThread = {
  accountId: string;
  channel: SocialChannel;
  place: string;
  messages: SocialMessage[];
  windowOpen: boolean;
  windowClosesAt?: string | null;
  humanAgent: boolean;
};
export type SocialConversation = {
  configured: boolean;
  connected: boolean;
  threads: SocialThread[];
};
export type SocialInboxThread = {
  leadId?: string | null;
  leadName: string;
  channel: SocialChannel;
  lastText?: string | null;
  lastAt: string;
  waiting: boolean;
  windowOpen: boolean;
};

export const CHANNEL_NAMES: Record<SocialChannel, string> = {
  messenger: "Messenger",
  instagram: "Instagram",
};

export const CONNECT_URL = "/v1/lead-desk/messaging/connect";

export function sendSocial(
  leadId: string,
  body: {
    channel: SocialChannel;
    accountId: string;
    text: string;
    humanAgent?: boolean;
  },
): Promise<SocialConversation> {
  return waCall<SocialConversation>(`/leads/${leadId}/social`, {
    method: "POST",
    body: JSON.stringify({ commandId: crypto.randomUUID(), ...body }),
  });
}

/** What the composer says about Meta's window for this conversation. */
export function socialWindowLine(
  thread: SocialThread,
  now: Date = new Date(),
): string {
  if (thread.windowOpen && thread.windowClosesAt) {
    const minutes = Math.max(
      0,
      Math.round(
        (new Date(thread.windowClosesAt).getTime() - now.getTime()) / 60000,
      ),
    );
    if (minutes < 60) return `You can reply for ${minutes} more min.`;
    const hours = Math.round(minutes / 60);
    return `You can reply for ${hours} more hour${hours === 1 ? "" : "s"}.`;
  }
  if (thread.humanAgent)
    return "More than 24 hours since their last message: you can still answer yourself within 7 days.";
  return "More than 24 hours since their last message. When they write again, you can reply.";
}

/** A message as the bubble shows it. */
export function socialText(message: SocialMessage): string {
  if (message.kind === "comment")
    return `Commented: ${message.text ?? "(comment removed)"}`;
  if (message.text) return message.text;
  if (message.kind === "story_reply") return "Replied to your story";
  if (message.kind === "story_mention") return "Mentioned you in their story";
  return "A photo, file or something Meta can't show here";
}

/** "price, site visit" ⇄ ["price", "site visit"] for the rule editor. */
export function keywordList(text: string): string[] {
  return text
    .split(",")
    .map((word) => word.trim())
    .filter(Boolean)
    .slice(0, 10);
}
