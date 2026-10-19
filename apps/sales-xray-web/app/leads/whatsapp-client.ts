/**
 * WhatsApp and first-response SLA calls for the Sales Xray CRM (/v1/lead-desk).
 * The organisation connects its own number; messages follow WhatsApp's rules
 * (free text for 24 hours after the person's last message, a template after).
 */

import { LeadsError } from "./leads-client";

const BASE = "/v1/lead-desk";

export type AutoReplies = {
  firstReply: {
    on: boolean;
    template?: string | null;
    language?: string | null;
    consentQuestion?: string | null;
  };
  outOfHours: { on: boolean; text?: string | null };
};
export type WaNumber = {
  id: string;
  displayNumber: string;
  verifiedName?: string | null;
  quality?: string | null;
  autoReplies: AutoReplies;
};
export type WaTemplate = {
  name: string;
  language: string;
  category: string;
  status: string;
  text: string;
  parts: number;
  rejectedReason?: string | null;
};
export type WaStatus = {
  configured: boolean;
  numbers: WaNumber[];
  templates: WaTemplate[];
};
export type WaMessage = {
  id: string;
  direction: "in" | "out";
  kind: string;
  text?: string | null;
  template?: string | null;
  status: string;
  error?: string | null;
  auto?: string | null;
  at: string;
  by?: string | null;
};
export type WaConversation = {
  configured: boolean;
  connected: boolean;
  numbers: WaNumber[];
  messages: WaMessage[];
  windowOpen: boolean;
  windowClosesAt?: string | null;
  optedIn: boolean;
  optInHow?: string | null;
  templates: WaTemplate[];
};
export type WaThread = {
  leadId?: string | null;
  leadName: string;
  lastText?: string | null;
  lastAt: string;
  waiting: boolean;
  windowOpen: boolean;
};
export type Sla = {
  on: boolean;
  minutes: number;
  alertManagers: boolean;
  targets: number[];
};
export type SellerSla = {
  personId?: string | null;
  name: string;
  leads: number;
  inTime: number;
  breached: number;
  waiting: number;
  medianMinutes?: number | null;
};
export type SlaReport = {
  settings: Sla;
  start: string;
  end: string;
  sellers: SellerSla[];
};

export async function waCall<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    credentials: "same-origin",
    cache: "no-store",
    ...init,
    headers: {
      accept: "application/json",
      ...(init.body ? { "content-type": "application/json" } : {}),
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    let detail: string | undefined;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* no body */
    }
    throw new LeadsError(
      detail ?? "That didn't work. Try again.",
      response.status,
    );
  }
  return (await response.json()) as T;
}

export const START_URL = `${BASE}/whatsapp/start`;

export function sendWhatsApp(
  leadId: string,
  body: {
    text?: string;
    template?: string;
    language?: string;
    values?: string[];
  },
): Promise<WaConversation> {
  return waCall<WaConversation>(`/leads/${leadId}/whatsapp`, {
    method: "POST",
    body: JSON.stringify({ commandId: crypto.randomUUID(), ...body }),
  });
}

/** The body of a template with its parts filled in, as the person reads it. */
export function filled(text: string, values: string[]): string {
  return text.replace(/\{\{(\d{1,2})\}\}/g, (whole, n: string) => {
    const value = values[Number(n) - 1];
    return value ? value : whole;
  });
}

/** "Free replies for 3 more hours" or the template rule, for the composer. */
export function windowLine(
  chat: WaConversation,
  now: Date = new Date(),
): string {
  if (!chat.windowOpen || !chat.windowClosesAt)
    return "More than 24 hours since their last message: send an approved template.";
  const minutes = Math.max(
    0,
    Math.round(
      (new Date(chat.windowClosesAt).getTime() - now.getTime()) / 60000,
    ),
  );
  if (minutes < 60) return `You can reply freely for ${minutes} more min.`;
  const hours = Math.round(minutes / 60);
  return `You can reply freely for ${hours} more hour${hours === 1 ? "" : "s"}.`;
}

/** In time as a share of the leads that have had their answer or ran out of time. */
export function inTimeShare(seller: SellerSla): string {
  const settled = seller.inTime + seller.breached;
  if (!settled) return "–";
  return `${Math.round((seller.inTime / settled) * 100)}%`;
}
